from queue import Queue
import random
import math
import psutil
import pytest

from coolbox.utils.process_monitor import ProcessEntry, ProcessWatcher


class _FakeProc:
    def __init__(
        self,
        pid: int = 1,
        step: float = 0.001,
        mem: float = 0.0,
        mem_step: float = 0.0,
        io_step: int = 0,
    ) -> None:
        self.pid = pid
        self._t = 0.0
        self._step = step
        self.mem = mem
        self.mem_step = mem_step
        self._read_bytes = 0
        self._write_bytes = 0
        self.io_step = io_step

    def cpu_times(self):
        self._t += self._step
        return (self._t, 0.0)

    def memory_info(self):
        self.mem += self.mem_step

        class Mem:
            def __init__(self, rss: int) -> None:
                self.rss = rss

        return Mem(int(self.mem * 1024 * 1024))

    def io_counters(self):
        self._read_bytes += self.io_step

        class IO:
            def __init__(self, r: int, w: int) -> None:
                self.read_bytes = r
                self.write_bytes = w

        return IO(self._read_bytes, self._write_bytes)


def test_proc_cpu_time_override() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(q, idle_active_samples=0)
    watcher._system_time_delta = 1.0

    called: list[int] = []

    def fake_cpu_time(pid: int, proc: _FakeProc, bulk=None) -> float:  # type: ignore[unused-argument]
        called.append(pid)
        return 42.0

    watcher._proc_cpu_time = fake_cpu_time  # type: ignore[assignment]
    proc = _FakeProc()
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, None, 1.0, 0.0, 0, 0)
    assert cpu_time == 42.0
    assert called == [proc.pid]


def test_idle_global_alpha_param() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(q, idle_global_alpha=0.7, idle_active_samples=0)
    watcher._system_time_delta = 1.0
    try:
        assert watcher.idle_global_alpha == 0.7
    finally:
        watcher.stop()


def test_idle_cpu_skip_logic() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(q, idle_cpu=1.0, idle_cycles=2, max_skip=4, idle_active_samples=0)
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert watcher._idle_counts[proc.pid] == 1
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert watcher._idle_counts[proc.pid] == 2
    assert watcher._cpu_skip_intervals[proc.pid] == 2
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    # Next call should skip
    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert cpu_time2 == prev.cpu_time
    assert cpu2 == prev.cpu
    assert watcher._cpu_skip_counts[proc.pid] == 1

    watcher.stop()


def test_idle_skip_reset_on_activity() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(q, idle_cpu=1.0, idle_cycles=2, max_skip=4, idle_active_samples=0)
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
        prev.cpu_time = cpu_time
        prev.cpu = cpu

    assert watcher._cpu_skip_intervals[proc.pid] == 2

    # Simulate activity after skip cycle completes
    proc._step = 0.02
    for _ in range(watcher._cpu_skip_intervals[proc.pid] + 1):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
        proc.cpu_times()
    assert cpu > 0.5
    assert watcher._cpu_skip_intervals[proc.pid] == 1
    assert watcher._idle_counts[proc.pid] == 0

    watcher.stop()


def test_skip_interval_decay() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=2,
        max_skip=4,
        idle_decay=0.5,
        idle_active_samples=2,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
        prev.cpu_time = cpu_time
        prev.cpu = cpu

    assert watcher._cpu_skip_intervals[proc.pid] == 2

    proc._step = 0.02
    for _ in range(watcher._cpu_skip_intervals[proc.pid] + 1):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
        proc.cpu_times()
    assert cpu > 0.5
    assert watcher._cpu_skip_intervals[proc.pid] == 1

    watcher.stop()


def test_global_baseline_used_for_new_process() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(q, idle_cpu=1.0, idle_cycles=1, max_skip=3, idle_active_samples=0)
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc_a = _FakeProc(pid=1, step=0.02)
    proc_b = _FakeProc(pid=2, step=0.02)

    ts = 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc_a, None, ts, 0.0, 0, 0)
    # Second process should get baseline close to first sample
    ts += 1.0
    cpu_time_b, cpu_b, _ = watcher._maybe_sample_cpu(proc_b, None, ts, 0.0, 0, 0)
    assert abs(watcher._idle_baseline[proc_b.pid] - watcher._global_idle_baseline) < 1e-6
    watcher.stop()


