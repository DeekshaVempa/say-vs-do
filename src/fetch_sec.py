"""
Downloads earnings call transcripts that a company files with the SEC and
turns them into the same plain-text format as the synthetic transcripts.

Infosys attaches the transcript of every earnings call to a Form 6-K, labeled
"TRANSCRIPT OF EARNINGS CALL". Its own website and the Indian exchanges block
scripted downloads, but the SEC allows them as long as each request says who
is asking, so the User-Agent has to include a contact email.
"""
import html
import json
import re
import time
import urllib.request

ARCHIVES = "https://www.sec.gov/Archives/edgar/data"
TRANSCRIPT_LABEL = "TRANSCRIPT OF EARNINGS CALL"

MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}


def sec_get(url, user_agent):
    # SEC's fair access rules allow 10 requests a second. Staying well under
    # that costs a few seconds and avoids getting the IP blocked.
    time.sleep(0.25)
    request = urllib.request.Request(url, headers={"User-Agent": user_agent, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


def list_filings(cik, start, end, user_agent, form="6-K"):
    data = json.loads(sec_get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json", user_agent))
    recent = data["filings"]["recent"]
    filings = []
    for i, filing_form in enumerate(recent["form"]):
        if filing_form == form and start <= recent["filingDate"][i] <= end:
            filings.append({"date": recent["filingDate"][i], "accession": recent["accessionNumber"][i]})
    return sorted(filings, key=lambda f: f["date"])


def find_documents(cik, accession, user_agent, label=TRANSCRIPT_LABEL):
    # The filing index lists every attachment with a description, which is
    # cheaper and more reliable than opening each exhibit to see what it is.
    folder = f"{ARCHIVES}/{int(cik)}/{accession.replace('-', '')}"
    page = sec_get(f"{folder}/{accession}-index.html", user_agent)
    urls = []
    for row in re.findall(r"(?is)<tr[^>]*>(.*?)</tr>", page):
        cells = [clean(c) for c in re.findall(r"(?is)<td[^>]*>(.*?)</td>", row)]
        if len(cells) >= 3 and cells[1].upper() == label:
            urls.append(f"{folder}/{cells[2]}")
    return urls


def clean(fragment):
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", fragment))
    return " ".join(text.split())


def html_to_blocks(raw):
    # Each paragraph or table cell becomes a block. A block whose text is all
    # bold and only a few words long is a speaker name ("Moderator",
    # "Jayesh Sanghrajka"); everything else is speech.
    blocks = []
    for match in re.finditer(r"(?is)<(p|td)\b[^>]*>(.*?)</\1>", raw):
        inner = match.group(2)
        text = clean(inner)
        if not text:
            continue
        bold = " ".join(clean(b) for b in re.findall(r"(?is)<b\b[^>]*>(.*?)</b>", inner))
        is_name = bold == text and len(text.split()) <= 5
        blocks.append((text, is_name))
    return blocks


def period_from_date(year, month):
    # Results calls happen a few weeks after the quarter closes. With an
    # April to March fiscal year, an April call reports Q4 of the year that
    # just ended and a July call reports Q1 of the new one.
    if month in (4, 5, 6):
        return f"Q4FY{year % 100:02d}"
    if month in (7, 8, 9):
        return f"Q1FY{(year + 1) % 100:02d}"
    if month in (10, 11, 12):
        return f"Q2FY{(year + 1) % 100:02d}"
    return f"Q3FY{year % 100:02d}"


def parse_participants(blocks):
    # The title page lists "CORPORATE PARTICIPANTS" (management) and then
    # everyone else under a heading that varies by quarter ("ANALYSTS",
    # "journalists"). Names are bold, titles and firms follow on their own lines.
    groups = {"Management": [], "Others": []}
    current = None
    for text, is_name in blocks:
        heading = text.strip().lower()
        if heading.startswith("corporate participants"):
            current = groups["Management"]
        elif heading.rstrip(":") in ("analyst", "analysts", "journalist", "journalists", "participants"):
            current = groups["Others"]
        elif current is None:
            continue
        elif is_name:
            current.append([text])
        elif current:
            current[-1].append(text)
    return {
        name: "; ".join(f"{p[0]} ({', '.join(p[1:])})" if len(p) > 1 else p[0] for p in people)
        for name, people in groups.items()
    }


def parse_transcript(raw):
    blocks = html_to_blocks(raw)
    first_turn = next(i for i, (text, is_name) in enumerate(blocks) if is_name and text == "Moderator")
    title = " ".join(text for text, _ in blocks[:first_turn])
    opening = " ".join(text for text, _ in blocks[first_turn:first_turn + 3])

    date = re.search(r"\b(" + "|".join(MONTHS) + r")\s+(\d{1,2}),\s+(\d{4})", title)
    if not date:
        raise ValueError("could not find the call date on the transcript's title page")
    year, month, day = int(date.group(3)), MONTHS[date.group(1)], int(date.group(2))
    call_date = f"{year}-{month:02d}-{day:02d}"

    # Most titles say "Q4 FY26", some only give the date. The moderator's
    # welcome usually names the quarter, and the date is the last resort.
    quarter = re.search(r"\bQ([1-4])\s*FY\s*'?(\d{2})\b", title + " " + opening)
    period = f"Q{quarter.group(1)}FY{quarter.group(2)}" if quarter else period_from_date(year, month)

    # Everything before the moderator first speaks is the title page and the
    # participant list. The list is kept because it is how the model can tell
    # management apart from analysts.
    participants = parse_participants(blocks[:first_turn])

    turns = []
    for text, is_name in blocks[first_turn:]:
        if is_name:
            turns.append([text, []])
        elif turns:
            turns[-1][1].append(text)
    turns = [(speaker, " ".join(parts)) for speaker, parts in turns if parts]

    return {"period": period, "date": call_date, "participants": participants, "turns": turns}


def to_transcript_text(company, parsed, source_url):
    quarter, year = parsed["period"][:2], parsed["period"][2:]
    lines = [
        f"Company: {company}",
        f"Period: {parsed['period']}",
        f"Call: {quarter} {year} earnings call",
        f"Date: {parsed['date']}",
        f"Source: {source_url}",
        "Note: Real transcript, downloaded from the company's SEC filing.",
        "",
        f"Management on the call: {parsed['participants']['Management']}",
        "",
        f"Others on the call: {parsed['participants']['Others']}",
        "",
    ]
    for speaker, text in parsed["turns"]:
        lines += [f"{speaker}: {text}", ""]
    return "\n".join(lines)


def fetch_transcripts(cik, company, start, end, out_dir, user_agent):
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = company.lower().replace(" ", "_")
    written = []
    for filing in list_filings(cik, start, end, user_agent):
        for url in find_documents(cik, filing["accession"], user_agent):
            parsed = parse_transcript(sec_get(url, user_agent))
            path = out_dir / f"{stem}_{parsed['period']}.txt"
            path.write_text(to_transcript_text(company, parsed, url), encoding="utf-8")
            words = sum(len(text.split()) for _, text in parsed["turns"])
            print(f"  {parsed['period']} call on {parsed['date']}: {len(parsed['turns'])} turns, {words} words -> {path.name}")
            written.append(path)
    return written
