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

def initialize_database():
    """Creates the database tables if they don't exist."""
    pool = get_db_connection()
    db_type = pool.dialect.name

    with pool.connect() as conn:
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

        # Add missing columns for SQLite if they don't exist
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
                status TEXT, -- active, completed, aborted
                total_putts INTEGER,
                total_makes INTEGER,
                total_misses INTEGER,
                best_streak INTEGER,
                fastest_21_makes REAL,
                putts_per_minute REAL,
                makes_per_minute REAL,
                most_makes_in_60_seconds INTEGER,
                session_duration REAL,
                putt_list TEXT, -- JSON
                makes_by_category TEXT, -- JSON
                misses_by_category TEXT, -- JSON
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
                status TEXT DEFAULT 'active', -- active, invited
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
                status TEXT DEFAULT 'scheduled', -- scheduled, active, completed
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
            CREATE TABLE IF NOT EXISTS sessions (
                session_id {session_id_type},
                player_id INTEGER NOT NULL,
                start_time {timestamp_type} DEFAULT {default_timestamp},
                end_time {timestamp_type},
                status TEXT, -- active, completed, aborted
                total_putts INTEGER,
                total_makes INTEGER,
                total_misses INTEGER,
                best_streak INTEGER,
                fastest_21_makes REAL,
                putts_per_minute REAL,
                makes_per_minute REAL,
                most_makes_in_60_seconds INTEGER,
                session_duration REAL,
                putt_list TEXT, -- JSON
                makes_by_category TEXT, -- JSON
                misses_by_category TEXT, -- JSON
                FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
            )
        '''))

        # ... other tables ...
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

        # Add missing columns for SQLite if they don't exist. This handles schema
        # updates for existing databases without requiring a full reset.
        # This also handles dropping obsolete columns from previous schema versions.
        if db_type == "sqlite":
            try:
                duel_table_info = conn.execute(sqlalchemy.text("PRAGMA table_info(duels)")).mappings().fetchall()
                duel_column_names = [col['name'] for col in duel_table_info]

                # Migration: Add new columns if they don't exist
                duel_columns_to_add = {
                    "invitation_expiry_minutes": "INTEGER",
                    "session_duration_limit_minutes": "INTEGER",
                    "invitation_expires_at": "DATETIME"
                }
                for column, col_type in duel_columns_to_add.items():
                    if column not in duel_column_names:
                        conn.execute(sqlalchemy.text(f"ALTER TABLE duels ADD COLUMN {column} {col_type}"))
                        logger.info(f"Migration: Added column '{column}' to 'duels' table.")

                # Migration: Drop obsolete 'time_limit_minutes' column
                if 'time_limit_minutes' in duel_column_names:
                    logger.info("Migration: Found obsolete 'time_limit_minutes' column in 'duels' table. Dropping it.")
                    conn.execute(sqlalchemy.text("ALTER TABLE duels DROP COLUMN time_limit_minutes"))
                    logger.info("Migration: Successfully dropped 'time_limit_minutes' column.")
            except Exception as e:
                logger.warning(f"A non-critical error occurred during 'duels' table migration. This is often safe to ignore. Error: {e}")

        

        # conn.execute(sqlalchemy.text(f'''
        #     CREATE TABLE IF NOT EXISTS duel_sessions (
        #         duel_session_id {session_id_type},
        #         duel_id INTEGER NOT NULL,
        #         session_id INTEGER NOT NULL,
        #         player_id INTEGER NOT NULL,
        #         score INTEGER NOT NULL,
        #         duration REAL,
        #         submitted_at {timestamp_type} DEFAULT {default_timestamp},
        #         FOREIGN KEY (duel_id) REFERENCES duels (duel_id) ON DELETE CASCADE,
        #         FOREIGN KEY (session_id) REFERENCES sessions (session_id) ON DELETE CASCADE,
        #         FOREIGN KEY (player_id) REFERENCES players (player_id) ON DELETE CASCADE
        #     )
        # '''))

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


def create_default_user_if_not_exists():
    """Ensures the default 'wake' user exists and is a full subscriber."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin(): # Use a single transaction
            # Check if the user exists
            wake_user = conn.execute(
                sqlalchemy.text("SELECT player_id, subscription_status FROM players WHERE email = :email"),
                {"email": "wake@bubblewake.com"}
            ).mappings().first()

            if not wake_user:
                logger.info("Default user 'wake@bubblewake.com' not found. Creating...")
                player_id, _ = register_player("wake@bubblewake.com", "password", "wake")
                wake_user = {'player_id': player_id, 'subscription_status': 'free'}
            else: # User exists, ensure password hash is updated to bcrypt
                logger.info(f"Default user {wake_user['player_id']} found. Ensuring password hash is bcrypt compatible.")
                hashed_password = bcrypt.hashpw("password".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                conn.execute(sqlalchemy.text("""
                    UPDATE players SET password_hash = :password_hash
                    WHERE player_id = :player_id
                """), {"password_hash": hashed_password, "player_id": wake_user['player_id']})
            
            # Now, ensure the subscription is active
            if wake_user and wake_user['subscription_status'] != 'active':
                logger.info(f"Upgrading default user {wake_user['player_id']} to 'active' subscription status.")
                conn.execute(sqlalchemy.text("""
                    UPDATE players SET subscription_status = 'active'
                    WHERE player_id = :player_id
                """), {"player_id": wake_user['player_id']})

def register_player(email, password, name):
    """Registers a new player with a hashed password."""
    # Backend validation to prevent empty submissions
    if not email or not password or not name: # Added name validation
        raise ValueError("Email, password, and name cannot be empty.")

    pool = get_db_connection()
    password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    db_type = pool.dialect.name

    with pool.connect() as conn:
        # Use a transaction to ensure both inserts succeed or fail together.
        with conn.begin() as trans:
            try:
                insert_sql = "INSERT INTO players (email, name, password_hash, timezone) VALUES (:email, :name, :password_hash, :timezone)"
                if db_type == "postgresql":
                    insert_sql += " RETURNING player_id"
                
                result = conn.execute(sqlalchemy.text(insert_sql), {"email": email, "name": name, "password_hash": password_hash, "timezone": "UTC"})
                
                if db_type == "postgresql":
                    player_id = result.scalar()
                else: # SQLite
                    player_id = result.lastrowid

                # Create the corresponding entry in the player_stats table
                conn.execute(sqlalchemy.text("INSERT INTO player_stats (player_id) VALUES (:player_id)"), {"player_id": player_id})
                
                # The transaction is committed automatically on successful exit of this block.
                logger.info(f"Registered new player '{name}' with ID {player_id}.")
                return player_id, name
            except IntegrityError as e:
                # The transaction is rolled back automatically on exception.
                # We can now be certain the error is for a duplicate email.
                raise ValueError("A player with this email already exists.")

def login_with_email_password(email, password):
    """Logs in a player, returning their data if credentials are valid."""
    # Prevent login attempts with empty credentials before hitting the DB
    if not email or not password:
        return None, None, None, None, None, None, None # Added None for subscription_status

    pool = get_db_connection()
    with pool.connect() as conn:
        player = conn.execute(sqlalchemy.text("SELECT player_id, name, email, password_hash, timezone, subscription_status FROM players WHERE email = :email"), {"email": email}).mappings().first()
        if player:
            if bcrypt.checkpw(password.encode('utf-8'), player['password_hash'].encode('utf-8')):
                player_id = player['player_id']
                stats = get_player_stats(player_id, conn)
                sessions = get_sessions_for_player(player_id, conn)
                return player_id, player['name'], player['email'], stats, sessions, player['timezone'], player['subscription_status']
    return None, None, None, None, None, None, None

def get_player_info(player_id, conn=None, viewer_id=None):
    """Retrieves basic player information, including follower counts and status."""
    def _fetch(connection):
        # Base player info
        sql = sqlalchemy.text("""
            SELECT name, email, timezone, subscription_status, notification_preferences,
                   x_url, tiktok_url, website_url
            FROM players WHERE player_id = :id
        """)
        player_info = connection.execute(sql, {"id": player_id}).mappings().first()
        if not player_info:
            return None
        player_info = dict(player_info)

        # Follower/Following counts
        followers_count_sql = sqlalchemy.text("SELECT COUNT(*) FROM player_relationships WHERE followed_id = :id")
        player_info['followers_count'] = connection.execute(followers_count_sql, {"id": player_id}).scalar()

        following_count_sql = sqlalchemy.text("SELECT COUNT(*) FROM player_relationships WHERE follower_id = :id")
        player_info['following_count'] = connection.execute(following_count_sql, {"id": player_id}).scalar()

        # Check follow status if a viewer is specified
        player_info['is_followed_by_viewer'] = False
        if viewer_id:
            status_sql = sqlalchemy.text("SELECT 1 FROM player_relationships WHERE follower_id = :viewer_id AND followed_id = :player_id")
            is_following = connection.execute(status_sql, {"viewer_id": viewer_id, "player_id": player_id}).scalar()
            if is_following:
                player_info['is_followed_by_viewer'] = True
        
        return player_info

    if conn:
        return _fetch(conn)
    
    pool = get_db_connection()
    with pool.connect() as connection:
        return _fetch(connection)

def update_player_notification_preferences(player_id, preferences):
    """Updates a player's notification preferences."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            conn.execute(
                sqlalchemy.text("UPDATE players SET notification_preferences = :prefs WHERE player_id = :id"),
                {
                    "prefs": json.dumps(preferences),
                    "id": player_id
                }
            )
            logger.info(f"Updated notification preferences for player {player_id}.")

def get_player_stats(player_id, conn=None):
    """
    Retrieves all-time stats for a given player.
    If a connection is provided, it's used; otherwise, a new one is created.
    """
    def _fetch(connection):
        result = connection.execute(
            sqlalchemy.text("SELECT * FROM player_stats WHERE player_id = :id"),
            {"id": player_id}
        ).mappings().first()
        return dict(result) if result else None

    if conn:
        return _fetch(conn)
    
    pool = get_db_connection()
    with pool.connect() as connection:
        return _fetch(connection)

def get_sessions_for_player(player_id, conn=None, limit=None, offset=None):
    """
    Retrieves all session data for a given player, ordered by most recent.
    Supports pagination with limit and offset.
    If a connection is provided, it's used; otherwise, a new one is created.
    """
    def _fetch(connection):
        base_sql = "SELECT * FROM sessions WHERE player_id = :id ORDER BY start_time DESC"
        params = {"id": player_id}
        
        if limit is not None:
            base_sql += " LIMIT :limit"
            params["limit"] = limit
        if offset is not None:
            base_sql += " OFFSET :offset"
            params["offset"] = offset

        results = connection.execute(sqlalchemy.text(base_sql), params).mappings().fetchall()
        sessions = []
        for row in results:
            session_dict = dict(row)
            session_dict['consecutive_by_category'] = calculate_consecutive_streaks(session_dict.get('putt_list'))
            sessions.append(session_dict)
        return sessions

    if conn:
        return _fetch(conn)

    pool = get_db_connection()
    with pool.connect() as connection:
        return _fetch(connection)

def get_sessions_count_for_player(player_id, conn=None):
    """Retrieves the total count of sessions for a given player."""
    def _fetch(connection):
        return connection.execute(
            sqlalchemy.text("SELECT COUNT(*) FROM sessions WHERE player_id = :id"),
            {"id": player_id}
        ).scalar_one()

    if conn:
        return _fetch(conn)
    
    pool = get_db_connection()
    with pool.connect() as connection:
        return _fetch(connection)

def _aggregate_session_makes(s_makes_by_cat, career_stats):
    """Helper to aggregate makes from a single session into career stats."""
    s_makes_overview_counts = {cat: 0 for cat in ["TOP", "RIGHT", "LOW", "LEFT"]}
    for cat, count in s_makes_by_cat.items():
        # Detailed aggregation
        if cat not in career_stats["makes_detailed"]:
            career_stats["makes_detailed"][cat] = {"high": 0, "sum": 0}
        career_stats["makes_detailed"][cat]["high"] = max(career_stats["makes_detailed"][cat]["high"], count)
        career_stats["makes_detailed"][cat]["sum"] += count
        
        # Tally for session overview
        if "TOP" in cat: s_makes_overview_counts["TOP"] += count
        if "RIGHT" in cat: s_makes_overview_counts["RIGHT"] += count
        if "LOW" in cat: s_makes_overview_counts["LOW"] += count
        if "LEFT" in cat: s_makes_overview_counts["LEFT"] += count
    
    # Update career overview with this session's totals
    for cat, count in s_makes_overview_counts.items():
        career_stats["makes_overview"][cat]["sum"] += count
        career_stats["makes_overview"][cat]["high"] = max(career_stats["makes_overview"][cat]["high"], count)

