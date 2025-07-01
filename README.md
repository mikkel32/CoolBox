# 🎉 CoolBox

A modern, feature-rich desktop application built with Python and CustomTkinter.

## 🚀 Features

- **Modern UI**: Beautiful dark/light theme with smooth animations
- **Modular Architecture**: Clean, maintainable code structure
- **Rich Toolset**: File tools, system utilities, text processing, and more
- **Customizable**: Extensive settings and preferences
- **Configurable UI**: Toggle the menu bar, toolbar and status bar on demand. The
  menu bar now includes recent files, a Quick Settings dialog and a fullscreen
  toggle. Quick Settings can also be launched from the toolbar or with the
  `Ctrl+Q` shortcut.
- **Unified Styling**: All views and dialogs inherit from shared base classes
  so fonts and accent colors update instantly when settings change.
- **Cross-Platform**: Works on Windows, macOS, and Linux
- **Custom Icon**: Displays the CoolBox logo in the window title and on the dock
- **Expanded Utilities**: File and directory copy/move helpers, an enhanced file manager, a threaded port scanner, a flexible hash calculator with optional disk caching, a multi-threaded duplicate finder that persists file hashes for lightning fast rescans, a screenshot capture tool, and a built-in process manager that auto-refreshes and sorts by CPU usage. The system info viewer now reports CPU cores and memory usage.
- **Security Center**: Toggle the Windows Firewall and Defender real-time protection directly from the app.
- **Kill by Click CLI**: `scripts/kill_by_click.py` opens the crosshair overlay
  from the terminal so you can quickly select any window. Pass `--skip-confirm`
  to close the overlay immediately without rechecking the click location.
