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
secret_key = os.getenv("SECRET_KEY")
if not secret_key:
    raise RuntimeError("SECRET_KEY environment variable is required.")
app.config["SECRET_KEY"] = secret_key


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
        INSERT INTO owner_sessions (owner_id, last_seen_at, game_started, current_player_id)
        VALUES (?, ?, 0, NULL)
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
            last_seen_at INTEGER NOT NULL,
            game_started INTEGER NOT NULL DEFAULT 0,
            current_player_id INTEGER
        )
        """
    )

    owner_session_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(owner_sessions)").fetchall()
    }
    if "game_started" not in owner_session_columns:
        db.execute(
            "ALTER TABLE owner_sessions ADD COLUMN game_started INTEGER NOT NULL DEFAULT 0"
        )
    if "current_player_id" not in owner_session_columns:
        db.execute("ALTER TABLE owner_sessions ADD COLUMN current_player_id INTEGER")

    db.execute(
        # Ensure every existing owner_id has a session record so cleanup works.
        """
        INSERT OR IGNORE INTO owner_sessions (owner_id, last_seen_at, game_started, current_player_id)
        SELECT DISTINCT owner_id, ?, 0, NULL
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


def get_owner_state(db: sqlite3.Connection, owner_id: str) -> sqlite3.Row:
    state = db.execute(
        """
        SELECT owner_id, last_seen_at, game_started, current_player_id
        FROM owner_sessions
        WHERE owner_id = ?
        """,
        (owner_id,),
    ).fetchone()
    if state is not None:
        return state

    now = int(time.time())
    db.execute(
        """
        INSERT INTO owner_sessions (owner_id, last_seen_at, game_started, current_player_id)
        VALUES (?, ?, 0, NULL)
        """,
        (owner_id, now),
    )
    db.commit()
    return db.execute(
        """
        SELECT owner_id, last_seen_at, game_started, current_player_id
        FROM owner_sessions
        WHERE owner_id = ?
        """,
        (owner_id,),
    ).fetchone()


def get_players_for_owner(db: sqlite3.Connection, owner_id: str) -> list[sqlite3.Row]:
    return db.execute(
        """
        SELECT id, name, score
        FROM players
        WHERE owner_id = ?
        ORDER BY id ASC
        """,
        (owner_id,),
    ).fetchall()


def get_next_player_id(players: list[sqlite3.Row], current_player_id: int | None) -> int | None:
    if not players:
        return None
    if current_player_id is None:
        return players[0]["id"]

    player_ids = [player["id"] for player in players]
    if current_player_id not in player_ids:
        return players[0]["id"]

    current_index = player_ids.index(current_player_id)
    next_index = (current_index + 1) % len(player_ids)
    return player_ids[next_index]




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
    players = get_players_for_owner(db, owner_id)
    state = get_owner_state(db, owner_id)
    game_started = bool(state["game_started"])
    current_player_id = state["current_player_id"]

    if game_started:
        current_player_ids = {player["id"] for player in players}
        if current_player_id not in current_player_ids and players:
            current_player_id = players[0]["id"]
            db.execute(
                "UPDATE owner_sessions SET current_player_id = ? WHERE owner_id = ?",
                (current_player_id, owner_id),
            )

    current_player = next(
        (player for player in players if player["id"] == current_player_id),
        None,
    )
    db.commit()
    return render_template(
        "index.html",
        players=players,
        game_started=game_started,
        current_player=current_player,
    )


@app.post("/players")
def add_player():
    name = request.form.get("name", "").strip()
    raw_starting_score = request.form.get("starting_score", "0").strip()
    if not name:
        flash("Player name cannot be empty.")
        return redirect(url_for("index"))

    try:
        starting_score = int(raw_starting_score)
    except ValueError:
        flash("Starting score must be a whole number.")
        return redirect(url_for("index"))

    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    state = get_owner_state(db, owner_id)
    if state["game_started"]:
        flash("Cannot add players after the game has started.")
        return redirect(url_for("index"))
    try:
        db.execute(
            # Save player row under this owner_id only.
            "INSERT INTO players (owner_id, name, score) VALUES (?, ?, ?)",
            (owner_id, name, starting_score),
        )
        db.commit()
        flash(f"Added player: {name} (start {starting_score})")
    except sqlite3.IntegrityError:
        flash("That player already exists.")

    return redirect(url_for("index"))


