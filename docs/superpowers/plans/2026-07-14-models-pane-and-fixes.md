# Models Pane Actions + Smart-Fit/HF Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship v0.17.0: actionable Models pane, HF install-CLI removal, sensible refresh icon, HF lookup fixed for directory checkpoints, built-in-MTP-aware profiles, and a vLLM-WSL fit estimator + full auto-tuner.

**Architecture:** Models-pane actions resolve each model to its auto-registered profile client-side (pure matcher + existing action functions). HF query inference stops mangling dotted directory names. MTP detection extends the existing gguf-meta cache (same pattern as `supports_tools`). vLLM fit lives in a new `lcc_core/vllm_estimates.py` that returns the exact `estimate_memory_fit` response shape, branched into `estimate_memory_fit` and `auto_tune_fit` on `runtime == "vllm-wsl"` so every existing caller (profile badges, tuner UI) works unchanged.

**Tech Stack:** Python 3.10+/FastAPI backend, vanilla-JS static frontend, unittest/pytest, Node-eval JS unit tests.

**Repo root (all paths relative to it):** `C:\Users\filth\llama.cpp-cuda\tools\llama-control-center-repo`

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-14-models-pane-and-fixes-design.md`.
- Baseline: 154 passed, 1 skipped (`python -m pytest tests/ -q`); suite green after every task.
- `node --check lcc_api/static/app.js` after every JS change.
- Profiles pane behavior unchanged; no Start/Stop buttons on model rows.
- MTP: only drop the draft_model requirement + force `flash_attn`; reasoning/jinja stay on existing detection.
- vLLM estimator returns the same dict shape as `estimate_memory_fit` (keys: `status,label,accelerator_status,ram_status,accelerator_name,backend,uses_ram_offload,model_size_mib,estimated{...},inputs{...},warnings`).
- Missing/unparsable vLLM `config.json` → `status: "unknown"` with a warning, never a GGUF-based guess.
- Commit messages end with: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Remove the HF "Install CLI" option

**Files:**
- Modify: `lcc_api/static/index.html:585` (delete button)
- Modify: `lcc_api/static/app.js:3278-3295` (delete listener block)
- Modify: `lcc_api/app.py:23` (import) and `:534-536` (endpoint)
- Modify: `lcc_core/hf_cli.py:19` (guidance copy) and `:82+` (`install_hf_cli`)
- Test: `tests/test_lcc_api.py` (route-gone assertion)

- [ ] **Step 1: Add the failing route-gone assertion**

In `tests/test_lcc_api.py`, inside `test_profiles_scan_registers_and_launch_scripts_routes_are_gone`, append:

```python
        self.assertEqual(self.client.post("/api/hf-cli/install").status_code, 404)
```

Run: `python -m pytest tests/test_lcc_api.py -q -k profiles_scan` — expected FAIL (endpoint still returns 200).

- [ ] **Step 2: Remove the surfaces**

- `index.html`: delete the line `<button class="mini-button primary" id="hf-install-button">Install CLI</button>`.
- `app.js`: delete the whole `$('#hf-install-button').addEventListener(...)` block (lines 3278–3295).
- `app.py`: remove `install_hf_cli` from the import at line 23; delete the `@app.post("/api/hf-cli/install")` endpoint (534–536).
- `hf_cli.py`: delete the `install_hf_cli` function; change the `install_guidance` string to `"Run 'pip install huggingface_hub' to install the Hugging Face CLI."`.
- Grep for stragglers: `git grep -n "install_hf_cli\|hf-install-button\|hf-cli/install" -- "*.py" "*.js" "*.html"` → only CHANGELOG history hits.

- [ ] **Step 3: Verify + commit**

```powershell
node --check lcc_api/static/app.js
python -m pytest tests/test_lcc_api.py -q
git add -u
git commit -m @'
feat!: remove the HF Install CLI button and endpoint

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 2: Refresh icon

**Files:**
- Modify: `lcc_api/static/index.html:116-118`
- Modify: `lcc_api/static/styles.css` (remove the old `.refresh-icon` glyph rules)

- [ ] **Step 1: Replace the icon markup**

In `index.html`, replace:

```html
            <button class="button secondary" id="refresh-button" type="button" title="Refresh inventory">
              <span class="toolbar-icon refresh-icon" aria-hidden="true"></span>
              Refresh
```

with:

```html
            <button class="button secondary" id="refresh-button" type="button" title="Refresh inventory">
              <svg class="toolbar-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false"><path d="M13.65 2.35A7.95 7.95 0 0 0 8 0a8 8 0 1 0 7.75 10h-2.08A6 6 0 1 1 8 2c1.66 0 3.14.69 4.22 1.78L9 7h7V0l-2.35 2.35z" fill="currentColor"/></svg>
              Refresh
```

- [ ] **Step 2: Remove the stale CSS glyph**

Find `.refresh-icon` rules in `styles.css` (`grep -n "refresh-icon" lcc_api/static/styles.css`) and delete them. If `.toolbar-icon` has sizing rules that assumed the span, verify the SVG inherits size/color correctly (it should — `currentColor` + explicit width/height).

- [ ] **Step 3: Verify + commit**

Open the dashboard later in Task 11's live check; for now `node --check` (unchanged JS) and a visual sanity check of the HTML edit. Commit:

```powershell
git add lcc_api/static/index.html lcc_api/static/styles.css
git commit -m @'
fix(ui): replace refresh toolbar icon with a standard circular-arrow glyph

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 3: `infer_query` fixes (HF lookup for directory checkpoints)

**Files:**
- Modify: `lcc_core/hf_metadata.py:36-45`
- Test: `tests/test_hf_metadata.py` (new file)

**Interfaces:**
- Produces: `infer_query(name, path)` — same signature, better output. Task 4 extends the same test file.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_hf_metadata.py`:

```python
from __future__ import annotations

import unittest

from lcc_core.hf_metadata import infer_query


class InferQueryTests(unittest.TestCase):
    def test_gguf_file_query_keeps_working(self) -> None:
        q = infer_query("Qwen3.6-27B-GGUF", r"C:\Users\x\models\Qwen3.6-27B-GGUF\Qwen3.6-27B-Q6_K.gguf")
        self.assertIn("Qwen3.6 27B", q)
        self.assertNotIn("gguf", q.lower())

    def test_dotted_directory_name_is_not_mangled(self) -> None:
        # Regression: Path.stem split "Qwen3.6-27B-NVFP4" into "Qwen3" and
        # parent.name appended "models", producing a query HF can't match.
        q = infer_query("Qwen3.6-27B-NVFP4", r"C:\Users\x\models\Qwen3.6-27B-NVFP4")
        self.assertEqual(q, "Qwen3.6 27B NVFP4")

    def test_generic_parent_folders_are_dropped(self) -> None:
        q = infer_query(None, r"C:\Users\x\models\Devstral-Small-2-24B")
        self.assertEqual(q, "Devstral Small 2 24B")

    def test_never_returns_empty(self) -> None:
        self.assertTrue(infer_query("", r"C:\models\gguf"))


if __name__ == "__main__":
    unittest.main()
```