- **Dynamic Gauges**: Resource gauges automatically change color from green to yellow to red as usage increases for quick visual feedback.
- **Stylish Setup**: Dependency installation is wrapped in a pulsing neon border
  with a dynamic spinner and live output for extra flair, even when triggered
  automatically on first launch.
  It also includes an advanced Force Quit utility with a searchable process
  list, automatic refresh, sort options, and multi-select termination. It can
  kill processes by name, command line pattern, port, host, open file, executable path
  or user. It can terminate entire process trees, children of a parent process
  or all processes older than a specified runtime, in addition to killing above
  configurable CPU or memory thresholds using platform-aware logic. The dialog
  refreshes the process list using a persistent background watcher thread that
  streams only changed processes to the UI. CPU usage is calculated from raw
  process time deltas which avoids expensive system polling and averages across
  recent samples for smoother updates. Filtering and sorting
  happen instantly on the latest snapshot, and rows update in-place only when
  values actually change to avoid flicker, so the interface stays responsive even with hundreds of processes. The dialog adds
  filtering by CPU, average CPU, memory, I/O rate or age thresholds, thread count filtering,
  open file and connection count metrics, and average I/O rate checks. It includes buttons to terminate high I/O or sustained high CPU processes,
  or processes with many files or network connections,
  an adjustable refresh interval, and an option to export the process list to CSV.
  The table shows the total number of processes and how many are currently selected.
  Automatic refresh can be paused when investigating specific entries and columns
  support toggling ascending/descending sort by clicking their headers.
  It allows filtering by user, name or PID and can be opened quickly with `Ctrl+Alt+F`.
  Zombie processes can be terminated with a single click and the list includes each
  process status, runtime and live I/O rate for quick troubleshooting.
  **New:** a *Kill Active Window* action instantly terminates the focused application
  and a *Kill by Click* option displays a crosshair overlay that follows your cursor,
  highlighting the window beneath it and showing the title as you hover.
  When global mouse hooks are available the overlay becomes completely
  click-through, updating on each movement without polling. If hooks fail to
  start or aren't available it falls back to normal bindings and briefly ignores
  mouse events while polling the window under the cursor at ``KILL_BY_CLICK_INTERVAL``
  and tracks pointer coordinates from hook callbacks or motion events to keep
  updates smooth without flicker. The window's normal interaction state is
  restored automatically when the overlay closes. The overlay samples the window
  The highlight color defaults to ``red`` but can be customized by setting
  ``KILL_BY_CLICK_HIGHLIGHT`` in the environment. The ``scripts/kill_by_click.py``
  helper launches the overlay directly from the command line. Use `--skip-confirm` to close it instantly without the final check. The overlay samples the window
  repeatedly and mixes those results with a short hover history to choose the
  most stable PID even when windows overlap. ``KILL_BY_CLICK_HISTORY`` sets how
  many hover entries are kept while ``KILL_BY_CLICK_SAMPLE_DECAY`` and
  ``KILL_BY_CLICK_HISTORY_DECAY`` control their relative weighting. ``KILL_BY_CLICK_SAMPLE_WEIGHT`` and
  ``KILL_BY_CLICK_HISTORY_WEIGHT`` tune the base influence of new samples versus
  hover history while ``KILL_BY_CLICK_ACTIVE_BONUS`` biases selection toward the
  previously active window. ``KILL_BY_CLICK_AREA_WEIGHT`` rewards smaller
  windows by adding an inverse-area score. ``KILL_BY_CLICK_CONFIDENCE`` controls
  how much larger the winning weight must be compared to the runner-up before a
  PID is accepted and ``KILL_BY_CLICK_EXTRA_ATTEMPTS`` sets how many additional
  samples are gathered when that confidence isn't reached. ``KILL_BY_CLICK_SCORE_DECAY``
  tunes how quickly long-running scores fade while ``KILL_BY_CLICK_SCORE_MIN``
  prunes rarely seen PIDs from consideration.
  ``KILL_BY_CLICK_SOFTMAX_TEMP`` adjusts the softmax temperature when converting
  weights into probabilities and ``KILL_BY_CLICK_DOMINANCE`` specifies the
  minimum probability required for a PID to be considered dominant. If neither
  the confidence ratio nor dominance threshold is met the overlay gathers extra
  samples until one is satisfied or ``KILL_BY_CLICK_EXTRA_ATTEMPTS`` is
  exhausted. ``KILL_BY_CLICK_STABILITY`` sets how many consecutive hover samples
  must agree before a PID is trusted while ``KILL_BY_CLICK_VELOCITY_SCALE``
  decreases sample weight at high mouse speeds so rapid motions don't overpower
  steady hovering. ``KILL_BY_CLICK_STABILITY_WEIGHT`` adds extra weight for
  PIDs that remain under the cursor across multiple samples, helping the overlay
  favour the window you're hovering rather than one that flashes beneath it.
  ``KILL_BY_CLICK_CENTER_WEIGHT`` rewards windows whose centers are close to the
  cursor while ``KILL_BY_CLICK_EDGE_PENALTY`` reduces scores when the pointer is
  near a window border. ``KILL_BY_CLICK_EDGE_BUFFER`` controls how close to an
  edge this penalty applies. ``KILL_BY_CLICK_VEL_STAB_SCALE`` increases the
  required stability count based on cursor speed so fast movements demand more
  agreement before a PID is trusted. ``KILL_BY_CLICK_PATH_HISTORY`` determines
  how many recent cursor positions are remembered while
  ``KILL_BY_CLICK_PATH_WEIGHT`` boosts windows that contain most of those
  coordinates so slow, deliberate motion is favoured over quick sweeps.
  ``KILL_BY_CLICK_HEATMAP_RES`` sets the resolution of a decaying heatmap that
  records cursor dwell time across the screen. ``KILL_BY_CLICK_HEATMAP_DECAY``
  controls how quickly old heat fades while ``KILL_BY_CLICK_HEATMAP_WEIGHT``
  biases selection toward windows covering the hottest regions. When the same
  PID remains under the cursor across consecutive samples the overlay adds a
  ``KILL_BY_CLICK_STREAK_WEIGHT`` multiplier to reward consistent hovering,
  ensuring foreground windows dominate momentary background flashes.
  ``KILL_BY_CLICK_TRACKER_RATIO`` sets the confidence ratio required for the
  overlay to trust its long-term window tracker when a direct query fails,
  letting it pick the PID that consistently appeared under the cursor even if
  the final sample was ambiguous. ``KILL_BY_CLICK_RECENCY_WEIGHT`` biases
  selection toward windows seen most recently while
