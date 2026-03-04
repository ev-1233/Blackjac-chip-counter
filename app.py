# SPDX-FileCopyrightText: 2026 Evan McKeown
# SPDX-License-Identifier: Apache-2.0

# Enables advanced type hinting (e.g., using `list[int]` instead of `List[int]`) in older Python versions
from __future__ import annotations

import os           # Used for interacting with the operating system, like reading environment variables
import sqlite3      # The built-in library for interacting with SQLite databases
import time         # Used for time-related operations (like timestamps for tracking inactivity)
import uuid         # Used for generating unique identifiers (UUIDs), specifically for anonymous user sessions
import secrets      # Used for generating cryptographically secure random strings
from pathlib import Path # Used for robust file and directory path management (object-oriented paths)

# Import necessary components from the Flask framework:
# Flask: The core application class used to initialize the web server
# flash: Used to store messages (like "Added player") that are shown to the user on the next page load
# g: A special object that stores data globally but *only* for the duration of a single web request (good for holding the DB connection)
# redirect: Used to send the user's browser to a different URL (e.g., after submitting a form)
# render_template: Used to load HTML files from the `templates/` folder and inject dynamic variables
# request: Contains all the data the user sent with their HTTP request (URL parameters, form data, etc.)
# session: A secure, encrypted cookie that stores data across different requests from the exact same user/browser
# url_for: Automatically generates URLs for specific functions, preventing hardcoded paths
from flask import Flask, flash, g, redirect, render_template, request, session, url_for

# Define the absolute path to the directory containing this script
BASE_DIR = Path(__file__).resolve().parent

# Define the path to the internal SQLite database file. 
# It checks if there's an environment variable 'DATABASE_PATH' and uses it; if not, defaults to 'scores.db' in the base folder.
DATABASE = Path(os.getenv("DATABASE_PATH", str(BASE_DIR / "scores.db")))

# Define "Time To Live" (TTL) for games. If a game is inactive for this many days, it gets deleted to save space.
# It defaults to 30 days if 'GAME_TTL_DAYS' isn't set in the environment.
GAME_TTL_DAYS = int(os.getenv("GAME_TTL_DAYS", "30"))
# Convert the TTL from days into seconds, because time.time() works in seconds.
GAME_TTL_SECONDS = GAME_TTL_DAYS * 24 * 60 * 60

# Initialize the Flask web application
app = Flask(__name__)

# Fetch the secret key from the environment. The secret key is essential! 
# It is used by Flask to cryptographically sign session cookies, preventing users from tampering with their session data.
# If not provided, we generate a random secure token using `secrets.token_hex()`
# Warning: Generating a new token on every restart means active user sessions will be invalidated when the server reboots!
secret_key = os.getenv("SECRET_KEY", secrets.token_hex(32))

# Apply the securely fetched secret key to the app's configuration.
app.config["SECRET_KEY"] = secret_key


def get_db() -> sqlite3.Connection:
    """Gets the database connection for the current Flask request.
    If a connection hasn't been created yet for this request, it establishes a new one.
    """
    # The 'g' object provided by Flask stores data required for one specific request.
    # We maintain only one database connection per incoming HTTP request context.
    if "db" not in g:
        # Establish a new connection pointing to the predefined DATABASE path
        g.db = sqlite3.connect(DATABASE)
        # Configuring row_factory to sqlite3.Row makes the fetched rows behave like dictionaries.
        # So instead of row[0], you can access columns via row['column_name'].
        g.db.row_factory = sqlite3.Row
    
    return g.db


