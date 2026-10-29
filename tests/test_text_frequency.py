"""
tests/test_text_frequency.py

Tests text response aggregation and word frequency analysis.
"""

from survey_core.responses import Question, Response
from survey_core.aggregation import aggregate_question


def test_aggregate_text_question_top_word_frequencies():
    """
    Test that word frequency aggregation includes the most frequent words.
    """
    q = Question(id="q_feedback", text="Feedback", question_type="text")
    responses = [
        [Response(question_id="q_feedback", raw_value="excellent dashboard excellent tool")]
    ]
    result = aggregate_question(q, responses)
    word_freq = result.get("word_freq", {})
    assert "excellent" in word_freq, (
        f"Expected 'excellent' to be included in word_freq, got {word_freq}"
    )
    assert word_freq["excellent"] == 2