``KILL_BY_CLICK_DURATION_WEIGHT`` favours windows that remained under the
cursor the longest. ``KILL_BY_CLICK_CONFIRM_DELAY`` waits this many seconds
after the overlay closes before checking the click position again while
``KILL_BY_CLICK_CONFIRM_WEIGHT`` boosts that final check when combining all
samples. ``KILL_BY_CLICK_ZORDER_WEIGHT`` favours windows that appear above
others at the click location so background windows are less likely to be
  chosen. ``KILL_BY_CLICK_GAZE_WEIGHT`` rewards windows that stay under the
  cursor for an extended time while ``KILL_BY_CLICK_GAZE_DECAY`` controls how
  quickly that effect fades.
  ``KILL_BY_CLICK_ACTIVE_HISTORY`` sets how many previously focused windows
  influence selection. Their impact decays by ``KILL_BY_CLICK_ACTIVE_DECAY`` and
  is scaled by ``KILL_BY_CLICK_ACTIVE_WEIGHT`` so recently active apps are more
  likely to be chosen. ``KILL_BY_CLICK_VEL_SMOOTH`` smooths cursor velocity
  updates before applying motion-based weighting, reducing noise from small
  jitters.
  ``KILL_BY_CLICK_SKIP_CONFIRM`` disables the final window check after clicking
  so the overlay closes instantly when accuracy is less important.
  so the overlay remains usable without extra dependencies. Process monitoring pauses while
  selecting so the overlay stays smooth. Click to
  immediately terminate that window's process. The confirmation dialog now includes the
  window title so you know
  exactly which application is about to close. Termination now employs a layered
  strategy that escalates from polite requests to root-level ``kill -9`` or
  ``taskkill`` commands so stubborn processes can't escape. macOS support uses ``pyobjc`` to
  query windows under the pointer while
  Linux relies on ``xdotool`` and ``xwininfo``. Process data is gathered concurrently using a small thread pool so updates
  remain fast even with hundreds of processes. Both actions only appear when these
  dependencies are detected so unsupported systems won't see them.
  Expensive metrics
  like open files and network connections are refreshed only every few cycles to
  further reduce overhead without losing accuracy.
  The dialog now skips UI updates when nothing has changed and supports several
  environment variables to tune performance. ``FORCE_QUIT_INTERVAL`` sets the
  refresh delay, ``FORCE_QUIT_DETAIL_INTERVAL`` controls how often expensive
  metrics are gathered, ``FORCE_QUIT_MAX`` limits displayed rows and
  ``FORCE_QUIT_WORKERS`` defines the worker thread count. ``FORCE_QUIT_CPU_ALERT``
  and ``FORCE_QUIT_MEM_ALERT`` change the CPU and memory thresholds that trigger
  row highlighting. ``FORCE_QUIT_SAMPLES`` controls how many samples are kept for
  average CPU/IO calculations. Row data is cached so only changed entries are
  redrawn for smoother updates. Pausing the dialog now halts the background
  watcher thread so no resources are wasted while inspecting a snapshot.
  ``FORCE_QUIT_CHANGE_CPU``, ``FORCE_QUIT_CHANGE_MEM`` and ``FORCE_QUIT_CHANGE_IO``
  define the minimum CPU percentage, memory in MB and I/O rate delta that must
  change before a row is considered updated. Their defaults are ``0.5`` for CPU,
  ``1.0`` for memory and ``0.5`` for I/O.
  ``FORCE_QUIT_CHANGE_SCORE`` combines the individual deltas into a single
  threshold so minor variations across metrics don't trigger redraws.
  ``FORCE_QUIT_CHANGE_AGG`` sets how many refresh cycles to aggregate change
  scores before a row is considered updated, further reducing noise from small
  fluctuations.
  ``FORCE_QUIT_CHANGE_ALPHA`` controls how quickly baseline CPU, memory and I/O
  usage adapt to recent samples. ``FORCE_QUIT_CHANGE_RATIO`` specifies how much
 deviation from that baseline counts as a significant change. ``FORCE_QUIT_CHANGE_STD_MULT``
 sets how many standard deviations a metric must deviate from its baseline
 before it contributes to the aggregate change score, enabling smarter
  detection of large shifts in resource usage. ``FORCE_QUIT_CHANGE_MAD_MULT``
  uses the median absolute deviation instead of variance for robustness and
  specifies how many deviations are required before a metric influences the
  change score.
 ``FORCE_QUIT_CHANGE_DECAY`` applies exponential decay to aggregated change
 scores so old deviations fade out. This helps focus updates on significant
 sustained changes rather than momentary spikes. The default decay factor is
 ``0.8`` meaning each cycle retains 80% of the previous total.
  ``FORCE_QUIT_STABLE_CYCLES`` controls how many refreshes a process must remain
  unchanged before it is considered stable. ``FORCE_QUIT_STABLE_SKIP`` defines
  how many cycles to skip detail refreshes for those stable processes.
  ``FORCE_QUIT_CHANGE_WINDOW`` sets how many refresh cycles a changed row stays
  highlighted in the list so you can quickly spot recent updates.
  ``FORCE_QUIT_VISIBLE_CPU`` ``FORCE_QUIT_VISIBLE_MEM`` and ``FORCE_QUIT_VISIBLE_IO``
  hide rows using less CPU, memory or I/O than these thresholds unless filtered.
  ``FORCE_QUIT_VISIBLE_AUTO`` adapts those visibility thresholds to the 75th
  percentile of recent usage so low-impact processes disappear automatically.
  ``FORCE_QUIT_WARN_CPU`` ``FORCE_QUIT_WARN_MEM`` and ``FORCE_QUIT_WARN_IO``
  define soft warning limits. Processes exceeding them but below the alert
  thresholds are marked as *warning* instead of *critical* in the new **Level**
  column.
  ``FORCE_QUIT_HIDE_SYSTEM`` omits system processes owned by ``root`` or
  ``SYSTEM`` entirely.
  ``FORCE_QUIT_SLOW_RATIO`` and ``FORCE_QUIT_FAST_RATIO`` set the change ratios
  that trigger automatic refresh tuning. Higher ratios make the watcher react
  faster to bursts of activity while lower ratios favour stability.
  ``FORCE_QUIT_RATIO_WINDOW`` controls how many cycles are averaged when
  calculating the change ratio for adaptive tuning, smoothing out short bursts.
  ``FORCE_QUIT_SHOW_DELTAS`` toggles optional columns displaying how much CPU,
  memory and I/O have changed since the last refresh for each process.
  ``FORCE_QUIT_SHOW_SCORE`` adds an aggregate change score column so you can
  quickly spot processes with unusually large deviations.
  ``FORCE_QUIT_TREND_WINDOW`` defines how many samples are used when
  determining if CPU, memory or I/O usage is trending upward.
  ``FORCE_QUIT_TREND_CPU`` and ``FORCE_QUIT_TREND_MEM`` set the minimum
  increase required to flag a process as trending. ``FORCE_QUIT_TREND_IO``
  controls the minimum I/O rate increase considered a trend. ``FORCE_QUIT_TREND_IO_WINDOW``
  lets you use a different sample window for I/O trends than CPU and memory,
  making disk-heavy bursts easier to catch. ``FORCE_QUIT_SHOW_TRENDS``
  toggles highlighting of trending processes and you can filter only trending
  rows using the new *Trending* option. Trend detection now combines slope and
  an exponential moving average for faster yet stable updates.
  ``FORCE_QUIT_SHOW_STABLE`` highlights processes that remain unchanged for
  several refresh cycles and lets you filter by them using a *Stable* option.
  ``FORCE_QUIT_SHOW_NORMAL`` shows low-activity processes that don't exceed
  the configured visibility thresholds. When false, the dialog hides these
  "normal" processes so only changed or high-usage entries appear by default.
  ``FORCE_QUIT_NORMAL_WINDOW`` controls how many consecutive refreshes a process
  must remain normal before it is hidden.
  ``FORCE_QUIT_EXCLUDE_USERS`` can specify a comma separated list of usernames
  that should be ignored entirely by the Force Quit monitor.
  ``FORCE_QUIT_IGNORE_NAMES`` lists process names that should be skipped when
  gathering data. Use this to exclude lightweight helpers from monitoring.
  ``FORCE_QUIT_IGNORE_AGE`` skips processes younger than this many seconds so
  short-lived helpers do not clutter the list.
  ``FORCE_QUIT_IDLE_CPU`` sets the CPU percentage considered idle for adaptive
  sampling. After a process stays below this for ``FORCE_QUIT_IDLE_CYCLES``
  refreshes, CPU usage collection is skipped for up to ``FORCE_QUIT_MAX_SKIP``
  cycles with exponential backoff. Idle processes no longer trigger expensive
  ``cpu_times`` calls, dramatically reducing monitor overhead.
  When activity resumes, idle counters reset automatically so metrics remain
  responsive without manual intervention.
  ``FORCE_QUIT_IDLE_BASELINE`` controls how quickly per-process idle baselines
  adapt to recent CPU usage. ``FORCE_QUIT_IDLE_RATIO`` specifies the fraction of
  the baseline considered idle. Together they let the monitor learn typical
  process activity and dynamically tune skip thresholds for even lower impact.
  ``FORCE_QUIT_IDLE_DECAY`` sets the fraction of the skip interval retained when
  a process becomes active again. Values below ``1`` slowly reduce skipping
  instead of resetting immediately, smoothing out CPU spikes.
  ``FORCE_QUIT_IDLE_DECAY_EXP`` raises the CPU excess above the idle threshold
  to this exponent when adjusting the decay so large spikes shorten the delay
  more aggressively.
  ``FORCE_QUIT_IDLE_GLOBAL_ALPHA`` controls how quickly a global idle baseline
  adapts to observed CPU usage. New processes use this baseline to determine
  skip thresholds before they accumulate history of their own, improving
  accuracy when many short-lived helpers appear.
  ``FORCE_QUIT_IDLE_JITTER`` introduces random jitter when skip intervals
  increase so multiple processes do not resample in lockstep. Set to ``1`` to
  disable.
  ``FORCE_QUIT_IDLE_WINDOW`` controls how many recent CPU samples are averaged
  when computing idle baselines for each process, smoothing out spikes and
  improving skip accuracy.
  ``FORCE_QUIT_IDLE_HYSTERESIS`` adds a margin around the idle threshold so
  processes must fall below ``(1-h)`` or exceed ``(1+h)`` times the threshold
  before switching states, preventing rapid flapping.
  ``FORCE_QUIT_IDLE_REFRESH`` forces a CPU sample if a process hasn't been
  measured for this many seconds, ensuring long-idle processes still update
  their baselines.
  ``FORCE_QUIT_IDLE_SKIP_ALPHA`` controls how strongly idle baselines are
  updated when CPU sampling is skipped. Higher values adapt faster to long
  periods of inactivity.
  ``FORCE_QUIT_IDLE_GRACE`` sets how many initial refresh cycles a new process
  is always sampled before idle skipping can activate, allowing more accurate
  baselines.
  ``FORCE_QUIT_IDLE_MULT`` controls how quickly skip intervals expand during
  idle periods. Values above ``2`` double the delay more aggressively.
  ``FORCE_QUIT_IDLE_DYNAMIC_MULT`` scales the multiplier based on how far CPU
  usage is below the idle threshold so processes that are deeply idle wait
  longer before being sampled again.
  ``FORCE_QUIT_IDLE_DYNAMIC_MEM`` extends this behaviour to memory usage so
  processes consuming far less memory than their idle baseline wait longer
  between samples.
  ``FORCE_QUIT_IDLE_DYNAMIC_IO`` does the same for I/O activity, combining all
  enabled metrics to determine how aggressively skip intervals grow.
  ``FORCE_QUIT_IDLE_DYNAMIC_MODE`` chooses how deficits are combined when
  dynamic scaling is active. Set to ``mean`` for a simple average or ``rms`` to
  emphasize larger gaps.
  ``FORCE_QUIT_IDLE_DYNAMIC_EXP`` raises the combined deficit to this exponent
  when calculating the multiplier so deeply idle processes can skip
  exponentially longer.
  ``FORCE_QUIT_IDLE_CPU_WEIGHT`` ``FORCE_QUIT_IDLE_MEM_WEIGHT`` and
  ``FORCE_QUIT_IDLE_IO_WEIGHT`` apply relative weights to CPU, memory and I/O
  deficits when computing the multiplier.
  ``FORCE_QUIT_IDLE_RESET_RATIO`` resets the skip interval when CPU usage
  exceeds this multiple of the idle threshold so spikes are measured
  immediately.
  ``FORCE_QUIT_IDLE_CHECK_INTERVAL`` forces a lightweight CPU check after this
  many seconds even when skipping to detect spikes sooner.
  ``FORCE_QUIT_IDLE_ACTIVE_SAMPLES`` sets how many active cycles are measured
  after a spike before idle skipping resumes.
  ``FORCE_QUIT_IDLE_MEM_DELTA`` breaks skipping when memory usage rises by more
  than this number of megabytes since the last sample, ensuring that idle
  processes consuming RAM are checked promptly.
  ``FORCE_QUIT_IDLE_IO_DELTA`` breaks skipping when I/O throughput increases by
  more than this many megabytes per second between samples.
  ``FORCE_QUIT_IDLE_MEM_RATIO`` breaks skipping when memory usage exceeds this
  multiple of the idle baseline, allowing gradual leaks to be detected sooner.
  ``FORCE_QUIT_IDLE_MEM_RESET_RATIO`` resets the skip interval when memory
  usage rises above this multiple of the baseline so spikes are sampled
  immediately, even if the process isn't currently being skipped.
  ``FORCE_QUIT_IDLE_IO_RATIO`` breaks skipping when I/O activity exceeds this
  multiple of the idle baseline throughput.
  ``FORCE_QUIT_IDLE_IO_RESET_RATIO`` resets the skip interval when I/O activity
  jumps above this multiple of the baseline and breaks idle state to resume
  active sampling.
  ``FORCE_QUIT_IDLE_MEM_GLOBAL_ALPHA`` controls how quickly global memory
  baselines adapt to observed usage so new processes inherit realistic
  thresholds.
  ``FORCE_QUIT_IDLE_IO_GLOBAL_ALPHA`` sets the adaptation speed of the global
  I/O baseline used for new processes.
  ``FORCE_QUIT_IDLE_TREND_RESET`` resets skip intervals whenever the previous
  sample detected a CPU, memory or I/O trend so rapidly growing processes are
  sampled without delay.
  ``FORCE_QUIT_IDLE_TREND_SAMPLES`` controls how many active cycles are
  captured after a trending event before idle skipping resumes, ensuring the
  monitor tracks fast-growing processes closely.
  ``FORCE_QUIT_BULK_CPU`` sets how many sampled processes trigger a bulk
  ``/proc`` scan for CPU times. When the number of active processes exceeds this
  threshold, the monitor reads all CPU times in one pass to further reduce
  overhead.
  ``FORCE_QUIT_BULK_WORKERS`` controls how many threads are used for the bulk
  scan so large systems can prefetch CPU times in parallel.
  ``FORCE_QUIT_LOAD_THRESHOLD`` sets the system CPU usage percentage that triggers a temporary pause in monitoring. When exceeded, the watcher skips ``FORCE_QUIT_LOAD_CYCLES`` refreshes to reduce contention.
  ``FORCE_QUIT_LOAD_CYCLES`` configures how many cycles are skipped each time the threshold is hit. Set the threshold to ``0`` to disable this behaviour.
  ``FORCE_QUIT_BATCH_SIZE`` controls how many processes are scanned in each
  refresh cycle so monitoring work is spread out more evenly. The default of
  ``100`` can be overridden in ``config.json`` or via the environment.
  ``FORCE_QUIT_AUTO_BATCH`` toggles dynamic tuning of the batch size based on
  how long recent cycles take and the ratio of changed or trending processes.
  ``FORCE_QUIT_MIN_BATCH`` and ``FORCE_QUIT_MAX_BATCH`` bound the adaptive
  range.
  ``FORCE_QUIT_AUTO_INTERVAL`` or ``force_quit_auto_interval`` enables dynamic
  tuning of the refresh interval. ``FORCE_QUIT_MIN_INTERVAL`` and
  ``FORCE_QUIT_MAX_INTERVAL`` bound the adaptive interval range.
  ``FORCE_QUIT_MIN_WORKERS`` and ``FORCE_QUIT_MAX_WORKERS`` bound the thread
  pool used by the watcher. The pool automatically scales between these limits
  based on the number of processes being monitored.
  ``FORCE_QUIT_TREND_SLOW_RATIO`` and ``FORCE_QUIT_TREND_FAST_RATIO`` adjust how
  aggressively refresh intervals respond to the number of trending processes.
  Set ``FORCE_QUIT_AUTO_KILL`` to ``cpu``, ``mem`` or ``both`` to automatically
  terminate processes exceeding the configured thresholds.
  Updated thresholds, auto-kill options, sort settings, refresh interval and
  window size persist across sessions when changed through the dialog. The
  interface now organizes advanced kill controls on a dedicated **Actions** tab
  with a toggleable details pane on the main monitor tab. A status bar shows the
  total CPU and memory usage of listed processes, the percentage currently
  trending, the percentage changed and the active batch size with its recent
  average, cycle time and refresh interval, and the dialog can
  stay **Always on Top** if enabled.
