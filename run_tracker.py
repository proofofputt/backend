# Main application entry point.
import cv2
import logging
import numpy as np
from datetime import datetime
import json
import time
import os
import glob
import argparse
import sys # Added
import subprocess # Added

# Configure logging for the tracker script
debug_logger = logging.getLogger("tracker_debug")
debug_logger.setLevel(logging.DEBUG)

# Create handlers
log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(log_dir, exist_ok=True)
file_handler = logging.FileHandler(os.path.join(log_dir, "tracker_debug.log"))
console_handler = logging.StreamHandler()

# Create formatters and add it to handlers
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add handlers to the logger
debug_logger.addHandler(file_handler)
debug_logger.addHandler(console_handler)

# Suppress matplotlib font manager debug messages
logging.getLogger('matplotlib.font_manager').setLevel(logging.WARNING)

import math
from video_processor import VideoProcessor
from putt_classifier import PuttClassifier
from session_reporter import SessionReporter
import data_manager

# --- Configuration Flags ---
DISPLAY_VIDEO = True  # Set to True to display video output, False to run headless

# --- OBS Text File Functions ---
def reset_obs_files(debug_logger):
    """Resets all OBS text files to their initial states at the start of a session."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    obs_dir = os.path.join(script_dir, "obs_text_files")
    os.makedirs(obs_dir, exist_ok=True)
    files_to_reset = {
        "TotalPutts.txt": "0", "MadePutts.txt": "0", "MissedPutts.txt": "0",
        "CurrentStreak.txt": "0", "Consecutive.txt": "0", "MaxStreak.txt": "0",
        "DetailedClassification.txt": ""  # Add the new file with an empty default
    }
    for filename, value in files_to_reset.items():
        try:
            with open(os.path.join(obs_dir, filename), "w") as f:
                f.write(value)
        except IOError as e:
            debug_logger.error(f"Error resetting OBS file {filename}: {e}")
    debug_logger.info("OBS text files have been reset.")


# Get the absolute path of the directory where the script is located
script_dir = os.path.dirname(os.path.abspath(__file__))

# Set up logging for putt classification results (CSV format)
log_dir = os.path.join(script_dir, "logs")
os.makedirs(log_dir, exist_ok=True) # Ensure the directory exists
putt_log_filename = os.path.join(log_dir, f"putt_classification_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
putt_logger = logging.getLogger('putt_logger')
putt_logger.setLevel(logging.INFO)
putt_handler = logging.FileHandler(putt_log_filename)
putt_handler.setFormatter(logging.Formatter('%(message)s')) # Only message, no timestamp or level
putt_logger.addHandler(putt_handler)
putt_logger.info("current_frame_time,classification,detailed_classification,ball_x,ball_y,transition_history") # CSV header

# Set up a separate debug logger
debug_log_filename = os.path.join(log_dir, f"debug_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt")
debug_logger = logging.getLogger('debug_logger')
debug_logger.setLevel(logging.DEBUG)
debug_handler = logging.FileHandler(debug_log_filename)
debug_handler.setFormatter(logging.Formatter('%(levelname)s - %(message)s'))
debug_logger.addHandler(debug_handler)

def update_obs_files(total_makes, total_misses, consecutive_makes, max_consecutive_makes, debug_logger):
    """Updates the text files used by OBS."""
    obs_dir = os.path.join(script_dir, "obs_text_files")
    total_putts = total_makes + total_misses
    
    files_to_update = {
        "TotalPutts.txt": total_putts,
        "MadePutts.txt": total_makes,
        "MissedPutts.txt": total_misses,
        "CurrentStreak.txt": consecutive_makes,
        "Consecutive.txt": consecutive_makes,
        "MaxStreak.txt": max_consecutive_makes
    }
    
    for filename, value in files_to_update.items():
        try:
            with open(os.path.join(obs_dir, filename), "w") as f:
                f.write(str(value))
        except IOError as e:
            debug_logger.error(f"Error updating OBS file {filename}: {e}")

def validate_and_correct_rois(roi_data, debug_logger):
    """
    Validates the loaded ROI data, specifically checking for outdated hole quadrant definitions.
    If old definitions are found, it re-infers them using the modern icosagon method.
    """
    # Check if a representative hole quadrant has the old, incorrect 4-point format.
    # The new format has 7 points (1 center + 6 on the arc).
    if "HOLE_TOP_ROI" in roi_data and len(roi_data.get("HOLE_TOP_ROI", [])) != 7:
        debug_logger.warning("Outdated hole quadrant format detected in calibration_output.json.")
        debug_logger.warning("Attempting to auto-correct by re-inferring hole quadrants.")

        if "HOLE_ROI" not in roi_data or len(roi_data["HOLE_ROI"]) < 3:
            debug_logger.error("Cannot correct ROIs: HOLE_ROI is missing or invalid.")
            return roi_data # Return original data

        hole_points = np.array(roi_data["HOLE_ROI"], dtype=np.int32)

        # --- Re-inference logic (copied from calibration script) ---
        M = cv2.moments(hole_points)
        if M["m00"] == 0:
            debug_logger.error("Cannot correct ROIs: Centroid of HOLE_ROI could not be calculated.")
            return roi_data
        
        center_x = int(M["m10"] / M["m00"])
        center_y = int(M["m01"] / M["m00"])
        center_point = (center_x, center_y)

        distances = [np.linalg.norm(np.array(center_point) - point) for point in hole_points]
        average_radius = np.mean(distances)

        num_vertices = 20
        icosagon_vertices = []
        start_angle_offset = -9 # degrees, fine-tuned for visual alignment
        for i in range(num_vertices):
            angle = math.radians((360 / num_vertices) * i + start_angle_offset)
            x = center_x + average_radius * math.cos(angle)
            y = center_y + average_radius * math.sin(angle)
            icosagon_vertices.append([int(x), int(y)])

        # Define New Quadrant ROIs with Shared Vertices
        roi_data["HOLE_TOP_ROI"] = [list(center_point)] + [icosagon_vertices[i % 20] for i in range(18, 24)]
        roi_data["HOLE_RIGHT_ROI"] = [list(center_point)] + [icosagon_vertices[i] for i in range(3, 9)]
        roi_data["HOLE_LOW_ROI"] = [list(center_point)] + [icosagon_vertices[i] for i in range(8, 14)]
        roi_data["HOLE_LEFT_ROI"] = [list(center_point)] + [icosagon_vertices[i] for i in range(13, 19)]
        
        debug_logger.info("Successfully re-inferred and corrected hole quadrants in memory.")
    
    return roi_data

def load_and_prepare_rois(config_path, debug_logger):
    """Loads, validates, and prepares ROI data from the configuration file."""
    try:
        with open(config_path, 'r') as f:
            calibrated_rois = json.load(f)
        debug_logger.info(f"Loaded ROI configuration from {config_path}")
    except FileNotFoundError:
        debug_logger.error(f"Error: Calibration file not found at {config_path}. Please run calibration first.")
        return None
    except json.JSONDecodeError as e:
        debug_logger.error(f"Error decoding JSON from {config_path}: {e}")
        return None

    # --- Auto-Correction for Outdated Calibration ---
    # This step checks if the loaded ROI file uses an old format for hole quadrants
    # and automatically updates it in memory to the modern, more accurate format.
    calibrated_rois = validate_and_correct_rois(calibrated_rois, debug_logger)

    # Ensure all expected ROIs are present in calibrated_rois
    expected_rois = [
        "PUTTING_MAT_ROI", "RAMP_ROI", "HOLE_ROI",
        "LEFT_OF_MAT_ROI", "CATCH_ROI", "RETURN_TRACK_ROI",
        "RAMP_LEFT_ROI", "RAMP_CENTER_ROI", "RAMP_RIGHT_ROI",
        "HOLE_TOP_ROI", "HOLE_RIGHT_ROI", "HOLE_LOW_ROI", "HOLE_LEFT_ROI",
        "IGNORE_AREA_ROI"
    ]

    for roi_name in expected_rois:
        if roi_name not in calibrated_rois:
            calibrated_rois[roi_name] = []
            debug_logger.warning(f"{roi_name} not found in calibration_output.json. Added as an empty ROI.")
        # Ensure all ROI lists are converted to NumPy arrays
        if isinstance(calibrated_rois[roi_name], list):
            calibrated_rois[roi_name] = np.array(calibrated_rois[roi_name], dtype=np.int32)
            
    return calibrated_rois

def update_display_window(display_frame, calibrated_rois, roi_colors, scale_factors, stats, ball_data, current_video_time):
    """Draws all visual elements onto the display frame."""
    scale_x_display, scale_y_display = scale_factors
    total_makes, total_misses, consecutive_makes, max_consecutive_makes = stats
    (overall_detected_ball_center, detailed_classification_results_display, 
     ball_in_hole, classification) = ball_data

    # Draw polygon ROIs on the display frame (scaled)
    for name, roi_points_data in calibrated_rois.items():
        if name == "camera_index": # Skip camera_index
            continue
        
        # Handle HOLE_ROI which might be a dict with 'points'
        if isinstance(roi_points_data, dict) and 'points' in roi_points_data:
            roi_points = np.array(roi_points_data['points'], dtype=np.int32)
        else:
            roi_points = np.array(roi_points_data, dtype=np.int32)

        if len(roi_points) > 0:
            scaled_roi = (roi_points * np.array([scale_x_display, scale_y_display])).astype(np.int32)
            cv2.polylines(display_frame, [scaled_roi], isClosed=True, color=roi_colors.get(name, (255, 255, 255)), thickness=2)

    # Draw a circle at the ball's position on the display frame (scaled)
    if overall_detected_ball_center:
        cv2.circle(display_frame, (int(overall_detected_ball_center[0] * scale_x_display), int(overall_detected_ball_center[1] * scale_y_display)), 10, (0, 255, 255), -1)
    
    # Highlight HOLE_ROI if ball is detected within it
    if ball_in_hole:
        # Use the loaded HOLE_ROI points
        hole_roi_points = calibrated_rois["HOLE_ROI"]
        if isinstance(hole_roi_points, dict) and 'points' in hole_roi_points:
            hole_roi_points = hole_roi_points['points']
        
        scaled_hole_roi = (np.array(hole_roi_points, dtype=np.int32) * np.array([scale_x_display, scale_y_display])).astype(np.int32)
        cv2.polylines(display_frame, [scaled_hole_roi], isClosed=True, color=(0, 255, 255), thickness=3) # Yellow highlight

    # Display overall statistics (persistent)
    cv2.putText(display_frame, f"Makes: {total_makes}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
    cv2.putText(display_frame, f"Misses: {total_misses}", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
    cv2.putText(display_frame, f"Consecutive Makes: {consecutive_makes}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
    cv2.putText(display_frame, f"Max Consecutive Makes: {max_consecutive_makes}", (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

    # Display session timer (minutes:seconds)
    if current_video_time > 0: # Only display if timer has started
        minutes = int(current_video_time // 60)
        seconds = int(current_video_time % 60)
        cv2.putText(display_frame, f"Time: {minutes:02d}:{seconds:02d}", (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

    if classification:
        cv2.putText(display_frame, f"Putt: {classification}", (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    # Display ball coordinates and ROI status on screen (persistent)
    y_offset_roi = 180 # Adjusted starting y-offset to avoid overlap with putt result
    if overall_detected_ball_center:
        cv2.putText(display_frame, f"Ball: ({overall_detected_ball_center[0] * scale_x_display:.0f}, {overall_detected_ball_center[1] * scale_y_display:.0f})", (10, y_offset_roi), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
        y_offset_roi += 30
    
    for k, v in detailed_classification_results_display.items():
        cv2.putText(display_frame, f"{k}: {v}", (10, y_offset_roi), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        y_offset_roi += 20

    cv2.imshow("Putt Tracker", display_frame)

def get_available_cameras():
    """
    Detects and returns a list of available camera indices.
    """
    available_cameras = []
    for i in range(10): # Check indices from 0 to 9
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            available_cameras.append(i)
            cap.release()
    return available_cameras

def confirm_calibration_interactively(cap, calibrated_rois, roi_colors, scale_x_display, scale_y_display, debug_logger, player_id):
    """
    Displays the loaded ROIs on the live camera feed and prompts the user for confirmation.
    If ROIs are incorrect, offers to launch calibration script.
    Returns True if calibration is confirmed, False if user quits or recalibrates.
    """
    debug_logger.info("Starting calibration confirmation stage.")
    
    # Create a temporary window for confirmation
    cv2.namedWindow("Confirm Calibration", cv2.WINDOW_NORMAL)

    while True:
        ret, frame = cap.read()
        if not ret:
            debug_logger.error("Error: Could not read frame from camera during calibration confirmation.")
            cv2.destroyAllWindows()
            return False

        display_frame = frame.copy()
        
        # Draw ROIs on the display frame (scaled)
        for name, roi_points_data in calibrated_rois.items():
            if name == "camera_index":
                continue
            
            if isinstance(roi_points_data, dict) and 'points' in roi_points_data:
                roi_points = np.array(roi_points_data['points'], dtype=np.int32)
            else:
                roi_points = np.array(roi_points_data, dtype=np.int32)

            if len(roi_points) > 0:
                scaled_roi = (roi_points * np.array([scale_x_display, scale_y_display])).astype(np.int32)
                cv2.polylines(display_frame, [scaled_roi], isClosed=True, color=roi_colors.get(name, (255, 255, 255)), thickness=2)

        # Add confirmation text
        cv2.putText(display_frame, "ROIs displayed. Press 'y' to confirm, 'r' to recalibrate, 'q' to quit.", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.imshow("Confirm Calibration", display_frame)

        key = cv2.waitKey(1) & 0xFF
        if key == ord('y'):
            debug_logger.info("Calibration confirmed by user.")
            cv2.destroyAllWindows()
            return True
        elif key == ord('r'):
            debug_logger.info("User requested recalibration. Launching calibration script.")
            cv2.destroyAllWindows()
            # Launch calibration script as a separate process
            python_executable = sys.executable # sys is not imported yet
            calibration_script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'calibration.py')
            subprocess.Popen([
                python_executable, calibration_script_path,
                '--player_id', str(player_id),
                '--camera_index', str(cap.get(cv2.CAP_PROP_POS_MSEC)) # Pass current camera index
            ])
            return False # Indicate that session should not proceed
        elif key == ord('q'):
            debug_logger.info("User quit calibration confirmation. Exiting session.")
            cv2.destroyAllWindows()
            return False

def main():
    parser = argparse.ArgumentParser(description="Run the Putt Tracker application.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--video_path", help="Path to the input video file.")
    group.add_argument("--camera_index", type=int, help="Index of the camera for live feed.")
    parser.add_argument("--model", default=os.path.join(script_dir, "models", "best.pt"), help="Path to the YOLOv8 model file.")
    parser.add_argument("--config", default=os.path.join(script_dir, "calibration_output.json"), help="Path to the ROI configuration JSON file.")
    parser.add_argument("--player_id", type=int, help="The ID of the player for this session (used with --camera_index).")
    parser.add_argument("--session_id", type=int, help="The ID of the session to update (used with --camera_index).")
    parser.add_argument("--duel_id", type=int, help="The ID of the duel this session is part of.")
    parser.add_argument("--league_round_id", type=int, help="The ID of the league round this session is part of.")
    parser.add_argument("--time_limit_seconds", type=int, help="Optional session duration limit in seconds.")
    args = parser.parse_args()

    is_live_feed = args.camera_index is not None
    if is_live_feed and (args.player_id is None or args.session_id is None):
        parser.error("--player_id and --session_id are required when using --camera_index.")

    video_source = None # Initialize video_source

    available_cameras = get_available_cameras()
    if not available_cameras:
        debug_logger.error("No cameras found. Please ensure a camera is connected and not in use.")
        return

    current_camera_list_index = 0 # Index into available_cameras list

    # Determine initial camera index
    if args.camera_index is not None:
        if args.camera_index in available_cameras:
            selected_camera_index = args.camera_index
            current_camera_list_index = available_cameras.index(selected_camera_index)
        else:
            debug_logger.warning(f"Provided camera index {args.camera_index} not found. Using first available camera.")
            selected_camera_index = available_cameras[0]
    elif args.video_path:
        # Static image mode, no live camera needed
        video_source = args.video_path
        is_live_feed = False
    else:
        # No camera index or video path provided, use first available camera
        selected_camera_index = available_cameras[0]

    # --- Live Camera Mode ---
    if video_source is None: # Only proceed if a camera index is valid
        video_source = selected_camera_index
        is_live_feed = True
        cap = cv2.VideoCapture(video_source)
        if not cap.isOpened():
            debug_logger.error(f"Error: Could not open camera with index {video_source}. Exiting.")
            return
    else: # Video path was provided
        cap = cv2.VideoCapture(video_source)
        if not cap.isOpened():
            debug_logger.error(f"Error: Could not open video source: {video_source}. Exiting.")
            return

    video_processor = VideoProcessor(model_path=args.model, min_bbox_area=50)
    scale_x_display = 1.0 # No scaling for display
    scale_y_display = 1.0 # No scaling for display

    roi_colors = {
        "PUTTING_MAT_ROI": (0, 0, 255), "RAMP_ROI": (0, 255, 255), "HOLE_ROI": (255, 0, 0),
        "LEFT_OF_MAT_ROI": (255, 255, 0), "CATCH_ROI": (0, 165, 255), "RETURN_TRACK_ROI": (255, 0, 255),
        "RAMP_LEFT_ROI": (128, 0, 128), "RAMP_CENTER_ROI": (0, 128, 128), "RAMP_RIGHT_ROI": (128, 128, 0),
        "HOLE_TOP_ROI": (0, 128, 0), "HOLE_RIGHT_ROI": (128, 0, 0), "HOLE_LOW_ROI": (0, 0, 128),
        "HOLE_LEFT_ROI": (128, 128, 128), "IGNORE_AREA_ROI": (50, 50, 50)
    }

    calibrated_rois = load_and_prepare_rois(args.config, debug_logger)
    if calibrated_rois is None:
        return

    putt_classifier = PuttClassifier(yolo_model=video_processor.model, rois=calibrated_rois, logger=debug_logger)
    cap = cv2.VideoCapture(video_source)
    reset_obs_files(debug_logger)

    if not cap.isOpened():
        debug_logger.error(f"Error: Could not open video source: {video_source}")
        return
    debug_logger.info(f"Video source opened successfully: {video_source}")

    if DISPLAY_VIDEO:
        cv2.namedWindow("Putt Tracker", cv2.WINDOW_NORMAL)
    
    # --- Calibration Confirmation Stage ---
    # Pass player_id to the confirmation function
    if not confirm_calibration_interactively(cap, calibrated_rois, roi_colors, scale_x_display, scale_y_display, debug_logger, args.player_id):
        debug_logger.info("Calibration not confirmed or recalibration requested. Exiting session.")
        cap.release()
        cv2.destroyAllWindows()
        return # Exit if calibration is not confirmed or recalibration is launched

    frame_count = 0
    start_time = time.time() # This will be the video start time
    session_start_time = None # This will be the time of the first putt in ramp
    total_makes = 0
    total_misses = 0
    consecutive_makes = 0
    max_consecutive_makes = 0
    scoring_active = False
    classification = None
    overall_detected_ball_center = None
    ball_in_hole = False
    ball_in_ramp = False # Initialize ball_in_ramp here
    
    session_duration_limit = args.time_limit_seconds
    if session_duration_limit:
        debug_logger.info(f"Session time limit is active: {session_duration_limit} seconds ({session_duration_limit / 60:.2f} minutes).")

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                debug_logger.info("End of video or cannot read frame.")
                break

            frame_count += 1
            video_current_time_raw = (time.time() - start_time) if is_live_feed else (cap.get(cv2.CAP_PROP_POS_MSEC) / 1000.0)
            
            # Detect first putt in ramp to start session timer
            if session_start_time is None and ball_in_ramp:
                session_start_time = time.time()
                debug_logger.info(f"First putt detected in ramp. Session timer started at {session_start_time}.")

            current_video_time = (time.time() - session_start_time) if session_start_time is not None else 0.0 # Calculate session-relative time

            display_frame = frame.copy() # Use original frame for display
            detected_balls_original_scale = video_processor.process_frame(frame)

            # Update and classify first, to get ball_in_ramp
            (current_state, classification, detailed_classification_str, overall_detected_ball_center, 
             ball_in_putting_mat, ball_in_ramp, ball_in_return_track, ball_in_left_of_mat, 
             ball_in_catch, ball_in_hole, ball_in_hole_top, ball_in_hole_right, 
             ball_in_hole_low, ball_in_hole_left, ball_in_ramp_left, ball_in_ramp_center, 
             ball_in_ramp_right, transition_history) = putt_classifier.update_and_classify(frame, detected_balls_original_scale, current_video_time) # Pass session-relative time
            
            # Check for session time limit
            if session_duration_limit is not None and current_video_time >= session_duration_limit:
                debug_logger.info(f"Session time limit of {session_duration_limit} seconds reached. Ending session.")
                break # Exit the main loop

            if classification:
                putt_logger.info(f'{current_video_time:.2f},{classification},{detailed_classification_str},{overall_detected_ball_center[0] if overall_detected_ball_center else ""},{overall_detected_ball_center[1] if overall_detected_ball_center else ""},{json.dumps(transition_history)}')
                
                if not scoring_active:
                    scoring_active = True
                    debug_logger.info("Scoring activated: First putt detected.")

                if classification.startswith("MAKE"):
                    total_makes += 1
                    consecutive_makes += 1
                    if consecutive_makes > max_consecutive_makes:
                        max_consecutive_makes = consecutive_makes
                elif classification.startswith("MISS"):
                    total_misses += 1
                    consecutive_makes = 0

                update_obs_files(total_makes, total_misses, consecutive_makes, max_consecutive_makes, debug_logger)
                
                try:
                    filepath = os.path.join(script_dir, "obs_text_files", "DetailedClassification.txt")
                    with open(filepath, "w") as f:
                        f.write(detailed_classification_str)
                except IOError as e:
                    debug_logger.error(f"Error writing to DetailedClassification.txt: {e}")

            if DISPLAY_VIDEO:
                detailed_classification_results_display = {
                    "ball_in_putting_mat": ball_in_putting_mat, "ball_in_ramp": ball_in_ramp,
                    "ball_in_hole": ball_in_hole, "ball_in_left_of_mat": ball_in_left_of_mat,
                    "ball_in_catch": ball_in_catch, "ball_in_return_track": ball_in_return_track,
                    "ball_in_ramp_left": ball_in_ramp_left, "ball_in_ramp_center": ball_in_ramp_center,
                    "ball_in_ramp_right": ball_in_ramp_right, "ball_in_hole_top": ball_in_hole_top,
                    "ball_in_hole_right": ball_in_hole_right, "ball_in_hole_low": ball_in_hole_low,
                    "ball_in_hole_left": ball_in_hole_left
                }
                stats = (total_makes, total_misses, consecutive_makes, max_consecutive_makes)
                ball_data = (overall_detected_ball_center, detailed_classification_results_display, ball_in_hole, classification)
                scale_factors = (scale_x_display, scale_y_display)
                update_display_window(display_frame, calibrated_rois, roi_colors, scale_factors, stats, ball_data, current_video_time)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                debug_logger.info("'q' pressed. Exiting...")
                break
    finally:
        end_time = time.time()
        # Calculate session_duration based on session_start_time if it was set
        if session_start_time is not None:
            session_duration = round(end_time - session_start_time)
            debug_logger.info(f"Session ended. Actual playing duration: {session_duration} seconds.")
        else:
            session_duration = 0
            debug_logger.info("Session ended. No putts detected in ramp, so playing duration is 0.")
        
        putt_log_file = putt_logger.handlers[0].baseFilename if putt_logger.handlers else None

        if is_live_feed and args.session_id and putt_log_file:
            # Get player info for the report
            player_info = data_manager.get_player_info(args.player_id)
            
            reporter = SessionReporter(putt_log_file) # Initialize with only input_csv_path # Initialize with only input_csv_path
            reporter.load_and_process_data() # Load and process data from the CSV
            
            # Generate report and get the report data
            session_report_data = reporter.generate_report(os.path.join(script_dir, "Session.Reports"), player_info) # Pass output_dir and player_info
            
            debug_logger.info(f"Session report generated for session {args.session_id}")
            
            # Update session stats in the database using data from the reporter
            data_manager.update_session(args.session_id, reporter)
            debug_logger.info(f"Updated session {args.session_id} in the database.")

            # Recalculate all-time player stats
            data_manager.recalculate_player_stats(args.player_id)

            if args.duel_id:
                data_manager.submit_duel_session(args.duel_id, args.session_id, args.player_id)

            if args.league_round_id:
                data_manager.submit_league_session(args.league_round_id, args.player_id, args.session_id, reporter.total_makes)

        cap.release()
        if DISPLAY_VIDEO:
            cv2.destroyAllWindows()
        debug_logger.info("Video capture released and windows closed.")


if __name__ == "__main__":
    main()