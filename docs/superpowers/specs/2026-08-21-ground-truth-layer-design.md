# Ground-Truth Layer — Design

**Date:** 2026-08-21
**Status:** Approved design, not yet implemented
**Scope:** `lcc_core/truth/`, `lcc_core/estimates.py`, `lcc_core/fit.py`, params panel in `lcc_api/static/`

---

## Problem

The LCC TODO list is almost entirely complete — Smart Fit, bandwidth-aware estimates, benchmark capture, HF integration, draft-model suggestions, watchdogs, live metrics and sampling presets all shipped. The tool is nonetheless still hard to use. Three failure modes, confirmed with the operator:

1. **The numbers are not trusted.** Fit says Good and reality OOMs, or says Tight when there was room. The operator hand-tunes and watches `nvidia-smi` anyway — the exact work LCC exists to remove.
2. **Too many knobs, no guidance.** The params panel is a flat list. Nothing tells the operator which three flags matter for the model in front of them.
3. **It rots.** New architectures, renamed flags, rebuilt binaries and `models.json` churn break assumptions scattered across roughly 22,000 lines.

These are one root cause: **LCC models llama.cpp by hand instead of asking it.**

- `estimates.py` (1,002 lines) predicts memory that llama.cpp itself computes and prints at load time, using tunable coefficients (`_quant_factor`, `_gpu_factor`, `_layer_fraction`).
- `backends.py` (426 lines) encodes which flags exist — a copy that goes stale on every rebuild.
- Nothing records what actually happened on a real load, so no prediction is ever checked against reality.
- No figure carries provenance, so a well-founded number and a guess render identically.

Each is written-down knowledge about a moving target. That is what rots, and what lies when stale.

**What is already right, and must not be rebuilt:** `estimates.py` already opens GGUFs with the
`gguf` package, already extracts layer counts, KV dimensions and context length, already
distinguishes attention layers from SSM layers in hybrid architectures (its docstring names Qwen3.5
and Jamba), and already caches results on size+mtime. The problem is narrower than "it does not
read metadata."

### Worked example: measured, not assumed

`Ornith-1.5-35B-A3B` (arch `qwen35moe`) is a hybrid: only **11 of 41 layers** hold a per-token KV
cache; the other 30 are gated-delta SSM layers with constant-size state.

`_extract_n_attn_layers` has two detection paths, and the wrong one wins:

```
priority 1  full_attention_interval:  41 // 4     = 10   <- short-circuits, wins
priority 2  tensor scan:              attn_k scan = 11   <- correct, never reached
layers carrying attn_k.weight: [3, 7, 11, 15, 19, 23, 27, 31, 35, 39, 40]
```

The integer-division shortcut misses the MTP layer at index 40. Measured against the real file:
**20.0 KiB/token instead of 22.0 — KV underestimated by 9%**, or 5.0 GiB instead of 5.5 GiB at
262k context.

Nine percent sounds survivable, but the sign is what matters: an *underestimate* is the direction
that reports Good and then OOMs. At Q5_K_L the half gigabyte is the difference between 29.9 and
30.4 GiB against a practical ceiling near 30 GiB. This is complaint 1, reproduced exactly.

The lesson generalises: the tensor list is ground truth, derived metadata shortcuts are not, and
nothing in the codebase currently checks either against a real load.

---

## Goals

- Fit figures that are either exact arithmetic or measured fact, each labelled with which.
- A params panel showing only the knobs that matter for the selected model, each with a generated reason.
- Absorb llama.cpp changes instead of chasing them.
- Net reduction in lines of code.

## Non-goals

- Rewriting the dashboard, the profile model, or the visual system. Ceremony was explicitly **not** a reported pain point.
- The parked Obsidian Rail overhaul in `TODO.md` stays parked.
- Multi-runtime parity. llama.cpp is the wired path; others stay detection-only.
- Auto-correcting estimates against measurements. See Divergence below.

## Audience constraint

"Me first, shareable if it gets good." Defaults and polish may specialise to the operator's host. The core mechanism must stay host-agnostic — which introspection is by nature, since asking the local binary and the local file works on any machine, while a heuristic tuned to one box does not.

---

## Architecture

One new package, `lcc_core/truth/`. Organising rule: **each module answers one question from one source, and none of them has an opinion.**

```
gguf.py ──► kv.py ──┐
build.py ───────────┼──► relevance.py ──► API ──► UI
observed.py ────────┘
```

