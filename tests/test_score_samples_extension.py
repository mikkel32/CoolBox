from collections import deque
from types import ModuleType
from typing import Any, cast
from unittest.mock import patch

import pytest

import coolbox.utils.analysis.scoring_engine as scoring_engine
from coolbox.utils.window_utils import WindowInfo


def test_score_samples_extension_matches_python() -> None:
    engine = scoring_engine.ScoringEngine(scoring_engine.tuning, 100, 100, own_pid=0)
    samples = [WindowInfo(1, (0, 0, 10, 10)), WindowInfo(2, (10, 0, 10, 10))]
    path = deque([(1, 1), (11, 1)])
    cy_helper = getattr(scoring_engine, "_cy_score_samples", None)
    if cy_helper is None:
        pytest.skip("Cython extension not built")
    scoring_module = cast(ModuleType, scoring_engine)
    with patch.multiple(
        scoring_engine.tuning,
        area_weight=1.0,
        center_weight=1.0,
        edge_penalty=0.5,
        path_weight=1.0,
        history_weight=0.5,
        velocity_scale=0.1,
    ):
        with patch.object(cast(Any, scoring_module), "_cy_score_samples", None):
            weights_py = engine.score_samples(samples, 5.0, 5.0, 0.5, path, None)
        assert cy_helper is not None
        with patch.object(cast(Any, scoring_module), "_cy_score_samples", cy_helper):
            weights_cy = engine.score_samples(samples, 5.0, 5.0, 0.5, path, None)
    assert weights_cy == weights_py