- **Network Scanner CLI**: Scan multiple hosts asynchronously with IPv4/IPv6
  support, host lookup caching, and configurable timeouts.
- **Process Monitor CLI**: Display live CPU and memory usage in your terminal
  using the same adaptive `ProcessWatcher` as Force Quit with optional dynamic
  batching, interval tuning and worker scaling.
- **Auto Network Scan**: Detects local networks, pings for active hosts and
  scans them automatically.

## 📋 Requirements

- Python 3.8+
- CustomTkinter
- See `requirements.txt` for full dependencies
- The optional `pynput` package enables the Kill by Click overlay to remain
  fully click-through using global mouse hooks. If the hooks fail to start the
  overlay automatically falls back to event bindings that poll the cursor at
  ``KILL_BY_CLICK_INTERVAL``.

## 🛠️ Installation

1. Clone the repository:
```bash
git clone https://github.com/mikkel32/CoolBox.git
cd CoolBox
```

2. Install dependencies:
```bash
python setup.py
```
Alternatively you can run:
```bash
pip install -r requirements.txt
```

For a development environment with additional tools, use:
```bash
python setup.py --dev
```
This script installs all packages from `requirements.txt` and optional
development extras like `debugpy` and `flake8` while displaying a
pulsing neon border and real-time progress.

