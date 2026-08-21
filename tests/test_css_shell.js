// Guard the app-shell rule: a closed block before display:grid
// collapses the whole dashboard into a stacked sidebar.
const fs = require('fs');
const path = require('path');

const css = fs.readFileSync(path.join(__dirname, '..', 'lcc_api', 'static', 'styles.css'), 'utf8');
const firstShell = css.match(/\.app-shell\s*\{[^}]*\}/);
if (!firstShell) {
  console.log(JSON.stringify({ ok: false, error: 'first .app-shell rule missing' }));
  process.exit(1);
}
const hasGrid = /display:\s*grid/.test(firstShell[0]);
const leftover = /\}\s*\n\s+display:\s*grid;/.test(css);
const html = fs.readFileSync(path.join(__dirname, '..', 'lcc_api/static/index.html'), 'utf8');
const noEyebrow = !/panel-eyebrow/.test(css) && !/panel-eyebrow/.test(html);
const noPanelFocusRail = !/\.panel:focus-within/.test(css);

const toastRule = css.match(/\.toast\s*\{[^}]*\}/);
const toastShow = css.match(/\.toast\.show\s*\{[^}]*\}/);
const toastHidden = toastRule && /pointer-events:\s*none/.test(toastRule[0]);
const toastClickable = toastShow && /pointer-events:\s*auto/.test(toastShow[0]);
const waitVisible = /#parameters \.launch-primary\.busy\s*\{[^}]*color:\s*inherit/.test(css)
  || /#parameters \.launch-primary\.busy \{[\s\S]*?color:\s*inherit/.test(css);

const ok = hasGrid && !leftover && toastHidden && toastClickable && waitVisible && noEyebrow && noPanelFocusRail;
console.log(JSON.stringify({
  ok,
  hasGrid,
  leftover,
  toastHidden,
  toastClickable,
  waitVisible,
  noEyebrow,
  noPanelFocusRail,
  snippet: firstShell[0].slice(0, 180),
}));
process.exit(ok ? 0 : 1);