def _aggregate_session_misses(putt_list, career_stats):
    """Helper to aggregate detailed misses from a single session's putt list."""
    s_misses_detailed = {}
    for putt in [p for p in putt_list if p.get('Putt Classification') == 'MISS']:
        detail = putt.get('Putt Detailed Classification', 'UNKNOWN').replace('MISS - ', '')
        s_misses_detailed[detail] = s_misses_detailed.get(detail, 0) + 1
    
    for detail, count in s_misses_detailed.items():
        if detail not in career_stats["misses_detailed"]:
            career_stats["misses_detailed"][detail] = {"low": float('inf'), "high": 0, "sum": 0}
        career_stats["misses_detailed"][detail]["low"] = min(career_stats["misses_detailed"][detail]["low"], count)
        career_stats["misses_detailed"][detail]["high"] = max(career_stats["misses_detailed"][detail]["high"], count)
        career_stats["misses_detailed"][detail]["sum"] += count

def get_career_stats(player_id):
    """
    Aggregates and calculates comprehensive career statistics for a player.
    """
    import json
    pool = get_db_connection()
    with pool.connect() as conn:
        # Get player info first to ensure player exists and to get their name
        player_info = get_player_info(player_id, conn)
        if not player_info:
            return None

        player_stats = get_player_stats(player_id, conn)
        if not player_stats: # Should not happen if player exists, but good practice
            player_stats = {}

        sessions = get_sessions_for_player(player_id, conn)
        # Fetch duels and leagues to calculate counts
        duels = get_duels_for_player(player_id, conn)
        leagues = get_leagues_for_player(player_id, conn)
        
        # Initialize career stats dictionary
        career_stats = {
            "player_id": player_id,
            "name": player_info.get('name', 'Unknown Player'),
            "high_makes": 0,
            "sum_makes": player_stats.get('total_makes', 0),
            "high_best_streak": player_stats.get('best_streak', 0),
            "low_fastest_21": player_stats.get('fastest_21_makes'),
            "high_ppm": 0.0,
            "avg_ppm": 0.0,
            "high_mpm": 0.0,
            "avg_mpm": 0.0,
            "high_most_in_60": 0,
            "high_duration": 0.0,
            "sum_duration": 0.0,
            "high_accuracy": 0.0,
            "avg_accuracy": 0.0,
            "consecutive": {str(c): {"high": 0, "sum": 0} for c in [3, 7, 10, 15, 21, 50, 100]},
            "makes_overview": {cat: {"high": 0, "sum": 0} for cat in ["TOP", "RIGHT", "LOW", "LEFT"]},
            "makes_detailed": {},
            "misses_overview": {cat: {"low": float('inf'), "high": 0, "sum": 0} for cat in ["RETURN", "CATCH", "TIMEOUT", "QUICK PUTT"]},
            "misses_detailed": {},
            "duel_counts": {
                "active": len([d for d in duels if d['status'] == 'accepted']),
                "complete": len([d for d in duels if d['status'] == 'completed'])
            },
            "league_counts": {
                "active": len([l for l in leagues.get('my_leagues', []) if l['status'] in ['active', 'registering']]),
                "complete": len([l for l in leagues.get('my_leagues', []) if l['status'] == 'completed'])
            },
            # Pass the subscription status through
            "is_subscribed": player_info.get('subscription_status') == 'active'
        }

        total_duration_seconds = 0
        for session in sessions:
            s_makes = session.get('total_makes', 0) or 0
            s_misses = session.get('total_misses', 0) or 0
            duration = session.get('session_duration', 0) or 0

            career_stats["high_makes"] = max(career_stats["high_makes"], s_makes)
            career_stats["high_ppm"] = max(career_stats["high_ppm"], session.get('putts_per_minute', 0) or 0)
            career_stats["high_mpm"] = max(career_stats["high_mpm"], session.get('makes_per_minute', 0) or 0)
            career_stats["high_most_in_60"] = max(career_stats["high_most_in_60"], session.get('most_makes_in_60_seconds', 0) or 0)
            career_stats["high_duration"] = max(career_stats["high_duration"], duration)
            total_duration_seconds += duration

            if (s_makes + s_misses) > 0:
                s_accuracy = (s_makes / (s_makes + s_misses)) * 100
                career_stats["high_accuracy"] = max(career_stats["high_accuracy"], s_accuracy)

            # Aggregate makes by category (overview and detailed)
            if session.get('makes_by_category'):
                try:
                    _aggregate_session_makes(json.loads(session['makes_by_category']), career_stats)
                except (json.JSONDecodeError, TypeError): pass

            # Aggregate misses by category (overview only)
            if session.get('misses_by_category'):
                try:
                    s_misses_by_cat = json.loads(session['misses_by_category'])
                    for cat, count in s_misses_by_cat.items():
                        if cat in career_stats["misses_overview"]:
                            career_stats["misses_overview"][cat]["low"] = min(career_stats["misses_overview"][cat]["low"], count)
                            career_stats["misses_overview"][cat]["high"] = max(career_stats["misses_overview"][cat]["high"], count)
                            career_stats["misses_overview"][cat]["sum"] += count
                except (json.JSONDecodeError, TypeError): pass

            for cat_str, count in session.get('consecutive_by_category', {}).items():
                if cat_str in career_stats["consecutive"]:
                    career_stats["consecutive"][cat_str]["high"] = max(career_stats["consecutive"][cat_str]["high"], count)
                    career_stats["consecutive"][cat_str]["sum"] += count

            if session.get('putt_list'):
                try:
                    _aggregate_session_misses(json.loads(session['putt_list']), career_stats)
                except (json.JSONDecodeError, TypeError): pass

        career_stats["sum_duration"] = total_duration_seconds
        total_putts = player_stats.get('total_makes', 0) + player_stats.get('total_misses', 0)
        if total_duration_seconds > 0:
            total_duration_minutes = total_duration_seconds / 60.0
            career_stats["avg_ppm"] = (total_putts / total_duration_minutes) if total_duration_minutes > 0 else 0
            career_stats["avg_mpm"] = (player_stats.get('total_makes', 0) / total_duration_minutes) if total_duration_minutes > 0 else 0
        if total_putts > 0:
            career_stats["avg_accuracy"] = (player_stats.get('total_makes', 0) / total_putts) * 100

        # Final cleanup: Replace any remaining float('inf') with None for JSON compatibility.
        # 'Infinity' is not a valid JSON token, but None serializes to 'null'.
        for detail in career_stats.get("misses_detailed", {}):
            if career_stats["misses_detailed"][detail]["low"] == float('inf'):
                career_stats["misses_detailed"][detail]["low"] = None
        for category in career_stats.get("misses_overview", {}):
            if career_stats["misses_overview"][category]["low"] == float('inf'):
                career_stats["misses_overview"][category]["low"] = None

        return career_stats

def create_session(player_id):
    """Creates a new, active session for a player and returns the session ID."""
    pool = get_db_connection()
    db_type = pool.dialect.name
    with pool.connect() as conn:
        with conn.begin():
            insert_sql = "INSERT INTO sessions (player_id, status) VALUES (:player_id, 'active')"
            if db_type == "postgresql":
                insert_sql += " RETURNING session_id"
            
            result = conn.execute(sqlalchemy.text(insert_sql), {"player_id": player_id})
            
            if db_type == "postgresql":
                session_id = result.scalar()
            else: # SQLite
                session_id = result.lastrowid
            
        logger.info(f"Created new active session {session_id} for player {player_id}.")
        return session_id

def create_duel(creator_id, invited_player_identifier, invitation_expiry_minutes, session_duration_limit_minutes):
    """Creates a new duel and returns the duel ID."""
    pool = get_db_connection()
    db_type = pool.dialect.name
    from datetime import datetime, timedelta, timezone

    with pool.connect() as conn:
        with conn.begin():
            # Resolve the invited player's ID
            invited_player = conn.execute(sqlalchemy.text("SELECT player_id FROM players WHERE email = :identifier OR name = :identifier"), {"identifier": invited_player_identifier}).mappings().first()
            if not invited_player:
                raise ValueError(f"Player with name or email '{invited_player_identifier}' not found.")
            invited_player_id = invited_player['player_id']

            now = datetime.now(timezone.utc)
            expires_at = now + timedelta(minutes=invitation_expiry_minutes)

            insert_sql = """
                INSERT INTO duels (creator_id, invited_player_id, invitation_expiry_minutes, session_duration_limit_minutes, status, invitation_expires_at)
                VALUES (:creator_id, :invited_player_id, :invitation_expiry_minutes, :session_duration_limit_minutes, 'pending', :expires_at)
            """
            if db_type == "postgresql":
                insert_sql += " RETURNING duel_id"
            
            result = conn.execute(sqlalchemy.text(insert_sql), {
                "creator_id": creator_id,
                "invited_player_id": invited_player_id,
                "invitation_expiry_minutes": invitation_expiry_minutes,
                "session_duration_limit_minutes": session_duration_limit_minutes,
                "expires_at": expires_at
            })
            
            if db_type == "postgresql":
                duel_id = result.scalar()
            else: # SQLite
                duel_id = result.lastrowid
            
        logger.info(f"Created new duel {duel_id} between {creator_id} and {invited_player_id}.")
        return duel_id

def get_duel(duel_id):
    """Retrieves a duel by its ID."""
    pool = get_db_connection()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT * FROM duels WHERE duel_id = :duel_id"),
            {"duel_id": duel_id}
        ).mappings().first()
        return dict(result) if result else None

def get_duel_details(duel_id):
    """Retrieves duel details by duel_id."""
    pool = get_db_connection()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT * FROM duels WHERE duel_id = :duel_id"),
            {"duel_id": duel_id}
        ).mappings().first()
        return dict(result) if result else None

def get_duels_for_player(player_id, conn=None):
    """
    Retrieves all duels for a player. Uses a provided connection or creates a new one.
    Fetches the actual session duration for completed duels.
    """
    def _fetch(connection):
        # This comprehensive query fetches duel data along with names and scores.
        sql = sqlalchemy.text("""
                SELECT d.*,
                       creator.name AS creator_name,
                       invited.name AS invited_player_name,
                       creator_s.total_makes AS creator_score,
                       creator_s.session_duration AS creator_duration,
                       creator_s.total_misses AS creator_total_misses,
                       creator_s.fastest_21_makes AS creator_fastest_21_makes,
                       creator_s.best_streak AS creator_best_streak,
                       invited_s.total_makes AS invited_player_score,
                       invited_s.session_duration AS invited_duration,
                       invited_s.total_misses AS invited_total_misses,
                       invited_s.fastest_21_makes AS invited_fastest_21_makes,
                       invited_s.best_streak AS invited_best_streak
                FROM duels d
                JOIN players creator ON d.creator_id = creator.player_id
                JOIN players invited ON d.invited_player_id = invited.player_id
                LEFT JOIN sessions creator_s ON d.creator_submitted_session_id = creator_s.session_id
                LEFT JOIN sessions invited_s ON d.invited_player_submitted_session_id = invited_s.session_id
                WHERE d.creator_id = :player_id OR d.invited_player_id = :player_id
                ORDER BY d.created_at DESC
            """)
        results = connection.execute(sql, {"player_id": player_id}).mappings().fetchall()
        return [dict(row) for row in results]

    if conn:
        return _fetch(conn)
    
    pool = get_db_connection()
    with pool.connect() as connection:
        return _fetch(connection)

def accept_duel(duel_id, player_id):
    """Updates the status of a duel to 'accepted' and sets the start_time."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            # Ensure the player accepting is the invited player
            update_sql = sqlalchemy.text("""
                UPDATE duels SET
                    status = 'accepted',
                    start_time = CURRENT_TIMESTAMP
                WHERE duel_id = :duel_id AND invited_player_id = :player_id AND status = 'pending'
            """)
            result = conn.execute(update_sql, {"duel_id": duel_id, "player_id": player_id})
            if result.rowcount == 0:
                raise ValueError("Duel could not be accepted. It may not be pending or you may not be the invited player.")
            logger.info(f"Duel {duel_id} accepted by player {player_id}.")

def reject_duel(duel_id):
    """Updates the status of a duel to 'declined'."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            # Set end_time when a duel is declined to mark its completion
            update_sql = sqlalchemy.text("""
                UPDATE duels SET status = 'declined', end_time = CURRENT_TIMESTAMP
                WHERE duel_id = :duel_id AND status = 'pending'
            """)
            conn.execute(update_sql, {"duel_id": duel_id})
        logger.info(f"Duel {duel_id} rejected (status set to declined).")

