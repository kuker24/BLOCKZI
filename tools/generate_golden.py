import json
import random
from pathlib import Path
import numpy as np

import sys
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / 'copilot'))
import solver_legacy as legacy

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

def P(s, i):
    return {'slot': i, 'slot_name': f's{i}', 'shape': s, 'rows': len(s), 'cols': len(s[0])}

def make_board(fill, rng):
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

def make_gems(b, count, rng):
    g = np.zeros((8, 8), int)
    # Gems are placed on filled cells
    filled_indices = [k for k in range(64) if b[k // 8, k % 8] == 1]
    if filled_indices and count > 0:
        sample_count = min(count, len(filled_indices))
        for k in rng.sample(filled_indices, sample_count):
            g[k // 8, k % 8] = 1
    return g

def main():
    rng = random.Random(42)
    cases = []
    case_id = 0

    # 1. Fill levels 10, 20, 30, 40, 50 (fast) - 2 trials each
    for fill in [10, 20, 30, 40, 50]:
        for trial in range(2):
            case_id += 1
            b = make_board(fill, rng)
            g = np.zeros((8, 8), int)
            ps = [P(rng.choice(SHAPES), i) for i in range(3)]
            seq, score, ms = legacy.solve_full_sequence(b, g, ps)
            def to_builtin(obj):
                if isinstance(obj, (np.integer, np.int64, np.int32)):
                    return int(obj)
                if isinstance(obj, (np.floating, np.float64, np.float32)):
                    return float(obj)
                if isinstance(obj, np.ndarray):
                    return obj.tolist()
                if isinstance(obj, list):
                    return [to_builtin(x) for x in obj]
                if isinstance(obj, dict):
                    return {k: to_builtin(v) for k, v in obj.items()}
                return obj

            cases.append({
                'id': f'fill_{fill}_trial_{trial}',
                'fill': fill,
                'board': b.tolist(),
                'gems': g.tolist(),
                'pieces': ps,
                'expected_score': int(score),
                'expected_seq_len': len(seq),
                'seq': to_builtin(seq),
            })
            print(f"Generated case {case_id}: fill {fill} trial {trial} -> score {score}, seq_len {len(seq)}")

    # 2. Variants with gems (fill 20, 30, 40 with gems)
    for fill in [20, 30, 40]:
        for gem_count in [3, 6]:
            case_id += 1
            b = make_board(fill, rng)
            g = make_gems(b, gem_count, rng)
            ps = [P(rng.choice(SHAPES), i) for i in range(3)]
            seq, score, ms = legacy.solve_full_sequence(b, g, ps)
            cases.append({
                'id': f'gem_fill_{fill}_gems_{gem_count}',
                'fill': fill,
                'board': b.tolist(),
                'gems': g.tolist(),
                'pieces': ps,
                'expected_score': int(score),
                'expected_seq_len': len(seq),
                'seq': to_builtin(seq),
            })
            print(f"Generated case {case_id}: fill {fill} gems {gem_count} -> score {score}, seq_len {len(seq)}")

    # 3. One fill 0 trial with non-tiny pieces so it doesn't take 100 seconds
    case_id += 1
    b = np.zeros((8, 8), int)
    g = np.zeros((8, 8), int)
    # Use larger shapes: 3x3, 2x2, 1x5
    ps = [P(SHAPES[5], 0), P(SHAPES[4], 1), P(SHAPES[6], 2)]
    seq, score, ms = legacy.solve_full_sequence(b, g, ps)
    cases.append({
        'id': 'fill_0_large_shapes',
        'fill': 0,
        'board': b.tolist(),
        'gems': g.tolist(),
        'pieces': ps,
        'expected_score': int(score),
        'expected_seq_len': len(seq),
        'seq': to_builtin(seq),
    })
    print(f"Generated case {case_id}: fill 0 large shapes -> score {score}, seq_len {len(seq)}")

    out_file = repo_root / 'tests' / 'golden' / 'solver_v1.json'
    with open(out_file, 'w') as f:
        json.dump(cases, f, indent=2)
    print(f"Saved {len(cases)} golden test cases to {out_file}")

if __name__ == '__main__':
    main()
