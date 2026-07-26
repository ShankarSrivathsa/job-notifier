"""
Job Application Notifier
Searches for ML/AI/Data roles across free job APIs, filters for entry-level
eligibility, skips jobs already seen, and emails new matches.

Runs standalone or via GitHub Actions (see .github/workflows/job_notifier.yml).
"""

import json
import os
import re
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

import requests

# Whole-word matches only — plain "in" checks let "ai" match inside "retail",
# "ml" match inside random text, etc. This avoids that.
ROLE_WORD_PATTERN = re.compile(r"\b(machine learning|data scien\w*|data analy\w*|\bai\b|\bml\b)\b", re.IGNORECASE)


def contains_role_keyword(text):
    return bool(ROLE_WORD_PATTERN.search(text))

def detect_job_type(job):
    text = f"{job['title']} {job.get('description', '')}".lower()
    if re.search(r"\bintern(ship)?\b", text):
        return "Internship"
    if re.search(r"\bpart[- ]time\b", text):
        return "Part-time"
    return "Full-time"


def detect_work_mode(job):
    text = f"{job['title']} {job.get('description', '')} {job.get('location', '')}".lower()
    if job.get("is_remote"):
        return "Remote"
    if re.search(r"\bhybrid\b", text):
        return "Hybrid"
    if re.search(r"\bremote\b", text):
        return "Remote"
    return "On-site"

def is_internship_like(job):
    text = f"{job['title']} {job.get('description', '')}".lower()
    return (
        detect_job_type(job) == "Internship"
        or "trainee" in text
        or "graduate" in text
        or "new grad" in text
    )
    
def clean_snippet(description, max_len=220):
    """Strip HTML tags and trim to a short preview."""
    text = re.sub(r"<[^>]+>", " ", description or "")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rsplit(" ", 1)[0] + "..."
    return text


# ---------------------------------------------------------------------------
# Config — edit these to tune your search
# ---------------------------------------------------------------------------

SEARCH_KEYWORDS = [
    "Machine Learning Engineer Associate",
    "ML Engineer Fresher",
    "Associate Machine Learning Engineer",
    "Junior Machine Learning Engineer",
    "Machine Learning Engineer - New Grad",
    "AI/ML Engineer Trainee",
    "Graduate Engineer Trainee AI ML",
    "AI Engineer Fresher",
    "Applied ML Engineer Associate",
    "ML Ops Engineer Fresher",
    "AI/ML Developer Entry Level",
    "Machine Learning Intern",
    "AI Research Associate",
]

# Words that suggest a role is actually entry-level / open to you
ELIGIBLE_HINTS = [
    "intern", "internship", "fresher", "entry level", "entry-level",
    "graduate", "junior", "trainee", "0-1 year", "0-2 years", "campus",
    "associate", "new grad", "graduate-engineer-trainee"
]

# Words that mean "skip this, it's not for you right now"
EXCLUDE_HINTS = [
    "senior", "sr.", "lead", "principal", "staff engineer", "manager",
    "5+ years", "6+ years", "7+ years", "8+ years", "10+ years",
    "director", "head of",
]

# Catches "2-4 years", "3+ years", "minimum 2 years experience", etc.
EXPERIENCE_PATTERN = re.compile(
    r"(\d+)\s*(?:\+|\s*-\s*\d+)?\s*(?:years?|yrs?)\s*(?:of\s*)?(?:experience|exp)\b",
    re.IGNORECASE,
)

MAX_YEARS_EXPERIENCE = 1 # bump to 2 if you want to include 2-year-min roles too

OWNERSHIP_HINTS = [
    "design and build", "own the", "production-grade", "architect",
    "define the roadmap", "drive the strategy", "mentor",
]

def has_ownership_language(text):
    return any(hint in text for hint in OWNERSHIP_HINTS)


def exceeds_experience_cap(text):
    for match in EXPERIENCE_PATTERN.finditer(text):
        if int(match.group(1)) > MAX_YEARS_EXPERIENCE:
            return True
    return False

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
                    "is_remote": False,
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
            text_blob = f"{title} {tags}"
            if not contains_role_keyword(text_blob):
                continue
            jobs.append({
                "id": f"arbeitnow_{r.get('slug')}",
                "title": title,
                "company": r.get("company_name", "Unknown"),
                "location": r.get("location", "") or "Not specified",
                "is_remote": bool(r.get("remote")),
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
    text = f"{job['title']} {job['description']}"
    lower = text.lower()

    # Role relevance is now mandatory, not optional — fixes marketing/BA
    # interns slipping through just because they say "intern".
    if not contains_role_keyword(text):
        return False
    if any(bad in lower for bad in EXCLUDE_HINTS):
        return False
    if exceeds_experience_cap(text):
        return False
    if has_ownership_language(lower):
        return False
    if any(hint in lower for hint in ELIGIBLE_HINTS):
        return True
    return False

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
    msg["Subject"] = f"{len(new_jobs)} new Job role(s) matched"
    msg["From"] = sender
    msg["To"] = recipient

    def render_job(j):
        snippet = clean_snippet(j.get("description", ""))
        job_type = detect_job_type(j)
        work_mode = detect_work_mode(j)
        return (
            f"<p><b>{j['title']}</b> — {j['company']}<br>"
            f"{j['location']} · <b>{job_type}</b> · <b>{work_mode}</b> · via {j['source']}<br>"
            f"<span style='color:#555'>{snippet}</span><br>"
            f"<a href='{j['url']}'>{j['url']}</a></p>"
        )

    internships = [j for j in new_jobs if is_internship_like(j)]
    others = [j for j in new_jobs if not is_internship_like(j)]

    sections = []

    if internships:
        sections.append(
            "<h2 style='color:#0a7d3c;border-bottom:2px solid #0a7d3c;padding-bottom:4px;'>"
            f"🎓 Internships ({len(internships)})</h2>"
            + "<hr>".join(render_job(j) for j in internships)
        )

    if others:
        sections.append(
            "<h2 style='color:#333;border-bottom:2px solid #333;padding-bottom:4px;margin-top:30px;'>"
            f"💼 Full-time Roles ({len(others)})</h2>"
            + "<hr>".join(render_job(j) for j in others)
        )

    html = f"<html><body>{''.join(sections)}</body></html>"
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
