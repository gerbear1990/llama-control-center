# Llama Control Center TODO

## Current Feature Pass

- [x] CUDA estimate automatically updates when settings are manually changed.
- [x] Full support for non-CUDA GPUs, including AMD, Intel discrete GPUs, and integrated GPUs.
- [x] Metal acceleration options when macOS is detected.
- [x] MLX runtime support.
- [x] Show fit status per profile using VRAM and RAM-aware estimates:
  - Good: green
  - Tight: orange
  - Near Limit: red
- [x] Include RAM in fit status when CPU/offload settings need host memory.
- [x] Show the CPU model in the header, not just core count.
- [x] Add a full benchmark option using the current selected parameters.
- [x] Store and display precise benchmark tokens/sec and other useful runtime measurements.
- [x] Commit finished work to `gerbear1990/llama-control-center`.
- [x] Generate a repository README with setup and run instructions.