For a development environment with debugging tools, run:
```bash
./scripts/setup_dev_env.sh
```
Pass ``--skip-deps`` to ``run_vm_debug.py`` or set ``SKIP_DEPS=1`` when
running ``run_debug.sh`` to reuse existing Python packages.

### Running Tests

To run the test suite and style checks:

```bash
pytest -q
flake8 src setup.py tests
```

3. Run the application:
```bash
python main.py
```
By default, ``main.py`` computes a digest of ``requirements.txt``, ``setup.py``
and your Python executable. It also verifies that all listed packages are
installed. When either the digest has changed or any dependency is missing it
automatically runs the setup routine with the same neon border and spinner
for a seamless experience. Set
``SKIP_SETUP=1`` to bypass this check if you have already handled installation
yourself.

To start the app and wait for a debugger to attach, use:
```bash
./scripts/run_debug.sh
```
This script will automatically start the application under ``xvfb`` if no
display is available, making it convenient to debug in headless
environments such as CI or containers. Make sure the ``xvfb`` package is
installed so the ``xvfb-run`` command exists (``sudo apt-get install xvfb`` on
Debian/Ubuntu). The ``-Xfrozen_modules=off`` option
is passed to Python to silence warnings when using debugpy with frozen
modules.

Alternatively you can launch directly using ``python``:

