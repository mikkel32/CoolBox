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
- **Cross-Platform**: Works on Windows, macOS, and Linux
- **Expanded Utilities**: File and directory copy/move helpers, an enhanced file manager, a threaded port scanner, a flexible hash calculator with optional disk caching, a multi-threaded duplicate finder that persists file hashes for lightning fast rescans, a screenshot capture tool, and a built-in process manager that auto-refreshes and sorts by CPU usage. The system info viewer now reports CPU cores and memory usage.
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
  It allows filtering by user, name or PID and can be opened quickly with
  `Ctrl+Alt+F`. Zombie processes can be terminated with a single click and the
  list includes each process status, runtime and live I/O rate for quick
  troubleshooting. Process data is gathered concurrently using a small thread
  pool so updates remain fast even with hundreds of processes. Expensive metrics
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
  Set ``FORCE_QUIT_AUTO_KILL`` to ``cpu``, ``mem`` or ``both`` to automatically
  terminate processes exceeding the configured thresholds.
  Updated thresholds, auto-kill options, sort settings, refresh interval and
  window size persist across sessions when changed through the dialog. The
  interface now organizes advanced kill controls on a dedicated **Actions** tab
  with a toggleable details pane on the main monitor tab. A status bar shows the
  total CPU and memory usage of listed processes, and the dialog can stay
  **Always on Top** if enabled.
- **Network Scanner CLI**: Scan multiple hosts asynchronously with IPv4/IPv6
  support, host lookup caching, and configurable timeouts.
- **Auto Network Scan**: Detects local networks, pings for active hosts and
  scans them automatically.

## 📋 Requirements

- Python 3.8+
- CustomTkinter
- See `requirements.txt` for full dependencies

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
development extras like `debugpy` and `flake8`.

For a development environment with debugging tools, run:
```bash
./scripts/setup_dev_env.sh
```

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

To start the app and wait for a debugger to attach, use:
```bash
./scripts/run_debug.sh
```
This script will automatically start the application under ``xvfb`` if no
display is available, making it convenient to debug in headless
environments such as CI or containers. The ``-Xfrozen_modules=off`` option
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
python main.py --vm-debug
```
This calls ``launch_vm_debug`` which tries Docker or Podman first, then Vagrant,
falling back to ``run_debug.sh`` if neither is available.

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
* ``--top`` scans the top N most common ports instead of ``PORTS``

The ``PORTS`` argument accepts service names (``ssh``), ranges with optional
steps (``20-30:2``), comma separated lists (``22,80``) and ``topN`` shortcuts.
Hosts may be specified individually or using CIDR notation, ranges and ``*``
wildcards like ``192.168.1.*``.

### Auto Network Scan

From the **Tools** view choose *Auto Network Scan* to open a modern dialog with scanning options on the left and a results table on the right. CoolBox automatically detects local subnets using `psutil` and pings each address to find active hosts before scanning the specified ports. A progress bar tracks detection and scanning with results displayed in a scrollable list when complete.

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
Docker environments.  You may also use ``./scripts/run_vm_debug.sh`` or
``python scripts/run_vm_debug.py`` (``.\scripts\run_vm_debug.ps1`` on Windows) which choose Docker/Podman or Vagrant
depending on what is installed. If neither is present, it falls back to
``run_debug.sh`` so you can still debug locally.

### Debugging in a Vagrant VM

If you prefer a lightweight virtual machine instead of Docker, a
`Vagrantfile` is provided. This sets up an Ubuntu VM with all
dependencies preinstalled and starts CoolBox under `debugpy`.
The debug server port **5678** is forwarded to the host so you can attach
to `localhost:5678`:

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
Python script so all command line options like ``--prefer`` and ``--code`` are
available on both Unix and Windows.
Use the ``--code`` flag to open Visual Studio Code before launching the
environment so it's ready to attach to the debug server.
Run ``python scripts/run_vm_debug.py --list`` to display the backends
detected on your system.

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
