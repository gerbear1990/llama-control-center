# SDD ledger — plan: docs/superpowers/plans/2026-08-21-ground-truth-layer.md

Spec: `docs/superpowers/specs/2026-08-21-ground-truth-layer-design.md` (read, reachable)
Worktree: `C:\Users\filth\llama.cpp-cuda\tools\lcc-ground-truth-layer`
Branch: `feat/ground-truth-layer` from `8ab846d`
Test interpreter: `C:/Users/filth/AppData/Local/Programs/Python/Python313/python.exe -m pytest`

## Baseline (clean checkout of 8ab846d, before any task)

`3 failed, 176 passed, 4 skipped` — pre-existing, NOT caused by this work:
- `tests/test_launch_smoke.py::LaunchSmokeTests::test_launch_smoke_18717`
- `tests/test_lcc_core.py::PortAvailabilityTests::test_next_free_port_skips_windows_reserved_range`
- `tests/test_lcc_core.py::PortAvailabilityTests::test_windows_reserved_range_detected_via_probe`

## Setup rulings

Ruling: work in a fresh worktree rather than in place — `tests/test_lcc_core.py` is BOTH operator-uncommitted-WIP and a file Task 1 must edit, so any in-place commit would sweep up their work. Cost if wrong: the operator merges `feat/ground-truth-layer` later and resolves one conflict in that test file.

Ruling: test with system Python 3.13 (pytest 9.1.1), not the project `.venv` — the venv has no pytest installed, so the plan's original command could never have run. Cost if wrong: nothing; both interpreters see the same `gguf` and `numpy`.

Ruling: the 3 baseline failures are out of scope — implementers and reviewers are told not to chase them. Cost if wrong: a real regression hides behind a known-failing name. Mitigated by requiring "no NEW failure" rather than "all green".

## Pre-flight conflict scan

### Cross-task: shared files and interfaces

| Producer | Consumer | Produced vs consumed | Finding |
|---|---|---|---|
| T1 `write_minimal_gguf(path,*,arch,n_layer,attn_layers,n_kv_heads,k_len,v_len,extra_kv)` | T2, T4, T5 | All three call with exactly those kwargs | Clean |
| T2 `ArchFacts` (15 fields) | T3 `_facts()` builds `ArchFacts(**base)` | 15 field names compared one by one | Clean — exact match |
| T2 `_facts_from_kv_and_tensors` | T4 `parse_header_bytes` calls it | Shared builder exists in T2 as written | Clean (was a defect; fixed pre-plan by moving the builder into T2) |
| T3 `breakdown(facts,*,weights_bytes,ctx,ctk,ctv,mmproj_bytes)` | T5 shadow calls with 5 kwargs | All keyword-only params supplied or defaulted | Clean |
| T2 `read_facts` | T5 shadow | Path arg | Clean |
| T1 `estimates.py` (`_extract_n_attn_layers`, `_KV_META_CACHE_VERSION`) | T5 `estimates.py` (`estimate_memory_fit`) | Same file, disjoint regions | Clean |
| T2 `tests/test_truth_gguf.py` | T4 appends to same file | T4 uses `pytest.raises`; T2 Step 6 adds `import pytest` first | Clean — ordering holds |

### Per-task: does each task's text agree with itself?

| Task | Check | Finding |
|---|---|---|
| T1 | Fixture tensor names vs `_layer_index_from_tensor` regex; asserted 10 pre-fix / 11 post-fix | Clean — **verified empirically** against a real 2,464-byte synthetic file before dispatch |
| T2 | `read_facts` return vs every test assertion; `n_ssm_layers` property = 41−11 = 30 | **DEFECT A** — see ruling |
| T3 | Every asserted number recomputed by hand | **DEFECT B** — see ruling |
| T4 | Parser error paths vs `pytest.raises` match strings; truncation offset reaches a length-prefixed read | Clean |
| T5 | 4 attn layers × 2 KV heads = 8; 8×64×2×2 = 2048 B/token × 4096 = 8.0 MiB; (10−8)/8 = 25% | Clean |

### Pre-flight rulings

Ruling: **DEFECT A** — `read_facts` and `parse_header_bytes` materialised every metadata field, including `tokenizer.ggml.tokens`/`merges`/`token_type` (~250k elements each on a modern vocab), costing seconds and hundreds of MB per call on a real model. Fixed both paths to skip `tokenizer.*` before dispatch; the remote parser still walks those bytes to stay aligned but discards them via a `keep=False` mode. Cost if wrong: none functionally — no memory-relevant field lives under `tokenizer.`.

Ruling: **DEFECT B** — `test_breakdown_totals` asserted 27.8 GiB, but the arithmetic gives 27.8575 → 27.9. The 27.8 figure came from the design discussion, which predated SSM state being added to the breakdown. Corrected the assertion to 27.9 with the component figures in a comment. Cost if wrong: a failing test on Task 3, caught immediately.

