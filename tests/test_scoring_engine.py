from collections import deque
from unittest.mock import patch

from src.utils.scoring_engine import ScoringEngine, tuning
from src.utils.window_utils import WindowInfo


def test_skip_zorder_stack_for_single_sample() -> None:
    engine = ScoringEngine(tuning, 100, 100, own_pid=0)
    sample = [WindowInfo(1, (0, 0, 10, 10))]
    with patch.object(tuning, "zorder_weight", 5.0), patch(
        "src.utils.scoring_engine.list_windows_at"
    ) as lwa, patch("src.utils.scoring_engine.prime_window_cache"):
        engine.score_samples(sample, 0.0, 0.0, 0.0, deque(), None)
        lwa.assert_not_called()


def test_zorder_stack_limited_depth() -> None:
    engine = ScoringEngine(tuning, 100, 100, own_pid=0)
    samples = [WindowInfo(1, (0, 0, 10, 10)), WindowInfo(2, (0, 0, 10, 10))]
    with patch.object(tuning, "zorder_weight", 5.0), patch(
        "src.utils.scoring_engine.list_windows_at", return_value=samples
    ) as lwa, patch("src.utils.scoring_engine.prime_window_cache"):
        engine.score_samples(samples, 5.0, 5.0, 0.0, deque(), None)
        lwa.assert_called_once_with(5, 5, len(samples))
