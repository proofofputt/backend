import os
import logging
import sqlalchemy
import json
import bcrypt
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy.exc import IntegrityError, OperationalError

logger = logging.getLogger('debug_logger')

import notification_service # Import the notification service

# Global connector and connection pool to be initialized once.
connector = None
pool = None

def get_db_connection():
    """
    Initializes a connection pool. Uses a PostgreSQL database if DATABASE_URL is set,
    otherwise falls back to a local SQLite database file.
    """
    global pool
    if pool:
        return pool

    db_url = os.environ.get("DATABASE_URL")

    if db_url:
        logger.info("DATABASE_URL found. Connecting to PostgreSQL database.")
        pool = sqlalchemy.create_engine(db_url)
    else:
        db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "proofofputt_data.db")
        logger.warning(f"DATABASE_URL not set. Falling back to local SQLite DB: {db_path}")
        pool = sqlalchemy.create_engine(f"sqlite:///{db_path}")

    return pool

def create_default_session_if_needed(player_id):
    pool = get_db_connection()
    with pool.connect() as conn:
        # Check if the player already has any sessions
        session_count = conn.execute(
            sqlalchemy.text("SELECT COUNT(*) FROM sessions WHERE player_id = :player_id"),
            {"player_id": player_id}
        ).scalar()

        if session_count == 0:
            logger.info(f"No sessions found for player {player_id}. Creating a default session.")
            # Insert a default session with all zero values
            conn.execute(
                sqlalchemy.text(
                    "INSERT INTO sessions (player_id, start_time, end_time, status, total_putts, total_makes, total_misses, best_streak, fastest_21_makes, putts_per_minute, makes_per_minute, most_makes_in_60_seconds, session_duration, putt_list, makes_by_category, misses_by_category) "
                    "VALUES (:player_id, :start_time, :end_time, :status, :total_putts, :total_makes, :total_misses, :best_streak, :fastest_21_makes, :putts_per_minute, :makes_per_minute, :most_makes_in_60_seconds, :session_duration, :putt_list, :makes_by_category, :misses_by_category)"
                ),
                {
                    "player_id": player_id,
                    "start_time": datetime.utcnow(),
                    "end_time": datetime.utcnow(),
                    "status": "completed",
                    "total_putts": 0,
                    "total_makes": 0,
                    "total_misses": 0,
                    "best_streak": 0,
                    "fastest_21_makes": 0.0,
                    "putts_per_minute": 0.0,
                    "makes_per_minute": 0.0,
                    "most_makes_in_60_seconds": 0,
                    "session_duration": 0.0,
                    "putt_list": "[]",
                    "makes_by_category": "{}",
                    "misses_by_category": "{}"
                }
            )
            conn.commit() # Commit the session creation
            logger.info(f"Default session created for player {player_id}.")
        else:
            logger.info(f"Player {player_id} already has sessions. Skipping default session creation.")