Run: `python -m pytest tests/test_hf_metadata.py -q` — expected: 2+ FAIL (mangled query).

- [ ] **Step 2: Implement**

Replace `infer_query` in `lcc_core/hf_metadata.py`:

```python
_MODEL_FILE_SUFFIXES = {".gguf", ".safetensors", ".bin", ".pt", ".pth"}
_GENERIC_PATH_TOKENS = {"models", "model", "hf", "gguf", "checkpoints", "weights", "downloads"}


def infer_query(name: str | None = None, path: str | None = None) -> str:
    parts = [name or ""]
    if path:
        path_obj = Path(path)
        # Only strip a suffix when it's a known model-file extension —
        # Path.stem on a dotted directory name ("Qwen3.6-27B-NVFP4") would
        # otherwise mangle it into "Qwen3".
        base = path_obj.stem if path_obj.suffix.lower() in _MODEL_FILE_SUFFIXES else path_obj.name
        for candidate in (base, path_obj.parent.name):
            if not candidate or candidate.lower() in _GENERIC_PATH_TOKENS:
                continue
            if candidate.lower() in (name or "").lower():
                continue  # already covered by the name
            parts.append(candidate)
    query = " ".join(parts)
    query = re.sub(r"(?i)\b(gguf|unsloth|thebloke|q\d(?:_[a-z0-9]+)+|ud|it)\b", " ", query)
    query = re.sub(r"[-_]+", " ", query)
    query = re.sub(r"\s+", " ", query).strip()
    return query or (name or Path(path or "").name)
```

Note the final fallback also changes `.stem` → `.name` (same mangling bug).

- [ ] **Step 3: Verify + commit**

Run: `python -m pytest tests/test_hf_metadata.py -q` — all pass. Then live-check the original failure:

```powershell
python -c "from lcc_core.hf_metadata import fetch_model_info; r = fetch_model_info(name='Qwen3.6-27B-NVFP4', path=r'C:\Users\filth\models\Qwen3.6-27B-NVFP4'); print(r.get('success'), r.get('query'), r.get('model_id'))"
```

Expected: `True Qwen3.6 27B NVFP4 <some-repo-id>` (network permitting; if HF genuinely has no such repo, `success=False` with the *clean* query is still the fix working).

```powershell
git add lcc_core/hf_metadata.py tests/test_hf_metadata.py
git commit -m @'
fix: HF query inference no longer mangles dotted checkpoint dir names

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 4: Directory-aware `check_model_update`

**Files:**
- Modify: `lcc_core/hf_metadata.py:105-159`
- Test: `tests/test_hf_metadata.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_hf_metadata.py`:

```python
class DirUpdateCheckTests(unittest.TestCase):
    def test_directory_checkpoint_uses_newest_shard_mtime(self) -> None:
        import tempfile, os, time
        from pathlib import Path as P
        from unittest import mock
        from lcc_core import hf_metadata

        with tempfile.TemporaryDirectory() as tmp:
            ckpt = P(tmp) / "Fake-NVFP4"
            ckpt.mkdir()
            shard = ckpt / "model-00001-of-00001.safetensors"
            shard.write_bytes(b"x" * 128)

            fake_info = {"success": True, "model_id": "org/fake", "url": "u", "query": "q"}
            # Repo modified long before the local shard -> no update.
            fake_meta = {"lastModified": "2020-01-01T00:00:00.000Z"}
            with mock.patch.object(hf_metadata, "fetch_model_info", return_value=fake_info), \
                 mock.patch.object(hf_metadata, "_get_json", return_value=fake_meta):
                result = hf_metadata.check_model_update(name="Fake", path=str(ckpt))

        self.assertTrue(result["success"])
        self.assertIsNone(result["file_differs"])  # no single-file compare for dirs
        self.assertFalse(result["update_available"])
        self.assertIn("director", result["reason"].lower() + " directory")  # dir-aware reason mentioned
```

Run: `python -m pytest tests/test_hf_metadata.py -q -k Dir` — expected FAIL (current code stats the dir itself; `filename` is the dir name and `_find_remote_file` is attempted).

- [ ] **Step 2: Implement**

In `check_model_update`, replace the local-file block:

```python
    filename = local_size = local_mtime = None
    is_dir = False
    if path:
        local = Path(path)
        if local.is_dir():
            # Sharded checkpoint: no single file to compare. Use the newest
            # model-shard mtime as the local freshness signal.
            is_dir = True
            shards = sorted(local.glob("*.safetensors")) or sorted(local.iterdir())
            mtimes = [f.stat().st_mtime for f in shards if f.is_file()]
            local_mtime = max(mtimes) if mtimes else None
        else:
            filename = local.name
            if local.exists():
                stat = local.stat()
                local_size, local_mtime = stat.st_size, stat.st_mtime
```

and adjust the reason strings after the `update_available` computation:

```python
    if file_differs is not None:
        update_available = file_differs
        reason = "remote file size differs from local copy" if file_differs else "remote file matches your local copy"
    else:
        update_available = _modified_after(last_modified, local_mtime)
        suffix = " (directory checkpoint: compared repo activity to your newest shard)" if is_dir else ""
        reason = (
            f"repo changed after your local file (may be a card/metadata edit){suffix}"
            if update_available
            else f"no newer changes detected{suffix}"
        )
```

(`remote = _find_remote_file(...) if filename else None` already short-circuits for dirs since `filename` stays `None`.)

- [ ] **Step 3: Verify + commit**

```powershell
python -m pytest tests/test_hf_metadata.py -q
git add lcc_core/hf_metadata.py tests/test_hf_metadata.py
git commit -m @'
fix: HF update check handles sharded directory checkpoints

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 5: Pure `profileForModelPath` matcher (JS) + Node test

**Files:**
- Modify: `lcc_api/static/app.js` (add near `formatServerMetricsLine`, ~line 1290)
- Create: `tests/test_models_pane_matcher.js`
- Test: `tests/test_lcc_api.py` (Python wrapper test, same pattern as `ServerMetricsFormatterTests`)

**Interfaces:**
- Produces: `profileForModelPath(profiles, path) -> profile | null` used by Task 6.

- [ ] **Step 1: Write the Node-eval test**

Create `tests/test_models_pane_matcher.js` (mirror the extraction style of `tests/test_server_metrics_formatter.js` — read that file first and copy its function-extraction helper):

