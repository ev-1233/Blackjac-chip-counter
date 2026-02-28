# Blackjack Chip Counter (Simple Flask Score Tracker)

This project is now a simple Flask app that lets you:

- Add players
- Increase/decrease player scores
- Remove players
- Reset all scores

Scores are stored in a local SQLite database file (`scores.db`) so they persist between runs.

## Dev Container (recommended for contributors)

This repo includes a VS Code Dev Container at [.devcontainer/devcontainer.json](.devcontainer/devcontainer.json).

You only need Docker + VS Code (with Dev Containers extension). No local Python, pip, Flask, Node, or npm setup is required.

1. Open the repo in VS Code.
2. Run **Dev Containers: Reopen in Container**.
3. Wait for first-time setup to finish (it creates `.venv`, installs Python deps, and runs `npm install`).
4. Set a strong secret key:

	export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

5. Start the app:

	npm run dev

6. Open:

	http://127.0.0.1:5000

## Run locally

1. Create and activate a virtual environment.
2. Install dependencies:

	pip install -r requirements.txt

3. Set a strong secret key:

	export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

4. Start the app:

	python app.py

5. Open the app in your browser:

	http://127.0.0.1:5000

Optional (same thing via npm script):

	npm run dev

## Run with Docker only (no local Python/npm install)

### Start app

Set a strong secret key first:

	export SECRET_KEY="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"

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