```bash
python main.py --debug
```
This starts ``debugpy`` on port ``5678`` and waits for a debugger to
attach. Use ``--debug-port`` to specify a custom port.

To automatically spin up a Docker/Podman or Vagrant environment and attach a
debugger, run:

```bash
python main.py --vm-debug --vm-prefer docker --open-code --debug-port 5679
```
This calls ``launch_vm_debug`` which tries Docker, Podman or Vagrant depending
on ``--vm-prefer`` (or auto-detection when omitted). ``--open-code`` opens
Visual Studio Code once the environment starts and ``--debug-port`` sets the
debug server port. If no backend is available the app runs locally under
``debugpy``.

### Network Scanner CLI

Use ``scripts/network_scan.py`` to scan multiple hosts for open ports:

```bash
./scripts/network_scan.py 22-25 host1 host2 host3
```
The script runs asynchronous scans with caching so repeated invocations are fast
and supports a few useful options:

```bash
./scripts/network_scan.py 80-85 host1 --timeout 1.0 --family ipv6
```
* ``--timeout`` sets the connection timeout in seconds
* ``--family`` forces IPv4 or IPv6 resolution (``auto`` by default)
* ``--ping`` filters the host list by pinging before scanning. Ping checks are
  fully asynchronous for fast host discovery.