def get_owner_id() -> str:
    """Retrieves or creates a unique session identifier for the user.
    This links a generic browser to their specific data in the database.
    """
    # Attempt to retrieve 'owner_id' from the user's signed session cookie. 
    # Flask manages this cookie, and it's securely stored in their browser.
    owner_id = session.get("owner_id")
    
    # If the user has never visited us (or cleared cookies), 'owner_id' will be None.
    if not owner_id:
        # Generate a brand new, highly random UUID (Universally Unique Identifier).
        # We take the hexadecimal string version of it (e.g. "a1b2c3d4...")
        owner_id = uuid.uuid4().hex
        
        # Save this new UUID back into the user's secure session cookie for future visits!
        session["owner_id"] = owner_id
        
    return owner_id


def touch_owner_session(db: sqlite3.Connection, owner_id: str) -> None:
    """Updates the 'last_seen_at' timestamp for a user so their game isn't pruned.
    This effectively tells the system: "This user is still actively playing!"
    """
    # Grab the current UTC timestamp (seconds since epoch)
    now = int(time.time())
    
    # Execute an "upsert" (Insert or Update). 
    # Try inserting a new session record with 'last_seen_at' set to 'now'.
    # If a record with this 'owner_id' already exists (ON CONFLICT), update its timestamp instead.
    db.execute(
        """
        INSERT INTO owner_sessions (owner_id, last_seen_at, game_started, current_player_id)
        VALUES (?, ?, 0, NULL)
        ON CONFLICT(owner_id) DO UPDATE SET last_seen_at = excluded.last_seen_at
        """,
        (owner_id, now),
    )


def prune_expired_games(db: sqlite3.Connection) -> None:
    """Cleans up inactive games to stop the database from growing infinitely.
    Deletes both players and session configuration for older records.
    """
    # Determine the absolute earliest timestamp allowed. Any session older than this is "expired".
    cutoff = int(time.time()) - GAME_TTL_SECONDS
    
    # First, find and delete all rows in the 'players' table that belong to an expired session.
    db.execute(
        "DELETE FROM players WHERE owner_id IN (SELECT owner_id FROM owner_sessions WHERE last_seen_at < ?)",
        (cutoff,),
    )
    
    # Next, delete the actual tracking rows from 'owner_sessions' itself.
    db.execute("DELETE FROM owner_sessions WHERE last_seen_at < ?", (cutoff,))


def init_db() -> None:
    """Initializes the SQLite database tables and applies structural migrations if required.
    It builds the initial schema for handling segregated user game states or modifies
    legacy structures securely to maintain backwards compatibility.
    """
    
    # Normally we do 'get_db()' inside a route request, but this setup happens strictly 
    # before the server processes requests, so we must connect directly here.
    db = sqlite3.connect(DATABASE)
    db.row_factory = sqlite3.Row
    now = int(time.time())

    # Check the built-in 'sqlite_master' table (which catalogs everything in the database)
    # to find out if the 'players' table already exists.
    table_exists = db.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'players'"
    ).fetchone()

    # If 'table_exists' is None, it means this is a highly fresh installation 
    # and no 'players' table has been created yet.
    if table_exists is None:
        # Create a completely fresh 'players' table. 
        # Crucial Columns:
        # id: Automatically increments, primary way to identify a particular player uniquely.
        # owner_id: String linking a player solely to a specific web browser/user.
        # name: Player's visual display name.
        # score: Track their points/chips.
        # UNIQUE constraint: Ensures under the same owner_id, a specific player 'name' only gets stored once.
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
        # If the 'players' table DID exist... we must handle migrations (i.e. older versions of the app)
        # Fetch the detailed structure data (columns array) for 'players'.
        columns = {
            row["name"] for row in db.execute("PRAGMA table_info(players)").fetchall()
        }
        
        # If 'owner_id' is missing, it implies data exists from a much older version 
        # before the application offered "private rooms" or multi-player sessions via sessions.
        if "owner_id" not in columns:
            # We construct a new, temporary table 'players_new' matching the modern schema.
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
            # Port all older global data into this new table, appending a dummy 'legacy' owner ID.
            # This protects user data from being arbitrarily deleted upon migration.
            db.execute(
                """
                INSERT INTO players_new (name, score, owner_id)
                SELECT name, score, 'legacy'
                FROM players
                """
            )
            # Safely drop the outdated table.
            db.execute("DROP TABLE players")
            # Rename the robust replacement table to act as the primary structural piece.
            db.execute("ALTER TABLE players_new RENAME TO players")

    # Create the 'owner_sessions' table, mapping session IDs directly to game progression details.
    # It stores timestamps and turns (e.g. knowing who is taking their specific turn).
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

    # Perform another migration check specific to the 'owner_sessions' table, 
    # resolving potential missing columns in slightly older but post-legacy versions.
    owner_session_columns = {
        row["name"] for row in db.execute("PRAGMA table_info(owner_sessions)").fetchall()
    }
    
    # Adds a column stating if a specific user's game is currently ongoing (boolean flag logic 1 or 0)
    if "game_started" not in owner_session_columns:
        db.execute(
            "ALTER TABLE owner_sessions ADD COLUMN game_started INTEGER NOT NULL DEFAULT 0"
        )
        
    # Adds a linkage to keep track of whose actual "turn" it is (stores an integer linking to a player ID)
    if "current_player_id" not in owner_session_columns:
        db.execute("ALTER TABLE owner_sessions ADD COLUMN current_player_id INTEGER")

    # Final sanity check: Ensures there is a metadata row in 'owner_sessions' 
    # for EVERY unique 'owner_id' that exists inside the 'players' table. 
    # This ensures no games get lost or orphaned without timestamps.
    db.execute(
        """
        INSERT OR IGNORE INTO owner_sessions (owner_id, last_seen_at, game_started, current_player_id)
        SELECT DISTINCT owner_id, ?, 0, NULL
        FROM players
        """,
        (now,),
    )

    # Apply all database queries sequentially. Commit executes them.
    db.commit()
    # Close the database to relinquish file lock.
    db.close()


