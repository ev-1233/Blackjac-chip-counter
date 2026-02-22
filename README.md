# Blackjack Chip Counter (Simple Flask Score Tracker)

This project is now a simple Flask app that lets you:

- Add players
- Increase/decrease player scores
- Remove players
- Reset all scores

Scores are stored in a local SQLite database file (`scores.db`) so they persist between runs.

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies:

	pip install -r requirements.txt

3. Start the app:

	python app.py

4. Open the app in your browser:

	http://127.0.0.1:5000

Optional (same thing via npm script):

	npm run dev

## Run with Docker only (no local Python/npm install)

### Start app

	docker compose up --build app

Open:

- Backend app: http://127.0.0.1:5000

### Notes

- SQLite data is persisted in Docker volume `db_data`.
- Stop everything with:

	docker compose down

## License header automation (Apache-2.0 SPDX)

This repo includes an SPDX header automation script.
It enforces both `SPDX-FileCopyrightText: 2026 Evan McKeown`
and `SPDX-License-Identifier: Apache-2.0`.

- Add missing headers:

	npm run license:apply

- Check headers (non-zero exit if missing):

	npm run license:check

Optional: enforce on every commit with pre-commit:

	pip install pre-commit
	pre-commit install

This repo also includes a built-in Git hook at [.githooks/pre-commit](.githooks/pre-commit)
that auto-applies SPDX headers to staged files during commit.

Enable it once per clone:

	git config core.hooksPath .githooks
