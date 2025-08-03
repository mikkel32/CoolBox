# Changelog

## Unreleased

## 1.2.16 - 2025-08-03

- **Refactor:** Extract hover tracking into reusable `HoverTracker` class.

## 1.2.15 - 2025-09-25

- **Refactor:** Split overlay update into gaze, crosshair, label and hover helpers.

## 1.2.14 - 2025-09-24

- **Fix:** Lift click overlay once during selection and drop redundant z-order checks.

## 1.2.13 - 2025-09-23

- **Perf:** Cache window probes by cursor position with configurable granularity.

## 1.2.12 - 2025-09-22

- **Feat:** Calibrate click overlay intervals on Force Quit startup and cache results.
- **Fix:** Clamp click overlay delays to tuned interval bounds.

## 1.2.11 - 2025-09-21

- **Perf:** Scale pointer move debounce and pixel thresholds by cursor velocity and display DPI with configurable minimum caps.

## 1.2.10 - 2025-09-20

- **Perf:** Warm click overlay window cache on dialog startup for faster initial selection.

## 1.2.9 - 2025-09-19

- **Perf:** Process fast pointer moves immediately for smoother hover updates.

## 1.2.8 - 2025-09-18

- **Fix:** Clamp delay smoothing to the minimum interval to avoid negative scheduling after slow frames.

## 1.2.7 - 2025-09-17

- **Refactor:** Manage Kill-by-Click overlay cleanup with a context manager.

## 1.2.6 - 2025-09-16

- **Refactor:** Centralize overlay highlight color updates and tests.

## 1.2.5 - 2025-09-15

- **Feat:** Auto-calibrate click overlay intervals and reuse saved tuning.

## 1.2.4 - 2025-09-14

- **Perf:** Scale window probe cache TTL inversely with cursor velocity for faster cache expiry when moving quickly.

## 1.2.3 - 2025-09-13

- **Feat:** Scale click overlay debounce thresholds with cursor velocity.

## 1.2.2 - 2025-09-12

- **Fix:** Avoid redundant selection when highlighting the same PID.

## 1.2.1 - 2025-09-11

- **Refactor:** Initialize kill-by-click overlay once and reuse configuration.

## 1.2.0 - 2025-09-10

- **Feat:** Track gaze timestamps and apply configurable decay for recent focus.

## 1.1.6 - 2025-09-09

- **Test:** Add click overlay pointer movement benchmark.

## 1.1.5 - 2025-09-08

- **Feat:** Skip tiny or menu/tooltip windows and ignore their PIDs when scoring.

## 1.1.4 - 2025-09-07

- **Perf:** Introduce off-screen buffer with selective canvas updates and frame
  timing logs for faster click overlay rendering.

## 1.1.2 - 2025-09-06

- **Perf:** Offload sample scoring loops to optional Cython extension with Python fallback.

## 1.1.1 - 2025-09-05

- **Fix:** Pre-initialize click overlay and global mouse listener in Force Quit
  dialog and stop hooks when the dialog closes.

## 1.1.0 - 2025-09-04

- **Feat:** Replace exponential smoothing with a configurable Kalman filter for
  click overlay cursor tracking.

## 1.0.83 - 2025-09-04

- **Perf:** Use ``WindowFromPoint`` on Windows for direct lookups and avoid
  enumerating stacked windows unless deeper z-order data is requested.
- **Perf:** Skip stack queries in ``ScoringEngine`` when scoring a single
  window.

## 1.0.82 - 2025-09-04

- **Perf:** Refresh window cache on OS events and query cache for window lookups,
  polling only when events are unavailable.

## 1.0.81 - 2025-09-04

- **Perf:** Offload click overlay scoring and window probing to a background
  thread and marshal results back to the Tk event loop.

## 1.0.80 - 2025-09-03

- **Fix:** Start global listener during Force Quit dialog initialization so hooks are primed before the first click.

## 1.0.79 - 2025-09-02

- **Feat:** Allow disabling crosshair lines via ``show_crosshair`` and skip canvas updates for crosshair and label when hidden.

## 1.0.77 - 2025-09-01

- **Feat:** Add optional OpenGL/Qt overlay backend selectable via ``KILL_BY_CLICK_BACKEND``.

## 1.0.76 - 2025-08-31

- **Feat:** Debounce pointer motion with configurable ``KILL_BY_CLICK_MOVE_DEBOUNCE_MS``
  and ``KILL_BY_CLICK_MIN_MOVE_PX`` thresholds.

## 1.0.74 - 2025-08-30

- **Perf:** Vectorize weighted confidence scoring with NumPy and expose a Python wrapper for seamless integration.

## 1.0.73 - 2025-08-30

- **Perf:** Use configurable thread pool for click overlay tasks, leveraging available CPU cores.

## 1.0.72 - 2025-08-30

- **Feat:** Display watchdog spinner during kill operations, allow cancellation on timeout and log kill duration metrics.

## 1.0.71 - 2025-08-30

- **Feat:** Add native global input hooks for mouse and keyboard with early event filtering.

## 1.0.70 - 2025-08-29

- **Feat:** Add basic rendering mode toggle that disables compositing effects and drop shadows for legacy GPU compatibility.
- **Feat:** Provide GPU usage benchmarking utility.

## 1.0.69 - 2025-08-28

- **Feat:** Introduce thread manager with logger, process and monitor threads to detect deadlocks.

## 1.0.68 - 2025-08-28

