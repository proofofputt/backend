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
CORS(app, resources={r"/*": {"origins": os.environ.get("FRONTEND_URL", "http://localhost:5173"), "allow_headers": "Content-Type"}})

# Initialize database and create default user once when the app starts
with app.app_context():
    data_manager.initialize_database()

@app.route('/')
def home():
    return "Proof of Putt API is running."

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
            return jsonify({"error": "Player identification is required for this feature."}), 400

        player_info = data_manager.get_player_info(player_id)
        if not player_info or player_info.get('subscription_status') != 'active':
            return jsonify({"error": "This feature requires a full subscription."}), 403
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
        return jsonify({"error": "An internal error occurred during login."}), 500

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
            return jsonify({"error": "Registration successful, but failed to log in automatically."}), 500
    except ValueError as e:
        return jsonify({"error": str(e)}), 409
    except Exception as e:
        app.logger.error(f"Registration failed: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred during registration."}), 500

# ... (rest of the file is the same)
