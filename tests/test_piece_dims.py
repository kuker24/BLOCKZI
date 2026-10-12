import pytest
import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / 'copilot'))

from solver import get_dim_count


@pytest.mark.parametrize('scale', [0.8, 1.0, 1.298, 1.5])
def test_piece_dimensions_classes_1_to_5(scale):
    """Verify pixel extent maps correctly to cell counts 1..5 across resolutions."""
    # Representative pixel sizes for cell count c: approx c * 65 * scale
    test_cases = [
        (1, 65 * scale),
        (2, 130 * scale),
        (3, 195 * scale),
        (4, 260 * scale),
        (5, 325 * scale),
    ]

    for expected_cells, px_dim in test_cases:
        assert get_dim_count(px_dim, scale) == expected_cells, (
            f"Failed for {expected_cells} cells at dimension {px_dim} with scale {scale}"
        )


def test_piece_dimensions_boundary_conditions():
    """Verify behavior around the threshold boundaries at fx=1.0."""
    fx = 1.0
    # Boundary thresholds: 95, 160, 228, 295
    assert get_dim_count(94 * fx, fx) == 1
    assert get_dim_count(96 * fx, fx) == 2
    assert get_dim_count(159 * fx, fx) == 2
    assert get_dim_count(161 * fx, fx) == 3
    assert get_dim_count(227 * fx, fx) == 3
    assert get_dim_count(229 * fx, fx) == 4
    assert get_dim_count(294 * fx, fx) == 4
    assert get_dim_count(296 * fx, fx) == 5