* ``--ping-timeout`` controls how long each ping attempt waits for a response
  (defaults to 1 second).
* ``--ping-concurrency`` sets the number of simultaneous ping checks
  (defaults to 100).
* ``--services`` shows service names for each open port
* ``--banner`` captures a short banner string from open ports
* ``--latency`` measures connection latency for each port in milliseconds
* ``--ping-latency`` records ping round-trip time for each host
* ``--ping-ttl`` includes the TTL value from ping replies
* ``--os`` shows a basic OS guess derived from ping TTL
* ``--hostname`` displays resolved hostnames
* ``--mac`` shows MAC addresses
* ``--vendor`` adds vendor names for MAC prefixes
* ``--connections`` lists active local connection counts
* ``--http`` collects basic HTTP server information
* ``--http-concurrency`` sets how many HTTP requests run concurrently
* ``--host-concurrency`` limits how many hosts are scanned in parallel
* ``--device`` guesses the device type
* ``--risk`` shows a simple risk score
* ``--top`` scans the top N most common ports instead of ``PORTS``
* ``--auto`` automatically detects active hosts on local networks
* ``--max-hosts`` limits the number of auto-detected hosts per network
* ``--no-host-cache`` disables caching of detected hosts
* ``--clear-cache`` clears cached scan, host and DNS data before scanning
* ``--json`` writes scan results to a JSON file or stdout
* ``--stream`` streams JSON results as each host completes

The ``PORTS`` argument accepts service names (``ssh``), ranges with optional
steps (``20-30:2``), comma separated lists (``22,80``) and ``topN`` shortcuts.
Hosts may be specified individually or using CIDR notation, ranges and ``*``
wildcards like ``192.168.1.*``.

Environment variables can tune default behavior:

- ``NET_SCAN_WORKERS`` sets concurrent port/ping workers.
- ``PING_WORKERS`` limits how many ping checks run concurrently.
- ``PING_CACHE_TTL`` sets how long ping results are cached.
- ``HOST_SCAN_WORKERS`` limits how many hosts are scanned at once.
- ``META_WORKERS`` controls concurrency when fetching hostnames and MAC addresses.
- ``NET_SCAN_TIMEOUT`` defines the connection timeout.
- ``HTTP_CONCURRENCY`` configures concurrent HTTP requests.
- ``NETWORK_CACHE_FILE`` changes where scan results are cached.
- ``HTTP_CACHE_FILE`` and ``HTTP_CACHE_TTL`` control HTTP metadata caching.
- ``DNS_CACHE_FILE`` and ``DNS_CACHE_TTL`` tune DNS caching.
- ``LOCAL_HOST_CACHE_TTL`` sets how long detected hosts are cached.
- ``LOCAL_HOST_CACHE_FILE`` changes where detected hosts are cached.
- ``OUI_FILE`` specifies a vendor prefix list for MAC lookups.
- ``ARP_CACHE_TTL`` controls how often the ARP table is refreshed for MAC lookups.
- ``ARP_CACHE_FILE`` sets where the parsed ARP table is cached on disk.
- When ``arp`` is unavailable on Linux, the scanner automatically falls back to
  ``ip neighbor`` to gather MAC addresses.
- Auto network scans merge hosts listed in the ARP table to avoid unnecessary pings.
- ``HOST_CACHE_TTL`` defines how long DNS lookups are cached.

### Process Monitor CLI

Run ``scripts/process_monitor_cli.py`` to view live CPU and memory usage in the
terminal. The script uses the same adaptive `ProcessWatcher` as the Force Quit
dialog and accepts additional tuning options:

```bash
python scripts/process_monitor_cli.py --interval 1.5 --limit 10 \
    --auto-interval --min-interval 0.5 --max-interval 5 \
    --auto-batch --min-batch 50 --max-batch 500 --ignore-names bash --show-stats
```

### Auto Network Scan