def check_and_complete_duel(duel_id, conn):
    """
    Checks if a duel is ready to be completed (both players submitted).
    If so, determines the winner based on a set of rules and updates the duel status.
    """
    duel = conn.execute(
        sqlalchemy.text("""
            SELECT creator_id, invited_player_id, creator_submitted_session_id, invited_player_submitted_session_id
            FROM duels WHERE duel_id = :duel_id AND status = 'accepted'
        """),
        {"duel_id": duel_id}
    ).mappings().first()

    # Proceed only if the duel is 'accepted' and both players have submitted their sessions
    if not duel or not duel['creator_submitted_session_id'] or not duel['invited_player_submitted_session_id']:
        return

    # Fetch session stats for both players, now including session_duration for the tie-breaker
    session_stats_sql = sqlalchemy.text("SELECT total_makes, total_misses, fastest_21_makes, best_streak, session_duration FROM sessions WHERE session_id = :id")
    
    creator_stats = conn.execute(session_stats_sql, {"id": duel['creator_submitted_session_id']}).mappings().first()
    invited_stats = conn.execute(session_stats_sql, {"id": duel['invited_player_submitted_session_id']}).mappings().first()

    if not creator_stats or not invited_stats:
        logger.error(f"Could not retrieve full session stats for duel {duel_id} to determine winner.")
        return

    winner_id = None

    # Rule 1: Most makes (primary condition)
    if creator_stats['total_makes'] > invited_stats['total_makes']:
        winner_id = duel['creator_id']
    elif invited_stats['total_makes'] > creator_stats['total_makes']:
        winner_id = duel['invited_player_id']
    else:  # Tie in makes, proceed to tie-breakers
        # Rule 2: Fastest 21 makes (lower is better, None is worst)
        c_f21 = creator_stats.get('fastest_21_makes')
        i_f21 = invited_stats.get('fastest_21_makes')

        if c_f21 is not None and (i_f21 is None or c_f21 < i_f21):
            winner_id = duel['creator_id']
        elif i_f21 is not None and (c_f21 is None or i_f21 < c_f21):
            winner_id = duel['invited_player_id']
        elif c_f21 == i_f21: # Also handles when both are None
            # Rule 3: Highest best streak (max consecutive makes)
            if creator_stats['best_streak'] > invited_stats['best_streak']:
                winner_id = duel['creator_id']
            elif invited_stats['best_streak'] > creator_stats['best_streak']:
                winner_id = duel['invited_player_id']
            elif creator_stats['best_streak'] == invited_stats['best_streak']:
                # Rule 4: Least misses (lower is better)
                if creator_stats['total_misses'] < invited_stats['total_misses']:
                    winner_id = duel['creator_id']
                elif invited_stats['total_misses'] < creator_stats['total_misses']:
                    winner_id = duel['invited_player_id']
                elif creator_stats['total_misses'] == invited_stats['total_misses']:
                    # FINAL TIE-BREAKER: Shortest session duration (lower is better)
                    c_dur = creator_stats.get('session_duration')
                    i_dur = invited_stats.get('session_duration')
                    if c_dur is not None and (i_dur is None or c_dur < i_dur):
                        winner_id = duel['creator_id']
                    elif i_dur is not None and (c_dur is None or i_dur < c_dur):
                        winner_id = duel['invited_player_id']

    # Update the duel to 'completed' and set the winner_id
    update_sql = sqlalchemy.text("""
        UPDATE duels SET status = 'completed', winner_id = :winner_id, end_time = CURRENT_TIMESTAMP
        WHERE duel_id = :duel_id
    """)
    conn.execute(update_sql, {"winner_id": winner_id, "duel_id": duel_id})
    
    # Notify both players of the result
    creator_info = get_player_info(duel['creator_id'], conn)
    invited_info = get_player_info(duel['invited_player_id'], conn)

    creator_name = creator_info.get('name', f"Player {duel['creator_id']}")
    invited_name = invited_info.get('name', f"Player {duel['invited_player_id']}")

    creator_score = creator_stats['total_makes']
    invited_score = invited_stats['total_makes']

    if winner_id == duel['creator_id']:
        # Creator won
        notification_service.create_in_app_notification(duel['creator_id'], 'DUEL_WON', f'You defeated {invited_name} {creator_score} to {invited_score}!', {'opponent_name': invited_name, 'your_score': creator_score, 'opponent_score': invited_score, 'duel_id': duel_id}, '/duels', conn=conn)
        notification_service.create_in_app_notification(duel['invited_player_id'], 'DUEL_LOST', f'You lost to {creator_name} {invited_score} to {creator_score}.', {'opponent_name': creator_name, 'your_score': invited_score, 'opponent_score': creator_score, 'duel_id': duel_id}, '/duels', conn=conn)
    elif winner_id == duel['invited_player_id']:
        # Invited player won
        notification_service.create_in_app_notification(duel['invited_player_id'], 'DUEL_WON', f'You defeated {creator_name} {invited_score} to {creator_score}!', {'opponent_name': creator_name, 'your_score': invited_score, 'opponent_score': creator_score, 'duel_id': duel_id}, '/duels', conn=conn)
        notification_service.create_in_app_notification(duel['creator_id'], 'DUEL_LOST', f'You lost to {invited_name} {creator_score} to {invited_score}.', {'opponent_name': invited_name, 'your_score': creator_score, 'opponent_score': invited_score, 'duel_id': duel_id}, '/duels', conn=conn)
    else:
        # Draw
        notification_service.create_in_app_notification(duel['creator_id'], 'DUEL_DRAW', f'Your duel with {invited_name} was a draw {creator_score} to {invited_score}!', {'opponent_name': invited_name, 'your_score': creator_score, 'opponent_score': invited_score, 'duel_id': duel_id}, '/duels', conn=conn)
        notification_service.create_in_app_notification(duel['invited_player_id'], 'DUEL_DRAW', f'Your duel with {creator_name} was a draw {invited_score} to {creator_score}!', {'opponent_name': creator_name, 'your_score': invited_score, 'opponent_score': creator_score, 'duel_id': duel_id}, '/duels', conn=conn)

    logger.info(f"Duel {duel_id} completed. Winner ID: {winner_id if winner_id else 'Draw'}.")