A fan, not a chain. `gguf` and `kv` do not know subprocesses exist. `build` does not know what a model is. `observed` parses a string. Each is testable alone.

### truth/gguf.py — what is this model?

**This is a consolidation, not a new parser.** The `gguf` package is already a project dependency
(`gguf>=0.19.0`) and `estimates.py` already uses `GGUFReader`. The extraction logic exists but is
scattered across seven private functions in a 1,002-line module, where it cannot be tested or
reused. This module moves that logic behind one typed interface, fixes the attention-layer
detection order, and adds the one capability `GGUFReader` cannot provide: remote reads.

```python
read_facts(path: Path) -> ArchFacts              # wraps gguf.GGUFReader
read_facts_remote(url: str) -> ArchFacts         # HTTP range request, no download
```

`ArchFacts` carries: `n_layers`, `attn_layer_indices`, `n_kv_heads`, `k_len`, `v_len`, the SSM
parameters (`conv_kernel`, `state_size`, `group_count`, `inner_size`), `n_experts`,
`n_experts_used`, `has_mtp`, `needs_mmproj`, `native_ctx`, `quant_type`.

**Correctness change: the tensor scan becomes primary, `full_attention_interval` the fallback.**
The current priority order is inverted, which is the Ornith 10-vs-11 defect. Tensor names are
ground truth; interval metadata is a derived shortcut that cannot see the MTP layer. The interval
path is retained only for files whose tensor names do not match any known pattern.

`read_facts_remote` uses an HTTP range request against `resolve/main/<file>` to read the header
without the body, so fit can be answered *before* committing to a download of tens of gigabytes.
`GGUFReader` memory-maps a local file and cannot do this; that path is hand-rolled and small.

Existing behaviour to preserve: the size+mtime cache in `estimates.py` (reading a multi-GB header
costs 5-11 seconds) and the `_TOOL_TEMPLATE_MARKERS` jinja detection, which is orthogonal to fit
and stays where it is.

### truth/kv.py — what will it cost?

```python
kv_bytes_per_token(facts, cache_type) -> int
ssm_state_bytes(facts) -> int
breakdown(facts, weights_bytes, ctx, ctk, ctv, mmproj_bytes) -> Breakdown
```

Pure arithmetic, zero I/O. The purity is the point: it makes the module exhaustively testable, which is what converts "trustworthy" from a claim into a test result.

### truth/build.py — what does this binary accept?

```python
probe(binary: Path) -> BuildFacts   # version, build number, commit, flag universe, archs
```

Cached on `(path, mtime, size)`. The flag universe is parsed from `--help`.

**Known weakness:** architecture support has no clean interrogation path. Detection is by binary string scan — validated, in that a control string correctly returns zero hits — backed by an authoritative fallback of attempting a metadata-only load and catching the specific refusal. This is the least elegant corner of the design.

Motivating incident: on 2026-08-17 `C:\Users\filth\llama.cpp-cuda` was rebuilt in place from b10021 to b10472, while two reference documents continued to describe it as stale and unusable. Directory name and documentation both lied; only `--version` told the truth.

### truth/observed.py — what actually happened?

```python
parse_load_report(stderr: str) -> Measured   # KV self size, compute buffer, model buffer
record(model_key, params_key, measured) -> None   # append-only JSONL
lookup(model_key, params_key) -> Measured | None
```

llama.cpp already prints every figure of interest at load time. Nothing was reading it.

---

## Data flow

```
profile ──► gguf.read_header (cached: mtime+size) ──► ArchFacts
binary  ──► build.probe      (cached: mtime)      ──► BuildFacts
                                                          │
observed.lookup(model_key, params_key) ──────────► kv.breakdown()
            │                                             │
            └──── measured (n runs) ◄──┬──► computed ◄────┘
                                       ▼
                        UI renders ONE number + its provenance
```

### Provenance is mandatory

No bare numbers. Every figure renders in exactly one state:

| State | Meaning |
|---|---|
| `computed` | Arithmetic from GGUF facts |
| `measured · n runs` | Observed from real loads |
| `unknown` | Header unreadable or architecture unmodelled — say so |

The current estimator emits a number with no epistemic status, so a good figure and a bad one look identical. That is the trust defect, and provenance is the fix.

On launch, stderr is teed to `parse_load_report()`. From the second run onward the profile shows measured.