def update_score(player_name: str, delta: int, owner_id: str | None = None) -> bool:
    """Updates a specific player's score by adding or subtracting points.
    
    Args:
        player_name (str): The exact name of the player to update.
        delta (int): The amount to change the score by (positive or negative).
        owner_id (str | None): The session ID. Defaults to the current user's session if not provided.
        
    Returns:
        bool: True if exactly one matching player was successfully updated.
    """
    db = get_db()
    # Resolve the owner_id; if none was passed into the function, get it from the session.
    resolved_owner_id = owner_id or get_owner_id()
    
    # Housekeeping: delete old games to save space, and mark this session as recently active.
    prune_expired_games(db)
    touch_owner_session(db, resolved_owner_id)
    
    # Attempt to update the player in the database. 
    # The WHERE clause ensures we only update the player belonging to THIS specific user's session.
    result = db.execute(
        "UPDATE players SET score = score + ? WHERE name = ? AND owner_id = ?",
        (delta, player_name, resolved_owner_id),
    )
    db.commit() # Save the change to the database file.
    
    # result.rowcount will be 1 if it successfully found and updated a player, 0 otherwise.
    return result.rowcount > 0


def get_owner_state(db: sqlite3.Connection, owner_id: str) -> sqlite3.Row:
    """Retrieves the current metadata/settings for a user's game session.
    This includes whether the game is currently running, when they were last active, 
    and whose turn it currently is.
    """
    # Attempt to fetch the existing row from 'owner_sessions'
    state = db.execute(
        """
        SELECT owner_id, last_seen_at, game_started, current_player_id
        FROM owner_sessions
        WHERE owner_id = ?
        """,
        (owner_id,),
    ).fetchone()
    
    if state is not None:
        # If we successfully found their game state, return it immediately.
        return state

    # If 'state' is None, it means the user's session data is missing.
    # This shouldn't normally happen since 'touch_owner_session' creates it, 
    # but as a fallback, we explicitly insert a default "blank" session state.
    now = int(time.time())
    db.execute(
        """
        INSERT INTO owner_sessions (owner_id, last_seen_at, game_started, current_player_id)
        VALUES (?, ?, 0, NULL)
        """,
        (owner_id, now),
    )
    db.commit()
    
    # Now query it back from the database directly so it returns a proper sqlite3.Row object
    return db.execute(
        """
        SELECT owner_id, last_seen_at, game_started, current_player_id
        FROM owner_sessions
        WHERE owner_id = ?
        """,
        (owner_id,),
    ).fetchone()


