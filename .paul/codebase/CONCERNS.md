---
description: "Llama Control Center — known concerns, debt, and risk areas"
type: CodebaseDoc
about: "llama-control-center"
---

# Codebase Concerns

Mapped 2026-08-21 against `feat/terminal-instrument-design`. Cross-referenced to `docs/2026-07-14-audit.md` and the M-numbers in `.paul/ROADMAP.md`.

## Known Bugs

**Issue #14 — embedded-MTP models.** Models with the MTP head inside the GGUF (Qwen3.5/3.6) hit two independent heuristics that both assumed "MTP" in a name meant a *separate draft file*. Status as of 2026-08-21 is **half-fixed, and the fix is uncommitted**:

- ✅ **Discovery (was `DRAFT_NAME_RE` in `lcc_core/profile_registry.py`) — fixed in the current WIP.** Replaced by `_is_draft_model()`, which treats `mtp` as a companion only when it is a path segment, a filename *prefix* (`mtp-`), or an `-mtp.gguf` suffix. Its docstring calls out the exact former failure: "``-MTP-`` in the middle of a product name (e.g. NVFP4-MTP-Q8attn) is not." Landed in `cb1818f` with end-to-end cover, and direct per-branch unit cover added in Phase 2 T1 (`DraftModelDetectionTests`). Verified to bite: reverting the rule fails 3 tests.
- ❌ **Launch — still open.** `lcc_core/profile_resolver.py` still runs `if "mtp" in text and runtime == "llama.cpp":` → `missing.append("draft_model")`, so an embedded-MTP profile is unlaunchable. Request-level `overrides` can't clear it; the check runs pre-merge. This is what T8 of the paused plan addresses. (The resolver *is* WIP-modified, but only for pinned-model-path handling — unrelated.)

*Workaround while it's open:* `POST /api/profiles/save` with "MTP" absent from mode/name/description.

Related: `--spec-type draft-mtp` isn't a profile param, so MTP weights load as dead capacity (`lcc_core/fit.py`, `build_fit_args`).

## Tech Debt

**[High] `lcc_api/static/app.js` — 5,060 lines in one file.** One file holds the API client, the global `state`, every panel renderer, modals, the command palette, keyboard handling, and utilities. Only four section banners exist in the whole file. *The audit measured 3,816 lines in July — it has grown ~30% since, so this is getting worse, not better.* Phase 5 / M5.1.

**[High] `lcc_api/static/styles.css` — 4,156 lines in one file.** Split into tokens/theme, base layout, and per-panel sheets, moving panel code and panel styles together. Phase 5.

**[Medium] `lcc_core/server_manager.py` — 1,172 lines** mixing tracked-state persistence, process/port detection, launch orchestration, WSL/vLLM stop logic, and the crash watchdog. Suggested split: `server_state.py`, `process_utils.py`, `vllm_wsl.py`.

**[Medium] `lcc_api/app.py` — 745 lines, 41 routes, 13 Pydantic models in one module.** Natural router seams already visible: profiles, servers, models/HF, system, estimates.

**[Medium] Duplicated constant tables (M3.1).** `CACHE_BYTES` exists in **both** `lcc_core/estimates.py` and `lcc_core/truth/kv.py` — the latter's own comment admits it is "mirroring estimates.CACHE_BYTES exactly". `CACHE_LADDER` lives separately in `smart_tune.py`. Two tables that must agree byte-for-byte, maintained by hand, is a silent-divergence trap in the one part of the codebase where wrong numbers mean OOM.

**[Medium] Defaults duplicated across the stack (M1.5).** `PARAM_DEFAULTS` in `app.js` mirrors backend defaults with nothing enforcing agreement.

**[Low] `lcc_core/estimates.py` (1,019) and `hardware.py` (999)** — cohesive but dense. Only worth splitting when next touched.

## Performance Bottlenecks

