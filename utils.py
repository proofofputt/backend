import json
import os

def get_camera_index_from_config(player_id):
    """Reads the camera index from the player-specific calibration config file."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f'calibration_output_{player_id}.json')
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        return config.get('camera_index', 0) # Default to 0 if not found
    except (FileNotFoundError, json.JSONDecodeError):
        return 0 # Default to camera 0 if config is missing or invalid