def initialize_database():
    """Creates the database tables if they don't exist and ensures the default user is present."""
    pool = get_db_connection()
    db_type = pool.dialect.name

    with pool.connect() as conn:
        with conn.begin(): # Use a single transaction for all setup
            player_id_type = "SERIAL PRIMARY KEY" if db_type == "postgresql" else "INTEGER PRIMARY KEY"
            session_id_type = "SERIAL PRIMARY KEY" if db_type == "postgresql" else "INTEGER PRIMARY KEY"
            timestamp_type = "TIMESTAMP WITH TIME ZONE" if db_type == "postgresql" else "DATETIME"
            default_timestamp = "CURRENT_TIMESTAMP" if db_type == "postgresql" else "CURRENT_TIMESTAMP"

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS players (
                    player_id {player_id_type},
                    email TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at {timestamp_type} DEFAULT {default_timestamp},
                    subscription_status TEXT DEFAULT 'free',
                    zaprite_subscription_id TEXT,
                    timezone TEXT DEFAULT 'UTC',
                    x_url TEXT,
                    tiktok_url TEXT,
                    website_url TEXT,
                    notification_preferences TEXT
                )
            '''))

            if db_type == "sqlite":
                columns_to_add = {
                    "x_url": "TEXT",
                    "tiktok_url": "TEXT",
                    "website_url": "TEXT",
                    "notification_preferences": "TEXT"
                }
                for column, col_type in columns_to_add.items():
                    try:
                        conn.execute(sqlalchemy.text(f"ALTER TABLE players ADD COLUMN {column} {col_type}"))
                        logger.info(f"Added column '{column}' to 'players' table.")
                    except OperationalError as e:
                        if "duplicate column name" in str(e).lower():
                            logger.info(f"Column '{column}' already exists in 'players' table. Skipping.")
                        else:
                            logger.error(f"Error adding column '{column}' to 'players' table: {e}")

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id {session_id_type},
                    player_id INTEGER NOT NULL,
                    start_time {timestamp_type} DEFAULT {default_timestamp},
                    end_time {timestamp_type},
                    status TEXT,
                    total_putts INTEGER,
                    total_makes INTEGER,
                    total_misses INTEGER,
                    best_streak INTEGER,
                    fastest_21_makes REAL,
                    putts_per_minute REAL,
                    makes_per_minute REAL,
                    most_makes_in_60_seconds INTEGER,
                    session_duration REAL,
                    putt_list TEXT,
                    makes_by_category TEXT,
                    misses_by_category TEXT,
                    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
                )
            '''))

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS leagues (
                    league_id {session_id_type},
                    creator_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    privacy_type TEXT NOT NULL,
                    settings TEXT,
                    start_time {timestamp_type},
                    status TEXT DEFAULT 'registering',
                    final_notifications_sent BOOLEAN DEFAULT FALSE,
                    created_at {timestamp_type} DEFAULT {default_timestamp},
                    FOREIGN KEY (creator_id) REFERENCES players (player_id) ON DELETE CASCADE
                )
            '''))

            if db_type == "sqlite":
                league_columns_to_add = {
                    "final_notifications_sent": "BOOLEAN"
                }
                for column, col_type in league_columns_to_add.items():
                    try:
                        conn.execute(sqlalchemy.text(f"ALTER TABLE leagues ADD COLUMN {column} {col_type} DEFAULT FALSE"))
                        logger.info(f"Added column '{column}' to 'leagues' table.")
                    except OperationalError as e:
                        if "duplicate column name" in str(e).lower():
                            logger.info(f"Column '{column}' already exists in 'leagues' table. Skipping.")
                        else:
                            logger.error(f"Error adding column '{column}' to 'leagues' table: {e}")

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS league_members (
                    member_id {session_id_type},
                    league_id INTEGER NOT NULL,
                    player_id INTEGER NOT NULL,
                    status TEXT DEFAULT 'active',
                    UNIQUE (league_id, player_id),
                    FOREIGN KEY (league_id) REFERENCES leagues (league_id) ON DELETE CASCADE,
                    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
                )
            '''))

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS league_rounds (
                    round_id {session_id_type},
                    league_id INTEGER NOT NULL,
                    round_number INTEGER NOT NULL,
                    status TEXT DEFAULT 'scheduled',
                    start_time {timestamp_type},
                    end_time {timestamp_type},
                    FOREIGN KEY (league_id) REFERENCES leagues (league_id) ON DELETE CASCADE
                )
            '''))

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS league_round_submissions (
                    submission_id {session_id_type},
                    round_id INTEGER NOT NULL,
                    player_id INTEGER NOT NULL,
                    session_id INTEGER NOT NULL,
                    score INTEGER NOT NULL,
                    points_awarded INTEGER,
                    submitted_at {timestamp_type} DEFAULT {default_timestamp},
                    UNIQUE (round_id, player_id),
                    FOREIGN KEY (round_id) REFERENCES league_rounds (round_id) ON DELETE CASCADE,
                    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE,
                    FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE
                )
            '''))

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS player_stats (
                    player_id INTEGER PRIMARY KEY,
                    total_putts INTEGER DEFAULT 0,
                    total_makes INTEGER DEFAULT 0,
                    total_misses INTEGER DEFAULT 0,
                    best_streak INTEGER DEFAULT 0,
                    fastest_21_makes REAL,
                    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
                )
            '''))

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS coach_conversations (
                    conversation_id {session_id_type},
                    player_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    history_json TEXT NOT NULL,
                    created_at {timestamp_type} DEFAULT {default_timestamp},
                    last_updated {timestamp_type} DEFAULT {default_timestamp},
                    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
                )
            '''))

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS duels (
                    duel_id {session_id_type},
                    creator_id INTEGER NOT NULL,
                    invited_player_id INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    invitation_expiry_minutes INTEGER,
                    session_duration_limit_minutes INTEGER,
                    completion_deadline_minutes INTEGER,
                    creator_submitted_session_id INTEGER,
                    invited_player_submitted_session_id INTEGER,
                    winner_id INTEGER,
                    created_at {timestamp_type} DEFAULT {default_timestamp},
                    start_time {timestamp_type},
                    end_time {timestamp_type},
                    invitation_expires_at {timestamp_type},
                    completion_deadline_at {timestamp_type},
                    FOREIGN KEY (creator_id) REFERENCES players (player_id) ON DELETE CASCADE,
                    FOREIGN KEY (invited_player_id) REFERENCES players (player_id) ON DELETE CASCADE,
                    FOREIGN KEY (creator_submitted_session_id) REFERENCES sessions (session_id),
                    FOREIGN KEY (invited_player_submitted_session_id) REFERENCES sessions (session_id),
                    FOREIGN KEY (winner_id) REFERENCES players (player_id)
                )
            '''))

            if db_type == "sqlite":
                try:
                    duel_table_info = conn.execute(sqlalchemy.text("PRAGMA table_info(duels)")).mappings().fetchall()
                    duel_column_names = [col['name'] for col in duel_table_info]
                    duel_columns_to_add = {
                        "invitation_expiry_minutes": "INTEGER",
                        "session_duration_limit_minutes": "INTEGER",
                        "invitation_expires_at": "DATETIME"
                    }
                    for column, col_type in duel_columns_to_add.items():
                        if column not in duel_column_names:
                            conn.execute(sqlalchemy.text(f"ALTER TABLE duels ADD COLUMN {column} {col_type}"))
                            logger.info(f"Migration: Added column '{column}' to 'duels' table.")
                    if 'time_limit_minutes' in duel_column_names:
                        logger.info("Migration: Found obsolete 'time_limit_minutes' column in 'duels' table. Dropping it.")
                        conn.execute(sqlalchemy.text("ALTER TABLE duels DROP COLUMN time_limit_minutes"))
                        logger.info("Migration: Successfully dropped 'time_limit_minutes' column.")
                except Exception as e:
                    logger.warning(f"A non-critical error occurred during 'duels' table migration. This is often safe to ignore. Error: {e}")

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS notifications (
                    id {session_id_type},
                    player_id INTEGER NOT NULL,
                    type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details TEXT,
                    read_status BOOLEAN DEFAULT FALSE,
                    created_at {timestamp_type} DEFAULT {default_timestamp},
                    link_path TEXT,
                    email_sent BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
                )
            '''))

            if db_type == "sqlite":
                notification_columns_to_add = {
                    "email_sent": "BOOLEAN"
                }
                for column, col_type in notification_columns_to_add.items():
                    try:
                        conn.execute(sqlalchemy.text(f"ALTER TABLE notifications ADD COLUMN {column} {col_type}"))
                        logger.info(f"Added column '{column}' to 'notifications' table.")
                    except OperationalError as e:
                        if "duplicate column name" in str(e).lower():
                            logger.info(f"Column '{column}' already exists in 'notifications' table. Skipping.")
                        else:
                            logger.error(f"Error adding column '{column}' to 'notifications' table: {e}")

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS fundraisers (
                    fundraiser_id {session_id_type},
                    player_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    cause TEXT,
                    description TEXT,
                    goal_amount REAL NOT NULL,
                    start_time {timestamp_type} NOT NULL,
                    end_time {timestamp_type} NOT NULL,
                    status TEXT DEFAULT 'upcoming',
                    last_notified_milestone INTEGER DEFAULT 0,
                    conclusion_notification_sent BOOLEAN DEFAULT FALSE,
                    created_at {timestamp_type} DEFAULT {default_timestamp},
                    FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
                )
            '''))

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS pledges (
                    pledge_id {session_id_type},
                    fundraiser_id INTEGER NOT NULL,
                    pledger_player_id INTEGER NOT NULL,
                    amount_per_putt REAL NOT NULL,
                    max_donation REAL,
                    status TEXT DEFAULT 'active',
                    created_at {timestamp_type} DEFAULT {default_timestamp},
                    FOREIGN KEY (fundraiser_id) REFERENCES fundraisers (fundraiser_id) ON DELETE CASCADE,
                    FOREIGN KEY (pledger_player_id) REFERENCES players (player_id) ON DELETE CASCADE
                )
            '''))

            if db_type == "sqlite":
                fundraiser_columns_to_add = {
                    "last_notified_milestone": "INTEGER",
                    "conclusion_notification_sent": "BOOLEAN"
                }
                for column, col_type in fundraiser_columns_to_add.items():
                    try:
                        conn.execute(sqlalchemy.text(f"ALTER TABLE fundraisers ADD COLUMN {column} {col_type} DEFAULT 0"))
                        logger.info(f"Added column '{column}' to 'fundraisers' table.")
                    except OperationalError as e:
                        if "duplicate column name" in str(e).lower():
                            logger.info(f"Column '{column}' already exists in 'fundraisers' table. Skipping.")
                        else:
                            logger.error(f"Error adding column '{column}' to 'fundraisers' table: {e}")

            conn.execute(sqlalchemy.text(f'''
                CREATE TABLE IF NOT EXISTS player_relationships (
                    follower_id INTEGER NOT NULL,
                    followed_id INTEGER NOT NULL,
                    created_at {timestamp_type} DEFAULT {default_timestamp},
                    PRIMARY KEY (follower_id, followed_id),
                    FOREIGN KEY (follower_id) REFERENCES players (player_id) ON DELETE CASCADE,
                    FOREIGN KEY (followed_id) REFERENCES players (player_id) ON DELETE CASCADE
                )
            '''))

            # --- Create Default User Logic ---
            pop_user = conn.execute(
                sqlalchemy.text("SELECT player_id, subscription_status FROM players WHERE email = :email"),
                {"email": "pop@proofofputt.com"}
            ).mappings().first()

            if not pop_user:
                logger.info("Default user 'pop@proofofputt.com' not found. Creating...")
                password_hash = bcrypt.hashpw("passwordpop123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                insert_sql = "INSERT INTO players (email, name, password_hash, timezone) VALUES (:email, :name, :password_hash, :timezone)"
                if db_type == "postgresql":
                    insert_sql += " RETURNING player_id"
                
                result = conn.execute(sqlalchemy.text(insert_sql), {"email": "pop@proofofputt.com", "name": "POP", "password_hash": password_hash, "timezone": "UTC"})
                
                player_id = result.scalar() if db_type == "postgresql" else result.lastrowid
                
                conn.execute(sqlalchemy.text("INSERT INTO player_stats (player_id) VALUES (:player_id)"), {"player_id": player_id})
                pop_user = {'player_id': player_id, 'subscription_status': 'free'}
                logger.info(f"Registered new default player 'POP' with ID {player_id}.")
                create_default_session_if_needed(player_id) # Add this line

            else:
                logger.info(f"Default user {pop_user['player_id']} found. Ensuring password hash is bcrypt compatible.")
                hashed_password = bcrypt.hashpw("passwordpop123".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                conn.execute(sqlalchemy.text('''
                    UPDATE players SET password_hash = :password_hash
                    WHERE player_id = :player_id
                '''), {"password_hash": hashed_password, "player_id": pop_user['player_id']})
                create_default_session_if_needed(pop_user['player_id']) # Add this line
            
            if pop_user and pop_user['subscription_status'] != 'active':
                logger.info(f"Upgrading default user {pop_user['player_id']} to 'active' subscription status.")
                conn.execute(sqlalchemy.text('''
                    UPDATE players SET subscription_status = 'active'
                    WHERE player_id = :player_id
                '''), {"player_id": pop_user['player_id']})

def register_player(email, password, name):
    """Registers a new player with a hashed password."""
    if not email or not password or not name:
        raise ValueError("Email, password, and name cannot be empty.")

    pool = get_db_connection()
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    db_type = pool.dialect.name

    with pool.connect() as conn:
        with conn.begin() as trans:
            try:
                insert_sql = "INSERT INTO players (email, name, password_hash, timezone) VALUES (:email, :name, :password_hash, :timezone)"
                if db_type == "postgresql":
                    insert_sql += " RETURNING player_id"
                
                result = conn.execute(sqlalchemy.text(insert_sql), {"email": email, "name": name, "password_hash": password_hash, "timezone": "UTC"})
                
                player_id = result.scalar() if db_type == "postgresql" else result.lastrowid

                conn.execute(sqlalchemy.text("INSERT INTO player_stats (player_id) VALUES (:player_id)"), {"player_id": player_id})
                
                # Call the new function to create a default session if needed
                create_default_session_if_needed(player_id)

                logger.info(f"Registered new player '{name}' with ID {player_id}.")
                return player_id, name
            except IntegrityError as e:
                raise ValueError("A player with this email already exists.")

def login_with_email_password(email, password):
    """Authenticates a player with email and password."""
    pool = get_db_connection()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT player_id, name, email, password_hash, timezone, subscription_status FROM players WHERE email = :email"),
            {"email": email}
        ).mappings().first()

        if result and bcrypt.checkpw(password.encode('utf-8'), result['password_hash'].encode('utf-8')):
            player_id = result['player_id']
            stats = get_player_stats(player_id)
            sessions = get_sessions_for_player(player_id, limit=25)
            return player_id, result['name'], result['email'], stats, sessions, result['timezone'], result['subscription_status']
        
        return None, None, None, None, None, None, None

def get_player_stats(player_id):
    pool = get_db_connection()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT total_putts, total_makes, total_misses, best_streak, fastest_21_makes FROM player_stats WHERE player_id = :player_id"),
            {"player_id": player_id}
        ).mappings().first()
        if result:
            return dict(result)
        return None

def get_sessions_for_player(player_id, limit=25, offset=0):
    pool = get_db_connection()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT session_id, start_time, end_time, status, total_putts, total_makes, total_misses, best_streak, fastest_21_makes, putts_per_minute, makes_per_minute, most_makes_in_60_seconds, session_duration, putt_list, makes_by_category, misses_by_category FROM sessions WHERE player_id = :player_id ORDER BY start_time DESC LIMIT :limit OFFSET :offset"),
            {"player_id": player_id, "limit": limit, "offset": offset}
        ).mappings().fetchall()
        return [dict(row) for row in result]

# ... (rest of the file is the same) ...
