"""
tests/test_likert_reverse.py

Tests Likert scale reverse-coding logic and scoring.
"""

from survey_core.responses import Response, score_likert_scale


def test_score_likert_reverse_coding():
    """
    Test that reverse-coding a 1 on a 1-5 Likert scale produces (5 + 1) - 1 = 5.
    With q1 (val=1, reverse-coded -> 5) and q2 (val=4, normal -> 4),
    mean score must be (5 + 4) / 2 = 4.5.
    """
    responses = [
        Response(question_id="q1", raw_value=1),
        Response(question_id="q2", raw_value=4),
    ]
    mean_score = score_likert_scale(
        responses,
        question_ids=["q1", "q2"],
        reverse_coded=["q1"],
        max_value=5,
    )
    assert mean_score == 4.5, f"Expected mean 4.5, got {mean_score}"

