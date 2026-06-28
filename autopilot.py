"""
Auto-pilot (stage 1): turn newly-found jobs into a review queue of tailored,
ready-to-submit applications.

For each new job it:
  1. drafts a tailored cover letter (grounded in profile.md, via HF Inference),
  2. detects the ATS from the apply URL (Greenhouse / Lever / Ashby / other),
  3. writes a queue entry with status `ready` (supported ATS) or `manual`
     (unsupported / needs human attention).

You then review the queue and approve; stage 2 (`submit.py`) submits the
`ready` ones in a browser and ALWAYS pauses on screening / visa questions.

Nothing is submitted here. Run:  python autopilot.py
"""

import csv
import json
import os
import re
import datetime as dt

from huggingface_hub import InferenceClient, get_token

ROOT = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(ROOT, "data")
QUEUE_JSON = os.path.join(DATA, "queue.json")
QUEUE_MD = os.path.join(ROOT, "QUEUE.md")
JOBS_CSV = os.path.join(DATA, "jobs.csv")

MODELS = ["meta-llama/Llama-3.1-8B-Instruct", "Qwen/Qwen2.5-7B-Instruct"]

# Apply-URL host -> ATS name. Only these are auto-submittable in stage 2.
ATS_HOSTS = {
    "boards.greenhouse.io": "greenhouse",
    "job-boards.greenhouse.io": "greenhouse",
    "jobs.lever.co": "lever",
    "jobs.ashbyhq.com": "ashby",
}

SYSTEM = (
    "You write concise, honest UK cover letters for one candidate using ONLY the "
    "facts in their profile. Never invent experience. British English, ~180 words."
)


def detect_ats(url: str) -> str:
    host = re.sub(r"^https?://", "", url or "").split("/")[0].lower()
    for h, name in ATS_HOSTS.items():
        if host.endswith(h):
            return name
    return "other"


def load_queue() -> dict:
    if os.path.exists(QUEUE_JSON):
        with open(QUEUE_JSON, encoding="utf-8") as fh:
            return json.load(fh)
    return {}


def save_queue(q: dict) -> None:
    os.makedirs(DATA, exist_ok=True)
    with open(QUEUE_JSON, "w", encoding="utf-8") as fh:
        json.dump(q, fh, indent=2, ensure_ascii=False)


def todays_jobs() -> list:
    if not os.path.exists(JOBS_CSV):
        return []
    today = dt.date.today().isoformat()
    with open(JOBS_CSV, encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if r.get("found_date") == today]


def draft_cover_letter(profile: str, job: dict) -> str:
    token = get_token()
    if not token:
        return ""
    jd = (f"Role: {job['title']}\nCompany: {job['company']}\n"
          f"Location: {job['location']}\n")
    user = (f"{profile}\n\nWrite a tailored cover letter for this role:\n{jd}")
    for model in MODELS:
        try:
            client = InferenceClient(model=model, token=token)
            r = client.chat_completion(
                messages=[{"role": "system", "content": SYSTEM},
                          {"role": "user", "content": user}],
                max_tokens=400, temperature=0.4)
            return r.choices[0].message.content.strip()
        except Exception as exc:  # noqa: BLE001
            print(f"[info] {model} unavailable ({exc}); trying next…")
    return ""


def render_queue_md(q: dict) -> None:
    ready = [v for v in q.values() if v["status"] == "ready"]
    manual = [v for v in q.values() if v["status"] == "manual"]
    pending = [v for v in q.values() if v["status"] == "pending_approval"]
    lines = [
        "# ✅ Application queue",
        "",
        f"_{len(pending)} awaiting approval · {len(ready)} approved & ready · "
        f"{len(manual)} need manual attention._",
        "",
        "Approve with: `python autopilot.py --approve-all` "
        "(or edit status to `ready` in data/queue.json). "
        "Then submit with: `python submit.py`.",
        "",
    ]
    for bucket, title in [(pending, "⏳ Awaiting your approval"),
                          (ready, "🟢 Approved — will be auto-submitted"),
                          (manual, "🟠 Manual (visa/screening or unsupported ATS)")]:
        if not bucket:
            continue
        lines.append(f"## {title}")
        for v in bucket:
            lines.append(f"- **{v['title']}** — {v['company']} "
                         f"({v['ats']}) · [posting]({v['url']})")
        lines.append("")
    with open(QUEUE_MD, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--approve-all", action="store_true",
                    help="Mark all pending entries as ready for submission")
    args = ap.parse_args()

    q = load_queue()

    if args.approve_all:
        n = 0
        for v in q.values():
            if v["status"] == "pending_approval":
                v["status"] = "ready"
                n += 1
        save_queue(q)
        render_queue_md(q)
        print(f"Approved {n} application(s). Run `python submit.py` to submit them.")
        return

    with open(os.path.join(ROOT, "profile.md"), encoding="utf-8") as fh:
        profile = fh.read()

    added = 0
    for job in todays_jobs():
        jid = job["id"]
        if jid in q:
            continue
        ats = detect_ats(job["url"])
        cover = draft_cover_letter(profile, job)
        q[jid] = {
            "id": jid,
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "url": job["url"],
            "ats": ats,
            "cover_letter": cover,
            # supported ATS -> wait for approval; otherwise leave to the human
            "status": "pending_approval" if ats != "other" else "manual",
        }
        added += 1

    save_queue(q)
    render_queue_md(q)
    print(f"Queued {added} new application(s). Review QUEUE.md, then "
          f"`python autopilot.py --approve-all`.")


if __name__ == "__main__":
    main()
