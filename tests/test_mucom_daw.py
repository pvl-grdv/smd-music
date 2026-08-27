from fractions import Fraction

from smd_music.muc_sequence import MucNote
from smd_music.mucom_daw import _note_gate_duration


def test_q_shortens_untied_note():
    n = MucNote('A', Fraction(0), Fraction(12), 60, 1, 10, 3, 3, 0)
    assert _note_gate_duration(n) == 9


def test_q_does_not_break_tie_segment():
    n = MucNote('A', Fraction(0), Fraction(12), 60, 1, 10, 3, 3, 0, tied_to_next=True)
    assert _note_gate_duration(n) == 12
