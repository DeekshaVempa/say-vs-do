# Say vs Do: management credibility score

When a management team gives guidance on an earnings call, how often do they actually hit it?

This prototype reads earnings call transcripts, pulls out the forward-looking numbers management committed to, checks each one against what the company later reported, and rolls that up into a credibility score per company. Every promise in the output links back to the exact quote, the call it was made on, and the reported figure it was judged against.

![Credibility chart](outputs/credibility_chart.png)

## The problem

Guidance moves stock prices, but there is no easy way to see whether a particular management team has a habit of over-promising. Right now an analyst would have to reread a year of transcripts and line them up against results by hand.

Who I had in mind:

- A retail user on Spectra asking "has Deccan Motors management been reliable on guidance?" and getting an answer with the quotes and dates attached.
- An institutional user on the Dashboard screening for companies that consistently guide low and beat, or the reverse.

Why this for Prism: "management guidance tracked against actual delivery" is already on Prism's list of company data, and building it needs both of the things Prism is working on. There's an LLM step that turns unstructured text into structured records, and a transparent quantitative layer on top of that. It's also a good test of the trust rule. If a number can't be traced back to a document, it shouldn't be shown.

## How it works

```
transcripts ──> extract guidance ──> verify quote ──> match to reported result ──> score ──> report
                (Claude, or my       (drop anything    (actuals.csv)                         (HTML, CSV, chart)
                 hand labels)         not in the text)
```

**1. Extract.** Each transcript goes to Claude with a fixed list of 8 metrics and a fixed output schema. A promise comes back like this:

```json
{
  "quote": "gross NPA should come down below 2.5 percent by end of Q2",
  "metric": "gross_npa_pct",
  "type": "at_most",
  "high": 2.5,
  "target_period": "Q2FY26"
}
```

**2. Verify.** The quote has to appear word for word in the transcript (ignoring case and whitespace). If it doesn't, the record is marked `unverified_quote` and is never scored. It's a crude check, but it catches the failure I'm most worried about, which is the model inventing guidance. Records that are missing a number or a target period are marked `incomplete` instead of being guessed at.

**3. Judge each promise** against the reported number for the period it was about:

| Guidance type | Example | Kept when |
|---|---|---|
| range | "6 to 8 percent" | actual is inside the range |
| at_least | "at least 21 percent" | actual >= target |
| at_most | "below 2.5 percent" | actual <= target |
| point | "around 15 percent" | actual within a tolerance (0.5pp default, 0.1pp for NIM and NPA, 2pp for utilization) |
| direction | "margins will improve from Q2" | actual moved the promised way vs the reference period |
| vague | "the EV platform will be a game changer" | not scored, but counted |

**4. Roll up per company.**

- `raw_score` is kept / scored.
- `credibility_score` is (kept + 1) / (scored + 2), which is Laplace smoothing. With five or six promises per company, a team that kept 1 of 1 shouldn't rank alongside one that kept 6 of 6, so small samples get pulled toward 50%.
- `avg_gap_pp` is the average distance between the reported number and the promised target, in percentage points. Positive means the company tends to beat its own guidance. For gross NPA, where lower is better, the sign is flipped. Direction promises have no numeric target, so they're left out of this.

The tolerances, the lower-is-better list and the metric list are all in `config.py`, so changing a methodology choice doesn't mean digging through the scoring code.

## Results

12 synthetic transcripts (4 companies, Q1 to Q3 FY26 calls), scored against FY26 reported results:

| Company | Kept | Raw score | Credibility | Avg gap vs target |
|---|---|---|---|---|
| Aravali Infotech | 6 of 6 | 1.00 | 0.88 | +0.22 pp |
| Sahyadri Cement | 3 of 5 | 0.60 | 0.57 | -1.10 pp |
| Konkan Bank | 3 of 6 | 0.50 | 0.50 | -0.46 pp |
| Deccan Motors | 1 of 6 | 0.17 | 0.25 | -3.20 pp |

What I'd take from it:

- Aravali hit all six of its measurable targets, and narrowed its revenue range as the year went on, not the other way round.
- Deccan Motors missed 5 of 6, three of them by more than 3 points. It also kept restating volume targets it was nowhere near: at least 12% for FY26 in July, 15 to 18% for Q3 in October, still at least 10% for FY26 in January. Q3 came in at 11.2% and FY26 at 6.8%.
- Konkan's 0.50 hides a split. It missed both NIM targets and its original 16 to 18% loan growth range, but kept every asset-quality promise. A per-metric view would make that obvious, and it's the first thing I'd add.
- One of Sahyadri's misses is arguably good news. Management said Q4 margin would be lower than Q3 because of fuel costs, and it came in higher (19.4% to 19.9%). The forecast was wrong, so I think counting it as a miss is right for a credibility score, but the report should probably call it out.

