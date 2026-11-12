# Legal notice

This repository contains tools, an ARM64-to-C static lifter, an NVN 2 / Vulkan translation layer, and a host runtime written for research and interoperability. It does **not** contain Nintendo intellectual property, copyrighted game assets, executable code lifted from the game, firmware, or encryption keys.

Running the build requires your own legally obtained dump of *Yoshi and the Mysterious Book* (Ver. 1.0.2 / title ID `0400245021D2C000`, title version `131072`). Nothing generated from your game files (`build/`, `generated/`, extracted `.nup` trees, shaders, or caches) may be committed or distributed.

This project is not affiliated with or endorsed by Nintendo. All trademarks remain the property of their respective owners.

`yoshi4pc` is distributed under GPL-3.0-or-later as a whole (`LICENSE`) because it carries Eglantine's GPL Ampere shader lowering (`runtime/third_party/eglantine/`). Files originating from TotK Recomp retain their MIT terms (`LICENSE-MIT`); see `THIRD_PARTY_NOTICES.md` for full upstream attributions and per-component licenses.
