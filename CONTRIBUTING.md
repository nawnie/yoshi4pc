# Contributing

## Where to start

- Read [docs/yoshi-status.md](docs/yoshi-status.md) for current bring-up milestones, solved issues, and active blockers (Movie 2 format-3 `NVNtexture *` output handling and the `program 1217` descriptor storage limit).
- [docs/architecture.md](docs/architecture.md) describes the overall host/lifter/Vulkan pipeline, [docs/nvn2-command-modes.md](docs/nvn2-command-modes.md) and [docs/bananza-shaders.md](docs/bananza-shaders.md) document NVN 2 / Ampere shader lowering inherited from `dkb-pc-recomp`, and [docs/building.md](docs/building.md) covers the Windows toolchain.

## The hard rule: no game content

Nothing extracted or derived from your copy of *Yoshi and the Mysterious Book* goes into the repository: no `.nup` containers, encryption keys, ExeFS/RomFS dumps, lifted C code, compiled binaries, shader caches, or raw frame/shader dumps. Only host runtime code, tools, tests, hashes (`tools/data/expected-yoshi131072.json`), and repo documentation belong here.

Two automated checks enforce this:

- GitHub Actions runs `tools/check_content.py` and `tests/check_content_test.py` on pushes and pull requests.
- Enable the local pre-commit hook once per clone:

  ```sh
  git config core.hooksPath .githooks
  ```

Never bypass a failing check with `--no-verify`.

## Licensing and third-party code

See [LEGAL.md](LEGAL.md) and [AGENTS.md](AGENTS.md). `yoshi4pc` is GPL-3.0-or-later as a whole (`LICENSE`), while upstream files from TotK Recomp keep MIT (`LICENSE-MIT`). Copy only compatible MIT / BSD / ISC / zlib / Apache-2.0 / GPL-3.0-compatible code, preserve headers, and record the upstream commit in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Reporting bugs

Use the issue forms under `.github/ISSUE_TEMPLATE/`:

- Include the commit hash (`git rev-parse --short HEAD`), GPU, driver version, OS, steps to reproduce, and excerpts from `logs\yoshi.log` next to `yoshi.exe`.
- Never attach `.nup` files, keys, extracted files, shader caches, or binaries.

## Pull requests

- Keep changes focused (one topic per PR).
- Run `python tools/check_content.py --staged` and `python tests/check_content_test.py`.
- Run differential Unicorn checks (`tests/yoshi_udot_check.py`, `docs/building.md`) after editing `recomp/` or `runtime/cpu.h`.
- Use plain-sentence commit messages without type prefixes (for example `Fix OP_BIND_PROGRAM 0x80 stage unbind in vk_exec_draw.c`).
- Never hand-edit generated C.
