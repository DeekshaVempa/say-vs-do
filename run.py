"""
Say vs Do: management credibility scores.

    python run.py            uses the hand-labeled guidance (no API key needed)
    python run.py --use-llm  extracts guidance with Claude, evaluates it
                             against the hand labels, then scores the LLM output
"""
import argparse
import json

from config import GOLD_PATH, LLM_OUTPUT_PATH, OUTPUT_DIR
from src.load import load_transcripts, load_actuals, load_guidance, verify_quotes, add_call_dates
from src.score import score_all, company_scoreboard
from src.report import save_chart, save_html


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--use-llm", action="store_true", help="extract guidance with Claude")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(exist_ok=True)
    transcripts = load_transcripts()
    actuals = load_actuals()
    gold = add_call_dates(verify_quotes(load_guidance(GOLD_PATH), transcripts), transcripts)

    # The gold quotes are typed by hand, so check them too. If one fails,
    # it is a typo in the labels and the scores would be wrong.
    bad = [g["id"] for g in gold if not g["quote_verified"]]
    if bad:
        raise SystemExit(f"Gold quotes not found in transcripts: {bad}")

    print(f"Loaded {len(transcripts)} transcripts and {len(actuals)} reported numbers")

    if args.use_llm:
        from src.extract import run_extraction
        from src.evaluate import evaluate_extraction

        print("Extracting guidance with the LLM...")
        guidance, run_stats = run_extraction(transcripts)
        guidance = add_call_dates(verify_quotes(guidance, transcripts), transcripts)
        with open(LLM_OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(guidance, f, indent=2)

        eval_report = evaluate_extraction(gold, guidance, run_stats)

        # The number that matters most: does the LLM pipeline give
        # each company the same score as the hand-labeled pipeline?
        gold_board = company_scoreboard(score_all(gold, actuals))
        llm_board = company_scoreboard(score_all(guidance, actuals))
        merged = gold_board[["company", "credibility_score"]].merge(
            llm_board[["company", "credibility_score"]], on="company", suffixes=("_gold", "_llm")
        )
        eval_report["score_comparison"] = merged.to_dict(orient="records")

        with open(OUTPUT_DIR / "extraction_eval.json", "w", encoding="utf-8") as f:
            json.dump(eval_report, f, indent=2)
        print("\nExtraction evaluation:")
        print(json.dumps(eval_report, indent=2))
        source_label = "LLM extraction, checked against hand labels"
    else:
        guidance = gold
        source_label = "hand-labeled guidance"

    scored = score_all(guidance, actuals)
    board = company_scoreboard(scored)

    scored.to_csv(OUTPUT_DIR / "scored_guidance.csv", index=False)
    board.to_csv(OUTPUT_DIR / "scoreboard.csv", index=False)
    save_chart(board, OUTPUT_DIR / "credibility_chart.png")
    save_html(board, scored, OUTPUT_DIR / "report.html", source_label)

    print("\nScoreboard:")
    print(board.to_string(index=False))
    print(f"\nOutputs written to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
