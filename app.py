# SPDX-FileCopyrightText: 2026 Evan McKeown
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
import sqlite3
import time
import uuid
from pathlib import Path

from flask import Flask, flash, g, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
# SQLite file path. Can be overridden with DATABASE_PATH.
DATABASE = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "scores.db")))
# How long an inactive game is kept before automatic deletion.
GAME_TTL_DAYS = int(os.getenv("GAME_TTL_DAYS", "30"))
GAME_TTL_SECONDS = GAME_TTL_DAYS * 24 * 60 * 60

app = Flask(__name__)
app.config["SECRET_KEY"] = "dev-secret-key-change-me"


def get_db() -> sqlite3.Connection:
    # One SQLite connection per request context (Flask `g`).
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def get_owner_id() -> str:
    # `owner_id` is stored in the user session cookie.
    # The cookie does NOT store scores; it only identifies which server-side rows belong
    # to this browser/session.
    owner_id = session.get("owner_id")
    if not owner_id:
        owner_id = uuid.uuid4().hex
        session["owner_id"] = owner_id
    return owner_id


def touch_owner_session(db: sqlite3.Connection, owner_id: str) -> None:
    # Upsert the last active timestamp for this game/session.
    now = int(time.time())
    db.execute(
        """
        INSERT INTO owner_sessions (owner_id, last_seen_at)
        VALUES (?, ?)
        ON CONFLICT(owner_id) DO UPDATE SET last_seen_at = excluded.last_seen_at
        """,
        (owner_id, now),
    )


def prune_expired_games(db: sqlite3.Connection) -> None:
    # Remove data for sessions inactive longer than the TTL.
    # This deletes both player rows and the owner session metadata.
    cutoff = int(time.time()) - GAME_TTL_SECONDS
    db.execute(
        "DELETE FROM players WHERE owner_id IN (SELECT owner_id FROM owner_sessions WHERE last_seen_at < ?)",
        (cutoff,),
    )
    db.execute("DELETE FROM owner_sessions WHERE last_seen_at < ?", (cutoff,))


def init_db() -> None:
    # Startup schema init/migration:
    # - players table stores actual score data
    # - owner_sessions tracks last activity for expiry cleanup
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    now = int(time.time())

    table_exists = db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'players'"
    ).fetchone()

    if table_exists is None:
        # New schema: scores are isolated per `owner_id`.
        db.execute(
            """
            CREATE TABLE players (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id TEXT NOT NULL,
                name TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                UNIQUE(owner_id, name)
            )
            """
        )
    else:
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(players)").fetchall()
        }
        if "owner_id" not in columns:
            # One-time migration from old shared schema to per-owner schema.
            # Existing rows are tagged as `legacy` owner.
            db.execute(
                """
                CREATE TABLE players_new (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    owner_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    score INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(owner_id, name)
                )
                """
            )
            db.execute(
                """
                INSERT INTO players_new (name, score, owner_id)
                SELECT name, score, 'legacy'
                FROM players
                """
            )
            db.execute("DROP TABLE players")
            db.execute("ALTER TABLE players_new RENAME TO players")

    db.execute(
        """
        CREATE TABLE IF NOT EXISTS owner_sessions (
            owner_id TEXT PRIMARY KEY,
            last_seen_at INTEGER NOT NULL
        )
        """
    )
    db.execute(
        # Ensure every existing owner_id has a session record so cleanup works.
        """
        INSERT OR IGNORE INTO owner_sessions (owner_id, last_seen_at)
        SELECT DISTINCT owner_id, ?
        FROM players
        """,
        (now,),
    )

    db.commit()
    db.close()


def update_score(player_name: str, delta: int, owner_id: str | None = None) -> bool:
    """Update a player's score by name for the current owner.

    Usage inside request handlers: `update_score("Alice", 25)`.
    Returns True when a matching player was updated.
    """
    db = get_db()
    resolved_owner_id = owner_id or get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, resolved_owner_id)
    result = db.execute(
        "UPDATE players SET score = score + ? WHERE name = ? AND owner_id = ?",
        (delta, player_name, resolved_owner_id),
    )
    db.commit()
    return result.rowcount > 0


@app.teardown_appcontext
def close_db(_error: BaseException | None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


@app.get("/")
def index():
    db = get_db()
    owner_id = get_owner_id()
    # Keep storage small by deleting expired games, then mark this game as active.
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    players = db.execute(
        """
        -- Only load scores owned by this session's owner_id.
        SELECT id, name, score
        FROM players
        WHERE owner_id = ?
        ORDER BY score DESC, name ASC
        """,
        (owner_id,),
    ).fetchall()
    db.commit()
    return render_template("index.html", players=players)


@app.post("/players")
def add_player():
    name = request.form.get("name", "").strip()
    if not name:
        flash("Player name cannot be empty.")
        return redirect(url_for("index"))

    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    try:
        db.execute(
            # Save player row under this owner_id only.
            "INSERT INTO players (owner_id, name, score) VALUES (?, ?, 0)",
            (owner_id, name),
        )
        db.commit()
        flash(f"Added player: {name}")
    except sqlite3.IntegrityError:
        flash("That player already exists.")

    return redirect(url_for("index"))


@app.post("/players/<int:player_id>/update", endpoint="update_score")
def update_score_route(player_id: int):
    raw_delta = request.form.get("delta", "0").strip()
    try:
        delta = int(raw_delta)
    except ValueError:
        flash("Score change must be a whole number.")
        return redirect(url_for("index"))

    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    row = db.execute(
        # Prevent cross-user access by matching both id and owner_id.
        "SELECT name FROM players WHERE id = ? AND owner_id = ?",
        (player_id, owner_id),
    ).fetchone()
    if row is None:
        flash("Player not found.")
        return redirect(url_for("index"))

    update_score(row["name"], delta, owner_id=owner_id)
    flash(f"Updated {row['name']} by {delta:+d} points.")
    return redirect(url_for("index"))


@app.post("/players/<int:player_id>/delete")
def delete_player(player_id: int):
    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    row = db.execute(
        # Prevent cross-user deletes by matching both id and owner_id.
        "SELECT name FROM players WHERE id = ? AND owner_id = ?",
        (player_id, owner_id),
    ).fetchone()
    if row is None:
        flash("Player not found.")
        return redirect(url_for("index"))

    db.execute("DELETE FROM players WHERE id = ? AND owner_id = ?", (player_id, owner_id))
    db.commit()
    flash(f"Removed {row['name']}.")
    return redirect(url_for("index"))


@app.post("/reset")
def reset_scores():
    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    # Reset only this owner's scores.
    db.execute("UPDATE players SET score = 0 WHERE owner_id = ?", (owner_id,))
    db.commit()
    flash("All scores reset to 0.")
    return redirect(url_for("index"))


init_db()


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host=host, port=port, debug=debug)
