"""
Application assistant (component B).

For a given job description it creates a dedicated folder
`applications/<company>-<role>/` containing everything for that application:

    job.txt          the job description you fed in
    application.md   full draft: cover letter, why-this-role, CV bullets, fit/gaps
    cover_letter.md  just the cover letter (plain text)
    cover_letter.pdf ready-to-upload PDF of the cover letter

All content is grounded in your real profile (profile.md) and generated with the
Hugging Face Inference API using your local HF login (`hf auth login`). You review
and submit manually; nothing is sent. No experience is invented.

Usage:
    python apply.py job.txt --company "Graphcore" --role "AI Research Engineer"
    pbpaste | python apply.py --company "X" --role "Y"
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
    sys.exit("Provide a job: `--url <link>`, `python apply.py job.txt`, or pipe it on stdin.")


def fetch_jd(url: str) -> str:
    """Fetch the job description straight from a posting URL (no copy-paste)."""
    import json
    import urllib.request
    import html as _html

    def strip(h):
        h = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", h)
        return re.sub(r"\s+", " ", re.sub("<[^>]+>", " ", _html.unescape(h))).strip()

    try:
        m = re.search(r"greenhouse\.io/([^/?#]+)/jobs/(\d+)", url)
        if m:
            d = json.loads(urllib.request.urlopen(
                f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}",
                timeout=30).read())
            return f"Role: {d.get('title','')}\n\n{strip(d.get('content',''))[:2800]}"
        m = re.search(r"lever\.co/([^/?#]+)/([0-9a-fA-F-]+)", url)
        if m:
            d = json.loads(urllib.request.urlopen(
                f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}",
                timeout=30).read())
            return f"Role: {d.get('text','')}\n\n{strip(d.get('description',''))[:2800]}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "ignore")
        text = strip(page)
        if len(text) < 120:
            sys.exit("Couldn't read a description from that page. Save it to a .txt instead.")
        return text[:2800]
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"Could not fetch the job page ({exc}). "
                 "Save the description to a .txt and pass that instead.")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "application"


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
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            print(f"[info] {model} unavailable, trying next… ({exc})")
    sys.exit(f"All models failed. Last error: {last_err}")


def extract_cover_letter(markdown: str) -> str:
    m = re.search(r"##\s*Cover letter\s*(.*?)(?=\n##\s|\Z)", markdown, re.S | re.I)
    return (m.group(1).strip() if m else markdown).strip()


def _ascii(text: str) -> str:
    repl = {"’": "'", "‘": "'", "“": '"', "”": '"',
            "–": "-", "—": "-", "…": "...", " ": " ",
            "·": "-", "•": "-"}
    for a, b in repl.items():
        text = text.replace(a, b)
    return text.encode("latin-1", "ignore").decode("latin-1")


def load_contact() -> tuple[str, str]:
    """Name + contact line for the PDF header, from me.yaml if present."""
    path = os.path.join(ROOT, "me.yaml")
    if os.path.exists(path):
        try:
            import yaml
            d = yaml.safe_load(open(path, encoding="utf-8"))
            name = f"{d.get('first_name','')} {d.get('last_name','')}".strip()
            contact = " - ".join(x for x in [d.get("email"), d.get("phone"),
                                             d.get("location")] if x)
            return name or "Applicant", contact
        except Exception:
            pass
    return "Applicant", ""


def make_cover_pdf(path: str, name: str, contact: str, body: str) -> bool:
    try:
        from fpdf import FPDF
    except ImportError:
        return False
    pdf = FPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_margins(22, 20, 22)
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 9, _ascii(name), new_x="LMARGIN", new_y="NEXT")
    if contact:
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(90, 90, 90)
        pdf.cell(0, 6, _ascii(contact), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)
    pdf.set_draw_color(180, 180, 180)
    y = pdf.get_y()
    pdf.line(22, y, 188, y)
    pdf.ln(6)
    pdf.set_font("Helvetica", "", 11)
    for para in body.split("\n\n"):
        para = " ".join(para.split())
        if para:
            pdf.multi_cell(0, 6, _ascii(para))
            pdf.ln(2.5)
    pdf.output(path)
    return True


def log_tracker(company: str, role: str, folder: str) -> None:
    os.makedirs(APP_DIR, exist_ok=True)
    exists = os.path.exists(TRACKER)
    with open(TRACKER, "a", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        if not exists:
            w.writerow(["date", "company", "role", "status", "folder"])
        w.writerow([dt.date.today().isoformat(), company, role, "draft", folder])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jd", nargs="?", help="Path to a text file with the job description")
    ap.add_argument("--url", default="", help="Job posting URL — fetches the description for you")
    ap.add_argument("--company", default="")
    ap.add_argument("--role", default="")
    args = ap.parse_args()

    jd = fetch_jd(args.url) if args.url else read_jd(args)
    with open(os.path.join(ROOT, "profile.md"), encoding="utf-8") as fh:
        profile = fh.read()

    print("Generating tailored application… (this can take ~10-20s)")
    output = generate(profile, jd)
    cover = extract_cover_letter(output)

    slug = slugify(f"{args.company} {args.role}".strip()) if (args.company or args.role) \
        else dt.datetime.now().strftime("%Y%m%d-%H%M")
    folder = os.path.join(APP_DIR, slug)
    os.makedirs(folder, exist_ok=True)

    with open(os.path.join(folder, "job.txt"), "w", encoding="utf-8") as fh:
        fh.write(jd)
    header = f"# Application — {args.company or '?'} · {args.role or '?'}\n_{dt.date.today().isoformat()}_\n\n"
    with open(os.path.join(folder, "application.md"), "w", encoding="utf-8") as fh:
        fh.write(header + output + "\n")
    with open(os.path.join(folder, "cover_letter.md"), "w", encoding="utf-8") as fh:
        fh.write(cover + "\n")

    name, contact = load_contact()
    pdf_path = os.path.join(folder, "cover_letter.pdf")
    pdf_ok = make_cover_pdf(pdf_path, name, contact, cover)

    log_tracker(args.company or "?", args.role or "?", os.path.relpath(folder, ROOT))

    rel = os.path.relpath(folder, ROOT)
    print(f"\nSaved application to {rel}/")
    print(f"  - application.md   (full draft)")
    print(f"  - cover_letter.md  (text)")
    print(f"  - cover_letter.pdf {'(ready to upload)' if pdf_ok else '(skipped — run: pip install fpdf2)'}")
    print(f"  - job.txt")
    print("Logged in applications/tracker.csv. Review, edit, and submit it yourself.")


if __name__ == "__main__":
    main()