def test_exponential_backoff() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(q, idle_cpu=1.0, idle_cycles=1, max_skip=8, idle_active_samples=0)
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    # run through skip interval then sample again to double to 4
    for _ in range(watcher._cpu_skip_intervals[proc.pid] + 1):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
        prev.cpu_time = cpu_time
        prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 4

    # run through next interval to reach 8 (max_skip)
    for _ in range(watcher._cpu_skip_intervals[proc.pid] + 1):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
        prev.cpu_time = cpu_time
        prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 8

    watcher.stop()


def test_idle_skip_jitter(monkeypatch) -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=8,
        idle_jitter=2.0,
        idle_active_samples=2,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    monkeypatch.setattr(random, "uniform", lambda a, b: 1.5)

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert watcher._cpu_skip_intervals[proc.pid] == int(1 * 2 * 1.5)

    watcher.stop()


def test_idle_skip_multiplier() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=8,
        idle_mult=3.0,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 3

    for _ in range(watcher._cpu_skip_intervals[proc.pid] + 1):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
        prev.cpu_time = cpu_time
        prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 8

    watcher.stop()


def test_idle_dynamic_multiplier() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=8,
        idle_mult=3.0,
        idle_dynamic_mult=True,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    diff = max(0.0, min(watcher.idle_cpu, watcher.idle_cpu - cpu))
    factor = 1 + (watcher.idle_mult - 1) * diff / watcher.idle_cpu
    assert watcher._cpu_skip_intervals[proc.pid] == int(1 * factor)

    watcher.stop()


def test_idle_dynamic_weighted_rms() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=8,
        idle_mult=3.0,
        idle_dynamic_mult=True,
        idle_dynamic_mem=True,
        idle_dynamic_mode="rms",
        idle_cpu_weight=2.0,
        idle_mem_weight=1.0,
        idle_baseline=1.0,
        idle_mem_global_alpha=1.0,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc(mem=10.0)
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, proc.mem, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=proc.mem,
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

    proc.mem = 5.0
    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, proc.mem, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    prev.mem = proc.mem

    base_mem = watcher._idle_mem_baseline[proc.pid]
    diff_cpu = max(0.0, min(watcher.idle_cpu, watcher.idle_cpu - cpu)) / watcher.idle_cpu
    mem_def = max(0.0, base_mem - proc.mem) / base_mem if base_mem else 0.0
    scaled = math.sqrt(
        ((diff_cpu * watcher.idle_cpu_weight) ** 2 + (mem_def * watcher.idle_mem_weight) ** 2) / 2
    )
    scaled = min(1.0, max(0.0, scaled))
    factor = 1 + (watcher.idle_mult - 1) * scaled
    assert watcher._cpu_skip_intervals[proc.pid] == int(1 * factor)

    watcher.stop()


def test_idle_dynamic_exponent() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=8,
        idle_mult=3.0,
        idle_dynamic_mult=True,
        idle_dynamic_exp=2.0,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    diff = max(0.0, min(watcher.idle_cpu, watcher.idle_cpu - cpu)) / watcher.idle_cpu
    factor = 1 + (watcher.idle_mult - 1) * (diff ** watcher.idle_dynamic_exp)
    assert watcher._cpu_skip_intervals[proc.pid] == int(1 * factor)

    watcher.stop()


def test_idle_decay_exponent() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=8,
        idle_mult=2.0,
        idle_decay=0.5,
        idle_decay_exp=2.0,
        idle_dynamic_mult=True,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    proc._step = 0.1
    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert watcher._cpu_skip_intervals[proc.pid] == 1

    watcher.stop()


def test_idle_window_baseline() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_window=3,
        idle_baseline=1.0,
        idle_global_alpha=1.0,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc(step=0.02)
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu2

    proc._step = 0.04
    ts += 1.0
    cpu_time, cpu3, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)

    avg = (cpu + cpu2 + cpu3) / 3
    assert abs(watcher._idle_baseline[proc.pid] - avg) < 0.01

    watcher.stop()


def test_idle_refresh_forces_sample() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=8,
        idle_refresh=2.5,
        idle_jitter=1.0,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    # skip twice while within idle_refresh
    for _ in range(2):
        ts += 1.0
        cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
        assert cpu_time2 == prev.cpu_time
        assert cpu2 == prev.cpu

    # exceeded idle_refresh, sampling should resume even though skip interval
    ts += 1.0
    cpu_time3, cpu3, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert cpu_time3 != prev.cpu_time
    assert watcher._cpu_skip_counts[proc.pid] == 0

    watcher.stop()