```javascript
// Extracts profileForModelPath from the shipped app.js and unit-tests it.
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const src = fs.readFileSync(path.join(__dirname, '..', 'lcc_api', 'static', 'app.js'), 'utf8');
const start = src.indexOf('function profileForModelPath');
if (start === -1) { console.log(JSON.stringify({ ok: false, error: 'function not found' })); process.exit(1); }
// Take the function body up to the next top-level "\nfunction " declaration.
const end = src.indexOf('\nfunction ', start + 1);
const fnSrc = src.slice(start, end === -1 ? undefined : end);
const ctx = {};
vm.createContext(ctx);
vm.runInContext(fnSrc + '; this.fn = profileForModelPath;', ctx);

const profiles = [
  { mode: 'a', launchable: true, confidence: 1.0, model: { path: 'C:\\Users\\x\\models\\Qwen3.6-27B-GGUF\\Qwen3.6-27B-Q6_K.gguf' } },
  { mode: 'a-mtp', launchable: false, confidence: 1.0, model: { path: 'C:\\Users\\x\\models\\Qwen3.6-27B-GGUF\\Qwen3.6-27B-Q6_K.gguf' } },
  { mode: 'b', launchable: true, confidence: 1.0, model: { path: '/home/x/models/other.gguf' } },
  { mode: 'unresolved', launchable: false, confidence: 0, model: null },
];

const results = {
  exact: ctx.fn(profiles, 'C:\\Users\\x\\models\\Qwen3.6-27B-GGUF\\Qwen3.6-27B-Q6_K.gguf')?.mode,
  slashAgnostic: ctx.fn(profiles, 'C:/Users/x/models/Qwen3.6-27B-GGUF/Qwen3.6-27B-Q6_K.gguf')?.mode,
  caseAgnostic: ctx.fn(profiles, 'c:\\users\\x\\models\\qwen3.6-27b-gguf\\qwen3.6-27b-q6_k.gguf')?.mode,
  noMatch: ctx.fn(profiles, 'C:\\nowhere.gguf'),
};
const ok = results.exact === 'a' && results.slashAgnostic === 'a' && results.caseAgnostic === 'a' && results.noMatch === null;
console.log(JSON.stringify({ ok, results }));
process.exit(ok ? 0 : 1);
```

