#!/usr/bin/env python3
"""
Offline Self-Play Simulator for Blockzi Evaluator Comparison (v1 vs v2)
Plays simulated games using seeded piece distributions and compares survival rate and scores.
"""

import argparse
import os
import random
import sys
from pathlib import Path
import numpy as np

repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root))
sys.path.insert(0, str(repo_root / "copilot"))

import solver as S

# Standard Blockzi shapes
SHAPES = [
    [[1]],                                  # 1x1 dot
    [[1, 1]],                               # 1x2 horizontal
    [[1], [1]],                             # 2x1 vertical
    [[1, 1, 1]],                            # 1x3 horizontal
    [[1], [1], [1]],                        # 3x1 vertical
    [[1, 1], [1, 1]],                       # 2x2 square
    [[1, 1, 1], [1, 1, 1], [1, 1, 1]],      # 3x3 square
    [[1, 1, 1, 1]],                         # 1x4 horizontal
    [[1], [1], [1], [1]],                   # 4x1 vertical
    [[1, 1, 1, 1, 1]],                      # 1x5 horizontal
    [[1], [1], [1], [1], [1]],              # 5x1 vertical
    [[1, 0], [1, 0], [1, 1]],               # L small
    [[0, 1, 0], [1, 1, 1]],                 # T piece
    [[1, 1, 0], [0, 1, 1]],                 # Z piece
]

def make_piece(shape, slot):
    return {
        'slot': slot,
        'slot_name': f'Slot {slot+1}',
        'shape': shape,
        'rows': len(shape),
        'cols': len(shape[0]),
    }


def simulate_game(seed, eval_mode, max_turns=100, max_ms=200):
    """Play a single simulated game with the given evaluator."""
    rng = random.Random(seed)
    board = np.zeros((8, 8), dtype=int)
    gems = np.zeros((8, 8), dtype=int)

    total_score = 0
    turns_survived = 0
    game_over = False

    # Temporarily set eval mode
    old_eval = os.environ.get("BLOCKZI_EVAL")
    os.environ["BLOCKZI_EVAL"] = eval_mode

    try:
        for turn in range(max_turns):
            # Deal 3 pieces
            pieces = [make_piece(rng.choice(SHAPES), i) for i in range(3)]
            seq, score, dt = S.solve_full_sequence(board, gems, pieces, max_ms=max_ms)

            if not seq:
                game_over = True
                break

            turns_survived += 1
            # Apply each step in sequence to board
            for step in seq:
                # The step dictionary provides board_after
                board = np.array(step['board_after'], dtype=int)
            total_score += score
    finally:
        if old_eval is not None:
            os.environ["BLOCKZI_EVAL"] = old_eval
        else:
            os.environ.pop("BLOCKZI_EVAL", None)

    return {
        'seed': seed,
        'turns': turns_survived,
        'score': total_score,
        'game_over': game_over,
    }


def run_benchmark(num_games=10, base_seed=42, max_turns=100, max_ms=200):
    print("=" * 72)
    print(f"🎮 Blockzi Self-Play Evaluation: v1 vs v2 ({num_games} games, seed {base_seed})")
    print(f"   Max turns per game: {max_turns}, Solver max_ms: {max_ms}")
    print("=" * 72)

    results_v1 = []
    results_v2 = []

    for i in range(num_games):
        seed = base_seed + i * 17
        r1 = simulate_game(seed, "v1", max_turns=max_turns, max_ms=max_ms)
        r2 = simulate_game(seed, "v2", max_turns=max_turns, max_ms=max_ms)
        results_v1.append(r1)
        results_v2.append(r2)
        print(f"Game {i+1:2d} (seed {seed}): v1={r1['turns']} turns ({r1['score']} pts), v2={r2['turns']} turns ({r2['score']} pts)")

    v1_turns = [r['turns'] for r in results_v1]
    v2_turns = [r['turns'] for r in results_v2]
    v1_scores = [r['score'] for r in results_v1]
    v2_scores = [r['score'] for r in results_v2]
    v1_go = sum(r['game_over'] for r in results_v1) / num_games * 100
    v2_go = sum(r['game_over'] for r in results_v2) / num_games * 100

    print("\n" + "=" * 72)
    print("📊 Summary Results:")
    print("Metric                 v1 (Legacy Base)     v2 (Spatial Heuristic)")
    print("-" * 72)
    print(f"Mean Turns Survived:   {np.mean(v1_turns):10.1f}           {np.mean(v2_turns):10.1f}")
    print(f"Median Turns:          {np.median(v1_turns):10.1f}           {np.median(v2_turns):10.1f}")
    print(f"Mean Score:            {np.mean(v1_scores):10.1f}           {np.mean(v2_scores):10.1f}")
    print(f"Median Score:          {np.median(v1_scores):10.1f}           {np.median(v2_scores):10.1f}")
    print(f"Game Over Rate:        {v1_go:9.1f}%           {v2_go:9.1f}%")
    print("=" * 72)

    return results_v1, results_v2


def main():
    parser = argparse.ArgumentParser(description="Blockzi self-play evaluator simulator")
    parser.add_argument("--seed", type=int, default=42, help="Base RNG seed")
    parser.add_argument("--games", type=int, default=10, help="Number of games to simulate")
    parser.add_argument("--max-turns", type=int, default=50, help="Maximum turns per game")
    parser.add_argument("--max-ms", type=int, default=150, help="Solver time budget per turn")
    args = parser.parse_args()

    run_benchmark(num_games=args.games, base_seed=args.seed, max_turns=args.max_turns, max_ms=args.max_ms)


if __name__ == "__main__":
    main()
