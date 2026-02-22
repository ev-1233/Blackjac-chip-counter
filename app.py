from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, url_for

BASE_DIR = Path(__file__).resolve().parent
DATABASE = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "scores.db")))

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key-change-me"


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db() -> None:
    db = sqlite3.connect(DATABASE)
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            score INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    db.commit()
    db.close()


@app.teardown_appcontext
def close_db(_error: BaseException | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.get("/")
def index():
    db = get_db()
    players = db.execute(
        "SELECT id, name, score FROM players ORDER BY score DESC, name ASC"
    ).fetchall()
    return render_template("index.html", players=players)


@app.post("/players")
def add_player():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Player name cannot be empty.")
        return redirect(url_for("index"))

    db = get_db()
    try:
        db.execute("INSERT INTO players (name, score) VALUES (?, 0)", (name,))
        db.commit()
        flash(f"Added player: {name}")
    except sqlite3.IntegrityError:
        flash("That player already exists.")

    return redirect(url_for("index"))


@app.post("/players/<int:player_id>/update")
def update_score(player_id: int):
    raw_delta = request.form.get("delta", "0").strip()
    try:
        delta = int(raw_delta)
    except ValueError:
        flash("Score change must be a whole number.")
        return redirect(url_for("index"))

    db = get_db()
    row = db.execute("SELECT name FROM players WHERE id = ?", (player_id,)).fetchone()
    if row is None:
        flash("Player not found.")
        return redirect(url_for("index"))

    db.execute("UPDATE players SET score = score + ? WHERE id = ?", (delta, player_id))
    db.commit()
    flash(f"Updated {row['name']} by {delta:+d} points.")
    return redirect(url_for("index"))


@app.post("/players/<int:player_id>/delete")
def delete_player(player_id: int):
    db = get_db()
    row = db.execute("SELECT name FROM players WHERE id = ?", (player_id,)).fetchone()
    if row is None:
        flash("Player not found.")
        return redirect(url_for("index"))

    db.execute("DELETE FROM players WHERE id = ?", (player_id,))
    db.commit()
    flash(f"Removed {row['name']}.")
    return redirect(url_for("index"))


@app.post("/reset")
def reset_scores():
    db = get_db()
    db.execute("UPDATE players SET score = 0")
    db.commit()
    flash("All scores reset to 0.")
    return redirect(url_for("index"))


if __name__ == "__main__":
    init_db()
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
