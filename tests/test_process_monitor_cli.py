from argparse import Namespace
from unittest.mock import patch

from coolbox.cli.commands import process_monitor as pmcli


def test_parse_args_defaults(monkeypatch):
    for var in [
        "FORCE_QUIT_INTERVAL",
        "FORCE_QUIT_BATCH_SIZE",
        "FORCE_QUIT_MAX",
        "FORCE_QUIT_AUTO_INTERVAL",
        "FORCE_QUIT_MIN_INTERVAL",
        "FORCE_QUIT_MAX_INTERVAL",
        "FORCE_QUIT_AUTO_BATCH",
        "FORCE_QUIT_MIN_BATCH",
        "FORCE_QUIT_MAX_BATCH",
        "FORCE_QUIT_MIN_WORKERS",
        "FORCE_QUIT_MAX_WORKERS",
        "FORCE_QUIT_IGNORE_NAMES",
    ]:
        monkeypatch.delenv(var, raising=False)
    args = pmcli.parse_args([])
    assert isinstance(args, Namespace)
    assert args.interval == 2.0
    assert args.batch_size == 100
    assert args.limit == 20
    assert args.auto_interval is True
    assert args.min_interval == 0.5
    assert args.max_interval == 10.0
    assert args.auto_batch is True
    assert args.min_batch == 25
    assert args.max_batch == 1000
    assert args.min_workers == 2
    assert args.max_workers == 16
    assert args.ignore_names == ""


def test_parse_args_ignore(monkeypatch):
    monkeypatch.setenv("FORCE_QUIT_IGNORE_NAMES", "python,bash")
    args = pmcli.parse_args([])
    assert args.ignore_names == "python,bash"


def test_run_cli_starts_watcher(monkeypatch):
    calls = []

    class DummyWatcher:
        def __init__(self, *_a, **_kw):
            calls.append("init")
            self.interval = 0.01

        def start(self):
            calls.append("start")

        def stop(self):
            calls.append("stop")

    monkeypatch.setattr(pmcli, "ProcessWatcher", DummyWatcher)

    class DummyQueue:
        def __init__(self):
            self.items = []

        def empty(self) -> bool:
            return not self.items

        def get_nowait(self):
            return self.items.pop(0)

        def put_nowait(self, item):
            self.items.append(item)

    dq = DummyQueue()
    monkeypatch.setattr(pmcli, "Queue", lambda: dq)
    with patch.object(pmcli, "Live") as live:
        live.return_value.__enter__.return_value = live

        def stop(_):
            raise KeyboardInterrupt

        monkeypatch.setattr(pmcli.time, "sleep", stop)
        pmcli.run_cli(
            Namespace(
                interval=0.01,
                batch_size=1,
                limit=1,
                auto_interval=True,
                min_interval=0.5,
                max_interval=1.0,
                auto_batch=True,
                min_batch=1,
                max_batch=2,
                min_workers=1,
                max_workers=2,
                show_stats=False,
                ignore_names="",
            )
        )

    assert calls == ["init", "start", "stop"]