def get_players_for_owner(db: sqlite3.Connection, owner_id: str) -> list[sqlite3.Row]:
    """Retrieves an ordered list of all players belonging to a specific user.
    Ordered ascending by 'id' so players generally appear in the order they were added.
    """
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
    """Calculates whose turn it is next.
    
    Args:
        players: A list of all players in the game (as sqlite3 rows).
        current_player_id: The ID of the player whose turn just finished.
        
    Returns:
        The integer ID of the next player in the rotation, or None if no players exist.
    """
    if not players:
        # Cannot determine a next turn if there are no players.
        return None
        
    if current_player_id is None:
        # If the game literally just started, default to the very first player added.
        return players[0]["id"]

    # Build a simple list of just the player IDs, maintaining the original order.
    player_ids = [player["id"] for player in players]
    
    # If the current player's ID isn't in the list (e.g., they were deleted mid-game),
    # fallback to the topmost player to avoid breaking the turn cycle.
    if current_player_id not in player_ids:
        return players[0]["id"]

    # Mathematical modulo trick for cyclical loops:
    # 1. Find the exact list index (0, 1, 2...) of the current player.
    # 2. Add 1 to step forward.
    # 3. % len(player_ids) ensures that if we reach the end of the list, it loops back to 0.
    current_index = player_ids.index(current_player_id)
    next_index = (current_index + 1) % len(player_ids)
    
    return player_ids[next_index]


# @app.teardown_appcontext is a Flask decorator. 
# It ensures that this function runs entirely automatically at the very end of EVERY web request,
# whether the request succeeded or crashed with an error. 
@app.teardown_appcontext
def close_db(_error: BaseException | None) -> None:
    """Closes the current request's database connection when the response is sent back.
    This prevents memory leaks and lock issues on the SQLite database.
    """
    # Try to safely remove 'db' from the global 'g' object. Returns None if 'db' wasn't set.
    db = g.pop("db", None)
    if db is not None:
        db.close() # Free up the connection!


# @app.get("/") makes this function handle HTTP GET requests to the root URL (e.g. http://127.0.0.1:5000/)
@app.get("/")
def index():
    """Renders the main dashboard for the user. 
    It fetches all their specific game data, determines if a game has started,
    and calculates whose turn it currently is.
    """
    # 1. Grab DB and uniquely identify the user visiting the page.
    db = get_db()
    owner_id = get_owner_id()
    
    # 2. Keep storage small by deleting expired games (everyone's)
    #    THEN immediately mark THIS specific user's game as recently active so it won't get deleted.
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    
    # 3. Pull out the primary data we need to display on the dashboard:
    players = get_players_for_owner(db, owner_id)       # Complete list of their players
    state = get_owner_state(db, owner_id)               # The metadata rules (turn, started/stopped)
    
    # `game_started` stored as an integer (0 or 1) in SQLite. We cast to Python boolean (True/False).
    game_started = bool(state["game_started"])
    current_player_id = state["current_player_id"]      # Represents whose turn it is.

    # 4. Corrective Logic: What if the game is 'started' but the current player went missing? 
    #    (e.g., deleted by a parallel connection, or a bug)
    if game_started:
        # Build a set of all valid player IDs to check against.
        current_player_ids = {player["id"] for player in players}
        
        # If the supposedly active player doesn't exist anymore, AND there are still people playing...
        if current_player_id not in current_player_ids and players:
            # Force the turn back to the very first person in the list.
            current_player_id = players[0]["id"]
            # Save this correction to the database so it's consistent for the next page load.
            db.execute(
                "UPDATE owner_sessions SET current_player_id = ? WHERE owner_id = ?",
                (current_player_id, owner_id),
            )

    # 5. Look through the `players` list and extract the full row details for the active player.
    #    `next()` with a generator expression acts like an inline search loop.
    #    Returns None if no match is found.
    current_player = next(
        (player for player in players if player["id"] == current_player_id),
        None,
    )
    
    # Commit any potential corrective changes made during step 4.
    db.commit()
    
    # 6. Finally, serve the 'index.html' document, heavily passing backend data 
    #    as template variables into the frontend HTML so Jinja2 can draw the interface.
    return render_template(
        "index.html",
        players=players,
        game_started=game_started,
        current_player=current_player,
    )


