from src.utils.rainbow import BlueGlowBorder


def test_generate_colors_changes_with_phase():
    b = BlueGlowBorder(speed=0.01)
    cols1 = b._generate_colors(10, 5)
    b._phase += 1.0
    cols2 = b._generate_colors(10, 5)
    assert len(cols1) == 2 * 10 + 2 * 5 - 4
    assert cols1 != cols2
    assert all(c.startswith('#') for c in cols1)


def test_generate_colors_amplitude_zero():
    b = BlueGlowBorder(amplitude=0)
    colors = b._generate_colors(8, 4)
    assert len(set(colors)) == 1