---

## Task log

Task 1: dispatched (implementer sonnet, BASE 7e932a7) — brief task-1-brief.md, report task-1-report.md
Task 1: implementer DONE (commit 0763e2c). Real-model check: n_attn 11, kv_dims (22,256,256) — exact match.
Task 1: review dispatched (sonnet) over 7e932a7..0763e2c
Note: baseline failure count is 2 OR 3, not fixed — the two PortAvailabilityTests depend on which
  local ports are free and flap between runs. Implementer saw 2 failed/179 passed vs my 3 failed/176
  passed; arithmetic reconciles (176 +1 flapped-to-pass +2 new = 179). Treat the port tests as flaky,
  not as a regression signal, for the rest of this plan.
Task 1: review clean — spec OK, quality Approved, 0 Critical/Important.
Task 1: minor (deferred): new tests are bare pytest functions in a unittest-style file (matches brief snippet, not implementer-introduced).
Task 1: minor (deferred): docstring step-2 wording slightly overstates "no known pattern" (estimates.py:196).
Task 1: warn resolved by controller — full_attention_interval is read ONLY at estimates.py:227 inside the fixed
  function; its sole consumer is _extract_kv_dims:254 -> _kv_head_total. No other code assumed the old order.
Task 1: warn resolved by controller — cache version genuinely gates at estimates.py:320/334; suite arithmetic
  already reconciled (no new failures).
Task 1: complete (commits 7e932a7..0763e2c, review clean)
Task 2: dispatched (implementer sonnet, BASE 0763e2c)
Task 2: implementer DONE (commit 4df7e4c). 4/4 new tests pass incl. golden test vs real 26GB Ornith model,
  which passed first run with no code changes. Suite 183 passed / 2 flaky-failed / 4 skipped.
Task 2: review dispatched (sonnet) over 0763e2c..4df7e4c
Task 2: review clean — spec OK, quality Approved, 0 Critical/Important.
Task 2: minor (deferred): no test exercises memo INVALIDATION after a real mtime/size change
  (test_truth_gguf.py:296-308 only asserts identity on an unchanged file). Inherited from brief.
Task 2: minor (deferred): no test exercises the `interval-metadata` or `assumed-dense` source
  branches — both new tests hit `tensor-scan` only. FLAG FOR FINAL REVIEW: these fallbacks decide
  KV count for models whose tensor names don't match the six patterns, so an untested wrong branch
  there reproduces the very class of defect Task 1 fixed. Inherited from brief scope.
Task 2: warn resolved by controller — full-suite numbers not re-run by reviewer, but arithmetic
  reconciles exactly (179 after T1 + 4 new = 183); nothing else moved.
Task 2: complete (commits 0763e2c..4df7e4c, review clean)
Task 3: dispatched (implementer haiku — pure transcription of complete code + arithmetic tests, BASE 4df7e4c)
Task 3: implementer DONE (commit 1f11e9f). 17/17 new tests pass; suite 200 passed / 2 flaky / 4 skipped
  (183 + 17 = 200, reconciles exactly).
Task 3: review dispatched (sonnet) over 4df7e4c..1f11e9f
Task 3: review clean — spec OK, quality Approved, 0 Critical/Important.
Task 3: arithmetic independently recomputed by reviewer, all 5 figures matched:
  22528 B/tok f16 | 11968 B/tok q8_0 | 5.5 & 2.9 GiB @262144 | 64,389,120 B SSM | 27.8575 -> 27.9 GiB total.
Task 3: minor (deferred): brief's step-4 note says "PASS (14 tests)" but the 9-case parametrize block
  makes 17. Brief inconsistency, not an implementer error.
Task 3: warn resolved by controller — suite arithmetic reconciles (183 + 17 = 200).
Task 3: complete (commits 4df7e4c..1f11e9f, review clean)
Task 4: dispatched (implementer sonnet — hand-rolled binary parser, not transcription-simple, BASE 1f11e9f)
Task 4: implementer DONE (commit ab15b65). Local-vs-remote agreement test PASSED. Suite 203/2/4 (200+3).
Task 4: review dispatched (sonnet) over 1f11e9f..ab15b65
Task 4: review — spec OK, quality Approved, byte-alignment traced and confirmed (all three _Cursor
  branches consume identical bytes whether keep=True/False). Truncation test confirmed non-accidental.