# @app.post creates an endpoint that purely accepts data (usually form submissions).
@app.post("/players")
def add_player():
    """Endpoint for adding a new player logically to the game.
    Reads player inputs via a standard web form.
    """
    # Grab the name from the submitted HTML form, falling back to empty string, and stripping extra spaces.
    name = request.form.get("name", "").strip()
    
    # Grab the requested starting chips/score. Defaults to "0" if empty.
    raw_starting_score = request.form.get("starting_score", "0").strip()
    
    # Validation 1: Was a name provided?
    if not name:
        flash("Player name cannot be empty.")
        # redirect(url_for('index')) seamlessly sends their browser right back to the root page
        return redirect(url_for("index"))

    # Validation 2: Is the score typed strictly as an integer number?
    try:
        starting_score = int(raw_starting_score)
    except ValueError:
        flash("Starting score must be a whole number.")
        return redirect(url_for("index"))

    # Connect to the DB and get session context
    db = get_db()
    owner_id = get_owner_id()
    
    # Pre-action maintenance and session timestamp update.
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    
    # Pre-action check: Has the game already started? 
    # Business rule: We do not allow people joining mid-game.
    state = get_owner_state(db, owner_id)
    if state["game_started"]:
        flash("Cannot add players after the game has started.")
        return redirect(url_for("index"))
        
    try:
        # Actually attempt to insert the new player into the main database!
        db.execute(
            # Crucially, save the player row strictly under THIS owner_id.
            "INSERT INTO players (owner_id, name, score) VALUES (?, ?, ?)",
            (owner_id, name, starting_score),
        )
        db.commit()
        # Uses Flask 'flash' queue to tell the user "Success!" upon reloading the page.
        flash(f"Added player: {name} (start {starting_score})")
    except sqlite3.IntegrityError:
        # Our `init_db` schema contained `UNIQUE(owner_id, name)`. 
        # If this constraint breaks, it raises an IntegrityError (Player name already used for this session).
        flash("That player already exists.")

    return redirect(url_for("index"))


@app.post("/game/start")
def start_game():
    #Sets the game state to 'started' so calculating scores and taking turns can begin.
    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    
    # Fetch all players linked to the current person.
    players = get_players_for_owner(db, owner_id)
    
    # Edge case: you cannot start a multiplayer game with nobody registered.
    if not players:
        flash("Add at least one player before starting the game.")
        return redirect(url_for("index"))

    # Select the very first player added (by ascending IDs) to take the first opening turn.
    first_player_id = players[0]["id"]
    
    # Toggle 'game_started' flag to 1 (True) and officially set 'current_player_id'.
    db.execute(
        """
        UPDATE owner_sessions
        SET game_started = 1, current_player_id = ?
        WHERE owner_id = ?
        """,
        (first_player_id, owner_id),
    )
    db.commit()
    
    # Tell user the game has now started!
    flash(f"Game started. {players[0]['name']} goes first.")
    return redirect(url_for("index"))


