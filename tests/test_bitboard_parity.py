import random
import numpy as np

import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / 'copilot'))

from solver import (
    count_isolated_holes,
    count_isolated_holes_bb,
    simulate_step,
    step_bb,
)

SHAPES = [
    [[1]],
    [[1, 1]],
    [[1], [1]],
    [[1, 1, 1]],
    [[1, 1], [1, 1]],
    [[1, 1, 1], [1, 1, 1], [1, 1, 1]],
    [[1, 1, 1, 1, 1]],
    [[1, 0], [1, 0], [1, 1]],
    [[0, 1, 0], [1, 1, 1]],
    [[1, 1, 1, 1]],
]


def test_bitboard_holes_parity():
    """Verify bitboard count_isolated_holes matches numpy on 2,000 random boards."""
    rng = random.Random(42)
    for trial in range(2000):
        # Generate random occupancy with varying density
        density = rng.uniform(0.05, 0.7)
        arr = (np.array([rng.random() < density for _ in range(64)], dtype=int)).reshape((8, 8))
        bb = sum(int(arr[r, c]) << (8 * r + c) for r in range(8) for c in range(8))

        np_holes = count_isolated_holes(arr)
        bb_holes = count_isolated_holes_bb(bb)
        assert np_holes == bb_holes, f"Holes mismatch trial {trial}: np={np_holes}, bb={bb_holes}"


def test_bitboard_simulate_step_parity():
    """Verify step_bb matches simulate_step clears, gems, and resulting board bits."""
    rng = random.Random(42)
    for trial in range(2000):
        b_arr = (np.array([rng.random() < 0.25 for _ in range(64)], dtype=int)).reshape((8, 8))
        g_arr = (np.array([rng.random() < 0.10 for _ in range(64)], dtype=int)).reshape((8, 8))
        s = rng.choice(SHAPES)
        p = {'shape': s, 'rows': len(s), 'cols': len(s[0])}
        r0 = rng.randint(0, 8 - p['rows'])
        c0 = rng.randint(0, 8 - p['cols'])

        mask = 0
        for dr in range(p['rows']):
            for dc in range(p['cols']):
                if s[dr][dc]:
                    mask |= 1 << (8 * (r0 + dr) + (c0 + dc))

        b_bits = sum(int(b_arr[r, c]) << (8 * r + c) for r in range(8) for c in range(8))
        g_bits = sum(int(g_arr[r, c]) << (8 * r + c) for r in range(8) for c in range(8))

        nb_np, ng_np, cl_np, fr_np, fc_np, gm_np, pc_np = simulate_step(b_arr, g_arr, p, r0, c0)
        nb_bb, ng_bb, cl_bb, fr_bb, fc_bb, gm_bb = step_bb(b_bits, g_bits, mask)

        if nb_np is None:
            assert nb_bb is None, f"Collision mismatch trial {trial}"
        else:
            assert nb_bb is not None
            assert cl_np == cl_bb
            assert gm_np == gm_bb
            assert fr_np == fr_bb
            assert fc_np == fc_bb

            nb_np_bits = sum(int(nb_np[r, c]) << (8 * r + c) for r in range(8) for c in range(8))
            assert nb_np_bits == nb_bb, f"Board bits mismatch trial {trial}"

            ng_np_bits = sum(int(ng_np[r, c]) << (8 * r + c) for r in range(8) for c in range(8))
            assert ng_np_bits == ng_bb, f"Gem bits mismatch trial {trial}"
