# yoshi4pc — *Yoshi and the Mysterious Book* Recomp

**Research project:** experimental static recompilation of *Yoshi and the Mysterious Book* (Nintendo Switch 2, ARM64, **Ver. 1.0.2** / title ID `0400245021D2C000`, title version `131072`) into a native Windows x86-64 executable (`yoshi.exe`) with a Vulkan renderer.

Forked from [`dkb-pc-recomp`](https://github.com/Lucas-blip-png/dkb-pc-recomp) (itself built on [`totk-pc-recomp`](https://github.com/valentderah/totk-pc-recomp)).

> [!IMPORTANT]
> **Research only. No game assets are included in this repository.** It contains no game containers, keys, extracted game files, game footage, or compiled game binaries. You must provide your own legally obtained game dump to build or run it.

> [!NOTE]
> **Project Status (Pre-Gameplay WIP):** Boots through startup, plays the H.264 format-4 intro island movie via Windows Media Foundation, renders the title screen (`Ver. 1.0.2`) and animated profile menu (`41.3–42.4 fps`, `0` skipped draws/frame), and opens the local offline profile. Gameplay does not start yet due to the Movie 2 format-3 `NVNtexture *` cutscene stall after selecting `New Game`. See [docs/yoshi-status.md](docs/yoshi-status.md).

---

## Progress & known issues

| Subsystem | Status | Notes |
|---|---|---|
| ExeFS verification (`main`, `rtld`, `sdk`, `subsdk0..2`, `main.npdm`) | Working | Verified against SHA-256 hashes in [tools/data/expected-yoshi131072.json](tools/data/expected-yoshi131072.json) |
| ARM64 static lifter (`recomp/gen.py`, `recomp/simd_c.py`) | Working | Added `UDOT` vector lifting + `RET`-bounded `ADR`/`BR` callback discovery |
| Console load-order dynamic linking (`runtime/loader.c`) | Working | Resolves shared movie TLS singletons consistently across `sdk` & `subsdk2` |
| Kernel, FS directory listing, IPC domains (`bsd`/`ssl`/`fsp-srv`) | Working | Boots offline with single local user (`nn::account`, `nn::time`, `nn::fs`) |
| SDL3 `AudioOut` pacer + H.264 format-4 movie playback | Working | Plays intro island movie via Media Foundation (`runtime/movie_avc_win.c`) |
| Title & profile rendering (`Vulkan` + `NVN 2` + Ampere lowering) | Working | Fixed `OP_BIND_PROGRAM` `0x80` unbind (`0` skipped draws/frame at `41.3–42.4 fps`) |
| Cutscene Movie 2 (`format 3` `NVNtexture *`) on `New Game` | **Blocked** | `AcquireOutputBufferIndex` / `GetOutputBuffer` loop produces black frames and never calls `ReleaseOutputBufferIndex` |
| Compute shaders in `program 1217` (`e1f058...`, `fddd96...`) | **Open** | `totk_xlate.exe` hits `NotSupportedException: Storage candidates exceed the descriptor resource limit` (`disp nosh=2`) |

Full engineering notes live in [docs/yoshi-status.md](docs/yoshi-status.md).

---

## Building from source (Windows)

`yoshi4pc` ships **zero game files, keys, generated C, compiled binaries, or shader caches**. You must provide your own legally dumped Switch 2 copy of *Yoshi and the Mysterious Book* (Ver. `1.0.2`, title version `131072`).

See [docs/building.md](docs/building.md) for prerequisite versions (MSYS2 UCRT64 `clang`/`lld`/`ninja`, `.NET 10 SDK` + VS 2026 C++ Build Tools for `totk_xlate.exe`, Vulkan SDK, `uv`, Python 3.12 & 3.14).

### 1. Create Python environments

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r tools\requirements.txt
uv venv --python 3.14 .venv-py314
uv pip install --python .venv-py314\Scripts\python.exe -r tools\requirements-py314.txt
```

### 2. Enable the local content-guard pre-commit hook

```sh
git config core.hooksPath .githooks
```

### 3. Extract your `.nup` container (to ignored `build/`)

```powershell
.venv-py314\Scripts\python tools\extract_nup.py path\to\yoshi.nup --select latest --pack --out build\extracted\yoshi131072
```

(`--pack` extracts the ExeFS modules and packs RomFS directly into `romfs.bin` and `index.json` without a separate unpack step; use `tools\dkb_pack_romfs.py --dir <romfs> --out <out>` if extracting from an already-unpacked RomFS folder.)

### 4. Build the shader translator (once; no game files)

```powershell
.venv\Scripts\python tools\build_xlate.py
```

### 5. Lift and compile `yoshi.exe`

```powershell
.venv\Scripts\python recomp\gen.py --exefs build\extracted\yoshi131072\exefs --out generated\yoshi131072
.venv\Scripts\python tools\build_game.py --version yoshi131072 --expected tools\data\expected-yoshi131072.json
```

### 6. Run

```powershell
build\yoshi131072\yoshi.exe
```

Useful runtime environment variables (`set NAME=value` before launch; `YOSHI_*` aliases `DKB_*` and `TOTK_*`):

- `YOSHI_PROFILE_DIR=<path>` — use an isolated save/profile directory (`yoshi.ini` is stored next to `yoshi.exe`; logs write to `logs\yoshi.log` next to `yoshi.exe`).
- `TOTK_TRACE=perf` — print periodic frame rate, draw/dispatch counts, and skip telemetry.
- `TOTK_GPU=null` — run without Vulkan rendering for CPU/OS/service debugging.

---

## Legal & license

- Read [LEGAL.md](LEGAL.md) and [SECURITY.md](SECURITY.md). Nothing extracted or derived from `.nup` containers or game executables may be pushed to this repository (`tools/check_content.py` enforces a 1 MiB ceiling and blocks Switch containers, ExeFS modules including `subsdk2`, `.nup` packages, keys, and generated C markers).
- Licensed under **GPL-3.0-or-later** as a whole ([LICENSE](LICENSE)) because it includes Eglantine's GPL Ampere shader lowering (`runtime/third_party/eglantine/`). Files inherited from TotK Recomp keep **MIT** ([LICENSE-MIT](LICENSE-MIT)).
- Full third-party and upstream credits are documented in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) (`dkb-pc-recomp`, `totk-pc-recomp`, `Eglantine`/`Eden`, `Ryujinx`, `MacNativeGames`, `LAS Recomp`, `d2r-mobile`, `nxnative`, `SavageWindRecomp`, SDL3, VMA, Dear ImGui).
