import unittest
from unittest.mock import patch

from coolbox.utils.hover_tracker import HoverTracker
from coolbox.utils.window_utils import WindowInfo


class TestHoverTracker(unittest.TestCase):
    def test_decay_removes_old_entries(self) -> None:
        with (
            patch("coolbox.utils.hover_tracker.tuning.gaze_decay", 0.5),
            patch("coolbox.utils.hover_tracker.tuning.score_min", 0.6),
            patch(
                "coolbox.utils.hover_tracker.time.monotonic",
                side_effect=[0.0, 1.0, 2.0, 3.0],
            ),
        ):
            tracker = HoverTracker()
            tracker.update(WindowInfo(1))
            tracker.update(WindowInfo(2))
            tracker.update(WindowInfo(2))
        self.assertNotIn(1, tracker.gaze_duration)

    def test_stability_returns_guess(self) -> None:
        with (
            patch("coolbox.utils.hover_tracker.tuning.stability_threshold", 2),
            patch("coolbox.utils.hover_tracker.tuning.vel_stab_scale", 0),
        ):
            tracker = HoverTracker()
            tracker.update(WindowInfo(1))
            tracker.update(WindowInfo(1))
            tracker.update(WindowInfo(1))
            info = tracker.stable_info(0.0)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.pid, 1)
