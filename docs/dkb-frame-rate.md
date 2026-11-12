# Experimental Bananza frame timing

Bananza 1.0.0 can adjust game timing to measured frame duration. This is
experimental and off by default. Enable the existing **Game speed follows the
clock** option (`DKB_REALTIME=1`, or `realtime = 1` in `dkb.ini`; `TOTK_REALTIME` is still accepted) and restart
once. With it enabled, the existing frame-rate selector, including Monitor rate,
applies cap changes without restarting. The default cap remains 60 FPS. TotK
retains its existing on-by-default timing setting.
No new frame-rate choices are added. Numeric caps in configuration accept 30
through 360; this is an experimental range,
not a claim that all rates or scenes have been validated.

The host measures presentation intervals using the existing five-frame average.
The Bananza controller receives a rounded FPS value, while seven clock producers
receive the precise floating-point step. Their existing pause, time-scale and
seconds-conversion logic remains in place. The maximum step is 1/15 second;
long stalls can still slow simulation. No rendering interpolation or frame
generation is added. CPU and GPU performance determine the achievable rate.

The controller's `+0x40` field is its chosen present interval: the native path
stores it at `1eadec`, computes `60 / interval`, and passes it through `1ead2c`
to `1eaed0`. Keep that interval unchanged, including values above 1; the host's
`runtime/nvn_api_obj.c` `present_period` already uses the selected cap when
real-time timing is enabled. No scene-specific interval policy is assumed.
At the rate hook `1ead24`, `x8` is dead: the next call at `1ead28` targets
`1eaf30`, whose first instruction overwrites `w8` before any read of `x8`.

## Validation

- Patch generation checks all original instruction words against base 1.0.0.
- `python tests/dkb_frame_rate_test.py --cc <clang>` checks the lifted replacement
  instructions on synthetic registers, stack and controller memory, including
  fractional rates and preserved present intervals 1 through 4, at O0 and O2:
  12,456 cases per build, zero failures.
- A local Unicorn check independently executes all eight replacement sequences
  at twelve rates: 96 cases, zero failures.
- Review revision, Windows, Ryzen 7 9800X3D, RTX 5090, 240 Hz display:
  a 60-second save-load and scripted cave run with no timing opt-in exited
  successfully; the log confirmed `realtime off` and original game timing.
- A 72-second opt-in run switched 60 → 120 → 240 → 30 → 45 → 60 → Monitor rate
  (239.984 Hz) → 60 through the live settings API without restarting and exited
  successfully. At the 240 cap, short cave samples achieved about 184–193 FPS;
  settled simulation/wall-time ratios there were 0.996–1.002. The native present
  interval remained 1 in this run; preservation of values 2–4 is covered by the
  synthetic test, not a cutscene playtest.
- Targets were tested through 240 FPS to match the available display; higher
  rates were not validated. Gameplay remains performance-limited: the tester
  reports difficulty sustaining above approximately 120 FPS on this system.
  The short automated observations above do not establish a performance gain.
- The clean player build passes `--selftest` and `--probe-cfg`.

This is not fully qualified arbitrary-frame-rate support. Earlier prototype
tests measured about 139.6 degrees at 60 FPS and 147.5 degrees at higher FPS
for a one-second full-stick camera turn. This discrepancy remains unresolved;
input sampling and the camera's frame-based smoothing need
further isolation. Jumping and movement were exercised, but jump trajectories,
destruction physics, cutscenes, audio synchronization and long-session stability
have not been established equivalent across rates. No test establishes sustained
240 FPS gameplay in the cave.

## Related work

[Bananza PR #80](https://github.com/Lucas-blip-png/dkb-pc-recomp/pull/80) is an
existing proposal for smoothing simulation at 10–60 FPS. Its controller location
helped locate the original timing path; this experiment uses the repository's
switchable patch table and precise host clock instead of modifying NSO loading.
No implementation code from that PR was copied.

[TotK's frame timing](https://github.com/valentderah/totk-pc-recomp/blob/main/runtime/frame_rate.c)
provides the inherited host pacer. Its current upstream implementation documents
physics failures with steps shorter than 1/240 second. Those TotK-specific limits
are a reference for testing, not evidence of Bananza's safe limits.
