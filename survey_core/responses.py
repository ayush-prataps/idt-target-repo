"""
survey_core/responses.py

Core response-handling logic: parsing, validation, and scoring of survey responses.
Each function implements core domain rules for response handling.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Question:
    id: str
    text: str
    question_type: str        # "likert" | "text" | "multiple_choice" | "rating"
    required: bool = True
    choices: list[str] = None
    min_value: int = 1
    max_value: int = 5

    def __post_init__(self):
        if self.choices is None:
            self.choices = []


@dataclass
class Response:
    question_id: str
    raw_value: Any            # str, int, or list[str]
    respondent_id: str = ""


@dataclass
class ValidationError:
    question_id: str
    message: str


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_csv_row(row: dict[str, str], questions: list[Question]) -> list[Response]:
    """
    Turn a flat CSV row (column headers = question IDs) into a list of Response objects.
    Skips columns whose header doesn't match any known question ID.
    Multi-select answers are pipe-delimited: "Option A|Option B".
    """
    question_index = {q.id: q for q in questions}
    responses: list[Response] = []

    respondent_id = row.get("respondent_id", "")

    for col, raw in row.items():
        if col == "respondent_id":
            continue
        q = question_index.get(col)
        if q is None:
            continue

        if q.question_type == "multiple_choice" and "|" in raw:
            value: Any = [part.strip() for part in raw.split("|") if part.strip()]
        elif q.question_type in ("likert", "rating"):
            try:
                value = int(raw)
            except ValueError:
                value = raw   # keep as str — will fail validation downstream
            else:
                pass
        else:
            value = raw.strip()

        responses.append(Response(question_id=col, raw_value=value, respondent_id=respondent_id))

    return responses


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_response(response: Response, question: Question) -> list[ValidationError]:
    """
    Validate a single response against its question contract.
    Returns a (possibly empty) list of ValidationError.
    """
    errors: list[ValidationError] = []
    qid = response.question_id
    val = response.raw_value

    if question.required and (val is None or val == "" or val == []):
        errors.append(ValidationError(qid, "Required field is empty"))
        return errors   # no point checking further

    if question.question_type in ("likert", "rating"):
        if not isinstance(val, int):
            errors.append(ValidationError(qid, f"Expected integer, got {type(val).__name__}"))
        elif val < question.min_value or val > question.max_value:
            errors.append(ValidationError(
                qid,
                f"Value {val} out of range [{question.min_value}, {question.max_value}]",
            ))

    elif question.question_type == "multiple_choice":
        if not isinstance(val, list):
            errors.append(ValidationError(qid, "Expected list for multiple_choice"))
        else:
            invalid = [c for c in val if c not in question.choices]
            if invalid:
                errors.append(ValidationError(qid, f"Unknown choices: {invalid}"))

    elif question.question_type == "text":
        if not isinstance(val, str):
            errors.append(ValidationError(qid, "Expected string for text question"))
        elif len(val) > 5000:
            errors.append(ValidationError(qid, "Response exceeds 5000-character limit"))

    return errors


def validate_response_set(
    responses: list[Response],
    questions: list[Question],
) -> dict[str, list[ValidationError]]:
    """
    Validate a full set of responses for one respondent.
    Also checks that all required questions are answered (even if missing entirely).
    Returns a dict mapping question_id → [ValidationError].
    """
    question_index = {q.id: q for q in questions}
    answered_ids = {r.question_id for r in responses}
    errors_by_qid: dict[str, list[ValidationError]] = {}

    # Check for missing required questions
    for q in questions:
        if q.required and q.id not in answered_ids:
            errors_by_qid[q.id] = [ValidationError(q.id, "Required question not answered")]

    # Validate each provided response
    for r in responses:
        q = question_index.get(r.question_id)
        if q is None:
            continue   # unknown question — not an error, just skip
        errs = validate_response(r, q)
        if errs:
            errors_by_qid[r.question_id] = errs

    return errors_by_qid


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def score_likert_scale(
    responses: list[Response],
    question_ids: list[str],
    *,
    reverse_coded: list[str] | None = None,
    max_value: int = 5,
) -> float | None:
    """
    Compute a mean Likert-scale score across a subscale.

    Args:
        responses:     All responses for one respondent.
        question_ids:  The subset of question IDs forming this subscale.
        reverse_coded: Question IDs whose scale should be flipped before averaging.
        max_value:     Top of the scale (standard 5).

    Returns the mean score, or None if no valid numeric answers exist.
    Reverse-coding formula: flipped = (max_value + 1) - original.
    """
    reverse_coded_set = set(reverse_coded or [])
    resp_index = {r.question_id: r for r in responses}
    values: list[float] = []

    for qid in question_ids:
        r = resp_index.get(qid)
        if r is None or not isinstance(r.raw_value, int):
            continue
        v = float(r.raw_value)
        if qid in reverse_coded_set:
            v = max_value - v
        values.append(v)

    return statistics.mean(values) if values else None


def compute_nps(responses: list[Response], nps_question_id: str) -> dict[str, Any]:
    """
    Compute Net Promoter Score from a 0-10 rating question.

    Promoters:  9-10
    Passives:   7-8
    Detractors: 0-6
    NPS = %Promoters - %Detractors (range: -100 to +100)
    """
    values: list[int] = []
    for r in responses:
        if r.question_id == nps_question_id and isinstance(r.raw_value, int):
            values.append(r.raw_value)

    if not values:
        return {"nps": None, "promoters": 0, "passives": 0, "detractors": 0, "n": 0}

    n = len(values)
    promoters = sum(1 for v in values if v >= 9)
    passives   = sum(1 for v in values if 7 <= v <= 8)
    detractors = sum(1 for v in values if v <= 6)

    nps = round(((promoters - detractors) / n) * 100, 1)
    return {
        "nps": nps,
        "promoters": promoters,
        "passives": passives,
        "detractors": detractors,
        "n": n,
    }


# ---------------------------------------------------------------------------
# Text analysis helpers
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[a-zA-Z']+")


def word_frequency(text_responses: list[str], stop_words: set[str] | None = None) -> dict[str, int]:
    """
    Count word frequencies across a list of free-text responses.
    Lowercases, tokenises on word boundaries, and optionally removes stop words.
    """
    stop = stop_words or set()
    freq: dict[str, int] = {}

    for text in text_responses:
        for match in _WORD_RE.finditer(text.lower()):
            word = match.group()
            if word not in stop:
                freq[word] = freq.get(word, 0) + 1

    return dict(sorted(freq.items(), key=lambda kv: kv[1], reverse=True))


def summarise_numeric(values: list[int | float]) -> dict[str, Any]:
    """
    Return basic descriptive statistics for a list of numeric values.
    Returns an empty dict if the list is empty.
    """
    if not values:
        return {}

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    mean = statistics.mean(sorted_vals)
    median = statistics.median(sorted_vals)
    std = statistics.stdev(sorted_vals) if n > 1 else 0.0

    # Quartiles via linear interpolation
    def percentile(p: float) -> float:
        idx = (n - 1) * p
        lo, hi = int(idx), min(int(idx) + 1, n - 1)
        return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (idx - lo)

    return {
        "n": n,
        "mean": round(mean, 4),
        "median": median,
        "std": round(std, 4),
        "min": sorted_vals[0],
        "max": sorted_vals[-1],
        "q1": round(percentile(0.25), 4),
        "q3": round(percentile(0.75), 4),
    }