def submit_duel_session(duel_id, session_id, player_id):
    """Updates the duels table with the submitted session ID."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            # Update duels table to mark session as submitted by player
            duel = conn.execute(
                sqlalchemy.text("SELECT creator_id, invited_player_id FROM duels WHERE duel_id = :duel_id"),
                {"duel_id": duel_id}
            ).mappings().first()

            if duel:
                update_column = None
                if duel['creator_id'] == player_id:
                    update_column = "creator_submitted_session_id"
                elif duel['invited_player_id'] == player_id:
                    update_column = "invited_player_submitted_session_id"
                
                if update_column:
                    update_duel_sql = sqlalchemy.text(f"""
                        UPDATE duels SET {update_column} = :session_id
                        WHERE duel_id = :duel_id
                    """)
                    conn.execute(update_duel_sql, {"session_id": session_id, "duel_id": duel_id})
                    logger.info(f"Duel {duel_id} updated: {update_column} set to {session_id}.")
                else:
                    logger.warning(f"Player {player_id} is neither creator nor invited player for duel {duel_id}. No duel update performed.")
            else:
                logger.warning(f"Duel {duel_id} not found when submitting session {session_id}.")

            # After updating, check if the duel can be marked as complete
            check_and_complete_duel(duel_id, conn)

            # Notify the other player that their opponent has submitted a session
            duel_details = get_duel_details(duel_id) # Re-fetch details to get both player IDs
            if duel_details:
                opponent_id = duel_details['creator_id'] if duel_details['invited_player_id'] == player_id else duel_details['invited_player_id']
                opponent_info = get_player_info(opponent_id, conn)
                current_player_info = get_player_info(player_id, conn)
                
                # BUG FIX: Fetch the score from the submitted session to include in the notification
                session_info = conn.execute(
                    sqlalchemy.text("SELECT total_makes FROM sessions WHERE session_id = :session_id"),
                    {"session_id": session_id}
                ).mappings().first()
                score = session_info.get('total_makes') if session_info else 'N/A'
                
                if opponent_info and current_player_info:
                    notification_service.create_in_app_notification(
                        opponent_id, 
                        'DUEL_OPPONENT_SUBMITTED', 
                        f'{current_player_info.get('name', f'Player {player_id}')} has submitted their score for your duel!',
                        {'duel_id': duel_id, 'opponent_name': current_player_info.get('name'), 'score': score},
                        '/duels',
                        conn=conn
                    )
                    notification_service.send_email_notification(
                        opponent_id, 
                        'DUEL_OPPONENT_SUBMITTED', 
                        f'{current_player_info.get('name', f'Player {player_id}')} has submitted their score for your duel!',
                        {'duel_id': duel_id, 'opponent_name': current_player_info.get('name'), 'score': score, 'player_email': opponent_info.get('email')},
                        'duel_opponent_submitted_template'
                    )

        logger.info(f"Session {session_id} submitted to duel {duel_id}.")

def get_leagues_for_player(player_id, conn=None):
    """
    Retrieves two lists of leagues: those the player is a member of,
    and all public leagues they are not a member of.
    Uses a provided connection or creates a new one.
    """
    def _fetch(connection):
        # My Leagues
        my_leagues_sql = sqlalchemy.text("""
            SELECT l.*,
                   (SELECT COUNT(*) FROM league_members WHERE league_id = l.league_id AND status = 'active') as member_count,
                   (SELECT lr.round_number FROM league_rounds lr WHERE lr.league_id = l.league_id AND lr.status = 'active' LIMIT 1) as active_round_number
            FROM leagues l
            JOIN league_members lm ON l.league_id = lm.league_id
            WHERE lm.player_id = :player_id
            ORDER BY l.created_at DESC
        """)
        my_leagues = connection.execute(my_leagues_sql, {"player_id": player_id}).mappings().fetchall()

        # Public Leagues
        public_leagues_sql = sqlalchemy.text("""
            SELECT l.*,
                   (SELECT COUNT(*) FROM league_members WHERE league_id = l.league_id AND status = 'active') as member_count,
                   (SELECT lr.round_number FROM league_rounds lr WHERE lr.league_id = l.league_id AND lr.status = 'active' LIMIT 1) as active_round_number
            FROM leagues l
            WHERE l.privacy_type = 'public' AND NOT EXISTS (
                SELECT 1 FROM league_members lm WHERE lm.league_id = l.league_id AND lm.player_id = :player_id
            )
            ORDER BY l.created_at DESC
        """)
        public_leagues = connection.execute(public_leagues_sql, {"player_id": player_id}).mappings().fetchall()
        return {"my_leagues": [dict(r) for r in my_leagues], "public_leagues": [dict(r) for r in public_leagues]}

    if conn:
        return _fetch(conn)
    pool = get_db_connection()
    with pool.connect() as connection:
        return _fetch(connection)

def _complete_round(round_id, league_id, conn):
    """
    Calculates points for a completed round, updates submissions,
    and activates the next round if applicable.
    """
    logger.info(f"Attempting to complete round {round_id} for league {league_id}.")
    
    # Get total number of members for points calculation (N points for 1st in N-player league)
    member_count = conn.execute(
        sqlalchemy.text("SELECT COUNT(*) FROM league_members WHERE league_id = :league_id AND status = 'active'"),
        {"league_id": league_id}
    ).scalar_one() or 0 # Default to 0 if no members

    # Get submissions, ordered by score to determine rank
    submissions = conn.execute(
        sqlalchemy.text("SELECT submission_id, player_id, score FROM league_round_submissions WHERE round_id = :round_id ORDER BY score DESC"),
        {"round_id": round_id}
    ).mappings().fetchall()

    # Create a map of player_id to their result for notifications
    player_results = {sub['player_id']: {'rank': i + 1, 'score': sub['score']} for i, sub in enumerate(submissions)}

    # Award points based on rank
    for i, submission in enumerate(submissions):
        rank = i + 1
        points = member_count - (rank - 1)
        conn.execute(
            sqlalchemy.text("UPDATE league_round_submissions SET points_awarded = :points WHERE submission_id = :id"),
            {"points": points, "id": submission['submission_id']}
        )
        logger.info(f"Awarded {points} points to player {submission['player_id']} for round {round_id} (Rank: {rank}).")

    # Mark the current round as completed
    conn.execute(
        sqlalchemy.text("UPDATE league_rounds SET status = 'completed' WHERE round_id = :round_id"),
        {"round_id": round_id}
    )

    # Get current round number for notifications
    current_round_number = conn.execute(
        sqlalchemy.text("SELECT round_number FROM league_rounds WHERE round_id = :round_id"),
        {"round_id": round_id}
    ).scalar_one()

    # Notify all active members of the round results
    league_members = conn.execute(sqlalchemy.text("SELECT player_id FROM league_members WHERE league_id = :league_id AND status = 'active'"), {"league_id": league_id}).mappings().fetchall()
    league_info = conn.execute(sqlalchemy.text("SELECT name FROM leagues WHERE league_id = :league_id"), {"league_id": league_id}).mappings().first()
    league_name = league_info.get('name', 'a league') if league_info else 'a league'

    for member in league_members:
        member_id = member['player_id']
        result = player_results.get(member_id)
        
        if result:
            player_rank = result['rank']
            player_score = result['score']
            message = f'Round {current_round_number} of {league_name} has ended. You placed {player_rank} with {player_score} points!'
        else:
            # Player did not submit a score for this round
            player_rank = 'N/A'
            player_score = 'N/A'
            message = f'Round {current_round_number} of {league_name} has ended. You did not submit a score.'

        notification_service.create_in_app_notification(
            member_id, 
            'LEAGUE_ROUND_RESULTS', 
            message,
            {'round_number': current_round_number, 'league_name': league_name, 'league_id': league_id, 'rank': player_rank, 'score': player_score},
            f'/leagues/{league_id}',
            conn=conn
        )
        # Email notification would go here

    # Find and activate the next scheduled round
    next_round = conn.execute(
        sqlalchemy.text("SELECT round_id FROM league_rounds WHERE league_id = :league_id AND round_number = :next_num AND status = 'scheduled'"),
        {"league_id": league_id, "next_num": current_round_number + 1}
    ).mappings().first()

    if next_round:
        conn.execute(
            sqlalchemy.text("UPDATE league_rounds SET status = 'active' WHERE round_id = :round_id"),
            {"round_id": next_round['round_id']}
        )
        logger.info(f"Activated next round {next_round['round_id']} for league {league_id}.")
    else:
        # No more rounds, so complete the league
        conn.execute(
            sqlalchemy.text("UPDATE leagues SET status = 'completed' WHERE league_id = :league_id"),
            {"league_id": league_id}
        )
        logger.info(f"All rounds complete. League {league_id} marked as completed.")

def _create_league_rounds(league_id, league_start_time, settings, conn):
    """Helper to create/recreate rounds for a league."""
    from datetime import datetime, timedelta
    num_rounds = settings.get('num_rounds', 4)
    round_duration_hours = settings.get('round_duration_hours', 168)

    for i in range(num_rounds):
        round_number = i + 1
        round_start_time = league_start_time + timedelta(hours=i * round_duration_hours)
        round_end_time = round_start_time + timedelta(hours=round_duration_hours)
        
        insert_round_sql = sqlalchemy.text("""
            INSERT INTO league_rounds (league_id, round_number, status, start_time, end_time)
            VALUES (:league_id, :round_number, 'scheduled', :start_time, :end_time)
        """)
        conn.execute(insert_round_sql, {
            "league_id": league_id,
            "round_number": round_number,
            "start_time": round_start_time,
            "end_time": round_end_time
        })
    logger.info(f"Created/recreated {num_rounds} rounds for league {league_id}.")

def get_league_details(league_id):
    """Retrieves comprehensive details for a single league."""
    import json
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin(): # Use a single transaction for the entire operation
            # --- Check if a 'registering' league needs to be activated ---
            registering_leagues_to_check = conn.execute(
                sqlalchemy.text("SELECT league_id, start_time FROM leagues WHERE league_id = :id AND status = 'registering'"),
                {"id": league_id}
            ).mappings().fetchall()

            from datetime import datetime, timezone
            now_utc = datetime.now(timezone.utc)

            for league_to_activate in registering_leagues_to_check:
                start_time = league_to_activate['start_time']
                start_time_utc = None
                if isinstance(start_time, str):
                    try:
                        # fromisoformat is more flexible and handles formats like 'YYYY-MM-DD HH:MM:SS.ffffff'
                        start_time_naive = datetime.fromisoformat(start_time)
                    except ValueError:
                        # If fromisoformat fails, log it and skip this league activation check
                        logger.error(f"Could not parse start_time string '{start_time}' for league {league_to_activate['league_id']}. Skipping activation check.")
                        continue
                    start_time_utc = start_time_naive.replace(tzinfo=timezone.utc)
                elif isinstance(start_time, datetime):
                    start_time_utc = start_time.replace(tzinfo=timezone.utc) if start_time.tzinfo is None else start_time
                
                if start_time_utc and now_utc >= start_time_utc:
                    conn.execute(sqlalchemy.text("UPDATE leagues SET status = 'active' WHERE league_id = :id"), {"id": league_to_activate['league_id']})
                    logger.info(f"League {league_to_activate['league_id']} start time reached. Status updated to 'active'.")

            # --- Check if a 'scheduled' round needs to be activated ---
            # This is important for leagues that just became active.
            scheduled_rounds_to_check = conn.execute(
                sqlalchemy.text("""
                    SELECT r.round_id, r.start_time 
                    FROM league_rounds r
                    JOIN leagues l ON r.league_id = l.league_id
                    WHERE r.league_id = :id AND l.status = 'active' AND r.status = 'scheduled'
                    ORDER BY r.round_number ASC
                """),
                {"id": league_id}
            ).mappings().fetchall()

            if scheduled_rounds_to_check:
                # Check if there's already an active round to prevent activating two at once
                active_round_exists = conn.execute(
                    sqlalchemy.text("SELECT 1 FROM league_rounds WHERE league_id = :id AND status = 'active'"),
                    {"id": league_id}
                ).scalar()

                if not active_round_exists:
                    # Only consider the next scheduled round
                    round_to_activate = scheduled_rounds_to_check[0]
                    start_time = round_to_activate['start_time']
                    start_time_utc = datetime.fromisoformat(start_time).replace(tzinfo=timezone.utc) if isinstance(start_time, str) else start_time.replace(tzinfo=timezone.utc)
                    
                    if now_utc >= start_time_utc:
                        conn.execute(sqlalchemy.text("UPDATE league_rounds SET status = 'active' WHERE round_id = :round_id"), {"round_id": round_to_activate['round_id']})
                        logger.info(f"Round {round_to_activate['round_id']} start time reached. Status updated to 'active'.")

            # --- Check for and complete any rounds that have ended ---
            active_rounds_to_check = conn.execute(
                sqlalchemy.text("SELECT round_id, end_time FROM league_rounds WHERE league_id = :id AND status = 'active'"),
                {"id": league_id}
            ).mappings().fetchall()
            # No need to re-import or redefine now_utc

            for r in active_rounds_to_check:
                end_time = r['end_time']
                if not end_time:
                    continue

                end_time_utc = None
                if isinstance(end_time, str):
                    try:
                        end_time_naive = datetime.fromisoformat(end_time)
                    except ValueError:
                        logger.error(f"Could not parse end_time string '{end_time}' for round {r['round_id']}. Skipping round completion check.")
                        continue
                    end_time_utc = end_time_naive.replace(tzinfo=timezone.utc)
                elif isinstance(end_time, datetime): # If it's already a datetime object
                    end_time_utc = end_time.replace(tzinfo=timezone.utc) if end_time.tzinfo is None else end_time
                
                if end_time_utc and now_utc > end_time_utc:
                    _complete_round(r['round_id'], league_id, conn)

            # --- Fetch all details (will now reflect any completed rounds) ---
            league_info = conn.execute(sqlalchemy.text("SELECT * FROM leagues WHERE league_id = :id"), {"id": league_id}).mappings().first()
            if not league_info:
                return None
            
            league_details = dict(league_info)
            league_details['settings'] = json.loads(league_details.get('settings', '{}'))

            # Fetch only active members for the member list
            members_sql = sqlalchemy.text("SELECT p.player_id, p.name FROM league_members lm JOIN players p ON lm.player_id = p.player_id WHERE lm.league_id = :id AND lm.status = 'active' ORDER BY p.name")
            league_details['members'] = [dict(row) for row in conn.execute(members_sql, {"id": league_id}).mappings().fetchall()]

            rounds_sql = sqlalchemy.text("SELECT * FROM league_rounds WHERE league_id = :id ORDER BY round_number")
            rounds = [dict(row) for row in conn.execute(rounds_sql, {"id": league_id}).mappings().fetchall()]

            for r in rounds:
                # FIX: Corrected the parameter marker in the SQL query from :r['round_id'] to :round_id
                submissions_sql = sqlalchemy.text("""
                    SELECT ls.player_id, p.name, ls.score, ls.points_awarded, ls.submitted_at
                    FROM league_round_submissions ls
                    JOIN players p ON ls.player_id = p.player_id
                    WHERE ls.round_id = :round_id
                    ORDER BY ls.score DESC
                """)
                r['submissions'] = [dict(row) for row in conn.execute(submissions_sql, {"round_id": r['round_id']}).mappings().fetchall()]
            
            league_details['rounds'] = rounds
            return league_details

def get_league_round_details(round_id):
    """
    Retrieves details for a specific league round, including its session duration limit.
    """
    pool = get_db_connection()
    with pool.connect() as conn:
        sql = sqlalchemy.text("""
            SELECT lr.*, l.settings
            FROM league_rounds lr
            JOIN leagues l ON lr.league_id = l.league_id
            WHERE lr.round_id = :round_id
        """)
        result = conn.execute(sql, {"round_id": round_id}).mappings().first()
        if result:
            round_details = dict(result)
            league_settings = json.loads(round_details.get('settings', '{}'))
            round_details['session_duration_limit_minutes'] = league_settings.get('time_limit_minutes')
            return round_details
        return None

def get_league_leaderboard_stats(league_id):
    """
    Aggregates session statistics for all players within a specific league.
    """
    pool = get_db_connection()
    with pool.connect() as conn:
        # This query joins members with their submitted sessions in the league
        # to calculate aggregate statistics.
        query = sqlalchemy.text("""
            SELECT
                p.player_id,
                p.name,
                SUM(s.total_makes) AS total_makes,
                SUM(s.total_misses) AS total_misses,
                MAX(s.best_streak) AS best_streak,
                MIN(s.fastest_21_makes) AS fastest_21,
                AVG(s.putts_per_minute) AS avg_ppm,
                AVG(s.makes_per_minute) AS avg_mpm
            FROM players p
            JOIN league_members lm ON p.player_id = lm.player_id
            LEFT JOIN league_round_submissions lrs ON p.player_id = lrs.player_id AND lm.league_id = (SELECT league_id FROM league_rounds WHERE round_id = lrs.round_id)
            LEFT JOIN sessions s ON lrs.session_id = s.session_id
            WHERE lm.league_id = :league_id AND lm.status = 'active'
            GROUP BY p.player_id, p.name
            ORDER BY total_makes DESC, best_streak DESC
        """)
        results = conn.execute(query, {"league_id": league_id}).mappings().fetchall()
        return [dict(row) for row in results]

def create_league(name, description, creator_id, privacy_type, settings):
    """
    Creates a new league, adds the creator as the first member, and returns the league ID.
    """
    import json
    pool = get_db_connection()
    db_type = pool.dialect.name
    from datetime import datetime, timedelta, timezone
    
    with pool.connect() as conn:
        with conn.begin() as trans:
            # Determine league start time and initial status
            start_offset_hours = settings.get('start_offset_hours', 0)
            now = datetime.now(timezone.utc)
            settings.setdefault('allow_late_joiners', False) # Ensure this setting always exists
            league_start_time = now + timedelta(hours=start_offset_hours)
            initial_status = 'registering' if start_offset_hours > 0 else 'active'

            # Step 1: Insert the new league into the 'leagues' table.
            insert_league_sql = sqlalchemy.text("""
                INSERT INTO leagues (name, description, creator_id, privacy_type, settings, start_time, status)
                VALUES (:name, :description, :creator_id, :privacy_type, :settings, :start_time, :status)
            """ + (" RETURNING league_id" if db_type == "postgresql" else ""))
            
            result = conn.execute(insert_league_sql, {
                "name": name,
                "description": description,
                "creator_id": creator_id,
                "privacy_type": privacy_type,
                "settings": json.dumps(settings), # Serialize settings dict to JSON string
                "start_time": league_start_time,
                "status": initial_status
            })

            league_id = result.scalar() if db_type == "postgresql" else result.lastrowid

            # Step 2: Automatically add the creator as the first member.
            insert_member_sql = sqlalchemy.text("""
                INSERT INTO league_members (league_id, player_id, status)
                VALUES (:league_id, :player_id, 'active')
            """)
            conn.execute(insert_member_sql, {
                "league_id": league_id,
                "player_id": creator_id
            })

            _create_league_rounds(league_id, league_start_time, settings, conn)
            
            logger.info(f"Created new league '{name}' (ID: {league_id}) by player {creator_id}.")
            return league_id

def join_league(league_id, player_id):
    """Adds a player to a public league. If the player has a pending invitation, it accepts it."""
    pool = get_db_connection()
    db_type = pool.dialect.name
    with pool.connect() as conn:
        with conn.begin():
            league = conn.execute(sqlalchemy.text("SELECT privacy_type, status, settings FROM leagues WHERE league_id = :id"), {"id": league_id}).mappings().first()
            if not league:
                raise ValueError("League not found.")

            if league['status'] == 'active':
                settings = json.loads(league.get('settings', '{}'))
                if not settings.get('allow_late_joiners', False):
                    raise ValueError("This league is already active and does not allow new players to join.")
            elif league['status'] not in ['registering', 'active']: # Allow joining active if late joins are on
                raise ValueError(f"This league is not open for registration (status: {league['status']}).")

            # Check if the player is already an active member to provide a clear error.
            existing_member = conn.execute(
                sqlalchemy.text("SELECT status FROM league_members WHERE league_id = :league_id AND player_id = :player_id"),
                {"league_id": league_id, "player_id": player_id}
            ).mappings().first()

            if existing_member and existing_member['status'] == 'active':
                raise ValueError("You are already an active member of this league.")
            
            if league['privacy_type'] == 'private' and not existing_member:
                raise ValueError("This is a private league. You must be invited to join.")

            # Use UPSERT to handle both new joins and accepting invitations.
            if db_type == "postgresql":
                upsert_sql = sqlalchemy.text("""
                    INSERT INTO league_members (league_id, player_id, status) VALUES (:league_id, :player_id, 'active')
                    ON CONFLICT (league_id, player_id) DO UPDATE SET status = 'active' WHERE league_members.status = 'invited'
                """)
            else: # SQLite
                upsert_sql = sqlalchemy.text("""
                    INSERT INTO league_members (league_id, player_id, status) VALUES (:league_id, :player_id, 'active')
                    ON CONFLICT(league_id, player_id) DO UPDATE SET status = 'active' WHERE status = 'invited'
                """)
            
            conn.execute(upsert_sql, {"league_id": league_id, "player_id": player_id})
            logger.info(f"Player {player_id} successfully joined or accepted invite for league {league_id}.")

            # Notify the player they joined the league
            league_info = conn.execute(sqlalchemy.text("SELECT name FROM leagues WHERE league_id = :id"), {"id": league_id}).mappings().first()
            league_name = league_info.get('name', 'a league') if league_info else 'a league'
            notification_service.create_in_app_notification(player_id, 'LEAGUE_JOINED', f'Welcome to {league_name}!', {'league_name': league_name, 'league_id': league_id}, f'/leagues/{league_id}', conn=conn)

def invite_to_league(league_id, inviter_id, invitee_identifier):
    """Adds a player to a league with 'invited' status, checking permissions."""
    import json
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            # Resolve the invited player's ID
            invitee = conn.execute(sqlalchemy.text("SELECT player_id FROM players WHERE email = :identifier OR name = :identifier"), {"identifier": invitee_identifier}).mappings().first()
            if not invitee:
                raise ValueError(f"Player with name or email '{invitee_identifier}' not found.")
            invitee_id = invitee['player_id']

            league = conn.execute(
                sqlalchemy.text("SELECT creator_id, privacy_type, settings FROM leagues WHERE league_id = :id"),
                {"id": league_id}
            ).mappings().first()

            if not league:
                raise ValueError("League not found.")
            if inviter_id == invitee_id:
                raise ValueError("You cannot invite yourself.")

            # Check if inviter has permission
            is_creator = league['creator_id'] == inviter_id
            settings = json.loads(league.get('settings', '{}'))
            members_can_invite = settings.get('members_can_invite', False)
            
            is_member = conn.execute(
                sqlalchemy.text("SELECT 1 FROM league_members WHERE league_id = :league_id AND player_id = :player_id AND status = 'active'"),
                {"league_id": league_id, "player_id": inviter_id}
            ).scalar() == 1

            can_invite = is_creator or (is_member and (league['privacy_type'] == 'public' or members_can_invite))

            if not can_invite:
                raise ValueError("You do not have permission to invite players to this league.")

            # Add the invitation
            try:
                insert_sql = sqlalchemy.text("INSERT INTO league_members (league_id, player_id, status) VALUES (:league_id, :player_id, 'invited')")
                conn.execute(insert_sql, {"league_id": league_id, "player_id": invitee_id})
                logger.info(f"Player {inviter_id} invited player {invitee_id} to league {league_id}.")
            except IntegrityError:
                raise ValueError("This player is already a member or has a pending invitation.")

def respond_to_league_invite(league_id, player_id, action):
    """Updates a player's invitation status to 'active' or deletes it."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            if action == 'accept':
                sql = sqlalchemy.text("UPDATE league_members SET status = 'active' WHERE league_id = :league_id AND player_id = :player_id AND status = 'invited'")
            elif action == 'decline':
                sql = sqlalchemy.text("DELETE FROM league_members WHERE league_id = :league_id AND player_id = :player_id AND status = 'invited'")
            else:
                raise ValueError("Invalid action specified.")
            conn.execute(sql, {"league_id": league_id, "player_id": player_id})
            logger.info(f"Player {player_id} {action}ed invitation to league {league_id}.")