def test_idle_baseline_updates_during_skip() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_skip_alpha=1.0,
        idle_window=3,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    ts = 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, None, ts, 0.0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    hist_len = len(watcher._idle_history[proc.pid])

    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert cpu_time2 == prev.cpu_time
    assert len(watcher._idle_history[proc.pid]) == hist_len + 1

    watcher.stop()


def test_idle_grace_delay() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(q, idle_cpu=1.0, idle_cycles=1, idle_grace=2, max_skip=4, idle_active_samples=0)
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    # still within grace period, skip interval should remain 1
    assert watcher._cpu_skip_intervals.get(proc.pid, 1) == 1

    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    assert watcher._idle_counts[proc.pid] == 1
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    watcher.stop()


def test_proc_cpu_time_no_such_process(monkeypatch) -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(q, idle_active_samples=0)
    proc = _FakeProc()

    def raise_nsp():
        raise psutil.NoSuchProcess(proc.pid)

    monkeypatch.setattr(proc, "cpu_times", raise_nsp)

    with pytest.raises(psutil.NoSuchProcess):
        watcher._proc_cpu_time(proc.pid, proc)


def test_proc_cpu_time_generic_error(monkeypatch) -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(q, idle_active_samples=0)
    proc = _FakeProc()

    def raise_err():
        raise RuntimeError("boom")

    monkeypatch.setattr(proc, "cpu_times", raise_err)

    assert watcher._proc_cpu_time(proc.pid, proc) == 0.0


def test_proc_cpu_time_attribute_error(monkeypatch) -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(q, idle_active_samples=0)
    proc = _FakeProc()

    def raise_attr():
        raise AttributeError("_cache")

    monkeypatch.setattr(proc, "cpu_times", raise_attr)

    with pytest.raises(psutil.NoSuchProcess):
        watcher._proc_cpu_time(proc.pid, proc)


def test_idle_reset_ratio() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_reset_ratio=1.5,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    proc._step = 0.05
    for _ in range(watcher._cpu_skip_intervals[proc.pid]):
        ts += 1.0
        cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
        prev.cpu_time = cpu_time
        prev.cpu = cpu
    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert cpu > watcher.idle_cpu * watcher.idle_reset_ratio
    assert watcher._cpu_skip_intervals[proc.pid] == 1
    watcher.stop()


def test_idle_check_interval_breaks_skip() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_reset_ratio=1.5,
        idle_check_interval=0.0,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    proc._step = 0.05
    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert cpu > watcher.idle_cpu * watcher.idle_reset_ratio
    assert watcher._cpu_skip_intervals[proc.pid] == 1
    watcher.stop()


def test_idle_active_samples_delay_skipping() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_reset_ratio=1.5,
        idle_active_samples=2,
        idle_check_interval=0.0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    proc._step = 0.05
    # Skip cycle will run but active_samples will prevent skipping next
    ts += 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert cpu > watcher.idle_cpu * watcher.idle_reset_ratio
    assert watcher._cpu_skip_intervals[proc.pid] == 1

    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert cpu2 >= 0.0
    assert watcher._cpu_skip_counts[proc.pid] == 0

    ts += 1.0
    cpu_time3, cpu3, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time3
    prev.cpu = cpu3
    assert watcher._cpu_skip_counts[proc.pid] == 0
    watcher.stop()


def test_idle_mem_delta_breaks_skip() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_mem_delta=1.0,
        idle_check_interval=0.0,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc(mem=10.0)
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=10.0,
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    proc.mem_step = 2.0
    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert cpu2 >= 0.0
    assert watcher._cpu_skip_counts[proc.pid] == 0
    watcher.stop()


def test_idle_io_delta_breaks_skip() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_io_delta=0.1,
        idle_check_interval=0.0,
        idle_active_samples=2,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    proc.io_step = 2 * 1024 * 1024
    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert cpu2 >= 0.0
    assert watcher._cpu_skip_counts[proc.pid] == 0
    watcher.stop()


def test_idle_mem_ratio_breaks_skip() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_mem_ratio=1.5,
        idle_check_interval=0.0,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc(mem=10.0)
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=10.0,
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    proc.mem_step = 6.0
    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert cpu2 >= 0.0
    assert watcher._cpu_skip_counts[proc.pid] == 0
    watcher.stop()


