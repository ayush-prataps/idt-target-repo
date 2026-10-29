"""
tests/test_responses.py

Tests for survey_core.responses — parsing, validation, and scoring.
"""

import sys
import os

# Allow running with  `python -m pytest`  from inside target repo
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from survey_core.responses import (
    Question,
    Response,
    parse_csv_row,
    validate_response,
    validate_response_set,
    score_likert_scale,
    compute_nps,
    word_frequency,
    summarise_numeric,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def likert_question():
    return Question(id="q1", text="Satisfaction", question_type="likert", min_value=1, max_value=5)


@pytest.fixture
def mc_question():
    return Question(
        id="q2",
        text="Preferred channel",
        question_type="multiple_choice",
        choices=["Email", "Phone", "Chat"],
    )


@pytest.fixture
def nps_question():
    return Question(id="q3", text="NPS", question_type="rating", min_value=0, max_value=10)


@pytest.fixture
def text_question():
    return Question(id="q4", text="Comments", question_type="text", required=False)


# ──────────────────────────────────────────────
# parse_csv_row
# ──────────────────────────────────────────────

class TestParseCsvRow:
    def test_likert_parsed_as_int(self, likert_question):
        row = {"respondent_id": "r1", "q1": "4"}
        responses = parse_csv_row(row, [likert_question])
        assert len(responses) == 1
        assert responses[0].raw_value == 4
        assert responses[0].respondent_id == "r1"

    def test_multiple_choice_pipe_split(self, mc_question):
        row = {"respondent_id": "r2", "q2": "Email|Chat"}
        responses = parse_csv_row(row, [mc_question])
        assert responses[0].raw_value == ["Email", "Chat"]

    def test_unknown_column_skipped(self, likert_question):
        row = {"respondent_id": "r3", "q1": "3", "unknown_col": "xyz"}
        responses = parse_csv_row(row, [likert_question])
        # Only q1 should produce a response; unknown_col is silently skipped
        assert len(responses) == 1

    def test_bad_int_kept_as_str(self, likert_question):
        row = {"respondent_id": "r4", "q1": "not_a_number"}
        responses = parse_csv_row(row, [likert_question])
        assert isinstance(responses[0].raw_value, str)


# ──────────────────────────────────────────────
# validate_response
# ──────────────────────────────────────────────

class TestValidateResponse:
    def test_valid_likert(self, likert_question):
        r = Response(question_id="q1", raw_value=3)
        assert validate_response(r, likert_question) == []

    def test_out_of_range_likert(self, likert_question):
        r = Response(question_id="q1", raw_value=6)
        errors = validate_response(r, likert_question)
        assert len(errors) == 1
        assert "out of range" in errors[0].message

    def test_invalid_type_likert(self, likert_question):
        r = Response(question_id="q1", raw_value="high")
        errors = validate_response(r, likert_question)
        assert any("integer" in e.message for e in errors)

    def test_valid_multiple_choice(self, mc_question):
        r = Response(question_id="q2", raw_value=["Email"])
        assert validate_response(r, mc_question) == []

    def test_unknown_choice(self, mc_question):
        r = Response(question_id="q2", raw_value=["Email", "Carrier Pigeon"])
        errors = validate_response(r, mc_question)
        assert any("Unknown choices" in e.message for e in errors)

    def test_required_empty_string(self, likert_question):
        r = Response(question_id="q1", raw_value="")
        errors = validate_response(r, likert_question)
        assert any("Required" in e.message for e in errors)

    def test_text_too_long(self, text_question):
        r = Response(question_id="q4", raw_value="x" * 5001)
        errors = validate_response(r, text_question)
        assert any("5000" in e.message for e in errors)


# ──────────────────────────────────────────────
# validate_response_set
# ──────────────────────────────────────────────

class TestValidateResponseSet:
    def test_missing_required_question_flagged(self, likert_question, mc_question):
        # mc_question is required by specification, but not answered
        responses = [Response(question_id="q1", raw_value=3)]
        errors = validate_response_set(responses, [likert_question, mc_question])
        assert "q2" in errors
        assert any("not answered" in e.message for e in errors["q2"])

    def test_all_valid_no_errors(self, likert_question, mc_question):
        responses = [
            Response(question_id="q1", raw_value=4),
            Response(question_id="q2", raw_value=["Phone"]),
        ]
        errors = validate_response_set(responses, [likert_question, mc_question])
        assert errors == {}


# ──────────────────────────────────────────────
# score_likert_scale
# ──────────────────────────────────────────────

class TestScoreLikertScale:
    def test_simple_mean(self):
        responses = [
            Response("q1", 4),
            Response("q2", 2),
        ]
        score = score_likert_scale(responses, ["q1", "q2"])
        assert score == pytest.approx(3.0)

    def test_reverse_coding(self):
        # q2=2 should be reverse-coded to (5+1)-2=4; mean of 4 and 4 = 4
        responses = [
            Response("q1", 4),
            Response("q2", 2),
        ]
        score = score_likert_scale(responses, ["q1", "q2"], reverse_coded=["q2"])
        assert score == pytest.approx(4.0)

    def test_missing_question_skipped(self):
        responses = [Response("q1", 5)]
        score = score_likert_scale(responses, ["q1", "q_missing"])
        assert score == pytest.approx(5.0)

    def test_all_missing_returns_none(self):
        score = score_likert_scale([], ["q1"])
        assert score is None


# ──────────────────────────────────────────────
# compute_nps
# ──────────────────────────────────────────────

class TestComputeNps:
    def _make_responses(self, scores: list[int]) -> list[Response]:
        return [Response("nps", v, respondent_id=str(i)) for i, v in enumerate(scores)]

    def test_all_promoters(self):
        result = compute_nps(self._make_responses([9, 10, 10]), "nps")
        assert result["nps"] == pytest.approx(100.0)
        assert result["promoters"] == 3

    def test_all_detractors(self):
        result = compute_nps(self._make_responses([0, 3, 6]), "nps")
        assert result["nps"] == pytest.approx(-100.0)

    def test_mixed(self):
        # 2 promoters, 1 passive, 1 detractor → (2-1)/4 * 100 = 25.0
        result = compute_nps(self._make_responses([10, 9, 7, 5]), "nps")
        assert result["nps"] == pytest.approx(25.0)
        assert result["n"] == 4

    def test_empty_returns_none(self):
        result = compute_nps([], "nps")
        assert result["nps"] is None


# ──────────────────────────────────────────────
# word_frequency
# ──────────────────────────────────────────────

class TestWordFrequency:
    def test_basic_count(self):
        freq = word_frequency(["good good bad"])
        assert freq["good"] == 2
        assert freq["bad"] == 1

    def test_stop_words_removed(self):
        freq = word_frequency(["the quick brown fox"], stop_words={"the"})
        assert "the" not in freq

    def test_case_insensitive(self):
        freq = word_frequency(["Great great GREAT"])
        assert freq["great"] == 3

    def test_empty_input(self):
        assert word_frequency([]) == {}


# ──────────────────────────────────────────────
# summarise_numeric
# ──────────────────────────────────────────────

class TestSummariseNumeric:
    def test_empty_returns_empty(self):
        assert summarise_numeric([]) == {}

    def test_single_value(self):
        result = summarise_numeric([7])
        assert result["mean"] == 7
        assert result["std"] == 0.0

    def test_known_stats(self):
        result = summarise_numeric([1, 2, 3, 4, 5])
        assert result["mean"] == pytest.approx(3.0)
        assert result["median"] == 3
        assert result["min"] == 1
        assert result["max"] == 5
        assert result["n"] == 5