Task 4: warn ESCALATED by controller to a real gap (enters fix loop). Reviewer flagged the HTTP layer
  as unverifiable; on inspection it is defective, not merely untested:
  read_facts_remote does `buf = response.read()` UNBOUNDED while explicitly accepting HTTP 200.
  200 is what a server returns when it ignores the Range header, so the "read the header without
  downloading the body" function would read the entire 26 GB body. Contradicts its own docstring
  and the task's stated purpose.
  Ruling: fix rather than park — the defect nullifies the feature's reason to exist, and the fix is
  one line (`response.read(max_bytes)`) plus a non-network regression test. Cost if wrong: a bounded
  read on a range-supporting server is identical behaviour, so the downside is nil.
Task 4: fix round 1/5 dispatched (resumed original implementer)
Task 4: fix round 1 implemented (commit f05e784, 1-line fix + 41-line regression test). Suite 204/2/4.
Task 4: scoped re-review dispatched (haiku) over ab15b65..f05e784.

PRE-EXISTING DEFECT FOUND INCIDENTALLY — SURFACE TO USER, do NOT fix in this plan (out of scope):
  The two "flaky" PortAvailabilityTests fail with `OverflowError: bind(): port must be 0-65535`
  raised from lcc_core/server_manager.py. That is not flakiness — it means the port-search logic
  can compute a port number above 65535 and hand it to bind(). It exists on the base commit and is
  unrelated to this plan, but it is a real bug in the operator's code, not a test-environment quirk.
Task 4: fix round 1/5 (1 addressed, 0 open — unbounded remote read; commits ab15b65..f05e784).
  Re-review confirmed the test would FAIL against the old code (calls == [None] vs [len(data)]),
  so it is a genuine regression guard, not a passthrough assertion. Both 200 and 206 still accepted.
Task 4: minor (deferred): read_facts_remote still has no test against a real HTTP server
  (redirects, non-range servers). Out of scope per brief; the bounded read makes the failure mode safe.
Task 4: complete (commits 1f11e9f..f05e784, review clean after 1 fix round)
Task 5: dispatched (implementer sonnet — integration into estimates.py, BASE f05e784)
Task 5: implementer DONE (commit 76abb30). Suite 206/2/4 (204 + 2 new). estimates.py +14/-0.
Task 5: FIRST SHADOW DATA POINT — Ornith Q5_K_L @262144 q8_0: legacy 2992.0 MiB == truth 2992.0 MiB,
  delta 0.0%. Controller independently verified: 11968 B/tok * 262144 / 1024^2 = 2992.0 exactly.
  INTERPRETATION (carry into the follow-up plan): once Task 1 corrected the attention-layer count,
  the legacy KV arithmetic already matched the truth layer on this model. The 9% error was entirely
  the layer-count bug, NOT the estimator's KV formula. This is evidence AGAINST rushing the flip —
  the truth layer's remaining value is SSM accounting, provenance, unread facts (experts/MTP/mmproj),
  remote reads, and testability, not KV correction. Gather divergence across more architectures
  (especially non-hybrid and Gemma-style per-layer-array KV) before deciding.
Task 5: review dispatched (sonnet) over f05e784..76abb30
Task 5: review clean — spec OK, quality Approved, 0 Critical/Important.
Task 5: inertness verified TWICE — reviewer traced the block (touches only kv_cache_mib; assigns only
  block-locals _shadow/_m never read again); controller then verified empirically: two identical
  probe calls return an identical dict, and probe_model=False appends nothing (gate works).
