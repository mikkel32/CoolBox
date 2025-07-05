import os
import signal
import time
import subprocess
from pathlib import Path


class Process:
    """Extremely small stand-in for :class:`psutil.Process`."""

    def __init__(self, pid: int = 0, name: str = "proc") -> None:
        self.pid = pid
        self._name = name

    # ------------------------------------------------------------------
    # Accessors used by the application. All return dummy values so the
    # code can run without the real psutil package installed.
    # ------------------------------------------------------------------
    def name(self) -> str:
        return self._name

    def exe(self) -> str:
        return "/proc"

    def terminate(self) -> None:  # pragma: no cover - basic signal
        try:
            os.kill(self.pid, signal.SIGTERM)
        except Exception:
            pass

    def kill(self) -> None:  # pragma: no cover - basic signal
        try:
            os.kill(self.pid, signal.SIGKILL)
        except Exception:
            pass

    def children(self, recursive: bool = False) -> list["Process"]:
        kids: list[Process] = []
        try:
            out = subprocess.check_output(["ps", "-o", "pid,ppid", "-e"], text=True)
            for line in out.splitlines()[1:]:
                try:
                    pid_str, ppid_str = line.strip().split()[:2]
                    pid = int(pid_str)
                    ppid = int(ppid_str)
                except Exception:
                    continue
                if ppid == self.pid:
                    child = Process(pid)
                    kids.append(child)
                    if recursive:
                        kids.extend(child.children(True))
        except Exception:
            pass
        return kids

    def wait(self, timeout: float | None = None) -> None:  # pragma: no cover
        start = time.time()
        while pid_exists(self.pid):
            if timeout is not None and time.time() - start > timeout:
                break
            time.sleep(0.05)

    def username(self) -> str:
        return "user"

    def status(self) -> str:
        return "running"

    def cmdline(self) -> list[str]:  # pragma: no cover - simple default
        return []

    def cpu_times(self):  # pragma: no cover - simple default
        return (0.0, 0.0)

    def cpu_percent(self, interval: float | None = None) -> float:
        return 0.0

    def memory_info(self):  # pragma: no cover - simple default
        return SimpleNamespace(rss=0, vms=0)

    def io_counters(self):  # pragma: no cover - simple default
        return SimpleNamespace(read_bytes=0, write_bytes=0)

    def open_files(self):  # pragma: no cover - simple default
        return []

    def connections(self, kind: str = "inet"):  # pragma: no cover - simple
        return []

    num_threads = 0


class NoSuchProcess(Exception):
    pass

class AccessDenied(Exception):
    pass

from collections import namedtuple
from types import SimpleNamespace

CONN_LISTEN = "LISTEN"
CONN_ESTABLISHED = "ESTABLISHED"
STATUS_ZOMBIE = "zombie"
STATUS_DEAD = "dead"

# very small subset of psutil._common for type hints
_sconn = namedtuple("sconn", "fd family type laddr raddr status pid")

class _common:  # pragma: no cover - minimal placeholder
    sconn = _sconn

# Stand-in functions used in tests

def process_iter(attrs=None):
    attrs = attrs or []
    proc_dir = Path("/proc")
    for pid_str in os.listdir(proc_dir):
        if not pid_str.isdigit():
            continue
        pid = int(pid_str)
        proc = Process(pid)
        info = {}
        if "name" in attrs or not hasattr(proc, "_name"):
            try:
                info_name = (proc_dir / pid_str / "comm").read_text().strip()
            except Exception:
                info_name = "proc"
            proc._name = info_name
            if "name" in attrs:
                info["name"] = info_name
        if "exe" in attrs:
            try:
                info["exe"] = os.readlink(proc_dir / pid_str / "exe")
            except Exception:
                info["exe"] = ""
        if "cmdline" in attrs:
            try:
                data = (proc_dir / pid_str / "cmdline").read_bytes().split(b"\0")
                info["cmdline"] = [d.decode() for d in data if d]
            except Exception:
                info["cmdline"] = []
        if "username" in attrs:
            try:
                uid = (proc_dir / pid_str).stat().st_uid
                import pwd
                info["username"] = pwd.getpwuid(uid).pw_name
            except Exception:
                info["username"] = ""
        if "memory_info" in attrs:
            try:
                rss_pages = int((proc_dir / pid_str / "statm").read_text().split()[1])
                rss = rss_pages * os.sysconf("SC_PAGE_SIZE")
            except Exception:
                rss = 0
            info["memory_info"] = SimpleNamespace(rss=rss)
        if "num_threads" in attrs:
            try:
                threads = 0
                with open(proc_dir / pid_str / "status") as f:
                    for line in f:
                        if line.startswith("Threads:"):
                            threads = int(line.split()[1])
                            break
            except Exception:
                threads = 0
            info["num_threads"] = threads
        if "io_counters" in attrs:
            try:
                vals = {}
                with open(proc_dir / pid_str / "io") as f:
                    for line in f:
                        key, val = line.split(":", 1)
                        vals[key.strip()] = int(val.strip())
                info["io_counters"] = SimpleNamespace(
                    read_bytes=vals.get("read_bytes", 0),
                    write_bytes=vals.get("write_bytes", 0),
                )
            except Exception:
                info["io_counters"] = SimpleNamespace(read_bytes=0, write_bytes=0)
        if "pid" in attrs:
            info["pid"] = pid
        proc.info = info
        yield proc

def net_connections(kind="inet"):
    return []

def net_if_addrs():
    return {}

def net_if_stats():
    return {}

def pid_exists(pid: int) -> bool:
    """Return ``True`` if ``pid`` appears to be running."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except Exception:
        return False
    return True

def cpu_count(logical=True):
    return 1

def cpu_percent(interval=None, percpu=False):
    if percpu:
        return [0.0]
    return 0.0

def virtual_memory():
    return SimpleNamespace(total=0, available=0, percent=0, used=0, free=0)

def disk_usage(path="/"):
    return SimpleNamespace(total=0, used=0, free=0, percent=0)

def net_io_counters():
    return SimpleNamespace(bytes_sent=0, bytes_recv=0)

def disk_io_counters():
    return SimpleNamespace(read_bytes=0, write_bytes=0)

def cpu_freq(percpu=False):
    if percpu:
        return [SimpleNamespace(current=0)]
    return SimpleNamespace(current=0)

def sensors_temperatures():
    return {}

def sensors_battery():
    return None

def wait_procs(procs, timeout=None):  # pragma: no cover - very small fallback
    return [], []

__all__ = [
    'Process','NoSuchProcess','AccessDenied',
    'CONN_LISTEN','CONN_ESTABLISHED','STATUS_ZOMBIE',
    'STATUS_DEAD',
    'process_iter','net_connections','net_if_addrs','net_if_stats','pid_exists',
    'cpu_count','cpu_percent','virtual_memory','disk_usage','net_io_counters',
    'disk_io_counters','cpu_freq','sensors_temperatures','sensors_battery',
    'wait_procs',
    '_common'
]