- **Feat:** Preload window titles, icons and handles in a background thread.
- **Perf:** Track a small ring buffer of recent windows to reduce cold-cache hits.
- **Fix:** Close window icon handles when windows vanish to avoid leaks.

## 1.0.67 - 2025-08-28

- **Perf:** Debounce process list refresh and hover updates to reduce redundant renders.

## 1.0.66 - 2025-08-28

- **Feat:** Cache running processes and refresh on OS notifications, rebuilding
  the snapshot only when updates fail.

## 1.0.65 - 2025-08-27

- **Refactor:** Replace shell-based process termination with direct API calls
  and surface failure to callers.

## 1.0.64 - 2025-08-26

- **Feat:** Boost kill priority to reduce termination latency and restore
  normal priority when system load spikes.

## 1.0.63 - 2025-08-26

- **Feat:** Stream process enumeration progress and disable kill actions until ready.

## 1.0.62 - 2025-08-26

- **Feat:** Calibrate click overlay refresh intervals and persist settings.

## 1.0.61 - 2025-08-26

- **Feat:** Allow disabling click overlay label via parameter or `KILL_BY_CLICK_LABEL` env var.

## 1.0.60 - 2025-08-26

- **Perf:** Vectorize cursor heat-map updates and window tracker confidence
  calculations with optional Cython helpers.

## 1.0.59 - 2025-08-26

- **Fix:** Cancel in-flight window queries before launching new ones.

## 1.0.58 - 2025-08-26

- **Perf:** Prime window cache in Force Quit dialog and remove redundant overlay warm-up.

## 1.0.57 - 2025-08-02

- **Refactor:** Reuse a persistent click-to-kill overlay within the Force Quit dialog.

## 1.0.56 - 2025-08-26

- **Feat:** Use foreground window callbacks to track active window without polling.

## 1.0.55 - 2025-08-26

- **Refactor:** Introduce a shared global mouse listener to reuse across
  overlays and stop once on exit.

## 1.0.54 - 2025-08-26

- **Refactor:** Share click overlay executor and shut it down on exit.

## 1.0.53 - 2025-08-26

- **Fix:** Skip Tk pointer lookups when hooks are active and fall back to polling
  only when hooks are unavailable.

## 1.0.52 - 2025-08-26

- **Perf:** Prime window cache on cursor movement so the click overlay reacts
  immediately when hovering new windows.

## 1.0.51 - 2025-08-25

- **Perf:** Query active window in a background thread and cache results to
  reduce overlay polling frequency.

## 1.0.50 - 2025-08-24

- **Perf:** Refresh overlay window cache on a worker thread to keep the UI responsive.
- **Perf:** Allow precomputed window lists to be filtered without blocking the main thread.

## 1.0.49 - 2025-08-24

- **Perf:** Switch cursor heatmap to lazy decay so only the active cell updates each frame.

## 1.0.48 - 2025-08-23

- **Perf:** Use cached window lists for click overlay queries so enumeration never blocks.
- **Test:** Assert window lookups finish under 50 ms with mocked subprocess calls.

## 1.0.47 - 2025-08-22

- **Perf:** Enumerate windows in a background thread and update a shared
  cache to avoid repeated subprocess calls.

## 1.0.46 - 2025-08-21

- **Perf:** Poll the active window on a timer and serve cached results to
  keep overlay updates off the UI thread.

## 1.0.45 - 2025-08-20

- **Perf:** Keep X11 window enumeration on a background thread and return
  cached results immediately so overlays never block.

## 1.0.44 - 2025-08-19

- **Perf:** Enumerate X11 windows on a background thread and serve cached
  results immediately to keep overlays responsive.

## 1.0.43 - 2025-08-19

- **Perf:** Cache active window PID on a background thread so overlay updates never block.

## 1.0.42 - 2025-08-18

- **Perf:** Poll active window details on a background thread to avoid blocking the overlay UI.

## 1.0.41 - 2025-08-17

- **Perf:** Probe the topmost window first and cache results across small cursor
  moves to reduce redundant enumeration.

## 1.0.40 - 2025-08-16

- **Perf:** Throttle active window polling with a background task to keep the click overlay responsive.

## 1.0.39 - 2025-08-15

- **Perf:** Reuse the previous window query result while a query is running to avoid redundant work.

## 1.0.38 - 2025-08-14

- **Perf:** Refresh the active window PID asynchronously on a timer to keep the
  click overlay responsive.

## 1.0.37 - 2025-08-13

- **Perf:** Query the active window asynchronously with caching so the click
  overlay stays responsive.

## 1.0.36 - 2025-08-12

- **Perf:** Reuse cached window info when the cursor remains inside a window,
  eliminating hover lag.

## 1.0.35 - 2025-08-11

- **Perf:** Halve kill-by-click refresh interval for smoother window switching.

## 1.0.34 - 2025-08-10

- **Perf:** Avoid blocking when gathering CPU metrics to keep the UI responsive.

## 1.0.33 - 2025-08-09

- **Fix:** Clear cached window info on cursor movement so the kill overlay
  follows the currently hovered program.

## 1.0.32 - 2025-08-09

- **Fix:** Initialize color key tracking before configuring the click overlay
  to prevent missing attribute errors during setup.

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

## 1.1.3 - 2025-08-03

- **Feat:** Support QtQuick/OpenGL overlay backend with shared drawing
  interface and runtime selection via ``KILL_BY_CLICK_BACKEND``.

