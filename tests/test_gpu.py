import types
from unittest.mock import patch

from src.utils.gpu import benchmark_gpu_usage


class DummyGPU:
    def __init__(self, load: float) -> None:
        self.load = load


def fake_getGPUs():
    return [DummyGPU(0.5)]


def test_benchmark_gpu_usage(monkeypatch):
    gputil = types.SimpleNamespace(getGPUs=fake_getGPUs)
    with patch.dict("sys.modules", {"GPUtil": gputil}):
        usage = benchmark_gpu_usage(samples=1, interval=0)
    assert usage == [50.0]
