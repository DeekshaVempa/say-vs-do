"""
Say vs Do: management credibility scores.

    python run.py            uses the hand-labeled guidance (no API key needed)
    python run.py --use-llm  extracts guidance with Claude, evaluates it
                             against the hand labels, then scores the LLM output

    python run.py --data data/infosys --out outputs/infosys
                             the same, on real Infosys transcripts (see fetch.py)
"""
import argparse
import json
from pathlib import Path

from config import DATA_DIR, OUTPUT_DIR
from src.load import (load_transcripts, load_actuals, load_guidance, verify_quotes, missing_alt_quotes,
                      add_call_dates, dedupe_within_call)
from src.score import score_all, company_scoreboard
from src.report import save_chart, save_html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-llm", action="store_true", help="extract guidance with Claude")
    parser.add_argument("--data", default=str(DATA_DIR), help="folder with transcripts/, actuals.csv, gold_guidance.json")
    parser.add_argument("--out", default=str(OUTPUT_DIR), help="where to write the report and CSVs")
    args = parser.parse_args()

    data_dir, out_dir = Path(args.data), Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    transcripts = load_transcripts(data_dir / "transcripts")
    if not transcripts:
        raise SystemExit(f"No transcripts in {data_dir / 'transcripts'}. For the Infosys data, run python fetch.py first.")
    actuals = load_actuals(data_dir / "actuals.csv")
    gold = add_call_dates(verify_quotes(load_guidance(data_dir / "gold_guidance.json"), transcripts), transcripts)

    # The gold quotes are typed by hand, so check them too. If one fails,
    # it is a typo in the labels and the scores would be wrong.
    bad = [g["id"] for g in gold if not g["quote_verified"]] + missing_alt_quotes(gold, transcripts)
    if bad:
        raise SystemExit(f"Gold quotes not found in transcripts: {bad}")
    gold = dedupe_within_call(gold, transcripts)

    synthetic = all(t["note"].lower().startswith("synthetic") for t in transcripts)
    data_note = ("Companies, transcripts and results are synthetic, built to demonstrate the method." if synthetic
                 else "Transcripts and reported results are real, taken from the company's SEC filings.")

    print(f"Loaded {len(transcripts)} transcripts and {len(actuals)} reported numbers")

    if args.use_llm:
        from src.extract import run_extraction
        from src.evaluate import evaluate_extraction

        print("Extracting guidance with the LLM...")
        extracted, run_stats = run_extraction(transcripts)
        extracted = add_call_dates(verify_quotes(extracted, transcripts), transcripts)
        with open(data_dir / "llm_guidance.json", "w", encoding="utf-8") as f:
            json.dump(extracted, f, indent=2)
        guidance = dedupe_within_call(extracted, transcripts)

        eval_report = evaluate_extraction(gold, guidance, run_stats, len(extracted) - len(guidance))

        # The number that matters most: does the LLM pipeline give
        # each company the same score as the hand-labeled pipeline?
        gold_board = company_scoreboard(score_all(gold, actuals))
        llm_board = company_scoreboard(score_all(guidance, actuals))
        merged = gold_board[["company", "credibility_score"]].merge(
            llm_board[["company", "credibility_score"]], on="company", suffixes=("_gold", "_llm")
        )
        eval_report["score_comparison"] = merged.to_dict(orient="records")

        with open(out_dir / "extraction_eval.json", "w", encoding="utf-8") as f:
            json.dump(eval_report, f, indent=2)
        print("\nExtraction evaluation:")
        print(json.dumps(eval_report, indent=2))
        source_label = "LLM extraction, checked against hand labels"
    else:
        guidance = gold
        source_label = "hand-labeled guidance"

    scored = score_all(guidance, actuals)
    board = company_scoreboard(scored)

    scored.to_csv(out_dir / "scored_guidance.csv", index=False)
    board.to_csv(out_dir / "scoreboard.csv", index=False)
    save_chart(board, out_dir / "credibility_chart.png")
    save_html(board, scored, out_dir / "report.html", source_label, data_note)

    print("\nScoreboard:")
    print(board.to_string(index=False))
    print(f"\nOutputs written to {out_dir}/")


if __name__ == "__main__":
    main()
