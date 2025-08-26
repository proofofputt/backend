import os # Cache-busting comment
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

# --- Auth & Player Routes ---

@app.route('/login', methods=['OPTIONS'])
def login_options():
    response = jsonify({'message': 'CORS preflight successful'})
    response.headers.add('Access-Control-Allow-Origin', os.environ.get("FRONTEND_URL", "http://localhost:5173"))
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

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

@app.route('/register', methods=['OPTIONS'])
def register_options():
    response = jsonify({'message': 'CORS preflight successful'})
    response.headers.add('Access-Control-Allow-Origin', os.environ.get("FRONTEND_URL", "http://localhost:5173"))
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
    response.headers.add('Access-Control-Allow-Credentials', 'true')
    return response

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
