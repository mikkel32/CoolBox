# 🎉 CoolBox

A modern, feature-rich desktop application built with Python and CustomTkinter.

## 🚀 Features

- **Modern UI**: Beautiful dark/light theme with smooth animations
- **Modular Architecture**: Clean, maintainable code structure
- **Rich Toolset**: File tools, system utilities, text processing, and more
- **Customizable**: Extensive settings and preferences
- **Cross-Platform**: Works on Windows, macOS, and Linux
- **Expanded Utilities**: File and directory copy/move helpers, an enhanced file manager, and a threaded port scanner

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
pip install -r requirements.txt
```

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
This requires Docker to be installed on your system. Like
``run_debug.sh``, the script automatically launches the app under
``xvfb`` if no display is detected so the GUI works even in headless
Docker environments.

### Debugging in a Vagrant VM

If you prefer a lightweight virtual machine instead of Docker, a
`Vagrantfile` is provided. This sets up an Ubuntu VM with all
dependencies preinstalled and starts CoolBox under `debugpy`.
The debug server port **5678** is forwarded to the host so you can attach
to `localhost:5678`:

```bash
./scripts/run_vagrant.sh
```

The first run may take a while while Vagrant downloads the base box and
installs packages. Once finished, Visual Studio Code can attach to the
debug server on port `5678` using the **Python: Attach** configuration.

### Debugging with VS Code

1. Open the project folder in Visual Studio Code.
2. Ensure the Python extension is installed.
3. Press `F5` or choose **Run > Start Debugging** to launch the app using the
   configuration provided in `.vscode/launch.json`.
4. Alternatively, run `./scripts/run_debug.sh` and select the
   **Python: Attach** configuration to connect the debugger.

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