### Divergence is a defect signal, not a correction factor

When `computed` and `measured` disagree beyond threshold, show both and flag it. The flag points at a modelling gap in `kv.py` to be fixed.

It must **not** feed back as an auto-correction. A self-correcting fudge factor conceals the very modelling errors it compensates for; the flag makes them visible. One approach is self-correcting, the other self-deceiving.

---

## Knob relevance

`relevance.py` intersects `ArchFacts` with `BuildFacts.flags` and emits a ranked short list.

| Trigger | Effect |
|---|---|
| `needs_mmproj` | `--mmproj` promoted to required |
| `n_experts > 0` | `--n-cpu-moe` becomes the offload lever; `-ngl` demoted |
| `has_mtp` | Draft-model section hidden; self-speculation available |
| No MTP, sibling exists | Draft-model section shown with suggestions |
| KV bytes x ctx large against free VRAM | `-ctk`/`-ctv` promoted — highest-leverage fit lever |
| ...small | `-ctk`/`-ctv` demoted — would cost quality for no gain |
| SSM/hybrid layers present | Note that long context is cheap on this model |

Ranked by **GiB moved**, computed via `kv.py`, so the ordering is arithmetic rather than a maintained opinion. Each surviving knob carries a generated one-line reason specific to the model.

### Ornith Q5_K_L, derived

- `--mmproj` — required; mrope sections `[11,11,10,0]`, vision tensors present
- `-c 262144` — native context; 11 of 41 layers cache per token, so 262k costs 5.5 GiB, not 20
- `-ctk/-ctv q8_0` — 5.5 to 2.9 GiB; this is what makes Q5_K_L fit at full context
- `--n-cpu-moe` — 256 experts, 8 active; the headroom lever if one is needed
- Draft-model UI — suppressed, MTP layer present

Four knobs and one suppression out of roughly forty, with no per-model configuration. A model downloaded next year receives the same treatment with no code change — the rot fix appearing as a side effect rather than as a separate feature.

---

## Error handling

Degrade per field, never guess, fail toward showing more.

| Failure | Behaviour |
|---|---|
| GGUF truncated or bad magic | Fit renders `unknown`, not a fallback estimate |
| Architecture present but unmodelled | Partial facts: layer count and quant reported, KV marked `unknown` |
| `build.probe` fails | Flag universe unknown, so show all knobs; never silently hide one |
| Profile references a dropped flag | Warn with the rename at edit time; block launch |
| Range requests unsupported | Prompt to download then inspect; never silently pull tens of GB |
| Log unparseable | Store raw, mark measured unavailable, continue with `computed` |

---

## Testing

1. **Golden fixtures** — derive `ArchFacts` for each GGUF already on disk (Ornith, Muse Glimmer, the three Qwen3.8-27B variants, gemma-4) and assert against hand-verified values.
2. **Pure arithmetic tables** — `kv.py` has no I/O. The adversarial cases are already on disk: the 11-of-41 Ornith hybrid, Muse Glimmer's 32Q/2KV GQA and sliding-window split, MoE expert counts, and whether the MTP layer's KV is counted.
3. **Measured reconciliation** — load each model for real once, capture the KV size llama.cpp prints, and assert `breakdown()` matches **within 2%** on the KV and model-buffer figures. The compute buffer is excluded from the assertion: it varies with batch size and backend, and is recorded rather than predicted. Marked `pytest -m gpu`, opt-in, never in the default run: the host rule against taking VRAM unasked shapes the test design rather than fighting it.

---

## Sequencing

Each step is independently valuable and independently revertible.

0. **Ship the attention-layer fix on its own.** Invert the detection order in
   `_extract_n_attn_layers` and bump `_KV_META_CACHE_VERSION` to invalidate stale cache entries.
   A few lines, an immediate 9% correction on hybrid models, and it stands alone if nothing else
   in this spec is ever built.
1. `truth/gguf.py` + `truth/kv.py` + golden fixtures. Pure, no integration, provable in isolation.
2. **Shadow mode.** Compute `kv.breakdown()` alongside the existing estimator, log divergence,
   surface nothing. Validates against reality at zero user-visible risk, and produces the evidence
   for step 3.
3. Flip fit to ground truth, add provenance labels, delete the coefficient paths in `estimates.py`.
4. `truth/build.py` plus flag validation against the live binary.
5. `truth/observed.py` plus measured reconciliation.
6. `relevance.py` plus the derived-knob params panel.

