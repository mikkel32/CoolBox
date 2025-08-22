#!/usr/bin/env python3
"""CoolBox — install/inspect utilities with neon border UI, atomic console, and end-of-run summary.

Changes:
- Removed border during subprocess work by default. Enable with --border or COOLBOX_BORDER=1.
- Progress + panels use the underlying Rich Console (no wrapper quirks).
- LockingConsole now fully context-manager compatible and exposes .raw for Rich internals.
- Non-interactive subprocess env to avoid stalls.
"""

from __future__ import annotations

__version__ = "1.5.6"

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
import threading
import socket
import logging
import json
import re
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from pathlib import Path
from typing import Sequence, Tuple, TYPE_CHECKING, TypeAlias
from types import ModuleType
import urllib.request

if TYPE_CHECKING:  # pragma: no cover - for static type checkers
    from rich.console import Console as ConsoleType
    from rich.text import Text as TextType
else:  # pragma: no cover - runtime fallbacks for annotations
    ConsoleType: TypeAlias = object
    TextType: TypeAlias = str

# ---------- rich UI ----------
RICH_AVAILABLE = False
try:
    from rich.console import Console as _RichConsole
    from rich.table import Table as _RichTable
    from rich.panel import Panel as _RichPanel
    from rich.progress import (
        Progress as _RichProgress,
        BarColumn as _RichBarColumn,
        TimeElapsedColumn as _RichTimeElapsedColumn,
        TaskProgressColumn as _RichTaskProgressColumn,
        MofNCompleteColumn as _RichMofNCompleteColumn,
        ProgressColumn as _RichProgressColumn,
    )
    from rich.text import Text as _RichText
    from rich import box as _rich_box
    from rich.traceback import install as _rich_tb_install

    _rich_tb_install(show_locals=False)
    RICH_AVAILABLE = True
except ImportError:  # pragma: no cover
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "rich>=13"],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        from rich.console import Console as _RichConsole
        from rich.table import Table as _RichTable
        from rich.panel import Panel as _RichPanel
        from rich.progress import (
            Progress as _RichProgress,
            BarColumn as _RichBarColumn,
            TimeElapsedColumn as _RichTimeElapsedColumn,
            TaskProgressColumn as _RichTaskProgressColumn,
            MofNCompleteColumn as _RichMofNCompleteColumn,
            ProgressColumn as _RichProgressColumn,
        )
        from rich.text import Text as _RichText
        from rich import box as _rich_box

        RICH_AVAILABLE = True
    except Exception:
        RICH_AVAILABLE = False

if RICH_AVAILABLE:
    Console = _RichConsole
    Table = _RichTable
    Panel = _RichPanel
    Progress = _RichProgress
    BarColumn = _RichBarColumn
    TimeElapsedColumn = _RichTimeElapsedColumn
    TaskProgressColumn = _RichTaskProgressColumn
    MofNCompleteColumn = _RichMofNCompleteColumn
    ProgressColumn = _RichProgressColumn
    Text = _RichText
    box = _rich_box
else:  # pragma: no cover - executed when rich unavailable

    class _PlainConsole:
        def print(self, *args, **kwargs) -> None:
            print(*args, **kwargs)

        def log(self, *args, **kwargs) -> None:
            print(*args, **kwargs)

        def flush(self) -> None:
            sys.stdout.flush()

    class _PlainTable:
        def __init__(self, *_, **__):
            self._rows: list[str] = []

        def add_column(self, *_, **__) -> None:
            pass

        def add_row(self, *args, **__) -> None:
            self._rows.append(" ".join(str(a) for a in args))

        def __str__(self) -> str:  # pragma: no cover - simple fallback
            return "\n".join(self._rows)

    class _PlainPanel:
        def __init__(self, content, **__):
            self.content = content

        def __str__(self) -> str:  # pragma: no cover
            return str(self.content)

    class _PlainProgress:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def add_task(self, *_, **__):
            return 0

        def advance(self, *_, **__):
            pass

    class _PlainText(str):
        def append(self, ch: str, style: str | None = None) -> None:  # pragma: no cover - simple fallback
            pass

    Console = _PlainConsole
    Table = _PlainTable
    Panel = _PlainPanel
    Progress = _PlainProgress
    BarColumn = TimeElapsedColumn = TaskProgressColumn = MofNCompleteColumn = ProgressColumn = object
    Text = _PlainText

    class _Box:
        SIMPLE_HEAVY = ROUNDED = MINIMAL_DOUBLE_HEAD = None

    box = _Box()