- **Double model scan** — `profile_registry.register_discovered_models` calls `discover_models()`, but `resolve_profiles()` already called it internally. Two directory walks + GGUF stats per scan, at startup *and* on `POST /api/profiles/scan`. Inherited from the removed `generate_all_launch_scripts`
- **`/api/profiles` recomputes everything per call** — manifest load + directory scan + GGUF metadata + fit enrichment on every request. The `(size, mtime)` GGUF cache softens it; a short TTL cache on the resolved payload (reusing the 2s lock+TTL pattern from `/api/system/live`) would fix it properly
- **`AppConfig.load()` re-reads `config.json` in nearly every endpoint** — cheap but constant
- **Startup autoscan blocks the ASGI lifespan** — registration runs synchronously before the server accepts requests; large model folders delay first paint

## Fragile Areas

- **The estimator is a single point of truth for everything.** Fit verdicts, the auto-tuner, and the launch preview all read it. A change there silently moves every surface — verify with a fit test or a benchmark, never by eye
- **Purity of `lcc_core/truth/kv.py`** is load-bearing ("Pure: no I/O, no globals, no clock"). Adding I/O there would quietly destroy its exhaustive testability
- **Per-OS hardware probes** (`powershell`/CIM, `system_profiler`, `lspci`, `nvidia-smi`) are only ever exercised on the host they run on. Non-host platforms are effectively untested
- **Subprocess encoding** — node output broke the suite once; `encoding="utf-8"` must be explicit
- **Git hygiene in this repo has bitten before:** `b4e818a revert: un-commit operator WIP swept into b961153`. Stage explicit paths; never `git add -A` while WIP is open

## Test Coverage Gaps

⚠️ **Four JS test files never run.** `tests/test_css_shell.js`, `test_empty_copy.js`, `test_launch_lock.js`, `test_smart_fit_ui.js` are referenced by no driver — verified by grepping the whole repo. JS tests only execute when a pytest test shells out to node (`tests/test_lcc_api.py` does this for exactly two files). These four were written and are silently dead. Either wire them in or delete them; leaving them looks like coverage that doesn't exist.

- No coverage tooling configured at all
- The WSL/vLLM launch+stop path is hard to exercise and thinly covered
- API smoke tests dominate suite runtime (~37s measured)

## Security Considerations

- **No authentication of any kind.** No auth layer, no sessions, no keys. Binds locally and assumes a single trusted operator. Anything exposing :8716 beyond localhost is an unbuilt feature, not a config change
- The app spawns processes and reads arbitrary local paths from `models.json` by design — that is the product, but it means the config file is a trust boundary

## Dependencies at Risk

Dependency surface is deliberately tiny (5 runtime packages), which is a strength. Real risk is in the **unversioned external binaries** — `nvidia-smi`, `wsl.exe`, `huggingface-cli`, `powershell`, `system_profiler`, `lspci`. Their output formats can change under you, and there is no pinning. The mitigation in place is best-effort degradation; keep it.

Upstream `llama.cpp` block layouts are mirrored by hand in `CACHE_BYTES` — an upstream quant-format change would need a manual update here.

## Missing Critical Features

**Backend shipped, UI missing** — the cheapest high-value work in the codebase. All three have working, tested endpoints today and render as almost nothing:

- Crash-watchdog surfacing (detection shipped v0.13.1) — M2.2
- Live server metrics panel: `GET /api/servers/{id}/metrics` returns KV usage, slots, decode t/s, RSS, GPU bytes; **the servers panel renders one line of it** — M2.1/M2.3
- Log tail: `GET /api/servers/{id}/logs` exists, no view — M2.4
- "Rescan models" button for `POST /api/profiles/scan` — registration otherwise only runs at startup, so a model dropped in mid-session is invisible until restart

## Process

`docs/2026-07-14-audit.md` remains the best technical reference for this codebase, but predates the ground-truth layer and the current design pass — check line counts against reality before quoting it (app.js has grown from 3,816 to 5,060 since it was written).