def test_idle_io_ratio_breaks_skip() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_io_ratio=1.5,
        idle_check_interval=0.0,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    proc.io_step = 3 * 1024 * 1024
    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert cpu2 >= 0.0
    assert watcher._cpu_skip_counts[proc.pid] == 0
    watcher.stop()


def test_idle_mem_reset_ratio() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_mem_reset_ratio=1.5,
        idle_check_interval=0.0,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc(mem=10.0)
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=10.0,
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    proc.mem_step = 8.0
    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert cpu2 >= 0.0
    assert watcher._cpu_skip_counts[proc.pid] == 0
    watcher.stop()


def test_idle_io_reset_ratio() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_io_reset_ratio=1.5,
        idle_check_interval=0.0,
        idle_active_samples=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu
    assert watcher._cpu_skip_intervals[proc.pid] == 2

    proc.io_step = int(4 * 1024 * 1024)
    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0, 0, 0)
    assert cpu2 >= 0.0
    assert watcher._cpu_skip_counts[proc.pid] == 0
    watcher.stop()


def test_idle_mem_reset_ratio_active() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=2,
        max_skip=4,
        idle_mem_reset_ratio=1.5,
        idle_active_samples=0,
        idle_grace=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc(mem=10.0)
    ts = 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, None, ts, proc.mem, 0, 0)
    prev = ProcessEntry(
        pid=proc.pid,
        name="p",
        cpu=cpu,
        mem=proc.mem,
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, proc.mem, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    proc.mem_step = 8.0
    ts += 1.0
    watcher._maybe_sample_cpu(proc, prev, ts, proc.mem, 0, 0)
    assert watcher._idle_counts[proc.pid] == 0
    assert watcher._cpu_skip_intervals.get(proc.pid, 1) == 1
    watcher.stop()


def test_idle_io_reset_ratio_active() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=2,
        max_skip=4,
        idle_io_reset_ratio=1.5,
        idle_active_samples=0,
        idle_grace=0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc()
    ts = 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, None, ts, 0.0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0.0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    proc.io_step = int(4 * 1024 * 1024)
    ts += 1.0
    watcher._maybe_sample_cpu(proc, prev, ts, 0.0, proc.io_step, 0)
    assert watcher._idle_counts[proc.pid] == 0
    assert watcher._cpu_skip_intervals.get(proc.pid, 1) == 1
    watcher.stop()


def test_global_mem_io_baseline_for_new_process() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=3,
        idle_active_samples=0,
        idle_mem_global_alpha=1.0,
        idle_io_global_alpha=1.0,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc_a = _FakeProc(pid=1, step=0.02, mem=5.0)
    ts = 1.0
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc_a, None, ts, proc_a.mem, 0, 0)
    entry_a = ProcessEntry(
        pid=proc_a.pid,
        name="a",
        cpu=cpu,
        mem=proc_a.mem,
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc_a, entry_a, ts, proc_a.mem, 0, 0)

    proc_b = _FakeProc(pid=2, step=0.02, mem=7.0)
    baseline_mem = watcher._global_mem_baseline
    baseline_io = watcher._global_io_baseline
    ts += 1.0
    cpu_time_b, cpu_b, _ = watcher._maybe_sample_cpu(proc_b, None, ts, proc_b.mem, 0, 0)
    assert abs(watcher._idle_mem_baseline[proc_b.pid] - baseline_mem) < 1e-6
    assert abs(watcher._idle_io_baseline[proc_b.pid] - baseline_io) < 1e-6
    watcher.stop()


def test_idle_trend_reset_breaks_skip() -> None:
    q: Queue[tuple[dict[int, ProcessEntry], set[int], float]] = Queue()
    watcher = ProcessWatcher(
        q,
        idle_cpu=1.0,
        idle_cycles=1,
        max_skip=4,
        idle_active_samples=0,
        idle_trend_reset=True,
        idle_trend_samples=2,
    )
    watcher._cpu_count = 1
    watcher._system_time_delta = 1.0

    proc = _FakeProc(step=0.02)
    prev = None
    ts = 1.0

    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0.0, 0, 0)
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
    cpu_time, cpu, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0.0, 0, 0)
    prev.cpu_time = cpu_time
    prev.cpu = cpu

    prev.trending_cpu = True

    ts += 1.0
    cpu_time2, cpu2, _ = watcher._maybe_sample_cpu(proc, prev, ts, 0.0, 0, 0)
    assert cpu_time2 != prev.cpu_time
    assert watcher._active_counts[proc.pid] == 2
    watcher.stop()
