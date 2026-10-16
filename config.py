"""
Settings and methodology choices. Anything that changes a score is set here,
not buried in the scoring code.
"""
import os
from pathlib import Path

ROOT = Path(__file__).parent
DATA_DIR = ROOT / "data"
TRANSCRIPT_DIR = DATA_DIR / "transcripts"
ACTUALS_PATH = DATA_DIR / "actuals.csv"
GOLD_PATH = DATA_DIR / "gold_guidance.json"
LLM_OUTPUT_PATH = DATA_DIR / "llm_guidance.json"
OUTPUT_DIR = ROOT / "outputs"

# The only metrics we know how to score. The LLM is told to use exactly these
# names. Without a fixed vocabulary, matching "topline growth" in a transcript
# to "revenue_growth_yoy_pct" in the results table becomes fuzzy guesswork.
METRICS = {
    "revenue_growth_yoy_pct": "Revenue growth, year on year, percent (constant currency is fine)",
    "ebit_margin_pct": "EBIT margin, percent",
    "ebitda_margin_pct": "EBITDA margin, percent",
    "loan_growth_yoy_pct": "Bank loan book growth, year on year, percent",
    "gross_npa_pct": "Gross non-performing assets ratio, percent",
    "nim_pct": "Net interest margin, percent",
    "volume_growth_yoy_pct": "Unit sales volume growth, year on year, percent",
    "capacity_utilization_pct": "Plant capacity utilization, percent",
}

# For these metrics a lower number is the good outcome. This only matters for
# the "gap vs target" number, not for whether a promise was kept.
LOWER_IS_BETTER = {"gross_npa_pct"}

# How close a "point" target ("around 15 percent") has to land to count as kept,
# in percentage points. Bank ratios move in small steps, so they get a tighter
# band. Utilization swings a lot quarter to quarter, so it gets a wider one.
DEFAULT_POINT_TOLERANCE_PP = 0.5
POINT_TOLERANCE_PP = {
    "nim_pct": 0.1,
    "gross_npa_pct": 0.1,
    "capacity_utilization_pct": 2.0,
}

# LLM settings. Model, effort and prices can be overridden with environment variables.
MODEL = os.getenv("SAYDO_MODEL", "claude-sonnet-5-5")
# Pulling a few sentences into a fixed schema is not hard reasoning, so low
# effort keeps latency and cost down. Worth re-checking against the eval if
# field accuracy turns out to be the weak spot.
EFFORT = os.getenv("SAYDO_EFFORT", "low")
# USD per million tokens (Sonnet 5.5 list price as of Oct 2026). Only used to
# estimate cost in the evaluation report, so update if you change the model.
INPUT_PRICE_PER_MTOK = float(os.getenv("SAYDO_INPUT_PRICE", "2.0"))
OUTPUT_PRICE_PER_MTOK = float(os.getenv("SAYDO_OUTPUT_PRICE", "10.0"))
