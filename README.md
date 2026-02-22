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

## Frontend test environment (Vite + Vitest)

A separate Vite workspace was added in [frontend](frontend) so you can run fast frontend tests.

1. Install frontend dependencies:

	cd frontend
	npm install

2. Run tests once:

	npm test

3. Run tests in watch mode:

	npm run test:watch