# Player Account Deletion: Soft Delete & Anonymization Instructions

This document outlines the steps to implement a "soft delete" and data anonymization strategy for player account deletion. This approach allows for the removal of Personally Identifiable Information (PII) while retaining non-PII data (e.g., game statistics) and preserving `player_id` integrity for historical or analytical purposes.

## 1. Database Schema Modifications

Modify the `players` table to include fields for soft deletion:

*   **`is_deleted`**: BOOLEAN, DEFAULT FALSE. Indicates if the account is logically deleted.
*   **`deleted_at`**: TIMESTAMP WITH TIME ZONE (PostgreSQL) or DATETIME (SQLite), NULLABLE. Records when the account was deleted.

**Example SQL (PostgreSQL):**
```sql
ALTER TABLE players
ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE,
ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE;
```

**Example SQL (SQLite - if needed, handle column existence):**
```sql
-- Add is_deleted
ALTER TABLE players ADD COLUMN is_deleted BOOLEAN DEFAULT FALSE;
-- Add deleted_at
ALTER TABLE players ADD COLUMN deleted_at DATETIME;
```

## 2. `data_manager.py` Modifications

### 2.1. Implement `delete_player_account(player_id)` function

Create a new function in `data_manager.py` to handle the soft deletion and anonymization process.

```python
from datetime import datetime, timezone
import uuid # For generating unique anonymous identifiers

def delete_player_account(player_id):
    """
    Soft deletes a player account and anonymizes their PII.
    Retains non-PII data for historical/analytical purposes.
    """
    pool = get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            # 1. Mark as deleted and set deletion timestamp
            conn.execute(
                sqlalchemy.text(
                    "UPDATE players SET is_deleted = TRUE, deleted_at = :deleted_at WHERE player_id = :player_id"
                ),
                {"deleted_at": datetime.now(timezone.utc), "player_id": player_id}
            )

            # 2. Anonymize PII in the players table
            # Generate a unique identifier for anonymized email/name
            anon_suffix = str(uuid.uuid4())[:8] # Use first 8 chars of a UUID
            anon_email = f"anon_{player_id}_{anon_suffix}@proofofputt.com"
            anon_name = f"Anonymous Player {player_id}"

            conn.execute(
                sqlalchemy.text(
                    "UPDATE players SET email = :anon_email, name = :anon_name, "
                    "password_hash = '', timezone = 'UTC', " # Clear password hash and reset timezone
                    "x_url = NULL, tiktok_url = NULL, website_url = NULL, "
                    "notification_preferences = NULL " # Clear social media and preferences
                    "WHERE player_id = :player_id"
                ),
                {
                    "anon_email": anon_email,
                    "anon_name": anon_name,
                    "player_id": player_id
                }
            )

            # 3. Consider anonymizing PII in other related tables if necessary
            # (e.g., if session data contains free-text fields with PII)
            # For this schema, most related tables only contain player_id and stats,
            # which are not PII themselves. Review carefully if new tables are added.

            logger.info(f"Player account {player_id} soft-deleted and anonymized.")

```

### 2.2. Modify existing data retrieval functions

Update functions that retrieve player data (e.g., `login_with_email_password`, `get_player_info`, `get_player_stats`, `get_sessions_for_player`, and any other functions that list or display players) to **exclude** soft-deleted players by default.

**Example: `login_with_email_password` modification:**

```python
def login_with_email_password(email, password):
    pool = get_db_connection()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT player_id, name, email, password_hash, timezone, subscription_status, is_deleted FROM players WHERE email = :email"),
            {"email": email}
        ).mappings().first()

        if result and not result['is_deleted'] and bcrypt.checkpw(password.encode('utf-8'), result['password_hash'].encode('utf-8')):
            # ... (rest of the function remains the same) ...
        
        return None, None, None, None, None, None, None
```

**Example: `get_player_info` modification (if it exists or is created):**

```python
def get_player_info(player_id):
    pool = get_db_connection()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT player_id, email, name, subscription_status, timezone, x_url, tiktok_url, website_url, notification_preferences FROM players WHERE player_id = :player_id AND is_deleted = FALSE"),
            {"player_id": player_id}
        ).mappings().first()
        if result:
            return dict(result)
        return None
```

**Example: `get_sessions_for_player` (no change needed as it queries `sessions` table, not `players` directly, but ensure `player_id` is valid and not deleted before calling this function from `api.py` if needed):**

No direct change needed in `get_sessions_for_player` itself, but any API endpoint calling it should first verify the player is not deleted.

## 3. `api.py` Modifications

### 3.1. Create a new API endpoint for player deletion

Add a new route (e.g., `/player/<int:player_id>/delete`) that calls the `data_manager.delete_player_account` function. This endpoint should be protected (e.g., only accessible by the player themselves or an admin).

```python
@app.route('/player/<int:player_id>/delete', methods=['POST'])
def delete_player(player_id):
    # Implement authentication/authorization here to ensure only the player or admin can delete
    # For example, check if current_user.player_id == player_id or current_user.is_admin
    try:
        data_manager.delete_player_account(player_id)
        return jsonify({"message": f"Player {player_id} account successfully deleted."}), 200
    except Exception as e:
        app.logger.error(f"Error deleting player {player_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred during account deletion."}), 500

```

## 4. Frontend Considerations

*   Update the frontend "Delete Account" functionality to call the new `/player/<int:player_id>/delete` API endpoint.
*   Ensure the frontend handles the response appropriately (e.g., logs the user out, redirects to a confirmation page).
*   Inform users about the implications of account deletion (what data is removed/anonymized, what is retained).

## 5. Testing

*   Test account deletion for existing users.
*   Verify that soft-deleted users cannot log in.
*   Verify that soft-deleted users' PII is anonymized in the database.
*   Verify that non-PII data (e.g., session stats) associated with soft-deleted users is still accessible for analytical purposes (if applicable, e.g., via admin tools or separate reports).
*   Ensure that soft-deleted users do not appear in public listings or search results.
