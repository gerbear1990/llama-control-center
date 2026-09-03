// Chat panel.

import { profileLabel, serverRunningForMode } from './profiles.js';
import { selectedMode } from './parameters.js';
import { $, escapeHtml } from '../util.js';
import { state } from '../state.js';
import { toast, withBusy } from '../feedback.js';
import { chatEmptyCopy, emptyStateHtml } from '../copy.js';
import { api } from '../api.js';

export const CHAT_HISTORY_KEY = 'lcc-chat-history';

export const CHAT_HISTORY_LIMIT = 50;

export function persistChatHistory() {
  try {
    const slim = {};
    Object.entries(state.chatHistory || {}).forEach(([mode, entries]) => {
      if (!Array.isArray(entries) || !entries.length) return;
      slim[mode] = entries.slice(-CHAT_HISTORY_LIMIT).map((entry) => ({
        role: entry.role === 'assistant' ? 'assistant' : 'user',
        content: String(entry.content || ''),
      }));
    });
    localStorage.setItem(CHAT_HISTORY_KEY, JSON.stringify(slim));
  } catch { /* private mode or quota */ }
}

export function restoreChatHistory() {
  try {
    const raw = JSON.parse(localStorage.getItem(CHAT_HISTORY_KEY));
    if (raw && typeof raw === 'object' && !Array.isArray(raw)) state.chatHistory = raw;
  } catch { /* malformed entry: start clean */ }
}

export async function sendTestPrompt() {
  const mode = selectedMode();
  if (!mode) {
    toast('Select a profile first');
    return;
  }
  if (!serverRunningForMode(mode)) {
    toast(`Start the server for "${profileLabel(mode)}" first`);
    return;
  }
  const input = $('#test-prompt-input');
  const prompt = (input.value || '').trim();
  if (!prompt) {
    toast('Enter a message to send');
    return;
  }

  // Maintain history for this mode
  if (!state.chatHistory[mode]) state.chatHistory[mode] = [];
  const history = state.chatHistory[mode];

  // Append user message. One entry appended, not a whole transcript rebuilt:
  // the log is a live region, so only the new line should be announced.
  history.push({ role: 'user', content: prompt });
  persistChatHistory();
  appendChatEntry(mode, { role: 'user', content: prompt });

  input.value = '';

  await withBusy($('#test-prompt-send'), async () => {
    try {
      // Send full history so backend can do proper multi-turn
      const result = await api('/api/servers/test-prompt', {
        method: 'POST',
        body: JSON.stringify({
          mode,
          messages: history,           // full conversation
          max_tokens: 512,
        }),
      });

      if (result.success && result.reply) {
        history.push({ role: 'assistant', content: result.reply });
        persistChatHistory();
        appendChatEntry(mode, { role: 'assistant', content: result.reply });

        // Show last-turn stats
        const meta = $('#test-prompt-meta');
        if (meta) {
          meta.hidden = false;
          meta.textContent = `${result.tokens_per_second || '?'} tok/s · ${result.completion_tokens || '?'} tokens · ${result.elapsed_seconds || '?'}s`;
        }
      } else {
        rollbackChatSend(mode, history, input, prompt);
        toast(result.error || 'Chat failed');
      }
    } catch (error) {
      rollbackChatSend(mode, history, input, prompt);
      toast(`Chat error: ${error.message}`);
    }
  });
}

// A failed send must not eat what the user typed: drop the optimistic history
// entry and put the message back in the box, ready to retry. If they already
// started typing something else while waiting, that draft wins.
export function rollbackChatSend(mode, history, input, prompt) {
  history.pop();
  persistChatHistory();
  const container = $('#chat-log');
  // Drop just the optimistic line rather than repainting (and re-announcing)
  // the transcript around it.
  container?.querySelector('.chat-entry:last-child')?.remove();
  if (!(state.chatHistory[mode] || []).length) renderChatLog(mode);
  if (input && !input.value.trim()) {
    input.value = prompt;
    input.focus();
  }
}

// Transcript entries are terminal lines, not bubbles: a role gutter, the text
// in mono, a hairline between turns. Markup is built once here so the
// incremental and full-rebuild paths cannot drift apart.
export function chatEntryHtml(msg) {
  const isUser = msg.role === 'user';
  return `
    <div class="chat-entry ${isUser ? 'user' : 'assistant'}">
      <span class="chat-role">${isUser ? 'you' : 'model'}<span aria-hidden="true"> ›</span></span>
      <span class="chat-text">${escapeHtml(msg.content)}</span>
    </div>`;
}

export function appendChatEntry(mode, msg) {
  const container = $('#chat-log');
  if (!container) return;
  if (!container.querySelector('.chat-entry')) container.innerHTML = '';
  container.insertAdjacentHTML('beforeend', chatEntryHtml(msg));
  container.scrollTop = container.scrollHeight;
}

// Full rebuild — only when the transcript being shown changes wholesale
// (profile switch, Clear). The live region is muted across the swap so a
// switch does not read the entire history back out.
export function renderChatLog(mode) {
  const container = $('#chat-log');
  if (!container) return;

  const history = state.chatHistory[mode] || [];
  const liveServer = serverRunningForMode(mode);
  container.setAttribute('aria-live', 'off');
  container.innerHTML = history.length
    ? history.map(chatEntryHtml).join('')
    : emptyStateHtml(chatEmptyCopy(!!liveServer, liveServer));
  container.scrollTop = container.scrollHeight;
  window.requestAnimationFrame(() => container.setAttribute('aria-live', 'polite'));
}

export function clearChat() {
  const mode = selectedMode();
  if (!mode) return;
  state.chatHistory[mode] = [];
  persistChatHistory();
  renderChatLog(mode);
  const meta = $('#test-prompt-meta');
  if (meta) meta.hidden = true;
}

// Event wiring for this panel, moved out of app.js's wireEvents().
export function initChatPanel() {
  $('#test-prompt-send').addEventListener('click', sendTestPrompt);
  $('#chat-clear')?.addEventListener('click', clearChat);
  $('#test-prompt-input').addEventListener('keydown', (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
      sendTestPrompt();
    } else if (event.key === 'Enter' && !event.shiftKey) {
      // allow normal enter to send (like many chats)
      event.preventDefault();
      sendTestPrompt();
    }
  });
}