@app.post("/game/end")
def end_game():
    """Halts the current game, resetting the session to a 'configuration' mode 
    so users can add/remove players again.
    """
    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    
    # Revert session state variables back to stopped states.
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


# Note: The route URL contains `<int:player_id>`. This captures the URL portion dynamically
# and passes it straight into our Python function as an integer parameter.
# The 'endpoint' overrides the internal Flask name so `url_for('update_score', ...)` matches cleanly.
@app.post("/players/<int:player_id>/update", endpoint="update_score")
def update_score_route(player_id: int):
    """Processes a scoring change specifically submitted for an explicitly chosen player.
    It expects the change delta via an HTML form submission.
    """
    # Extract 'delta' from the form (the amount being added, or negative for subtracted).
    raw_delta = request.form.get("delta", "0").strip()
    
    # Must be integer conversion! You cannot earn 5.5 chips.
    try:
        delta = int(raw_delta)
    except ValueError:
        flash("Score change must be a whole number.")
        return redirect(url_for("index"))

    # Connect to DB and refresh session state cache.
    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    
    # Rule validation: Ensure the game has actually been marked as started.
    state = get_owner_state(db, owner_id)
    if not state["game_started"]:
        flash("Start the game before taking turns.")
        return redirect(url_for("index"))

    # Rule validation: Enforce turn order. Is it actually this player's specific turn?
    if state["current_player_id"] != player_id:
        flash("It is not that player's turn.")
        return redirect(url_for("index"))

    # Extra security fetch: Ensure the player ID given actually belongs to the current user's session.
    # Passing both 'id' and 'owner_id' strictly isolates users from manipulating other users' player IDs.
    row = db.execute(
        # Prevent cross-user access by matching both id and owner_id.
        "SELECT name FROM players WHERE id = ? AND owner_id = ?",
        (player_id, owner_id),
    ).fetchone()
    
    # If fetch returns nothing, it means they provided a tampered player_id URL.
    if row is None:
        flash("Player not found.")
        return redirect(url_for("index"))

    # Using the helper function we defined earlier, physically mutate their score with the parsed delta.
    update_score(row["name"], delta, owner_id=owner_id)
    
    # We must now figure out whose turn is next, advancing the "turn tracker".
    players = get_players_for_owner(db, owner_id)
    next_player_id = get_next_player_id(players, player_id)
    
    # Save the calculated "next player in queue" directly to the 'owner_sessions' tracking table.
    db.execute(
        "UPDATE owner_sessions SET current_player_id = ? WHERE owner_id = ?",
        (next_player_id, owner_id),
    )
    db.commit()
    
    # Find the next player's name so we can inform the user who is up next via the flash message.
    next_player = next(
        (player for player in players if player["id"] == next_player_id),
        None,
    )
    
    # +d formatter forcibly adds a "+" sign for positive numbers (e.g. "+5 points" vs "-5 points").
    if next_player is None:
        flash(f"Updated {row['name']} by {delta:+d} points.")
    else:
        flash(f"Updated {row['name']} by {delta:+d} points. Next: {next_player['name']}.")
        
    return redirect(url_for("index"))


@app.post("/players/<int:player_id>/delete")
def delete_player(player_id: int):
    """Deletes a specific player from the current user's session.
    Can only be done before a game officially starts.
    """
    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    state = get_owner_state(db, owner_id)
    
    # Business rule: Deleting players mid-game breaks turn calculations.
    # We strictly forbid deletion while game_started = 1.
    if state["game_started"]:
        flash("Cannot remove players after the game has started.")
        return redirect(url_for("index"))
        
    # Verify the specific player belongs strictly to this browser session.
    row = db.execute(
        # Prevent cross-user deletes by matching both id and owner_id.
        "SELECT name FROM players WHERE id = ? AND owner_id = ?",
        (player_id, owner_id),
    ).fetchone()
    
    if row is None:
        flash("Player not found.")
        return redirect(url_for("index"))

    # Execute the actual permanent deletion from the persistent SQLite database.
    db.execute("DELETE FROM players WHERE id = ? AND owner_id = ?", (player_id, owner_id))
    db.commit()
    
    flash(f"Removed {row['name']}.")
    return redirect(url_for("index"))