Task 5: never-raises verified — double-wrapped (try/except at the estimates.py call site catching
  ImportError too, plus an inner try/except around shadow.py's whole body incl. mkdir/open/write).
Task 5: minor (deferred): `_m = model or {}` duplicates an earlier derivation (estimates.py:753).
Task 5: minor (deferred): delta_pct sign convention (legacy - truth) undocumented (shadow.py:35).
Task 5: complete (commits f05e784..76abb30, review clean)
ALL 5 TASKS COMPLETE. Dispatching final whole-branch review.

## FINAL WHOLE-BRANCH REVIEW (opus) — verdict: Merge after fixes

Headline positive: reviewer diffed estimates._extract_kv_dims vs truth.read_facts across ALL 14 GGUFs
on disk — all 10 text models agree exactly on (total_kv_heads, k_len, v_len), including gemma4's
per-layer-array KV (210 and 840 heads), Ornith 11/41, qwen35 hybrids 17/65 and 16/64, muse-glimmer,
dflash. So the 0.0% Ornith figure is not a sample of one; fact extraction is sound.

CRITICAL (controller-confirmed, MY plan's error): truth/kv.py CACHE_BYTES was a row-shifted
  transcription. Verified independently from ggml block structs: q4_0 = 18B/32 = 0.5625 (plan said
  0.5); q4_1 = 20B/32 = 0.625 (plan said 0.5625). NVFP4/MXFP4 absent from truth's table entirely so
  they fall to the 2.0 default while estimates has 0.5625/0.53125 — a -71.9% divergence on a model
  the operator actually owns. tests/test_truth_kv.py asserted ("q4_0", 0.5), locking the error in.
  Ruling: fix. It is wrong arithmetic in the one module whose entire claim is exact arithmetic, and
  it contaminates the shadow log that the flip decision depends on. Cost if wrong: nil, the legacy
  table is independently corroborated by the struct layouts.

IMPORTANT: _LAYER_RE covers 2 of the 5 conventions estimates._N_LAYER_PATTERNS covers (.h[N]. and
  block.N. dropped) -> false "assumed-dense" provenance + 3.7x KV on such a model. Latent (nothing on
  disk uses those names) but a lying provenance label defeats the spec's stated fix. Ruling: fix.

IMPORTANT: shadow mode adds ~5.5s to the first interactive estimate per model per restart, because
  truth's memo is in-process only while estimates has an on-disk cache. Shadow was specified as zero
  user-visible risk, so this violates its own acceptance criterion. Ruling: fix by mirroring the
  legacy on-disk cache.

Ruling: substitute ONE differential test (truth vs estimates across every GGUF on disk) for the
  spec's five enumerated golden fixtures. Strictly stronger — covers the same models AND guards the
  drift risk the review named as the live cross-cutting hazard, which hardcoded goldens would not.
  Cost if wrong: the test depends on the operator's model dir, so it skips on any other machine.

Ruling: defer ArchFacts.quant_type (spec-named but unconsumed by steps 0-3; Breakdown takes
  weights_bytes directly). Cost if wrong: a follow-up task adds one field.

Deferred minors accepted per reviewer triage: bare-pytest style, docstring wording, memo-invalidation
  test, interval/assumed-dense tests (reviewer proved both branches equivalent to legacy
  algebraically and in the wild), brief test-count typo, no real-HTTP test, _m duplication.
Also deferred per reviewer: array-length validation on the per-layer KV path, n_layers read only from
  block_count, no plausibility clamp in truth. All three are shared-logic or latent; recorded for the
  follow-up plan.

Housekeeping: running the suite dirties tracked models.json (+72 auto-discovered models) — a
  PRE-EXISTING test side-effect, not this branch. Reverted in the worktree; flag to operator.

Final fix wave: dispatched ONE fixer (sonnet) covering findings 1-6.

## Final fix wave + scoped re-review — ALL SIX ADDRESSED, no new breakage

Re-reviewer independently reproduced every corrected constant from the ggml struct layouts
(incl. NVFP4 36/64 = 0.5625, MXFP4 17/32 = 0.53125) and confirmed the new differential test is NOT
vacuous: replaying the old table against its 17 params fails on exactly 4 (q4_0, q4_1, nvfp4, mxfp4).
Finding 5 arithmetic reproduced: (4-1)*(4096 + 2*16*128) + 4096*128 = 548864, x4B x30 = 65,863,680 B
= 62.81 MiB -> 63; with group_count None it returns to 61.42 MiB, i.e. exactly the old formula.
Differential test: 11 text models compared and passing, 12 skips all genuine non-text (4 CLIP mmproj
+ 8 Wan video across duplicated Central/SwarmUI trees) — accounts for the whole 4->16 skip delta.

### Residual findings — adjudicated and PARKED (none load-bearing)

Ruling: park the three on-disk-cache notes (version gate is a no-op until the first bump; a
  valid-JSON-but-non-dict entry would AttributeError outside the inner guard; a stale entry silently
  yields None for a newly added ArchFacts field). All three are exact parity with the already-shipped
  estimates.py cache, so they are pre-existing exposure this branch mirrors rather than introduces,
  and shadow's own except still contains the middle one. Cost if wrong: a corrupt cache file
  recomputes instead of raising — the degradation is in the safe direction.

Ruling: park the `legacy_exact` synthesised-dict note. Verified safe in current code —
  estimates.py:737 calls _kv_dims(model, probe=True) before the shadow call at :755, warming the
  cache, and nothing anywhere sets a `kv_dims` key on a model dict. Latent only. Cost if wrong: one
  boolean in a diagnostic log reads False when it should read True; the KV figures are unaffected.

Ruling: park the differential test's 212 s warm runtime (it opens its own GGUFReader per file,
  bypassing the legacy meta cache). It carries the `slow` marker and is deselectable with
  -m "not slow". Cost if wrong: a slow full-suite run, already mitigated.

Ruling: preserve this ledger and the fix report in git under docs/superpowers/ before deleting the
  SDD workspace. The skill says git history becomes the record, but the deferred-findings list and
  the shadow-mode interpretation are the direct inputs to the follow-up plan and are not recoverable
  from commit messages. Cost if wrong: two extra markdown files in the repo.

BRANCH COMPLETE: 7 commits, 8ab846d..fc5d416. Suite 241 passed / 2 pre-existing failed / 16 skipped.
