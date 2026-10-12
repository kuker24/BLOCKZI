import sys, time, random, itertools, cProfile, pstats, io
from pathlib import Path
import numpy as np

# Ensure copilot is importable
repo_root = Path(__file__).resolve().parent.parent
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

def P(s, i):
    return {'slot': i, 'slot_name': f's{i}', 'shape': s, 'rows': len(s), 'cols': len(s[0])}

def board(fill, rng):
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

rng = random.Random(42)

# bitboard solver for comparison
FULLR = [0xFF << (8 * r) for r in range(8)]
FULLC = [sum(1 << (8 * r + c) for r in range(8)) for c in range(8)]

def masks(p):
    out = []
    for r in range(9 - p['rows']):
        for c in range(9 - p['cols']):
            m = 0
            for dr, row in enumerate(p['shape']):
                for dc, v in enumerate(row):
                    if v:
                        m |= 1 << (8 * (r + dr) + c + dc)
            out.append((r, c, m))
    return out

def step(b, m):
    nb = b | m
    cl = 0
    clr = 0
    for f in FULLR:
        if nb & f == f:
            clr |= f
            cl += 1
    for f in FULLC:
        if nb & f == f:
            clr |= f
            cl += 1
    return nb & ~clr, cl

def holes(b):
    e = ~b & ((1 << 64) - 1)
    h = 0
    while e:
        i = (e & -e).bit_length() - 1
        e &= e - 1
        r, c = divmod(i, 8)
        n = 0
        if r > 0 and (b >> (i - 8) & 1):
            n += 1
        if r < 7 and (b >> (i + 8) & 1):
            n += 1
        if c > 0 and (b >> (i - 1) & 1):
            n += 1
        if c < 7 and (b >> (i + 1) & 1):
            n += 1
        h += n >= 3
    return h

def bb_solve(b0, pieces):
    b = sum(1 << (8 * r + c) for r in range(8) for c in range(8) if b0[r, c])
    M = [masks(p) for p in pieces]
    best = -1e9
    seen = set()
    for perm in itertools.permutations(range(3)):
        key = tuple(str(pieces[i]['shape']) for i in perm)
        if key in seen:
            continue
        seen.add(key)
        for _, _, m0 in M[perm[0]]:
            if b & m0:
                continue
            b1, c0 = step(b, m0)
            for _, _, m1 in M[perm[1]]:
                if b1 & m1:
                    continue
                b2, c1 = step(b1, m1)
                for _, _, m2 in M[perm[2]]:
                    if b2 & m2:
                        continue
                    b3, c2 = step(b2, m2)
                    s = (c0 + c1 + c2) * 1500 - bin(b3).count('1') * 15 - holes(b3) * 35
                    if s > best:
                        best = s
    return best

if __name__ == '__main__':
    print("fill  orig_ms(trials)  bitboard_ms  same_score_no_gems")
    for fill in [0, 10, 20, 30, 40, 50]:
        to = []
        tb = []
        agree = True
        for t in range(3):
            b = board(fill, rng)
            ps = [P(rng.choice(SHAPES), i) for i in range(3)]
            g = np.zeros((8, 8), int)
            t0 = time.perf_counter()
            seq, sc, _ = S.solve_full_sequence(b, g, ps)
            to.append((time.perf_counter() - t0) * 1000)
            t0 = time.perf_counter()
            sb = bb_solve(b, ps)
            tb.append((time.perf_counter() - t0) * 1000)
            if seq and len(seq) == 3 and sb != sc:
                agree = False
        print(f"{fill:2d}  {[round(x) for x in to]}  {[round(x, 1) for x in tb]}  {agree}")

    # worst case: empty board, three 1x1
    ps = [P([[1]], i) for i in range(3)]
    b = np.zeros((8, 8), int)
    t0 = time.perf_counter()
    S.solve_full_sequence(b, np.zeros((8, 8), int), ps)
    print("worst 3x1x1 empty orig ms:", round((time.perf_counter() - t0) * 1000))
    t0 = time.perf_counter()
    bb_solve(b, ps)
    print("worst bitboard ms (dedup perms):", round((time.perf_counter() - t0) * 1000))

    # deadline probe
    for ms in [100, 800]:
        t0 = time.perf_counter()
        S.solve_full_sequence(b, np.zeros((8, 8), int), ps, max_ms=ms)
        print(f"max_ms={ms} actual ms:", round((time.perf_counter() - t0) * 1000))

    pr = cProfile.Profile()
    pr.enable()
    S.solve_full_sequence(
        board(20, rng),
        np.zeros((8, 8), int),
        [P(SHAPES[1], 0), P(SHAPES[3], 1), P(SHAPES[4], 2)]
    )
    pr.disable()
    s = io.StringIO()
    pstats.Stats(pr, stream=s).sort_stats('tottime').print_stats(6)
    print(s.getvalue()[:2500])
