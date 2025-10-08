# Changelog
All notable changes to this project will be documented in this file.

## [2.0.0] - 2025-10-08
### Added

- LoRA Hooks bundle: compact toolkit for LoRA on MODEL/CLIP
- Selectors: set of selector helper nodes used to pick model file names
- PgCpSwitch — two‑way switch for (MODEL, CLIP, VAE) triplets.
- PgSwapCFGGuidance — two‑phase CFG guider (CFG1 → early, CFG2 → late).
- PgPercentFloat — INT 0..100 → FLOAT 0..1 helper.

### Updated
- Unified Loader: CLIP auto‑detection.

## [1.0.0] - 2025-09-24
### Added
- Initial public release.
- Nodes: Lazy Prompt (+mini), Unified Loader (+mini), Just Save Image (+Out).
- Prompt history JSON + config file `PG_Lazy_Prompt_Config.json`.

## [1.5.0] - 2025-09-25
### Added
- Lazy Prompt (ext).

## [1.5.5] - 2025-09-25
### Fix
- "Unified Loader", DIFFUSION_MODEL output fix and Class name.
