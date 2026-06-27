"""
Job finder (component A).

Pulls AI/ML postings from the Adzuna API for a configured country, filters and
de-duplicates them, and writes a human-readable digest (JOBS.md) plus a full CSV
log (data/jobs.csv). Designed to run daily from GitHub Actions.

Env vars (GitHub Secrets):
    ADZUNA_APP_ID, ADZUNA_APP_KEY   -> free keys from https://developer.adzuna.com
"""

import csv
import datetime as dt
import html
import json
import os
import sys
import urllib.parse
import urllib.request

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT, "data")
SEEN_PATH = os.path.join(DATA_DIR, "seen.json")
CSV_PATH = os.path.join(DATA_DIR, "jobs.csv")
DIGEST_PATH = os.path.join(ROOT, "JOBS.md")
API = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


def load_config() -> dict:
    with open(os.path.join(ROOT, "config.yaml"), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def load_seen() -> set:
    if os.path.exists(SEEN_PATH):
        with open(SEEN_PATH, encoding="utf-8") as fh:
            return set(json.load(fh))
    return set()


def save_seen(seen: set) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SEEN_PATH, "w", encoding="utf-8") as fh:
        json.dump(sorted(seen), fh, indent=0)


def adzuna_search(country: str, what: str, app_id: str, app_key: str,
                  results: int, max_days_old: int) -> list:
    params = {
        "app_id": app_id,
        "app_key": app_key,
        "results_per_page": results,
        "what": what,
        "max_days_old": max_days_old,
        "sort_by": "date",
        "content-type": "application/json",
    }
    url = API.format(country=country) + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "job-hunt-assistant"})
    with urllib.request.urlopen(req, timeout=40) as resp:
        return json.loads(resp.read().decode()).get("results", [])


def normalise(job: dict) -> dict:
    return {
        "id": str(job.get("id", "")),
        "title": (job.get("title") or "").replace("\n", " ").strip(),
        "company": (job.get("company") or {}).get("display_name", "").strip(),
        "location": (job.get("location") or {}).get("display_name", "").strip(),
        "created": (job.get("created") or "")[:10],
        "salary_min": job.get("salary_min"),
        "salary_max": job.get("salary_max"),
        "category": (job.get("category") or {}).get("label", ""),
        "url": job.get("redirect_url", ""),
        "description": " ".join((job.get("description") or "").split())[:400],
    }


def keep(job: dict, cfg: dict) -> bool:
    title = job["title"].lower()
    blob = (job["title"] + " " + job["description"]).lower()
    if any(bad in title for bad in cfg.get("exclude_title_keywords", [])):
        return False
    inc = cfg.get("include_keywords") or []
    if inc and not any(k.lower() in blob for k in inc):
        return False
    return True


def salary_str(job: dict) -> str:
    lo, hi = job["salary_min"], job["salary_max"]
    if lo and hi:
        return f"£{int(lo):,}–£{int(hi):,}"
    if lo:
        return f"£{int(lo):,}+"
    return "—"


def write_digest(new_jobs: list, total_seen: int) -> None:
    today = dt.date.today().isoformat()
    lines = [
        "# 🎯 Job digest",
        "",
        f"_Last run: {today} · {len(new_jobs)} new posting(s) today · "
        f"{total_seen} tracked so far._",
        "",
        "> Auto-generated daily from the Adzuna API. Review and apply manually.",
        "",
    ]
    if not new_jobs:
        lines.append("No new postings matched today. 🙃")
    for j in new_jobs:
        lines.append(f"### [{j['title']}]({j['url']})")
        meta = " · ".join(x for x in [j["company"], j["location"],
                                      salary_str(j), j["created"]] if x and x != "—")
        lines.append(f"**{meta}**")
        if j["description"]:
            lines.append("")
            lines.append(html.unescape(j["description"]) + "…")
        lines.append("")
    with open(DIGEST_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def append_csv(new_jobs: list) -> None:
    os.makedirs(DATA_DIR, exist_ok=True)
    exists = os.path.exists(CSV_PATH)
    fields = ["found_date", "id", "title", "company", "location", "created",
              "salary_min", "salary_max", "category", "url"]
    today = dt.date.today().isoformat()
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        if not exists:
            w.writeheader()
        for j in new_jobs:
            w.writerow({"found_date": today, **{k: j.get(k, "") for k in fields[1:]}})


def main() -> None:
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        # Exit 0 so the scheduled workflow doesn't spam failure emails before
        # the keys are configured.
        print("ADZUNA_APP_ID / ADZUNA_APP_KEY not set — skipping. "
              "Add free keys from https://developer.adzuna.com as repo secrets.")
        return

    cfg = load_config()
    seen = load_seen()

    collected: dict[str, dict] = {}
    for query in cfg["queries"]:
        try:
            raw = adzuna_search(cfg["country"], query, app_id, app_key,
                                cfg["results_per_query"], cfg["max_days_old"])
        except Exception as exc:  # noqa: BLE001 — one bad query shouldn't kill the run
            print(f"[warn] query '{query}' failed: {exc}")
            continue
        for job in raw:
            j = normalise(job)
            if j["id"] and j["id"] not in collected and keep(j, cfg):
                collected[j["id"]] = j

    new_jobs = [j for jid, j in collected.items() if jid not in seen]
    new_jobs.sort(key=lambda j: j["created"], reverse=True)

    write_digest(new_jobs, len(seen) + len(new_jobs))
    append_csv(new_jobs)
    seen.update(j["id"] for j in new_jobs)
    save_seen(seen)

    print(f"{len(new_jobs)} new job(s) written to JOBS.md "
          f"({len(seen)} total tracked).")


if __name__ == "__main__":
    main()
