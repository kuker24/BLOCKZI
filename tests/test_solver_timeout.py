import time
import numpy as np

import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / 'copilot'))

from solver import solve_full_sequence


def test_worst_case_empty_board_timeout_100ms():
    """Worst case: empty board with three 1x1 pieces.

    Under max_ms=100, the solver must finish in <= 150 ms (wall time)
    and return an anytime legal sequence.
    """
    empty_board = np.zeros((8, 8), dtype=int)
    empty_gems = np.zeros((8, 8), dtype=int)
    pieces = [
        {'slot': 0, 'slot_name': 's0', 'shape': [[1]], 'rows': 1, 'cols': 1},
        {'slot': 1, 'slot_name': 's1', 'shape': [[1]], 'rows': 1, 'cols': 1},
        {'slot': 2, 'slot_name': 's2', 'shape': [[1]], 'rows': 1, 'cols': 1},
    ]

    t0 = time.perf_counter()
    seq, score, dt = solve_full_sequence(empty_board, empty_gems, pieces, max_ms=100)
    wall_ms = (time.perf_counter() - t0) * 1000

    # Acceptance criteria: wall time <= 150 ms
    assert wall_ms <= 150, f"Solver took too long: wall time = {wall_ms:.1f} ms"
    # Result must not be empty
    assert len(seq) > 0, "Anytime sequence should not be empty"
    # Timed out flag should be set or accessible
    if hasattr(seq, 'timed_out'):
        assert seq.timed_out is True


def test_worst_case_empty_board_timeout_200ms():
    """Verify max_ms=200 finishes within 250ms wall time."""
    empty_board = np.zeros((8, 8), dtype=int)
    empty_gems = np.zeros((8, 8), dtype=int)
    pieces = [
        {'slot': 0, 'slot_name': 's0', 'shape': [[1]], 'rows': 1, 'cols': 1},
        {'slot': 1, 'slot_name': 's1', 'shape': [[1]], 'rows': 1, 'cols': 1},
        {'slot': 2, 'slot_name': 's2', 'shape': [[1]], 'rows': 1, 'cols': 1},
    ]

    t0 = time.perf_counter()
    seq, score, dt = solve_full_sequence(empty_board, empty_gems, pieces, max_ms=200)
    wall_ms = (time.perf_counter() - t0) * 1000

    assert wall_ms <= 250, f"Solver took too long: wall time = {wall_ms:.1f} ms"
    assert len(seq) > 0
