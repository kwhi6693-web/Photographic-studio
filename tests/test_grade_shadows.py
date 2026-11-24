import numpy as np
import pytest

from grade import black_anchor
from pipeline import final_verdict, gate_notes


def test_shadows_only_mode_leaves_darkening_to_harmonize():
    reference = np.broadcast_to(np.linspace(10, 80, 96, dtype=np.float32), (96, 96)).copy()
    brighter = reference + 1.0
    darker = reference - 6.0

    protected, _ = black_anchor(True, brighter, reference, *reference.shape, allow_down=False)
    assert np.array_equal(protected, brighter)
    default, _ = black_anchor(True, brighter, reference, *reference.shape)
    assert np.any(default < brighter)

    lifted, _ = black_anchor(True, darker, reference, *reference.shape, allow_down=False)
    default_lifted, _ = black_anchor(True, darker, reference, *reference.shape)
    assert np.any(lifted > darker)
    assert np.array_equal(lifted, default_lifted)


@pytest.mark.parametrize('checks,verdict', [
    ({'physics': 'PHYSICALLY_PLAUSIBLE', 'failed_physics': []}, 'DELIVER_WITH_FLAGS: colour_order'),
    ({'physics': 'CHECK_BY_EYE: ghost_edges', 'failed_physics': ['ghost_edges']}, 'STOP_PHYSICS: ghost_edges'),
    ({'physics': 'TOOL_ERROR', 'failed_physics': None}, 'STOP_PHYSICS: missing or inconclusive check'),
])
def test_receipt_distinguishes_gate_tips_and_physics_failures(checks, verdict):
    gates = {'verdict': 'GATES_FAIL: colour_order', 'failed': ['colour_order']}
    assert final_verdict(gates, checks, 'DELIVER') == verdict
    assert gate_notes({'steps': [gates]}) == {
        'steps': [{'verdict': 'GATES_FLAGS: colour_order', 'failed': ['colour_order']}]
    }
    assert gates['verdict'] == 'GATES_FAIL: colour_order'
