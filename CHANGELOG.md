# Changelog

## Unreleased

## 1.0.31 - 2025-08-09

- **Fix:** Smooth kill-by-click overlay by avoiding repeated transparency warnings and redundant hover callbacks.

## 1.0.30 - 2025-08-09

- **Feat:** Offload window queries and scoring to a ``ThreadPoolExecutor`` to
  keep the click overlay responsive.

## 1.0.29 - 2025-08-08

- **Perf:** Revalidate the transparent color key only during initialization or
  when the background changes, reducing per-frame overhead.

## 1.0.28 - 2025-08-08

- **Perf:** Cache X11 window enumeration to avoid per-frame process launches.

## 1.0.27 - 2025-08-08

- **Perf:** Run window enumeration and scoring in a worker thread, keeping the
  click overlay responsive.

## 1.0.26 - 2025-08-07

- **Perf:** Click overlay caches window probes and reuses them until
  confidence drops, removing repeated queries.

## 1.0.25 - 2025-08-06

- **Feat:** Direct X11 queries replace subprocess calls for Linux window lookup with cached fallback.

## 1.0.24 - 2025-08-05

- **Perf:** Click overlay records frame durations and adjusts refresh delay based on average frame cost.

## 1.0.23 - 2025-08-04

- **Feat:** Offload window scoring to a background worker for smoother UI.

## 1.0.22 - 2025-08-03

- **Perf:** Use a persistent X11 connection for window enumeration with
  cached subprocess fallback.

## 1.0.21 - 2025-08-03

- **Perf:** Click overlay revalidates its transparent color key periodically
  instead of on every update, avoiding redundant system calls.

## 1.0.20 - 2025-08-02

- **Fix:** Click overlay uses a semi-transparent fallback and warns when the
  transparency color key cannot be set.

## 1.0.19 - 2025-08-01

- **Fix:** Kill-by-Click overlay now raises itself to ensure the crosshair
  is visible immediately.

## 1.0.18 - 2025-07-31

- **Performance:** Kill-by-Click overlay no longer computes velocity and heat-map updates in the mouse hook thread. Movement is buffered and processed on the Tkinter main loop, preventing input lag.
- **Efficiency:** Heat-map decay is skipped when `KILL_BY_CLICK_HEATMAP_WEIGHT` is zero, avoiding unnecessary loops.
- **Defaults:** Reduced window probe attempts from 5 to 3 for faster detection.
- **Tuning:** Refresh interval remains configurable via `KILL_BY_CLICK_INTERVAL`, `KILL_BY_CLICK_MIN_INTERVAL`, `KILL_BY_CLICK_MAX_INTERVAL` and `KILL_BY_CLICK_DELAY_SCALE`.
- **UI:** Force Quit dialog adapts its refresh delay to the detected screen refresh rate for smoother updates and no initial black window.
- **UI:** Initial refresh now loops at display frame rate until the first snapshot
  arrives, preventing visible blank states.
- **UI:** Click overlay matches the screen refresh rate and starts transparent to
  avoid the brief black flash.
- **Fix:** Click overlay sets a transparent color key even when using
  click-through hooks so it's fully invisible on all platforms.
- **Fix:** Overlay stays invisible when transparency isn't supported,
  preventing a black fullscreen window.
- **Fix:** Overlay canvas now uses a crosshair cursor so the pointer remains visible during Kill by Click.

## 1.0.11 - 2025-07-30

- **Fix:** Click overlay now verifies its transparent color key and remains
  invisible when ignored, preventing a black fullscreen window on some systems.

## 1.0.12 - 2025-07-31

- **Fix:** Overlay rechecks its transparent color key after mapping so the UI
  stays visible even if the key is dropped.

## 1.0.13 - 2025-07-31

- **Fix:** Overlay now continually verifies and restores its transparent color
  key, falling back to full transparency when unavailable to prevent any black
  fullscreen flash.

## 1.0.14 - 2025-07-31

- **Fix:** Normalize overlay background colors to hex so the transparent color
  key is honored, avoiding a persistent black overlay.

## 1.0.15 - 2025-07-31

- **Fix:** Accept uppercase transparent color keys so the click overlay
  remains visible on platforms that canonicalize colour values.

## 1.0.16 - 2025-07-31

- **Fix:** Canonicalize transparent color keys to hex, keeping the overlay
  visible even when the system returns shorthand codes.

## 1.0.17 - 2025-07-31

- **Perf:** Cache normalized colors to avoid repeated conversions.
- **Fix:** Parse hex color strings without consulting Tk, ensuring reliable
  transparent color keys.

