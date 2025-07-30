# Changelog

## Unreleased

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

