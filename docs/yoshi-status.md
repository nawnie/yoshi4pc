# Yoshi and the Mysterious Book (`yoshi4pc`) — Current Status

Target verified against ExeFS hash manifest [tools/data/expected-yoshi131072.json](../tools/data/expected-yoshi131072.json):

- **Title ID:** `0400245021D2C000`
- **Version:** `Ver. 1.0.2` (`title_version`: `131072`, `display_version`: `update 131072`)
- **ExeFS modules (`subsdk2` included):** `main`, `main.npdm`, `rtld`, `sdk`, `subsdk0`, `subsdk1`, `subsdk2`
- **Binary output (`tools/build_game.py`):** `yoshi.exe` (Windows) / `yoshi` (POSIX)

---

## Verified progress screenshots

All captures below were recorded at 960x540 (Vulkan swapchain output) after the `OP_BIND_PROGRAM` `0x80` fix eliminated per-frame unbinds (`0` skipped draws/frame across 1500-frame runs at `41.3–42.4 fps`):

1. [Intro island H.264 movie (format 4)](screenshots/01-intro-island.png) — Media Foundation H.264 playback over RGBA format-4 output buffers (`f00301`).
2. [Title logo](screenshots/02-title-logo.png) — *"Yoshi and the Mysterious Book"* title logo composited over the island background (`f00451`).
3. [Start screen (`Ver. 1.0.2`)](screenshots/03-start-screen.png) — Interactive title prompt (`A Start Game`) (`f00751`).
4. [Profile menu](screenshots/04-profile-select.png) — Local save/profile screen (`Local` / `New Game` / `Add User`) over the animated island with flying pelican (`f01051`).

---

## Summary of Yoshi-specific changes

### Lifter & code discovery (`recomp/`)
- **`recomp/simd_c.py`**: Added vector `UDOT` (`(w & 0xbfe0fc00) == 0x2e809400`) lifting with register snapshotting for overlapping operands. Verified in [`tests/yoshi_udot_check.py`](../tests/yoshi_udot_check.py) (400 comparisons against Unicorn across `Q=0/1` and overlapping registers).
- **`recomp/gen.py` + `runtime/dispatch.c`**: Stopped the nearby-`BR` / `ADD`-register jump-table filter at `RET` instructions so `ADR` callback materializations near a function return (for example `main+0x2394758`) remain in the discovered function table, backed by [`tests/adr_return_discovery_test.py`](../tests/adr_return_discovery_test.py) and a slow-path fallback in `runtime/dispatch.c`.

### Loader, kernel & boot (`runtime/`)
- **`runtime/loader.c`**: Switched default-visibility non-local symbol binding to console load order so earlier modules (`sdk`) satisfy shared objects such as `nn::movie::detail::HeapMemoryManager::GetInstance()::instance` across `subsdk2` and `sdk` without colliding on TLS slot 0. Installed a diagnostic trap for relocation type `1031` (`subsdk0` offset `0x1197b0`).
- **`runtime/kernel.c` & `runtime/boot.c`**: Updated expected `main.npdm` main thread stack size to `0x10000` (Ver. `1.0.2`), and populated `TLR+0x1F0` (`tls` pointer) and `TLR+0x110` (`t->handle`).

### Filesystem, IPC, Account, Time & Input (`runtime/`)
- **`runtime/fs_host.c` & `runtime/romfs.c`**: Implemented RomFS `OpenDirectory` / `ReadDirectory` / `GetEntryCount` over indexed and overlay RomFS entries, and stubbed `nn::fs::SetAllocator` (`fs_init()`).
- **`runtime/ipc.c`**: Implemented offline service handlers and root-only CMIF domain support for `bsd:s`, `bsd:u`, `bsd:a`, `ssl:s`, `ssl`, and `fsp-srv` (`SetCurrentProcess`, `GetGlobalAccessLogMode`).
- **`runtime/ov_system.c`**: Added `nn::account` user listing and open-by-`Uid` (`GetUserCount`, `ListAllUsers`, `ListQualifiedUsers`, `OpenUser`, fallback for `LoadProfileImage`), `nn::aoc::GetAddOnContentListChangedEvent`, `nn::oe` screenshot enable log, and `nn::time::GetDeviceLocationName` / `LoadTimeZoneRule` / `ToCalendarTime`.
- **`runtime/ov_input.c`**: Added `GetNpadState` overrides for Joy-Con left/right and handheld structs, `GetMouseState`, and `SetGyroscopeZeroDriftMode`.

