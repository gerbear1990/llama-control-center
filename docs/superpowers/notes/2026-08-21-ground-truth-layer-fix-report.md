# Final fix wave — ground-truth-layer whole-branch review

Branch `feat/ground-truth-layer`, worked from head `76abb30`. All six findings fixed in one wave, suite run once, committed once.

## Finding 1 (Critical) — `truth/kv.py` CACHE_BYTES row-shifted / NVFP4+MXFP4 missing

**Changed:** `lcc_core/truth/kv.py`. Replaced `CACHE_BYTES` with the exact values from `estimates.CACHE_BYTES` (Q4_0 0.5 → 0.5625, Q4_1 0.5625 → 0.625, added NVFP4 0.5625 and MXFP4 0.53125). Rewrote `cache_bytes_per_elem` to use the same two-tier algorithm as `estimates._cache_bytes` verbatim: tier 1 is an exact/`startswith` scan over the dict (in insertion order, matching legacy's dict-iteration semantics), tier 2 is the bare-prefix fallback chain (`Q8`, `Q6`, `Q5`, `Q4`/`IQ4`, `NVFP`, `MXFP`), default `2.0`.

**Covering tests:** `tests/test_truth_kv.py::test_cache_bytes_per_elem` (corrected `q4_0`→0.5625, added `q4_1`→0.625, `nvfp4`→0.5625, `mxfp4`→0.53125) and new `test_cache_bytes_matches_legacy_estimator` (parametrized over 16 inputs including bare prefixes, mixed case, `None`, and garbage), asserting `kv.cache_bytes_per_elem(name) == estimates._cache_bytes(name)` for every one — this is the drift guard the finding asked for.

**Command / output:**
```
python -m pytest -v tests/test_truth_kv.py
...
26 passed
```
(subset of the full run below; see full-suite section for the complete number)

## Finding 2 (Important) — `_LAYER_RE` missed `.h[N].` and `block.N.`

**Changed:** `lcc_core/truth/gguf.py`. `_LAYER_RE` widened from `r"(?:blk|layers?)\.(\d+)\."` to `r"\.h\[(\d+)\]\.|blk\.(\d+)\.|block\.(\d+)\.|layers?\.(\d+)\."`, matching `estimates._N_LAYER_PATTERNS` exactly (`.h[N].`, `transformer.layer.N.`/`model.layers.N.` via the `layers?\.` alternative, `blk.N.`, `block.N.`). `_layer_index` now iterates `match.groups()` and returns the first non-`None` (mirrors `estimates._layer_index_from_tensor`), since the widened regex has one capture group per alternative.

**Fixture change:** `tests/gguf_fixtures.py::write_minimal_gguf` gained an optional `tensor_prefix: str = "blk"` parameter (default preserves every existing caller) so tests can generate `block.{i}.attn_k.weight`-style tensors.

**Covering test:** new `tests/test_truth_gguf.py::test_read_facts_recognises_block_dot_n_tensor_naming` — writes a fixture with `tensor_prefix="block"` and asserts `facts.source == "tensor-scan"` (not the false `"assumed-dense"`) and the correct `attn_layer_indices`/`total_kv_heads`.

**Command / output:** included in the full-suite run below; `test_read_facts_recognises_block_dot_n_tensor_naming PASSED`.

## Finding 3 (Important) — shadow mode's ~5.5s stall (no on-disk facts cache)

**Changed:** `lcc_core/truth/gguf.py`. Added an on-disk cache mirroring `estimates._meta_cache_file`/`_load_meta_cache`/`_store_meta_cache`: same `cache_dir()`, distinct filename `truth_facts_cache.json`, own version constant `_FACTS_CACHE_VERSION = 1` (bumped on any `ArchFacts` shape change, invalidating stale entries rather than crashing on them). `read_facts` now checks, in order: in-process memo → on-disk cache (keyed on `(size, mtime)`, same signature as the memo) → full GGUF parse. A cache hit populates the memo too. Every cache read/write is wrapped in `try/except Exception: pass`/`return {}`, so a corrupt or unwritable cache degrades to recomputation and never raises — matches the legacy implementation's failure handling.

**Covering tests:** new `tests/test_truth_gguf.py::test_read_facts_served_from_disk_cache_in_a_fresh_process` — monkeypatches `_facts_cache_file` into `tmp_path`, reads once, clears `_facts_memo` to simulate a fresh process, monkeypatches `gguf.GGUFReader` to raise if called again, and asserts the second `read_facts` call still succeeds (served from disk). New `test_read_facts_degrades_to_recompute_on_a_corrupt_disk_cache` — writes invalid JSON to the cache file and asserts `read_facts` still returns correct facts instead of raising.

**Command / output:** both tests `PASSED` in the full-suite run below.

## Finding 4 (Minor) — shadow log missing ctk/ctv and legacy-exact provenance

**Changed:** `lcc_core/truth/shadow.py`. `record_divergence` now resolves `ctk`/`ctv` once (`params.get(...) or "f16"`, the same default `breakdown`/`kv_bytes_per_token` use) and logs them as `"ctk"`/`"ctv"` strings. Added `"legacy_exact"`: calls `estimates._kv_dims({"path": model_path}, probe=False)` (inside the existing exception guard) — `probe=False` means it only reports whether legacy *already* had exact dims cached (memory or on-disk), never triggers a parse of its own. `True` when legacy's figure came from exact dims, `False` when it came from the `KV_FALLBACK_FACTOR` heuristic guess. Docstring now states the `delta_pct` sign convention: `(legacy - truth) / truth * 100`, positive = legacy reads higher.

**Covering tests:** `tests/test_truth_shadow.py::test_records_divergence_between_legacy_and_truth` updated to assert `ctk == "f16"`, `ctv == "f16"`, and `legacy_exact is False` (no prior `_kv_dims` call primed the cache for this fixture's fresh `tmp_path` model) on both the returned dict and the logged JSONL entry.

**Command / output:** `PASSED` in the full-suite run below.

## Finding 5 (Minor) — `ssm_state_bytes` omitted the group-count term

**Changed:** `lcc_core/truth/gguf.py` — added `ssm_group_count: int | None` to `ArchFacts`, read from `{arch}.ssm.group_count`. `lcc_core/truth/kv.py::ssm_state_bytes` — conv term corrected from `(conv_kernel - 1) * inner_size` to `(conv_kernel - 1) * (inner_size + 2 * group_count * state_size)`, matching llama.cpp's `(d_conv - 1) * (d_inner + 2 * n_group * d_state)`. Missing `group_count` treated as 0, which reduces to the old formula (verified by a dedicated test). Recurrent-state term (`inner_size * state_size`) unchanged. Added a comment noting llama.cpp allocates this state per `--parallel` slot, so the figure is for one slot.

**Arithmetic** (test fixture: `inner_size=4096, conv_kernel=4, state_size=128, group_count=16, n_ssm_layers=30`):

- Old formula (no group term): `conv = inner_size * (conv_kernel - 1) = 4096 * 3 = 12288`
  `state = inner_size * state_size = 4096 * 128 = 524288`
  `per_layer = (12288 + 524288) * 4 bytes = 2146304`
  `total = 30 * 2146304 = 64,389,120 bytes = 61.4209 MiB` → rounds to **61 MiB** (old test assertion)

- New formula (with group term): `conv_width = inner_size + 2*group_count*state_size = 4096 + 2*16*128 = 4096 + 4096 = 8192`
  `conv = conv_width * (conv_kernel - 1) = 8192 * 3 = 24576`
  `state = 4096 * 128 = 524288` (unchanged)
  `per_layer = (24576 + 524288) * 4 bytes = 2,195,456`
  `total = 30 * 2,195,456 = 65,863,680 bytes = 62.8125 MiB` → rounds to **63 MiB** (new test assertion, `kv.ssm_state_bytes(facts) == 65863680`)

- `test_breakdown_totals`'s total-bytes comment recomputed with the new SSM figure: 24.0374 weights + 0.8382 mmproj + 2.9219 KV + 0.0613 SSM (was 0.0600) = 27.8589 GiB, still rounds to **27.9 GiB** (verified with a standalone Python calculation before editing the test).

**Covering tests:** `tests/test_truth_kv.py::test_ssm_state_is_constant_in_context` updated to the new formula/values with the arithmetic in its docstring; new `test_ssm_state_without_group_count_matches_the_plain_formula` asserts `ssm_group_count=None` reproduces the exact old-formula byte count (61 MiB); `test_dense_model_has_no_ssm_state` updated to also pass `ssm_group_count=None`. `tests/test_truth_gguf.py::test_golden_ornith` gained `assert facts.ssm_group_count == 16`.

## Finding 6 (spec gap) — differential coverage across real GGUFs on disk

**Changed:** new file `tests/test_truth_differential.py`. Recursively globs `C:\Users\filth\models\**\*.gguf` (23 files found, including a duplicate tree under `SwarmUI\Models\unet` mirroring `Central\unet`), parametrized per file, `pytest.mark.skipif` on the whole module when the directory is absent. For each file, opens its own `gguf.GGUFReader`, calls `estimates._extract_kv_dims` (via `_extract_n_layer`/`_gguf_field_value` the same way `estimates._parse_gguf_meta` does) and skips (not fails) when it returns `None` — the non-text CLIP/video models (`mmproj-*.gguf`, `Wan2.2-*.gguf`). For every remaining file, asserts `(facts.total_kv_heads, facts.k_len, facts.v_len) == legacy_dims`. Marked `@pytest.mark.slow`; registered the `slow` marker in `pyproject.toml` (`[tool.pytest.ini_options]`) so `-m "not slow"` deselects it cleanly. Speed is bounded by Finding 3's on-disk cache (truth side) plus the pre-existing `estimates` on-disk meta cache (legacy side) — a warm re-run of just this file took well under a minute.

**Result:** 11 text models compared (Ornith, both Muse-Glimmer variants, both gemma-4 variants, Qwen3.8-27B UD, RVN, mtp-Qwen3.8-27B, Qwen3.8-27B-NVFP4-MTP-Q8attn), all agree; 12 skipped (4 mmproj + 4 Wan2.2 × 2 duplicate paths).

**Command / output:**
```
python -m pytest -v tests/test_truth_kv.py tests/test_truth_gguf.py tests/test_truth_shadow.py tests/test_truth_differential.py
...
============ 62 passed, 12 skipped, 2 warnings in 84.41s (0:01:24) ============
```

## Full-suite run (once, from repo root)

```
C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest -q
```
Result: `2 failed, 241 passed, 16 skipped, 2 warnings, 9 subtests passed in 245.40s`

The 2 failures are the pre-existing, out-of-scope `tests/test_lcc_core.py::PortAvailabilityTests::test_next_free_port_skips_windows_reserved_range` and `::test_windows_reserved_range_detected_via_probe` (`OverflowError: bind(): port must be 0-65535`) — identical to the baseline, not touched. Passed count grew from the 206 baseline to 241 (+35: new/expanded parametrize cases across Findings 1, 2, 3, 5) and skipped grew from 4 to 16 (+12: Finding 6's non-text-model skips). No new failures were introduced.

`models.json` was reverted with `git checkout -- models.json` before staging (the suite run dirties it via auto-discovery).
