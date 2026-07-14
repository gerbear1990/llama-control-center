# NVFP4 on Windows with LCC

LCC launches Hugging Face NVFP4 checkpoints through vLLM inside WSL2. The
Windows dashboard remains the process owner and exposes the normal Start, Stop,
Logs, Metrics, Chat, and Benchmark controls. vLLM exposes an OpenAI-compatible
API on the profile's configured Windows localhost port.

## Validated stack

- Windows 11 with WSL2 and Ubuntu 24.04
- NVIDIA RTX 5090 (SM120)
- CUDA Toolkit 13.0 in WSL (`/usr/local/cuda`)
- Python 3.13 virtual environment at `/opt/lcc-vllm`
- vLLM 0.25.0 with PyTorch 2.11.0+cu130
- FlashInfer 0.6.13, `flashinfer-cubin`, and
  `flashinfer-jit-cache==0.6.13+cu130`
- `build-essential`, `ninja-build`, and `ffmpeg`

The CUDA-versioned FlashInfer JIT cache is required on a 64 GiB host. Without
it, compiling the SM120 FP4 runner while a 20+ GiB checkpoint is resident can
exhaust WSL memory. LCC's runtime preflight checks `cc`, `ninja`, `nvcc`, and
the FlashInfer JIT cache before marking the runtime launchable.

Do not install a Linux NVIDIA display driver inside WSL. The Windows driver is
projected into WSL; install the `cuda-toolkit-13-0` package only.

## Host configuration

The validated `C:\Users\<user>\.wslconfig` is:

```ini
[wsl2]
memory=48GB
swap=16GB
processors=16
localhostForwarding=true
```

Run `wsl --shutdown` after changing this file.

## LCC profile fields

An NVFP4 profile points `model_path` at the checkpoint directory containing
`config.json` and the sharded `model*.safetensors` files. Its
`recommended_params` should include:

```json
{
  "runtime": "vllm-wsl",
  "host": "127.0.0.1",
  "port": 18027,
  "alias": "qwen3.6-27b-nvfp4",
  "ctx_size": 8192,
  "gpu_memory_utilization": 0.9,
  "max_num_seqs": 32,
  "max_num_batched_tokens": 2048,
  "enable_auto_tool_choice": true,
  "tool_call_parser": "qwen3_coder",
  "reasoning_parser": "qwen3",
  "reasoning": false,
  "ready_timeout_seconds": 600
}
```

`max_num_batched_tokens` bounds prefill activation peaks without reducing the
advertised context length. The chat panel maps LCC's Reasoning toggle to
Qwen's `enable_thinking` template option and uses the served model alias, so
non-thinking chat and tool calls do not consume the token budget on hidden
reasoning.

## Operational notes

- Windows-hosted safetensors are read through WSL's 9P mount. Expect about
  90 seconds for the 27B checkpoint and 2.5 minutes for the 35B-A3B checkpoint
  on a cold start. Kernel and Torch graph compilation are cached after the
  first successful launch.
- Only run one large LCC model server at a time on a 32 GiB GPU. Background GPU
  applications reduce KV-cache headroom; the validated profiles coexist with
  roughly 3 GiB of other VRAM use.
- Profile endpoints are `http://127.0.0.1:<port>/v1`. LCC polls `/v1/models`
  for health and vLLM's Prometheus endpoint for request, KV-cache, and token
  counters.
- LCC Stop terminates the Linux API process and EngineCore descendants, then
  verifies the Windows WSL wrapper and endpoint are gone.