# ---------- optional project helpers ----------
try:
    from src.ensure_deps import ensure_numpy  # type: ignore
except Exception as exc:  # pragma: no cover
    print(f"Warning: could not import ensure_numpy ({exc}).", file=sys.stderr)

    def ensure_numpy(version: str | None = None) -> ModuleType:  # type: ignore
        """Fallback numpy import that errors loudly if numpy is missing."""
        try:
            return __import__("numpy")
        except ImportError as np_exc:
            msg = "numpy is required but was not found. Install it with 'pip install numpy'."
            print(msg, file=sys.stderr)
            raise ImportError(msg) from np_exc


try:
    from src.utils.system_utils import (  # type: ignore
        get_system_info,
        console as _helper_console,
    )
except Exception as exc:  # pragma: no cover
    print(
        f"Warning: helper utilities unavailable ({exc}). Using fallbacks.",
        file=sys.stderr,
    )
    _helper_console = None

    def get_system_info() -> str:  # type: ignore
        lines = [
            f"Python:   {sys.version.split()[0]} ({sys.executable})",
            f"Platform: {sys.platform}",
            f"CWD:      {Path.cwd()}",
        ]
        return "\n".join(lines)


# ---------- logging ----------
logger = logging.getLogger("coolbox.setup")
logger.setLevel(logging.INFO)
if os.environ.get("COOLBOX_LOG_FILE"):
    fh = logging.FileHandler(os.environ["COOLBOX_LOG_FILE"])
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(fh)
else:
    logger.addHandler(logging.NullHandler())

# Prevent messages from propagating to the root logger.
# This avoids duplicate output when other parts of the application
# configure root logging.
logger.propagate = False

# ---------- configuration ----------

DEFAULT_RAINBOW = (
    "#e40303",
    "#ff8c00",
    "#ffed00",
    "#008026",
    "#004dff",
    "#750787",
)


def _load_user_config() -> dict:
    for p in (Path.home() / ".coolboxrc", Path.cwd() / ".coolboxrc"):
        if p.exists():
            try:
                return json.loads(p.read_text())
            except Exception:
                logger.warning("Failed to read config %s", p)
    return {}


@dataclass
class Config:
    no_git: bool = os.environ.get("COOLBOX_NO_GIT") == "1"
    cli_no_anim: bool = os.environ.get("COOLBOX_FORCE_NO_ANIM") == "1"
    no_anim: bool = False
    border_enabled_default: bool = False
    alt_screen: bool = False
    rainbow_colors: Sequence[str] = field(default_factory=lambda: DEFAULT_RAINBOW)


CONFIG = Config()
USER_CFG = _load_user_config()
for key, value in USER_CFG.items():
    if hasattr(CONFIG, key):
        setattr(CONFIG, key, value)

IS_TTY = sys.stdout.isatty()

CONFIG.no_anim = (
    CONFIG.cli_no_anim
    or os.environ.get("COOLBOX_NO_ANIM") == "1"
    or os.environ.get("COOLBOX_CI") == "1"
    or os.environ.get("CI") == "1"
    or not IS_TTY
)
_border_env = os.environ.get("COOLBOX_BORDER")
CONFIG.border_enabled_default = IS_TTY if _border_env is None else _border_env == "1"
CONFIG.alt_screen = os.environ.get("COOLBOX_ALT_SCREEN") == "1"

if os.environ.get("COOLBOX_COLORS"):
    CONFIG.rainbow_colors = tuple(os.environ["COOLBOX_COLORS"].split(","))

RAINBOW_COLORS: Sequence[str] = tuple(CONFIG.rainbow_colors)


# ---------- neon border fallback ----------
class _NoopBorder:
    def __init__(self, *_, **__):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


try:
    from src.utils.rainbow import NeonPulseBorder as _BorderImpl  # type: ignore
except Exception:
    _BorderImpl = _NoopBorder  # type: ignore


def NeonPulseBorder(**kwargs):
    return _BorderImpl(**kwargs)


# ---------- rainbow helpers ----------


