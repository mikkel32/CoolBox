from collections import deque
from unittest.mock import patch

import pytest

from src.utils.scoring_engine import ScoringEngine, tuning, _cy_score_samples
from src.utils.window_utils import WindowInfo


def test_score_samples_extension_matches_python() -> None:
    engine = ScoringEngine(tuning, 100, 100, own_pid=0)
    samples = [WindowInfo(1, (0, 0, 10, 10)), WindowInfo(2, (10, 0, 10, 10))]
    path = deque([(1, 1), (11, 1)])
    if _cy_score_samples is None:
        pytest.skip("Cython extension not built")
    with patch.multiple(
        tuning,
        area_weight=1.0,
        center_weight=1.0,
        edge_penalty=0.5,
        path_weight=1.0,
        history_weight=0.5,
        velocity_scale=0.1,
    ):
        with patch("src.utils.scoring_engine._cy_score_samples", None):
            weights_py = engine.score_samples(samples, 5.0, 5.0, 0.5, path, None)
        weights_cy = engine.score_samples(samples, 5.0, 5.0, 0.5, path, None)
    assert weights_cy == weights_py