def remove_league_member(league_id, admin_id, member_to_remove_id):
    """Removes a member from a league, with creator-only permission."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            # Verify admin_id is the league creator
            creator_id = conn.execute(
                sqlalchemy.text("SELECT creator_id FROM leagues WHERE league_id = :league_id"),
                {"league_id": league_id}
            ).scalar_one_or_none()

            if not creator_id:
                raise ValueError("League not found.")
            if creator_id != admin_id:
                raise ValueError("Only the league creator can remove members.")
            if creator_id == member_to_remove_id:
                raise ValueError("The league creator cannot be removed.")

            # Remove the member
            delete_sql = sqlalchemy.text("DELETE FROM league_members WHERE league_id = :league_id AND player_id = :player_id")
            result = conn.execute(delete_sql, {"league_id": league_id, "player_id": member_to_remove_id})

            if result.rowcount == 0:
                raise ValueError("Member not found in this league.")
            
            logger.info(f"Creator {admin_id} removed member {member_to_remove_id} from league {league_id}.")

def update_league_settings(league_id, editor_id, new_settings):
    """Updates league settings, only if the editor is the creator and the league is in 'registering' state."""
    import json
    from datetime import datetime, timedelta, timezone
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin() as trans:
            # Step 1: Verify permissions and status
            league = trans.execute(
                sqlalchemy.text("SELECT creator_id, status FROM leagues WHERE league_id = :id"),
                {"id": league_id}
            ).mappings().first()

            if not league:
                raise ValueError("League not found.")
            if league['creator_id'] != editor_id:
                raise ValueError("Only the league creator can edit settings.")
            if league['status'] != 'registering':
                raise ValueError("League settings can only be edited before the league starts.")

            # Step 2: Update league settings and start time
            start_offset_hours = new_settings.get('start_offset_hours', 0)
            now = datetime.now(timezone.utc)
            new_start_time = now + timedelta(hours=start_offset_hours)

            update_sql = sqlalchemy.text("UPDATE leagues SET settings = :settings, start_time = :start_time WHERE league_id = :league_id")
            trans.execute(update_sql, {
                "settings": json.dumps(new_settings),
                "start_time": new_start_time,
                "league_id": league_id
            })

            # Step 3: Delete old rounds and recreate them
            trans.execute(sqlalchemy.text("DELETE FROM league_rounds WHERE league_id = :league_id"), {"league_id": league_id})
            _create_league_rounds(league_id, new_start_time, new_settings, trans)

            logger.info(f"League {league_id} settings updated by creator {editor_id}.")

def delete_league(league_id, player_id):
    """Deletes a league, only if the requesting player is the creator."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin() as trans:
            # Step 1: Verify the player is the creator of the league
            league_creator = trans.execute(
                sqlalchemy.text("SELECT creator_id FROM leagues WHERE league_id = :id"),
                {"id": league_id}
            ).scalar_one_or_none()

            if league_creator is None:
                raise ValueError("League not found.")
            
            if league_creator != player_id:
                raise ValueError("Only the league creator can delete the league.")

            # Step 2: Delete the league.
            # Assumes that foreign key constraints (e.g., in league_members, league_rounds)
            # are set up with ON DELETE CASCADE.
            trans.execute(sqlalchemy.text("DELETE FROM leagues WHERE league_id = :id"), {"id": league_id})
            logger.info(f"Player {player_id} deleted league {league_id}.")

def expire_pending_duels():
    """Expires pending duels that have passed their invitation deadline."""
    from datetime import datetime, timezone
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            now = datetime.now(timezone.utc)
            expired_duels_sql = sqlalchemy.text("""
                SELECT duel_id, creator_id, invited_player_id
                FROM duels 
                WHERE status = 'pending' AND invitation_expires_at < :now
            """)
            expired_duels = conn.execute(expired_duels_sql, {"now": now}).mappings().fetchall()

            if not expired_duels:
                return

            for duel in expired_duels:
                update_sql = sqlalchemy.text("UPDATE duels SET status = 'expired' WHERE duel_id = :duel_id")
                conn.execute(update_sql, {"duel_id": duel['duel_id']})

                # Notify both players
                creator_info = get_player_info(duel['creator_id'], conn)
                invited_info = get_player_info(duel['invited_player_id'], conn)
                
                if creator_info and invited_info:
                    message = f"Your duel with {invited_info['name']} has expired."
                    notification_service.create_in_app_notification(duel['creator_id'], 'DUEL_EXPIRED', message, {'opponent_name': invited_info['name'], 'duel_id': duel['duel_id']}, '/duels', conn=conn)
                    
                    message = f"Your duel with {creator_info['name']} has expired."
                    notification_service.create_in_app_notification(duel['invited_player_id'], 'DUEL_EXPIRED', message, {'opponent_name': creator_info['name'], 'duel_id': duel['duel_id']}, '/duels', conn=conn)
                
                logger.info(f"Expired duel {duel['duel_id']}.")

def start_pending_league_rounds():
    """Starts league rounds that are scheduled to begin and notifies members."""
    from datetime import datetime, timezone
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            now = datetime.now(timezone.utc)
            rounds_to_start_sql = sqlalchemy.text("""
                SELECT r.round_id, r.league_id, r.round_number, l.name as league_name
                FROM league_rounds r
                JOIN leagues l ON r.league_id = l.league_id
                WHERE r.status = 'scheduled' AND r.start_time <= :now
            """)
            rounds_to_start = conn.execute(rounds_to_start_sql, {"now": now}).mappings().fetchall()

            if not rounds_to_start:
                return

            for round_info in rounds_to_start:
                update_sql = sqlalchemy.text("UPDATE league_rounds SET status = 'active' WHERE round_id = :round_id")
                conn.execute(update_sql, {"round_id": round_info['round_id']})

                # Notify all league members
                members_sql = sqlalchemy.text("SELECT player_id FROM league_members WHERE league_id = :league_id AND status = 'active'")
                members = conn.execute(members_sql, {"league_id": round_info['league_id']}).mappings().fetchall()

                for member in members:
                    message = f"Round {round_info['round_number']} of {round_info['league_name']} is starting!"
                    details = {
                        'round_num': round_info['round_number'],
                        'league_name': round_info['league_name'],
                        'league_id': round_info['league_id']
                    }
                    notification_service.create_in_app_notification(member['player_id'], 'LEAGUE_ROUND_STARTING', message, details, f"/leagues/{round_info['league_id']}", conn=conn)
                
                logger.info(f"Started league round {round_info['round_id']} for league {round_info['league_id']}.")

