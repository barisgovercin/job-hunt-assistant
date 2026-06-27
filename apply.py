"""
Application assistant (component B).

Given a job description, generates a tailored cover letter, a short "why this
role/company" answer, and CV-bullet suggestions — grounded in the candidate's
real profile (profile.md). You review and submit manually; nothing is sent.

Uses the Hugging Face Inference API with your locally stored HF token
(run `hf auth login` once). No experience is invented.

Usage:
    python apply.py job.txt
    python apply.py job.txt --company "Roke" --role "Graduate AI/ML Engineer"
    pbpaste | python apply.py            # paste the JD on stdin
"""

import argparse
import csv
import datetime as dt
import os
import re
import sys

from huggingface_hub import InferenceClient, get_token

ROOT = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.join(ROOT, "applications")
TRACKER = os.path.join(APP_DIR, "tracker.csv")

# Tried in order until one is available on your HF inference quota.
MODELS = [
    "meta-llama/Llama-3.1-8B-Instruct",
    "Qwen/Qwen2.5-7B-Instruct",
    "mistralai/Mistral-7B-Instruct-v0.3",
]

SYSTEM = (
    "You are an expert UK career assistant. You write concise, specific, honest "
    "job applications for one candidate, using ONLY the facts in their profile. "
    "Never invent experience, employers, skills, or numbers. Prefer concrete "
    "project results over buzzwords. British English."
)

TEMPLATE = """Candidate profile:
---
{profile}
---

Job description:
---
{jd}
---

Produce, in Markdown with these exact headings:

## Cover letter
A focused cover letter (max ~250 words) tailored to this specific role and
company, drawing on the most relevant projects/experience from the profile.

## Why this role
A 3-4 sentence answer to "why do you want this role / company", specific to them.

## Tailored CV bullets
5 bullet points re-phrasing the candidate's real experience to match this job's
keywords and requirements (no fabrication).

## Fit & gaps
2-3 short honest notes: strongest matches, and any requirement the candidate
does not yet meet (so they can decide whether to apply).
"""


def read_jd(args) -> str:
    if args.jd:
        with open(args.jd, encoding="utf-8") as fh:
            return fh.read().strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    sys.exit("Provide a job description: `python apply.py job.txt` or pipe it on stdin.")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50] or "application"


def generate(profile: str, jd: str) -> str:
    token = get_token()
    if not token:
        sys.exit("No HF token found. Run `hf auth login` first.")
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": TEMPLATE.format(profile=profile, jd=jd)},
    ]
    last_err = None
    for model in MODELS:
        try:
            client = InferenceClient(model=model, token=token)
            resp = client.chat_completion(messages=messages, max_tokens=1100,
                                          temperature=0.4)
            return resp.choices[0].message.content
        except Exception as exc:  # noqa: BLE001 — try the next model
            last_err = exc
            print(f"[info] {model} unavailable, trying next… ({exc})")
    sys.exit(f"All models failed. Last error: {last_err}")


def log_tracker(company: str, role: str, path: str) -> None:
    os.makedirs(APP_DIR, exist_ok=True)
    exists = os.path.exists(TRACKER)
    with open(TRACKER, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if not exists:
            w.writerow(["date", "company", "role", "status", "draft"])
        w.writerow([dt.date.today().isoformat(), company, role, "draft", path])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jd", nargs="?", help="Path to a text file with the job description")
    ap.add_argument("--company", default="")
    ap.add_argument("--role", default="")
    args = ap.parse_args()

    jd = read_jd(args)
    with open(os.path.join(ROOT, "profile.md"), encoding="utf-8") as fh:
        profile = fh.read()

    print("Generating tailored application… (this can take ~10-20s)")
    output = generate(profile, jd)

    os.makedirs(APP_DIR, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    name = slugify(f"{args.company} {args.role}".strip()) if (args.company or args.role) else stamp
    path = os.path.join(APP_DIR, f"{name}.md")
    header = f"# Application — {args.company or '?'} · {args.role or '?'}\n_{dt.date.today().isoformat()}_\n\n"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(header + output + "\n")

    log_tracker(args.company or "?", args.role or "?", os.path.relpath(path, ROOT))
    print(f"\nSaved draft -> {os.path.relpath(path, ROOT)}")
    print("Logged in applications/tracker.csv. Review, edit, and submit it yourself.")


if __name__ == "__main__":
    main()