A Spectra-style answer this data could back up:

> Deccan Motors management has kept 1 of 6 measurable promises across its last three earnings calls. On the Q1 FY26 call (28 July 2025) the CFO guided FY26 volume growth of "at least 12 percent". Reported FY26 volume growth was 6.8%. The one promise kept was that Q3 EBITDA margin would improve on Q2 (said on the Q2 call, 27 October 2025), which it did: 11.6% to 11.9%. Sources: Q1 to Q3 FY26 call transcripts, Q2 and Q3 FY26 results releases, FY26 annual results.

Everything is in `outputs/`:

- `report.html`: the scoreboard plus every promise with its quote, call date, source file, target, reported number and verdict. Open it in a browser.
- `scoreboard.csv`: one row per company
- `scored_guidance.csv`: one row per promise
- `credibility_chart.png`: the chart at the top

## The LLM step and how to evaluate it

The scores above come from 28 statements I labeled by hand (`data/gold_guidance.json`). Those same labels are the test set for the LLM extraction, so "is the extraction good enough to trust?" gets answered with numbers.

`python run.py --use-llm` runs Claude over all 12 transcripts, scores the LLM's records instead of the hand labels, and writes `outputs/extraction_eval.json` with:

- recall and precision against the hand labels (did it miss promises, did it make any up)
- accuracy per field (metric, type, period, numbers, direction), so you can see which part the model gets wrong
- the share of quotes that actually appear in the transcript
- JSON parse failures and truncated responses
- each company's credibility score from the LLM records next to the score from the hand labels. This is the one I care about most, since it's what a user would actually see.
- average latency per transcript, total tokens, and estimated cost

### Results from a live run (Claude Sonnet 5.5, low effort)

| | |
|---|---|
| Statements found (recall) | 28 of 28 |
| Precision | 0.93 (2 extra records, see below) |
| Records correct on every field | 26 of 28 |
| Quotes found word for word in the transcript | 30 of 30 |
| JSON parse failures / truncated responses | 0 / 0 |
| Average latency | 2.2 s per transcript |
| Cost for all 12 transcripts | about $0.05 (11.5K input, 3.1K output tokens) |

| Company | Score from hand labels | Score from LLM |
|---|---|---|
| Aravali Infotech | 0.88 | 0.88 |
| Sahyadri Cement | 0.57 | 0.57 |
| Konkan Bank | 0.50 | 0.50 |
| Deccan Motors | 0.25 | 0.14 |

The full numbers are in `outputs/extraction_eval.json` and the model's records are in `data/llm_guidance.json`.

What went wrong, and what I take from it:

- **One ambiguous word moved a score by 11 points.** Deccan's CFO said "Margins will improve in Q3 from Q2 levels". I labeled that as EBITDA margin, since that's the only margin Deccan guides on. The model called it vague because the sentence doesn't say which margin. Both readings are defensible, but it removed Deccan's one kept promise, taking it from 1 of 6 to 0 of 5 (0.25 to 0.14). With this few promises per company, every labeling call matters. The fix I'd try first is giving the model the metrics each company has guided on before, so a bare "margins" can be resolved, and flagging it for review when it can't.
- **The two extra records aren't hallucinations.** "We believe deposit costs have peaked" (Konkan) and "We are also evaluating a few acquisition targets in the east" (Sahyadri) are real forward-looking statements that I didn't label. Both are vague, so neither affects a score. The 0.93 precision is really a disagreement about what counts as guidance, and that's a labeling rule I should write down.
- On one vague statement the model turned "next year" into FY27. Harmless, since vague statements aren't scored.
- The model usually quotes the whole sentence, including the reason ("...because of higher fuel costs", "Wage hikes are deferred to Q3 this year, so..."). The matcher handles it, and it's useful: the reason management gave is exactly what you'd want to show next to a miss.

On reproducibility: Sonnet 5.5 doesn't accept a temperature setting, so I can't force identical output. I ran the extraction twice to check. Both runs returned the same 30 records, 29 matched on every field, and the only one that changed was the same ambiguous "margins" sentence (vague both times). All four company scores were identical across the two runs. After extraction, everything is plain, unit-tested Python, so the model never does the math.

