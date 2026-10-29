# SurveyOps Core

A Python library for processing, validating, scoring, and aggregating survey responses.

## Overview

`survey_core` provides domain logic for:
- Response ingestion and parsing from CSV-style tabular data
- Schema and type validation for Likert, rating, multiple-choice, and text questions
- Scale scoring and subscale aggregation (Likert mean scores, reverse-coding, and Net Promoter Score calculations)
- Cross-tabulation, completion rate calculation, and word frequency summaries for free-text answers

## Project Structure

```
.
├── survey_core/          # Core survey processing and aggregation logic
│   ├── __init__.py
│   ├── responses.py      # Response models, validation, scoring
│   └── aggregation.py    # Cross-respondent aggregation and segmentation
├── tests/                # Test suite covering response parsing, validation, and analytics
├── scripts/              # CI utility scripts
│   └── ci_triage.py
├── requirements.txt
└── README.md
```

## Setup & Running Tests

### 1. Environment Setup

Create a virtual environment and install the required dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run Test Suite

Run all tests using `pytest`:

```bash
pytest tests -v
```

To run with structured JSON reporting:

```bash
pytest tests -v --json-report --json-report-file=pytest-report.json
```