def send_league_reminders():
    """Finds players who need a reminder for an ending league round and notifies them."""
    from datetime import datetime, timedelta, timezone
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            now = datetime.now(timezone.utc)
            reminder_threshold = now + timedelta(hours=24)

            reminders_sql = sqlalchemy.text("""
                SELECT lm.player_id, lr.round_id, lr.round_number, l.name as league_name, l.league_id
                FROM league_members lm
                JOIN league_rounds lr ON lm.league_id = lr.league_id
                JOIN leagues l ON lm.league_id = l.league_id
                WHERE lr.status = 'active'
                  AND lr.end_time BETWEEN :now AND :threshold
                  AND NOT EXISTS (
                      SELECT 1 FROM league_round_submissions lrs
                      WHERE lrs.round_id = lr.round_id AND lrs.player_id = lm.player_id
                  )
            """)
            players_to_remind = conn.execute(reminders_sql, {"now": now, "threshold": reminder_threshold}).mappings().fetchall()

            for player in players_to_remind:
                message = f"Reminder: Submit your score for Round {player['round_number']} of {player['league_name']}!"
                details = {'round_num': player['round_number'], 'league_name': player['league_name'], 'league_id': player['league_id']}
                notification_service.create_in_app_notification(player['player_id'], 'LEAGUE_REMINDER', message, details, f"/leagues/{player['league_id']}", conn=conn)
                logger.info(f"Sent league reminder to player {player['player_id']} for round {player['round_id']}.")

def process_final_league_results():
    """Calculates and sends final league results for completed leagues."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            leagues_to_process_sql = sqlalchemy.text("SELECT league_id, name FROM leagues WHERE status = 'completed' AND final_notifications_sent = FALSE")
            leagues = conn.execute(leagues_to_process_sql).mappings().fetchall()

            for league in leagues:
                # Logic to calculate final rankings
                # This is a simplified example; a real implementation might be more complex
                ranking_sql = sqlalchemy.text("""
                    SELECT player_id, SUM(points_awarded) as total_points
                    FROM league_round_submissions
                    WHERE round_id IN (SELECT round_id FROM league_rounds WHERE league_id = :league_id)
                    GROUP BY player_id
                    ORDER BY total_points DESC
                """)
                rankings = conn.execute(ranking_sql, {"league_id": league['league_id']}).mappings().fetchall()
                
                # Notify all members of their final rank
                members_sql = sqlalchemy.text("SELECT player_id FROM league_members WHERE league_id = :league_id")
                members = conn.execute(members_sql, {"league_id": league['league_id']}).mappings().fetchall()

                for member in members:
                    final_rank = "N/A"
                    for i, ranked_player in enumerate(rankings):
                        if ranked_player['player_id'] == member['player_id']:
                            final_rank = i + 1
                            break
                    
                    message = f"{league['name']} has concluded! You finished with a final rank of {final_rank}."
                    details = {'league_name': league['name'], 'league_id': league['league_id'], 'final_rank': final_rank}
                    notification_service.create_in_app_notification(member['player_id'], 'LEAGUE_FINAL_RESULTS', message, details, f"/leagues/{league['league_id']}", conn=conn)

                # Mark notifications as sent
                update_sql = sqlalchemy.text("UPDATE leagues SET final_notifications_sent = TRUE WHERE league_id = :league_id")
                conn.execute(update_sql, {"league_id": league['league_id']})
                logger.info(f"Sent final results notifications for league {league['league_id']}.")

def send_fundraiser_reminders():
    """Sends reminders for fundraisers that are ending soon."""
    from datetime import datetime, timedelta, timezone
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            now = datetime.now(timezone.utc)
            threshold = now + timedelta(hours=24)
            reminders_sql = sqlalchemy.text("SELECT fundraiser_id, player_id, name FROM fundraisers WHERE status = 'active' AND end_time BETWEEN :now AND :threshold")
            fundraisers = conn.execute(reminders_sql, {"now": now, "threshold": threshold}).mappings().fetchall()

            for fundraiser in fundraisers:
                message = f"Your fundraiser '{fundraiser['name']}' is ending soon. Make one last push!"
                details = {'fundraiser_name': fundraiser['name'], 'fundraiser_id': fundraiser['fundraiser_id']}
                notification_service.create_in_app_notification(fundraiser['player_id'], 'FUNDRAISER_ENDING_SOON', message, details, f"/fundraisers/{fundraiser['fundraiser_id']}", conn=conn)
                logger.info(f"Sent ending soon reminder for fundraiser {fundraiser['fundraiser_id']}.")

def process_concluded_fundraisers():
    """Sends notifications for fundraisers that have ended."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            fundraisers_sql = sqlalchemy.text("SELECT fundraiser_id, player_id, name FROM fundraisers WHERE status = 'completed' AND conclusion_notification_sent = FALSE")
            fundraisers = conn.execute(fundraisers_sql).mappings().fetchall()

            for fundraiser in fundraisers:
                details = get_fundraiser_details(fundraiser['fundraiser_id'], conn)
                amount_raised = details.get('amount_raised', 0.0)
                message = f"Your fundraiser '{fundraiser['name']}' has ended. You raised a total of ${amount_raised:.2f}! Thank you!"
                notification_details = {'fundraiser_name': fundraiser['name'], 'total_raised': amount_raised, 'fundraiser_id': fundraiser['fundraiser_id']}
                notification_service.create_in_app_notification(fundraiser['player_id'], 'FUNDRAISER_CONCLUDED', message, notification_details, f"/fundraisers/{fundraiser['fundraiser_id']}", conn=conn)

                # Mark as sent
                update_sql = sqlalchemy.text("UPDATE fundraisers SET conclusion_notification_sent = TRUE WHERE fundraiser_id = :id")
                conn.execute(update_sql, {"id": fundraiser['fundraiser_id']})
                logger.info(f"Sent conclusion notification for fundraiser {fundraiser['fundraiser_id']}.")

def submit_league_session(round_id, player_id, session_id, score):
    """Submits a player's session score to a league round."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            insert_sql = sqlalchemy.text("""
                INSERT INTO league_round_submissions (round_id, player_id, session_id, score)
                VALUES (:round_id, :player_id, :session_id, :score)
            """)
            try:
                conn.execute(insert_sql, {
                    "round_id": round_id,
                    "player_id": player_id,
                    "session_id": session_id,
                    "score": score
                })
                logger.info(f"Player {player_id} submitted score {score} from session {session_id} to round {round_id}.")

                # Notify the player that their score has been submitted for the league round
                league_round_info = conn.execute(sqlalchemy.text("SELECT lr.round_number, l.name, l.league_id FROM league_rounds lr JOIN leagues l ON lr.league_id = l.league_id WHERE lr.round_id = :round_id"), {"round_id": round_id}).mappings().first()
                if league_round_info:
                    round_number = league_round_info.get('round_number', 'unknown')
                    league_name = league_round_info.get('name', 'a league')
                    notification_service.create_in_app_notification(player_id, 'LEAGUE_SESSION_COMPLETED', f'Your score of {score} has been submitted for Round {round_number} of {league_name}.', {'score': score, 'round_number': round_number, 'league_name': league_name, 'league_id': league_round_info['league_id']}, f'/leagues/{league_round_info['league_id']}', conn=conn)

            except IntegrityError:
                raise ValueError("A score has already been submitted for this player in this round.")

def _calculate_amount_raised(fundraiser_details, conn):
    """Helper to calculate and add 'amount_raised' to a fundraiser dictionary."""
    from datetime import datetime # Import here to avoid circular dependency issues at top level

    # Ensure start/end times are in a consistent string format for SQL queries.
    # This prevents errors when comparing Python datetime objects against TEXT columns in SQLite.
    start_time = fundraiser_details['start_time']
    end_time = fundraiser_details['end_time']

    start_time_str = start_time.isoformat() if isinstance(start_time, datetime) else start_time
    end_time_str = end_time.isoformat() if isinstance(end_time, datetime) else end_time
    putts_sql = sqlalchemy.text("""
        SELECT SUM(total_makes) FROM sessions
        WHERE player_id = :player_id AND status = 'completed'
        AND start_time >= :start_time AND end_time <= :end_time
    """)
    total_putts = conn.execute(putts_sql, {
        "player_id": fundraiser_details['player_id'],
        "start_time": start_time_str,
        "end_time": end_time_str
    }).scalar() or 0

    pledge_sql = sqlalchemy.text("SELECT SUM(amount_per_putt) FROM pledges WHERE fundraiser_id = :id AND status = 'active'")
    total_pledge_per_putt = conn.execute(pledge_sql, {"id": fundraiser_details['fundraiser_id']}).scalar() or 0.0
    
    fundraiser_details['total_putts_made'] = total_putts
    fundraiser_details['amount_raised'] = total_putts * total_pledge_per_putt
    return fundraiser_details

def create_fundraiser(player_id, name, cause, description, goal_amount, start_time, end_time):
    """Creates a new fundraiser and returns its ID."""
    pool = get_db_connection()
    db_type = pool.dialect.name
    with pool.connect() as conn:
        with conn.begin():
            sql = sqlalchemy.text("""
                INSERT INTO fundraisers (player_id, name, cause, description, goal_amount, start_time, end_time)
                VALUES (:player_id, :name, :cause, :description, :goal_amount, :start_time, :end_time)
            """ + (" RETURNING fundraiser_id" if db_type == "postgresql" else ""))
            
            result = conn.execute(sql, {
                "player_id": player_id, "name": name, "cause": cause, "description": description,
                "goal_amount": goal_amount, "start_time": start_time, "end_time": end_time
            })
            
            logger.info(f"Player {player_id} created fundraiser '{name}'.")
            if db_type == "postgresql":
                return result.scalar()
            return result.lastrowid

def get_all_fundraisers():
    """Retrieves a list of all fundraisers, including player name and amount raised."""
    pool = get_db_connection()
    with pool.connect() as conn:
        # This approach is simplified for clarity. For performance at scale,
        # a more complex single query or denormalization would be better.
        sql = sqlalchemy.text("""
            SELECT f.*, p.name as player_name
            FROM fundraisers f
            JOIN players p ON f.player_id = p.player_id
            ORDER BY f.start_time DESC
        """)
        fundraisers = conn.execute(sql).mappings().fetchall()
        return [_calculate_amount_raised(dict(f), conn) for f in fundraisers]

def get_fundraiser_details(fundraiser_id):
    """Retrieves details for a single fundraiser and calculates the amount raised."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            # Step 1: Get basic fundraiser info
            fundraiser_sql = sqlalchemy.text("""
                SELECT f.*, p.name as player_name
                FROM fundraisers f
                JOIN players p ON f.player_id = p.player_id
                WHERE f.fundraiser_id = :id
            """)
            fundraiser = conn.execute(fundraiser_sql, {"id": fundraiser_id}).mappings().first()
            if not fundraiser:
                return None
            
            details = dict(fundraiser)

            # Step 2: Update fundraiser status based on current time
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            
            # Ensure start_time and end_time are datetime objects before comparison
            start_time_val = details['start_time']
            if isinstance(start_time_val, str):
                start_time_val = datetime.fromisoformat(start_time_val)
            
            end_time_val = details['end_time']
            if isinstance(end_time_val, str):
                end_time_val = datetime.fromisoformat(end_time_val)

            start_time = start_time_val.replace(tzinfo=timezone.utc) if start_time_val.tzinfo is None else start_time_val
            end_time = end_time_val.replace(tzinfo=timezone.utc) if end_time_val.tzinfo is None else end_time_val
            current_status = details['status']
            new_status = current_status

            if current_status != 'completed' and now >= end_time:
                new_status = 'completed'
            elif current_status == 'upcoming' and now >= start_time:
                new_status = 'active'
            
            if new_status != current_status:
                conn.execute(
                    sqlalchemy.text("UPDATE fundraisers SET status = :status WHERE fundraiser_id = :id"),
                    {"status": new_status, "id": fundraiser_id}
                )
                details['status'] = new_status

            # Step 3: Calculate amount raised
            # The details dict still has the original str/datetime, which is fine
            # because _calculate_amount_raised is now robust.
            details_with_amount = _calculate_amount_raised(details.copy(), conn)

            # Step 4: Get all pledges for this fundraiser
            pledges_sql = sqlalchemy.text("""
                SELECT pl.*, p.name as pledger_name
                FROM pledges pl
                JOIN players p ON pl.pledger_player_id = p.player_id
                WHERE pl.fundraiser_id = :id
                ORDER BY pl.amount_per_putt DESC
            """)
            pledges = conn.execute(pledges_sql, {"id": fundraiser_id}).mappings().fetchall()
            details_with_amount['pledges'] = [dict(p) for p in pledges]

            # Step 5: Get all sessions that occurred during the fundraiser
            sessions_sql = sqlalchemy.text("""
                SELECT session_id, start_time, total_makes, session_duration
                FROM sessions
                WHERE player_id = :player_id AND status = 'completed'
                AND start_time >= :start_time AND end_time <= :end_time
                ORDER BY start_time ASC
            """)
            sessions = conn.execute(sessions_sql, {"player_id": details['player_id'], "start_time": details['start_time'], "end_time": details['end_time']}).mappings().fetchall()
            details_with_amount['sessions'] = [dict(s) for s in sessions]

            return details_with_amount

