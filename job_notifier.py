"""
Job Application Notifier
Searches for ML/AI/Data roles across free job APIs, filters for entry-level
eligibility, skips jobs already seen, and emails new matches.

Runs standalone or via GitHub Actions (see .github/workflows/job_notifier.yml).
"""

import json
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Config — edit these to tune your search
# ---------------------------------------------------------------------------

SEARCH_KEYWORDS = [
    "machine learning intern",
    "machine learning engineer",
    "data scientist",
    "ai engineer",
    "ml engineer",
]

# Words that suggest a role is actually entry-level / open to you
ELIGIBLE_HINTS = [
    "intern", "internship", "fresher", "entry level", "entry-level",
    "graduate", "junior", "trainee", "0-1 year", "0-2 years", "campus",
    "associate", "new grad",
]

# Words that mean "skip this, it's not for you right now"
EXCLUDE_HINTS = [
    "senior", "sr.", "lead", "principal", "staff engineer", "manager",
    "5+ years", "6+ years", "7+ years", "8+ years", "10+ years",
    "director", "head of",
]

ADZUNA_COUNTRY = "in"  # India
SEEN_JOBS_FILE = Path(__file__).parent / "seen_jobs.json"

# ---------------------------------------------------------------------------
# Job sources
# ---------------------------------------------------------------------------

def fetch_adzuna_jobs():
    """Adzuna free API — needs ADZUNA_APP_ID and ADZUNA_APP_KEY env vars."""
    app_id = os.environ.get("ADZUNA_APP_ID")
    app_key = os.environ.get("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("Adzuna credentials not set, skipping Adzuna search.")
        return []

    jobs = []
    for keyword in SEARCH_KEYWORDS:
        url = f"https://api.adzuna.com/v1/api/jobs/{ADZUNA_COUNTRY}/search/1"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "what": keyword,
            "results_per_page": 20,
            "content-type": "application/json",
        }
        try:
            resp = requests.get(url, params=params, timeout=20)
            resp.raise_for_status()
            for r in resp.json().get("results", []):
                jobs.append({
                    "id": f"adzuna_{r['id']}",
                    "title": r.get("title", "").strip(),
                    "company": r.get("company", {}).get("display_name", "Unknown"),
                    "location": r.get("location", {}).get("display_name", ""),
                    "url": r.get("redirect_url", ""),
                    "description": r.get("description", ""),
                    "source": "Adzuna",
                })
        except requests.RequestException as e:
            print(f"Adzuna search failed for '{keyword}': {e}")
    return jobs


def fetch_arbeitnow_jobs():
    """Arbeitnow public API — no key required. Mostly remote tech roles."""
    jobs = []
    try:
        resp = requests.get("https://www.arbeitnow.com/api/job-board-api", timeout=20)
        resp.raise_for_status()
        for r in resp.json().get("data", []):
            title = r.get("title", "")
            tags = " ".join(r.get("tags", []) + r.get("job_types", []))
            text_blob = f"{title} {tags}".lower()
            if not any(k.split()[0] in text_blob for k in ["machine", "data", "ai", "ml"]):
                continue
            jobs.append({
                "id": f"arbeitnow_{r.get('slug')}",
                "title": title,
                "company": r.get("company_name", "Unknown"),
                "location": "Remote" if r.get("remote") else r.get("location", ""),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
                "source": "Arbeitnow",
            })
    except requests.RequestException as e:
        print(f"Arbeitnow search failed: {e}")
    return jobs


# ---------------------------------------------------------------------------
# Filtering
# ---------------------------------------------------------------------------

def is_eligible(job):
    text = f"{job['title']} {job['description']}".lower()
    if any(bad in text for bad in EXCLUDE_HINTS):
        return False
    if any(good in text for good in ELIGIBLE_HINTS):
        return True
    # No strong signal either way — include title-only matches conservatively
    return any(k.split()[0] in job["title"].lower() for k in ["machine", "data", "ai", "ml"])


def load_seen_ids():
    if SEEN_JOBS_FILE.exists():
        return set(json.loads(SEEN_JOBS_FILE.read_text()))
    return set()


def save_seen_ids(ids):
    SEEN_JOBS_FILE.write_text(json.dumps(sorted(ids), indent=2))


# ---------------------------------------------------------------------------
# Email
# ---------------------------------------------------------------------------

def send_email(new_jobs):
    sender = os.environ.get("GMAIL_ADDRESS")
    app_password = os.environ.get("GMAIL_APP_PASSWORD")
    recipient = os.environ.get("NOTIFY_EMAIL", sender)

    if not sender or not app_password:
        print("Gmail credentials not set, skipping email. Matches found:")
        for j in new_jobs:
            print(f" - {j['title']} @ {j['company']} ({j['url']})")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{len(new_jobs)} new ML/AI/Data role(s) matched"
    msg["From"] = sender
    msg["To"] = recipient

    lines = []
    for j in new_jobs:
        lines.append(
            f"<p><b>{j['title']}</b> — {j['company']}<br>"
            f"{j['location']} · via {j['source']}<br>"
            f"<a href='{j['url']}'>{j['url']}</a></p><hr>"
        )
    html = f"<html><body>{''.join(lines)}</body></html>"
    msg.attach(MIMEText(html, "html"))

    context = ssl.create_default_context()
    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls(context=context)
        server.login(sender, app_password)
        server.sendmail(sender, recipient, msg.as_string())
    print(f"Emailed {len(new_jobs)} new matches to {recipient}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    all_jobs = fetch_adzuna_jobs() + fetch_arbeitnow_jobs()
    print(f"Fetched {len(all_jobs)} raw results.")

    eligible = [j for j in all_jobs if is_eligible(j)]
    print(f"{len(eligible)} passed eligibility filter.")

    seen = load_seen_ids()
    new_jobs = [j for j in eligible if j["id"] not in seen]
    print(f"{len(new_jobs)} are new (not seen before).")

    if new_jobs:
        send_email(new_jobs)
        seen.update(j["id"] for j in new_jobs)
        save_seen_ids(seen)
    else:
        print("No new matches this run.")


if __name__ == "__main__":
    main()
