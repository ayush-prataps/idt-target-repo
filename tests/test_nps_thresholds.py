"""
tests/test_nps_thresholds.py

Tests Net Promoter Score category classification and thresholds.
"""

from survey_core.responses import Response, compute_nps


def test_nps_rating_seven_counted_as_passive():
    """
    Test that ratings of 7 and 8 are classified as passives (7 <= score <= 8).
    With scores [7, 8, 9], passives must equal 2 and promoters must equal 1.
    """
    responses = [
        Response(question_id="nps_q", raw_value=7),
        Response(question_id="nps_q", raw_value=8),
        Response(question_id="nps_q", raw_value=9),
    ]
    result = compute_nps(responses, "nps_q")
    assert result["passives"] == 2, (
        f"Expected 2 passives (scores 7 and 8), but got {result['passives']}"
    )

