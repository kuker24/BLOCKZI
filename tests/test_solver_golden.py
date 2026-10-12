import json
from pathlib import Path
import numpy as np
import pytest

import sys
repo_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(repo_root / 'copilot'))
import solver as S

GOLDEN_PATH = Path(__file__).resolve().parent / 'golden' / 'solver_v1.json'

def load_golden():
    with open(GOLDEN_PATH) as f:
        return json.load(f)

@pytest.mark.parametrize('case', load_golden(), ids=lambda c: c['id'])
def test_solver_golden_score(case):
    board = np.array(case['board'], dtype=int)
    gems = np.array(case['gems'], dtype=int)
    pieces = case['pieces']
    expected_score = case['expected_score']

    seq, score, ms = S.solve_full_sequence(board, gems, pieces)

    # In exhaustive mode, score must match golden score
    assert score == expected_score, (
        f"Case {case['id']}: expected score {expected_score}, got {score}"
    )
    if case['expected_seq_len'] > 0:
        assert len(seq) > 0, f"Case {case['id']}: expected non-empty seq"
