"""
Direct ATS-board source.

Queries the public job-board APIs of the companies in companies.yaml
(Greenhouse / Lever / Ashby), filters to AI/ML + UK/remote roles, and appends
new postings to data/jobs.csv — using the company's DIRECT application URL, so
the auto-pilot can actually submit them.

Run:  python fetch_ats.py
"""

import csv
import datetime as dt
import json
import os
import urllib.request

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
CSV_PATH = os.path.join(DATA, "jobs.csv")
SEEN_PATH = os.path.join(DATA, "ats_seen.json")

FIELDS = ["found_date", "id", "title", "company", "location", "created",
          "salary_min", "salary_max", "category", "url"]


def get(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "job-hunt-assistant"})
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] {url} -> {exc}")
        return None


def parse_greenhouse(slug):
    d = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    out = []
    for j in (d or {}).get("jobs", []):
        out.append({"id": j.get("id"), "title": j.get("title", ""),
                    "location": (j.get("location") or {}).get("name", ""),
                    "url": j.get("absolute_url", ""), "remote": False})
    return out


def parse_lever(slug):
    d = get(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    out = []
    for j in (d or []):
        cats = j.get("categories") or {}
        out.append({"id": j.get("id"), "title": j.get("text", ""),
                    "location": cats.get("location", ""),
                    "url": j.get("hostedUrl", ""),
                    "remote": "remote" in (cats.get("location", "") or "").lower()})
    return out


def parse_ashby(slug):
    d = get(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    out = []
    for j in (d or {}).get("jobs", []):
        if j.get("isListed") is False:
            continue
        out.append({"id": j.get("id"), "title": j.get("title", ""),
                    "location": j.get("location") or j.get("locationName") or "",
                    "url": j.get("jobUrl") or j.get("applyUrl") or "",
                    "remote": bool(j.get("isRemote"))})
    return out


PARSERS = {"greenhouse": parse_greenhouse, "lever": parse_lever, "ashby": parse_ashby}


def load_seen():
    if os.path.exists(SEEN_PATH):
        return set(json.load(open(SEEN_PATH, encoding="utf-8")))
    return set()


def main():
    cfg = yaml.safe_load(open(os.path.join(ROOT, "config.yaml"), encoding="utf-8"))
    companies = yaml.safe_load(open(os.path.join(ROOT, "companies.yaml"), encoding="utf-8"))["companies"]
    kws = [k.lower() for k in cfg.get("ats_title_keywords", [])]
    locs = [l.lower() for l in cfg.get("ats_locations", [])]
    excl = [e.lower() for e in cfg.get("exclude_title_keywords", [])]
    cap = cfg.get("ats_max_per_company", 25)

    seen = load_seen()
    today = dt.date.today().isoformat()
    new_rows = []

    for c in companies:
        parser = PARSERS.get(c["ats"])
        if not parser:
            continue
        kept = 0
        for j in parser(c["slug"]):
            if kept >= cap or not j["id"] or not j["url"]:
                continue
            title_l = j["title"].lower()
            loc_l = (j["location"] or "").lower()
            if not any(k.strip() in title_l for k in kws):
                continue
            if any(e in title_l for e in excl):
                continue
            if not (j["remote"] or any(l in loc_l for l in locs)):
                continue
            uid = f"{c['ats']}-{c['slug']}-{j['id']}"
            if uid in seen:
                continue
            seen.add(uid)
            new_rows.append({
                "found_date": today, "id": uid, "title": j["title"],
                "company": c["name"], "location": j["location"], "created": today,
                "salary_min": "", "salary_max": "", "category": c["ats"], "url": j["url"],
            })
            kept += 1
        print(f"{c['name']:18s} ({c['ats']}): +{kept} matched")

    os.makedirs(DATA, exist_ok=True)
    exists = os.path.exists(CSV_PATH)
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        if not exists:
            w.writeheader()
        for r in new_rows:
            w.writerow(r)
    json.dump(sorted(seen), open(SEEN_PATH, "w", encoding="utf-8"), indent=0)
    print(f"\n{len(new_rows)} new ATS-board job(s) added to data/jobs.csv. "
          f"Run `python autopilot.py` to draft + queue them.")


if __name__ == "__main__":
    main()
