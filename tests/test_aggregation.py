"""
tests/test_aggregation.py

Tests for survey_core.aggregation.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from survey_core.responses import Question, Response
from survey_core.aggregation import (
    aggregate_question,
    aggregate_survey,
    cross_tab,
    completion_rate,
)


@pytest.fixture
def likert_q():
    return Question(id="sat", text="Satisfaction", question_type="likert", min_value=1, max_value=5)


@pytest.fixture
def dept_q():
    return Question(
        id="dept",
        text="Department",
        question_type="multiple_choice",
        choices=["Engineering", "Sales", "Support"],
    )


@pytest.fixture
def text_q():
    return Question(id="comment", text="Comments", question_type="text", required=False)


def make_resp(qid: str, val) -> Response:
    return Response(question_id=qid, raw_value=val)


class TestAggregateQuestion:
    def test_likert_mean(self, likert_q):
        all_resps = [[make_resp("sat", 4)], [make_resp("sat", 2)], [make_resp("sat", 3)]]
        result = aggregate_question(likert_q, all_resps)
        assert result["mean"] == pytest.approx(3.0)
        assert result["n"] == 3

    def test_multiple_choice_counts(self, dept_q):
        all_resps = [
            [make_resp("dept", ["Engineering"])],
            [make_resp("dept", ["Sales"])],
            [make_resp("dept", ["Engineering"])],
        ]
        result = aggregate_question(dept_q, all_resps)
        assert result["counts"]["Engineering"] == 2
        assert result["counts"]["Sales"] == 1

    def test_text_word_freq(self, text_q):
        all_resps = [
            [make_resp("comment", "great service")],
            [make_resp("comment", "great product")],
        ]
        result = aggregate_question(text_q, all_resps)
        assert result["word_freq"]["great"] == 2


class TestCompletionRate:
    def test_full_completion(self, likert_q):
        all_resps = [
            [make_resp("sat", 5)],
            [make_resp("sat", 3)],
        ]
        rates = completion_rate([likert_q], all_resps)
        assert rates["sat"] == pytest.approx(1.0)

    def test_partial_completion(self, likert_q):
        # Only first respondent answered
        all_resps = [
            [make_resp("sat", 4)],
            [],   # no response
        ]
        rates = completion_rate([likert_q], all_resps)
        assert rates["sat"] == pytest.approx(0.5)

    def test_empty_respondents(self, likert_q):
        assert completion_rate([likert_q], []) == {}


class TestCrossTab:
    def test_segment_breakdown(self, likert_q, dept_q):
        all_resps = [
            [make_resp("sat", 5), make_resp("dept", ["Engineering"])],
            [make_resp("sat", 3), make_resp("dept", ["Sales"])],
            [make_resp("sat", 4), make_resp("dept", ["Engineering"])],
        ]
        result = cross_tab(likert_q, dept_q, all_resps)
        eng = result["['Engineering']"]
        assert eng["mean"] == pytest.approx(4.5)

