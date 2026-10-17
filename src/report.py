"""
Turns the scored data into things people can look at: a chart for the
README and a self-contained HTML report where every row cites its source.
"""
from html import escape

import matplotlib
matplotlib.use("Agg")  # no display needed, we only save files
import matplotlib.pyplot as plt

KEPT_COLOR = "#2E7D5B"
MIXED_COLOR = "#B7862B"
MISSED_COLOR = "#C2452D"


def score_color(score):
    if score >= 0.7:
        return KEPT_COLOR
    if score >= 0.45:
        return MIXED_COLOR
    return MISSED_COLOR


def save_chart(board, path):
    # Plot lowest score at the bottom so the best company reads first.
    board = board.sort_values("credibility_score")
    fig, ax = plt.subplots(figsize=(8, 3.6))

    colors = [score_color(s) for s in board["credibility_score"]]
    bars = ax.barh(board["company"], board["credibility_score"], color=colors)

    for bar, (_, row) in zip(bars, board.iterrows()):
        label = f"  {row['kept']} of {row['promises_scored']} kept"
        if row["beat"]:
            label += f", {row['beat']} beat"
        ax.text(bar.get_width(), bar.get_y() + bar.get_height() / 2, label,
                va="center", fontsize=10, color="#333333")

    ax.axvline(0.5, color="#999999", linestyle="--", linewidth=1)
    ax.set_xlim(0, 1.15)
    ax.set_xlabel("Credibility score (smoothed share of promises kept)")
    ax.set_title("Say vs Do: did management deliver what they guided?", loc="left", fontsize=12)
    for side in ["top", "right"]:
        ax.spines[side].set_visible(False)

    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def promise_strip(group):
    # One dot per statement in call order. This is the at-a-glance view:
    # a row of filled dots is a management team that does what it says.
    dots = []
    for _, row in group.iterrows():
        verdict = row["verdict"]
        title = escape(f"{row['call_period']}: {row['quote']} ({verdict})")
        dots.append(f'<span class="dot {verdict}" title="{title}"></span>')
    return "".join(dots)


def verdict_text(verdict):
    return {
        "kept": "Kept",
        "beat": "Beat",
        "missed": "Missed",
        "vague": "Not measurable",
        "no_data": "No reported data",
        "unverified_quote": "Quote not found in source",
        "incomplete": "Target details missing",
    }.get(verdict, verdict)


def fmt(value, suffix=""):
    if value is None or value != value:  # second check catches NaN
        return "n/a"
    return f"{value}{suffix}"


