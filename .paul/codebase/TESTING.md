---
description: "Llama Control Center — testing patterns"
type: CodebaseDoc
about: "llama-control-center"
---

# Testing Patterns

## Test Framework

**pytest**, configured in `pyproject.toml`. One custom marker:

```toml
markers = [
  "slow: exercises every real GGUF found on disk; deselect with -m \"not slow\"",
]
```

Run the fast suite with `pytest -m "not slow"`. The slow lane walks real model files on the host, so it is machine-dependent by design.

## Test File Organization

Flat `tests/`, one file per core module, mirroring the source name:

| File | Tests | Covers |
|---|---|---|
| `tests/test_lcc_core.py` | 136 | the bulk of `lcc_core/` — 2,388 lines |
| `tests/test_lcc_api.py` | 27 | API smoke tests; also the **driver for the JS tests** |
| `tests/test_profile_registry.py` | 16 | discovery/registration |
| `tests/test_truth_gguf.py` | 11 | GGUF header → `ArchFacts` |
| `tests/test_truth_kv.py` | 11 | pure memory arithmetic |
| `tests/test_hf_metadata.py` | 7 | HF lookups |
| `tests/test_stop_lcc.py` | 6 | shutdown path |
| `tests/test_launch_smoke.py` | 2 | launch smoke |
| `tests/test_truth_shadow.py` | 2 | legacy-vs-truth divergence logging |
| `tests/test_truth_differential.py` | 1 | differential check |

**219 Python tests total.** Baseline at the last recorded run: 151 passed + 1 skipped for the then-current subset; the audit measured 152 tests at ~37s with API smoke tests dominating.

## JavaScript Tests

Frontend logic is tested by extracting pure helpers to module scope and running them under **node, driven from pytest** — there is no npm test script:

```python
# tests/test_lcc_api.py
js_test = P(__file__).parent / "test_server_metrics_formatter.js"
out = subprocess.check_output(["node", str(js_test)], encoding="utf-8",
                              cwd=P(__file__).parent.parent)
```

`encoding="utf-8"` is **required** — node output broke collection once without it.

⚠️ **Only 2 of the 6 `.js` test files are wired into a driver:** `test_server_metrics_formatter.js` and `test_models_pane_matcher.js`. The four newer ones (`test_css_shell.js`, `test_empty_copy.js`, `test_launch_lock.js`, `test_smart_fit_ui.js`) are referenced by nothing and therefore never execute. See CONCERNS.

## Fixtures and Factories

`tests/gguf_fixtures.py` (56 lines) synthesizes GGUF inputs so header parsing and memory arithmetic can be tested without real multi-GB models.

Import it **bare** (`import gguf_fixtures`), not as a package path — commit `b961153` fixed collection specifically so it survives a stray `graphify/` directory in the tree.

## Test Types

- **Pure unit** — `test_truth_kv.py` is the model: no I/O, no clock, exhaustive arithmetic assertions
- **Parsing** — `test_truth_gguf.py` against synthetic fixtures
- **API smoke** — `test_lcc_api.py` via a FastAPI test client; the slowest lane
- **Differential/shadow** — `test_truth_differential.py`, `test_truth_shadow.py` assert the new truth layer against the legacy estimator instead of asserting absolute numbers
- **Cross-language** — node subprocess for frontend helpers
- **Slow/real-hardware** — marked `slow`, walks actual GGUFs on disk

## Common Patterns

- **Test the arithmetic, not the wiring.** The purity contract on `truth/kv.py` exists so its behaviour is checkable exhaustively — preserve it when adding memory math
- **Differential over absolute.** When changing the estimator, prefer asserting agreement with the shadow layer over hardcoding a byte count
- **Extract to test.** Frontend logic gets tested by lifting it out of DOM handlers into a module-scope pure function first

## Coverage Gaps

No coverage tooling is configured. Known blind spots: the four orphaned `.js` tests, the WSL/vLLM launch path (hard to exercise off Windows+WSL), and per-OS hardware probes other than the host's own.
