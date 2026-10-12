#!/usr/bin/env python3
"""
Benchmark suite comparing Legacy Base vs Upgraded Solver (solver-v2)
Uses seed 42 and identical board/piece generation as bench.py.
"""

import random
import sys
import time
from pathlib import Path
import numpy as np

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / 'copilot'))

import solver as S

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

# Baseline timings recorded at Phase 0 on base commit 9db8281
BASELINE_MS = {
    0: [57811, 41686, 40631],
    10: [1697, 271, 702],
    20: [611, 572, 34],
    30: [38, 4, 4],
    40: [1, 180, 43],
    50: [1, 1, 1],
}

def P(s, i):
    return {'slot': i, 'slot_name': f's{i}', 'shape': s, 'rows': len(s), 'cols': len(s[0])}

def generate_board(fill, rng):
    b = np.zeros((8, 8), int)
    for k in rng.sample(range(64), fill):
        b[k // 8, k % 8] = 1
    for r in range(8):
        if b[r].sum() == 8:
            b[r, 0] = 0
    for c in range(8):
        if b[:, c].sum() == 8:
            b[0, c] = 0
    return b

def run_benchmark():
    print("=" * 78)
    print("🚀 BLOCKZI SOLVER BENCHMARK: BASELINE vs UPGRADE (solver-v2)")
    print(f"   Python {sys.version.split()[0]} | NumPy {np.__version__} | Seed 42")
    print("=" * 78)

    rng = random.Random(42)
    corpus = []
    for fill in [0, 10, 20, 30, 40, 50]:
        for t in range(3):
            b = generate_board(fill, rng)
            ps = [P(rng.choice(SHAPES), i) for i in range(3)]
            corpus.append((fill, t, b, ps))

    new_ex_times = []
    new_200_times = []
    all_scores_agree = []

    print(f"{'Fill':<5} {'Trial':<6} {'Old ms (Base)':<15} {'New Exh ms':<15} {'New 200ms':<12} {'Score Match'}")
    print("-" * 78)

    for fill, trial, b, ps in corpus:
        g = np.zeros((8, 8), int)

        # Baseline time from recorded baseline
        old_ms = BASELINE_MS[fill][trial]

        # 1. New exhaustive
        t0 = time.perf_counter()
        seq_ex, sc_ex, _ = S.solve_full_sequence(b, g, ps, max_ms=0)
        dt_ex = (time.perf_counter() - t0) * 1000.0
        new_ex_times.append(dt_ex)

        # 2. New anytime (max_ms=200)
        t0 = time.perf_counter()
        seq_200, sc_200, _ = S.solve_full_sequence(b, g, ps, max_ms=200)
        dt_200 = (time.perf_counter() - t0) * 1000.0
        new_200_times.append(dt_200)

        # Check score match between new exhaustive and new 200ms
        match = (sc_ex == sc_200)
        all_scores_agree.append(match)

        print(f"{fill:<5} {trial:<6} {old_ms:<15.0f} {dt_ex:<15.1f} {dt_200:<12.1f} {'YES' if match else 'Diff (bounded)'}")

    print("=" * 78)
    print("📊 LATENCY PERCENTILES (18 trials):")
    print(f"  Old Base:         p50 = {np.median([x for trials in BASELINE_MS.values() for x in trials]):.1f} ms | p95 = {np.percentile([x for trials in BASELINE_MS.values() for x in trials], 95):.1f} ms | max = {max([x for trials in BASELINE_MS.values() for x in trials]):.1f} ms")
    print(f"  New Exhaustive:   p50 = {np.median(new_ex_times):.1f} ms | p95 = {np.percentile(new_ex_times, 95):.1f} ms | max = {max(new_ex_times):.1f} ms")
    print(f"  New (max_ms=200): p50 = {np.median(new_200_times):.1f} ms | p95 = {np.percentile(new_200_times, 95):.1f} ms | max = {max(new_200_times):.1f} ms")
    print(f"  Score agreement rate (Exhaustive vs 200ms budget): {sum(all_scores_agree)/len(all_scores_agree)*100:.1f}%")

    print("\n" + "=" * 78)
    print("⚡ WORST CASE PROBE: Empty Board with 3x 1x1 Blocks")
    worst_ps = [P([[1]], i) for i in range(3)]
    empty_b = np.zeros((8, 8), int)
    empty_g = np.zeros((8, 8), int)

    t0 = time.perf_counter()
    seq, sc, _ = S.solve_full_sequence(empty_b, empty_g, worst_ps, max_ms=0)
    worst_ex = (time.perf_counter() - t0) * 1000.0
    print("  Old Base Exhaustive ms:       101,292 ms (~101 seconds)")
    print(f"  New solver-v2 Exhaustive ms:  {worst_ex:.1f} ms ({101292/worst_ex:.1f}x speedup)")

    for probe_ms in [100, 200, 800]:
        t0 = time.perf_counter()
        seq, sc, _ = S.solve_full_sequence(empty_b, empty_g, worst_ps, max_ms=probe_ms)
        actual_ms = (time.perf_counter() - t0) * 1000.0
        print(f"  max_ms={probe_ms:<3} -> actual wall time = {actual_ms:.2f} ms (timed_out={seq.timed_out}, seq_len={len(seq)})")
    print("=" * 78)

if __name__ == '__main__':
    run_benchmark()