def save_html(board, scored, path, source_label, data_note):
    scored = scored.sort_values(["company", "call_period"])

    board_rows = []
    for _, row in board.iterrows():
        group = scored[scored["company"] == row["company"]]
        gap = row["avg_gap_pp"]
        gap_text = "n/a" if gap is None or gap != gap else f"{gap:+.2f} pp"
        board_rows.append(f"""
        <tr>
          <th scope="row">{escape(row['company'])}</th>
          <td class="strip">{promise_strip(group)}</td>
          <td>{row['kept']} of {row['promises_scored']}<span class="src">{row['beat']} beat, {row['missed']} missed</span></td>
          <td class="score" style="color:{score_color(row['credibility_score'])}">{row['credibility_score']:.2f}</td>
          <td>{gap_text}</td>
        </tr>""")

    detail_sections = []
    for company in board["company"]:
        group = scored[scored["company"] == company]
        rows = []
        for _, r in group.iterrows():
            actual = fmt(r["actual"], "%")
            # Missing values come back from pandas as NaN, which is a float, not None
            source = escape(r["actual_source"]) if isinstance(r["actual_source"], str) else ""
            call_date = escape(r["call_date"]) if isinstance(r["call_date"], str) else ""
            rows.append(f"""
            <tr>
              <td>{escape(r['call_period'])} call<span class="src">{call_date}</span></td>
              <td><q>{escape(r['quote'])}</q><span class="src">{escape(r['source_file'])}</span></td>
              <td>{escape(fmt(r['target_period']))}</td>
              <td>{escape(r['target'])}</td>
              <td>{actual}<span class="src">{source}</span></td>
              <td><span class="verdict {r['verdict']}">{verdict_text(r['verdict'])}</span></td>
            </tr>""")
        detail_sections.append(f"""
      <section>
        <h3>{escape(company)}</h3>
        <div class="scroll">
        <table class="detail">
          <thead><tr><th>Said on</th><th>What management said</th><th>For</th><th>Promise</th><th>Reported</th><th>Result</th></tr></thead>
          <tbody>{''.join(rows)}</tbody>
        </table>
        </div>
      </section>""")

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Say vs Do: management credibility scores</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Newsreader:ital,wght@0,500;1,400&family=Public+Sans:wght@400;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #F6F7F9; --ink: #17202B; --muted: #5F6875; --rule: #D9DDE3;
    --kept: #2E7D5B; --missed: #C2452D; --vague: #A9B0BA; --panel: #FFFFFF;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #12161C; --ink: #E6E9EE; --muted: #9AA3AF; --rule: #2A313B;
      --kept: #5BBF93; --missed: #E9785F; --vague: #5C6470; --panel: #181D24;
      color-scheme: dark;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink);
    font: 16px/1.5 "Public Sans", system-ui, sans-serif; }}
  main {{ max-width: 1040px; margin: 0 auto; padding: 48px 24px 80px; }}
  h1 {{ font: 500 2.6rem/1.1 "Newsreader", Georgia, serif; margin: 0 0 12px; }}
  h2 {{ font: 500 1.5rem/1.2 "Newsreader", Georgia, serif; margin: 56px 0 16px; }}
  h3 {{ font-size: 1.05rem; margin: 32px 0 8px; }}
  .lede {{ max-width: 68ch; color: var(--muted); margin: 0; }}
  .note {{ font-size: .85rem; color: var(--muted); margin-top: 16px; }}
  .scroll {{ overflow-x: auto; }}
  table {{ width: 100%; border-collapse: collapse; background: var(--panel); }}
  th, td {{ text-align: left; padding: 12px 14px; border-bottom: 1px solid var(--rule); vertical-align: top; }}
  thead th {{ font-size: .8rem; font-weight: 600; color: var(--muted); }}
  .board td, .board th[scope=row] {{ vertical-align: middle; }}
  .score {{ font: 500 1.6rem/1 "Newsreader", Georgia, serif; }}
  .strip {{ white-space: nowrap; }}
  .dot {{ display: inline-block; width: 16px; height: 16px; border-radius: 50%; margin-right: 6px; vertical-align: middle; }}
  .dot.kept {{ background: var(--kept); }}
  .dot.missed {{ border: 2px solid var(--missed); }}
  .dot.beat {{ border: 4px solid var(--kept); }}
  .dot.vague, .dot.no_data, .dot.unverified_quote, .dot.incomplete {{ width: 8px; height: 8px; background: var(--vague); }}
  q {{ font: italic 400 1.05rem/1.45 "Newsreader", Georgia, serif; }}
  .src {{ display: block; font-size: .75rem; color: var(--muted); margin-top: 4px; }}
  .verdict {{ font-weight: 600; font-size: .9rem; }}
  .verdict.kept, .verdict.beat {{ color: var(--kept); }}
  .verdict.missed {{ color: var(--missed); }}
  .verdict.vague, .verdict.no_data, .verdict.unverified_quote, .verdict.incomplete {{ color: var(--muted); font-weight: 400; }}
  .legend {{ font-size: .85rem; color: var(--muted); margin: 10px 0 0; }}
  .legend .dot {{ margin-left: 12px; }}
  .legend .dot:first-child {{ margin-left: 0; }}
</style>
</head>
<body>
<main>
  <h1>Who keeps their word?</h1>
  <p class="lede">Every forward-looking promise management made on an earnings call, checked against what the company reported later.
  The credibility score is the share of measurable promises kept, smoothed so that a company with only a few promises does not look perfect by luck.</p>
  <p class="note">Guidance source: {escape(source_label)}. {escape(data_note)}</p>

  <h2>Scoreboard</h2>
  <div class="scroll">
  <table class="board">
    <thead><tr><th>Company</th><th>Promises in call order</th><th>Kept</th><th>Credibility</th><th>Avg gap vs target</th></tr></thead>
    <tbody>{''.join(board_rows)}</tbody>
  </table>
  </div>
  <p class="legend"><span class="dot kept"></span>Kept <span class="dot beat"></span>Beat (missed, but on the good side) <span class="dot missed"></span>Missed <span class="dot vague"></span>Not measurable. Hover a dot to read the quote.</p>

  <h2>Every promise, with its source</h2>
  {''.join(detail_sections)}
</main>
</body>
</html>"""

    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
