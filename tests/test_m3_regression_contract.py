from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_m3_final_regression_harness_files_exist():
    expected = (
        ROOT / "tests" / "test_m3_compatibility.py",
        ROOT / "tests" / "test_m3_negative_matrix.py",
        ROOT / "tests" / "test_m3_provider_search_tripwires.py",
    )
    missing = [str(path.relative_to(ROOT)) for path in expected if not path.is_file()]
    assert not missing, f"missing M3 regression harness files: {missing}"