class RainbowSpinnerColumn(ProgressColumn):
    """Spinner that cycles through a rainbow of colors."""

    def __init__(self, frames: str = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", colors: Sequence[str] | None = None):
        # Ensure ProgressColumn is initialised so Rich can access internal
        # attributes such as ``_table_column``. Rich 14+ requires custom
        # progress columns to call ``super().__init__`` to set these up
        # correctly, otherwise an ``AttributeError`` is raised during
        # rendering.
        super().__init__()
        self.frames = frames
        self.colors = list(colors or RAINBOW_COLORS)
        self._index = 0

    def render(self, task):  # type: ignore[override]
        char = self.frames[self._index % len(self.frames)]
        color = self.colors[self._index % len(self.colors)]
        self._index += 1
        return Text(char, style=color)


def rainbow_text(msg: str, colors: Sequence[str] | None = None) -> TextType:
    """Return Text with a simple rainbow gradient."""
    colors = list(colors or RAINBOW_COLORS)
    t = Text()
    for i, ch in enumerate(msg):
        t.append(ch, style=colors[i % len(colors)])
    return t


# ---------- atomic console ----------
class LockingConsole:
    """Thread-safe console wrapper compatible with Rich. Exposes .raw for internals."""

    def __init__(self, base: ConsoleType | None = None):
        self._lock = threading.RLock()
        self._console = base or Console(soft_wrap=False, highlight=False)

    # Context manager support
    def __enter__(self):
        enter = getattr(self._console, "__enter__", None)
        if callable(enter):
            enter()
        return self

    def __exit__(self, exc_type, exc, tb):
        exit_ = getattr(self._console, "__exit__", None)
        if callable(exit_):
            return exit_(exc_type, exc, tb)
        return False

    def print(self, *args, **kwargs):
        with self._lock:
            self._console.print(*args, **kwargs)

    def log(self, *args, **kwargs):
        with self._lock:
            self._console.log(*args, **kwargs)

    def flush(self):
        with self._lock:
            try:
                self._console.file.flush()
            except Exception:
                pass

    @property
    def raw(self) -> ConsoleType:
        """Underlying Rich Console for constructs that expect a real Console."""
        return self._console

    def __getattr__(self, name):
        return getattr(self._console, name)


# ---------- env + constants ----------


def _detect_offline(timeout: float = 1.5) -> bool:
    """Return True if network appears unreachable."""
    try:
        with socket.create_connection(("pypi.org", 443), timeout=timeout):
            return False
    except OSError:
        return True


_OFFLINE_FORCED = os.environ.get("COOLBOX_OFFLINE") == "1"
_OFFLINE_AUTO: bool | None = None


def set_offline(value: bool) -> None:
    global _OFFLINE_FORCED, _OFFLINE_AUTO
    _OFFLINE_FORCED = value
    _OFFLINE_AUTO = True if value else None
    if value:
        os.environ["COOLBOX_OFFLINE"] = "1"
        BASE_ENV["COOLBOX_OFFLINE"] = "1"
    else:
        os.environ.pop("COOLBOX_OFFLINE", None)
        BASE_ENV.pop("COOLBOX_OFFLINE", None)


def is_offline() -> bool:
    if _OFFLINE_FORCED:
        return True
    global _OFFLINE_AUTO
    if _OFFLINE_AUTO is None:
        _OFFLINE_AUTO = _detect_offline()
    return _OFFLINE_AUTO


def offline_auto_detected() -> bool:
    return (_OFFLINE_AUTO is True) and not _OFFLINE_FORCED


BASE_ENV = {
    **os.environ,
    "PIP_DISABLE_PIP_VERSION_CHECK": "1",
    "PIP_NO_INPUT": "1",
    "PYTHONUNBUFFERED": "1",
    "PYTHONIOENCODING": "utf-8",
    "GIT_TERMINAL_PROMPT": "0",
}

# One global console
console = LockingConsole(_helper_console or Console(soft_wrap=False, highlight=False))

MIN_PYTHON: Tuple[int, int] = (3, 10)
if sys.version_info < MIN_PYTHON:
    raise RuntimeError(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required")


def locate_root(start: Path) -> Path:
    """Locate project root by walking parents for common markers."""
    p = Path(start).resolve()
    markers = {"requirements.txt", "pyproject.toml", ".git"}
    for parent in (p, *p.parents):
        if any((parent / m).exists() for m in markers):
            return parent
    return p


def get_root() -> Path:
    env = os.environ.get("COOLBOX_ROOT")
    if env:
        return Path(env).resolve()
    return locate_root(Path(__file__).resolve())


def get_venv_dir() -> Path:
    env = os.environ.get("COOLBOX_VENV")
    if env:
        return Path(env).resolve()
    return get_root() / ".venv"


ROOT_DIR = get_root()
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
DEV_PACKAGES: Sequence[str] = ("pip-tools>=7", "build>=1", "wheel>=0.43", "pytest>=8")

# default lightweight mode
os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")


def log(msg: str) -> None:
    logger.info(msg)
    try:
        console.print(f"[dim]»[/] {msg}")
    except Exception:
        print(msg)


def show_setup_banner() -> None:
    """Display a fancy rainbow setup banner for CoolBox."""
    banner = rainbow_text(f" CoolBox setup v{__version__} ")
    path = Text(str(ROOT_DIR), style="bold magenta")
    content = Text.assemble(banner, "\n", path)
    console.print(Panel(content, box=box.ROUNDED, expand=False))


def check_python_version() -> None:
    """Verify the current Python version meets requirements."""
    if sys.version_info < MIN_PYTHON:
        raise RuntimeError(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required")


# ---------- summary ----------
class RunSummary:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def add_warning(self, msg: str) -> None:
        self.warnings.append(msg)
        log(f"[yellow]WARN[/]: {msg}")

    def add_error(self, msg: str) -> None:
        self.errors.append(msg)
        log(f"[red]ERROR[/]: {msg}")

    def render(self) -> None:
        if not self.warnings and not self.errors:
            panel = Panel.fit("[green]No warnings or errors.[/]", title="Summary", box=box.ROUNDED)
            console.print(panel)
            return
        table = Table(box=box.SIMPLE_HEAVY)
        table.add_column("Type", no_wrap=True)
        table.add_column("Message", overflow="fold")
        for w in self.warnings:
            table.add_row("[yellow]Warning[/]", w)
        for e in self.errors:
            table.add_row("[red]Error[/]", e)
        console.print(Panel(table, title="Summary", box=box.ROUNDED))
        total = len(self.warnings) + len(self.errors)
        console.print(
            f"[bold]Total problems: {total} (Warnings: {len(self.warnings)}, Errors: {len(self.errors)})[/]"
        )


SUMMARY = RunSummary()


def send_telemetry(summary: RunSummary) -> None:
    """Send anonymized telemetry if configured."""
    url = os.environ.get("COOLBOX_TELEMETRY_URL")
    if not url:
        return
    data = {
        "warnings": summary.warnings,
        "errors": summary.errors,
        "platform": sys.platform,
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(data).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        urllib.request.urlopen(req, timeout=2)  # pragma: no cover - network
    except Exception:
        pass


# ---------- helpers ----------
def _venv_python() -> str:
    venv_dir = get_venv_dir()
    py = venv_dir / ("Scripts/python.exe" if sys.platform.startswith("win") else "bin/python")
    return str(py)


def ensure_venv() -> str:
    venv_dir = get_venv_dir()
    if not venv_dir.exists():
        log(f"Creating venv at {venv_dir}")
        import venv as _venv

        _venv.EnvBuilder(with_pip=True, clear=False, upgrade=False).create(str(venv_dir))
    return _venv_python()


def _run(cmd: Sequence[str], *, cwd: Path | None = None, env: dict | None = None, timeout: float | None = None) -> None:
    """Run command in non-interactive mode. Inherit IO for live display."""
    final_env = dict(BASE_ENV)
    if env:
        final_env.update(env)
    try:
        res = subprocess.run(list(cmd), cwd=cwd, env=final_env, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"Command '{' '.join(cmd)}' timed out after {timeout}s") from e
    if res.returncode != 0:
        raise subprocess.CalledProcessError(res.returncode, cmd)


def _retry(
    cmd: Sequence[str], *, attempts: int = 3, delay: float = 0.8, cwd: Path | None = None, timeout: float | None = None
) -> None:
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            _run(cmd, cwd=cwd, timeout=timeout)
            return
        except Exception as e:  # pragma: no cover
            last = e
            if i < attempts:
                time.sleep(delay * i)
    if last is not None:
        raise last


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _stamp_path() -> Path:
    return get_venv_dir() / ".req_hash"


def _should_install(req: Path, upgrade: bool) -> bool:
    if upgrade:
        return True
    if not req.exists():
        return False
    sp = _stamp_path()
    if not sp.exists():
        return True
    try:
        return sp.read_text().strip() != _file_hash(req)
    except Exception:
        return True


def _write_req_stamp(req: Path) -> None:
    _stamp_path().write_text(_file_hash(req), encoding="utf-8")


def update_repo() -> None:
    if CONFIG.no_git or is_offline():
        log("Skip git update (disabled or offline).")
        return
    if not (ROOT_DIR / ".git").exists():
        log("No .git directory. Skipping update.")
        return
    log("Updating repository...")
    try:
        _retry(["git", "-C", str(ROOT_DIR), "fetch", "--all", "--tags", "--prune"], attempts=2)
        _retry(["git", "-C", str(ROOT_DIR), "pull", "--rebase", "--autostash"], attempts=2)
    except Exception as e:
        SUMMARY.add_warning(f"git update failed: {e}")


def build_extensions() -> None:
    try:
        py = ensure_venv()
        _run([py, "-m", "build", "--wheel", "--no-isolation"], cwd=ROOT_DIR)
    except Exception as e:
        SUMMARY.add_warning(f"native build skipped: {e}")


def _progress(**overrides):
    """Progress configured for safety on all terminals."""
    return Progress(
        RainbowSpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        refresh_per_second=12,
        console=console.raw,  # use real Console
        transient=True,
        disable=CONFIG.no_anim,  # auto-disable when not TTY or CI
        **overrides,
    )


def _pip(
    args: Sequence[str],
    python: str | Path | None = None,
    *,
    upgrade_pip: bool = False,
    attempts: int = 2,
) -> None:
    """Run pip with retries. No border by default to avoid UI deadlocks."""
    py = str(python or ensure_venv())
    base_cmd = [py, "-m", "pip"]

    if is_offline():
        SUMMARY.add_warning("Offline mode: skipping " + " ".join(base_cmd + list(args)))
        return

    if upgrade_pip:
        _retry(base_cmd + ["install", "-U", "pip", "setuptools", "wheel"], attempts=attempts)
    cmd = base_cmd + list(args)

    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            _run(cmd)  # live output, non-interactive env, no prompts
            return
        except Exception as e:  # pragma: no cover
            last = e
            if i < attempts:
                time.sleep(0.8 * i)
    if last is not None:
        raise last


def check_outdated(*, requirements: Path | None, upgrade: bool = False) -> None:
    import json

    py = ensure_venv()
    cmd = [py, "-m", "pip", "list", "--outdated", "--format=json"]
    try:
        out = subprocess.check_output(cmd, text=True, env=BASE_ENV)
        pkgs = json.loads(out)
    except Exception as e:
        SUMMARY.add_warning(f"pip list --outdated failed: {e}")
        pkgs = []

    if upgrade and pkgs:
        with _progress() as prog:
            t = prog.add_task("Upgrading outdated packages", total=len(pkgs))

            def _worker(name: str) -> None:
                try:
                    _pip(["install", "-U", name], upgrade_pip=False, attempts=2)
                except Exception as e:  # pragma: no cover - network failures
                    SUMMARY.add_error(f"Upgrade {name} failed: {e}")
                finally:
                    prog.advance(t)

            with ThreadPoolExecutor() as ex:
                for item in pkgs:
                    name = item.get("name")
                    if name:
                        ex.submit(_worker, name)
    else:
        table = Table(title="Outdated packages", box=box.SIMPLE_HEAVY)
        table.add_column("Name")
        table.add_column("Version")
        table.add_column("Latest")
        table.add_column("Type")
        for p in pkgs:
            table.add_row(p.get("name", ""), p.get("version", ""), p.get("latest_version", ""), p.get("type", ""))
        console.print(table)


def show_info() -> None:
    info = get_system_info()
    table = Table(title="CoolBox — System Info", box=box.MINIMAL_DOUBLE_HEAD)
    for k, v in info.items():
        table.add_row(k, str(v))
    console.print(table)


def run_tests(extra: Sequence[str]) -> None:
    py = ensure_venv()
    with _progress() as prog:
        prog.add_task("Running tests")
        try:
            _run([py, "-m", "pytest", "-q", *extra])
        except Exception as e:
            SUMMARY.add_error(f"pytest failed: {e}")


def doctor() -> None:
    problems: list[str] = []
    if is_offline():
        problems.append("offline mode active, downloads disabled.")
    if CONFIG.no_git:
        problems.append("NO_GIT set, repo update disabled.")
    if not REQUIREMENTS_FILE.exists():
        problems.append("requirements.txt not found.")
    console.print(Panel.fit("\n".join(problems) or "No obvious problems.", title="Doctor", box=box.ROUNDED))


def lock() -> None:
    py = ensure_venv()
    try:
        _pip(["install", "-U", "pip-tools"], upgrade_pip=False)
        _run([py, "-m", "piptools", "compile", str(REQUIREMENTS_FILE), "--upgrade"])
    except Exception as e:
        SUMMARY.add_error(f"Lock failed: {e}")


def sync(lock_file: Path | None, *, upgrade: bool = False) -> None:
    py = ensure_venv()
    try:
        _pip(["install", "-U", "pip-tools"], upgrade_pip=False)
        args = [py, "-m", "piptools", "sync"]
        if lock_file:
            args.append(str(lock_file))
        if upgrade:
            _pip(["install", "-U", "-r", str(REQUIREMENTS_FILE)], upgrade_pip=False)
        _run(args)
    except Exception as e:
        SUMMARY.add_error(f"Sync failed: {e}")


def self_update() -> None:
    py = ensure_venv()
    try:
        _run([py, "-m", "pip", "install", "-U", "coolbox"])
    except Exception as e:  # pragma: no cover - network/install issues
        SUMMARY.add_error(f"Self-update failed: {e}")


def clean_pyc() -> None:
    n = 0
    for p in ROOT_DIR.rglob("*"):
        if p.is_dir() and p.name == "__pycache__":
            shutil.rmtree(p, ignore_errors=True)
            n += 1
    log(f"Removed {n} __pycache__ folders.")


def collect_problems(
    output: Path | None = None, markers: Sequence[str] | None = None
) -> None:
    """Scan project files for common problem markers.

    By default this searches for ``TODO``, ``FIXME``, ``BUG`` and ``WARNING``
    comments across the repository.  All matches are appended to the global
    ``SUMMARY`` so they are displayed in the final run report.  A custom list of
    *markers* can be provided via ``markers``.
    """

    markers = [m.strip() for m in (markers or ["TODO", "FIXME", "BUG", "WARNING"])]
    pattern = "|".join(re.escape(m) for m in markers)
    problem_re = re.compile(f"({pattern})", re.IGNORECASE)
    ignore_dirs = {".git", ".venv", "venv", "__pycache__"}

    files = [
        p
        for p in ROOT_DIR.rglob("*")
        if p.is_file() and not any(part in ignore_dirs for part in p.parts)
    ]

    def _scan(path: Path) -> list[tuple[str, int, str]]:
        results: list[tuple[str, int, str]] = []
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                for lineno, line in enumerate(fh, 1):
                    if problem_re.search(line):
                        rel = path.relative_to(ROOT_DIR)
                        results.append((str(rel), lineno, line.rstrip()))
        except Exception as exc:  # pragma: no cover - file read errors
            SUMMARY.add_warning(f"Could not read {path}: {exc}")
        return results

    matches: list[tuple[str, int, str]] = []
    with ThreadPoolExecutor() as ex:
        for res in ex.map(_scan, files):
            matches.extend(res)

    matches.sort()

    # Record all problem lines in the run summary for later display.
    for f, n, t in matches:
        SUMMARY.warnings.append(f"{f}:{n}: {t}")

    count = len(matches)
    if output:
        output.write_text("\n".join(f"{f}:{n}: {t}" for f, n, t in matches))
        log(f"Wrote {count} problem line{'s' if count != 1 else ''} to {output}")
    else:
        if RICH_AVAILABLE:
            table = Table(box=box.SIMPLE_HEAVY)
            table.add_column("File", overflow="fold")
            table.add_column("Line", justify="right")
            table.add_column("Text")
            for f, n, t in matches:
                table.add_row(f, str(n), t)
            console.print(Panel(table, title=f"Problems ({count})", box=box.ROUNDED))
            problem_word = "problem" if count == 1 else "problems"
            console.print(f"[bold]{count} {problem_word} found.[/]")
        else:
            for f, n, t in matches:
                log(f"{f}:{n}: {t}")
            log(f"Found {count} problem line{'s' if count != 1 else ''}.")


def _build_install_plan(req_path: Path, dev: bool, upgrade: bool) -> list[tuple[str, list[str], bool]]:
    """Assemble pip commands needed for installation."""
    planned: list[tuple[str, list[str], bool]] = []

    if req_path.is_file():
        if _should_install(req_path, upgrade):
            args = ["install", "-r", str(req_path)]
            if upgrade:
                args.append("-U")
            planned.append(("Install requirements", args, True))
        else:
            log("Requirements unchanged. Skipping install.")
    else:
        SUMMARY.add_warning(f"Requirements file missing: {req_path}")

    if dev:
        dev_req = ROOT_DIR / "requirements-dev.txt"
        if dev_req.is_file():
            args = ["install", "-r", str(dev_req)]
            if upgrade:
                args.append("-U")
            planned.append(("Install dev requirements", args, True))
        else:
            for pkg in DEV_PACKAGES:
                args = ["install", pkg]
                if upgrade:
                    args.append("-U")
                planned.append((f"Install {pkg}", args, False))

    return planned


def _execute_install_plan(planned: Sequence[tuple[str, list[str], bool]]) -> None:
    """Run the pip commands described by *planned*."""
    if not planned:
        return
    with _progress() as prog:
        t = prog.add_task("Executing install plan", total=len(planned))
        for title, pip_args, upgrade_pip in planned:
            prog.update(t, description=title)
            try:
                _pip(pip_args, upgrade_pip=upgrade_pip, attempts=3)
            except Exception as e:
                SUMMARY.add_error(f"{title} failed: {e}")
            prog.advance(t)


def install(
    requirements: Path | None = None,
    *,
    dev: bool = False,
    upgrade: bool = False,
    skip_update: bool = False,
    no_anim: bool | None = None,
    border: bool | None = None,
    alt_screen: bool | None = None,
) -> None:
    os.chdir(ROOT_DIR)
    if not skip_update:
        update_repo()

    ensure_numpy()
    py = ensure_venv()

    # runtime toggles
    if no_anim is True:
        CONFIG.no_anim = True
    if alt_screen is True:
        CONFIG.alt_screen = True
    border_enabled = CONFIG.border_enabled_default if border is None else bool(border)
    if CONFIG.no_anim:
        border_enabled = False

    req_path = requirements or REQUIREMENTS_FILE
    planned = _build_install_plan(req_path, dev, upgrade)

    border_ctx = (
        NeonPulseBorder(
            speed=0.04,
            style="rounded",
            theme="pride",
            thickness=2,
            use_alt_screen=CONFIG.alt_screen,
            console=console.raw,  # pass real Console
        )
        if border_enabled
        else nullcontext()
    )

    try:
        with border_ctx:
            show_setup_banner()
            _execute_install_plan(planned)

            try:
                _retry([py, "-m", "pip", "check"], attempts=1)
            except Exception as exc:
                SUMMARY.add_warning(f"pip check reported issues: {exc}")

            build_extensions()
    finally:
        console.flush()

    if req_path.is_file():
        try:
            _write_req_stamp(req_path)
        except Exception as e:
            SUMMARY.add_warning(f"Could not write requirement stamp: {e}")

    log("Done.")


# ---------- CLI ----------
def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="coolbox-setup", description="Install and inspect CoolBox deps.")
    p.add_argument("--offline", action="store_true", help="Force offline mode (skip network calls)")
    sub = p.add_subparsers(dest="command", required=False)

    p_install = sub.add_parser("install", help="Install requirements and dev extras")
    p_install.add_argument("--requirements", type=Path, default=None)
    p_install.add_argument("--dev", action="store_true")
    p_install.add_argument("--upgrade", action="store_true")
    p_install.add_argument("--skip-update", action="store_true")
    p_install.add_argument("--no-anim", action="store_true", help="Disable animations for this run")
    p_install.add_argument("--border", action="store_true", help="Enable neon border UI")
    p_install.add_argument("--alt-screen", action="store_true", help="Use alternate screen buffer")

    sub.add_parser("info", help="Show system info")
    sub.add_parser("doctor", help="Run quick diagnostics")

    p_check = sub.add_parser("check", help="List outdated packages")
    p_check.add_argument("--requirements", type=Path, default=None)

    p_up = sub.add_parser("upgrade", help="Upgrade all outdated packages")
    p_up.add_argument("--upgrade", action="store_true", default=True)

    sub.add_parser("lock", help="Generate lock file with pip-tools")
    p_sync = sub.add_parser("sync", help="Sync environment from lock file")
    p_sync.add_argument("--lock-file", type=Path, default=None)
    p_sync.add_argument("--upgrade", action="store_true")

    p_venv = sub.add_parser("venv", help="Create or recreate venv")
    p_venv.add_argument("--recreate", action="store_true")

    sub.add_parser("clean-pyc", help="Remove __pycache__ folders")

    p_prob = sub.add_parser("problems", help="Scan project for problem markers")
    p_prob.add_argument("--output", type=Path, default=None, help="Write results to file")
    p_prob.add_argument(
        "--markers",
        type=str,
        default=None,
        help="Comma separated markers (default: TODO,FIXME,BUG,WARNING)",
    )

    p_test = sub.add_parser("test", help="Run pytest")
    p_test.add_argument("extra", nargs="*", default=[])

    sub.add_parser("update", help="git fetch/pull if repo")
    sub.add_parser("self-update", help="Update the CoolBox setup script")

    p.set_defaults(command="install")
    _load_plugins(sub)
    return p.parse_args(argv)


def _load_plugins(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    """Load external CLI plugins via entry points."""
    try:
        from importlib.metadata import entry_points
    except Exception:
        return
    try:
        for ep in entry_points().select(group="coolbox.plugins"):
            try:
                ep.load()(sub)
            except Exception as exc:  # pragma: no cover - plugin errors
                SUMMARY.add_warning(f"Plugin {ep.name} failed: {exc}")
    except Exception:
        pass


def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv or sys.argv[1:])
    if getattr(args, "offline", False):
        set_offline(True)
    is_offline()  # prime detection so we can report status early
    if offline_auto_detected():
        log("Offline mode detected (network unreachable).")
    cmd = args.command

    exit_code = 0
    try:
        if cmd == "install":
            install(
                requirements=getattr(args, "requirements", None),
                dev=getattr(args, "dev", False),
                upgrade=getattr(args, "upgrade", False),
                skip_update=getattr(args, "skip_update", False),
                no_anim=getattr(args, "no_anim", False),
                border=getattr(args, "border", None),
                alt_screen=getattr(args, "alt_screen", None),
            )
        elif cmd == "check":
            check_outdated(requirements=args.requirements)
        elif cmd == "upgrade":
            check_outdated(requirements=None, upgrade=True)
        elif cmd == "info":
            show_info()
        elif cmd == "venv":
            if getattr(args, "recreate", False):
                vdir = get_venv_dir()
                if vdir.exists():
                    shutil.rmtree(vdir, ignore_errors=True)
                    log("Virtualenv removed.")
            ensure_venv()
            log("Virtualenv ready.")
        elif cmd == "clean-pyc":
            clean_pyc()
        elif cmd == "problems":
            markers = getattr(args, "markers", None)
            collect_problems(
                output=getattr(args, "output", None),
                markers=[m.strip() for m in markers.split(",")] if markers else None,
            )
        elif cmd == "test":
            run_tests(args.extra)
        elif cmd == "update":
            update_repo()
        elif cmd == "doctor":
            doctor()
        elif cmd == "lock":
            lock()
        elif cmd == "sync":
            sync(args.lock_file, upgrade=args.upgrade)
        elif cmd == "self-update":
            self_update()
        else:
            install()
    except KeyboardInterrupt:
        SUMMARY.add_warning("Interrupted by user.")
        exit_code = 130
    except BaseException as e:
        SUMMARY.add_error(f"Fatal: {e.__class__.__name__}: {e}")
        exit_code = 1
        raise
    else:
        exit_code = 0
    finally:
        if cmd != "problems":
            try:
                collect_problems()
            except Exception as exc:  # pragma: no cover - best effort
                SUMMARY.add_error(f"Problem scan failed: {exc}")
        SUMMARY.render()
        send_telemetry(SUMMARY)
        if exit_code == 0 and SUMMARY.errors:
            exit_code = 1
        sys.exit(exit_code)


if __name__ == "__main__":
    main()
