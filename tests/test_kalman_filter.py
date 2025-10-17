from coolbox.ui.views.overlays.click_overlay import _Kalman1D


def test_kalman_update_tracks_velocity():
    kf = _Kalman1D(0.0001, 0.01)
    kf.update(0.0, 0.0)
    x, v = kf.update(10.0, 1.0)
    assert abs(x - 10.0) < 0.1
    assert v > 4.0
