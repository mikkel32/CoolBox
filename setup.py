#!/usr/bin/env python3
"""CoolBox — install/inspect utilities with neon border UI, atomic console, and end-of-run summary."""

from __future__ import annotations

__version__ = "1.6.0"

import argparse
import hashlib
import shlex
import os
import platform
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
from typing import Sequence, Tuple, TYPE_CHECKING, TypeAlias, Literal
from types import ModuleType
import urllib.request
import urllib.parse

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.markers import default_environment
from packaging.version import Version, InvalidVersion

from src.setup.run_summary import CommandRecord, RunSummaryPanelModel
from src.setup import stages as setup_stages

if TYPE_CHECKING:
    from rich.console import Console
    from rich.table import Table, Column
    from rich.panel import Panel
    from rich.progress import (
        Progress,
        BarColumn,
        TimeElapsedColumn,
        TaskProgressColumn,
        MofNCompleteColumn,
        ProgressColumn,
    )
    from rich.text import Text
    from rich import box

    ConsoleType = Console
    TextType = Text
    Console = Console
    Table = Table
    Panel = Panel
    Progress = Progress
    BarColumn = BarColumn
    TimeElapsedColumn = TimeElapsedColumn
    TaskProgressColumn = TaskProgressColumn
    MofNCompleteColumn = MofNCompleteColumn
    ProgressColumn = ProgressColumn
    Column = Column
    Text = Text
    box = box
    RICH_AVAILABLE = True
else:
    ConsoleType: TypeAlias = object
    TextType: TypeAlias = str

    # ---------- rich UI ----------
    _RichConsole = _RichTable = _RichPanel = _RichProgress = None
    _RichBarColumn = _RichTimeElapsedColumn = _RichTaskProgressColumn = None
    _RichMofNCompleteColumn = _RichProgressColumn = None
    _RichColumn = _RichText = None
    _rich_box = None
    RICH_AVAILABLE = False
    try:
        from rich.console import Console as _RichConsole
        from rich.table import Table as _RichTable, Column as _RichColumn
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
    except ImportError:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "rich>=13"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            from rich.console import Console as _RichConsole
            from rich.table import Table as _RichTable, Column as _RichColumn
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
        Column = _RichColumn
        Text = _RichText
        box = _rich_box
    else:

        class _PlainConsole:
            def print(self, *args, **kwargs) -> None: print(*args, **kwargs)

            def log(self, *args, **kwargs) -> None: print(*args, **kwargs)

            def flush(self) -> None: sys.stdout.flush()

        class _PlainTable:
            def __init__(self, *_, **__): self._rows: list[str] = []

            def add_column(self, *_, **__) -> None: ...

            def add_row(self, *args, **__) -> None: self._rows.append(
                " ".join(str(a) for a in args)
            )

            def __str__(self) -> str: return "\n".join(self._rows)

        class _PlainPanel:
            def __init__(self, content, **__): self.content = content

            def __str__(self) -> str: return str(self.content)

        class _PlainProgress:
            def __enter__(self): return self

            def __exit__(self, *exc): return False

            def add_task(self, *_, **__): return 0

            def advance(self, *_, **__): ...

        class _PlainText(str):
            def append(self, ch: str, style: str | None = None) -> None: ...

        class _PlainColumn:  # shim
            def __init__(self, *_, **__): ...

        Console = _PlainConsole
        Table = _PlainTable
        Panel = _PlainPanel
        Progress = _PlainProgress
        BarColumn = (
            TimeElapsedColumn
        ) = TaskProgressColumn = MofNCompleteColumn = ProgressColumn = object
        Column = _PlainColumn
        Text = _PlainText

        class _Box:
            SIMPLE_HEAVY = ROUNDED = MINIMAL_DOUBLE_HEAD = None

        box = _Box()

# ---------- optional project helpers ----------
try:
    from src.ensure_deps import ensure_numpy  # type: ignore
except Exception as exc:
    print(f"Warning: could not import ensure_numpy ({exc}).", file=sys.stderr)
    def ensure_numpy(version: str | None = None) -> ModuleType:  # type: ignore
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
except Exception as exc:
    print(f"Warning: helper utilities unavailable ({exc}). Using fallbacks.", file=sys.stderr)
    _helper_console = None

    def get_system_info() -> str:  # type: ignore
        python = f"Python {sys.version.split()[0]} ({sys.executable})"
        details = [python, f"Platform: {sys.platform}", f"CWD: {Path.cwd()}"]
        return "\n".join(details)

# ---------- logging ----------
logger = logging.getLogger("coolbox.setup")
logger.setLevel(logging.INFO)
if os.environ.get("COOLBOX_LOG_FILE"):
    fh = logging.FileHandler(os.environ["COOLBOX_LOG_FILE"])
    fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s"))
    logger.addHandler(fh)
else:
    logger.addHandler(logging.NullHandler())
logger.propagate = False

# ---------- configuration ----------
DEFAULT_RAINBOW = ("#e40303","#ff8c00","#ffed00","#008026","#004dff","#750787")

def _load_user_config() -> dict:
    for p in (Path.home() / ".coolboxrc", Path.cwd() / ".coolboxrc"):
        if p.exists():
            try: return json.loads(p.read_text())
            except Exception: logger.warning("Failed to read config %s", p)
    return {}

@dataclass
class Config:
    no_git: bool = os.environ.get("COOLBOX_NO_GIT") == "1"
    cli_no_anim: bool = os.environ.get("COOLBOX_FORCE_NO_ANIM") == "1"
    no_anim: bool = False
    border_enabled_default: bool = False   # default OFF
    alt_screen: bool = False
    rainbow_colors: Sequence[str] = field(default_factory=lambda: DEFAULT_RAINBOW)

CONFIG = Config()
USER_CFG = _load_user_config()
for key, value in USER_CFG.items():
    if hasattr(CONFIG, key): setattr(CONFIG, key, value)

IS_TTY = sys.stdout.isatty()
CONFIG.no_anim = (
    CONFIG.cli_no_anim
    or os.environ.get("COOLBOX_NO_ANIM") == "1"
    or os.environ.get("COOLBOX_CI") == "1"
    or os.environ.get("CI") == "1"
    or not IS_TTY
)
_border_env = os.environ.get("COOLBOX_BORDER")
CONFIG.border_enabled_default = False if _border_env is None else _border_env == "1"
CONFIG.alt_screen = os.environ.get("COOLBOX_ALT_SCREEN") == "1"
if os.environ.get("COOLBOX_COLORS"):
    CONFIG.rainbow_colors = tuple(os.environ["COOLBOX_COLORS"].split(","))
RAINBOW_COLORS: Sequence[str] = tuple(CONFIG.rainbow_colors)

# ---------- neon border fallback ----------
class _NoopBorder:
    def __init__(self, *_, **__): ...
    def __enter__(self): return self
    def __exit__(self, *_): return False

try:
    from src.utils.rainbow import NeonPulseBorder as _BorderImpl  # type: ignore
except Exception:
    _BorderImpl = _NoopBorder  # type: ignore

def NeonPulseBorder(**kwargs): return _BorderImpl(**kwargs)

