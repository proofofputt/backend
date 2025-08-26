import os # Added a comment to trigger redeployment
from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import subprocess
import sys
from dotenv import load_dotenv
import logging
from datetime import datetime, timedelta, timezone
import threading
from google.api_core import exceptions as google_exceptions
import tenacity
from functools import wraps
import google.generativeai as genai

# Load environment variables from a .env file at the project root.
load_dotenv()

import data_manager
import notification_service # Import the new notification service
from utils import get_camera_index_from_config

# Configure the Gemini API client
try:
    genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
except Exception as e:
    logging.warning(f"Could not configure Gemini API. AI Coach will be disabled. Error: {e}")

app = Flask(__name__)
CORS(app)

# Initialize database and create default user once when the app starts
with app.app_context():
    data_manager.initialize_database()

@app.errorhandler(ValueError)
def handle_value_error(e):
    return jsonify({"error": str(e)}), 400

@app.errorhandler(Exception)
def handle_generic_exception(e):
    app.logger.error(f"An unexpected server error occurred: {e}", exc_info=True)
    return jsonify({"error": "An unexpected server error occurred."}), 500

@app.route('/favicon.ico')
def favicon():
    return '', 204

def subscription_required(f):
    """A decorator to protect routes that require a subscription."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        player_id = None
        # Extract player_id from route, body, or query args
        if 'player_id' in kwargs:
            player_id = kwargs['player_id']
        elif request.is_json:
            data = request.get_json()
            player_id = data.get('player_id') or data.get('creator_id')
        elif request.method == 'GET':
            player_id = request.args.get('player_id', type=int)

        if not player_id:
            return jsonify({"error": "Player identification is required for this feature."} ), 400

        player_info = data_manager.get_player_info(player_id)
        if not player_info or player_info.get('subscription_status') != 'active':
            return jsonify({"error": "This feature requires a full subscription."} ), 403
        return f(*args, **kwargs)
    return decorated_function

def _create_daily_ai_chat_if_needed(player_id):
    """
    Checks if a daily AI chat should be created for a subscribed player and creates it.
    This is intended to be run asynchronously (e.g., in a thread) to not block API responses.
    """
    with app.app_context():
        # Check subscription status
        player_info = data_manager.get_player_info(player_id)
        if not player_info or player_info.get('subscription_status') != 'active':
            return

        # Check daily limit - has a conversation been created in the last 24 hours?
        last_convo_time = data_manager.get_last_conversation_time(player_id)
        if last_convo_time and (datetime.now(timezone.utc) - last_convo_time.replace(tzinfo=timezone.utc) < timedelta(days=1)):
            return

        # Check for data to analyze - don't create a chat if there's nothing to talk about.
        stats = data_manager.get_career_stats(player_id)
        sessions = data_manager.get_sessions_for_player(player_id)
        if not stats or not sessions:
            app.logger.info(f"Skipping daily AI chat for player {player_id}: no stats or sessions.")
            return

        # All checks passed, create the conversation
        try:
            model = genai.GenerativeModel('gemini-1.5-flash-latest')
            recent_sessions = sessions[:2]
            player_name = player_info.get('name', f'Player {player_id}')
            
            initial_prompt = f'''As a PhD-level putting coach, provide a comprehensive initial analysis for {player_name}.
Please ensure the response is well-formatted for readability, using line breaks and bullet points as specified.

1.  **Career Skills Evaluation:** Based on these career stats, highlight one key accomplishment and provide one specific, actionable recommendation for improvement. Career Stats: {json.dumps(stats, indent=2)}
2.  **Recent Performance Summary:** Compare their two most recent sessions. Focus on changes in makes, misses, and makes per minute to identify short-term trends. Recent Sessions: {json.dumps(recent_sessions, indent=2)}
3.  **Putting Trends Analysis:** Analyze the 'classification' data within the sessions to identify any patterns (e.g., 'MISS - RETURN: Entry RAMP_ROI - Exit RAMP_ROI'). Provide an insight based on this data.

Keep the entire response concise and encouraging.'''
            initial_response = _generate_content_with_retry(model, initial_prompt)
            title_prompt = f"Create a very short, descriptive title (5 words or less) for a conversation that starts with this analysis: {initial_response.text}"
            title_response = _generate_content_with_retry(model, title_prompt)
            title = title_response.text.strip().replace('"', '') if title_response and title_response.text else "AI Coach Analysis"
            initial_history = [{'role': 'model', 'parts': [initial_response.text]}]
            new_conversation_id = data_manager.create_conversation(player_id, title, initial_history)

            notification_service.create_in_app_notification(player_id, 'AI_COACH_INSIGHT', 'Your AI Coach has a new insight for you!', {'conversation_id': new_conversation_id, 'title': title}, f'/coach/{new_conversation_id}')
            app.logger.info(f"Created daily AI chat {new_conversation_id} for player {player_id}.")
        except Exception as e:
            app.logger.error(f"Failed to auto-create daily AI chat for player {player_id}: {e}", exc_info=True)

# --- Auth & Player Routes ---
@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').strip()
    password = data['password']
    if not email or not password:
        return jsonify({"error": "Invalid credentials"}), 401
    try:
        player_id, player_name, player_email, stats, sessions, timezone, subscription_status = data_manager.login_with_email_password(email, password)
        if player_id is not None:
            # Asynchronously trigger the daily AI chat creation check
            thread = threading.Thread(target=_create_daily_ai_chat_if_needed, args=(player_id,))
            thread.start()

            return jsonify({
                "player_id": player_id, 
                "name": player_name,
                "email": player_email,
                "stats": stats,
                "sessions": sessions,
                "timezone": timezone,
                "subscription_status": subscription_status,
                "is_new_user": False
            }), 200
        else:
            return jsonify({"error": "Invalid credentials"}), 401
    except Exception as e:
        app.logger.error(f"Login failed: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred during login."} ), 500

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get('email', '').strip()
    password = data['password']
    name = data['name'].strip()
    if not email or not password or not name:
        return jsonify({"error": "Email, password, and name cannot be empty"}), 400
    try:
        player_id, player_name = data_manager.register_player(email, password, name)
        # After registering, log them in to get the full data object
        player_id, player_name, player_email, stats, sessions, timezone, subscription_status = data_manager.login_with_email_password(email, password)
        if player_id is not None:
            
            return jsonify({
                "player_id": player_id,
                "name": player_name,
                "email": player_email,
                "stats": stats,
                "sessions": sessions,
                "timezone": timezone,
                "subscription_status": subscription_status,
                "is_new_user": True
            }), 201
        else:
            return jsonify({"error": "Registration successful, but failed to log in automatically."} ), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        app.logger.error(f"Registration failed: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred during registration."} ), 500

@app.route('/player/<int:player_id>/data', methods=['GET'])
def get_player_data(player_id):
    try:
        viewer_id = request.args.get('viewer_id', type=int)
        player_info = data_manager.get_player_info(player_id, viewer_id=viewer_id)
        if not player_info:
            return jsonify({"error": "Player not found"}), 404
        
        stats = data_manager.get_player_stats(player_id)
        # For the dashboard, we only need a small number of recent sessions.
        sessions = data_manager.get_sessions_for_player(player_id, limit=25)
        
        # Asynchronously trigger the daily AI chat creation check on data refresh
        thread = threading.Thread(target=_create_daily_ai_chat_if_needed, args=(player_id,))
        thread.start()

        # The get_player_info function now returns a dictionary, so we can pass it directly
        response_data = {
            "player_id": player_id,
            "stats": stats,
            "sessions": sessions
        }
        response_data.update(player_info)

        return jsonify(response_data), 200
    except Exception as e:
        app.logger.error(f"Failed to refresh data for player {player_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve player data"}), 500

@app.route('/player/<int:player_id>/career-stats', methods=['GET'])
#@subscription_required # Decorator removed to allow page access
def get_career_stats_api(player_id):
    """
    Gets career stats. The subscription status is checked here and passed
    to the frontend, which will handle blurring the data for non-subscribers.
    """
    player_info = data_manager.get_player_info(player_id)
    if not player_info:
        return jsonify({"error": "Player not found."} ), 404
    
    is_subscribed = player_info.get('subscription_status') == 'active'

    stats = data_manager.get_career_stats(player_id)
    if stats is None:
        return jsonify({"error": "Could not calculate stats for this player."} ), 404
    
    stats['is_subscribed'] = is_subscribed
    return jsonify(stats), 200

@app.route('/players/search', methods=['GET'])
def search_players_api():
    search_term = request.args.get('search_term', '').strip()
    if not search_term:
        return jsonify([]), 200
    players = data_manager.search_players_by_name(search_term)
    return jsonify(players), 200

@app.route('/player/<int:player_id>/socials', methods=['PUT'])
def update_player_socials_api(player_id):
    """Updates a player's social links."""
    data = request.get_json()
    # Basic validation to ensure we have a dictionary
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid data format. Expected a JSON object."} ), 400
    
    # Filter for allowed keys to prevent unwanted updates
    allowed_keys = {'x_url', 'tiktok_url', 'website_url'}
    socials_to_update = {k: v for k, v in data.items() if k in allowed_keys}

    if not socials_to_update:
        return jsonify({"error": "No valid social link fields provided."} ), 400

    try:
        data_manager.update_player_socials(player_id, socials_to_update)
        return jsonify({"message": "Social links updated successfully."} ), 200
    except Exception as e:
        app.logger.error(f"Failed to update social links for player {player_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/player/<int:player_id>/name', methods=['PUT'])
def update_player_name_api(player_id):
    """Updates a player's name."""
    data = request.get_json()
    new_name = data.get('name', '').strip()
    if not new_name:
        return jsonify({"error": "Name cannot be empty."} ), 400
    try:
        data_manager.update_player_name(player_id, new_name)
        return jsonify({"message": "Name updated successfully."} ), 200
    except Exception as e:
        app.logger.error(f"Failed to update name for player {player_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/player/<int:player_id>/timezone', methods=['PUT'])
def update_player_timezone_api(player_id):
    """Updates a player's timezone."""
    data = request.get_json()
    new_timezone = data.get('timezone', '').strip()
    if not new_timezone:
        return jsonify({"error": "Timezone cannot be empty."} ), 400
    try:
        data_manager.update_player_timezone(player_id, new_timezone)
        return jsonify({"message": "Timezone updated successfully."} ), 200
    except Exception as e:
        app.logger.error(f"Failed to update timezone for player {player_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/player/<int:player_id>/password', methods=['PUT'])
def change_password_api(player_id):
    """Changes a player's password."""
    data = request.get_json()
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    try:
        data_manager.change_password(player_id, old_password, new_password)
        
        # --- Notification Logic ---
        player_info = data_manager.get_player_info(player_id)
        if player_info:
            player_name = player_info.get('name', f'Player {player_id}')
            player_email = player_info.get('email')
            timestamp = datetime.now().isoformat()
            ip_address = request.remote_addr

            # In-App Notification
            notification_service.create_in_app_notification(
                player_id, 
                'PASSWORD_CHANGED', 
                'Your password has been changed.', 
                {'timestamp': timestamp, 'ip_address': ip_address}, 
                '/settings'
            )
            
            # Email Notification
            notification_service.send_email_notification(
                player_id, 
                'PASSWORD_CHANGED', 
                'Your password has been changed.', 
                {'player_name': player_name, 'timestamp': timestamp, 'ip_address': ip_address, 'player_email': player_email}, 
                'password_changed_template'
            )

        return jsonify({"message": "Password changed successfully."} ), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route('/player/<int:player_id>/notification-preferences', methods=['PUT'])
def update_notification_preferences_api(player_id):
    """Updates a player's notification preferences."""
    data = request.get_json()
    if not isinstance(data, dict):
        return jsonify({"error": "Invalid data format. Expected a JSON object."} ), 400
    try:
        data_manager.update_player_notification_preferences(player_id, data)
        return jsonify({"message": "Notification preferences updated successfully."} ), 200
    except Exception as e:
        app.logger.error(f"Failed to update notification preferences for player {player_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/player/<int:player_id>/subscription/cancel', methods=['POST'])
def cancel_subscription_api(player_id):
    """
    Cancels a player's active subscription.
    In a real-world scenario, this would also trigger an API call to the
    payment provider (e.g., Zaprite) to cancel the recurring payment.
    """
    try:
        data_manager.cancel_player_subscription(player_id)
        return jsonify({"message": "Subscription cancelled successfully."} ), 200
    except Exception as e:
        app.logger.error(f"Failed to cancel subscription for player {player_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/player/<int:player_id>/redeem-coupon', methods=['POST'])
def redeem_coupon_api(player_id):
    """Redeems a coupon code to upgrade a subscription."""
    data = request.get_json()
    coupon_code = data.get('coupon_code')

    if not coupon_code:
        return jsonify({"error": "Coupon code is required."} ), 400

    # For this implementation, we hardcode the special beta tester code.
    if coupon_code.upper() == 'EARLY':
        try:
            data_manager.upgrade_player_subscription_with_code(player_id)

            # --- Notification Logic ---
            player_info = data_manager.get_player_info(player_id)
            if player_info:
                player_name = player_info.get('name', f'Player {player_id}')
                player_email = player_info.get('email')

                # In-App Notification
                notification_service.create_in_app_notification(
                    player_id, 
                    'SUBSCRIPTION_UPGRADED', 
                    'Your subscription has been upgraded!', 
                    {'status': 'active'}, 
                    '/upgrade'
                )
                
                # Email Notification
                notification_service.send_email_notification(
                    player_id, 
                    'SUBSCRIPTION_UPGRADED', 
                    'Your subscription has been upgraded!', 
                    {'player_name': player_name, 'status': 'active', 'player_email': player_email}, 
                    'subscription_upgraded_template'
                )

            return jsonify({"message": "Subscription upgraded successfully."} ), 200
        except Exception as e:
            app.logger.error(f"Failed to upgrade subscription for player {player_id}: {e}", exc_info=True)
            return jsonify({"error": "An internal error occurred during upgrade."} ), 500
    else:
        return jsonify({"error": "Invalid coupon code."} ), 400

@app.route('/player/<int:player_id>/sessions', methods=['GET'])
def get_player_sessions_paginated_api(player_id):
    """Gets a paginated list of a player's sessions."""
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 25, type=int)
        offset = (page - 1) * limit

        sessions = data_manager.get_sessions_for_player(player_id, limit=limit, offset=offset)
        total_sessions = data_manager.get_sessions_count_for_player(player_id)
        total_pages = (total_sessions + limit - 1) // limit

        return jsonify({
            "sessions": sessions,
            "total_pages": total_pages,
            "current_page": page
        }), 200
    except Exception as e:
        app.logger.error(f"Failed to get paginated sessions for player {player_id}: {e}", exc_info=True)
        return jsonify({"error": "Failed to retrieve session history."} ), 500

# --- Session and Calibration Routes ---
@app.route('/start-session', methods=['POST'])
def start_session():
    data = request.get_json()
    player_id = data['player_id']
    duel_id = data.get('duel_id')
    league_round_id = data.get('league_round_id')
    camera_index = get_camera_index_from_config(player_id)
    python_executable = sys.executable
    script_path = os.path.join(os.path.dirname(__file__), 'run_tracker.py')
    session_id = data_manager.create_session(player_id)
    calibration_config_path = os.path.join(os.path.dirname(__file__), f"calibration_output_{player_id}.json")
    
    command = [python_executable, script_path, '--player_id', str(player_id), '--session_id', str(session_id), '--camera_index', str(camera_index), '--config', calibration_config_path]
    
    time_limit_seconds = None

    if duel_id:
        command.extend(['--duel_id', str(duel_id)])
        duel_details = data_manager.get_duel_details(duel_id)
        if duel_details and duel_details.get('session_duration_limit_minutes'):
            time_limit_seconds = duel_details['session_duration_limit_minutes'] * 60
        else:
            app.logger.warning(f"Could not determine time limit for duel {duel_id}.")
    
    if league_round_id:
        command.extend(['--league_round_id', str(league_round_id)])
        # Fetch league round details to get the session duration limit
        league_round_details = data_manager.get_league_round_details(league_round_id)
        if league_round_details and league_round_details.get('session_duration_limit_minutes'):
            time_limit_seconds = league_round_details['session_duration_limit_minutes'] * 60
        else:
            app.logger.warning(f"Could not determine time limit for league round {league_round_id}.")

    if time_limit_seconds:
        command.extend(['--time_limit_seconds', str(int(time_limit_seconds))])

    subprocess.Popen(command)
    return jsonify({"message": f"Session started for player {player_id}."}), 202

@app.route('/start-calibration', methods=['POST'])
def start_calibration():
    data = request.get_json()
    player_id = data['player_id']
    camera_index = get_camera_index_from_config(player_id)
    python_executable = sys.executable
    script_path = os.path.join(os.path.dirname(__file__), 'calibration.py')
    subprocess.Popen([python_executable, script_path, '--camera_index', str(camera_index), '--player_id', str(player_id)])
    return jsonify({"message": "Calibration process started."} ), 202

# --- Leaderboard Routes ---
@app.route('/leaderboard', methods=['GET'])
def get_leaderboard():
    sort_by = request.args.get('sort_by', 'makes')
    leaderboard_data = data_manager.get_leaderboard(sort_by)
    return jsonify(leaderboard_data), 200

@app.route('/leaderboard/sessions', methods=['GET'])
def get_session_leaderboards_api():
    leaderboard_data = data_manager.get_session_leaderboards()
    return jsonify(leaderboard_data), 200

# --- Duels Routes ---
@app.route('/duels', methods=['POST'])
@subscription_required
def create_duel_api():
    """Creates a new duel."""
    data = request.get_json()
    creator_id = data.get('creator_id')
    invited_player_identifier = data.get('invited_player_identifier')
    invitation_expiry_minutes = data.get('invitation_expiry_minutes')
    session_duration_limit_minutes = data.get('session_duration_limit_minutes')

    if not all([creator_id, invited_player_identifier, invitation_expiry_minutes, session_duration_limit_minutes]):
        return jsonify({"error": "creator_id, invited_player_identifier, invitation_expiry_minutes, and session_duration_limit_minutes are required."} ), 400
    
    try:
        duel_id = data_manager.create_duel(creator_id, invited_player_identifier, invitation_expiry_minutes, session_duration_limit_minutes)
        
        # Fetch player names for notification
        creator_info = data_manager.get_player_info(creator_id)
        invited_player_info = data_manager.get_player_info(invited_player_id)
        creator_name = creator_info.get('name', f'Player {creator_id}')
        invited_player_name = invited_player_info.get('name', f'Player {invited_player_id}')

        # Notify invited player
        notification_service.create_in_app_notification(invited_player_id, 'DUEL_CHALLENGE', f'You\'ve been challenged by {creator_name}!', {'challenger_name': creator_name, 'duel_id': duel_id}, '/duels')
        notification_service.send_email_notification(invited_player_id, 'DUEL_CHALLENGE', f'You\'ve been challenged by {creator_name}!', {'challenger_name': creator_name, 'duel_id': duel_id, 'player_email': invited_player_info.get('email')}, 'duel_challenge_template')

        return jsonify({"message": "Duel created successfully.", "duel_id": duel_id}), 201
    except Exception as e:
        app.logger.error(f"Failed to create duel: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/duels/list/<int:player_id>', methods=['GET'])
def list_duels_api(player_id):
    duels = data_manager.get_duels_for_player(player_id)
    return jsonify(duels), 200

@app.route('/duels/<int:duel_id>/accept', methods=['POST'])
def accept_duel_api(duel_id):
    """Accepts a duel invitation. Accessible by non-subscribers."""
    try:
        # We need to verify that the player accepting is the invited player.
        data = request.get_json()
        player_id = data.get('player_id')
        if not player_id:
            return jsonify({"error": "Player ID is required to accept a duel."} ), 400

        duel = data_manager.get_duel_details(duel_id)
        if not duel:
            return jsonify({"error": "Duel not found."} ), 404
        if duel.get('invited_player_id') != player_id:
            return jsonify({"error": "You are not authorized to accept this duel."} ), 403
        if duel.get('status') != 'pending':
            return jsonify({"error": "This duel is no longer pending."} ), 400

        data_manager.accept_duel(duel_id, player_id)
        
        # Notify the creator that the duel was accepted
        creator_id = duel['creator_id']
        invited_player_info = data_manager.get_player_info(player_id)
        invited_player_name = invited_player_info.get('name', f'Player {player_id}')
        notification_service.create_in_app_notification(creator_id, 'DUEL_ACCEPTED', f'{invited_player_name} has accepted your duel!', {'opponent_name': invited_player_name, 'duel_id': duel_id}, '/duels')

        updated_duels = data_manager.get_duels_for_player(player_id)
        return jsonify(updated_duels), 200
    except Exception as e:
        app.logger.error(f"Failed to accept duel {duel_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/duels/<int:duel_id>/reject', methods=['POST'])
def reject_duel_api(duel_id):
    """Rejects a duel invitation. Accessible by non-subscribers."""
    try:
        data = request.get_json()
        player_id = data.get('player_id')
        if not player_id:
            return jsonify({"error": "Player ID is required to reject a duel."} ), 400

        duel = data_manager.get_duel_details(duel_id)
        if not duel:
            return jsonify({"error": "Duel not found."} ), 404
        if duel.get('invited_player_id') != player_id:
            return jsonify({"error": "You are not authorized to reject this duel."} ), 403

        data_manager.reject_duel(duel_id)
        
        # Notify the creator that the duel was rejected
        creator_id = duel['creator_id']
        invited_player_info = data_manager.get_player_info(player_id)
        invited_player_name = invited_player_info.get('name', f'Player {player_id}')
        notification_service.create_in_app_notification(creator_id, 'DUEL_REJECTED', f'{invited_player_name} has declined your duel.', {'opponent_name': invited_player_name, 'duel_id': duel_id}, '/duels')

        updated_duels = data_manager.get_duels_for_player(player_id)
        return jsonify(updated_duels), 200
    except Exception as e:
        app.logger.error(f"Failed to reject duel {duel_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/duels/<int:duel_id>/submit-session', methods=['POST'])
def submit_duel_session_api(duel_id):
    """Receives a completed session from the tracker and submits it to a duel."""
    data = request.get_json()
    required_fields = ['session_id', 'player_id', 'score', 'duration']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields for duel session submission."} ), 400

    try:
        data_manager.submit_duel_session(
            duel_id=duel_id,
            session_id=data['session_id'],
            player_id=data['player_id'],
            score=data['score'],
            duration=data['duration']
        )
        return jsonify({"message": "Duel session submitted successfully."} ), 200
    except Exception as e:
        app.logger.error(f"Failed to submit session to duel {duel_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

# --- Leagues Routes ---
@app.route('/leagues', methods=['GET'])
def list_leagues_api():
    player_id = request.args.get('player_id', type=int)
    if not player_id:
        return jsonify({"error": "Missing player_id query parameter."} ), 400
    leagues = data_manager.get_leagues_for_player(player_id)
    return jsonify(leagues), 200

@app.route('/leagues', methods=['POST'])
@subscription_required
def create_league_api():
    """Creates a new league."""
    data = request.get_json()
    required_fields = ['creator_id', 'name', 'privacy_type', 'settings']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields for league creation."} ), 400
    
    try:
        league_id = data_manager.create_league(
            name=data['name'],
            description=data.get('description', ''),
            creator_id=data['creator_id'],
            privacy_type=data['privacy_type'],
            settings=data['settings']
        )
        return jsonify({"message": "League created successfully.", "league_id": league_id}), 201
    except Exception as e:
        app.logger.error(f"Failed to create league: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/leagues/<int:league_id>', methods=['GET'])
def get_league_details_api(league_id):
    details = data_manager.get_league_details(league_id)
    if not details:
        return jsonify({"error": "League not found."} ), 404
    return jsonify(details), 200

@app.route('/leagues/<int:league_id>', methods=['DELETE'])
def delete_league_api(league_id):
    """Deletes a league."""
    # For DELETE requests, it's common to pass the user's ID in the body
    # to confirm their identity and authorization.
    data = request.get_json()
    player_id = data.get('player_id')
    if not player_id:
        return jsonify({"error": "player_id is required."} ), 400

    try:
        data_manager.delete_league(league_id, player_id)
        return jsonify({"message": "League deleted successfully."} ), 200
    except ValueError as e:
        # Check for specific error messages to return appropriate status codes
        if "not found" in str(e).lower():
            return jsonify({"error": str(e)}), 404
        # Permission denied
        return jsonify({"error": str(e)}), 403

@app.route('/leagues/<int:league_id>/join', methods=['POST'])
def join_league_api(league_id):
    """Allows a player to join a public league."""
    data = request.get_json()
    player_id = data.get('player_id')
    if not player_id:
        return jsonify({"error": "player_id is required."} ), 400
    try:
        data_manager.join_league(league_id, player_id)
        return jsonify({"message": "Successfully joined league."} ), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route('/leagues/invites/<int:league_id>/respond', methods=['POST'])
def respond_to_league_invite_api(league_id):
    """Allows a player to accept or decline a league invitation."""
    data = request.get_json()
    player_id = data.get('player_id')
    action = data.get('action')
    if not player_id or not action:
        return jsonify({"error": "player_id and action are required."} ), 400
    try:
        data_manager.respond_to_league_invite(league_id, player_id, action)
        return jsonify({"message": f"Invitation {action}ed successfully."} ), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route('/leagues/<int:league_id>/invite', methods=['POST'])
def invite_to_league_api(league_id):
    """Invites a player to a league."""
    data = request.get_json()
    inviter_id = data.get('inviter_id')
    invitee_identifier = data.get('invitee_identifier')

    if not inviter_id or not invitee_identifier:
        return jsonify({"error": "inviter_id and invitee_identifier are required."} ), 400

    try:
        data_manager.invite_to_league(league_id, inviter_id, invitee_identifier)
        
        # Fetch player names for notification
        inviter_info = data_manager.get_player_info(inviter_id)
        invitee_info = data_manager.get_player_info(invitee_id)
        league_details = data_manager.get_league_details(league_id)

        inviter_name = inviter_info.get('name', f'Player {inviter_id}')
        invitee_email = invitee_info.get('email', 'unknown')
        league_name = league_details.get('name', 'a league')

        notification_service.create_in_app_notification(invitee_id, 'LEAGUE_INVITE', f'{inviter_name} has invited you to join {league_name}!', {'inviter_name': inviter_name, 'league_name': league_name, 'league_id': league_id}, '/leagues')
        notification_service.send_email_notification(invitee_id, 'LEAGUE_INVITE', f'{inviter_name} has invited you to join {league_name}!', {'inviter_name': inviter_name, 'league_name': league_name, 'league_id': league_id, 'player_email': invitee_email}, 'league_invite_template')

        return jsonify({"message": "Invitation sent successfully."} ), 200
    except ValueError as e:
        # This will catch permission errors, player already invited, etc.
        return jsonify({"error": str(e)}), 400

# --- Follower Routes ---
@app.route('/players/<int:followed_id>/follow', methods=['POST'])
def follow_player_api(followed_id):
    data = request.get_json()
    follower_id = data.get('follower_id')
    if not follower_id:
        return jsonify({"error": "follower_id is required."} ), 400
    try:
        data_manager.follow_player(follower_id, followed_id)
        return jsonify({"message": f"You are now following player {followed_id}."} ), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@app.route('/players/<int:followed_id>/unfollow', methods=['POST'])
def unfollow_player_api(followed_id):
    data = request.get_json()
    follower_id = data.get('follower_id')
    if not follower_id:
        return jsonify({"error": "follower_id is required."} ), 400
    data_manager.unfollow_player(follower_id, followed_id)
    return jsonify({"message": f"You have unfollowed player {followed_id}."} ), 200

@app.route('/players/<int:player_id>/followers', methods=['GET'])
def get_followers_api(player_id):
    followers = data_manager.get_followers(player_id)
    return jsonify(followers), 200

@app.route('/players/<int:player_id>/following', methods=['GET'])
def get_following_api(player_id):
    following = data_manager.get_following(player_id)
    return jsonify(following), 200

@app.route('/leagues/<int:league_id>/remove-member', methods=['POST'])
@subscription_required
def remove_league_member_api(league_id):
    """Removes a member from a league. Only accessible by the league creator."""
    data = request.get_json()
    admin_id = data.get('admin_id')
    member_to_remove_id = data.get('member_to_remove_id')

    if not admin_id or not member_to_remove_id:
        return jsonify({"error": "admin_id and member_to_remove_id are required."} ), 400

    try:
        # Get league name before removing the member, for the notification
        league_details = data_manager.get_league_details(league_id)
        if not league_details:
            return jsonify({"error": "League not found."} ), 404
        league_name = league_details.get('name', 'a league')

        data_manager.remove_league_member(league_id, admin_id, member_to_remove_id)

        # --- Notification Logic ---
        notification_service.create_in_app_notification(
            member_to_remove_id,
            'LEAGUE_REMOVED',
            f"You have been removed from {league_name} by an administrator.",
            {'league_name': league_name, 'league_id': league_id}
        )

        return jsonify({"message": "Member removed successfully."} ), 200
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:
        app.logger.error(f"Failed to remove member from league {league_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/zaprite-webhook', methods=['POST'])
def zaprite_webhook():
    """Handles incoming webhooks from Zaprite to update subscription status."""
    # In a production environment, you MUST verify the webhook signature.
    payload = request.get_json()
    event_type = payload.get('type')
    data = payload.get('data', {}).get('object', {})
    customer_email = data.get('customer', {}).get('email')

    if not customer_email:
        return jsonify({"status": "ignored", "reason": "No customer email provided."} ), 200

    # Get player_id from email. This is crucial for linking the webhook to our system.
    player_id = data_manager.get_player_by_name(customer_email)
    if not player_id:
        app.logger.warning(f"Received webhook for unknown email: {customer_email}")
        return jsonify({"status": "ignored", "reason": "Player not found for the provided email."} ), 200
    
    player_info = data_manager.get_player_info(player_id)
    player_name = player_info.get('name', f'Player {player_id}')

    if event_type in ['subscription.created', 'subscription.updated']:
        subscription_status = data.get('status')
        zaprite_subscription_id = data.get('id')
        if subscription_status:
            data_manager.update_player_subscription_status(customer_email, subscription_status, zaprite_subscription_id)
            app.logger.info(f"Processed '{event_type}' for {customer_email}. New status: {subscription_status}")

    elif event_type == 'subscription.canceled':
        effective_date = data.get('cancel_at_period_end')
        # This is primarily an email notification as the user may not log in again.
        notification_service.send_email_notification(
            player_id, 
            'SUBSCRIPTION_CANCELED', 
            'Your subscription has been canceled.', 
            {'player_name': player_name, 'effective_date': effective_date, 'player_email': customer_email}, 
            'subscription_canceled_template'
        )
        app.logger.info(f"Processed 'subscription.canceled' for {customer_email}.")

    elif event_type == 'subscription.past_due':
        # In-App Notification
        notification_service.create_in_app_notification(
            player_id, 
            'PAYMENT_FAILED', 
            'Your subscription payment failed.', 
            {'reason': 'past_due'}, 
            '/upgrade'
        )
        # Email Notification
        notification_service.send_email_notification(
            player_id, 
            'PAYMENT_FAILED', 
            'Your subscription payment failed.', 
            {'player_name': player_name, 'reason': 'past_due', 'player_email': customer_email}, 
            'payment_failed_template'
        )
        app.logger.info(f"Processed 'subscription.past_due' for {customer_email}.")

    return jsonify({"status": "received"}), 200


# --- Fundraising Routes ---
@app.route('/fundraisers', methods=['POST'])
@subscription_required
def create_fundraiser_api():
    """Creates a new fundraiser."""
    data = request.get_json()
    # Basic validation
    required_fields = ['player_id', 'name', 'cause', 'goal_amount', 'start_time', 'end_time']
    if not all(field in data for field in required_fields):
        return jsonify({"error": "Missing required fields."} ), 400

    try:
        fundraiser_id = data_manager.create_fundraiser(
            player_id=data['player_id'], name=data['name'], cause=data['cause'],
            description=data.get('description', ''), goal_amount=data['goal_amount'],
            start_time=data['start_time'], end_time=data['end_time']
        )
        
        # --- Notification Logic ---
        notification_service.create_in_app_notification(
            data['player_id'],
            'FUNDRAISER_CREATED',
            f"Your fundraiser '{data['name']}' is live!",
            {'fundraiser_name': data['name'], 'fundraiser_id': fundraiser_id},
            f"/fundraisers/{fundraiser_id}"
        )

        return jsonify({"message": "Fundraiser created successfully.", "fundraiser_id": fundraiser_id}), 201
    except Exception as e:
        app.logger.error(f"Failed to create fundraiser: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/fundraisers', methods=['GET'])
def list_fundraisers_api():
    """Lists all fundraisers."""
    try:
        fundraisers = data_manager.get_all_fundraisers()
        return jsonify(fundraisers), 200
    except Exception as e:
        app.logger.error(f"Failed to list fundraisers: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/fundraisers/<int:fundraiser_id>', methods=['GET'])
def get_fundraiser_details_api(fundraiser_id):
    """Gets details for a single fundraiser."""
    try:
        details = data_manager.get_fundraiser_details(fundraiser_id)
        if not details:
            return jsonify({"error": "Fundraiser not found."} ), 404
        return jsonify(details), 200
    except Exception as e:
        app.logger.error(f"Failed to get fundraiser details for {fundraiser_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

@app.route('/players/<int:player_id>/pledges', methods=['GET'])
def get_player_pledges_api(player_id):
    return jsonify(data_manager.get_pledges_for_player(player_id))

@app.route('/fundraisers/<int:fundraiser_id>/pledge', methods=['POST'])
def pledge_api(fundraiser_id):
    """Creates a new pledge for a fundraiser."""
    data = request.get_json()
    pledger_player_id = data.get('pledger_player_id')
    amount_per_putt = data.get('amount_per_putt')
    max_donation = data.get('max_donation')

    if not pledger_player_id or not amount_per_putt:
        return jsonify({"error": "pledger_player_id and amount_per_putt are required."} ), 400

    try:
        # Create the pledge
        data_manager.create_pledge(fundraiser_id, pledger_player_id, amount_per_putt, max_donation)

        # --- Notification Logic ---
        # Get fundraiser owner's ID
        fundraiser_details = data_manager.get_fundraiser_details(fundraiser_id)
        if fundraiser_details:
            fundraiser_owner_id = fundraiser_details.get('player_id')
            
            # Get pledger's name
            pledger_info = data_manager.get_player_info(pledger_player_id)
            pledger_name = pledger_info.get('name', f'Player {pledger_player_id}') if pledger_info else f'Player {pledger_player_id}'
            
            # Get owner's email for the email notification
            owner_info = data_manager.get_player_info(fundraiser_owner_id)
            owner_email = owner_info.get('email') if owner_info else None

            message = f"{pledger_name} has pledged ${float(amount_per_putt):.2f} per putt to your fundraiser!"
            details = {
                'pledger_name': pledger_name,
                'amount_per_putt': amount_per_putt,
                'fundraiser_id': fundraiser_id
            }

            # In-App Notification to fundraiser owner
            notification_service.create_in_app_notification(
                fundraiser_owner_id,
                'NEW_PLEDGE_RECEIVED',
                message,
                details,
                f"/fundraisers/{fundraiser_id}"
            )

            # Email Notification to fundraiser owner
            if owner_email:
                email_details = details.copy()
                email_details['player_email'] = owner_email
                notification_service.send_email_notification(
                    fundraiser_owner_id,
                    'NEW_PLEDGE_RECEIVED',
                    message,
                    email_details,
                    'new_pledge_template'
                )

        return jsonify({"message": "Pledge created successfully."} ), 201
    except Exception as e:
        app.logger.error(f"Failed to create pledge for fundraiser {fundraiser_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred."} ), 500

# --- Notifications API ---
@app.route('/notifications/<int:player_id>', methods=['GET'])
def get_notifications_api(player_id):
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    status = request.args.get('status', 'all') # 'all', 'read', 'unread'
    notifications = notification_service.get_player_notifications(player_id, limit, offset, status)
    return jsonify(notifications), 200

@app.route('/notifications/<int:player_id>/unread_count', methods=['GET'])
def get_unread_notifications_count_api(player_id):
    count = notification_service.get_unread_notifications_count(player_id)
    return jsonify({"count": count}), 200

@app.route('/notifications/<int:notification_id>/mark_read', methods=['POST'])
def mark_notification_as_read_api(notification_id):
    data = request.get_json()
    player_id = data.get('player_id')
    if not player_id:
        return jsonify({"error": "Player ID is required."} ), 400
    success = notification_service.mark_notification_as_read(notification_id, player_id)
    if success:
        return jsonify({"message": "Notification marked as read."} ), 200
    return jsonify({"error": "Notification not found or not authorized."} ), 404

@app.route('/notifications/<int:player_id>/mark_all_read', methods=['POST'])
def mark_all_notifications_as_read_api(player_id):
    success_count = notification_service.mark_all_notifications_as_read(player_id)
    return jsonify({"message": f"{success_count} notifications marked as read."} ), 200

@app.route('/notifications/<int:notification_id>', methods=['DELETE'])
def delete_notification_api(notification_id):
    data = request.get_json()
    player_id = data.get('player_id')
    if not player_id:
        return jsonify({"error": "Player ID is required."} ), 400
    success = notification_service.delete_notification(notification_id, player_id)
    if success:
        return jsonify({"message": "Notification deleted."} ), 200
    return jsonify({"error": "Notification not found or not authorized."} ), 404

# --- AI Coach Endpoints ---
@app.route('/coach/conversations', methods=['GET'])
@subscription_required
def list_conversations_api():
    player_id = request.args.get('player_id', type=int)
    if not player_id:
        return jsonify({"error": "Missing player_id query parameter."} ), 400
    return jsonify(data_manager.list_conversations(player_id))

@app.route('/coach/conversations/<int:conversation_id>', methods=['GET'])
@subscription_required
def get_conversation_api(conversation_id):
    history = data_manager.get_conversation_history(conversation_id)
    if not history:
        return jsonify({"error": "Conversation not found."} ), 404
    return jsonify(history)

# --- AI Coach Retry Logic ---

# Use the app logger for tenacity's retry logging
def _log_after_retry(retry_state):
    app.logger.warning(
        f"Retrying Gemini API call, attempt {retry_state.attempt_number}, "
        f"waited {retry_state.seconds_since_start:.2f}s, error: {retry_state.outcome.exception()}"
    )

@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
    stop=tenacity.stop_after_attempt(4),
    retry=tenacity.retry_if_exception_type(google_exceptions.ResourceExhausted),
    after=_log_after_retry,
    reraise=True  # Reraise the exception after the final attempt
)
def _generate_content_with_retry(model, prompt):
    """Generates content with retry logic for rate limiting."""
    return model.generate_content(prompt)

@tenacity.retry(
    wait=tenacity.wait_exponential(multiplier=1, min=2, max=30),
    stop=tenacity.stop_after_attempt(4),
    retry=tenacity.retry_if_exception_type(google_exceptions.ResourceExhausted),
    after=_log_after_retry,
    reraise=True
)
def _send_message_with_retry(chat, message):
    """Sends a chat message with retry logic for rate limiting."""
    return chat.send_message(message)

@app.route('/coach/chat', methods=['POST'])
@subscription_required
def coach_chat_api():
    data = request.get_json()
    player_id = data.get('player_id')
    user_message = data.get('message')
    conversation_id = data.get('conversation_id')

    # This endpoint now only handles sending messages to existing conversations.
    # New conversations are created automatically on login/refresh.
    if not all([player_id, user_message, conversation_id]):
        return jsonify({"error": "Missing player_id, message, or conversation_id in request."} ), 400

    try:
        # Authorization check: make sure the player owns this conversation
        convo_owner_id = data_manager.get_conversation_owner(conversation_id)
        if convo_owner_id != player_id:
            return jsonify({"error": "Not authorized to access this conversation."} ), 403

        # Check message limit for existing conversation
        history = data_manager.get_conversation_history(conversation_id)
        user_message_count = sum(1 for msg in history if msg.get('role') == 'user')
        if user_message_count >= 5:
            return jsonify({"error": "You have reached the message limit for this conversation."} ), 429

        model = genai.GenerativeModel('gemini-1.5-flash-latest')
        chat = model.start_chat(history=history)
        response = _send_message_with_retry(chat, user_message)
        serializable_history = [{'role': h.role, 'parts': [part.text for part in h.parts]} for h in chat.history]
        data_manager.update_conversation_history(conversation_id, serializable_history)
        return jsonify({"response": response.text, "conversation_id": conversation_id})

    except google_exceptions.ResourceExhausted as e:
        app.logger.error(f"AI Coach chat failed for player {player_id} due to rate limiting after retries: {e}", exc_info=True)
        return jsonify({"error": "The AI Coach is currently overloaded. Please try again in a few minutes."} ), 429
    except Exception as e:
        app.logger.error(f"AI Coach chat failed for player {player_id}: {e}", exc_info=True)
        return jsonify({"error": f"The AI Coach encountered an error: {e}"} ), 503
