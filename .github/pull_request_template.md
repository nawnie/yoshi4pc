## Problem

<!-- What is wrong or missing, and how it shows (log line, scene, or blocker from docs/yoshi-status.md). -->

## Change

<!-- What this pull request changes, and why this way. One topic per pull request. -->

## How it was tested

<!-- Commit, GPU and driver, scene reached, capture duration, and whether a fresh profile was used. -->

## Checklist

- [ ] `python tools/check_content.py --staged` passes, and nothing from `.nup` / game files / generated C / shader caches / builds is in this pull request.
- [ ] `python tests/check_content_test.py` passes.
- [ ] Changes to `recomp/` or `runtime/cpu.h` pass the differential tests (`tests/yoshi_udot_check.py`, `docs/building.md`).
- [ ] Copied code keeps its license header and has a row in `THIRD_PARTY_NOTICES.md`.
- [ ] Generated C is not edited by hand.