### Audio, Movie & UI (`runtime/`)
- **`runtime/audren.c`**: Implemented a paced SDL3 `AudioOut` queue returning PCM16 buffers on schedule (plus a no-device fallback so timing advances).
- **`runtime/ov_movie.c`, `runtime/movie.h`, `runtime/movie_avc.h`, `runtime/movie_avc_win.c`**: Implemented Windows Media Foundation H.264 decoding for `movie::Decoder`. Format-4 RGBA title playback works, and signaling the guest client's `movie::Buffer::GetNvnSync` `NVNsync` after format-3 `NVNtexture *` delivery advances playback through Movie 2 (3,665 frames) into the Stage 1 transition.
- **`runtime/ui/`, `runtime/ui_text.*`, `runtime/yoshi.ico`, `runtime/totk.rc`, `runtime/cfg.c`, `runtime/gfx_window_*.c`**: Replaced the inherited Donkey Kong Bananza theme (`dk` bark/banana UI, `DKB Recomp` version/title strings, BotW/TotK button hints) with a Yoshi storybook palette (`yoshi` theme default alongside `classic`), a 7-size Yoshi Egg application icon (`runtime/yoshi.ico`), `YoshiRecompWindow` / `yoshi-recomp` window identifiers, complete English/Russian UI strings, and `rt_patch_set` gating (`RT_PATCH_COUNT == 0`) so unsupported patch-dependent settings stay hidden on Yoshi.

### NVN 2, Shaders & Vulkan (`runtime/`)
- **`runtime/vk_exec_draw.c` (`bind_program`)**: Fixed a critical bug where per-draw `nvnCommandBufferBindProgram(cmd, NULL, 0x80)` stage-unbind calls zeroed `ex->prog`. Ignoring binds where `!(stages & (NVN_SHADER_STAGE_ALL_GRAPHICS_BITS | NVN_SHADER_STAGE_COMPUTE_BIT))` cut skipped draws from `26–79/frame` to `0/frame`, resolving the white screen and ghosting.
- **`runtime/gfx_texture_handle.h` & `runtime/nvn2_lower.cpp`**: Enabled uniform-texture lowering (`allow_uniform_texture = true`) and resolved packed constant-buffer texture/sampler handles via `gfx_texture_handle_read`.
- **`runtime/third_party/eglantine/shader_recompiler/frontend/ampere/lower_to_maxwell.h`**: Extended Ampere-to-Maxwell lowering for `ATOMS.U32`, 2D `SUATOM.D`, 1D/2D/2D_ARRAY/3D surface dimension codes, and cbuf shift forms.
- **`runtime/nvn_api_core.c`, `runtime/nvn_api_obj.c`, `runtime/nvn_api_cmd.c`**: Added NVN2 device properties (`0x69`, `0x85`, `0x95`, `0xa4..0xa6`), `nvnTexturePoolGetSize`, recorded `nvnCommandBufferFenceSync` published on queue submit, and safe rejection of unlowerable NVN2 stages in `nvnProgramSetShaders`.
- **`runtime/vk_exec.h`, `runtime/vk_exec.c`, `runtime/vk_exec_xfer.c`**: Added per-reason draw/clear/dispatch skip counters and uniform-texture miss telemetry.
- **`runtime/cfg.c` & `runtime/main.c`**: Added `YOSHI_*` environment variable aliases (precedence over `DKB_*` / `TOTK_*`), `yoshi.ini`, and `logs/yoshi.log`.

---

## Remaining blockers to reach gameplay

1. **Stage 1 Ampere shader lowering failures (`NVN2Shaders.cpp` abort after Movie 2)**
   - After Movie 2 finishes, the game compiles Stage 1 shaders. Offline census (`tools/dkb_lower_test.cpp`) of `378` dumped Stage 1 stages lowers `292` (`77.2%`) and fails on `86`:
     - `76` `native uniform texture mode` (`TEX.SCR` `0xf60` — disassembly shows `TEX.SCR.LB.NODEP` forms with `lod == 2` bias / scheduling flags / non-contiguous writemasks or `RZ` destination),
     - `6` `unsupported native opcode` (`0x59f` / `0x364`),
     - `1` each of `native uniform texture gather mode` (`0xf63`), `native shared increment mode` (`0xf8c`), `native uniform shift mode` (`0x899`), and `native warp reduction mode` (`0x3c4`).
   - Returning `0` (`NVN_FALSE`) from `nvnProgramSetShaders` triggers an intentional UE5 abort inside `NVN2Shaders.cpp` (`nn::diag::detail::Abort`).

2. **Two compute shaders in `program 1217` exceed descriptor storage limit**
   - Compute shaders `e1f058...` and `fddd96...` fail offline and runtime translation (`totk_xlate.exe`) inside `GlobalToStorage.GenerateGuardedStorageOp` with:
     `NotSupportedException: Storage candidates exceed the descriptor resource limit.`
   - These account for `disp nosh=2` skipped compute dispatches per frame in the title/island scene.
