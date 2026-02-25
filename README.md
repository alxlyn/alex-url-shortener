# Alex URL Shortener

Built as a backend systems project to deepen understanding of web architecture, database persistence, and request lifecycle management.

A production-ready URL shortener written in Python using Flask and PostgreSQL, implementing collision-safe short code generation, click analytics, and a statistics dashboard.

## Project Summary
This project implements a fully functional URL shortener with persistent storage, analytics tracking, and a minimal user interface.

The application supports short link generation, automatic collision handling, server-side validation, click tracking, and statistics visualization.

The focus of this project was building a clean backend architecture, handling edge cases properly, and implementing production-style safety mechanisms such as collision retries and URL normalization.

## Features

- Shorten long URLs
- Persistent storage (PostgreSQL)
- Collision-safe short code generation
- Click tracking and timestamp metadata
- Stats page per link
- Top links leaderboard
- Server-side URL validation

## Known Limitations

1. No authentication / user accounts
2. No rate limiting
3. No custom alias feature (intentionally excluded for scope control)
4. Minimal UI styling

## What I Learned

- Input validation should be handled server-side, not only by client-side HTML attributes.
- Schema evolution requires safe migration strategies to avoid data loss.
- Click tracking requires careful ordering of read/update operations.
- Simplicity often leads to cleaner architecture and easier debugging.
- Clean commit history and structured code matter as much as features.

## Project Structure

    app.py                               # Flask application & routes
    templates/                           # HTML templates
    static/                              # Shared styling
    scripts/init_postgres.sql            # PostgreSQL schema initialization
    scripts/migrate_sqlite_to_postgres.py# SQLite -> PostgreSQL data migration
    requirements.txt
    Procfile                             # Deployment configuration

## Design Decisions

- Used PostgreSQL for reliable persistence and easier production scaling.
- Implemented retry-based collision handling using database PRIMARY KEY constraints.
- Used server-side URL normalization instead of relying on browser validation.
- Added a SQLite-to-Postgres migration script for existing local data.
- Separated route logic from utility functions for readability.
- Prioritized clarity, correctness, and maintainability over premature optimization.

## Endpoints

- `/` - Homepage
- `/shorten` - POST route to create short links
- `/<code>` - Redirect to original URL
- `/stats/<code>` - Statistics page for a link
- `/top` - Top 10 most clicked links

### Clone Repository

```bash
git clone https://github.com/alxlyn/alex-url-shortener.git
cd alex-url-shortener
```

### Virtual Environment and Dependencies

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Set Database URL

```bash
export DATABASE_URL=postgresql://localhost/url_shortener
```

### Create Local Postgres Database

```bash
createdb url_shortener
```

### Run App

```bash
python3 app.py
```

Visit: `http://127.0.0.1:5000`

## Requirements

- Python 3.10+
- Flask
- PostgreSQL
- gunicorn (for deployment)

## Uniqueness Validation (10,000 links)

Run:

```bash
export DATABASE_URL=postgresql://localhost/url_shortener
python scripts/validate_uniqueness.py --count 10000
```