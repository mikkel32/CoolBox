import setup
from pathlib import Path


def test_collect_problems_records_in_summary():
    test_file = setup.ROOT_DIR / "temp_problem.txt"
    test_file.write_text("FOOBAR_MARKER\n")
    try:
        setup.SUMMARY.warnings.clear()
        setup.collect_problems(markers=["FOOBAR_MARKER"])
        assert any("temp_problem.txt:1" in w for w in setup.SUMMARY.warnings)
    finally:
        if test_file.exists():
            test_file.unlink()
        setup.SUMMARY.warnings.clear()
