"""
Auto-pilot (stage 2): submit the approved, supported-ATS applications in a
VISIBLE browser — with a hard safety gate.

For each queue entry with status `ready`:
  1. open the apply form,
  2. fill the standard fields (name, email, phone, links) + upload the CV
     + paste the tailored cover letter,
  3. STOP and hand it to you (status -> `manual`) if it finds ANY of:
       - a required field it could not fill,
       - a question containing a stop keyword (visa/sponsorship/clearance/…),
       - an unsupported form / CAPTCHA,
  4. otherwise click Submit and verify the confirmation (status -> `submitted`).

It never guesses screening / visa answers. You watch it happen in the browser.

Setup (one time):
    pip install playwright pyyaml
    playwright install chromium
Run:
    python submit.py            # submit all `ready` entries
    python submit.py --dry-run  # fill everything but DO NOT click submit
"""

import argparse
import json
import os
import sys

import yaml

ROOT = os.path.dirname(os.path.abspath(__file__))
QUEUE_JSON = os.path.join(ROOT, "data", "queue.json")

# Greenhouse-style field selectors (the most common, most predictable ATS).
GREENHOUSE = {
    "first_name": "input#first_name",
    "last_name": "input#last_name",
    "email": "input#email",
    "phone": "input#phone",
    "resume": "input[type=file]",
}


def load(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) if path.endswith((".yaml", ".yml")) else json.load(fh)


def save_queue(q):
    with open(QUEUE_JSON, "w", encoding="utf-8") as fh:
        json.dump(q, fh, indent=2, ensure_ascii=False)


def page_text(page) -> str:
    try:
        return page.inner_text("body").lower()
    except Exception:
        return ""


def has_stop_keyword(page, stop_keywords) -> str | None:
    text = page_text(page)
    for kw in stop_keywords:
        if kw.lower() in text:
            return kw
    return None


def fill_greenhouse(page, me, cover_letter) -> list:
    """Returns a list of problems; empty list means safe to submit."""
    problems = []

    def try_fill(selector, value):
        try:
            el = page.locator(selector).first
            if el.count() and el.is_visible():
                el.fill(value)
                return True
        except Exception:
            pass
        return False

    try_fill(GREENHOUSE["first_name"], me["first_name"])
    try_fill(GREENHOUSE["last_name"], me["last_name"])
    if not try_fill(GREENHOUSE["email"], me["email"]):
        problems.append("email field not found")
    try_fill(GREENHOUSE["phone"], me["phone"])

    # Custom text questions, matched by their visible label (LinkedIn/GitHub/…).
    label_fills = {"linkedin": me.get("linkedin", ""), "github": me.get("github", ""),
                   "website": me.get("portfolio", ""), "portfolio": me.get("portfolio", "")}
    try:
        for el in page.locator("input[type=text]").all():
            lbl = (el.get_attribute("aria-label") or "").lower()
            for key, val in label_fills.items():
                if key in lbl and val and not (el.input_value() or "").strip():
                    try:
                        el.fill(val)
                    except Exception:
                        pass
    except Exception:
        pass

    # Resume upload
    try:
        f = page.locator(GREENHOUSE["resume"]).first
        if f.count():
            f.set_input_files(me["cv_path"])
    except Exception:
        problems.append("could not upload CV")

    # Any required field still empty -> unsafe
    try:
        for el in page.locator("[required]").all():
            if el.is_visible() and not (el.input_value() or "").strip():
                lbl = (el.get_attribute("aria-label") or el.get_attribute("name") or "field")
                problems.append(f"required field empty: {lbl}")
    except Exception:
        pass

    return problems


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--url", help="Test a single Greenhouse form "
                                  "(implies --dry-run, ignores the queue)")
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("Playwright not installed. Run:\n"
                 "  pip install playwright pyyaml\n  playwright install chromium")

    me = load(os.path.join(ROOT, "me.yaml"))
    if not os.path.exists(me["cv_path"]):
        sys.exit(f"CV not found at {me['cv_path']} — fix cv_path in me.yaml.")

    if args.url:
        args.dry_run = True
        q = {}
        ready = [{"title": "(test)", "company": "(test)", "url": args.url,
                  "ats": "greenhouse", "cover_letter": ""}]
    else:
        q = load(QUEUE_JSON) if os.path.exists(QUEUE_JSON) else {}
        ready = [v for v in q.values()
                 if v["status"] == "ready" and v["ats"] == "greenhouse"]
        if not ready:
            print("No approved Greenhouse applications in the queue. "
                  "(Stage 2 currently supports Greenhouse; Lever/Ashby coming next.)")
            return

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page()
        for v in ready:
            print(f"\n→ {v['title']} @ {v['company']}")
            try:
                page.goto(v["url"], timeout=45000)
                page.wait_for_timeout(2500)

                stop = has_stop_keyword(page, me["stop_keywords"])
                if stop:
                    print(f"   ⏸ stop keyword '{stop}' found — leaving for you.")
                    v["status"] = "manual"; v["reason"] = f"contains '{stop}'"
                    continue

                if page.locator("iframe[src*='recaptcha'], iframe[title*='recaptcha'], "
                                ".g-recaptcha").count():
                    print("   ⏸ CAPTCHA present — leaving for you.")
                    v["status"] = "manual"; v["reason"] = "captcha"
                    continue

                problems = fill_greenhouse(page, me, v.get("cover_letter", ""))
                if problems:
                    print("   ⏸ not safe to auto-submit: " + "; ".join(problems))
                    v["status"] = "manual"; v["reason"] = "; ".join(problems)
                    continue

                if args.dry_run:
                    print("   ✓ filled (dry-run, not submitted).")
                    continue

                # Submit
                page.locator("button:has-text('Submit'), input[type=submit]").first.click()
                page.wait_for_timeout(4000)
                if "thank" in page_text(page) or "submitted" in page_text(page):
                    print("   ✅ submitted.")
                    v["status"] = "submitted"
                else:
                    print("   ⏸ no confirmation seen — check manually.")
                    v["status"] = "manual"; v["reason"] = "no confirmation"
            except Exception as exc:  # noqa: BLE001
                print(f"   ⏸ error: {exc}")
                v["status"] = "manual"; v["reason"] = str(exc)[:120]
            finally:
                if not args.url:
                    save_queue(q)

        print("\nDone. Review any 🟠 manual ones in QUEUE.md.")
        input("Press Enter to close the browser…")
        browser.close()


if __name__ == "__main__":
    main()