def get_pledges_for_player(player_id):
    """Retrieves a list of fundraisers a player has pledged to, including amount raised."""
    pool = get_db_connection()
    with pool.connect() as conn:
        sql = sqlalchemy.text("""
            SELECT f.*, p.name as player_name
            FROM fundraisers f
            JOIN pledges pl ON f.fundraiser_id = pl.fundraiser_id
            JOIN players p ON f.player_id = p.player_id
            WHERE pl.pledger_player_id = :player_id
            ORDER BY f.start_time DESC
        """)
        fundraisers = conn.execute(sql, {"player_id": player_id}).mappings().fetchall()
        
        # Process timestamps before calculating amounts
        from datetime import datetime
        processed_fundraisers = []
        for f in fundraisers:
            f_dict = dict(f)
            if isinstance(f_dict.get('start_time'), str):
                f_dict['start_time'] = datetime.fromisoformat(f_dict['start_time'])
            if isinstance(f_dict.get('end_time'), str):
                f_dict['end_time'] = datetime.fromisoformat(f_dict['end_time'])
            processed_fundraisers.append(f_dict)
        
        return [_calculate_amount_raised(f, conn) for f in processed_fundraisers]

def create_pledge(fundraiser_id, pledger_player_id, amount_per_putt, max_donation=None):
    """Creates a new pledge for a fundraiser."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            # In a real app, this is where you would interact with Stripe to
            # create a customer and save a payment method before inserting the pledge.
            sql = sqlalchemy.text("INSERT INTO pledges (fundraiser_id, pledger_player_id, amount_per_putt, max_donation) VALUES (:fid, :pid, :amt, :max)")
            conn.execute(sql, {"fid": fundraiser_id, "pid": pledger_player_id, "amt": amount_per_putt, "max": max_donation})
            logger.info(f"Player {pledger_player_id} pledged {amount_per_putt}/putt to fundraiser {fundraiser_id}.")

def update_fundraiser_progress(player_id, conn):
    """
    Checks for fundraiser progress after a session, sending notifications for milestones.
    This function should be called within an existing database transaction.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    
    # Find active fundraisers for the player
    active_fundraisers_sql = sqlalchemy.text("""
        SELECT fundraiser_id, name, goal_amount, last_notified_milestone
        FROM fundraisers
        WHERE player_id = :player_id AND status = 'active' AND end_time > :now
    """)
    active_fundraisers = conn.execute(active_fundraisers_sql, {"player_id": player_id, "now": now}).mappings().fetchall()

    if not active_fundraisers:
        return

    for fundraiser in active_fundraisers:
        # Recalculate the amount raised for this fundraiser
        details_for_calc = get_fundraiser_details(fundraiser['fundraiser_id'], conn)
        if not details_for_calc:
            continue

        amount_raised = details_for_calc.get('amount_raised', 0.0)
        goal_amount = fundraiser['goal_amount']
        
        if goal_amount <= 0:
            continue

        progress_percent = (amount_raised / goal_amount) * 100
        milestones = [25, 50, 75, 100]
        last_notified = fundraiser['last_notified_milestone']
        
        for milestone in milestones:
            if progress_percent >= milestone and last_notified < milestone:
                # Send notification for this milestone
                if milestone == 100:
                    # Goal Reached Notification
                    notification_service.create_in_app_notification(
                        player_id,
                        'FUNDRAISER_GOAL_REACHED',
                        f"Congratulations! You've reached your goal for {fundraiser['name']}!",
                        {'amount_raised': amount_raised, 'fundraiser_name': fundraiser['name'], 'fundraiser_id': fundraiser['fundraiser_id']},
                        f"/fundraisers/{fundraiser['fundraiser_id']}",
                        conn=conn
                    )
                else:
                    # Milestone Reached Notification
                    notification_service.create_in_app_notification(
                        player_id,
                        'FUNDRAISER_MILESTONE',
                        f"You've passed {milestone}% of your goal for {fundraiser['name']}!",
                        {'milestone_percent': milestone, 'amount_raised': amount_raised, 'fundraiser_name': fundraiser['name'], 'fundraiser_id': fundraiser['fundraiser_id']},
                        f"/fundraisers/{fundraiser['fundraiser_id']}",
                        conn=conn
                    )
                
                # Update the last notified milestone in the database
                update_milestone_sql = sqlalchemy.text("UPDATE fundraisers SET last_notified_milestone = :milestone WHERE fundraiser_id = :id")
                conn.execute(update_milestone_sql, {"milestone": milestone, "id": fundraiser['fundraiser_id']})
                logger.info(f"Notified player {player_id} of {milestone}% milestone for fundraiser {fundraiser['fundraiser_id']}.")

def update_session(session_id, reporter): # Removed conn argument
    """
    Updates a session with the final results from the tracker.
    """
    import json
    fastest_21 = reporter.fastest_21_makes if reporter.fastest_21_makes != float('inf') else None

    session_data = {
        "session_id": session_id,
        "total_makes": reporter.total_makes,
        "total_misses": reporter.total_misses,
        "best_streak": reporter.max_consecutive_makes,
        "fastest_21_makes": fastest_21,
        "makes_by_category": json.dumps(reporter.makes_by_category),
        "misses_by_category": json.dumps(reporter.misses_by_category),
        "putt_list": json.dumps(reporter.putt_data),
        "putts_per_minute": round(reporter.putts_per_minute, 2),
        "makes_per_minute": round(reporter.makes_per_minute, 2), # Add makes_per_minute
        "most_makes_in_60_seconds": reporter.most_makes_in_60_seconds, # Added
        "session_duration": reporter.session_duration, # Added
        "status": "completed"
    }

    pool = get_db_connection() # Get pool here
    with pool.connect() as conn:
        with conn.begin(): # Added transaction
            # Get player_id from session_id for notifications
            player_id = conn.execute(
                sqlalchemy.text("SELECT player_id FROM sessions WHERE session_id = :session_id"),
                {"session_id": session_id}
            ).scalar_one_or_none()

            # --- Personal Best Notification Logic ---
            if player_id:
                # Fetch career stats *before* this session is factored in
                career_stats = get_player_stats(player_id, conn)
                if career_stats:
                    # Compare current session stats with career stats
                    if reporter.max_consecutive_makes > career_stats.get('best_streak', 0):
                        notification_service.create_in_app_notification(player_id, 'NEW_PERSONAL_BEST', f"New Personal Best! You set a new record for Best Streak with a value of {reporter.max_consecutive_makes}!", {'metric_name': 'Best Streak', 'value': reporter.max_consecutive_makes}, '/career-stats', conn=conn)
                    
                    # Note: For fastest_21, lower is better
                    if fastest_21 and (career_stats.get('fastest_21_makes') is None or fastest_21 < career_stats.get('fastest_21_makes')):
                         notification_service.create_in_app_notification(player_id, 'NEW_PERSONAL_BEST', f"New Personal Best! You set a new record for Fastest 21 Makes with a time of {fastest_21:.2f}s!", {'metric_name': 'Fastest 21 Makes', 'value': f"{fastest_21:.2f}s"}, '/career-stats', conn=conn)

            end_time_sql = "CURRENT_TIMESTAMP" if pool.dialect.name == "postgresql" else "CURRENT_TIMESTAMP"
            
            update_sql = sqlalchemy.text(f"""
                UPDATE sessions SET
                    end_time = {end_time_sql},
                    total_makes = :total_makes,
                    total_misses = :total_misses,
                    best_streak = :best_streak,
                    fastest_21_makes = :fastest_21_makes,
                    makes_by_category = :makes_by_category,
                    misses_by_category = :misses_by_category,
                    putt_list = :putt_list,
                    putts_per_minute = :putts_per_minute,
                    makes_per_minute = :makes_per_minute,
                    most_makes_in_60_seconds = :most_makes_in_60_seconds,
                    session_duration = :session_duration,
                    status = :status
                WHERE session_id = :session_id
            """)
        
            conn.execute(update_sql, session_data)
            logger.info(f"Updated session {session_id} with final results.")

            # --- Session Report Ready Notification ---
            if player_id:
                notification_service.create_in_app_notification(
                    player_id,
                    'SESSION_REPORT_READY',
                    'Your session report is ready!',
                    {'session_id': session_id, 'makes': reporter.total_makes, 'misses': reporter.total_misses, 'mpm': round(reporter.makes_per_minute, 2)},
                    f'/session/{session_id}',
                    conn=conn
                )

                # --- Check for fundraiser progress ---
                update_fundraiser_progress(player_id, conn)

def recalculate_player_stats(player_id): # Removed conn argument
    """
    Recalculates and updates a player's all-time stats.
    """
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin(): # Added transaction
            sessions = conn.execute(
                sqlalchemy.text("SELECT total_makes, total_misses, best_streak, fastest_21_makes FROM sessions WHERE player_id = :id AND status = 'completed'"),
                {"id": player_id}
            ).mappings().fetchall()

            total_makes = sum(s['total_makes'] for s in sessions if s['total_makes'] is not None)
            total_misses = sum(s['total_misses'] for s in sessions if s['total_misses'] is not None)
            best_streak = max((s['best_streak'] for s in sessions if s['best_streak'] is not None), default=0)
            
            valid_fastest_times = [s['fastest_21_makes'] for s in sessions if s['fastest_21_makes'] is not None]
            fastest_21_makes = min(valid_fastest_times) if valid_fastest_times else None

            update_sql = sqlalchemy.text("""
                UPDATE player_stats SET
                    total_makes = :total_makes,
                    total_misses = :total_misses,
                    best_streak = :best_streak,
                    fastest_21_makes = :fastest_21_makes
                WHERE player_id = :player_id
            """)
            conn.execute(update_sql, {
                "player_id": player_id,
                "total_makes": total_makes,
                "total_misses": total_misses,
                "best_streak": best_streak,
                "fastest_21_makes": fastest_21_makes
            })
            logger.info(f"Recalculated all-time stats for player {player_id}.")

def get_leaderboard(sort_by='makes'):
    """
    Retrieves the full player leaderboard, including player_id for linking.
    Can be sorted using the 'sort_by' query parameter.
    """
    pool = get_db_connection()
    
    # Define the base query
    query_sql = """
        SELECT p.player_id, p.name, s.total_makes, s.best_streak, s.fastest_21_makes
        FROM players p
        JOIN player_stats s ON p.player_id = s.player_id
    """
    
    # Define sorting logic
    order_by_clause = {
        'name': 'ORDER BY p.name ASC',
        'makes': 'ORDER BY s.total_makes DESC, s.best_streak DESC',
        'streak': 'ORDER BY s.best_streak DESC, s.total_makes DESC',
        'fastest21': 'ORDER BY s.fastest_21_makes ASC, s.total_makes DESC'
    }.get(sort_by, 'ORDER BY s.total_makes DESC') # Default sort

    if sort_by == 'fastest21':
        order_by_clause = 'ORDER BY s.fastest_21_makes IS NULL, s.fastest_21_makes ASC, s.total_makes DESC'

    final_query = sqlalchemy.text(f"{query_sql} {order_by_clause}")

    with pool.connect() as conn:
        results = conn.execute(final_query).mappings().fetchall()
        return [dict(row) for row in results]

def get_session_leaderboards():
    """Retrieves top 3 single-session performances for key stats."""
    pool = get_db_connection()
    leaderboards = []

    stats_to_query = [
        ("Makes", "total_makes"),
        ("Best Streak", "best_streak"),
        ("Fastest 21", "fastest_21_makes"),
        ("Makes Per Minute", "makes_per_minute")
    ]

    with pool.connect() as conn:
        for title, column in stats_to_query:
            order = "ASC" if column == "fastest_21_makes" else "DESC"
            
            db_type = pool.dialect.name
            if column == "session_duration":
                if db_type == 'postgresql':
                    value_expression = "EXTRACT(EPOCH FROM (s.end_time - s.start_time))"
                else: # SQLite
                    value_expression = "(julianday(s.end_time) - julianday(s.start_time)) * 86400"
                where_clause = f"WHERE s.end_time IS NOT NULL AND s.start_time IS NOT NULL AND s.status = 'completed'"
            else:
                value_expression = f"s.{column}"
                where_clause = f"WHERE s.{column} IS NOT NULL AND s.status = 'completed'"

            query = sqlalchemy.text(f'''
                SELECT p.name, {value_expression} AS value
                FROM sessions s
                JOIN players p ON s.player_id = p.player_id
                {where_clause}
                ORDER BY value {order}
                LIMIT 3
            ''')
            
            results = conn.execute(query).mappings().fetchall()
            leaderboards.append({"title": title, "leaders": [dict(row) for row in results]})
    
    return leaderboards

