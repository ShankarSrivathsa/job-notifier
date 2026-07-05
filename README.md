# Job Notifier — ML/AI/Data roles

Searches Adzuna (India) + Arbeitnow (remote) daily, filters for entry-level/
intern/fresher roles, and emails you the new ones. Runs free on GitHub
Actions — no laptop needed once it's set up.

## Setup (about 15 minutes, one-time)

### 1. Create a new GitHub repo
Push this whole folder to a **private** GitHub repo (private so your
secrets/config aren't public). If you're using Claude Code or the GitHub
web UI, just create a repo called `job-notifier` and upload these files.

### 2. Get free Adzuna API keys
1. Go to https://developer.adzuna.com/ and sign up (free).
2. Create an app — you'll get an `App ID` and `App Key`.

### 3. Create a Gmail App Password
Regular Gmail passwords won't work for this — you need an App Password:
1. Turn on 2-Step Verification on your Google Account (Security settings) if not already on.
2. Go to https://myaccount.google.com/apppasswords
3. Generate a password for "Mail" — copy the 16-character code.

### 4. Add secrets to your GitHub repo
In your repo: **Settings → Secrets and variables → Actions → New repository secret**.
Add these four:

| Secret name | Value |
|---|---|
| `ADZUNA_APP_ID` | from step 2 |
| `ADZUNA_APP_KEY` | from step 2 |
| `GMAIL_ADDRESS` | your Gmail address |
| `GMAIL_APP_PASSWORD` | the 16-char app password from step 3 |
| `NOTIFY_EMAIL` | (optional) where to send results, defaults to GMAIL_ADDRESS |

### 5. Enable the workflow
The workflow file is already at `.github/workflows/job_notifier.yml`. Once
pushed, go to the **Actions** tab in your repo — you may need to click
"I understand my workflows, enable them." It'll then run automatically
every day at 9 AM IST.

### 6. Test it immediately (don't wait for tomorrow)
Actions tab → "Job Notifier" workflow → **Run workflow** button. Check the
logs, then check your inbox.

## Tuning it

Open `job_notifier.py` and edit:
- `SEARCH_KEYWORDS` — the role searches it runs
- `ELIGIBLE_HINTS` / `EXCLUDE_HINTS` — the keyword filter logic
- Cron schedule in the workflow file if you want a different time

## Honest limitations

- This is a keyword filter, not a real eligibility check — it can't read
  your resume against a JD. Expect some noise; that's normal.
- LinkedIn/Naukri aren't included — no free, ToS-compliant API exists for
  them. This covers Adzuna's India listings and Arbeitnow's remote tech
  board, which is a real but partial slice of what's out there. Keep
  checking LinkedIn/Naukri manually alongside this.
- `seen_jobs.json` is how it avoids re-emailing the same job — the workflow
  commits it back to the repo after each run, so don't edit that file by
  hand.
