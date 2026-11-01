"""
survey_core/aggregation.py

Aggregates responses across many respondents into per-question summaries
and cross-tab breakdowns.
"""

from __future__ import annotations

from typing import Any

from .responses import Question, Response, summarise_numeric, word_frequency


# ---------------------------------------------------------------------------
# Per-question aggregation
# ---------------------------------------------------------------------------

def aggregate_question(
    question: Question,
    all_responses: list[list[Response]],
) -> dict[str, Any]:
    """
    Aggregate all respondents' answers to a single question.

    Returns a summary dict whose shape depends on question type:
    - likert/rating  → descriptive stats (n, mean, median, std, q1, q3)
    - multiple_choice → {choice: count, choice: count, ...}
    - text           → top-30 word frequencies (stop words removed)
    """
    # Gather raw values for this question across all response sets
    values: list[Any] = []
    for resp_set in all_responses:
        for r in resp_set:
            if r.question_id == question.id:
                values.append(r.raw_value)

    if question.question_type in ("likert", "rating"):
        numeric = [v for v in values if isinstance(v, int)]
        return {"type": question.question_type, **summarise_numeric(numeric)}

    elif question.question_type == "multiple_choice":
        counts: dict[str, int] = {c: 0 for c in question.choices}
        for v in values:
            if isinstance(v, list):
                for choice in v:
                    if choice in counts:
                        counts[choice] += 1
            elif isinstance(v, str) and v in counts:
                counts[v] += 1
        return {"type": "multiple_choice", "counts": counts, "n_respondents": len(values)}

    elif question.question_type == "text":
        _STOP = {
            "the", "a", "an", "and", "or", "but", "in", "on", "at",
            "to", "for", "of", "with", "is", "it", "was", "i", "my",
            "this", "that", "are", "be", "have", "had", "not", "no",
        }
        texts = [v for v in values if isinstance(v, str)]
        freq = word_frequency(texts, stop_words=_STOP)
        top30 = dict(list(freq.items())[:30])
        return {"type": "text", "n_responses": len(texts), "word_freq": top30}

    return {"type": question.question_type, "n": len(values)}


def aggregate_survey(
    questions: list[Question],
    all_responses: list[list[Response]],
) -> dict[str, dict[str, Any]]:
    """
    Aggregate all questions in a survey.
    Returns a dict mapping question_id → aggregated summary.
    """
    return {q.id: aggregate_question(q, all_responses) for q in questions}


# ---------------------------------------------------------------------------
# Cross-tab / segmentation
# ---------------------------------------------------------------------------

def cross_tab(
    target_question: Question,
    segment_question: Question,
    all_responses: list[list[Response]],
) -> dict[str, dict[str, Any]]:
    """
    Group respondents by their answer to `segment_question`, then
    aggregate `target_question` within each segment.

    Useful for: "How does satisfaction (Likert) break down by department (MC)?"

    Returns:
        {segment_value: aggregated_target_summary, ...}
    """
    # Build per-respondent maps: respondent index → {qid: raw_value}
    by_segment: dict[str, list[list[Response]]] = {}

    for resp_set in all_responses:
        segment_val: str | None = None
        for r in resp_set:
            if r.question_id == segment_question.id:
                segment_val = str(r.raw_value)
                break
        if segment_val is None:
            continue
        if segment_val not in by_segment:
            by_segment[segment_val] = []
        by_segment[segment_val].append(resp_set)

    result: dict[str, dict[str, Any]] = {}
    for seg_val, group_responses in by_segment.items():
        result[seg_val] = aggregate_question(target_question, group_responses)

    return result


# ---------------------------------------------------------------------------
# Completion rate
# ---------------------------------------------------------------------------

def completion_rate(
    questions: list[Question],
    all_responses: list[list[Response]],
) -> dict[str, float]:
    """
    For each required question, compute the fraction of respondents who
    provided a non-empty answer.

    Returns {question_id: rate} where rate ∈ [0.0, 1.0].
    """
    n_respondents = len(all_responses)
    if n_respondents == 0:
        return {}

    required = [q for q in questions if q.required]
    rates: dict[str, float] = {}

    for q in required:
        answered = 0
        for resp_set in all_responses:
            for r in resp_set:
                if r.question_id == q.id:
                    val = r.raw_value
                    if val is not None and val != "" and val != []:
                        answered += 1
                    break
        rates[q.id] = answered / n_respondents

    return rates
