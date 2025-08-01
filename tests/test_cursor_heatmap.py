import importlib.util
import pathlib
import sys
import types

import pytest

base = pathlib.Path(__file__).resolve().parents[1] / "src"
utils_pkg = types.ModuleType("utils")
utils_pkg.__path__ = [str(base / "utils")]
sys.modules.setdefault("utils", utils_pkg)

spec = importlib.util.spec_from_file_location(
    "utils.scoring_engine", base / "utils/scoring_engine.py"
)
scoring_engine = importlib.util.module_from_spec(spec)
assert spec.loader is not None
sys.modules["utils.scoring_engine"] = scoring_engine
spec.loader.exec_module(scoring_engine)  # type: ignore[union-attr]
CursorHeatmap = scoring_engine.CursorHeatmap
Tuning = scoring_engine.Tuning


def _make_heatmap(decay: float = 0.9) -> CursorHeatmap:
    t = Tuning(
        heatmap_res=1,
        heatmap_weight=1.0,
        heatmap_decay=decay,
    )
    return CursorHeatmap(32, 32, t)


def test_lazy_decay_accumulates() -> None:
    hm = _make_heatmap()
    hm.update(5, 5)
    hm.update(5, 5)
    score = hm.region_score((5, 5, 0, 0))
    assert score == pytest.approx(1 + hm.decay)


def test_region_score_applies_decay() -> None:
    hm = _make_heatmap()
    hm.update(0, 0)
    hm.update(10, 10)
    score = hm.region_score((0, 0, 0, 0))
    assert score == pytest.approx(hm.decay)


def test_normalization_retains_values() -> None:
    hm = _make_heatmap(decay=0.1)
    for _ in range(6):
        hm.update(0, 0)
    score = hm.region_score((0, 0, 0, 0))
    expected = (1 - hm.decay ** 6) / (1 - hm.decay)
    assert score == pytest.approx(expected)