# ---------- rainbow helpers ----------
class RainbowSpinnerColumn(ProgressColumn):
    """Spinner with Rich 13.x compatibility."""
    def __init__(self, frames: str = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏", colors: Sequence[str] | None = None):
        super().__init__()
        self.frames = frames
        self.colors = list(colors or RAINBOW_COLORS)
        self._index = 0
    def get_table_column(self, *_, **__):  # support old/new Rich
        return Column(no_wrap=True, justify="left", min_width=1, ratio=None)
    def render(self, task):  # type: ignore[override]
        char = self.frames[self._index % len(self.frames)]
        color = self.colors[self._index % len(self.colors)]
        self._index += 1
        return Text(char, style=color)

class SmartPercentColumn(ProgressColumn):
    """Always show percent. Works when total is known or missing."""
    def __init__(self, precision: int = 0):
        super().__init__()
        self.precision = max(0, int(precision))
    def get_table_column(self, *_, **__):
        # Enough width for "100%"
        return Column(no_wrap=True, justify="right", min_width=5, ratio=None)
    def render(self, task):  # type: ignore[override]
        try:
            total = task.total
            completed = task.completed or 0
            if total and total > 0:
                pct = max(0.0, min(100.0, 100.0 * float(completed) / float(total)))
                fmt = f"{{0:.{self.precision}f}}%"
                return Text(fmt.format(pct))
            # Unknown total: show spinner-like placeholder that still reads as progress
            # Use task.fields.get("phase_pct") if provided by caller.
            phase_pct = float(task.fields.get("phase_pct", 0.0)) if hasattr(task, "fields") else 0.0
            pct = max(0.0, min(99.0, phase_pct))
            fmt = f"{{0:.{self.precision}f}}%"
            return Text(fmt.format(pct))
        except Exception:
            return Text("--%")

def rainbow_text(msg: str, colors: Sequence[str] | None = None) -> TextType:
    colors = list(colors or RAINBOW_COLORS)
    t = Text()
    for i, ch in enumerate(msg): t.append(ch, style=colors[i % len(colors)])
    return t

# ---------- atomic console ----------
class LockingConsole:
    def __init__(self, base: ConsoleType | None = None):
        self._lock = threading.RLock()
        self._console = base or Console(soft_wrap=False, highlight=False)
    def __enter__(self):
        enter = getattr(self._console, "__enter__", None)
        if callable(enter): enter()
        return self
    def __exit__(self, exc_type, exc, tb):
        exit_ = getattr(self._console, "__exit__", None)
        if callable(exit_): return exit_(exc_type, exc, tb)
        return False
    def print(self, *args, **kwargs):
        with self._lock: self._console.print(*args, **kwargs)
    def log(self, *args, **kwargs):
        with self._lock: self._console.log(*args, **kwargs)
    def flush(self):
        with self._lock:
            try: self._console.file.flush()
            except Exception: ...
    @property
    def raw(self) -> ConsoleType: return self._console
    def __getattr__(self, name): return getattr(self._console, name)

# ---------- env + constants ----------
CONNECTIVITY_PROBE_TIMEOUT = 0.75
CONNECTIVITY_HOST_ENV = "COOLBOX_CONNECTIVITY_HOST"
CONNECTIVITY_DEFAULT_HOST = "pypi.org"


def _connectivity_host() -> str:
    return os.environ.get(CONNECTIVITY_HOST_ENV, CONNECTIVITY_DEFAULT_HOST)


def _detect_offline(timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection((CONNECTIVITY_DEFAULT_HOST, 443), timeout=timeout): return False
    except OSError:
        return True

_OFFLINE_FORCED = os.environ.get("COOLBOX_OFFLINE") == "1"
_OFFLINE_AUTO: bool | None = None

def set_offline(value: bool) -> None:
    global _OFFLINE_FORCED, _OFFLINE_AUTO
    _OFFLINE_FORCED = value
    _OFFLINE_AUTO = True if value else False
    if value:
        os.environ["COOLBOX_OFFLINE"] = "1"; BASE_ENV["COOLBOX_OFFLINE"] = "1"
    else:
        os.environ.pop("COOLBOX_OFFLINE", None); BASE_ENV.pop("COOLBOX_OFFLINE", None)


def _probe_connectivity(timeout: float = CONNECTIVITY_PROBE_TIMEOUT) -> ConnectivityProbe:
    host = _connectivity_host()
    start = time.perf_counter()
    try:
        with socket.create_connection((host, 443), timeout=timeout):
            latency = (time.perf_counter() - start) * 1000.0
            return ConnectivityProbe(True, True, host, latency)
    except OSError as exc:
        return ConnectivityProbe(True, False, host, None, error=str(exc))
    except Exception as exc:
        return ConnectivityProbe(True, None, host, None, error=str(exc))

def is_offline() -> bool:
    if _OFFLINE_FORCED: return True
    global _OFFLINE_AUTO
    if _OFFLINE_AUTO is None: _OFFLINE_AUTO = _detect_offline()
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

console = LockingConsole(_helper_console or Console(soft_wrap=False, highlight=False))

MIN_PYTHON: Tuple[int, int] = (3, 10)
if sys.version_info < MIN_PYTHON:
    raise RuntimeError(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ required")

def locate_root(start: Path) -> Path:
    p = Path(start).resolve()
    markers = {"requirements.txt", "pyproject.toml", ".git"}
    for parent in (p, *p.parents):
        if any((parent / m).exists() for m in markers): return parent
    return p

def get_root() -> Path:
    env = os.environ.get("COOLBOX_ROOT")
    if env: return Path(env).resolve()
    return locate_root(Path(__file__).resolve())

def get_venv_dir() -> Path:
    env = os.environ.get("COOLBOX_VENV")
    if env: return Path(env).resolve()
    return get_root() / ".venv"

ROOT_DIR = get_root()
REQUIREMENTS_FILE = ROOT_DIR / "requirements.txt"
DEV_PACKAGES: Sequence[str] = ("pip-tools>=7", "build>=1", "wheel>=0.43", "pytest>=8")

STAMP_STALE_AFTER_DAYS = 30.0
VENV_DISK_WARN_PERCENT = 5.0


def _default_cache_root() -> Path:
    env = os.environ.get("COOLBOX_CACHE")
    if env:
        return Path(env).expanduser().resolve()
    try:
        home = Path.home()
    except Exception:
        home = ROOT_DIR
    return (home / ".coolbox" / "cache").resolve()


CACHE_ROOT = _default_cache_root()


def _cache_dir(name: str) -> Path:
    path = CACHE_ROOT / name
    path.mkdir(parents=True, exist_ok=True)
    return path


WHEEL_CACHE_ROOT = _cache_dir("wheels")
STAMP_CACHE_ROOT = _cache_dir("stamps")

os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")

def log(msg: str) -> None:
    logger.info(msg)
    try: console.print(f"[dim]»[/] {msg}")
    except Exception: print(msg)

def show_setup_banner() -> None:
    banner = rainbow_text(f" CoolBox setup v{__version__} ")
    path = Text(str(ROOT_DIR), style="bold magenta")
    content = Text.assemble(banner, "\n", path)
    console.print(Panel(content, box=box.ROUNDED, expand=False))


def check_python_version(min_version: tuple[int, int] = (3, 8)) -> None:
    """Ensure the running Python meets the minimum required version.

    Parameters
    ----------
    min_version:
        A ``(major, minor)`` tuple representing the minimum supported
        Python version. Defaults to ``(3, 8)``.

    Raises
    ------
    RuntimeError
        If the current interpreter is older than ``min_version``.
    """

    if sys.version_info < min_version:
        required = ".".join(map(str, min_version))
        current = sys.version.split()[0]
        msg = f"Python {required}+ is required, but {current} is running"
        logger.error(msg)
        raise RuntimeError(msg)

# ---------- summary ----------
class RunSummary(RunSummaryPanelModel):
    """Rich-enabled summary that logs command diagnostics."""

    def __init__(self) -> None:
        super().__init__()
        self._logger = logging.getLogger("coolbox.setup.summary")

    def add_warning(self, msg: str) -> None:  # type: ignore[override]
        super().add_warning(msg)
        log(f"[yellow]WARN[/]: {msg}")

    def add_error(self, msg: str) -> None:  # type: ignore[override]
        super().add_error(msg)
        log(f"[red]ERROR[/]: {msg}")

    def begin_command(self, command: Sequence[str], *, cwd: str | None = None) -> CommandRecord:  # type: ignore[override]
        record = super().begin_command(command, cwd=cwd)
        self._logger.debug("Executing command: %s", " ".join(map(str, command)))
        return record

    def render(self) -> None:
        panel = self.as_panel()
        if hasattr(console, "print"):
            console.print(panel)
        else:
            print(panel)


SUMMARY = RunSummary()

def send_telemetry(summary: RunSummary) -> None:
    url = os.environ.get("COOLBOX_TELEMETRY_URL")
    if not url: return
    data = {
        "warnings": summary.warnings,
        "errors": summary.errors,
        "platform": sys.platform,
        "commands": [
            {
                "command": " ".join(map(str, record.command)),
                "exit_code": record.exit_code,
                "duration": record.duration,
                "hint": record.hint,
            }
            for record in summary.commands
        ],
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(data).encode("utf-8"), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=2)
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

def _hint_for_command(cmd: Sequence[str], exit_code: int | None, stderr: str | None) -> str | None:
    joined = " ".join(map(str, cmd)).lower()
    stderr_lower = (stderr or "").lower()
    if "pip" in joined:
        if exit_code:
            if "connection" in stderr_lower or "timeout" in stderr_lower:
                return "Check connectivity or pre-download wheels with 'pip download'."
        return "Pip will reuse cached wheels from ~/.coolbox/cache/wheels when available."
    if "git" in joined:
        return "Verify git remotes or rerun with --skip-update if network access is limited."
    if "build" in joined or "wheel" in joined:
        return "Ensure build deps are installed; cached wheels will be used when builds fail."
    return None


def _run(
    cmd: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict | None = None,
    timeout: float | None = None,
) -> subprocess.CompletedProcess[str]:
    cmd_list = [str(part) for part in cmd]
    record = SUMMARY.begin_command(cmd_list, cwd=str(cwd) if cwd else None)
    final_env = dict(BASE_ENV)
    if env:
        final_env.update(env)
    start = time.perf_counter()
    try:
        result = subprocess.run(
            cmd_list,
            cwd=cwd,
            env=final_env,
            timeout=timeout,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - start
        hint = _hint_for_command(cmd_list, None, str(exc))
        record.finalize(exit_code=None, stderr=str(exc), duration=duration, hint=hint)
        logger.error("Command timed out: %s", " ".join(cmd_list))
        raise RuntimeError(
            f"Command '{' '.join(cmd_list)}' timed out after {timeout}s"
        ) from exc

    duration = time.perf_counter() - start
    stderr_text = result.stderr or ""
    hint = _hint_for_command(cmd_list, result.returncode, stderr_text)
    record.finalize(
        exit_code=result.returncode,
        stderr=stderr_text,
        duration=duration,
        hint=hint,
    )
    logger.debug(
        "Command %s finished with exit %s in %.2fs",
        " ".join(cmd_list),
        result.returncode,
        duration,
    )
    if hint and result.returncode != 0:
        logger.info("Remediation hint: %s", hint)
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd_list,
            output=None,
            stderr=stderr_text,
        )
    return result

def _retry(
    cmd: Sequence[str],
    *,
    attempts: int = 3,
    delay: float = 0.8,
    cwd: Path | None = None,
    timeout: float | None = None,
    env: dict | None = None,
) -> None:
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            _run(cmd, cwd=cwd, timeout=timeout, env=env)
            return
        except Exception as e:
            last = e
            if i < attempts:
                time.sleep(delay * i)
    if last is not None:
        raise last


def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""): h.update(chunk)
    return h.hexdigest()


def _stamp_path() -> Path: return get_venv_dir() / ".req_hash"


def _global_stamp_path(req_hash: str) -> Path:
    return STAMP_CACHE_ROOT / f"{req_hash}.stamp"


def _hydrate_stamp_from_cache(req_hash: str, target: Path) -> None:
    cached = _global_stamp_path(req_hash)
    if cached.is_file():
        try:
            data = cached.read_text(encoding="utf-8")
            target.write_text(data, encoding="utf-8")
        except Exception:
            pass


def _store_stamp_to_cache(req_hash: str, serialized: str) -> None:
    cached = _global_stamp_path(req_hash)
    try:
        cached.write_text(serialized, encoding="utf-8")
    except Exception:
        pass


def _should_install(req: Path, upgrade: bool) -> bool:
    if upgrade:
        return True
    if not req.exists():
        return False
    stamp = _inspect_requirement_stamp(req)
    if stamp.recorded_hash is None:
        return True
    return stamp.changed


def _write_req_stamp(req: Path) -> None:
    req_hash = _file_hash(req)
    target = _stamp_path()
    payload = {
        "hash": req_hash,
        "python": _python_runtime_tag(),
        "pip": _current_pip_version(),
        "timestamp": time.time(),
    }
    serialized = json.dumps(payload, sort_keys=True)
    target.write_text(serialized, encoding="utf-8")
    _store_stamp_to_cache(req_hash, serialized)


def _wheel_cache_key() -> str:
    h = hashlib.sha256()
    for name in ("pyproject.toml", "setup.py"):
        path = ROOT_DIR / name
        if path.is_file():
            h.update(path.read_bytes())
    return h.hexdigest()


def _wheel_cache_dir() -> Path:
    path = WHEEL_CACHE_ROOT / _wheel_cache_key()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _store_wheel_artifacts(dist_dir: Path) -> None:
    if not dist_dir.exists():
        return
    cache_dir = _wheel_cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    for item in dist_dir.glob("*.whl"):
        try:
            shutil.copy2(item, cache_dir / item.name)
        except Exception:
            continue


def _restore_wheel_artifacts(dist_dir: Path) -> bool:
    cache_dir = _wheel_cache_dir()
    if not cache_dir.exists():
        return False
    dist_dir.mkdir(parents=True, exist_ok=True)
    restored = False
    for item in cache_dir.glob("*.whl"):
        try:
            shutil.copy2(item, dist_dir / item.name)
            restored = True
        except Exception:
            continue
    return restored


def _available_wheel_links() -> list[str]:
    links: list[str] = []
    if WHEEL_CACHE_ROOT.exists():
        for candidate in [WHEEL_CACHE_ROOT, *WHEEL_CACHE_ROOT.glob("*")]:
            if candidate.is_dir():
                links.append(str(candidate))
    return links


def _wheel_cache_stats() -> tuple[int, int]:
    if not WHEEL_CACHE_ROOT.exists():
        return (0, 0)
    total_files = 0
    total_bytes = 0
    try:
        for wheel in WHEEL_CACHE_ROOT.rglob("*.whl"):
            total_files += 1
            try:
                total_bytes += wheel.stat().st_size
            except OSError:
                continue
    except Exception:
        return (total_files, total_bytes)
    return (total_files, total_bytes)


WHEEL_CACHE_STALE_AFTER_DAYS = 30


def _wheel_cache_freshness() -> tuple[float | None, float | None]:
    if not WHEEL_CACHE_ROOT.exists():
        return (None, None)
    newest: float | None = None
    oldest: float | None = None
    try:
        for wheel in WHEEL_CACHE_ROOT.rglob("*.whl"):
            try:
                mtime = wheel.stat().st_mtime
            except OSError:
                continue
            if newest is None or mtime > newest:
                newest = mtime
            if oldest is None or mtime < oldest:
                oldest = mtime
    except Exception:
        return (None, None)
    return newest, oldest


def _parse_stamp_payload(data: str) -> dict:
    text = data.strip()
    if not text:
        return {}
    try:
        loaded = json.loads(text)
    except Exception:
        return {"hash": text}
    if isinstance(loaded, dict):
        return loaded
    return {"hash": text}


@dataclass(frozen=True)
class RequirementStampState:
    """Details about the current requirements stamp state."""

    stamp_path: Path
    stamp_exists: bool
    requirement_hash: str | None
    recorded_hash: str | None
    changed: bool
    recorded_python: str | None
    recorded_pip: str | None
    recorded_timestamp: float | None
    age_days: float | None


@dataclass(frozen=True)
class RequirementIssue:
    """Structured description of a requirement that needs attention."""

    requirement: str
    package: str
    installed: str | None
    specifier: str | None
    kind: Literal["missing", "mismatch"]


@dataclass(frozen=True)
class ConnectivityProbe:
    """Outcome of probing network connectivity for smart setup heuristics."""

    attempted: bool
    reachable: bool | None
    host: str
    latency_ms: float | None
    error: str | None = None


@dataclass(frozen=True)
class VenvDiagnostics:
    """Snapshot describing the current virtual environment state."""

    root: Path
    exists: bool
    python_path: Path
    python_exists: bool
    site_packages: tuple[Path, ...]
    missing_site_packages: tuple[Path, ...]
    writable: bool
    disk_total_bytes: int | None
    disk_free_bytes: int | None
    disk_percent_free: float | None


@dataclass(frozen=True)
class RequirementSourceAnalysis:
    """Summary of requirement entries and their source characteristics."""

    total: int
    network: tuple[str, ...]
    local: tuple[str, ...]
    missing_local: tuple[str, ...]
    editable: tuple[str, ...]
    nested: tuple[str, ...]
    missing_nested: tuple[str, ...]


@dataclass(frozen=True)
class RequirementPinningAnalysis:
    """Summary describing how requirements are pinned or left floating."""

    total: int
    pinned: tuple[str, ...]
    ranged: tuple[str, ...]
    unversioned: tuple[str, ...]
    wildcard: tuple[str, ...]
    markers: tuple[str, ...]
    extras: tuple[str, ...]
    constraints: tuple[str, ...]
    invalid: tuple[str, ...]


@dataclass(frozen=True)
class RequirementDuplicationAnalysis:
    """Summary of duplicate requirement entries and potential conflicts."""

    total: int
    duplicates: tuple[str, ...]
    marker_variants: tuple[str, ...]
    conflicting: tuple[str, ...]


@dataclass(frozen=True)
class RequirementHashingAnalysis:
    """Summary describing requirement hash coverage and related risks."""

    total: int
    hashed_total: int
    unhashed_total: int
    hashed: tuple[str, ...]
    unhashed: tuple[str, ...]
    hashed_unpinned: tuple[str, ...]
    insecure_urls: tuple[str, ...]


@dataclass(frozen=True)
class RequirementMarkerAnalysis:
    """Summary describing requirement environment markers and compatibility."""

    total: int
    with_markers: int
    satisfied: tuple[str, ...]
    unsatisfied: tuple[str, ...]
    python_mismatch: tuple[str, ...]
    platform_mismatch: tuple[str, ...]
    parsing_errors: tuple[str, ...]


@dataclass(frozen=True)
class RequirementIndexAnalysis:
    """Summary describing index, link, and host directives in requirements files."""

    primary_index: str | None
    extra_indexes: tuple[str, ...]
    find_links: tuple[str, ...]
    trusted_hosts: tuple[str, ...]
    no_index: bool
    insecure_indexes: tuple[str, ...]
    insecure_links: tuple[str, ...]
    network_indexes: tuple[str, ...]
    network_find_links: tuple[str, ...]


@dataclass(frozen=True)
class RequirementOptionAnalysis:
    """Summary of global pip options declared inside requirement files."""

    require_hashes: bool
    prefer_binary: bool
    pre: bool
    no_build_isolation: bool
    no_deps: bool
    no_binary: tuple[str, ...]
    only_binary: tuple[str, ...]
    use_features: tuple[str, ...]
    other_options: tuple[str, ...]


@dataclass(frozen=True)
class SmartInstallContext:
    """Environment snapshot used to build smart install plans."""

    requirements_path: Path | None
    requirements_exist: bool
    stamp: RequirementStampState
    missing_requirements: tuple[str, ...]
    offline: bool
    wheel_links: tuple[str, ...]
    upgrade_requested: bool
    dev_requested: bool
    dev_requirements_path: Path
    dev_requirements_exist: bool
    should_install: bool
    reasons: tuple[str, ...]
    missing_packages: tuple[str, ...]
    conflicting_packages: tuple[str, ...]
    missing_details: tuple[RequirementIssue, ...]
    partial_reinstall: tuple[str, ...]
    analysis_warnings: tuple[str, ...]
    pip_bootstrap_recommended: bool
    pip_bootstrap_reason: str | None
    python_version: str
    pip_version: str | None
    stamp_age_days: float | None
    wheel_cache_files: int
    wheel_cache_bytes: int
    connectivity: ConnectivityProbe
    wheel_cache_newest: float | None
    wheel_cache_oldest: float | None
    venv: VenvDiagnostics
    requirement_sources: RequirementSourceAnalysis
    requirement_pinning: RequirementPinningAnalysis
    requirement_duplicates: RequirementDuplicationAnalysis
    requirement_hashing: RequirementHashingAnalysis
    requirement_markers: RequirementMarkerAnalysis
    requirement_indexes: RequirementIndexAnalysis
    requirement_options: RequirementOptionAnalysis


@dataclass(frozen=True)
class SmartPlanStep:
    """Single pip invocation planned by the smart planner."""

    title: str
    pip_args: tuple[str, ...]
    upgrade_pip: bool
    reason: str | None = None
    optional: bool = False

    def legacy(self) -> tuple[str, list[str], bool]:
        return (self.title, list(self.pip_args), self.upgrade_pip)


@dataclass(frozen=True)
class SmartInstallPlan:
    """Smart plan containing pip steps and contextual insights."""

    context: SmartInstallContext
    steps: tuple[SmartPlanStep, ...]
    insights: tuple[str, ...] = ()

    def legacy(self) -> list[tuple[str, list[str], bool]]:
        return [step.legacy() for step in self.steps]


def _inspect_requirement_stamp(req_path: Path | None) -> RequirementStampState:
    stamp_path = _stamp_path()
    requirement_hash: str | None = None
    if req_path and req_path.exists():
        requirement_hash = _file_hash(req_path)
        if not stamp_path.exists():
            _hydrate_stamp_from_cache(requirement_hash, stamp_path)
    recorded_hash: str | None = None
    recorded_python: str | None = None
    recorded_pip: str | None = None
    recorded_timestamp: float | None = None
    changed = bool(requirement_hash)
    now = time.time()
    if stamp_path.exists():
        try:
            payload = _parse_stamp_payload(stamp_path.read_text(encoding="utf-8"))
            recorded_hash = payload.get("hash") or payload.get("requirement_hash")
            recorded_python = payload.get("python") or payload.get("python_version")
            recorded_pip = payload.get("pip") or payload.get("pip_version")
            timestamp_raw = payload.get("timestamp")
            if isinstance(timestamp_raw, (int, float)):
                recorded_timestamp = float(timestamp_raw)
            elif isinstance(timestamp_raw, str):
                try:
                    recorded_timestamp = float(timestamp_raw)
                except ValueError:
                    recorded_timestamp = None
            else:
                recorded_timestamp = None
            if requirement_hash is not None:
                changed = recorded_hash != requirement_hash if recorded_hash else True
            else:
                changed = False
        except Exception:
            recorded_hash = None
            recorded_python = None
            recorded_pip = None
            recorded_timestamp = None
            changed = bool(requirement_hash)
    age_days: float | None = None
    if recorded_timestamp is not None:
        try:
            delta = max(now - recorded_timestamp, 0.0)
            age_days = delta / 86_400
        except Exception:
            age_days = None
    return RequirementStampState(
        stamp_path=stamp_path,
        stamp_exists=stamp_path.exists(),
        requirement_hash=requirement_hash,
        recorded_hash=recorded_hash,
        changed=changed,
        recorded_python=recorded_python,
        recorded_pip=recorded_pip,
        recorded_timestamp=recorded_timestamp,
        age_days=age_days,
    )


def _metadata_paths_for_analysis() -> list[Path]:
    try:
        venv_dir = Path(get_venv_dir())
    except Exception:
        return []
    try:
        return setup_stages._candidate_site_packages(venv_dir)
    except Exception:
        return []


def _gather_venv_diagnostics() -> VenvDiagnostics:
    try:
        venv_root = Path(get_venv_dir()).resolve()
    except Exception:
        venv_root = (ROOT_DIR / ".venv").resolve()

    exists = venv_root.exists()
    python_path = Path(_venv_python()).resolve()
    python_exists = python_path.exists()

    try:
        site_candidates = tuple(
            Path(p).resolve() for p in setup_stages._candidate_site_packages(venv_root)
        )
    except Exception:
        site_candidates = ()

    missing_site = tuple(path for path in site_candidates if not path.exists())

    if exists:
        disk_target = venv_root
    else:
        disk_target = venv_root.parent if venv_root.parent.exists() else ROOT_DIR

    disk_total: int | None = None
    disk_free: int | None = None
    disk_percent: float | None = None
    try:
        usage = shutil.disk_usage(disk_target)
        disk_total = int(getattr(usage, "total", usage[0]))
        disk_free = int(getattr(usage, "free", usage[2]))
        if disk_total:
            disk_percent = (disk_free / disk_total) * 100.0
    except Exception:
        disk_total = disk_total or None
        disk_free = disk_free or None
        disk_percent = None

    writable_target = venv_root if exists else disk_target
    try:
        writable = os.access(writable_target, os.W_OK)
    except Exception:
        writable = True

    return VenvDiagnostics(
        root=venv_root,
        exists=exists,
        python_path=python_path,
        python_exists=python_exists,
        site_packages=site_candidates,
        missing_site_packages=missing_site,
        writable=writable,
        disk_total_bytes=disk_total,
        disk_free_bytes=disk_free,
        disk_percent_free=disk_percent,
    )


def _python_runtime_tag() -> str:
    return platform.python_version()


def _current_pip_version() -> str | None:
    try:
        import pip  # type: ignore
    except Exception:
        return None
    try:
        return pip.__version__  # type: ignore[attr-defined]
    except Exception:
        return None


def _evaluate_pip_status(version: str | None) -> tuple[bool, str | None]:
    if version is None:
        return True, "pip module unavailable"
    try:
        parsed = Version(version)
    except InvalidVersion:
        return True, f"pip version '{version}' is invalid"
    recommended = Version("23.0")
    if parsed < recommended:
        return True, f"pip {version} below recommended {recommended}"
    return False, None


def _preview_missing(missing: Sequence[str], limit: int = 3) -> str:
    if not missing:
        return ""
    sample = list(missing[:limit])
    text = ", ".join(sample)
    if len(missing) > limit:
        text += f" (+{len(missing) - limit} more)"
    return text


def _describe_connectivity(probe: ConnectivityProbe) -> str:
    if not probe.attempted:
        reason = probe.error or "probe skipped"
        return f"Network probe: skipped ({reason})"
    if probe.reachable:
        if probe.latency_ms is not None:
            return f"Network probe: reachable {probe.host} in {probe.latency_ms:.0f} ms"
        return f"Network probe: reachable {probe.host}"
    if probe.reachable is False:
        detail = probe.error or "unknown error"
        return f"Network probe: unreachable {probe.host} ({detail})"
    detail = probe.error or "unknown"
    return f"Network probe: inconclusive for {probe.host} ({detail})"


def _format_timespan(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    if seconds < 1:
        return "0s"
    thresholds = [
        (86_400, "d"),
        (3_600, "h"),
        (60, "m"),
    ]
    for divider, suffix in thresholds:
        if seconds >= divider:
            return f"{seconds / divider:.1f}{suffix}"
    return f"{int(seconds)}s"


def _format_bytes(size: int) -> str:
    if size <= 0:
        return "0 B"
    suffixes = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for suffix in suffixes:
        if value < 1024 or suffix == suffixes[-1]:
            return f"{value:.1f} {suffix}"
        value /= 1024
    return f"{value:.1f} PB"


def _analyze_requirement_issues(
    req_path: Path,
    missing: Sequence[str],
    *,
    metadata_paths: Sequence[Path],
) -> tuple[list[RequirementIssue], list[str], list[str], list[str]]:
    if not req_path.exists() or not missing:
        return ([], [], [], [])

    missing_set = set(missing)
    installed = setup_stages._installed_packages(metadata_paths)
    environment = {key: str(value) for key, value in default_environment().items()}

    details: list[RequirementIssue] = []
    missing_packages: list[str] = []
    mismatched_packages: list[str] = []
    warnings: list[str] = []

    for raw in setup_stages._parse_requirements(req_path):
        if raw not in missing_set:
            continue
        try:
            requirement = Requirement(raw)
        except Exception as exc:
            warnings.append(f"Failed to parse requirement '{raw}': {exc}")
            continue
        if requirement.marker and not requirement.marker.evaluate(environment):
            # Requirement gated off by environment markers; ignore.
            continue
        name = requirement.name
        canonical = canonicalize_name(name)
        installed_version = installed.get(canonical)
        spec_text = str(requirement.specifier) or None
        if installed_version is None:
            missing_packages.append(name)
            kind: Literal["missing", "mismatch"] = "missing"
        else:
            mismatch_text = spec_text or "unspecified"
            mismatched_packages.append(f"{name} ({installed_version}→{mismatch_text})")
            kind = "mismatch"
        details.append(
            RequirementIssue(
                requirement=raw,
                package=name,
                installed=installed_version,
                specifier=spec_text,
                kind=kind,
            )
        )

    return details, missing_packages, mismatched_packages, warnings


def _analyze_requirement_sources(req_path: Path | None) -> RequirementSourceAnalysis:
    if not req_path or not req_path.exists():
        return RequirementSourceAnalysis(
            total=0,
            network=(),
            local=(),
            missing_local=(),
            editable=(),
            nested=(),
            missing_nested=(),
        )

    try:
        lines = req_path.read_text(encoding="utf-8").splitlines()
    except Exception:
        lines = []

    base_dir = req_path.parent
    network: list[str] = []
    local: list[str] = []
    missing_local: list[str] = []
    editable: list[str] = []
    nested: list[str] = []
    missing_nested: list[str] = []
    total = 0

    def _normalize_entry(entry: str) -> str:
        comment_split = entry.split(" #", 1)[0].strip()
        return comment_split

    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if stripped.startswith(('-r ', '--requirement ')):
            parts = stripped.split(None, 1)
            target = parts[1].strip() if len(parts) == 2 else ""
            if target:
                normalized_target = _normalize_entry(target)
                nested.append(normalized_target)
                lowered_target = normalized_target.lower()
                if lowered_target.startswith("git+") or "://" in lowered_target:
                    network.append(normalized_target)
                else:
                    candidate = (base_dir / normalized_target).resolve()
                    if not candidate.exists():
                        missing_nested.append(normalized_target)
            continue

        if stripped.startswith(('-c ', '--constraint ')):
            continue

        entry = stripped
        editable_entry = False
        if entry.startswith("-e "):
            editable_entry = True
            entry = entry[3:].strip()
            editable.append(_normalize_entry(stripped))

        normalized = _normalize_entry(entry)
        if not normalized:
            continue

        total += 1
        source = normalized
        if "@" in normalized:
            marker_parts = normalized.split("@", 1)
            candidate = marker_parts[1].strip()
            if candidate:
                source = candidate
        lowered_source = source.lower()

        if lowered_source.startswith("git+") or "://" in lowered_source:
            network.append(_normalize_entry(stripped) if editable_entry else normalized)
            continue

        local_detected = False
        path_target: Path | None = None

        if "file://" in lowered_source:
            try:
                url = urllib.parse.urlparse(source)
                path_target = Path(url.path)
            except Exception:
                path_target = None
            local_detected = True
        elif normalized.startswith(("./", "../", "/")):
            local_detected = True
            if normalized.startswith("/"):
                path_target = Path(normalized)
            else:
                path_target = (base_dir / normalized).resolve()
        elif any(
            normalized.endswith(suffix)
            for suffix in (".whl", ".zip", ".tar.gz", ".tgz")
        ):
            local_detected = True
            path_target = (base_dir / normalized).resolve()
        elif editable_entry:
            local_detected = True
            path_target = (base_dir / normalized).resolve()

        if local_detected:
            normalized_entry = _normalize_entry(stripped) if editable_entry else normalized
            local.append(normalized_entry)
            if path_target is not None and not path_target.exists():
                missing_local.append(normalized_entry)
            continue

    return RequirementSourceAnalysis(
        total=total,
        network=tuple(dict.fromkeys(network)),
        local=tuple(dict.fromkeys(local)),
        missing_local=tuple(dict.fromkeys(missing_local)),
        editable=tuple(dict.fromkeys(editable)),
        nested=tuple(dict.fromkeys(nested)),
        missing_nested=tuple(dict.fromkeys(missing_nested)),
    )


def _analyze_requirement_pinning(req_path: Path | None) -> RequirementPinningAnalysis:
    if not req_path or not req_path.exists():
        return RequirementPinningAnalysis(
            total=0,
            pinned=(),
            ranged=(),
            unversioned=(),
            wildcard=(),
            markers=(),
            extras=(),
            constraints=(),
            invalid=(),
        )

    pinned: list[str] = []
    ranged: list[str] = []
    unversioned: list[str] = []
    wildcard: list[str] = []
    markers: list[str] = []
    extras: list[str] = []
    constraints: list[str] = []
    invalid: list[str] = []

    try:
        text = req_path.read_text(encoding="utf-8")
    except OSError:
        return RequirementPinningAnalysis(
            total=0,
            pinned=(),
            ranged=(),
            unversioned=(),
            wildcard=(),
            markers=(),
            extras=(),
            constraints=(),
            invalid=("<unreadable requirements file>",),
        )

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        constraint_value: str | None = None
        if line.startswith(('-c', '--constraint')):
            if line.startswith('-c'):
                remainder = line[2:]
            else:
                remainder = line[len('--constraint') :]
            remainder = remainder.lstrip(' =')
            if remainder:
                constraint_value = remainder
            else:
                parts = raw_line.split(None, 1)
                if len(parts) == 2:
                    candidate = parts[1].strip()
                    if candidate:
                        constraint_value = candidate
            if constraint_value:
                constraints.append(constraint_value)
            continue
        if line.startswith(('-r ', '--requirement ')):
            continue
        if line.startswith("--"):
            continue
        if line.startswith("-"):
            continue

        try:
            requirement = Requirement(line)
        except Exception:
            invalid.append(line)
            continue

        if requirement.marker:
            markers.append(line)
        if requirement.extras:
            extras.append(line)

        specifier = list(requirement.specifier)
        if not specifier:
            unversioned.append(line)
            continue

        operators = {spec.operator for spec in specifier}
        versions = [spec.version or "" for spec in specifier]
        if operators <= {"==", "==="}:
            if any("*" in version for version in versions):
                wildcard.append(line)
            else:
                pinned.append(line)
        else:
            ranged.append(line)

    total = len(pinned) + len(ranged) + len(unversioned) + len(wildcard)
    return RequirementPinningAnalysis(
        total=total,
        pinned=tuple(pinned),
        ranged=tuple(ranged),
        unversioned=tuple(unversioned),
        wildcard=tuple(wildcard),
        markers=tuple(markers),
        extras=tuple(extras),
        constraints=tuple(constraints),
        invalid=tuple(invalid),
    )


def _analyze_requirement_duplicates(
    req_path: Path | None,
) -> RequirementDuplicationAnalysis:
    if not req_path or not req_path.exists():
        return RequirementDuplicationAnalysis(
            total=0,
            duplicates=(),
            marker_variants=(),
            conflicting=(),
        )

    try:
        text = req_path.read_text(encoding="utf-8")
    except OSError:
        return RequirementDuplicationAnalysis(
            total=0,
            duplicates=(),
            marker_variants=(),
            conflicting=("<unreadable requirements file>",),
        )

    groups: dict[str, list[tuple[Requirement, str]]] = {}
    total = 0

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        normalized = stripped.split(" #", 1)[0].strip()
        if not normalized:
            continue
        if normalized.startswith(('-r ', '--requirement ')):
            continue
        if normalized.startswith(('-c ', '--constraint ')):
            continue
        if normalized.startswith("--"):
            continue

        if normalized.startswith("-e "):
            normalized = normalized[3:].strip()
            if not normalized:
                continue

        if normalized.startswith("-"):
            continue

        try:
            requirement = Requirement(normalized)
        except Exception:
            continue

        total += 1
        canonical = canonicalize_name(requirement.name)
        groups.setdefault(canonical, []).append((requirement, normalized))

    duplicates: list[str] = []
    marker_variants: list[str] = []
    conflicting: list[str] = []

    for items in groups.values():
        if len(items) <= 1:
            continue

        names = sorted({req.name for req, _ in items}, key=str.lower)
        display_name = names[0]
        summary = f"{display_name} ({len(items)} entries)"
        markers = [str(req.marker) for req, _ in items if req.marker is not None]
        if markers:
            marker_variants.append(summary)
        if len(markers) != len(items):
            duplicates.append(summary)

        pinned_versions = {
            spec.version
            for req, _ in items
            for spec in req.specifier
            if spec.operator in ("==", "===") and spec.version
        }
        if len(pinned_versions) > 1:
            conflicting.append(
                f"{display_name}: " + " | ".join(entry for _, entry in items)
            )

    return RequirementDuplicationAnalysis(
        total=total,
        duplicates=tuple(dict.fromkeys(duplicates)),
        marker_variants=tuple(dict.fromkeys(marker_variants)),
        conflicting=tuple(dict.fromkeys(conflicting)),
    )


def _is_strictly_pinned(requirement: Requirement) -> bool:
    specifiers = list(requirement.specifier)
    if not specifiers:
        return False
    for spec in specifiers:
        if spec.operator not in ("==", "==="):
            return False
        version = spec.version or ""
        if "*" in version:
            return False
    return True


def _analyze_requirement_hashing(
    req_path: Path | None,
) -> RequirementHashingAnalysis:
    if not req_path or not req_path.exists():
        return RequirementHashingAnalysis(
            total=0,
            hashed_total=0,
            unhashed_total=0,
            hashed=(),
            unhashed=(),
            hashed_unpinned=(),
            insecure_urls=(),
        )

    try:
        text = req_path.read_text(encoding="utf-8")
    except OSError:
        return RequirementHashingAnalysis(
            total=0,
            hashed_total=0,
            unhashed_total=0,
            hashed=(),
            unhashed=("<unreadable requirements file>",),
            hashed_unpinned=(),
            insecure_urls=(),
        )

    hash_option_re = re.compile(r"\s+--hash(?:=|\s)\S+")

    hashed_entries: list[str] = []
    unhashed_entries: list[str] = []
    hashed_unpinned: list[str] = []
    insecure_urls: list[str] = []
    hashed_total = 0
    unhashed_total = 0

    current_line: str | None = None
    current_has_hash = False
    continuation = False

    def flush_current() -> None:
        nonlocal current_line, current_has_hash, hashed_total, unhashed_total, continuation
        if current_line is None:
            continuation = False
            current_has_hash = False
            return
        entry = current_line.strip()
        current_line = None
        continuation = False
        has_hash = current_has_hash
        current_has_hash = False
        if not entry:
            return
        sanitized = hash_option_re.sub("", entry).strip()
        if not sanitized:
            sanitized = entry
        try:
            parsed = Requirement(sanitized)
        except Exception:
            parsed = None
        if has_hash:
            hashed_total += 1
            hashed_entries.append(sanitized)
            if parsed is None or not _is_strictly_pinned(parsed):
                hashed_unpinned.append(sanitized)
        else:
            unhashed_total += 1
            unhashed_entries.append(sanitized)
        if parsed is not None:
            url = parsed.url or ""
            lowered = url.lower()
            if lowered.startswith("http://") or lowered.startswith("git+http://"):
                insecure_urls.append(sanitized)
            elif lowered.startswith("git+") and "+http://" in lowered:
                insecure_urls.append(sanitized)
        else:
            lowered_line = sanitized.lower()
            if "http://" in lowered_line or lowered_line.startswith("git+http://"):
                insecure_urls.append(sanitized)

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            flush_current()
            continue
        if stripped.startswith("#"):
            continue

        normalized = stripped.split(" #", 1)[0].strip()
        if not normalized:
            continue

        if normalized.startswith("--hash"):
            if current_line is not None:
                current_has_hash = True
                continuation = raw_line.rstrip().endswith("\\")
                if not continuation:
                    flush_current()
            continue

        line_continues = raw_line.rstrip().endswith("\\")
        if normalized.endswith("\\"):
            normalized = normalized[:-1].rstrip()

        if normalized.startswith(("-r ", "--requirement ")):
            flush_current()
            continue
        if normalized.startswith(("-c ", "--constraint ")):
            flush_current()
            continue
        if normalized.startswith("--"):
            flush_current()
            continue

        if normalized.startswith("-e "):
            normalized = normalized[3:].strip()
        elif normalized.startswith("--editable"):
            parts = normalized.split(None, 1)
            normalized = parts[1].strip() if len(parts) == 2 else ""
        if not normalized:
            flush_current()
            continue
        if normalized.startswith("-"):
            flush_current()
            continue

        if current_line is not None:
            flush_current()

        current_line = normalized
        current_has_hash = "--hash" in normalized
        continuation = line_continues
        if not continuation and not current_has_hash:
            flush_current()
        elif not continuation and current_has_hash:
            flush_current()

    flush_current()

    total = hashed_total + unhashed_total
    return RequirementHashingAnalysis(
        total=total,
        hashed_total=hashed_total,
        unhashed_total=unhashed_total,
        hashed=tuple(dict.fromkeys(hashed_entries)),
        unhashed=tuple(dict.fromkeys(unhashed_entries)),
        hashed_unpinned=tuple(dict.fromkeys(hashed_unpinned)),
        insecure_urls=tuple(dict.fromkeys(insecure_urls)),
    )


def _analyze_requirement_markers(
    req_path: Path | None,
) -> RequirementMarkerAnalysis:
    if not req_path or not req_path.exists():
        return RequirementMarkerAnalysis(
            total=0,
            with_markers=0,
            satisfied=(),
            unsatisfied=(),
            python_mismatch=(),
            platform_mismatch=(),
            parsing_errors=(),
        )

    try:
        text = req_path.read_text(encoding="utf-8")
    except OSError:
        return RequirementMarkerAnalysis(
            total=0,
            with_markers=0,
            satisfied=(),
            unsatisfied=(),
            python_mismatch=(),
            platform_mismatch=(),
            parsing_errors=("<unreadable requirements file>",),
        )

    environment: dict[str, str] = {
        key: str(value) for key, value in default_environment().items()
    }
    total = 0
    with_markers = 0
    satisfied: list[str] = []
    unsatisfied: list[str] = []
    python_mismatch: list[str] = []
    platform_mismatch: list[str] = []
    errors: list[str] = []

    hash_option_re = re.compile(r"\s+--hash(?:=|\s)\S+")

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        normalized = stripped.split(" #", 1)[0].strip()
        if not normalized:
            continue
        if normalized.startswith(("-r ", "--requirement ")):
            continue
        if normalized.startswith(("-c ", "--constraint ")):
            continue
        if normalized.startswith("--"):
            continue

        editable = False
        if normalized.startswith("-e "):
            editable = True
            normalized = normalized[3:].strip()
            if not normalized:
                continue

        if normalized.startswith("-") and not editable:
            continue

        sanitized = hash_option_re.sub("", normalized).strip()
        if sanitized.endswith("\\"):
            sanitized = sanitized.rstrip("\\").rstrip()

        try:
            requirement = Requirement(sanitized)
        except Exception as exc:
            errors.append(f"{normalized} ({exc})")
            continue

        total += 1
        marker = requirement.marker
        if marker is None:
            continue

        with_markers += 1
        display = sanitized
        try:
            result = marker.evaluate(environment)
        except Exception as exc:
            errors.append(f"{display} ({exc})")
            continue

        if result:
            satisfied.append(display)
        else:
            unsatisfied.append(display)
            marker_text = str(marker).lower()
            if any(
                keyword in marker_text
                for keyword in ("python_version", "python_full_version")
            ):
                python_mismatch.append(display)
            if any(
                keyword in marker_text
                for keyword in (
                    "sys_platform",
                    "platform_system",
                    "platform_machine",
                    "platform_release",
                    "platform_version",
                    "platform_python_implementation",
                    "os_name",
                )
            ):
                platform_mismatch.append(display)

    return RequirementMarkerAnalysis(
        total=total,
        with_markers=with_markers,
        satisfied=tuple(dict.fromkeys(satisfied)),
        unsatisfied=tuple(dict.fromkeys(unsatisfied)),
        python_mismatch=tuple(dict.fromkeys(python_mismatch)),
        platform_mismatch=tuple(dict.fromkeys(platform_mismatch)),
        parsing_errors=tuple(dict.fromkeys(errors)),
    )


def _looks_like_windows_path(value: str) -> bool:
    return bool(re.match(r"^[a-zA-Z]:[\\/]|^\\\\", value))


def _extract_option_argument(
    text: str, *, long_option: str, short_option: str | None = None
) -> str | None:
    if text.startswith(long_option):
        remainder = text[len(long_option) :]
    elif short_option and text.startswith(short_option):
        remainder = text[len(short_option) :]
    else:
        return None
    remainder = remainder.lstrip()
    if remainder.startswith("="):
        remainder = remainder[1:].lstrip()
    if not remainder:
        return None
    return remainder.split()[0]


def _requires_network_source(url: str) -> bool:
    candidate = url.strip()
    if not candidate:
        return False
    lowered = candidate.lower()
    if lowered.startswith("file://"):
        return False
    if _looks_like_windows_path(candidate):
        return False
    network_prefixes = (
        "http://",
        "https://",
        "git+http://",
        "git+https://",
        "git+ssh://",
        "git+git://",
        "ssh://",
        "git://",
        "ftp://",
        "ftps://",
        "sftp://",
        "s3://",
    )
    if lowered.startswith(network_prefixes):
        return True
    parsed = urllib.parse.urlparse(candidate)
    scheme = parsed.scheme.lower()
    if not scheme:
        return False
    if scheme == "file":
        return False
    if len(scheme) == 1 and _looks_like_windows_path(candidate):
        return False
    return True


def _is_insecure_url(url: str) -> bool:
    candidate = url.strip()
    if not candidate:
        return False
    lowered = candidate.lower()
    if lowered.startswith("http://") or lowered.startswith("git+http://"):
        return True
    parsed = urllib.parse.urlparse(candidate)
    scheme = parsed.scheme.lower()
    if scheme == "http":
        return True
    if scheme.startswith("git+"):
        _, _, remainder = scheme.partition("+")
        return remainder == "http"
    return False


def _analyze_requirement_indexes(
    req_path: Path | None,
) -> RequirementIndexAnalysis:
    if not req_path or not req_path.exists():
        return RequirementIndexAnalysis(
            primary_index=None,
            extra_indexes=(),
            find_links=(),
            trusted_hosts=(),
            no_index=False,
            insecure_indexes=(),
            insecure_links=(),
            network_indexes=(),
            network_find_links=(),
        )

    try:
        text = req_path.read_text(encoding="utf-8")
    except OSError:
        return RequirementIndexAnalysis(
            primary_index=None,
            extra_indexes=(),
            find_links=(),
            trusted_hosts=(),
            no_index=False,
            insecure_indexes=(),
            insecure_links=(),
            network_indexes=(),
            network_find_links=(),
        )

    primary_index: str | None = None
    extra_indexes: list[str] = []
    find_links: list[str] = []
    trusted_hosts: list[str] = []
    insecure_indexes: list[str] = []
    insecure_links: list[str] = []
    network_indexes: list[str] = []
    network_find_links: list[str] = []
    no_index = False

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        sanitized = stripped.split(" #", 1)[0].strip()
        if not sanitized:
            continue
        lowered = sanitized.lower()
        if lowered.startswith("--no-index"):
            no_index = True
            continue

        value = _extract_option_argument(
            sanitized, long_option="--index-url", short_option="-i"
        )
        if value is not None:
            normalized = value.strip()
            if not normalized:
                continue
            if primary_index is None:
                primary_index = normalized
            else:
                extra_indexes.append(normalized)
            if _requires_network_source(normalized):
                network_indexes.append(normalized)
            if _is_insecure_url(normalized):
                insecure_indexes.append(normalized)
            continue

        value = _extract_option_argument(
            sanitized, long_option="--extra-index-url", short_option=None
        )
        if value is not None:
            normalized = value.strip()
            if not normalized:
                continue
            extra_indexes.append(normalized)
            if _requires_network_source(normalized):
                network_indexes.append(normalized)
            if _is_insecure_url(normalized):
                insecure_indexes.append(normalized)
            continue

        value = _extract_option_argument(
            sanitized, long_option="--find-links", short_option="-f"
        )
        if value is not None:
            normalized = value.strip()
            if not normalized:
                continue
            find_links.append(normalized)
            if _requires_network_source(normalized):
                network_find_links.append(normalized)
            if _is_insecure_url(normalized):
                insecure_links.append(normalized)
            continue

        value = _extract_option_argument(
            sanitized, long_option="--trusted-host", short_option=None
        )
        if value is not None:
            normalized = value.strip()
            if normalized:
                trusted_hosts.append(normalized)
            continue

    return RequirementIndexAnalysis(
        primary_index=primary_index,
        extra_indexes=tuple(dict.fromkeys(extra_indexes)),
        find_links=tuple(dict.fromkeys(find_links)),
        trusted_hosts=tuple(dict.fromkeys(trusted_hosts)),
        no_index=no_index,
        insecure_indexes=tuple(dict.fromkeys(insecure_indexes)),
        insecure_links=tuple(dict.fromkeys(insecure_links)),
        network_indexes=tuple(dict.fromkeys(network_indexes)),
        network_find_links=tuple(dict.fromkeys(network_find_links)),
    )


_OPTION_VALUE_FLAGS = {
    "--no-binary",
    "--only-binary",
    "--use-feature",
}

_IGNORED_OPTION_TOKENS = {
    "-r",
    "--requirement",
    "-c",
    "--constraint",
    "-f",
    "--find-links",
    "-i",
    "--index-url",
    "--extra-index-url",
    "--trusted-host",
    "--no-index",
    "--hash",
}


def _normalize_option_values(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    entries: list[str] = []
    for raw in value.split(","):
        candidate = raw.strip()
        if candidate:
            entries.append(candidate)
    return tuple(dict.fromkeys(entries))


def _analyze_requirement_options(
    req_path: Path | None,
) -> RequirementOptionAnalysis:
    if not req_path or not req_path.exists():
        return RequirementOptionAnalysis(
            require_hashes=False,
            prefer_binary=False,
            pre=False,
            no_build_isolation=False,
            no_deps=False,
            no_binary=(),
            only_binary=(),
            use_features=(),
            other_options=(),
        )

    try:
        text = req_path.read_text(encoding="utf-8")
    except OSError:
        return RequirementOptionAnalysis(
            require_hashes=False,
            prefer_binary=False,
            pre=False,
            no_build_isolation=False,
            no_deps=False,
            no_binary=(),
            only_binary=(),
            use_features=(),
            other_options=(),
        )

    require_hashes = False
    prefer_binary = False
    pre = False
    no_build_isolation = False
    no_deps = False
    no_binary: list[str] = []
    only_binary: list[str] = []
    use_features: list[str] = []
    other_options: list[str] = []

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        sanitized = stripped.split(" #", 1)[0].strip()
        if not sanitized:
            continue
        try:
            tokens = shlex.split(sanitized, comments=False, posix=True)
        except ValueError:
            tokens = sanitized.split()

        idx = 0
        while idx < len(tokens):
            token = tokens[idx]
            lowered = token.lower()
            consumed_next = False
            value: str | None = None
            if lowered.startswith("--"):
                name, eq, inline_value = token.partition("=")
                normalized = name.lower()
                if eq:
                    value = inline_value
                elif normalized in _OPTION_VALUE_FLAGS:
                    next_index = idx + 1
                    if next_index < len(tokens):
                        candidate = tokens[next_index]
                        if candidate != "-" and not candidate.startswith("--"):
                            value = candidate
                            consumed_next = True

                if normalized == "--require-hashes":
                    require_hashes = True
                elif normalized == "--prefer-binary":
                    prefer_binary = True
                elif normalized == "--pre":
                    pre = True
                elif normalized == "--no-build-isolation":
                    no_build_isolation = True
                elif normalized == "--no-deps":
                    no_deps = True
                elif normalized == "--no-binary":
                    no_binary.extend(_normalize_option_values(value))
                elif normalized == "--only-binary":
                    only_binary.extend(_normalize_option_values(value))
                elif normalized == "--use-feature":
                    use_features.extend(_normalize_option_values(value))
                elif normalized not in _IGNORED_OPTION_TOKENS:
                    if consumed_next and value is not None:
                        other_options.append(f"{token} {value}")
                    else:
                        other_options.append(token)
            elif token.startswith("-"):
                normalized = token.lower()
                if normalized not in _IGNORED_OPTION_TOKENS:
                    other_options.append(token)
            if consumed_next:
                idx += 1
            idx += 1

    return RequirementOptionAnalysis(
        require_hashes=require_hashes,
        prefer_binary=prefer_binary,
        pre=pre,
        no_build_isolation=no_build_isolation,
        no_deps=no_deps,
        no_binary=tuple(dict.fromkeys(no_binary)),
        only_binary=tuple(dict.fromkeys(only_binary)),
        use_features=tuple(dict.fromkeys(use_features)),
        other_options=tuple(dict.fromkeys(other_options)),
    )


def _issue_reason(issue: RequirementIssue) -> str:
    if issue.kind == "missing":
        return f"{issue.package} not installed"
    spec = issue.specifier or "unspecified"
    installed = issue.installed or "unknown"
    return f"{issue.package} {installed} does not satisfy {spec}"


def _compute_smart_context(
    requirements: Path | None,
    *,
    dev: bool,
    upgrade: bool,
) -> SmartInstallContext:
    req_path = requirements.resolve() if requirements else REQUIREMENTS_FILE
    requirements_exist = req_path.exists()
    stamp = _inspect_requirement_stamp(req_path if requirements_exist else None)
    python_version = _python_runtime_tag()
    pip_version = _current_pip_version()
    pip_needs_bootstrap, bootstrap_reason = _evaluate_pip_status(pip_version)

    metadata_paths = _metadata_paths_for_analysis()
    requirement_sources = _analyze_requirement_sources(
        req_path if requirements_exist else None
    )
    requirement_pinning = _analyze_requirement_pinning(
        req_path if requirements_exist else None
    )
    requirement_duplicates = _analyze_requirement_duplicates(
        req_path if requirements_exist else None
    )
    requirement_hashing = _analyze_requirement_hashing(
        req_path if requirements_exist else None
    )
    requirement_markers = _analyze_requirement_markers(
        req_path if requirements_exist else None
    )
    requirement_indexes = _analyze_requirement_indexes(
        req_path if requirements_exist else None
    )
    requirement_options = _analyze_requirement_options(
        req_path if requirements_exist else None
    )
    missing: tuple[str, ...] = ()
    if requirements_exist:
        try:
            missing = tuple(
                setup_stages._missing_requirements(
                    req_path, metadata_paths=metadata_paths
                )
            )
        except Exception as exc:
            SUMMARY.add_warning(f"Requirement analysis failed: {exc}")
    details, missing_packages, mismatched_packages, warnings = _analyze_requirement_issues(
        req_path,
        missing,
        metadata_paths=metadata_paths,
    )
    marker_warnings: list[str] = []
    if requirement_markers.parsing_errors:
        marker_warnings.extend(
            f"Requirement marker parsing failed: {error}"
            for error in requirement_markers.parsing_errors
        )
    if requirement_markers.unsatisfied:
        marker_warnings.append(
            "Requirement markers unsatisfied for current environment: "
            + _preview_missing(requirement_markers.unsatisfied)
        )
    if requirement_markers.python_mismatch:
        marker_warnings.append(
            "Python version markers exclude current runtime: "
            + _preview_missing(requirement_markers.python_mismatch)
        )
    if requirement_markers.platform_mismatch:
        marker_warnings.append(
            "Platform markers exclude current platform: "
            + _preview_missing(requirement_markers.platform_mismatch)
        )
    if marker_warnings:
        warnings.extend(marker_warnings)
    offline = is_offline()
    wheel_links = tuple(_available_wheel_links())
    wheel_cache_files, wheel_cache_bytes = _wheel_cache_stats()
    wheel_cache_newest, wheel_cache_oldest = _wheel_cache_freshness()
    venv_diagnostics = _gather_venv_diagnostics()
    if offline:
        connectivity = ConnectivityProbe(
            attempted=False,
            reachable=None,
            host=_connectivity_host(),
            latency_ms=None,
            error="offline mode forced",
        )
    else:
        connectivity = _probe_connectivity()
        if connectivity.attempted and not connectivity.reachable and connectivity.error:
            SUMMARY.add_warning(f"Network probe failed: {connectivity.error}")

    reasons: list[str] = []
    if not requirements_exist:
        reasons.append("requirements file missing")
    else:
        if stamp.recorded_hash is None:
            reasons.append("no requirement stamp recorded")
        if stamp.changed and stamp.recorded_hash is not None:
            reasons.append("requirements changed")
        if missing:
            count = len(missing)
            noun = "package" if count == 1 else "packages"
            reasons.append(f"{count} missing {noun}")
        if stamp.recorded_python and stamp.recorded_python != python_version:
            reasons.append("python version changed")
        if stamp.age_days is not None and stamp.age_days > STAMP_STALE_AFTER_DAYS:
            reasons.append(f"stamp stale ({int(stamp.age_days)}d)")
    if not venv_diagnostics.exists:
        reasons.append("virtualenv missing")
    elif not venv_diagnostics.python_exists:
        reasons.append("venv python missing")
    if not offline and connectivity.attempted and not connectivity.reachable:
        reasons.append("network unreachable")
    if upgrade:
        reasons.append("upgrade requested")

    dev_req_path = (ROOT_DIR / "requirements-dev.txt").resolve()
    dev_req_exists = dev_req_path.exists()

    triggered_by_stamp = requirements_exist and (
        stamp.recorded_hash is None or (stamp.changed and stamp.recorded_hash is not None)
    )
    partial_reinstall: tuple[str, ...] = ()
    if (
        requirements_exist
        and missing
        and not upgrade
        and not triggered_by_stamp
        and len(details) == len(missing)
    ):
        partial_reinstall = tuple(detail.requirement for detail in details)

    should_install = requirements_exist and (
        upgrade
        or bool(missing)
        or stamp.changed
        or stamp.recorded_hash is None
        or (
            bool(stamp.recorded_python)
            and stamp.recorded_python != python_version
        )
    )
    if requirements_exist and not venv_diagnostics.python_exists:
        should_install = True
    needs_pip_for_work = should_install or (dev and (dev_req_exists or bool(DEV_PACKAGES)))
    pip_bootstrap_recommended = not offline and (
        pip_needs_bootstrap or needs_pip_for_work
    )
    pip_bootstrap_reason = bootstrap_reason
    if pip_bootstrap_reason is None and needs_pip_for_work:
        pip_bootstrap_reason = "prepare pip for upcoming installs"

    if not venv_diagnostics.exists:
        warnings.append(
            f"Virtualenv directory missing at {venv_diagnostics.root}"
        )
    elif not venv_diagnostics.python_exists:
        warnings.append(
            f"Virtualenv python missing at {venv_diagnostics.python_path}"
        )
    if venv_diagnostics.missing_site_packages:
        missing_preview = ", ".join(
            str(path) for path in venv_diagnostics.missing_site_packages[:2]
        )
        if len(venv_diagnostics.missing_site_packages) > 2:
            missing_preview += " …"
        warnings.append(
            "Site-packages directory missing: " + missing_preview
        )
    if not venv_diagnostics.writable:
        warnings.append(
            f"Virtualenv path not writable: {venv_diagnostics.root}"
        )
    if (
        venv_diagnostics.disk_percent_free is not None
        and venv_diagnostics.disk_percent_free < VENV_DISK_WARN_PERCENT
    ):
        warnings.append(
            f"Low disk space near virtualenv ({venv_diagnostics.disk_percent_free:.1f}% free)"
        )

    if requirement_sources.missing_local:
        warnings.append(
            "Local requirement path missing: "
            + _preview_missing(requirement_sources.missing_local)
        )
    if requirement_sources.missing_nested:
        warnings.append(
            "Nested requirements missing: "
            + _preview_missing(requirement_sources.missing_nested)
        )
    if offline and requirement_sources.network:
        warnings.append(
            "Offline mode but requirements need network access: "
            + _preview_missing(requirement_sources.network)
        )

    if requirement_indexes.insecure_indexes:
        warnings.append(
            "Insecure index URL detected: "
            + _preview_missing(requirement_indexes.insecure_indexes)
        )
    if requirement_indexes.insecure_links:
        warnings.append(
            "Insecure find-links URL detected: "
            + _preview_missing(requirement_indexes.insecure_links)
        )
    if offline and not requirement_indexes.no_index and requirement_indexes.network_indexes:
        warnings.append(
            "Offline mode but index URLs configured: "
            + _preview_missing(requirement_indexes.network_indexes)
        )
    if offline and requirement_indexes.network_find_links:
        warnings.append(
            "Offline mode but find-links require network access: "
            + _preview_missing(requirement_indexes.network_find_links)
        )

    if requirement_options.no_binary:
        warnings.append(
            "Binary wheels disabled via --no-binary: "
            + _preview_missing(requirement_options.no_binary)
        )
    if requirement_options.pre:
        warnings.append(
            "Pre-release installs allowed (--pre); builds may pull unstable versions."
        )
    if requirement_options.no_build_isolation:
        warnings.append(
            "Build isolation disabled (--no-build-isolation); builds may leak environment state."
        )
    if requirement_options.no_deps:
        warnings.append(
            "Dependency resolution disabled (--no-deps); transitive packages may be missing."
        )
    if requirement_options.use_features:
        warnings.append(
            "Experimental pip features enabled: "
            + _preview_missing(requirement_options.use_features)
        )
    if requirement_options.other_options:
        warnings.append(
            "Additional pip options encountered: "
            + _preview_missing(requirement_options.other_options)
        )

    if requirement_pinning.unversioned:
        warnings.append(
            "Unversioned requirements: "
            + _preview_missing(requirement_pinning.unversioned)
        )
    if requirement_pinning.ranged:
        warnings.append(
            "Loose version ranges: "
            + _preview_missing(requirement_pinning.ranged)
        )
    if requirement_pinning.wildcard:
        warnings.append(
            "Wildcard pins may drift: "
            + _preview_missing(requirement_pinning.wildcard)
        )
    if requirement_pinning.invalid:
        warnings.append(
            "Invalid requirement entries: "
            + _preview_missing(requirement_pinning.invalid)
        )

    if requirement_duplicates.duplicates:
        warnings.append(
            "Duplicate requirement entries: "
            + _preview_missing(requirement_duplicates.duplicates)
        )
    if requirement_duplicates.conflicting:
        warnings.append(
            "Conflicting requirement pins: "
            + _preview_missing(requirement_duplicates.conflicting)
        )

    if (
        requirement_hashing.hashed_total
        and requirement_hashing.unhashed
        and requirement_hashing.unhashed_total
    ):
        warnings.append(
            "Requirement hashes missing: "
            + _preview_missing(requirement_hashing.unhashed)
        )
    if requirement_hashing.hashed_unpinned:
        warnings.append(
            "Hashed requirements lack strict pins: "
            + _preview_missing(requirement_hashing.hashed_unpinned)
        )
    if requirement_hashing.insecure_urls:
        warnings.append(
            "Insecure requirement URLs: "
            + _preview_missing(requirement_hashing.insecure_urls)
        )

    return SmartInstallContext(
        requirements_path=req_path,
        requirements_exist=requirements_exist,
        stamp=stamp,
        missing_requirements=missing,
        offline=offline,
        wheel_links=wheel_links,
        upgrade_requested=upgrade,
        dev_requested=dev,
        dev_requirements_path=dev_req_path,
        dev_requirements_exist=dev_req_exists,
        should_install=should_install,
        reasons=tuple(reasons),
        missing_packages=tuple(missing_packages),
        conflicting_packages=tuple(mismatched_packages),
        missing_details=tuple(details),
        partial_reinstall=partial_reinstall,
        analysis_warnings=tuple(warnings),
        pip_bootstrap_recommended=pip_bootstrap_recommended,
        pip_bootstrap_reason=pip_bootstrap_reason,
        python_version=python_version,
        pip_version=pip_version,
        stamp_age_days=stamp.age_days,
        wheel_cache_files=wheel_cache_files,
        wheel_cache_bytes=wheel_cache_bytes,
        connectivity=connectivity,
        wheel_cache_newest=wheel_cache_newest,
        wheel_cache_oldest=wheel_cache_oldest,
        venv=venv_diagnostics,
        requirement_sources=requirement_sources,
        requirement_pinning=requirement_pinning,
        requirement_duplicates=requirement_duplicates,
        requirement_hashing=requirement_hashing,
        requirement_markers=requirement_markers,
        requirement_indexes=requirement_indexes,
        requirement_options=requirement_options,
    )


def build_smart_install_plan(
    requirements: Path | None,
    *,
    dev: bool,
    upgrade: bool,
) -> SmartInstallPlan:
    context = _compute_smart_context(requirements, dev=dev, upgrade=upgrade)
    steps: list[SmartPlanStep] = []
    insights: list[str] = []
    had_install_step = False

    insights.append(
        "Python runtime: "
        f"{context.python_version} (last {context.stamp.recorded_python or 'unknown'})"
    )
    insights.append(
        "pip: "
        f"{context.pip_version or 'unavailable'} (last {context.stamp.recorded_pip or 'unknown'})"
    )
    insights.append(
        f"Offline mode: {'yes' if context.offline else 'no'} (wheel links: {len(context.wheel_links)})"
    )
    if context.stamp.requirement_hash:
        recorded = context.stamp.recorded_hash or "<none>"
        match = (
            "match" if recorded == context.stamp.requirement_hash else "mismatch"
        )
        insights.append(
            f"Requirement hash: {context.stamp.requirement_hash[:12]}… (recorded {match})"
        )
    elif context.requirements_exist:
        insights.append("Requirement hash unavailable; install recommended.")

    if context.stamp_age_days is not None:
        insights.append(
            f"Requirement stamp age: {context.stamp_age_days:.1f} days"
        )
    else:
        insights.append("Requirement stamp age: unavailable")

    sources = context.requirement_sources
    insights.append(
        "Requirement sources: "
        f"{sources.total} direct spec(s) "
        f"(network {len(sources.network)}, local {len(sources.local)}, nested {len(sources.nested)})"
    )
    if sources.network:
        insights.append(
            "Network requirements detected: "
            + _preview_missing(sources.network)
        )
    if sources.local:
        insights.append(
            "Local path requirements detected: "
            + _preview_missing(sources.local)
        )
    if sources.editable:
        insights.append(
            "Editable installs detected: "
            + _preview_missing(sources.editable)
        )
    if sources.nested:
        insights.append(
            "Nested requirement files referenced: "
            + _preview_missing(sources.nested)
        )

    indexes = context.requirement_indexes
    if (
        indexes.primary_index is not None
        or indexes.extra_indexes
        or indexes.no_index
    ):
        parts: list[str] = []
        if indexes.primary_index is not None:
            parts.append(f"primary {indexes.primary_index}")
        else:
            parts.append("primary default")
        if indexes.extra_indexes:
            parts.append(f"{len(indexes.extra_indexes)} extra index(es)")
        if indexes.no_index:
            parts.append("no-index enabled")
        insights.append("Requirement indexes: " + ", ".join(parts))
    if indexes.find_links:
        insights.append(
            "Find-links sources: " + _preview_missing(indexes.find_links)
        )
    if indexes.trusted_hosts:
        insights.append(
            "Trusted hosts configured: " + _preview_missing(indexes.trusted_hosts)
        )

    options = context.requirement_options
    option_flags: list[str] = []
    if options.require_hashes:
        option_flags.append("require-hashes")
    if options.prefer_binary:
        option_flags.append("prefer-binary")
    if options.pre:
        option_flags.append("pre")
    if options.no_build_isolation:
        option_flags.append("no-build-isolation")
    if options.no_deps:
        option_flags.append("no-deps")
    if option_flags:
        insights.append("Requirement options: " + ", ".join(option_flags))
    if options.no_binary:
        insights.append(
            "Binary wheels disabled for: " + _preview_missing(options.no_binary)
        )
    if options.only_binary:
        insights.append(
            "Only binary wheels enforced for: "
            + _preview_missing(options.only_binary)
        )
    if options.use_features:
        insights.append(
            "Experimental pip features: " + _preview_missing(options.use_features)
        )
    if options.other_options:
        insights.append(
            "Additional pip options: " + _preview_missing(options.other_options)
        )

    pinning = context.requirement_pinning
    loose_count = (
        len(pinning.ranged) + len(pinning.unversioned) + len(pinning.wildcard)
    )
    if pinning.total or pinning.invalid:
        insights.append(
            "Requirement pinning: "
            f"{len(pinning.pinned)}/{pinning.total} pinned, {loose_count} loose"
        )
    if pinning.constraints:
        insights.append(
            "Constraints referenced: " + _preview_missing(pinning.constraints)
        )
    if pinning.unversioned:
        insights.append(
            "Unversioned requirements detected: "
            + _preview_missing(pinning.unversioned)
        )
    if pinning.ranged:
        insights.append(
            "Version ranges detected: " + _preview_missing(pinning.ranged)
        )
    if pinning.wildcard:
        insights.append(
            "Wildcard pins detected: " + _preview_missing(pinning.wildcard)
        )
    if pinning.markers:
        insights.append(
            "Requirements with markers: " + _preview_missing(pinning.markers)
        )
    if pinning.extras:
        insights.append(
            "Extras requested: " + _preview_missing(pinning.extras)
        )
    if pinning.invalid:
        insights.append(
            "Invalid requirements skipped: "
            + _preview_missing(pinning.invalid)
        )

    markers = context.requirement_markers
    if markers.with_markers:
        summary = (
            "Requirement markers: "
            f"{markers.with_markers}/{markers.total} conditional entries"
        )
        if markers.unsatisfied:
            summary += (
                f", {len(markers.unsatisfied)} unsatisfied for this environment"
            )
        insights.append(summary)
    if markers.unsatisfied:
        insights.append(
            "Markers not satisfied for this environment: "
            + _preview_missing(markers.unsatisfied)
        )
    if markers.python_mismatch:
        insights.append(
            "Python marker mismatches: "
            + _preview_missing(markers.python_mismatch)
        )
    if markers.platform_mismatch:
        insights.append(
            "Platform marker mismatches: "
            + _preview_missing(markers.platform_mismatch)
        )

    duplicates = context.requirement_duplicates
    if duplicates.duplicates:
        insights.append(
            "Duplicate requirement entries detected: "
            + _preview_missing(duplicates.duplicates)
        )
    if duplicates.marker_variants:
        insights.append(
            "Marker-specific requirement variants: "
            + _preview_missing(duplicates.marker_variants)
        )
    if duplicates.conflicting:
        insights.append(
            "Conflicting requirement pins detected: "
            + _preview_missing(duplicates.conflicting)
        )

    hashing = context.requirement_hashing
    if hashing.total:
        summary = (
            f"Requirement hashes: {hashing.hashed_total}/{hashing.total} hashed"
        )
        if hashing.hashed_unpinned:
            summary += (
                f", {len(hashing.hashed_unpinned)} hashed without strict pins"
            )
        insights.append(summary)
    if hashing.unhashed and hashing.hashed_total:
        insights.append(
            "Requirements without hashes: "
            + _preview_missing(hashing.unhashed)
        )
    elif hashing.unhashed and hashing.total:
        insights.append(
            "Requirement hashes missing entirely: "
            + _preview_missing(hashing.unhashed)
        )
    if hashing.hashed_unpinned:
        insights.append(
            "Hashed requirements missing strict pins: "
            + _preview_missing(hashing.hashed_unpinned)
        )
    if hashing.insecure_urls:
        insights.append(
            "Insecure requirement URLs: "
            + _preview_missing(hashing.insecure_urls)
        )

    insights.append(
        "Wheel cache: "
        f"{context.wheel_cache_files} wheel(s) ({_format_bytes(context.wheel_cache_bytes)}) "
        f"across {len(context.wheel_links)} link(s)"
    )
    insights.append(_describe_connectivity(context.connectivity))

    venv = context.venv
    venv_status = "present" if venv.exists else "missing"
    python_status = "ready" if venv.python_exists else "missing python"
    if not venv.writable:
        python_status += ", read-only"
    insights.append(
        f"Virtualenv: {venv_status} at {venv.root} ({python_status})"
    )
    if venv.site_packages:
        missing_count = len(venv.missing_site_packages)
        present = len(venv.site_packages) - missing_count
        insights.append(
            f"Site-packages: {present}/{len(venv.site_packages)} available"
        )
    else:
        insights.append("Site-packages: unavailable")
    if (
        venv.disk_total_bytes is not None
        and venv.disk_free_bytes is not None
        and venv.disk_total_bytes > 0
    ):
        percent = (
            venv.disk_percent_free
            if venv.disk_percent_free is not None
            else (venv.disk_free_bytes / venv.disk_total_bytes) * 100.0
        )
        insights.append(
            "Virtualenv storage: "
            f"{_format_bytes(venv.disk_free_bytes)} free of "
            f"{_format_bytes(venv.disk_total_bytes)} ({percent:.1f}% free)"
        )
    elif venv.disk_free_bytes is not None:
        insights.append(
            f"Virtualenv storage: {_format_bytes(venv.disk_free_bytes)} free"
        )
    if venv.missing_site_packages:
        preview = ", ".join(
            str(path) for path in venv.missing_site_packages[:2]
        )
        if len(venv.missing_site_packages) > 2:
            preview += " …"
        insights.append(f"Missing site-packages paths: {preview}")
    if not venv.writable:
        insights.append("Virtualenv directory not writable; installs may fail.")

    now = time.time()
    freshness_parts: list[str] = []
    if context.wheel_cache_newest is not None:
        freshness_parts.append(
            f"newest {_format_timespan(now - context.wheel_cache_newest)} ago"
        )
    if (
        context.wheel_cache_oldest is not None
        and context.wheel_cache_oldest != context.wheel_cache_newest
    ):
        freshness_parts.append(
            f"oldest {_format_timespan(now - context.wheel_cache_oldest)} ago"
        )
    if freshness_parts:
        insights.append("Wheel cache freshness: " + "; ".join(freshness_parts))
    else:
        insights.append("Wheel cache freshness: unavailable")

    if context.offline and context.wheel_cache_files == 0:
        warning = "Offline mode with empty wheel cache; pip commands may fail."
        insights.append(warning)
        SUMMARY.add_warning(warning)
    elif context.offline and context.wheel_cache_oldest is not None:
        age_days = max((now - context.wheel_cache_oldest) / 86_400, 0.0)
        if age_days > WHEEL_CACHE_STALE_AFTER_DAYS:
            warning = (
                "Wheel cache stale; oldest wheel is "
                f"{int(age_days)}d old. Refresh offline assets."
            )
            insights.append(warning)
            SUMMARY.add_warning(warning)

    if context.reasons:
        insights.append("Install triggers: " + ", ".join(context.reasons))

    if context.missing_packages:
        insights.append(
            "Packages not installed: " + _preview_missing(context.missing_packages)
        )
    if context.conflicting_packages:
        insights.append(
            "Version conflicts: " + _preview_missing(context.conflicting_packages)
        )

    for warning in context.analysis_warnings:
        SUMMARY.add_warning(warning)
        insights.append(f"Analysis warning: {warning}")

    if not context.requirements_exist:
        warning = f"Requirements file missing: {context.requirements_path}"
        insights.append(warning)
        SUMMARY.add_warning(warning)
    else:
        reason_map = {issue.requirement: issue for issue in context.missing_details}
        if context.partial_reinstall:
            insights.append(
                f"Targeted reinstall for {len(context.partial_reinstall)} requirement(s)."
            )
            for req in context.partial_reinstall:
                issue = reason_map.get(req)
                title_name = issue.package if issue else req
                reason = _issue_reason(issue) if issue else f"Requirement {req} unsatisfied"
                steps.append(
                    SmartPlanStep(
                        f"Install {title_name}",
                        ("install", req),
                        upgrade_pip=not context.pip_bootstrap_recommended,
                        reason=reason,
                    )
                )
                had_install_step = True
        elif context.should_install:
            args = ["install", "-r", str(context.requirements_path)]
            if upgrade:
                args.append("-U")
            reason: str | None = None
            if context.reasons:
                reason = "; ".join(context.reasons)
            steps.append(
                SmartPlanStep(
                    "Install requirements",
                    tuple(args),
                    upgrade_pip=not context.pip_bootstrap_recommended,
                    reason=reason,
                )
            )
            had_install_step = True
        else:
            insights.append("Requirements unchanged. Skipping install.")

    if dev:
        if context.dev_requirements_exist:
            args = ["install", "-r", str(context.dev_requirements_path)]
            if upgrade:
                args.append("-U")
            steps.append(
                SmartPlanStep(
                    "Install dev requirements",
                    tuple(args),
                    upgrade_pip=not context.pip_bootstrap_recommended,
                    reason="dev extras requested",
                )
            )
            had_install_step = True
        else:
            for pkg in DEV_PACKAGES:
                args = ["install", pkg]
                if upgrade:
                    args.append("-U")
                steps.append(
                    SmartPlanStep(
                        f"Install {pkg}",
                        tuple(args),
                        upgrade_pip=not context.pip_bootstrap_recommended,
                        reason="dev extras fallback",
                        optional=True,
                    )
                )
                had_install_step = True
            insights.append(
                "Dev requirements file missing; falling back to individual dev packages."
            )

    if context.pip_bootstrap_reason:
        insights.append(f"pip bootstrap reason: {context.pip_bootstrap_reason}")

    if had_install_step:
        insights.append("pip check scheduled to validate installation.")
        steps.append(
            SmartPlanStep(
                "Validate environment",
                ("check",),
                upgrade_pip=False,
                reason="verify dependency graph",
            )
        )

    if steps and context.pip_bootstrap_recommended:
        steps.insert(
            0,
            SmartPlanStep(
                "Bootstrap pip",
                ("install", "-U", "pip", "setuptools", "wheel"),
                upgrade_pip=False,
                reason=context.pip_bootstrap_reason or "pip bootstrap recommended",
            ),
        )

    return SmartInstallPlan(context=context, steps=tuple(steps), insights=tuple(insights))
def update_repo() -> None:
    if CONFIG.no_git or is_offline(): log("Skip git update (disabled or offline)."); return
    if not (ROOT_DIR / ".git").exists(): log("No .git directory. Skipping update."); return
    log("Updating repository...")
    try:
        _retry(["git", "-C", str(ROOT_DIR), "fetch", "--all", "--tags", "--prune"], attempts=2)
        _retry(["git", "-C", str(ROOT_DIR), "pull", "--rebase", "--autostash"], attempts=2)
    except Exception as e:
        SUMMARY.add_warning(f"git update failed: {e}")

def build_extensions() -> None:
    dist_dir = ROOT_DIR / "dist"
    if is_offline():
        if _restore_wheel_artifacts(dist_dir):
            log("Offline mode: restored cached wheel artifacts.")
        else:
            SUMMARY.add_warning("Offline mode: no cached wheels available for reuse.")
        return
    try:
        py = ensure_venv()
        _run([py, "-m", "build", "--wheel", "--no-isolation"], cwd=ROOT_DIR)
    except Exception as e:
        SUMMARY.add_warning(f"native build skipped: {e}")
        if _restore_wheel_artifacts(dist_dir):
            log("Used cached wheel artifacts after build failure.")
    else:
        _store_wheel_artifacts(dist_dir)

def _progress(**overrides):
    # Columns: spinner | description | bar | % | M/N | elapsed
    return Progress(
        RainbowSpinnerColumn(),
        "[progress.description]{task.description}",
        BarColumn(bar_width=None),
        SmartPercentColumn(precision=0),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        refresh_per_second=10,
        console=console.raw,
        transient=True,
        disable=CONFIG.no_anim,
        **overrides,
    )

def _pip(args: Sequence[str], python: str | Path | None = None, *, upgrade_pip: bool = False, attempts: int = 2) -> None:
    py = str(python or ensure_venv())
    base_cmd = [py, "-m", "pip"]
    env_override: dict[str, str] = {}
    offline = is_offline()
    links = _available_wheel_links()
    if offline:
        offline_args: list[str] = ["--no-index"]
        if not links:
            SUMMARY.add_warning(
                "Offline mode enabled but wheel cache is empty; pip command may fail."
            )
        for link in links:
            offline_args.extend(["--find-links", link])
        if links:
            env_override["PIP_FIND_LINKS"] = os.pathsep.join(links)
        env_override["PIP_NO_INDEX"] = "1"
        cmd = base_cmd + list(args) + offline_args
        log("Offline mode: forcing pip to use cached wheels.")
    else:
        cmd = base_cmd + list(args)
        if upgrade_pip:
            _retry(
                base_cmd + ["install", "-U", "pip", "setuptools", "wheel"],
                attempts=attempts,
                env=env_override,
            )
    if offline and upgrade_pip:
        SUMMARY.add_warning("Offline mode: skipping pip bootstrap upgrade.")
    if upgrade_pip:
        env_override.setdefault("PIP_DEFAULT_TIMEOUT", "60")
    last: Exception | None = None
    for i in range(1, attempts + 1):
        try:
            _run(cmd, env=env_override or None)
            return
        except Exception as e:
            last = e
            if i < attempts: time.sleep(0.8 * i)
    if last is not None: raise last

def check_outdated(*, requirements: Path | None, upgrade: bool = False) -> None:
    import json
    py = ensure_venv()
    cmd = [py, "-m", "pip", "list", "--outdated", "--format=json"]
    try: out = subprocess.check_output(cmd, text=True, env=BASE_ENV); pkgs = json.loads(out)
    except Exception as e: SUMMARY.add_warning(f"pip list --outdated failed: {e}"); pkgs = []
    if upgrade and pkgs:
        with _progress() as prog:
            t = prog.add_task("Upgrading outdated packages", total=len(pkgs))
            def _worker(name: str) -> None:
                try: _pip(["install", "-U", name], upgrade_pip=False, attempts=2)
                except Exception as e: SUMMARY.add_error(f"Upgrade {name} failed: {e}")
                finally: prog.advance(t)
            with ThreadPoolExecutor() as ex:
                for item in pkgs:
                    name = item.get("name")
                    if name: ex.submit(_worker, name)
    else:
        table = Table(title="Outdated packages", box=box.SIMPLE_HEAVY)
        table.add_column("Name"); table.add_column("Version"); table.add_column("Latest"); table.add_column("Type")
        for p in pkgs: table.add_row(p.get("name",""), p.get("version",""), p.get("latest_version",""), p.get("type",""))
        console.print(table)

def show_info() -> None:
    info = get_system_info()
    if isinstance(info, dict):
        table = Table(title="CoolBox — System Info", box=box.MINIMAL_DOUBLE_HEAD)
        for k, v in info.items():
            table.add_row(k, str(v))
        console.print(table)
    else:
        console.print(info)

def show_plan(
    plan: SmartInstallPlan | None = None,
    *,
    requirements: Path | None = None,
    dev: bool = False,
    upgrade: bool = False,
) -> None:
    computed = plan or build_smart_install_plan(requirements, dev=dev, upgrade=upgrade)
    steps = computed.steps
    if RICH_AVAILABLE:
        table = Table(title="Smart Install Plan", box=box.SIMPLE_HEAVY)
        table.add_column("#", justify="right", no_wrap=True)
        table.add_column("Step")
        table.add_column("Command", overflow="fold")
        table.add_column("Why", overflow="fold")
        if steps:
            for idx, step in enumerate(steps, 1):
                command = "pip " + " ".join(step.pip_args)
                reason = step.reason or "(auto)"
                if step.optional:
                    reason += " (optional)"
                table.add_row(str(idx), step.title, command, reason)
        else:
            table.add_row("-", "No actions planned", "", "")
        console.print(table)
    else:
        if steps:
            for idx, step in enumerate(steps, 1):
                command = "pip " + " ".join(step.pip_args)
                reason = step.reason or "(auto)"
                if step.optional:
                    reason += " (optional)"
                log(f"Step {idx}: {step.title} -> {command} [{reason}]")
        else:
            log("No actions planned.")

    for insight in computed.insights:
        log(insight)

def run_tests(extra: Sequence[str]) -> None:
    py = ensure_venv()
    with _progress() as prog:
        task_id = prog.add_task("Running tests", total=1)
        try: _run([py, "-m", "pytest", "-q", *extra])
        except Exception as e: SUMMARY.add_error(f"pytest failed: {e}")
        finally: prog.advance(task_id)

def doctor() -> None:
    problems: list[str] = []
    if is_offline(): problems.append("offline mode active, downloads disabled.")
    if CONFIG.no_git: problems.append("NO_GIT set, repo update disabled.")
    if not REQUIREMENTS_FILE.exists(): problems.append("requirements.txt not found.")
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
        if lock_file: args.append(str(lock_file))
        if upgrade: _pip(["install", "-U", "-r", str(REQUIREMENTS_FILE)], upgrade_pip=False)
        _run(args)
    except Exception as e:
        SUMMARY.add_error(f"Sync failed: {e}")

def self_update() -> None:
    py = ensure_venv()
    try: _run([py, "-m", "pip", "install", "-U", "coolbox"])
    except Exception as e: SUMMARY.add_error(f"Self-update failed: {e}")

def clean_pyc() -> None:
    n = 0
    for p in ROOT_DIR.rglob("*"):
        if p.is_dir() and p.name == "__pycache__": shutil.rmtree(p, ignore_errors=True); n += 1
    log(f"Removed {n} __pycache__ folders.")

def collect_problems(output: Path | None = None, markers: Sequence[str] | None = None) -> None:
    markers = [m.strip() for m in (markers or ["TODO","FIXME","BUG","WARNING"])]
    pattern = "|".join(re.escape(m) for m in markers)
    problem_re = re.compile(f"({pattern})", re.IGNORECASE)
    ignore_dirs = {".git",".venv","venv","__pycache__"}
    files = [p for p in ROOT_DIR.rglob("*") if p.is_file() and not any(part in ignore_dirs for part in p.parts)]
    def _scan(path: Path) -> list[tuple[str,int,str]]:
        results: list[tuple[str,int,str]] = []
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                for lineno, line in enumerate(fh, 1):
                    if problem_re.search(line):
                        rel = path.relative_to(ROOT_DIR); results.append((str(rel), lineno, line.rstrip()))
        except Exception as exc: SUMMARY.add_warning(f"Could not read {path}: {exc}")
        return results
    matches: list[tuple[str,int,str]] = []
    with ThreadPoolExecutor() as ex:
        for res in ex.map(_scan, files): matches.extend(res)
    matches.sort()
    for f, n, t in matches: SUMMARY.warnings.append(f"{f}:{n}: {t}")
    if output:
        output.write_text("\n".join(f"{f}:{n}: {t}" for f, n, t in matches)); log(f"Wrote {len(matches)} problem lines to {output}")
    else:
        if RICH_AVAILABLE:
            table = Table(box=box.SIMPLE_HEAVY)
            table.add_column("File", overflow="fold"); table.add_column("Line", justify="right"); table.add_column("Text")
            for f, n, t in matches: table.add_row(f, str(n), t)
            console.print(Panel(table, title=f"Problems ({len(matches)})", box=box.ROUNDED))
        else:
            for f, n, t in matches: log(f"{f}:{n}: {t}")
            log(f"Found {len(matches)} problem lines.")

def _build_install_plan(req_path: Path, dev: bool, upgrade: bool) -> list[tuple[str, list[str], bool]]:
    plan = build_smart_install_plan(req_path, dev=dev, upgrade=upgrade)
    return plan.legacy()

def _execute_install_plan(planned: Sequence[SmartPlanStep]) -> None:
    if not planned:
        return
    with _progress() as prog:
        t = prog.add_task("Executing install plan", total=len(planned))
        for step in planned:
            prog.update(t, description=step.title)
            if step.reason:
                log(f"{step.title}: {step.reason}")
            try:
                _pip(list(step.pip_args), upgrade_pip=step.upgrade_pip, attempts=3)
            except Exception as e:
                SUMMARY.add_error(f"{step.title} failed: {e}")
            prog.advance(t)

def install(requirements: Path | None = None, *, dev: bool = False, upgrade: bool = False,
            skip_update: bool = False, no_anim: bool | None = None,
            border: bool | None = None, alt_screen: bool | None = None) -> None:
    os.chdir(ROOT_DIR)
    if not skip_update: update_repo()
    ensure_numpy()
    py = ensure_venv()

    if no_anim is True: CONFIG.no_anim = True
    if alt_screen is True: CONFIG.alt_screen = True
    border_enabled = CONFIG.border_enabled_default if border is None else bool(border)
    if CONFIG.no_anim: border_enabled = False

    req_path = requirements or REQUIREMENTS_FILE
    plan = build_smart_install_plan(req_path, dev=dev, upgrade=upgrade)
    for insight in plan.insights:
        log(insight)
    planned_steps = plan.steps
    log(f"Install plan steps: {len(planned_steps)}")

    border_ctx = (
        NeonPulseBorder(speed=0.04, style="rounded", theme="pride", thickness=2,
                        use_alt_screen=CONFIG.alt_screen, console=console.raw)
        if border_enabled else nullcontext()
    )

    try:
        with border_ctx:
            show_setup_banner()
            _execute_install_plan(planned_steps)
            try: _retry([py, "-m", "pip", "check"], attempts=1)
            except Exception as exc: SUMMARY.add_warning(f"pip check reported issues: {exc}")
            build_extensions()
    finally:
        console.flush()

    if req_path.is_file():
        try: _write_req_stamp(req_path)
        except Exception as e: SUMMARY.add_warning(f"Could not write requirement stamp: {e}")

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

    p_plan = sub.add_parser("plan", help="Preview smart install plan")
    p_plan.add_argument("--requirements", type=Path, default=None)
    p_plan.add_argument("--dev", action="store_true")
    p_plan.add_argument("--upgrade", action="store_true")

    sub.add_parser("lock", help="Generate lock file with pip-tools")
    p_sync = sub.add_parser("sync", help="Sync environment from lock file")
    p_sync.add_argument("--lock-file", type=Path, default=None)
    p_sync.add_argument("--upgrade", action="store_true")

    p_venv = sub.add_parser("venv", help="Create or recreate venv")
    p_venv.add_argument("--recreate", action="store_true")

    sub.add_parser("clean-pyc", help="Remove __pycache__ folders")

    p_prob = sub.add_parser("problems", help="Scan project for problem markers")
    p_prob.add_argument("--output", type=Path, default=None)
    p_prob.add_argument("--markers", type=str, default=None)

    p_test = sub.add_parser("test", help="Run pytest")
    p_test.add_argument("extra", nargs="*", default=[])

    sub.add_parser("update", help="git fetch/pull if repo")
    sub.add_parser("self-update", help="Update the CoolBox setup script")

    p.set_defaults(command="install")
    _load_plugins(sub)
    return p.parse_args(argv)

def _load_plugins(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    try:
        from importlib.metadata import entry_points
    except Exception:
        return
    try:
        for ep in entry_points().select(group="coolbox.plugins"):
            try: ep.load()(sub)
            except Exception as exc: SUMMARY.add_warning(f"Plugin {ep.name} failed: {exc}")
    except Exception:
        pass

def main(argv: Sequence[str] | None = None) -> None:
    args = _parse_args(argv or sys.argv[1:])
    if getattr(args, "offline", False): set_offline(True)
    is_offline()
    if offline_auto_detected(): log("Offline mode detected (network unreachable).")
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
        elif cmd == "plan":
            show_plan(
                requirements=getattr(args, "requirements", None),
                dev=getattr(args, "dev", False),
                upgrade=getattr(args, "upgrade", False),
            )
        elif cmd == "venv":
            if getattr(args, "recreate", False):
                vdir = get_venv_dir()
                if vdir.exists():
                    shutil.rmtree(vdir, ignore_errors=True); log("Virtualenv removed.")
            ensure_venv(); log("Virtualenv ready.")
        elif cmd == "clean-pyc":
            clean_pyc()
        elif cmd == "problems":
            markers = getattr(args, "markers", None)
            collect_problems(output=getattr(args, "output", None),
                             markers=[m.strip() for m in markers.split(",")] if markers else None)
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
        SUMMARY.add_warning("Interrupted by user."); exit_code = 130
    except BaseException as e:
        SUMMARY.add_error(f"Fatal: {e.__class__.__name__}: {e}"); exit_code = 1; raise
    finally:
        if cmd != "problems":
            try: collect_problems()
            except Exception as exc: SUMMARY.add_error(f"Problem scan failed: {exc}")
        SUMMARY.render(); send_telemetry(SUMMARY)
        if exit_code == 0 and SUMMARY.errors: exit_code = 1
        sys.exit(exit_code)

if __name__ == "__main__":
    main()
