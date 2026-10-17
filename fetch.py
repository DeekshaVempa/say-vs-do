"""
Download real earnings call transcripts from SEC filings.

    export SEC_USER_AGENT="Your Name you@example.com"
    python fetch.py                       # Infosys, Q4 FY24 to Q4 FY26 calls

The defaults pull the 9 Infosys calls that cover two full guidance cycles
(FY25 and FY26). Other companies that attach transcripts to their SEC
filings can be fetched with --cik and --company.
"""
import argparse
import os
from pathlib import Path

from src.fetch_sec import fetch_transcripts

ROOT = Path(__file__).parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cik", default="1067491", help="SEC company id (default: Infosys)")
    parser.add_argument("--company", default="Infosys")
    parser.add_argument("--start", default="2024-04-01", help="first filing date to include")
    parser.add_argument("--end", default="2026-05-31", help="last filing date to include")
    parser.add_argument("--out", default=str(ROOT / "data" / "infosys" / "transcripts"))
    args = parser.parse_args()

    user_agent = os.getenv("SEC_USER_AGENT")
    if not user_agent or "@" not in user_agent:
        raise SystemExit('SEC requires a contact email. Set SEC_USER_AGENT="Your Name you@example.com"')

    print(f"Fetching {args.company} earnings call transcripts filed {args.start} to {args.end}")
    written = fetch_transcripts(args.cik, args.company, args.start, args.end, Path(args.out), user_agent)
    print(f"{len(written)} transcripts written to {args.out}")


if __name__ == "__main__":
    main()
