# Changelog

## 0.1.3 (2026-10-01)
- `config.yaml` is no longer tracked. The repository ships `config.example.yaml` with placeholders; copy it to `config.yaml` (git-ignored) on each machine.
- `.gitignore` grouped by risk: real config, credentials, survey and client data, model weights and outputs, company documents, runtime state, archives.
- `tools/check_secrets.sh` and `tools/install_git_hook.sh`: pre-commit check for company words (from the git-ignored `.secret-patterns.local`), private IPs, keys, passwords, blocked file types and files over 5 MB.
- Demo data, mock classes, tests and docs use placeholder names instead of internal site, user and model names.

## 0.1.2 (2026-10-01)
- App icon (`assets/`), web app manifest and favicon. Edge and Chrome can install Pixel Muncher as an app window.
- `launchers/macos/make_app.sh` builds `Pixel Muncher.app`. It starts the server if needed and opens an app window.
- `launchers/linux/install_desktop_icon.sh` adds a menu and desktop icon on the workstation.
- Power button in laptop modes (`--mock`, `--local`) stops the server.

## 0.1.1 (2026-10-01)
- `./run.sh --local`: test on a laptop with your own .tif. Tiling is real (GDAL), classification is fake.
- `./run.sh --check`: verify paths, models, results folder, GPU and disk space, then exit.
- Built-in map (*Open map*): classification over the orthomosaic with an opacity slider, works offline.
- `config.site.yaml` (git-ignored) overrides `config.yaml`, so `git pull` does not conflict with workstation paths.
- Tiling can run as `python -m osgeo_utils.gdal2tiles` (`tiling.script: module:osgeo_utils.gdal2tiles`).
- Requires Python 3.10+ and NiceGUI 3.

## 0.1.0 (2026-10-01)
- First version: New run wizard with preflight checks, persistent single-GPU job queue,
  live log and progress, cancel and re-run, results organised as in Manual 8.4.6,
  `run_manifest.json` for traceability.