From the **Tools** view choose *Auto Network Scan* to open a modern dialog with scanning options on the left and a results table on the right. CoolBox automatically detects local subnets using `psutil` and pings each address to find active hosts before scanning the specified ports. A progress bar tracks detection and scanning with results displayed in a scrollable list when complete. Recent updates add HTTP metadata collection, vendor and device type guessing, ping latency and TTL measurements, and a risk score computed from open ports. Results can be filtered and exported to CSV. Link-local addresses are skipped so only reachable hosts are scanned. Hosts already listed in the local ARP table are merged into the results, avoiding unnecessary pings. Asynchronous MAC lookups keep scans responsive even with many hosts.

### Debugging in a Dev Container

The project includes a **devcontainer** for running CoolBox inside Docker.  This
lets you debug the application in an isolated environment:

1. Install the *Dev Containers* extension for Visual Studio Code.
2. From the Command Palette choose **Dev Containers: Open Folder in Container**.
3. Once the container starts, run `./scripts/run_debug.sh` to launch the app
   under `debugpy`.

You can also start the container manually:

```bash
./scripts/run_devcontainer.sh
```
This requires Docker or Podman to be installed on your system. Like
``run_debug.sh``, the script automatically launches the app under
``xvfb`` if no display is detected so the GUI works even in headless
Docker environments. Install the ``xvfb`` package to ensure the
``xvfb-run`` helper is available. You may also use ``./scripts/run_vm_debug.sh`` or
``python scripts/run_vm_debug.py`` (``.\scripts\run_vm_debug.ps1`` on Windows) which choose Docker/Podman or Vagrant
depending on what is installed. If neither is present, it falls back to
``run_debug.sh`` so you can still debug locally.
When this fallback occurs the application waits for a debugger to attach on
``DEBUG_PORT`` (default ``5678``). Run ``python scripts/run_vm_debug.py --list``
to verify whether Docker, Podman or Vagrant are available on your system.

### Debugging in a Vagrant VM

If you prefer a lightweight virtual machine instead of Docker, a
`Vagrantfile` is provided. This sets up an Ubuntu VM with all
dependencies preinstalled and starts CoolBox under `debugpy`.
The debug server port **5678** is forwarded to the host by default so you can attach
to `localhost:5678`. Use ``--port`` to choose a custom port:

```bash
./scripts/run_vagrant.sh
```

As a shortcut you can use ``./scripts/run_vm_debug.sh`` or
``python scripts/run_vm_debug.py`` which will start ``run_vagrant.sh`` or
``run_devcontainer.sh`` depending on what tools are available. When
neither is found the script falls back to running ``run_debug.sh`` in the
current environment.  You can set ``PREFER_VM=docker``, ``PREFER_VM=podman`` or
``PREFER_VM=vagrant`` to force a specific backend or pass ``--prefer`` to
``run_vm_debug.py``. The ``run_vm_debug.sh`` wrapper now simply calls this
Python script so all command line options like ``--prefer`` ``--code`` and
``--port`` and ``--skip-deps`` are
available on both Unix and Windows.
Use the ``--code`` flag to open Visual Studio Code before launching the
environment so it's ready to attach to the debug server.
Run ``python scripts/run_vm_debug.py --list`` to display the backends
detected on your system.
``run_vm_debug.ps1`` accepts the same options including ``--list`` for Windows users.

The first run may take a while while Vagrant downloads the base box and
installs packages. Once finished, Visual Studio Code can attach to the
debug server on port `5678` using the **Python: Attach** configuration.

### Debugging with VS Code

1. Open the project folder in Visual Studio Code.
2. Ensure the Python extension is installed.
3. Press `F5` or choose **Run > Start Debugging** to launch the app using the
   configuration provided in `.vscode/launch.json`.
4. For convenience a task named **Run CoolBox in Debug** is provided. Open the
   Command Palette and run **Tasks: Run Task** then choose this task to launch
   the app via `./scripts/run_debug.sh`.
5. Additional tasks are available for launching the app in Docker/Podman or Vagrant.
   Choose **Run in Dev Container**, **Run in Vagrant VM**, or
   **Run in Available VM** to start the appropriate environment.
6. Alternatively, run the scripts manually and select the **Python: Attach**
   configuration to connect the debugger.
7. Within the application, open **Tools > System Tools > Launch VM Debug** to
   start the same environment directly from the GUI. The tool now asks whether
   to open Visual Studio Code automatically once the VM starts.

## 📁 Project Structure

```
CoolBox/
├── main.py              # Entry point
├── src/
│   ├── app.py          # Main application class
│   ├── components/     # UI components
│   ├── views/          # Application views
│   ├── utils/          # Utilities
│   └── models/         # Data models
└── assets/             # Resources
```

## 🎨 Screenshots

[Add screenshots here]

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 📄 License

This project is licensed under the MIT License.

## 👨‍💻 Author

Created by mikkel32

---

⭐ If you find this project useful, please give it a star!
