# 🎯 Job Hunt Assistant

A two-part, ToS-respecting job-search toolkit for AI/ML roles. It **finds**
relevant postings automatically and **drafts tailored applications** — but never
auto-submits anything. You stay in control and apply yourself.

- **[JOBS.md](JOBS.md)** — the latest auto-generated daily digest.

## A · Job finder (automated daily)

A GitHub Actions workflow runs every morning, queries the **Adzuna** job API for
the configured country and search terms, filters and de-duplicates results, and
commits a fresh [`JOBS.md`](JOBS.md) digest plus a full `data/jobs.csv` log.

Edit [`config.yaml`](config.yaml) to change country, search queries, freshness
window, and exclude terms. Adding another country later is a one-line change.

### Setup (one-time)

1. Get free API keys at **https://developer.adzuna.com** (`app_id` + `app_key`).
2. Add them as repository secrets:
   ```bash
   gh secret set ADZUNA_APP_ID  --body "YOUR_APP_ID"
   gh secret set ADZUNA_APP_KEY --body "YOUR_APP_KEY"
   ```
3. Run it now from the **Actions → Daily job digest → Run workflow** button, or
   wait for the daily 07:00 UTC schedule.

Run locally instead:
```bash
pip install -r requirements.txt
ADZUNA_APP_ID=... ADZUNA_APP_KEY=... python fetch_jobs.py
```

## B · Application assistant

Turn a job description into a tailored draft, grounded in your real profile
([`profile.md`](profile.md)) — a cover letter, a "why this role" answer, CV-bullet
suggestions, and an honest fit/gaps note. Uses the Hugging Face Inference API
with your local HF login (`hf auth login`), so it is free.

```bash
pip install -r requirements.txt
python apply.py job.txt --company "Roke" --role "Graduate AI/ML Engineer"
# or:  pbpaste | python apply.py
```

Drafts are written to `applications/` and logged in `applications/tracker.csv`
(both git-ignored — they stay private). **Review and submit every application
yourself.**

## Why not fully automatic submission?

Auto-submitting to LinkedIn/Indeed violates their terms and risks a permanent
account ban, and mass-generic applications get filtered out by recruiters. This
tool optimises for *quality and reach*, with a human in the loop.

## Stack

Python · Adzuna API · GitHub Actions (cron) · Hugging Face Inference · PyYAML
