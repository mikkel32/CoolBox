class Process:
    def __init__(self, pid=0, name="proc"):
        self.pid = pid
        self._name = name
    def name(self):
        return self._name
    def exe(self):
        return "/proc"
    def terminate(self):
        pass
    def kill(self):
        pass
    def children(self, recursive=False):
        return []
    def wait(self, timeout=None):
        pass
    def username(self):
        return "user"
    def status(self):
        return "running"

class NoSuchProcess(Exception):
    pass

class AccessDenied(Exception):
    pass

CONN_LISTEN = "LISTEN"
CONN_ESTABLISHED = "ESTABLISHED"

# Stand-in functions used in tests

def process_iter(attrs=None):
    return iter([])

def net_connections(kind="inet"):
    return []

def net_if_addrs():
    return {}

def net_if_stats():
    return {}

def pid_exists(pid):
    return False

def cpu_count(logical=True):
    return 1

def cpu_percent(interval=None, percpu=False):
    if percpu:
        return [0.0]
    return 0.0

def virtual_memory():
    from types import SimpleNamespace
    return SimpleNamespace(total=0, available=0, percent=0, used=0, free=0)

__all__ = [
    'Process','NoSuchProcess','AccessDenied','CONN_LISTEN','CONN_ESTABLISHED',
    'process_iter','net_connections','net_if_addrs','net_if_stats','pid_exists','cpu_count','cpu_percent','virtual_memory'
]
