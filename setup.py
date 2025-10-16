#!/usr/bin/env python3
"""CoolBox — install/inspect utilities with neon border UI, atomic console, and end-of-run summary."""

from __future__ import annotations

__version__ = "1.6.0"

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

from src.setup.run_summary import CommandRecord, RunSummaryPanelModel

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
def _detect_offline(timeout: float = 1.5) -> bool:
    try:
        with socket.create_connection(("pypi.org", 443), timeout=timeout): return False
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


def _store_stamp_to_cache(req_hash: str) -> None:
    cached = _global_stamp_path(req_hash)
    try:
        cached.write_text(req_hash, encoding="utf-8")
    except Exception:
        pass


def _should_install(req: Path, upgrade: bool) -> bool:
    if upgrade:
        return True
    if not req.exists():
        return False
    req_hash = _file_hash(req)
    sp = _stamp_path()
    if not sp.exists():
        _hydrate_stamp_from_cache(req_hash, sp)
    try:
        recorded = sp.read_text().strip()
    except Exception:
        return True
    return recorded != req_hash


def _write_req_stamp(req: Path) -> None:
    req_hash = _file_hash(req)
    target = _stamp_path()
    target.write_text(req_hash, encoding="utf-8")
    _store_stamp_to_cache(req_hash)


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
    planned: list[tuple[str, list[str], bool]] = []
    if req_path.is_file():
        if _should_install(req_path, upgrade):
            args = ["install", "-r", str(req_path)]
            if upgrade: args.append("-U")
            planned.append(("Install requirements", args, True))
        else:
            log("Requirements unchanged. Skipping install.")
    else:
        SUMMARY.add_warning(f"Requirements file missing: {req_path}")
    if dev:
        dev_req = ROOT_DIR / "requirements-dev.txt"
        if dev_req.is_file():
            args = ["install", "-r", str(dev_req)]
            if upgrade: args.append("-U")
            planned.append(("Install dev requirements", args, True))
        else:
            for pkg in ("pip-tools>=7","build>=1","wheel>=0.43","pytest>=8"):
                args = ["install", pkg]
                if upgrade: args.append("-U")
                planned.append((f"Install {pkg}", args, False))
    return planned

def _execute_install_plan(planned: Sequence[tuple[str, list[str], bool]]) -> None:
    if not planned: return
    with _progress() as prog:
        t = prog.add_task("Executing install plan", total=len(planned))
        for title, pip_args, upgrade_pip in planned:
            prog.update(t, description=title)
            try: _pip(pip_args, upgrade_pip=upgrade_pip, attempts=3)
            except Exception as e: SUMMARY.add_error(f"{title} failed: {e}")
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
    planned = _build_install_plan(req_path, dev, upgrade)
    log(f"Install plan steps: {len(planned)}")

    border_ctx = (
        NeonPulseBorder(speed=0.04, style="rounded", theme="pride", thickness=2,
                        use_alt_screen=CONFIG.alt_screen, console=console.raw)
        if border_enabled else nullcontext()
    )

    try:
        with border_ctx:
            show_setup_banner()
            _execute_install_plan(planned)
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
