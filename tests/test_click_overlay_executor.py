import os
import importlib

os.environ.setdefault("COOLBOX_LIGHTWEIGHT", "1")


def reload_module(monkeypatch, workers=None):
    if workers is None:
        monkeypatch.delenv("KILL_BY_CLICK_WORKERS", raising=False)
    else:
        monkeypatch.setenv("KILL_BY_CLICK_WORKERS", str(workers))
    import src.views.click_overlay as click_overlay
    return importlib.reload(click_overlay)


def shutdown_executor(mod):
    if mod._EXECUTOR is not None:
        mod._EXECUTOR.shutdown(cancel_futures=True)
        mod._EXECUTOR = None


def test_get_executor_defaults_to_two_workers(monkeypatch):
    mod = reload_module(monkeypatch)
    try:
        ex = mod.get_executor()
        assert ex._max_workers == 2
    finally:
        shutdown_executor(mod)


def test_get_executor_respects_env_override(monkeypatch):
    mod = reload_module(monkeypatch, workers=5)
    try:
        ex = mod.get_executor()
        assert ex._max_workers == 5
    finally:
        shutdown_executor(mod)
