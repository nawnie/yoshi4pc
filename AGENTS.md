# yoshi4pc (`Yoshi and the Mysterious Book` Recomp)

Experimental static recompilation of *Yoshi and the Mysterious Book* (Nintendo Switch 2, ARM64, Ver. `1.0.2` / title version `131072`) into a native Windows x86-64 executable (`yoshi.exe`) with a Vulkan renderer, forked from `dkb-pc-recomp` (itself built on `totk-pc-recomp`). Most of the lifter, host kernel, and Vulkan backend come from `totk-pc-recomp` and `dkb-pc-recomp`; see [docs/yoshi-status.md](docs/yoshi-status.md) for current bring-up status and [docs/architecture.md](docs/architecture.md) for architecture notes.

## Game content boundary

This repository is public. Game containers (`.nup`), keys, extracted ExeFS/RomFS trees, generated C files, compiled binaries, and shader caches stay outside git in ignored folders.

- Personal paths belong only in `config.local.toml` (ignored). Keys never appear in logs, outputs, commands, or commits.
- Everything extracted or generated goes under `build/` or `generated/` (or ignored `build-*/` and `generated-*/`).
- Every generated C file carries `GENERATED_MARKER` as defined in `tools/check_content.py`.
- Note on progress images: `tools/check_content.py` limits committed files to `MAX_BYTES = 1024 * 1024` (1 MiB) and blocks all `.nup` / Switch executable / container / asset formats (`subsdk2` included). Do not commit raw `.nup` assets, frame dumps (>1 MiB PNGs), or shader dumps.
- Run `python tools/check_content.py --staged` and `python tests/check_content_test.py` before committing.

## Reusing code

- Keep licenses clean: files originating from `totk-pc-recomp` retain MIT (`LICENSE-MIT`), while the repository as a whole is GPL-3.0-or-later (`LICENSE`) due to Eglantine's GPL Ampere shader lowering (`runtime/third_party/eglantine/`).
- Every copied snippet or helper must retain its copyright/license header and receive a row in `THIRD_PARTY_NOTICES.md` with upstream source and commit.
- `tools/vendor/` stays byte-identical to upstream.

## Code and workflow

- Build C/runtime targets on Windows with MSYS2 UCRT64 Clang (`C:\msys64\ucrt64\bin`). Generated C uses GNU extensions (`cl.exe` is unsupported).
- Python environments: `.venv` (Python 3.12) for lifting/building, `.venv-py314` (Python 3.14, stdlib `compression.zstd`) for `.nup` extraction and shader tools.
- Never hand-edit generated C: fix `recomp/` or `runtime/` overrides instead.
- Any lifter/SIMD change in `recomp/` must pass differential checks against Unicorn (`tests/yoshi_udot_check.py`, `docs/building.md`).
- Comments, documentation, and commit messages are in English; commit messages are plain sentences without conventional-commit type prefixes.