## Data and assumptions

- **All companies, transcripts and results are made up.** I designed them to show three management styles (conservative, mixed, over-promising), and I didn't want to put invented quotes in the mouths of real Indian companies. Real data works without code changes: drop transcripts into `data/transcripts/` with the same header and add rows to `data/actuals.csv`.
- Indian fiscal year: Q1FY26 is April to June 2025, and FY26 ends March 2026.
- Only management statements count, not analyst questions.
- Each promise is judged against the first reported number for its period. Restatements are ignored.
- Every promise has equal weight, and it's either kept or missed, with no partial credit. The gap number carries the "by how much".

## Limitations

- Sample size. Five or six promises per company is enough to show the idea, not to judge a management team. Smoothing helps but doesn't fix it.
- Vague guidance isn't scored, so a team that never commits to a number can never miss. The report counts vague statements so it's visible, but a team that's always vague probably deserves a lower score, not a neutral one.
- Repeated guidance counts more than once. Aravali's FY26 revenue guide shows up on all three calls (6 to 8%, then 7 to 8%, then around 7.5%) and gets scored three times against the same 7.4%. Deccan's FY26 volume miss is counted twice the same way. Whether a reiterated target should count once or every time is a real methodology question. I kept it simple for now.
- Beating a cautious guide counts as a miss, as with Sahyadri above.
- Not all misses are equal. Missing because of an unusual monsoon is different from a plan that was never realistic, and the score can't tell them apart.
- The gap average mixes metrics. A 1pp miss on NIM is a much bigger deal than a 1pp miss on loan growth. Fine as a rough signal, not for ranking.
- Look-ahead. The score is computed as of today, and promises from the Q3 call are judged on Q4 results. A historical score would have to include only promises whose target period had been reported by that date, which means `actuals.csv` needs a release date column.
- Fixed metric list. Anything outside the 8 metrics is treated as vague.

## Before production

1. Real transcripts for 20 to 30 companies over 3 years, and a bigger hand-labeled set (100+ statements) so the extraction metrics mean something.
2. Actuals from Prism's structured financials with point-in-time history, so historical scores don't have look-ahead.
3. Per-metric breakdowns ("reliable on margins, not on growth"), plus tracking how guidance gets revised from call to call. A run of downgrades is a signal by itself.
4. Weight recent promises more, since management teams change.
5. Switch to structured outputs instead of parsing JSON out of text, and make the run-to-run comparison part of the eval instead of a manual check.
6. Expose it as a Spectra tool, something like `get_guidance_track_record(company)`, that returns the score with cited quotes so the chat answers with evidence and not just a number.
7. Run the extraction eval in CI on every prompt or model change, and track latency and cost per transcript.

## How to run

```bash
pip install -r requirements.txt

# Default: scores the hand-labeled guidance, no API key needed
python run.py

# With the LLM: extracts guidance with Claude, evaluates it, then scores it.
# This also rebuilds the report from the LLM's records; run plain
# `python run.py` afterwards to go back to the hand-labeled version.
export ANTHROPIC_API_KEY=your-key
python run.py --use-llm

# Tests
python -m pytest tests/
```

Then open `outputs/report.html` in a browser.

The model, effort level and token prices can be changed with `SAYDO_MODEL`, `SAYDO_EFFORT`, `SAYDO_INPUT_PRICE` and `SAYDO_OUTPUT_PRICE` (see `config.py`).

## Project structure

```
say-vs-do/
├── run.py                  # entry point
├── config.py               # metrics, tolerances, model settings
├── src/
│   ├── load.py             # reads transcripts, actuals and guidance, verifies quotes
│   ├── extract.py          # LLM prompt, call and parsing
│   ├── score.py            # kept/missed rules and the company scoreboard
│   ├── evaluate.py         # LLM output vs hand labels
│   └── report.py           # chart and HTML report
├── data/
│   ├── transcripts/        # 12 synthetic call excerpts
│   ├── actuals.csv         # reported results
│   ├── gold_guidance.json  # 28 hand-labeled statements (scoring input and LLM test set)
│   └── llm_guidance.json   # what Claude extracted on the live run
├── tests/test_score.py     # scoring rules, quote matching, extraction with a fake client
└── outputs/                # generated, including extraction_eval.json from the live run
```
