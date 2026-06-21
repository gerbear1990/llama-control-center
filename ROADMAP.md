# Roadmap

This roadmap collects candidate features before they are designed and scheduled.
Items here are not release promises; they are the working direction for the next
passes.

## Completed

- Runtime cards show each runtime's binary/module location, API or probe URL,
  and port. Added in `v0.1.1`.
- Full UI pass over spacing, responsive behavior, visual hierarchy, modal
  patterns, focus management, color contrast, and version surface. Added in
  `v0.1.2`.

## Runtime Management

- Add automatic runtime update checks.
- Let users choose an update channel in settings, such as stable or another
  release stream when the runtime supports it.
- Add a small apply-update button on runtime cards when an update is available.

## UI Polish

- Continue iterating on spacing, alignment, and visual hierarchy as new
  panels are added.
- Keep the style clean, modern, and utilitarian rather than decorative.

## Draft Models

- Suggest compatible draft models for the selected profile and base model.
- Offer optional Hugging Face pulls for compatible draft models.
- Detect the Hugging Face CLI and use it when available for model downloads.

## Hugging Face Tooling

- Add a main-page Hugging Face CLI widget that can:
  - detect whether the CLI is installed,
  - show the installed version,
  - offer install guidance or an install action when missing,
  - check for CLI updates,
  - apply a CLI update when the user chooses it.
- Add a selected-model update check against Hugging Face.

## Estimates And Hardware Detail

- Push speed estimates toward high confidence when model metadata, runtime
  backend, GPU, VRAM, RAM, and benchmark calibration data are available.
- Fall back clearly to medium or low confidence when inputs are incomplete.
- Detect RAM DDR generation, speed, and estimated bandwidth where available.
- Detect VRAM memory generation, speed, and estimated bandwidth where available.
- Feed RAM and VRAM speed/bandwidth into tokens/sec estimates and fit scoring
  when the signal is reliable enough to help.

## Ollama

- Add full Ollama integration.
- Let users choose Ollama as their preferred source/runtime flow instead of
  Hugging Face where appropriate.
- Support Ollama model discovery, launch/status display, model pulls, and
  update flows in the same dashboard language as local GGUF profiles.
