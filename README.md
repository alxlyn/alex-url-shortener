# Alex URL Shortener

A production-ready URL shortener built with Flask and SQLite.

## Features

- Shorten long URLs
- Persistent storage (SQLite)
- Collision-safe short code generation
- Click tracking and timestamp metadata
- Stats page per link
- Top links leaderboard
- Server-side URL validation

## Tech Stack

- Python
- Flask
- SQLite
- Gunicorn (for deployment)

## Running Locally

```bash
git clone <repo-url>
cd Alex-URL-Shortener
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 app.py