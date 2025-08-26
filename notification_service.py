import json
import logging
from datetime import datetime
import data_manager # Assuming data_manager.py is in the same directory
import sqlalchemy # Import sqlalchemy here

logger = logging.getLogger('debug_logger')

def create_in_app_notification(player_id, type, message, details=None, link_path=None, conn=None):
    """
    Creates an in-app notification record in the database.
    If a connection `conn` is provided, it will be used to execute the query,
    allowing this function to participate in an existing transaction.
    """
    insert_sql = sqlalchemy.text("""
        INSERT INTO notifications (player_id, type, message, details, link_path)
        VALUES (:player_id, :type, :message, :details, :link_path)
    """)
    params = {
        "player_id": player_id,
        "type": type,
        "message": message,
        "details": json.dumps(details) if details else None,
        "link_path": link_path
    }

    if conn:
        # Use the provided connection, assume transaction is managed by caller
        conn.execute(insert_sql, params)
        logger.info(f"Created in-app notification for player {player_id} within existing transaction.")
    else:
        # Create a new connection and transaction
        pool = data_manager.get_db_connection()
        with pool.connect() as new_conn:
            with new_conn.begin():
                new_conn.execute(insert_sql, params)
                logger.info(f"Created in-app notification for player {player_id}: {type} - {message}")

import os
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

def send_email_notification(player_id, type, message, details=None, template_name=None):
    """
    Sends an email notification using the SendGrid API.
    """
    sendgrid_api_key = os.environ.get("SENDGRID_API_KEY")
    from_email = os.environ.get("SENDGRID_FROM_EMAIL")
    to_email = details.get('player_email') # Assumes the player's email is in the details dict

    if not all([sendgrid_api_key, from_email, to_email]):
        logger.error("SendGrid API Key, From Email, or To Email is not configured. Cannot send email.")
        return

    # For now, we will send a simple text email. In a real app, you would use SendGrid templates.
    # The `template_name` argument is preserved for that future implementation.
    subject = f"Proof of Putt Notification: {type.replace('_', ' ').title()}"
    
    # Create a more readable HTML content from the message and details
    html_content = f"""
    <h3>{message}</h3>
    <p>Details:</p>
    <ul>
    """
    if details:
        for key, value in details.items():
            # Avoid printing sensitive info like the email itself in the body
            if key != 'player_email':
                html_content += f"<li><strong>{key.replace('_', ' ').title()}:</strong> {value}</li>"
    html_content += "</ul><p>Thank you,<br>The Proof of Putt Team</p>" 

    message = Mail(
        from_email=from_email,
        to_emails=to_email,
        subject=subject,
        html_content=html_content
    )

    try:
        sg = SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        logger.info(f"Email sent to {to_email}. Status code: {response.status_code}")
    except Exception as e:
        logger.error(f"Error sending email via SendGrid: {e}")

# Helper functions for notification management (will be called by API endpoints)
def get_player_notifications(player_id, limit=20, offset=0, status='all'):
    pool = data_manager.get_db_connection()
    with pool.connect() as conn:
        query = sqlalchemy.text("""
            SELECT id, player_id, type, message, details, read_status, created_at, link_path
            FROM notifications
            WHERE player_id = :player_id
        """)
        params = {"player_id": player_id}

        if status == 'unread':
            query = sqlalchemy.text(query.text + " AND read_status = FALSE")
        elif status == 'read':
            query = sqlalchemy.text(query.text + " AND read_status = TRUE")
        
        query = sqlalchemy.text(query.text + " ORDER BY created_at DESC LIMIT :limit OFFSET :offset")
        params["limit"] = limit
        params["offset"] = offset

        results = conn.execute(query, params).mappings().fetchall()
        
        # Deserialize details JSON
        notifications = []
        for row in results:
            notification_dict = dict(row)
            if notification_dict['details']:
                notification_dict['details'] = json.loads(notification_dict['details'])
            notifications.append(notification_dict)
        return notifications

def get_unread_notifications_count(player_id):
    pool = data_manager.get_db_connection()
    with pool.connect() as conn:
        result = conn.execute(
            sqlalchemy.text("SELECT COUNT(*) FROM notifications WHERE player_id = :player_id AND read_status = FALSE"),
            {"player_id": player_id}
        ).scalar_one()
        return result

def mark_notification_as_read(notification_id, player_id):
    pool = data_manager.get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            update_sql = sqlalchemy.text("""
                UPDATE notifications SET read_status = TRUE
                WHERE id = :notification_id AND player_id = :player_id
            """)
            result = conn.execute(update_sql, {"notification_id": notification_id, "player_id": player_id})
            return result.rowcount > 0

def mark_all_notifications_as_read(player_id):
    pool = data_manager.get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            update_sql = sqlalchemy.text("""
                UPDATE notifications SET read_status = TRUE
                WHERE player_id = :player_id AND read_status = FALSE
            """)
            result = conn.execute(update_sql, {"player_id": player_id})
            return result.rowcount

def delete_notification(notification_id, player_id):
    pool = data_manager.get_db_connection()
    with pool.connect() as conn:
        with conn.begin():
            delete_sql = sqlalchemy.text("""
                DELETE FROM notifications
                WHERE id = :notification_id AND player_id = :player_id
            """)
            result = conn.execute(delete_sql, {"notification_id": notification_id, "player_id": player_id})
            return result.rowcount > 0