Step 0 alone fixes a real, measured error. Steps 1 to 3 close complaint 1. Step 4 closes
complaint 3. Step 6 closes complaint 2.

**Plan split:** steps 0-3 form the first implementation plan and deliver trustworthy fit on their
own. Steps 4-6 get a second plan once the first is landed and the divergence data from shadow mode
is available to inform it.

---

## Risks

- **`observed.py` parses log text**, so it is itself a rot surface. Mitigated by being small, isolated and failing gracefully — but it is the weakest joint in this design.
- **Architecture detection in `build.py`** is the inelegant corner, backed by a load-attempt fallback.
- **`kv.py` will need extending** for genuinely new attention families such as MLA. That is modelling real structure rather than adding fudge factors, and the divergence flag reveals when it is needed instead of leaving it to be discovered through an OOM.

## Open questions

- Divergence threshold before flagging: proportional, absolute, or both.
- Whether shadow mode (step 2) ships to the operator or stays on a local branch.
- Whether `models.json` should cache `ArchFacts` for faster startup, at the cost of another staleness surface, or always re-derive from file mtime.

---

## Execution findings (steps 0-3 landed 2026-08-21)

Recorded here because they change the argument for step 3.

### The flip is less urgent than this spec assumed

Shadow mode's first real data point: `Ornith-1.5-35B-A3B-Q5_K_L` at 262144 ctx, q8_0 KV —
legacy **2992.0 MiB**, truth **2992.0 MiB**, divergence **0.0%**.

Once step 0 corrected the attention-layer count, the legacy estimator's KV arithmetic already
matched. **The 9% error was entirely the layer-count bug, not the KV formula.** A cross-check over
every GGUF on disk found `estimates._extract_kv_dims` and `truth.read_facts` agree exactly on all 10
text models — including gemma-4's per-layer-array KV (210 and 840 heads), both qwen35 hybrids,
muse-glimmer and dflash.

So the truth layer's remaining value is **not** KV correction. It is: SSM state accounting the
estimator never modelled, provenance labels, facts the estimator never read (expert counts, MTP,
mmproj requirement), remote pre-download reads, and testability. Weigh step 3 on those, not on
"the numbers are wrong".

### Deferred, for whoever picks up steps 4-6

- `ArchFacts.quant_type` — named in this spec, not implemented; nothing in steps 0-3 consumes it.
- No test covers memo/disk-cache **invalidation** after an mtime change (same key scheme as the
  already-shipped `estimates` cache).
- No unit test covers the `interval-metadata` or `assumed-dense` source branches. Both were verified
  equivalent to the legacy path by hand and in the wild; `len(range(i-1,n,i)) == n//i` for all n, i>=1.
- `truth` reads `n_layers` only from `{arch}.block_count`; `estimates` also tries `{arch}.n_layer`
  and a tensor max-index scan. A file with only `n_layer` yields `None` and silently disables both
  fallbacks.
- `truth` has no plausibility clamp; `estimates` rejects `total_kv_heads > 200000` and dims > 4096.
  A misread field currently yields a confident `provenance="computed"` where `unknown` exists.
- The per-layer-array KV branch never validates array length against the attention-layer count. Both
  implementations share this logic, so shadow mode is structurally blind to it.
- `read_facts_remote` has no test against a real HTTP server (redirects, non-range servers). The
  bounded read caps the blast radius at `max_bytes`.
- `tests/test_truth_differential.py` takes ~212 s warm; it is `slow`-marked, deselect with
  `-m "not slow"`.

### Pre-existing defects found while working here — NOT caused by this work

- `lcc_core/server_manager.py` can compute a port above 65535 and pass it to `bind()`, raising
  `OverflowError: bind(): port must be 0-65535`. Two `PortAvailabilityTests` fail on it.
- Two `tests/test_launch_smoke.py` tests fail with `TimeoutError` on a socket read.
  Both confirmed failing identically on base commit `8ab846d`.
- `pytest` at the repo root collects the gitignored vendored `graphify/` checkout — ~2,900 extra
  tests, ~46 failing for unrelated reasons. Run `pytest tests/` for this project's own suite.
  `graphify/tests/__init__.py` also shadows a `tests.`-prefixed import, which is why test modules
  here import `gguf_fixtures` bare.