@app.post("/game/start")
def start_game():
    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    players = get_players_for_owner(db, owner_id)
    if not players:
        flash("Add at least one player before starting the game.")
        return redirect(url_for("index"))

    first_player_id = players[0]["id"]
    db.execute(
        """
        UPDATE owner_sessions
        SET game_started = 1, current_player_id = ?
        WHERE owner_id = ?
        """,
        (first_player_id, owner_id),
    )
    db.commit()
    flash(f"Game started. {players[0]['name']} goes first.")
    return redirect(url_for("index"))


@app.post("/game/end")
def end_game():
    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    db.execute(
        """
        UPDATE owner_sessions
        SET game_started = 0, current_player_id = NULL
        WHERE owner_id = ?
        """,
        (owner_id,),
    )
    db.commit()
    flash("Game ended. You can edit players and start again.")
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
    state = get_owner_state(db, owner_id)
    if not state["game_started"]:
        flash("Start the game before taking turns.")
        return redirect(url_for("index"))

    if state["current_player_id"] != player_id:
        flash("It is not that player's turn.")
        return redirect(url_for("index"))

    row = db.execute(
        # Prevent cross-user access by matching both id and owner_id.
        "SELECT name FROM players WHERE id = ? AND owner_id = ?",
        (player_id, owner_id),
    ).fetchone()
    if row is None:
        flash("Player not found.")
        return redirect(url_for("index"))

    update_score(row["name"], delta, owner_id=owner_id)
    players = get_players_for_owner(db, owner_id)
    next_player_id = get_next_player_id(players, player_id)
    db.execute(
        "UPDATE owner_sessions SET current_player_id = ? WHERE owner_id = ?",
        (next_player_id, owner_id),
    )
    db.commit()
    next_player = next(
        (player for player in players if player["id"] == next_player_id),
        None,
    )
    if next_player is None:
        flash(f"Updated {row['name']} by {delta:+d} points.")
    else:
        flash(f"Updated {row['name']} by {delta:+d} points. Next: {next_player['name']}.")
    return redirect(url_for("index"))


@app.post("/players/<int:player_id>/delete")
def delete_player(player_id: int):
    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    state = get_owner_state(db, owner_id)
    if state["game_started"]:
        flash("Cannot remove players after the game has started.")
        return redirect(url_for("index"))
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


@app.post("/turn/update")
def update_turn_score():
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
    state = get_owner_state(db, owner_id)
    if not state["game_started"]:
        flash("Start the game before taking turns.")
        return redirect(url_for("index"))

    players = get_players_for_owner(db, owner_id)
    if not players:
        flash("No players found.")
        return redirect(url_for("index"))

    current_player_id = state["current_player_id"]
    current_player = next(
        (player for player in players if player["id"] == current_player_id),
        None,
    )
    if current_player is None:
        current_player = players[0]
        current_player_id = current_player["id"]

    updated = update_score(current_player["name"], delta, owner_id=owner_id)
    if not updated:
        flash("Current player not found.")
        return redirect(url_for("index"))

    next_player_id = get_next_player_id(players, current_player_id)
    db.execute(
        "UPDATE owner_sessions SET current_player_id = ? WHERE owner_id = ?",
        (next_player_id, owner_id),
    )
    db.commit()

    next_player = next(
        (player for player in players if player["id"] == next_player_id),
        None,
    )
    if next_player is None:
        flash(f"Updated {current_player['name']} by {delta:+d} points.")
    else:
        flash(
            f"Updated {current_player['name']} by {delta:+d} points. Next: {next_player['name']}."
        )
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
