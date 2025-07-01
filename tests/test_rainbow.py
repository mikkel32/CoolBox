from src.utils.rainbow import NeonPulseBorder


def test_generate_colors_changes_with_phase():
    b = NeonPulseBorder(speed=0.01)
    cols1 = b._generate_colors(10, 5)
    b._phase += 1.0
    cols2 = b._generate_colors(10, 5)
    assert len(cols1) == 2 * 10 + 2 * 5 - 4
    assert cols1 != cols2
    assert all(c.startswith('#') for c in cols1)


def test_single_color_when_no_highlight():
    b = NeonPulseBorder(base_color="#123456", highlight_color="#123456")
    colors = b._generate_colors(8, 4)
    assert len(set(colors)) == 1