def calculate_consecutive_streaks(putt_list_json):
    """
    Calculates the count of consecutive make streaks for various categories.

    Args:
        putt_list_json: A JSON string representing a list of putts.

    Returns:
        A dictionary with the counts for each streak category.
    """
    import json
    
    categories = [3, 7, 10, 15, 21, 50, 100]
    streak_counts = {str(c): 0 for c in categories}

    if not putt_list_json:
        return streak_counts

    try:
        putt_list = json.loads(putt_list_json)
    except json.JSONDecodeError:
        return streak_counts

    streaks = []
    current_streak = 0
    for putt in putt_list:
        if putt.get('Putt Classification', '').upper() == 'MAKE':
            current_streak += 1
        else:
            if current_streak > 0:
                streaks.append(current_streak)
            current_streak = 0
    if current_streak > 0:
        streaks.append(current_streak)

    for streak in streaks:
        for category in categories:
            if streak >= category:
                streak_counts[str(category)] += streak // category

    return streak_counts

def get_player_by_name(player_name):
    """Finds a player by their name or email (case-insensitive) and returns their ID."""
    pool = get_db_connection()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT player_id FROM players WHERE LOWER(email) = :name OR LOWER(name) = :name"),
            {"name": player_name.lower()}
        ).scalar_one_or_none()
        return result

def search_players_by_name(search_term):
    """Searches for players whose names or emails contain the search term (case-insensitive)."""
    pool = get_db_connection()
    with pool.connect() as conn:
        # Using ILIKE for case-insensitive search (PostgreSQL) or LIKE for SQLite
        # and handling the wildcard for 'contains' search.
        search_pattern = f"%{search_term.lower()}%"
        
        results = conn.execute(
            sqlalchemy.text("SELECT player_id, name, email FROM players WHERE LOWER(name) LIKE :search_pattern OR LOWER(email) LIKE :search_pattern"),
            {"search_pattern": search_pattern}
        ).mappings().fetchall()
        
        # Return a list of dictionaries with player_id and name
        return [{'player_id': row['player_id'], 'name': row['name'], 'email': row['email']} for row in results]

def follow_player(follower_id, followed_id):
    """Creates a follow relationship between two players."""
    if follower_id == followed_id:
        raise ValueError("You cannot follow yourself.")
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            try:
                sql = sqlalchemy.text("INSERT INTO player_relationships (follower_id, followed_id) VALUES (:follower_id, :followed_id)")
                conn.execute(sql, {"follower_id": follower_id, "followed_id": followed_id})
                logger.info(f"Player {follower_id} started following player {followed_id}.")
            except IntegrityError:
                # This will be raised if the relationship already exists, which is fine.
                logger.warning(f"Attempted to create a follow relationship that already exists between {follower_id} and {followed_id}.")
                pass # Or raise a specific error if you want to notify the user they are already following.

def unfollow_player(follower_id, followed_id):
    """Removes a follow relationship."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            sql = sqlalchemy.text("DELETE FROM player_relationships WHERE follower_id = :follower_id AND followed_id = :followed_id")
            conn.execute(sql, {"follower_id": follower_id, "followed_id": followed_id})
            logger.info(f"Player {follower_id} unfollowed player {followed_id}.")

def get_followers(player_id):
    """Gets a list of players who are following the given player_id."""
    pool = get_db_connection()
    with pool.connect() as conn:
        sql = sqlalchemy.text("""
            SELECT p.player_id, p.name, p.email 
            FROM players p
            JOIN player_relationships pr ON p.player_id = pr.follower_id
            WHERE pr.followed_id = :player_id
        """)
        results = conn.execute(sql, {"player_id": player_id}).mappings().fetchall()
        return [dict(row) for row in results]

def get_following(player_id):
    """Gets a list of players that the given player_id is following."""
    pool = get_db_connection()
    with pool.connect() as conn:
        sql = sqlalchemy.text("""
            SELECT p.player_id, p.name, p.email
            FROM players p
            JOIN player_relationships pr ON p.player_id = pr.followed_id
            WHERE pr.follower_id = :player_id
        """)
        results = conn.execute(sql, {"player_id": player_id}).mappings().fetchall()
        return [dict(row) for row in results]

def create_historical_session(player_id, session_date, reporter):
    """Creates a historical session entry from a backfilled log."""
    import json
    pool = get_db_connection()
    
    fastest_21 = reporter.fastest_21_makes if reporter.fastest_21_makes != float('inf') else None

    with pool.connect() as conn:
        with conn.begin(): # Ensure transaction for historical session creation
            insert_sql = sqlalchemy.text("""
                INSERT INTO sessions (player_id, start_time, end_time, total_makes, total_misses, best_streak, fastest_21_makes, putts_per_minute, makes_per_minute, makes_by_category, misses_by_category, putt_list, status)
                VALUES (:player_id, :start_time, :end_time, :total_makes, :total_misses, :best_streak, :fastest_21_makes, :putts_per_minute, :makes_per_minute, :makes_by_category, :misses_by_category, :putt_list, 'completed')
            """)
            conn.execute(insert_sql, {
                "player_id": player_id,
                "start_time": session_date,
                "end_time": session_date,
                "total_makes": reporter.total_makes,
                "total_misses": reporter.total_misses,
                "best_streak": reporter.max_consecutive_makes,
                "fastest_21_makes": fastest_21,
                "putts_per_minute": round(reporter.putts_per_minute, 2), # Added
                "makes_per_minute": round(reporter.makes_per_minute, 2), # Added
                "makes_by_category": json.dumps(reporter.makes_by_category),
                "misses_by_category": json.dumps(reporter.misses_by_category),
                "putt_list": json.dumps(reporter.putt_data)
            })
        logger.info(f"Created historical session for player {player_id} on {session_date}.")

def list_all_players():
    """Lists all players in the database for debugging purposes."""
    pool = get_db_connection()
    with pool.connect() as conn:
        players = conn.execute(sqlalchemy.text("SELECT player_id, email, name FROM players")).fetchall()
        print("--- Current Players in DB ---")
        if players:
            for player in players:
                print(f"ID: {player[0]}, Email: {player[1]}, Name: {player[2]}")
        else:
            print("No players found.")
        print("-----------------------------")

def change_password(player_id, old_password, new_password):
    """
    Changes a player's password securely by verifying the old one.
    Raises ValueError for invalid inputs or incorrect old password.
    """
    # Input validation
    if not old_password or not new_password:
        raise ValueError("Old and new passwords cannot be empty.")
    
    if len(new_password) < 8:
        raise ValueError("New password must be at least 8 characters long.")

    if old_password == new_password:
        raise ValueError("New password must be different from the old password.")

    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin() as trans:
            stored_hash = conn.execute(
                sqlalchemy.text("SELECT password_hash FROM players WHERE player_id = :id"),
                {"id": player_id}
            ).scalar_one_or_none()

            if not stored_hash or not check_password_hash(stored_hash, old_password):
                raise ValueError("Incorrect old password.")

            new_password_hash = generate_password_hash(new_password)

            conn.execute(
                sqlalchemy.text("UPDATE players SET password_hash = :hash WHERE player_id = :id"),
                {"hash": new_password_hash, "id": player_id}
            )
            logger.info(f"Successfully changed password for player ID {player_id}.")

def upgrade_player_subscription_with_code(player_id):
    """Upgrades a player's subscription to 'active' via a coupon code."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            conn.execute(
                sqlalchemy.text("UPDATE players SET subscription_status = 'active' WHERE player_id = :id"),
                {"id": player_id}
            )
            logger.info(f"Upgraded subscription for player {player_id} to 'active' via coupon code.")

def cancel_player_subscription(player_id):
    """Sets a player's subscription status to 'cancelled'."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            # We only cancel 'active' subscriptions.
            sql = sqlalchemy.text("UPDATE players SET subscription_status = 'cancelled' WHERE player_id = :id AND subscription_status = 'active'")
            result = conn.execute(sql, {"id": player_id})

            if result.rowcount == 0:
                # This could happen if the user is not subscribed or already cancelled.
                logger.warning(f"Attempted to cancel subscription for player {player_id}, but they were not active.")
            else:
                logger.info(f"Cancelled subscription for player {player_id}.")

def update_player_subscription_status(email, new_status, zaprite_id=None):
    """Updates a player's subscription status based on webhook data."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            if zaprite_id:
                sql = sqlalchemy.text("UPDATE players SET subscription_status = :status, zaprite_subscription_id = :zid WHERE email = :email")
                conn.execute(sql, {"status": new_status, "zid": zaprite_id, "email": email})
            else:
                sql = sqlalchemy.text("UPDATE players SET subscription_status = :status WHERE email = :email")
                conn.execute(sql, {"status": new_status, "email": email})
            logger.info(f"Updated subscription status for {email} to {new_status}.")

def update_player_timezone(player_id, new_timezone):
    """Updates a player's timezone."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            conn.execute(
                sqlalchemy.text("UPDATE players SET timezone = :timezone WHERE player_id = :id"),
                {"timezone": new_timezone, "id": player_id}
            )
            logger.info(f"Successfully updated timezone for player ID {player_id} to {new_timezone}.")



def update_player_name(player_id, new_name):
    """Updates a player's name."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            conn.execute(
                sqlalchemy.text("UPDATE players SET name = :name WHERE player_id = :id"),
                {"name": new_name, "id": player_id}
            )
            logger.info(f"Successfully updated name for player ID {player_id} to {new_name}.")

def update_player_socials(player_id, socials):
    """Updates a player's social links."""
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            # Only update fields that are provided
            for key, value in socials.items():
                # Sanitize key to prevent SQL injection, although parameterization helps.
                if key in ['x_url', 'tiktok_url', 'website_url']:
                    # Use f-string for the column name (safe here as we've whitelisted it)
                    # and parameterization for the value.
                    sql = sqlalchemy.text(f"UPDATE players SET {key} = :value WHERE player_id = :id")
                    conn.execute(sql, {"value": value, "id": player_id})
            logger.info(f"Updated social links for player {player_id}.")

def list_conversations(player_id):
    """Lists all conversations for a given player, most recent first."""
    pool = get_db_connection()
    with pool.connect() as conn:
        results = conn.execute(
            sqlalchemy.text("SELECT conversation_id, title, created_at, last_updated FROM coach_conversations WHERE player_id = :id ORDER BY created_at DESC"),
            {"id": player_id}
        ).mappings().fetchall()
        return [dict(row) for row in results]

def get_conversation_history(conversation_id):
    """Retrieves the history for a specific conversation."""
    pool = get_db_connection()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT history_json FROM coach_conversations WHERE conversation_id = :id"),
            {"id": conversation_id}
        ).scalar_one_or_none()
        return json.loads(result) if result else []

def get_last_conversation_time(player_id):
    """Retrieves the creation time of the most recent conversation for a player."""
    pool = get_db_connection()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT MAX(created_at) FROM coach_conversations WHERE player_id = :id"),
            {"id": player_id}
        ).scalar_one_or_none()
        
        # Ensure result is a datetime object
        if isinstance(result, str):
            try:
                # Attempt to parse as ISO format (common for DATETIME strings)
                return datetime.fromisoformat(result)
            except ValueError:
                # Fallback for other string formats if necessary, or log error
                logging.error(f"Could not parse datetime string: {result}")
                return None # Or raise an error, depending on desired behavior
        return result

def create_conversation(player_id, title, initial_history):
    """Creates a new conversation and returns its ID."""
    pool = get_db_connection()
    db_type = pool.dialect.name
    history_json = json.dumps(initial_history)
    with pool.connect() as conn:
        with conn.begin():
            insert_sql = sqlalchemy.text(
                "INSERT INTO coach_conversations (player_id, title, history_json) VALUES (:player_id, :title, :history_json)"
                + (" RETURNING conversation_id" if db_type == "postgresql" else "")
            )
            result = conn.execute(insert_sql, {"player_id": player_id, "title": title, "history_json": history_json})
            if db_type == "postgresql":
                return result.scalar()
            return result.lastrowid

def update_conversation_history(conversation_id, new_history):
    """Updates the history for an existing conversation."""
    pool = get_db_connection()
    history_json = json.dumps(new_history)
    with pool.connect() as conn:
        with conn.begin():
            conn.execute(
                sqlalchemy.text("UPDATE coach_conversations SET history_json = :history, last_updated = CURRENT_TIMESTAMP WHERE conversation_id = :id"),
                {"history": history_json, "id": conversation_id}
            )
