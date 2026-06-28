"""
Render JOBS.md from the full data/jobs.csv as a rolling board of all jobs found
in the last N days (config: digest_days, default 14) — newest first.

Run after the fetchers; the workflow calls it last so JOBS.md always shows the
complete recent board, not just one run's delta. The full history always lives
in data/jobs.csv.
"""

import csv
import datetime as dt
import html
import os

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
CSV_PATH = os.path.join(ROOT, "data", "jobs.csv")
DIGEST = os.path.join(ROOT, "JOBS.md")


def salary_str(r) -> str:
    lo, hi = r.get("salary_min"), r.get("salary_max")
    try:
        if lo and hi:
            return f"£{int(float(lo)):,}–£{int(float(hi)):,}"
        if lo:
            return f"£{int(float(lo)):,}+"
    except ValueError:
        pass
    return ""


def main() -> None:
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config.yaml"), encoding="utf-8"))
    days = cfg.get("digest_days", 14)
    if not os.path.exists(CSV_PATH):
        return
    rows = list(csv.DictReader(open(CSV_PATH, encoding="utf-8")))

    cutoff = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    recent = [r for r in rows if r.get("found_date", "") >= cutoff]
    recent.sort(key=lambda r: (r.get("found_date", ""), r.get("created", "")), reverse=True)
    today = dt.date.today().isoformat()

    lines = [
        "# 🎯 Job board",
        "",
        f"_{len(recent)} open role(s) from the last {days} days · "
        f"{len(rows)} tracked in total · updated {today}._",
        "",
        "> Auto-generated from the Adzuna API and target ATS boards. "
        "Full history in [`data/jobs.csv`](data/jobs.csv). Review and apply manually.",
        "",
    ]
    last_date = None
    for r in recent:
        if r.get("found_date") != last_date:
            last_date = r.get("found_date")
            tag = " (today)" if last_date == today else ""
            lines.append(f"\n### {last_date}{tag}")
        meta = " · ".join(x for x in [r.get("company", ""), r.get("location", ""),
                                      salary_str(r)] if x)
        lines.append(f"- [{r.get('title','')}]({r.get('url','')}) — {meta}")

    with open(DIGEST, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    print(f"JOBS.md rendered: {len(recent)} roles from the last {days} days.")


if __name__ == "__main__":
    main()