@app.post("/turn/update")
def update_turn_score():
    """An alternate endpoint that automatically updates whichever player's turn it *currently* is.
    Instead of passing a specific player ID, this endpoint figures out the active player first.
    """
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
    # The game must be started to have turns!
    if not state["game_started"]:
        flash("Start the game before taking turns.")
        return redirect(url_for("index"))

    players = get_players_for_owner(db, owner_id)
    if not players:
        flash("No players found.")
        return redirect(url_for("index"))

    # Determine who the "Active Player" actually is using the session state.
    current_player_id = state["current_player_id"]
    current_player = next(
        (player for player in players if player["id"] == current_player_id),
        None,
    )
    
    # Corrective catch: If the session points to an invalid player, reset to the first player.
    if current_player is None:
        current_player = players[0]
        current_player_id = current_player["id"]

    # Use the helper logic to bump their specific score based on their fetched name.
    updated = update_score(current_player["name"], delta, owner_id=owner_id)
    if not updated:
        flash("Current player not found.")
        return redirect(url_for("index"))

    # Automatically progress the turn to the *next* person in the array.
    next_player_id = get_next_player_id(players, current_player_id)
    db.execute(
        "UPDATE owner_sessions SET current_player_id = ? WHERE owner_id = ?",
        (next_player_id, owner_id),
    )
    db.commit()

    # Inform the user via flash message.
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
    """Resets all players in the user's specific session to 0 points/chips."""
    db = get_db()
    owner_id = get_owner_id()
    prune_expired_games(db)
    touch_owner_session(db, owner_id)
    
    # Global wipe for this specific user. Update the column 'score' to 0 everywhere.
    # Reset only this owner's scores.
    db.execute("UPDATE players SET score = 0 WHERE owner_id = ?", (owner_id,))
    db.commit()
    
    flash("All scores reset to 0.")
    return redirect(url_for("index"))


@app.post("/api/calculate")
def calculate_logic():
    """API endpoint that strictly handles the math in Python based on local variables.
    Receives JSON from JS with the specific button pressed, e.g.: {"action": "add_5", "current": 10}
    Returns JSON to JS: {"result": 15}
    """
    data = request.get_json()
    current = int(data.get("current", 0))
    action = data.get("action", "")
    
    # ---
    # Action-based routing! 
    # Respond differently depending on the specific button pressed.
    # ---
    new_total = current
    
    if action == "hit":
        new_total = current
        #promt to check if bust
        
    elif action == "stand":
        new_total = current
        #end trun
        
    elif action == "double":
        new_total = current * 2
        #promt to check if bust

        #TODO: Implement logic to only allow doubling on the first turn if specifed by deler, and only if the player has enough chips to double.

    elif action == "surrender":
        new_total = current / 2  
        #end turn 

    elif action == "split":
        #add split logic here
        new_total = current
        
    
    return {"result": new_total}


# Execute our initialize database function as soon as this Python module is loaded.
# This ensures that empty .db files get built automatically before a single web request comes in.
init_db()


# Typical python convention: This block runs only if you run `python app.py` directly,
# but NOT if it's imported as a module by something else (like Guicorn/Waitress/Gevent).
if __name__ == "__main__":
    # Fetch deployment configurations directly from environment variables.
    # Defaults are given if env variable doesn't exist (e.g. host 127.0.0.1, port 5000).
    host = os.getenv("FLASK_HOST", "127.0.0.1")
    port = int(os.getenv("FLASK_PORT", "5000"))
    # Debug mode controls whether the application restarts on file changes and shows giant error pages.
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    
    # Kick off the internal flask development server!
    app.run(host=host, port=port, debug=debug)