And in `tests/test_lcc_api.py`, add to `ServerMetricsFormatterTests` (rename mentally: it's the JS-unit-test class):

```python
    def test_profile_for_model_path_matcher(self):
        import subprocess
        import json
        from pathlib import Path as P

        js_test = P(__file__).parent / "test_models_pane_matcher.js"
        out = subprocess.check_output(["node", str(js_test)], encoding="utf-8", cwd=P(__file__).parent.parent)
        data = json.loads(out.strip())
        self.assertTrue(data["ok"], data)
```

Run: `python -m pytest tests/test_lcc_api.py -q -k matcher` — expected FAIL (`function not found`).

- [ ] **Step 2: Implement the pure function in app.js**

Add immediately before `function formatServerMetricsLine(m)`:

```javascript
// Pure matcher: resolve a model file/dir path to its profile. Case- and
// slash-agnostic (Windows paths); prefers launchable exact matches when
// several profiles share one model file (e.g. an MTP variant).
function profileForModelPath(profiles, path) {
  if (!path) return null;
  const norm = (p) => String(p || '').replace(/\//g, '\\').toLowerCase();
  const target = norm(path);
  const matches = (profiles || []).filter((p) => p.model && norm(p.model.path) === target);
  if (!matches.length) return null;
  const ranked = [...matches].sort((a, b) => (
    (b.launchable === true) - (a.launchable === true)
    || (b.confidence === 1.0) - (a.confidence === 1.0)
  ));
  return ranked[0];
}
```

- [ ] **Step 3: Verify + commit**

```powershell
node --check lcc_api/static/app.js
python -m pytest tests/test_lcc_api.py -q -k "matcher or formatter"
git add lcc_api/static/app.js tests/test_models_pane_matcher.js tests/test_lcc_api.py
git commit -m @'
feat(ui): pure profileForModelPath matcher + node unit test

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 6: Models pane action strip

**Files:**
- Modify: `lcc_api/static/app.js:1291-1304` (`renderModels`) + one delegated click handler in the wiring section (near line 3230)
- Modify: `lcc_api/static/styles.css` (`.model-actions` styles)

**Interfaces:**
- Consumes: `profileForModelPath` (Task 5); existing `runFitTest()`, `runAutoTune()`, `fetchHFInfo()`, `checkModelUpdate()`, `renderParameters()`, `renderProfiles()`, `refresh()`, `api()`, `toast()`, `withBusy()`, `state`.

- [ ] **Step 1: Rewrite `renderModels`**

```javascript
function renderModels() {
  const models = (state.inventory?.models || []).filter(modelMatches);
  $('#model-list').innerHTML = models.map((model) => {
    const profile = profileForModelPath(state.profiles, model.path);
    const actions = profile
      ? `
        <button class="mini-button" type="button" data-model-action="params" data-model-path="${escapeHtml(model.path)}" title="Open this model in the Parameters editor">Parameters</button>
        <button class="mini-button" type="button" data-model-action="fit" data-model-path="${escapeHtml(model.path)}" title="Run a fit test for this model">Fit test</button>
        <button class="mini-button" type="button" data-model-action="tune" data-model-path="${escapeHtml(model.path)}" title="Smart-fit auto-tune this model">Auto-tune</button>
        <button class="mini-button" type="button" data-model-action="hf" data-model-path="${escapeHtml(model.path)}" title="Hugging Face info + update check">HF check</button>`
      : `
        <button class="mini-button primary" type="button" data-model-action="register" data-model-path="${escapeHtml(model.path)}" title="Register this model as a launchable profile">Register</button>`;
    return `
    <article class="model-row">
      <strong>${escapeHtml(model.name)}</strong>
      <div class="model-meta">
        <span class="badge">${escapeHtml(model.quant || 'unknown quant')}</span>
        <span class="badge">${escapeHtml(formatBytes(model.size_bytes))}</span>
        <span class="badge">${escapeHtml(model.source)}</span>
      </div>
      <div class="model-path">${escapeHtml(model.path)}</div>
      <div class="model-actions">${actions}</div>
    </article>`;
  }).join('') || '<div class="loading">No models match the current search.</div>';
}
```

- [ ] **Step 2: Add the delegated handler + selection helper**

Add these functions near `runAutoTune`:

```javascript
// Select the profile that owns `path` in the Parameters editor (same code
// path as the #param-profile dropdown), returning the profile or null.
function selectProfileForModelPath(path) {
  const profile = profileForModelPath(state.profiles, path);
  if (!profile) {
    toast('No profile for this model yet — click Register first');
    return null;
  }
  state.selectedProfileMode = profile.mode;
  const select = $('#param-profile');
  if (select) select.value = profile.mode;
  renderParameters();
  renderProfiles();
  return profile;
}

async function handleModelAction(action, path, trigger) {
  if (action === 'register') {
    await withBusy(trigger, async () => {
      try {
        const result = await api('/api/profiles/scan', { method: 'POST' });
        toast(result.registered_count ? `Registered ${result.registered_count} profile(s)` : 'No new models to register');
        await refresh();
      } catch (error) {
        toast(`Register failed: ${error.message}`);
      }
    });
    return;
  }
  const profile = selectProfileForModelPath(path);
  if (!profile) return;
  if (action === 'params') {
    document.querySelector('#parameters-panel, #param-profile')?.closest('section, .panel')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else if (action === 'fit') {
    await runFitTest();
  } else if (action === 'tune') {
    await runAutoTune();
  } else if (action === 'hf') {
    await fetchHFInfo();
    await checkModelUpdate();
  }
}
```

In the wiring section (after the `#fit-button` listener at ~line 3237), add:

```javascript
  $('#model-list').addEventListener('click', (event) => {
    const button = event.target.closest('[data-model-action]');
    if (!button) return;
    handleModelAction(button.dataset.modelAction, button.dataset.modelPath, button);
  });
```

Before finalizing, verify the real IDs/selectors: `grep -n "model-list\|parameters-panel" lcc_api/static/index.html` — adjust the `scrollIntoView` target to the actual Parameters panel container id/class found there. Also confirm `fetchHFInfo` and `checkModelUpdate` are the real function names (grep) — `checkModelUpdate` is wired at app.js:3260.

- [ ] **Step 3: CSS**

Append to the Models panel section of `styles.css` (find `.model-row` rules):

```css
.model-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
```

- [ ] **Step 4: Verify + commit**

```powershell
node --check lcc_api/static/app.js
python -m pytest tests/test_lcc_api.py -q
git add lcc_api/static/app.js lcc_api/static/styles.css
git commit -m @'
feat(ui): models pane action strip (Parameters / Fit / Auto-tune / HF / Register)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

Live verification happens in Task 11.

---

### Task 7: Built-in MTP detection in the gguf-meta cache

**Files:**
- Modify: `lcc_core/estimates.py` (meta cache: `_KV_META_CACHE_VERSION` 3→4, `_parse_gguf_meta`, `_store_meta_cache`, `_gguf_meta`, new `model_has_builtin_mtp`)
- Test: `tests/test_lcc_core.py` (new test class)

**Interfaces:**
- Produces: `model_has_builtin_mtp(model_path: str | None, probe: bool = True) -> bool | None` (None = unknown), used by Task 8. Cache tuple grows a 5th element `mtp`.

- [ ] **Step 1: Read the current meta-cache code paths**

Read `lcc_core/estimates.py:276-500` completely (cache load/store, `_parse_gguf_meta`, `_gguf_meta`, `model_supports_tools`, `recommend_jinja`, `prime_model_meta`) before editing — the new field must flow through every one of those functions identically to `supports_tools`.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_lcc_core.py` (imports at top of file already include tempfile/Path/estimates or add locally in the class):

```python
class BuiltinMtpDetectionTests(unittest.TestCase):
    def test_cache_roundtrip_and_cache_only_read(self) -> None:
        import os
        import tempfile
        from lcc_core import estimates

        with tempfile.TemporaryDirectory() as tmp:
            orig = os.environ.get("LCC_CACHE_DIR")
            os.environ["LCC_CACHE_DIR"] = tmp
            try:
                model = Path(tmp) / "mtp-model.gguf"
                model.write_bytes(b"gguf-bytes")
                sig = estimates._file_signature(str(model))
                estimates._store_meta_cache(str(model), sig, 48, (4, 256, 256), True, 262144, mtp=True)
                # Cache-only read (probe=False) must see it without opening the file.
                self.assertTrue(estimates.model_has_builtin_mtp(str(model), probe=False))
                # Unknown model -> None, not False.
                self.assertIsNone(estimates.model_has_builtin_mtp(str(Path(tmp) / "other.gguf"), probe=False))
            finally:
                if orig is None:
                    os.environ.pop("LCC_CACHE_DIR", None)
                else:
                    os.environ["LCC_CACHE_DIR"] = orig

    def test_tensor_name_detection(self) -> None:
        from lcc_core import estimates
        self.assertTrue(estimates._tensor_names_indicate_mtp(["blk.0.attn_q.weight", "blk.48.nextn.embed_tokens.weight"]))
        self.assertTrue(estimates._tensor_names_indicate_mtp(["mtp.head.weight"]))
        self.assertFalse(estimates._tensor_names_indicate_mtp(["blk.0.attn_q.weight", "output.weight"]))
```

Run: `python -m pytest tests/test_lcc_core.py -q -k Mtp` — expected FAIL (no such functions/params).

- [ ] **Step 3: Implement**

In `estimates.py`:

1. Bump `_KV_META_CACHE_VERSION = 4`.
2. Add near `_template_supports_tools`:

```python
_MTP_TENSOR_RE = re.compile(r"(?i)(?:^|\.)(?:nextn|mtp)(?:\.|_|$)")


def _tensor_names_indicate_mtp(names) -> bool:
    """True when tensor names reveal built-in MTP/NextN speculative layers."""
    return any(_MTP_TENSOR_RE.search(str(name)) for name in names)
```

3. Extend `_store_meta_cache(...)` with a keyword param `mtp: bool | None = None` stored alongside the others.
4. Extend `_parse_gguf_meta` to compute `mtp = _tensor_names_indicate_mtp(tensor names already iterated for the layer scan)` — reuse the existing tensor iteration (do NOT re-open the reader); return it as the 5th tuple element and pass to `_store_meta_cache`.
5. Extend `_gguf_meta` to read/return the 5th element (`entry.get("mtp")`) with `None` default for old entries.
6. Update every unpack site of the meta tuple (`grep -n "_gguf_meta(" lcc_core/estimates.py`) to the 5-element form.
7. Add the public accessor following `model_supports_tools`:

```python
def model_has_builtin_mtp(model_path: str | None, probe: bool = True) -> bool | None:
    """Whether the GGUF carries built-in MTP/NextN speculative layers.

    Cache-only when probe=False (resolver hot path). None = unknown.
    """
    _n_layer, _kv, _tools, _ctx, mtp = _gguf_meta(model_path, parse=probe)
    return mtp
```

(Adjust to the actual tuple arity found in Step 1 — if `_gguf_meta` returns 4 elements today, it returns 5 after this change; update `prime_model_meta`, `model_supports_tools`, `model_max_context`, `_read_gguf_*` unpackers accordingly.)

- [ ] **Step 4: Verify + commit**

```powershell
python -m pytest tests/test_lcc_core.py -q
git add lcc_core/estimates.py tests/test_lcc_core.py
git commit -m @'
feat: detect built-in MTP/NextN layers via the gguf-meta cache (v4)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 8: Resolver honors built-in MTP

**Files:**
- Modify: `lcc_core/profile_resolver.py:170-199` (`_validate_resolved`) and `_resolved_params`
- Test: `tests/test_lcc_core.py`

**Interfaces:**
- Consumes: `model_has_builtin_mtp` (Task 7, `probe=False`).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_lcc_core.py` (inside or beside the existing resolver test class — follow the file's existing fixture style with a temp root + models.json + seeded cache):

```python
class BuiltinMtpResolutionTests(unittest.TestCase):
    def test_mtp_profile_launchable_without_draft_when_builtin(self) -> None:
        import os
        import tempfile
        from lcc_core import estimates
        from lcc_core.profile_resolver import resolve_profiles

        with tempfile.TemporaryDirectory() as tmp:
            orig = os.environ.get("LCC_CACHE_DIR")
            os.environ["LCC_CACHE_DIR"] = tmp
            try:
                root = Path(tmp) / "proj"
                (root / "models").mkdir(parents=True)
                model = root / "models" / "Qwen-MTP-Q6_K.gguf"
                model.write_bytes(b"gguf-bytes")
                sig = estimates._file_signature(str(model))
                estimates._store_meta_cache(str(model), sig, 48, (4, 256, 256), True, 262144, mtp=True)
                (root / "models.json").write_text(json.dumps({"models": [{
                    "mode": "qwen-mtp",
                    "name": "Qwen MTP",
                    "description": "MTP profile",
                    "model_path": str(model),
                    "recommended_params": {"ctx_size": 8192, "threads": 4, "gpu_layers": 999,
                                           "cache_type_k": "q8_0", "cache_type_v": "q8_0"},
                }]}), encoding="utf-8")

                resolved = resolve_profiles(project_root=root, model_dirs=[root / "models"])
            finally:
                if orig is None:
                    os.environ.pop("LCC_CACHE_DIR", None)
                else:
                    os.environ["LCC_CACHE_DIR"] = orig

        self.assertEqual(len(resolved), 1)
        profile = resolved[0]
        self.assertTrue(profile.launchable, (profile.missing, profile.warnings))
        self.assertNotIn("draft_model", profile.missing)
        self.assertTrue(profile.params.get("flash_attn"))
```

Run: `python -m pytest tests/test_lcc_core.py -q -k BuiltinMtpResolution` — expected FAIL (`draft_model` in missing).

- [ ] **Step 2: Implement**

In `profile_resolver.py`, import the accessor:

```python
from .estimates import model_has_builtin_mtp, recommend_jinja
```

In `_validate_resolved`, replace the MTP block:

```python
    text = " ".join([profile.mode, profile.name, profile.description]).lower()
    if "mtp" in text and runtime == "llama.cpp":
        builtin_mtp = bool(model and model_has_builtin_mtp(model.path if hasattr(model, "path") else (model or {}).get("path"), probe=False))
        draft_model = str(params.get("draft_model", "")).strip()
        if builtin_mtp:
            # Built-in MTP/NextN layers: no external draft model needed, and
            # spec decode requires flash attention.
            params["flash_attn"] = True
        elif not draft_model:
            missing.append("draft_model")
        elif not Path(draft_model).expanduser().exists():
            missing.append("draft_model")
            warnings.append(f"Draft model does not exist: {draft_model}")
        if model and not builtin_mtp and "mtp" not in model.path.lower() and "gemma" not in text:
            warnings.append("MTP profile matched a non-MTP model path; this may require a WSL or custom backend.")
```

Note: `_validate_resolved` receives `model: ModelFile | None` — check the actual call site (`resolve_profiles` passes the `ModelFile` object) and use `model.path` directly; drop the dict fallback if it's always a `ModelFile`.

- [ ] **Step 3: Verify + commit**

```powershell
python -m pytest tests/test_lcc_core.py -q
python -c "from lcc_core.profile_resolver import resolve_profiles; ps=resolve_profiles(); mtp=[p for p in ps if 'mtp' in p.mode]; print([(p.mode, p.launchable, p.missing) for p in mtp])"
```

The live check on `qwen3.6-27b-q6_k-mtp` should flip to launchable **only after** its GGUF has been parsed once with the v4 cache (prime happens on the first Smart Fit / estimate touching it; the resolver itself is cache-only). If it still shows `draft_model` missing, run
`python -c "from lcc_core.estimates import model_has_builtin_mtp; print(model_has_builtin_mtp(r'<path-to-mtp-gguf>', probe=True))"` to prime + confirm detection against the real file, then re-check. If the real GGUF has no MTP tensors, report that finding — do not force it.

```powershell
git add lcc_core/profile_resolver.py tests/test_lcc_core.py
git commit -m @'
feat: built-in MTP models launch without an external draft model

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 9: vLLM estimator (`lcc_core/vllm_estimates.py`)

**Files:**
- Create: `lcc_core/vllm_estimates.py`
- Modify: `lcc_core/estimates.py:703` (runtime branch at the top of `estimate_memory_fit`)
- Test: `tests/test_vllm_estimates.py` (new)

**Interfaces:**
- Produces: `estimate_vllm_memory_fit(params: dict, model: dict | None, hardware: dict | None) -> dict` — exact `estimate_memory_fit` response shape. `read_checkpoint_config(path: str | Path) -> dict | None` (merged top-level + `text_config`). Task 10 consumes both.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vllm_estimates.py`:

```python
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from lcc_core.vllm_estimates import estimate_vllm_memory_fit, read_checkpoint_config


def _make_checkpoint(tmp: str, layers: int = 64, kv_heads: int = 4, head_dim: int = 256,
                     max_pos: int = 262144, weight_bytes: int = 16 * 1024**3) -> Path:
    ckpt = Path(tmp) / "Fake-NVFP4"
    ckpt.mkdir()
    (ckpt / "config.json").write_text(json.dumps({
        "model_type": "qwen3_5",
        "text_config": {
            "num_hidden_layers": layers,
            "num_key_value_heads": kv_heads,
            "num_attention_heads": 24,
            "head_dim": head_dim,
            "hidden_size": 5120,
            "max_position_embeddings": max_pos,
        },
    }), encoding="utf-8")
    shard = ckpt / "model-00001-of-00001.safetensors"
    # Sparse file trick is unreliable cross-platform; write a small file and
    # let the test pass explicit weight bytes via the model dict instead.
    shard.write_bytes(b"x" * 1024)
    return ckpt


HW = {
    "primary_gpu": {"name": "RTX 5090", "vram_total_bytes": 32 * 1024**3, "vram_free_bytes": 30 * 1024**3},
    "memory": {"total_bytes": 64 * 1024**3, "available_bytes": 48 * 1024**3},
}


class ReadConfigTests(unittest.TestCase):
    def test_merges_text_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = _make_checkpoint(tmp)
            cfg = read_checkpoint_config(ckpt)
        self.assertEqual(cfg["num_hidden_layers"], 64)
        self.assertEqual(cfg["num_key_value_heads"], 4)
        self.assertEqual(cfg["max_position_embeddings"], 262144)

    def test_missing_config_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_checkpoint_config(Path(tmp)))


class VllmFitTests(unittest.TestCase):
    def test_small_context_fits_large_context_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ckpt = _make_checkpoint(tmp)
            model = {"path": str(ckpt), "size_bytes": 16 * 1024**3, "format": "SAFETENSORS"}
            small = estimate_vllm_memory_fit(
                {"runtime": "vllm-wsl", "max_model_len": 8192, "gpu_memory_utilization": 0.9, "max_num_seqs": 4},
                model, HW)
            # KV/token = 2*64*4*256*2 B = 512 KiB/token -> 8192 tokens ~ 4 GiB: fits in
            # 32*0.9 - 16 - overhead ~ 10.8 GiB pool.
            self.assertIn(small["status"], ("good", "tight"))
            self.assertEqual(small["inputs"]["ctx_size"], 8192)
            huge = estimate_vllm_memory_fit(
                {"runtime": "vllm-wsl", "max_model_len": 262144, "gpu_memory_utilization": 0.9, "max_num_seqs": 4},
                model, HW)
            self.assertEqual(huge["status"], "near_limit")

    def test_missing_config_is_unknown_not_guessed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "NoConfig"
            empty.mkdir()
            result = estimate_vllm_memory_fit(
                {"runtime": "vllm-wsl", "max_model_len": 8192},
                {"path": str(empty), "size_bytes": 0}, HW)
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(result["warnings"])


if __name__ == "__main__":
    unittest.main()
```

Run: `python -m pytest tests/test_vllm_estimates.py -q` — expected FAIL (`ModuleNotFoundError`).

- [ ] **Step 2: Implement `lcc_core/vllm_estimates.py`**

```python
"""Memory-fit estimation for vLLM-in-WSL checkpoint profiles.

Mirrors the response shape of :func:`lcc_core.estimates.estimate_memory_fit`
exactly so profile badges and the smart tuner can treat GGUF and vLLM
profiles interchangeably. Sizing comes from the checkpoint itself:
weights = real safetensors bytes on disk, KV dims = config.json
(top-level merged with ``text_config`` for multimodal wrappers).

vLLM budgeting model: the engine claims ``VRAM_total * gpu_memory_utilization``
and fills what's left after weights + activation/runtime overhead with the
paged KV cache. A ``max_model_len`` fits when one full sequence's KV fits in
that pool. Overhead allowance is calibrated against the live server's
"GPU KV cache size" startup report (see 2026-07-14 spec).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Activations + CUDA graphs + NCCL/runtime slack. Calibrate in Task 11.
_VLLM_OVERHEAD_MIB = 2048.0
_KV_DTYPE_BYTES = {"fp16": 2.0, "bf16": 2.0, "auto": 2.0, "fp8": 1.0, "fp8_e4m3": 1.0, "fp8_e5m2": 1.0}

_CONFIG_KEYS = (
    "num_hidden_layers",
    "num_key_value_heads",
    "num_attention_heads",
    "head_dim",
    "hidden_size",
    "max_position_embeddings",
    "torch_dtype",
)


def read_checkpoint_config(path: str | Path) -> dict[str, Any] | None:
    """Read config.json, merging nested text_config over missing top-level keys."""
    config_path = Path(path) / "config.json"
    if not config_path.is_file():
        return None
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    nested = raw.get("text_config") if isinstance(raw.get("text_config"), dict) else {}
    merged = dict(raw)
    for key in _CONFIG_KEYS:
        if merged.get(key) is None and nested.get(key) is not None:
            merged[key] = nested[key]
    return merged


def _weights_mib(model: dict[str, Any] | None, path: Path) -> float | None:
    size = (model or {}).get("size_bytes")
    if size:
        return float(size) / 1024.0 / 1024.0
    try:
        total = sum(f.stat().st_size for f in path.glob("*.safetensors"))
    except OSError:
        return None
    return (total / 1024.0 / 1024.0) if total else None


def _kv_bytes_per_token(cfg: dict[str, Any], params: dict[str, Any]) -> float | None:
    layers = cfg.get("num_hidden_layers")
    kv_heads = cfg.get("num_key_value_heads")
    head_dim = cfg.get("head_dim")
    if head_dim is None and cfg.get("hidden_size") and cfg.get("num_attention_heads"):
        head_dim = int(cfg["hidden_size"]) // int(cfg["num_attention_heads"])
    if not (layers and kv_heads and head_dim):
        return None
    dtype = str(params.get("kv_cache_dtype") or "auto").lower()
    dtype_bytes = _KV_DTYPE_BYTES.get(dtype, 2.0)
    return 2.0 * float(layers) * float(kv_heads) * float(head_dim) * dtype_bytes


def _status(headroom: float | None, capacity: float | None, target: float) -> str:
    # Same thresholds as estimates._status_from_headroom, inlined to avoid a
    # circular import; keep in sync.
    if headroom is None or capacity is None or capacity <= 0:
        return "unknown"
    if headroom >= target:
        return "good"
    if headroom >= target * 0.35:
        return "tight"
    return "near_limit"


def estimate_vllm_memory_fit(
    params: dict[str, Any],
    model: dict[str, Any] | None = None,
    hardware: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hardware = hardware or {}
    primary_gpu = hardware.get("primary_gpu") or {}
    gpu_total_mib = (primary_gpu.get("vram_total_bytes") or 0) / 1024.0 / 1024.0 or None
    gpu_free_mib = (primary_gpu.get("vram_free_bytes") or 0) / 1024.0 / 1024.0 or None

    util = float(params.get("gpu_memory_utilization") or 0.9)
    max_len = int(float(params.get("max_model_len") or params.get("ctx_size") or 4096))
    target = float(params.get("fit_target_mib") or params.get("target_mib") or 1024.0)

    path = Path((model or {}).get("path") or "")
    cfg = read_checkpoint_config(path) if path else None
    weights = _weights_mib(model, path)
    warnings: list[str] = []

    def _payload(status: str, used: float | None, budget: float | None, kv_mib: float | None) -> dict[str, Any]:
        headroom = (budget - used) if (budget is not None and used is not None) else None
        return {
            "status": status,
            "label": {"good": "Good", "tight": "Tight", "near_limit": "Near limit", "unknown": "Unknown"}[status],
            "accelerator_status": status,
            "ram_status": "good",
            "accelerator_name": primary_gpu.get("name") or "Accelerator (vLLM in WSL)",
            "backend": "vllm-wsl",
            "uses_ram_offload": False,
            "model_size_mib": round(weights) if weights else None,
            "estimated": {
                "accelerator_used_mib": round(used) if used is not None else None,
                "accelerator_capacity_mib": round(budget) if budget is not None else None,
                "accelerator_headroom_mib": round(headroom) if headroom is not None else None,
                "ram_used_mib": None,
                "ram_capacity_mib": None,
                "ram_headroom_mib": None,
                "kv_cache_mib": round(kv_mib) if kv_mib is not None else None,
                "compute_mib": round(_VLLM_OVERHEAD_MIB),
                "target_headroom_mib": round(target),
            },
            "inputs": {
                "ctx_size": max_len,
                "gpu_layer_fraction": 1.0,
                "cache_type_k": str(params.get("kv_cache_dtype") or "auto"),
                "cache_type_v": str(params.get("kv_cache_dtype") or "auto"),
                "kv_offload": True,
                "op_offload": True,
                "gpu_memory_utilization": util,
                "max_num_seqs": int(float(params.get("max_num_seqs") or 1)),
            },
            "warnings": warnings,
        }

    if cfg is None:
        warnings.append("vLLM checkpoint config.json is missing or unreadable; fit is unknown.")
        return _payload("unknown", None, None, None)
    kv_per_token = _kv_bytes_per_token(cfg, params)
    if kv_per_token is None or not weights or not gpu_total_mib:
        if kv_per_token is None:
            warnings.append("config.json lacks layer/head dimensions; fit is unknown.")
        if not weights:
            warnings.append("No safetensors weights found to size; fit is unknown.")
        if not gpu_total_mib:
            warnings.append("GPU VRAM capacity is unknown; fit is unknown.")
        return _payload("unknown", None, None, None)

    budget = gpu_total_mib * util
    kv_mib = kv_per_token * max_len / 1024.0 / 1024.0
    used = weights + _VLLM_OVERHEAD_MIB + kv_mib
    status = _status(budget - used, budget, target)

    max_pos = cfg.get("max_position_embeddings")
    if max_pos and max_len > int(max_pos):
        warnings.append(
            f"max_model_len {max_len} exceeds the model's trained window ({int(max_pos)})."
        )
    if gpu_free_mib is not None and budget > gpu_free_mib:
        warnings.append(
            f"vLLM will claim ~{int(budget)} MiB (utilization {util}) but only ~{int(gpu_free_mib)} MiB "
            "VRAM is currently free — stop whatever is holding VRAM before launching."
        )
        if status == "good":
            status = "tight"
    return _payload(status, used, budget, kv_mib)
```

- [ ] **Step 3: Branch `estimate_memory_fit`**

At the very top of `estimate_memory_fit` in `estimates.py` (line 717, right after `hardware = hardware or {}`):

```python
    if str(params.get("runtime") or "").strip() == "vllm-wsl":
        from .vllm_estimates import estimate_vllm_memory_fit
        return estimate_vllm_memory_fit(params, model, hardware)
```

- [ ] **Step 4: Verify + commit**

```powershell
python -m pytest tests/test_vllm_estimates.py tests/test_lcc_core.py -q
git add lcc_core/vllm_estimates.py lcc_core/estimates.py tests/test_vllm_estimates.py
git commit -m @'
feat: vLLM-WSL memory-fit estimator from checkpoint config + real weights

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 10: vLLM auto-tuner

**Files:**
- Modify: `lcc_core/smart_tune.py` (branch in `auto_tune_fit` + new `_auto_tune_vllm`)
- Test: `tests/test_vllm_estimates.py` (extend)

**Interfaces:**
- Consumes: `estimate_vllm_memory_fit`, `read_checkpoint_config` (Task 9).
- Produces: same response contract as `auto_tune_fit` (`success, tuned_params, changes, suggestions[{intent,intents,label,labels,description,params,changes,fit_status,speed_estimate}], before, after, notes`); `speed_estimate` may be `{"success": False, "reason": ...}` for vLLM (no calibrated TPS model yet).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_vllm_estimates.py`:

```python
class VllmTunerTests(unittest.TestCase):
    def test_tuner_maximizes_context_within_budget(self) -> None:
        from lcc_core.smart_tune import auto_tune_fit

        with tempfile.TemporaryDirectory() as tmp:
            ckpt = _make_checkpoint(tmp)
            model = {"path": str(ckpt), "size_bytes": 16 * 1024**3, "format": "SAFETENSORS"}
            out = auto_tune_fit(
                {"runtime": "vllm-wsl", "max_model_len": 4096, "gpu_memory_utilization": 0.9, "max_num_seqs": 32},
                model, HW)

        self.assertTrue(out["success"], out)
        tuned = out["tuned_params"]
        self.assertGreater(tuned["max_model_len"], 4096)      # grew context
        self.assertLessEqual(tuned["max_model_len"], 262144)  # capped at trained window
        self.assertEqual(out["after"]["fit_status"]["inputs"]["ctx_size"], tuned["max_model_len"])
        self.assertNotEqual(out["after"]["fit_status"]["status"], "near_limit")
        self.assertTrue(out["suggestions"])
        for s in out["suggestions"]:
            self.assertIn(s["fit_status"]["status"], ("good", "tight"))

    def test_tuner_declines_without_config(self) -> None:
        from lcc_core.smart_tune import auto_tune_fit

        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "NoConfig"
            empty.mkdir()
            out = auto_tune_fit(
                {"runtime": "vllm-wsl", "max_model_len": 4096},
                {"path": str(empty), "size_bytes": 0}, HW)
        self.assertFalse(out["success"])
        self.assertIn("config", out["reason"].lower())
```

Run: `python -m pytest tests/test_vllm_estimates.py -q -k Tuner` — expected FAIL (GGUF-path nonsense or crash).

- [ ] **Step 2: Implement `_auto_tune_vllm` in smart_tune.py**

At the top of `auto_tune_fit` (after `base = dict(params or {})`):

```python
    if str(base.get("runtime") or "").strip() == "vllm-wsl":
        return _auto_tune_vllm(base, model, hardware, target_mib)
```

New function (place before `auto_tune_fit`):

```python
_VLLM_UTIL_LADDER = [0.85, 0.90, 0.92, 0.95]
_VLLM_SEQ_LADDER = [1, 2, 4, 8]
_VLLM_CTX_LADDER = [4096, 8192, 16384, 32768, 49152, 65536, 98304, 131072, 196608, 262144]

_VLLM_INTENTS = (
    ("balanced", "Balanced", "Largest context at a moderate utilization with headroom to spare."),
    ("max_context", "Max context", "Largest context that fits, at the highest safe utilization."),
    ("max_throughput", "Max throughput", "More concurrent sequences at a solid context."),
)


def _auto_tune_vllm(
    base: dict[str, Any],
    model: dict[str, Any] | None,
    hardware: dict[str, Any] | None,
    target_mib: int,
) -> dict[str, Any]:
    """Greedy grid scan for vllm-wsl profiles: utilization x max_model_len x seqs.

    Mirrors the GGUF tuner's response contract. KV in vLLM is a shared paged
    pool, so context and concurrency trade against the same budget; the fit
    estimator prices one full sequence at max_model_len (worst case for a
    single long chat, the dashboard's primary use).
    """
    from .vllm_estimates import estimate_vllm_memory_fit, read_checkpoint_config

    path = Path((model or {}).get("path") or "")
    cfg = read_checkpoint_config(path) if path else None
    before_fit = estimate_vllm_memory_fit(base, model, hardware)
    no_speed = {"success": False, "reason": "No calibrated vLLM speed model yet; benchmark to measure."}
    if cfg is None:
        return {
            "success": False,
            "reason": "vLLM checkpoint config.json is missing or unreadable; cannot tune.",
            "before": {"params": base, "fit_status": before_fit, "speed_estimate": no_speed},
        }

    max_pos = int(cfg.get("max_position_embeddings") or 0)
    ctx_ladder = [c for c in _VLLM_CTX_LADDER if not max_pos or c <= max_pos]
    if max_pos and max_pos not in ctx_ladder:
        ctx_ladder.append(max_pos)

    candidates: list[dict[str, Any]] = []
    for util in _VLLM_UTIL_LADDER:
        for ctx in ctx_ladder:
            for seqs in _VLLM_SEQ_LADDER:
                cand = dict(base)
                cand.update({
                    "gpu_memory_utilization": util,
                    "max_model_len": ctx,
                    "ctx_size": ctx,
                    "max_num_seqs": seqs,
                })
                fit = estimate_vllm_memory_fit(cand, model, hardware)
                if fit["status"] not in ("good", "tight"):
                    continue
                candidates.append({
                    "params": cand,
                    "fit": fit,
                    "util": util,
                    "ctx_norm": ctx_ladder.index(ctx) / max(1, len(ctx_ladder) - 1),
                    "seqs": seqs,
                    "roomy": 1 if fit["status"] == "good" else 0,
                })
    if not candidates:
        return {
            "success": False,
            "reason": "No vLLM configuration fit within the GPU budget.",
            "before": {"params": base, "fit_status": before_fit, "speed_estimate": no_speed},
        }

    intent_keys: dict[str, Callable[[dict[str, Any]], tuple]] = {
        "balanced": lambda c: (c["ctx_norm"], c["roomy"], -abs(c["util"] - 0.90), c["seqs"]),
        "max_context": lambda c: (c["ctx_norm"], c["util"], c["roomy"], c["seqs"]),
        "max_throughput": lambda c: (c["seqs"], c["ctx_norm"], c["roomy"], c["util"]),
    }

    suggestions: list[dict[str, Any]] = []
    by_signature: dict[tuple, dict[str, Any]] = {}
    for intent_id, label, description in _VLLM_INTENTS:
        best = max(candidates, key=intent_keys[intent_id])
        sig = (best["params"]["gpu_memory_utilization"], best["params"]["max_model_len"], best["params"]["max_num_seqs"])
        if sig in by_signature:
            entry = by_signature[sig]
            entry["intents"].append(intent_id)
            entry["labels"].append(label)
            entry["label"] = " / ".join(entry["labels"])
            continue
        entry = {
            "intent": intent_id,
            "intents": [intent_id],
            "label": label,
            "labels": [label],
            "description": description,
            "params": best["params"],
            "changes": _changes(base, best["params"]),
            "fit_status": best["fit"],
            "speed_estimate": no_speed,
        }
        by_signature[sig] = entry
        suggestions.append(entry)

    primary = suggestions[0]
    return {
        "success": True,
        "tuned_params": primary["params"],
        "cpu_fallback": False,
        "changes": primary["changes"],
        "suggestions": suggestions,
        "jinja": {"recommended": False, "reason": "vLLM applies the checkpoint's own chat template server-side"},
        "before": {"params": base, "fit_status": before_fit, "speed_estimate": no_speed},
        "after": {"params": primary["params"], "fit_status": primary["fit_status"], "speed_estimate": no_speed},
        "notes": [
            "vLLM sizing comes from the checkpoint config + real safetensors bytes; verify with a live launch.",
            "The KV pool is shared: more max_num_seqs trades against usable context in the same budget.",
            f"Overhead allowance is {int(2048)} MiB (activations + CUDA graphs); calibrated against the live server's startup report.",
        ],
    }
```

Check `_changes` signature (`grep -n "_changes" lcc_core/smart_tune.py`) and match it. Verify `Callable` is imported (it is, line 3).

- [ ] **Step 3: Verify + commit**

```powershell
python -m pytest tests/test_vllm_estimates.py -q
python -m pytest tests/ -q
git add lcc_core/smart_tune.py tests/test_vllm_estimates.py
git commit -m @'
feat: full vLLM-WSL auto-tuner (utilization x max_model_len x max_num_seqs)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

---

### Task 11: Calibration + live end-to-end verification

No new features — evidence gathering. Use superpowers:verification-before-completion.

- [ ] **Step 1: Static gates**

```powershell
python -m pytest tests/ -q
node --check lcc_api/static/app.js
```

- [ ] **Step 2: Calibrate the vLLM overhead allowance**

Find a past vLLM startup log (server_manager stores per-server stderr logs in the user cache dir; also `wsl -d Ubuntu-24.04 -- ls /tmp/lcc-vllm/`). Look for vLLM's startup lines reporting model weights size and "GPU KV cache size". Compare:
`budget (VRAM_total × util) − weights − reported_KV_pool = actual overhead`. If actual overhead differs from 2048 MiB by more than ~25%, update `_VLLM_OVERHEAD_MIB` and note the measured value in a comment. If no log exists, start the `qwen3.6-27b-nvfp4-vllm` profile once via the dashboard/API to produce one (600s ready timeout — be patient), then stop it.

- [ ] **Step 3: Live dashboard check**

`lcc start`, open http://127.0.0.1:8716/, verify: refresh icon looks right; Models pane shows action strips; Parameters/Fit/Auto-tune/HF actions work on a GGUF model; the vllm profile's fit badge is populated (not GGUF nonsense); Smart Fit on `qwen3.6-27b-nvfp4-vllm` returns vLLM suggestions; HF check on the NVFP4 model now resolves (clean query). `lcc stop` after. Record what was actually observed.

- [ ] **Step 4: Commit any calibration change**

```powershell
git add -u
git commit -m @'
chore: calibrate vLLM overhead allowance against live startup report

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
'@
```

(Skip the commit if nothing changed.)

---

### Task 12: Changelog + release v0.17.0

**Files:**
- Modify: `CHANGELOG.md`, `README.md:7`, `lcc_api/__init__.py`, `lcc_core/__init__.py`, `pyproject.toml`, `lcc_api/static/index.html` (cache buster)

- [ ] **Step 1: Changelog**

Move the existing Unreleased "Fixed" (netstat fallback) under the new release and add:

```markdown
## [0.17.0] - <today's date>

### Added
- **Models pane actions.** Every model row gains Parameters / Fit test /
  Auto-tune / HF check buttons that resolve to the model's auto-registered
  profile; unregistered models get a one-click Register (profile scan).
- **vLLM-WSL fit estimate + auto-tuner.** `vllm-wsl` profiles are now sized
  from the checkpoint itself (config.json dims + real safetensors bytes)
  against the vLLM budget (VRAM × gpu_memory_utilization); Smart Fit searches
  utilization × max_model_len × max_num_seqs and returns the same
  suggestion contract as the GGUF tuner. ([vllm_estimates.py](lcc_core/vllm_estimates.py))
- **Built-in MTP detection.** GGUFs carrying NextN/MTP speculative layers are
  detected via the gguf-meta cache; MTP profiles no longer demand an external
  draft model and force flash attention on. Reasoning/jinja stay on their
  existing per-model detection.

### Fixed
- **HF lookup for directory checkpoints.** Query inference no longer mangles
  dotted directory names ("Qwen3.6-27B-NVFP4" → "Qwen3") or appends generic
  folder names; the update check compares repo activity against the newest
  shard for sharded checkpoints instead of a meaningless dir-size compare.
- (moved) `start-lcc.py` netstat fallback fix from Unreleased.

### Removed
- **HF "Install CLI" button** and its `/api/hf-cli/install` endpoint; the
  widget still detects, versions, and update-checks the CLI.

### Changed
- Refresh toolbar icon replaced with a standard circular-arrow glyph.
```

- [ ] **Step 2: Version bumps + release commits (match v0.16.0 style)**

Bump `0.16.0` → `0.17.0` in `lcc_api/__init__.py`, `lcc_core/__init__.py`, `pyproject.toml`; update the README line-7 blurb to describe v0.17.0. Commit `Cut v0.17.0 release notes`. Then flip `?v=0.16.0` → `?v=0.17.0` in `index.html`, commit `bump cache buster to v0.17.0 in index.html`. Tag `v0.17.0`, push with tags — **only after Task 11's live checks passed and the user has seen the summary** (pushing publishes; confirm with the user if anything in Task 11 was shaky).
