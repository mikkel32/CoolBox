from queue import Queue
import random

from src.utils.process_monitor import ProcessEntry, ProcessWatcher


class _FakeProc:
    def __init__(self, pid: int = 1, step: float = 0.001) -> None:
        self.pid = pid
        self._t = 0.0
        self._step = step

    def cpu_times(self):
        self._t += self._step
        return (self._t, 0.0)


def test_proc_cpu_time_override() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(q)
    watcher._system_time_delta = 1.0

    called: list[int] = []

    def fake_cpu_time(pid: int, proc: _FakeProc, bulk=None) -> float:  # type: ignore[unused-argument]
        called.append(pid)
        return 42.0

    watcher._proc_cpu_time = fake_cpu_time  # type: ignore[assignment]
    proc = _FakeProc()
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, None, 1.0, 0, 0)
    assert cpu_time == 42.0
    assert called == [proc.pid]


def test_idle_global_alpha_param() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(q, idle_global_alpha=0.7)
    watcher._system_time_delta = 1.0
    try:
        assert watcher.idle_global_alpha == 0.7
    finally:
        watcher.stop()


def test_idle_cpu_skip_logic() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(q, idle_cpu=1.0, idle_cycles=2, max_skip=4)
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=0.0,
        user="u",
        start=0.0,
        status="",
        cpu_time=cpu_time,
        threads=1,
        read_bytes=0,
        write_bytes=0,
        files=0,
        conns=0,
    )

    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    assert watcher._idle_counts[proc.pid] == 1
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    assert watcher._idle_counts[proc.pid] == 2
    assert watcher._cpu_skip_intervals[proc.pid] == 2
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    # Next call should skip
    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    assert cpu_time2 == prev.cpu_time
    assert cpu2 == prev.cpu
    assert watcher._cpu_skip_counts[proc.pid] == 1

    watcher.stop()


def test_idle_skip_reset_on_activity() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(q, idle_cpu=1.0, idle_cycles=2, max_skip=4)
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=0.0,
        user="u",
        start=0.0,
        status="",
        cpu_time=cpu_time,
        threads=1,
        read_bytes=0,
        write_bytes=0,
        files=0,
        conns=0,
    )

    # Two idle samples to trigger skipping
    for _ in range(2):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
        prev.cpu_time = cpu_time
        prev.cpu = cpu

    assert watcher._cpu_skip_intervals[proc.pid] == 2

    # Simulate activity after skip cycle completes
    proc._step = 0.02
    for _ in range(watcher._cpu_skip_intervals[proc.pid] + 1):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
        proc.cpu_times()
    assert cpu > 0.5
    assert watcher._cpu_skip_intervals[proc.pid] == 1
    assert watcher._idle_counts[proc.pid] == 0

    watcher.stop()


def test_skip_interval_decay() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=2,
        max_skip=4,
        idle_decay=0.5,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=0.0,
        user="u",
        start=0.0,
        status="",
        cpu_time=cpu_time,
        threads=1,
        read_bytes=0,
        write_bytes=0,
        files=0,
        conns=0,
    )

    for _ in range(2):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
        prev.cpu_time = cpu_time
        prev.cpu = cpu

    assert watcher._cpu_skip_intervals[proc.pid] == 2

    proc._step = 0.02
    for _ in range(watcher._cpu_skip_intervals[proc.pid] + 1):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
        proc.cpu_times()
    assert cpu > 0.5
    assert watcher._cpu_skip_intervals[proc.pid] == 1

    watcher.stop()


def test_global_baseline_used_for_new_process() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(q, idle_cpu=1.0, idle_cycles=1, max_skip=3)
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc_a = _FakeProc(pid=1, step=0.02)
    proc_b = _FakeProc(pid=2, step=0.02)

    ts = 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc_a, None, ts, 0, 0)
    # Second process should get baseline close to first sample
    ts += 1.0
    cpu_time_b, cpu_b, _ = watcher._maybe_sample_cpu(proc_b, None, ts, 0, 0)
    assert abs(watcher._idle_baseline[proc_b.pid] - watcher._global_idle_baseline) < 1e-6
    watcher.stop()


