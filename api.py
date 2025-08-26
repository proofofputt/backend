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

# ... (rest of the file is the same)