def test_exponential_backoff() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(q, idle_cpu=1.0, idle_cycles=1, max_skip=8)
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=0.0,
        user="u",
        start=0.0,
        status="",
        cpu_time=cpu_time,
        threads=1,
        read_bytes=0,
        write_bytes=0,
        files=0,
        conns=0,
    )

    # first idle cycle triggers skip interval 2
    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    # run through skip interval then sample again to double to 4
    for _ in range(watcher._cpu_skip_intervals[proc.pid] + 1):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
        prev.cpu_time = cpu_time
        prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 4

    # run through next interval to reach 8 (max_skip)
    for _ in range(watcher._cpu_skip_intervals[proc.pid] + 1):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
        prev.cpu_time = cpu_time
        prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 8

    watcher.stop()


def test_idle_skip_jitter(monkeypatch) -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=8,
        idle_jitter=2.0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    monkeypatch.setattr(random, "uniform", lambda a, b: 1.5)

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=0.0,
        user="u",
        start=0.0,
        status="",
        cpu_time=cpu_time,
        threads=1,
        read_bytes=0,
        write_bytes=0,
        files=0,
        conns=0,
    )

    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    assert watcher._cpu_skip_intervals[proc.pid] == int(1 * 2 * 1.5)

    watcher.stop()


def test_idle_window_baseline() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_window=3,
        idle_baseline=1.0,
        idle_global_alpha=1.0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc(step=0.02)
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=0.0,
        user="u",
        start=0.0,
        status="",
        cpu_time=cpu_time,
        threads=1,
        read_bytes=0,
        write_bytes=0,
        files=0,
        conns=0,
    )
    assert abs(watcher._idle_baseline[proc.pid] - cpu) < 0.01

    proc._step = 0.06
    ts += 1.0
    cpu_time, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu2

    proc._step = 0.04
    ts += 1.0
    cpu_time, cpu3, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)

    avg = (cpu + cpu2 + cpu3) / 3
    assert abs(watcher._idle_baseline[proc.pid] - avg) < 0.01

    watcher.stop()


def test_idle_refresh_forces_sample() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=8,
        idle_refresh=2.5,
        idle_jitter=1.0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=0.0,
        user="u",
        start=0.0,
        status="",
        cpu_time=cpu_time,
        threads=1,
        read_bytes=0,
        write_bytes=0,
        files=0,
        conns=0,
    )

    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    # skip twice while within idle_refresh
    for _ in range(2):
        ts += 1.0
        cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
        assert cpu_time2 == prev.cpu_time
        assert cpu2 == prev.cpu

    # exceeded idle_refresh, sampling should resume even though skip interval
    ts += 1.0
    cpu_time3, cpu3, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    assert cpu_time3 != prev.cpu_time
    assert watcher._cpu_skip_counts[proc.pid] == 0

    watcher.stop()


def test_idle_baseline_updates_during_skip() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_skip_alpha=1.0,
        idle_window=3,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    ts = 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, None, ts, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=0.0,
        user="u",
        start=0.0,
        status="",
        cpu_time=cpu_time,
        threads=1,
        read_bytes=0,
        write_bytes=0,
        files=0,
        conns=0,
    )

    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    hist_len = len(watcher._idle_history[proc.pid])

    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    assert cpu_time2 == prev.cpu_time
    assert len(watcher._idle_history[proc.pid]) == hist_len + 1

    watcher.stop()


def test_idle_grace_delay() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int]]] = Queue()
    watcher = ProcessWatcher(q, idle_cpu=1.0, idle_cycles=1, idle_grace=2, max_skip=4)
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=0.0,
        user="u",
        start=0.0,
        status="",
        cpu_time=cpu_time,
        threads=1,
        read_bytes=0,
        write_bytes=0,
        files=0,
        conns=0,
    )

    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    # still within grace period, skip interval should remain 1
    assert watcher._cpu_skip_intervals.get(proc.pid, 1) == 1

    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    assert watcher._idle_counts[proc.pid] == 1
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    watcher.stop()
