import cv2
import numpy as np
import json
import argparse
import os
import math
from datetime import datetime
from math import atan2, degrees

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

# Global variables
current_roi_points = []
roi_data = {}
current_roi_name = ""
img_original = None
output_config_path = ""
_last_clicked_point = None

# Physical dimensions (in inches)
RAMP_WIDTH_INCHES = 12.0
HOLE_DIAMETER_INCHES = 4.0
HOLE_OFFSET_FROM_CATCH_INCHES = 1.5 # Distance from the top edge of the ramp to the center of the hole
RAMP_LENGTH_INCHES = 14.5 # Length of the ramp in inches

# Inference extension distances (in pixels)
LEFT_OF_MAT_EXTENSION_PIXELS = 300
CATCH_EXTENSION_PIXELS = 100


def calculate_centroid(points):
    """Calculates the centroid of a list of points."""
    x_coords = [p[0] for p in points]
    y_coords = [p[1] for p in points]
    centroid_x = sum(x_coords) / len(points)
    centroid_y = sum(y_coords) / len(points)
    return (centroid_x, centroid_y)

def get_quadrant(point, centroid):
    """
    Determines the quadrant of a point relative to the centroid,
    with quadrants rotated by 45 degrees.
    """
    # Adjust point to be relative to the centroid
    x = point[0] - centroid[0]
    y = point[1] - centroid[1]

    angle = math.atan2(y, x)

    # Normalize angle to be in [0, 2*pi]
    if angle < 0:
        angle += 2 * math.pi

    # Quadrant boundaries rotated by 45 degrees (pi/4 radians)
    # Top: -45 to 45 deg (-pi/4 to pi/4)
    # Right: 45 to 135 deg (pi/4 to 3pi/4)
    # Low: 135 to 225 deg (3pi/4 to 5pi/4)
    # Left: 225 to 315 deg (5pi/4 to 7pi/4)

    if (angle <= math.pi / 4) or (angle > 7 * math.pi / 4):
        return "TOP"
    elif (angle > math.pi / 4) and (angle <= 3 * math.pi / 4):
        return "RIGHT"
    elif (angle > 3 * math.pi / 4) and (angle <= 5 * math.pi / 4):
        return "LOW"
    else: # (angle > 5 * math.pi / 4) and (angle <= 7 * math.pi / 4)
        return "LEFT"

def average_points_to_dodecagon(points):
    """
    Averages 12 points into a regular dodecagon centered on their centroid.
    The dodecagon is rotated 90 degrees clockwise.
    """
    if len(points) != 12:
        raise ValueError("Input must be a list of 12 points.")

    centroid = calculate_centroid(points)

    # Calculate the average radius from the centroid to the points
    radii = [math.sqrt((p[0] - centroid[0])**2 + (p[1] - centroid[1])**2) for p in points]
    avg_radius = sum(radii) / len(radii)

    dodecagon_points = []
    # 12 vertices, 30 degrees (pi/6 radians) apart
    for i in range(12):
        # Start at -90 degrees (-pi/2) for the 90-degree clockwise rotation
        # and add 30 degrees for each subsequent point.
        angle = -math.pi / 2 + (i * math.pi / 6)
        x = centroid[0] + avg_radius * math.cos(angle)
        y = centroid[1] + avg_radius * math.sin(angle)
        dodecagon_points.append((x, y))

    return dodecagon_points, centroid

def infer_hole_quadrants(roi_data):
    if "HOLE_ROI" not in roi_data or len(roi_data["HOLE_ROI"]) < 3:
        print("Warning: HOLE_ROI not defined or has fewer than 3 points. Cannot infer hole quadrants.")
        return

    hole_points = np.array(roi_data["HOLE_ROI"], dtype=np.int32)

    # --- Icosagon-based quadrant inference (from visualize_hole_rois_v2.py) ---
    M = cv2.moments(hole_points)
    if M["m00"] == 0:
        print("Error: Could not calculate centroid of HOLE_ROI. Cannot infer quadrants.")
        return
    
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

    # Define New Quadrant ROIs with Shared Vertices (7 points: 1 center + 6 on arc)
    roi_data["HOLE_TOP_ROI"] = [list(center_point)] + [icosagon_vertices[i % 20] for i in range(18, 24)]
    roi_data["HOLE_RIGHT_ROI"] = [list(center_point)] + [icosagon_vertices[i] for i in range(3, 9)]
    roi_data["HOLE_LOW_ROI"] = [list(center_point)] + [icosagon_vertices[i] for i in range(8, 14)]
    roi_data["HOLE_LEFT_ROI"] = [list(center_point)] + [icosagon_vertices[i] for i in range(13, 19)]
    
    print("Inferred HOLE_TOP_ROI, HOLE_RIGHT_ROI, HOLE_LOW_ROI, HOLE_LEFT_ROI using icosagon analysis.")

def compute_circle_and_arcs(points):
    # Placeholder function for compute_circle_and_arcs
    # In a real scenario, this would compute the best-fit circle and arc data from the 12 points
    print("Warning: Using placeholder for compute_circle_and_arcs. Implement actual logic for accurate hole data.")
    return None, None, None

def infer_left_of_mat_roi(roi_data):
    if "PUTTING_MAT_ROI" not in roi_data:
        print("Warning: PUTTING_MAT_ROI not defined. Cannot infer LEFT_OF_MAT_ROI.")
        return

    putting_mat_points = np.array(roi_data["PUTTING_MAT_ROI"], dtype=np.float32)

    # Find the two points with the largest Y-coordinates (bottom edge of putting mat)
    # and the two points with the smallest Y-coordinates (top edge of putting mat)
    sorted_by_y = sorted(putting_mat_points, key=lambda p: p[1])
    top_left_mat = sorted_by_y[0] # Assuming top-left is smallest Y, then smallest X
    top_right_mat = sorted_by_y[1] # Assuming top-right is smallest Y, then largest X
    bottom_left_mat = sorted_by_y[2] # Assuming bottom-left is largest Y, then smallest X
    bottom_right_mat = sorted_by_y[3] # Assuming bottom-right is largest Y, then largest X

    # Re-sort by X to ensure correct order for extension
    top_points = sorted([sorted_by_y[0], sorted_by_y[1]], key=lambda p: p[0])
    bottom_points = sorted([sorted_by_y[2], sorted_by_y[3]], key=lambda p: p[0])

    top_left_mat = top_points[0]
    top_right_mat = top_points[1]
    bottom_left_mat = bottom_points[0]
    bottom_right_mat = bottom_points[1]

    # Extend lines from top corners through bottom corners
    # Vector from top-left to bottom-left
    v1 = bottom_left_mat - top_left_mat
    # Vector from top-right to bottom-right
    v2 = bottom_right_mat - top_right_mat

    # Calculate new points by extending these vectors
    new_bottom_left = top_left_mat + v1 * (1 + LEFT_OF_MAT_EXTENSION_PIXELS / np.linalg.norm(v1)) if np.linalg.norm(v1) > 0 else bottom_left_mat
    new_bottom_right = top_right_mat + v2 * (1 + LEFT_OF_MAT_EXTENSION_PIXELS / np.linalg.norm(v2)) if np.linalg.norm(v2) > 0 else bottom_right_mat

    # The LEFT_OF_MAT_ROI will be defined by the original top points and the new extended bottom points
    left_of_mat_roi = np.array([
        top_left_mat,
        top_right_mat,
        new_bottom_right,
        new_bottom_left
    ], dtype=np.int32)
    roi_data["LEFT_OF_MAT_ROI"] = left_of_mat_roi.tolist()
    print("Inferred LEFT_OF_MAT_ROI.")

def infer_catch_roi(roi_data):
    if "RAMP_ROI" not in roi_data:
        print("Warning: RAMP_ROI not defined. Cannot infer CATCH_ROI.")
        return

    ramp_points = np.array(roi_data["RAMP_ROI"], dtype=np.float32)

    # Find the two points with the smallest Y-coordinates (top edge of ramp)
    sorted_by_y = sorted(ramp_points, key=lambda p: p[1])
    top_left_ramp = sorted_by_y[0] # Assuming top-left is smallest Y, then smallest X
    top_right_ramp = sorted_by_y[1] # Assuming top-right is smallest Y, then largest X

    # Re-sort by X to ensure correct order for extension
    top_points = sorted([sorted_by_y[0], sorted_by_y[1]], key=lambda p: p[0])
    bottom_points = sorted([sorted_by_y[2], sorted_by_y[3]], key=lambda p: p[0])

    top_left_ramp = top_points[0]
    top_right_ramp = top_points[1]
    bottom_left_ramp = bottom_points[0]
    bottom_right_ramp = bottom_points[1]

    # Extend lines from bottom corners through top corners (upwards)
    # Vector from bottom-left to top-left
    v1 = top_left_ramp - bottom_left_ramp
    # Vector from bottom-right to top-right
    v2 = top_right_ramp - bottom_right_ramp

    # Calculate new points by extending these vectors
    new_top_left = bottom_left_ramp + v1 * (1 + CATCH_EXTENSION_PIXELS / np.linalg.norm(v1)) if np.linalg.norm(v1) > 0 else top_left_ramp
    new_top_right = bottom_right_ramp + v2 * (1 + CATCH_EXTENSION_PIXELS / np.linalg.norm(v2)) if np.linalg.norm(v2) > 0 else top_right_ramp

    # The CATCH_ROI will be defined by the original bottom points and the new extended top points
    catch_roi = np.array([
        new_top_left,
        new_top_right,
        bottom_right_ramp,
        bottom_left_ramp
    ], dtype=np.int32)
    roi_data["CATCH_ROI"] = catch_roi.tolist()
    print("Inferred CATCH_ROI.")

def interpolate_y(x, p1, p2):
    # p1 and p2 are [x, y] points
    x1, y1 = p1
    x2, y2 = p2
    if x2 - x1 == 0: # Vertical line
        return y1 # Should not happen for ramp top/bottom edges
    return y1 + (x - x1) * (y2 - y1) / (x2 - x1)

def infer_ramp_rois(roi_data):
    if "RAMP_ROI" not in roi_data or "HOLE_ROI" not in roi_data:
        print("Warning: RAMP_ROI or HOLE_ROI not defined. Cannot infer ramp sub-ROIs.")
        return None

    # Get the pixel coordinates of the RAMP_ROI (these are the destination points)
    ramp_pixel_pts = np.array(roi_data["RAMP_ROI"], dtype=np.float32)

    # Robustly identify the four corner points of the RAMP_ROI
    # Sort points based on their sum and difference to find corners
    s = ramp_pixel_pts.sum(axis=1)
    d = np.diff(ramp_pixel_pts, axis=1)

    ramp_top_left_pixel = ramp_pixel_pts[np.argmin(s)]
    ramp_bottom_right_pixel = ramp_pixel_pts[np.argmax(s)]
    ramp_top_right_pixel = ramp_pixel_pts[np.argmin(d)]
    ramp_bottom_left_pixel = ramp_pixel_pts[np.argmax(d)]

    # Re-order to ensure consistency for interpolation (Top-Left, Top-Right, Bottom-Right, Bottom-Left)
    # This step is crucial if the above sorting doesn't guarantee the exact order needed for linear interpolation
    # However, for a roughly rectangular ROI, the sum/diff method is usually sufficient to find the extreme corners.
    # Let's re-sort based on y-coordinate to get top and bottom, then x-coordinate for left and right.
    # This is a more reliable way to get the "visual" top-left, top-right, etc.
    sorted_by_y = sorted(ramp_pixel_pts, key=lambda p: p[1])
    top_points = sorted(sorted_by_y[:2], key=lambda p: p[0]) # Top-left and Top-right
    bottom_points = sorted(sorted_by_y[2:], key=lambda p: p[0]) # Bottom-left and Bottom-right

    ramp_top_left_pixel = top_points[0]
    ramp_top_right_pixel = top_points[1]
    ramp_bottom_left_pixel = bottom_points[0]
    ramp_bottom_right_pixel = bottom_points[1]

    # Calculate the length of the ramp in pixels (approximate, using average y-coordinates)
    avg_top_y = (ramp_top_left_pixel[1] + ramp_top_right_pixel[1]) / 2
    avg_bottom_y = (ramp_bottom_left_pixel[1] + ramp_bottom_right_pixel[1]) / 2
    ramp_pixel_length = avg_bottom_y - avg_top_y

    if ramp_pixel_length <= 0:
        print("Warning: Ramp pixel length is non-positive. Cannot infer ramp sub-ROIs.")
        return None

    # Define proportions for division along the length
    # We want three sections: TOP, MIDDLE, BOTTOM
    # So, two division lines at 1/3 and 2/3 of the length
    prop1 = 1/3.0
    prop2 = 2/3.0

    # Interpolate points along the left and right side edges of the RAMP_ROI
    # Left side edge: from ramp_top_left_pixel to ramp_bottom_left_pixel
    div1_left_pixel = ramp_top_left_pixel + (ramp_bottom_left_pixel - ramp_top_left_pixel) * prop1
    div2_left_pixel = ramp_top_left_pixel + (ramp_bottom_left_pixel - ramp_top_left_pixel) * prop2

    # Right side edge: from ramp_top_right_pixel to ramp_bottom_right_pixel
    div1_right_pixel = ramp_top_right_pixel + (ramp_bottom_right_pixel - ramp_top_right_pixel) * prop1
    div2_right_pixel = ramp_top_right_pixel + (ramp_bottom_right_pixel - ramp_top_right_pixel) * prop2

    # Infer RAMP_LEFT_ROI (now effectively RAMP_TOP_ROI)
    ramp_left_roi = np.array([
        ramp_top_left_pixel,
        ramp_top_right_pixel,
        div1_right_pixel,
        div1_left_pixel
    ], dtype=np.int32)
    roi_data["RAMP_LEFT_ROI"] = ramp_left_roi.tolist()

    # Infer RAMP_CENTER_ROI (now effectively RAMP_MIDDLE_ROI)
    ramp_center_roi = np.array([
        div1_left_pixel,
        div1_right_pixel,
        div2_right_pixel,
        div2_left_pixel
    ], dtype=np.int32)
    roi_data["RAMP_CENTER_ROI"] = ramp_center_roi.tolist()

    # Infer RAMP_RIGHT_ROI (now effectively RAMP_BOTTOM_ROI)
    ramp_right_roi = np.array([
        div2_left_pixel,
        div2_right_pixel,
        ramp_bottom_right_pixel,
        ramp_bottom_left_pixel
    ], dtype=np.int32)
    roi_data["RAMP_RIGHT_ROI"] = ramp_right_roi.tolist()

    print("Inferred RAMP_LEFT_ROI (TOP), RAMP_CENTER_ROI (MIDDLE), RAMP_RIGHT_ROI (BOTTOM) using proportional interpolation along ramp length.")
    # No perspective matrix returned as it's not used for hole calculation anymore
    return None

def save_rois_to_json(roi_data_to_save, rotated_image_height, rotated_image_width):
    """Save ROIs to JSON, ensuring all numbers are Python-native types."""
    try:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M")
        output_path = output_config_path
        if output_path == "roi_config.json":
            output_path = f"ROI_Config_{timestamp}.JSON"
        
        processed_roi_data = {}
        for roi_name, data in roi_data_to_save.items():
            if roi_name == "camera_index":
                processed_roi_data[roi_name] = data
                continue
            
            points = data
            valid_points = [p for p in points if p is not None]
            if not valid_points:
                print(f"Warning: Skipping empty ROI '{roi_name}' in save.")
                continue

            # Convert all points to native Python integers
            native_points = [[int(p[0]), int(p[1])] for p in valid_points]
            
            # The points are already in the correct orientation from the user clicks.
            # No rotation is needed.
            if roi_name == "HOLE_ROI" and isinstance(data, dict) and "points" in data:
                center, radius, arcs = compute_circle_and_arcs(native_points)
                if center and radius:
                    processed_roi_data[roi_name] = {
                        "points": native_points,
                        "center": [int(center[0]), int(center[1])],
                        "radius": float(radius),
                        "arcs": arcs
                    }
                else:
                    processed_roi_data[roi_name] = native_points
            else:
                processed_roi_data[roi_name] = native_points
        
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, 'w') as f:
            json.dump(processed_roi_data, f, indent=4)
        print(f"\nROI configuration saved to {output_path}")
        return output_path
    except Exception as e:
        print(f"Error saving ROI configuration: {e}")
        return None


def mouse_callback(event, x, y, flags, param):
    global _last_clicked_point
    if event == cv2.EVENT_LBUTTONDOWN:
        _last_clicked_point = [x, y]
        print(f"Debug: Left click at ({x}, {y})")


def main():
    global current_roi_points, roi_data, current_roi_name, img_original, output_config_path, _last_clicked_point

    parser = argparse.ArgumentParser(description="Calibrate ROIs for golf ball tracking (v3.0).")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--camera_index", type=int, help="Index of the camera to use for live calibration.")
    group.add_argument("--image_path", type=str, help="Path to a static image file for calibration.")
    parser.add_argument("--player_id", type=int, required=True, help="Player ID to associate with this calibration file.")
    args = parser.parse_args()

    # Construct the output path based on the player_id to create player-specific calibrations.
    output_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"calibration_output_{args.player_id}.json")
    selected_camera_index = -1
    img_original = None

    available_cameras = get_available_cameras()
    if not available_cameras:
        print("Error: No cameras found. Please ensure a camera is connected and not in use.")
        return

    current_camera_list_index = 0 # Index into available_cameras list

    # Determine initial camera index
    if args.camera_index is not None:
        if args.camera_index in available_cameras:
            selected_camera_index = args.camera_index
            current_camera_list_index = available_cameras.index(selected_camera_index)
        else:
            print(f"Warning: Provided camera index {args.camera_index} not found. Using first available camera.")
            selected_camera_index = available_cameras[0]
    elif args.image_path:
        # Static image mode, no live camera needed
        img_original = cv2.imread(args.image_path) # Renamed from args.image_path
        if img_original is None:
            print(f"Error: Could not load image from {args.image_path}")
            return
        selected_camera_index = -1 # Indicates calibration from file
    else:
        # No camera index or video path provided, use first available camera
        selected_camera_index = available_cameras[0]

    # --- Live Camera Mode ---
    if selected_camera_index != -1: # Only proceed if a camera index is valid
        cap = cv2.VideoCapture(selected_camera_index)
        if not cap.isOpened():
            print(f"Error: Could not open camera with index {selected_camera_index}.")
            return

        print("\nCamera feed open.")
        print("Press SPACE to capture a frame for calibration.")
        print("Press 'n' to cycle to the next camera.") # Changed from 's' to 'n'
        print("Press 'q' to quit.")

        while True:
            ret, frame = cap.read()
            if not ret:
                print("Error: Could not read frame from camera.")
                break

            display_frame = frame.copy()
            cv2.putText(display_frame, f"Camera: {selected_camera_index} (Press SPACE to capture, 'n' for next, 'q' to quit)", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2) # Updated instruction
            cv2.imshow("Camera Feed", display_frame)

            key = cv2.waitKey(1) & 0xFF
            if key == ord(' '): # Space bar
                img_original = frame
                print("Frame captured.")
                break
            elif key == ord('n'): # Changed from 's' to 'n' for next camera
                cap.release() # Release current camera
                current_camera_list_index = (current_camera_list_index + 1) % len(available_cameras)
                selected_camera_index = available_cameras[current_camera_list_index]
                
                cap = cv2.VideoCapture(selected_camera_index) # Try to open new camera
                if not cap.isOpened():
                    print(f"Error: Could not open camera with index {selected_camera_index}. Trying next available.")
                    # If new camera fails, try the next one in the list
                    # This loop ensures we find a working camera or exhaust all options
                    for _ in range(len(available_cameras)): # Prevent infinite loop
                        current_camera_list_index = (current_camera_list_index + 1) % len(available_cameras)
                        selected_camera_index = available_cameras[current_camera_list_index]
                        cap = cv2.VideoCapture(selected_camera_index)
                        if cap.isOpened():
                            break
                    if not cap.isOpened(): # If still not opened after trying all
                        print("No working camera found. Exiting calibration.")
                        cv2.destroyAllWindows()
                        return
                print(f"Switched to Camera Index: {selected_camera_index}")
                # Continue the loop with the new camera
            elif key == ord('q'):
                print("Quitting calibration.")
                cap.release()
                cv2.destroyAllWindows()
                return

        cap.release()
        cv2.destroyAllWindows()

        if img_original is None:
            print("No frame was captured. Exiting.")
            return

    roi_data["camera_index"] = selected_camera_index

    # --- No Chessboard Detection or Homography Calculation ---
    # All ROIs will be defined manually.
    print("All ROIs will be defined manually.")

    # --- ROI Definitions ---
    roi_names_to_define = [
        "PUTTING_MAT_ROI", "RAMP_ROI", "HOLE_ROI", # Define these first for inference
        "LEFT_OF_MAT_ROI", "CATCH_ROI", "RETURN_TRACK_ROI",
        "RAMP_LEFT_ROI", "RAMP_CENTER_ROI", "RAMP_RIGHT_ROI",
        "HOLE_TOP_ROI", "HOLE_RIGHT_ROI", "HOLE_LOW_ROI", "HOLE_LEFT_ROI",
        "IGNORE_AREA_ROI" # Added new ROI
    ]

    special_roi_configs = {
        "PUTTING_MAT_ROI": {
            "manual_points_needed": 4,
            "manual_prompt": "Click the 4 corners of the Putting Mat (Top-Left, Top-Right, Bottom-Right, Bottom-Left)."
        },
        "LEFT_OF_MAT_ROI": {
            "manual_points_needed": 4,
            "manual_prompt": "Click the 4 corners of the area left of the mat (Top-Left, Top-Right, Bottom-Right, Bottom-Left)."
        },
        "CATCH_ROI": {
            "manual_points_needed": 4,
            "manual_prompt": "Click the 4 corners of the Catch area (Top-Left, Top-Right, Bottom-Right, Bottom-Left)."
        },
        "RETURN_TRACK_ROI": {
            "manual_points_needed": 4,
            "manual_prompt": "Click the 4 corners of the Return Track (Top-Left, Top-Right, Bottom-Right, Bottom-Left)."
        },
        "HOLE_ROI": {
            "manual_points_needed": 12,
            "manual_prompt": "Click 12 points around the hole's circumference."
        },
        "RAMP_ROI": { "manual_points_needed": 4, "manual_prompt": "Click the 4 corners of the main Ramp ROI (Top-Left, Top-Right, Bottom-Right, Bottom-Left)." },
        "RAMP_LEFT_ROI": { "manual_points_needed": 0, "manual_prompt": "Inferred from RAMP_ROI and HOLE_ROI." },
        "RAMP_CENTER_ROI": { "manual_points_needed": 0, "manual_prompt": "Inferred from RAMP_ROI and HOLE_ROI." },
        "RAMP_RIGHT_ROI": { "manual_points_needed": 0, "manual_prompt": "Inferred from RAMP_ROI and HOLE_ROI." },
        "HOLE_TOP_ROI": { "manual_points_needed": 0, "manual_prompt": "Inferred from HOLE_ROI." },
        "HOLE_RIGHT_ROI": { "manual_points_needed": 0, "manual_prompt": "Inferred from HOLE_ROI." },
        "HOLE_LOW_ROI": { "manual_points_needed": 0, "manual_prompt": "Inferred from HOLE_ROI." },
        "HOLE_LEFT_ROI": { "manual_points_needed": 0, "manual_prompt": "Inferred from HOLE_ROI." },
        "IGNORE_AREA_ROI": { "manual_points_needed": 4, "manual_prompt": "Click the 4 corners of the area to ignore (Top-Left, Top-Right, Bottom-Right, Bottom-Left)." } # New ROI
    }

    # --- Main Calibration Loop ---
    cv2.namedWindow("Calibrate ROIs")
    cv2.setMouseCallback("Calibrate ROIs", mouse_callback)

    for name in roi_names_to_define:
        current_roi_name = name
        current_roi_points = []

        config = special_roi_configs.get(name, {})
        expected_manual_points = config.get("manual_points_needed", 3) # Default to 3 for standard ROIs
        manual_prompt = config.get("manual_prompt", f"Click at least 3 points for {name}.")

        print(f"\n>>> Defining: {current_roi_name} ({manual_prompt}) <<<")
        
        roi_completed = False
        while not roi_completed:
            temp_img = img_original.copy()

            # Draw existing ROIs
            for roi_name, data in roi_data.items():
                if roi_name == "camera_index" or roi_name == "perspective_matrix":
                    continue
                
                if roi_name == "HOLE_ROI" and isinstance(data, dict) and "points" in data:
                    # Draw the 12-point polygon for HOLE_ROI
                    pts = np.array(data["points"], np.int32)
                    if len(pts) > 0:
                        cv2.polylines(temp_img, [pts.reshape((-1, 1, 2))], True, (0, 255, 255), 3) # Yellow, thicker
                        cv2.putText(temp_img, roi_name, (pts[0][0], pts[0][1] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2) # Yellow, larger font

                elif data:
                    pts = np.array([p for p in data if p is not None], np.int32)
                    if len(pts) > 0:
                        cv2.polylines(temp_img, [pts.reshape((-1, 1, 2))], True, (0, 255, 255), 3) # Yellow, thicker
                        cv2.putText(temp_img, roi_name, (pts[0][0], pts[0][1] - 15), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2) # Yellow, larger font

            # Draw current ROI points
            valid_points = [p for p in current_roi_points if p is not None]
            for i, p in enumerate(valid_points):
                cv2.circle(temp_img, tuple(p), 5, (0, 255, 0), -1)
                if i > 0:
                    cv2.line(temp_img, tuple(valid_points[i-1]), tuple(valid_points[i]), (0, 255, 0), 2)

            # Display UI text
            cv2.putText(temp_img, f"Defining: {current_roi_name}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3) # Larger, thicker
            cv2.putText(temp_img, manual_prompt, (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 0), 2) # Larger, yellow
            cv2.putText(temp_img, "'x': Complete, 'c': Clear Last, 'r': Reset, 's': Save, 'q': Quit", (10, temp_img.shape[0] - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2) # Larger

            cv2.imshow("Calibrate ROIs", temp_img)
            key = cv2.waitKey(0) & 0xFF # Wait indefinitely for a key press
            print(f"Debug: Key pressed: {key}")

            # --- Key/Mouse Handling ---
            if _last_clicked_point:
                if expected_manual_points == 0:
                    print("No manual points needed for this ROI. Ignoring click.")
                elif len(current_roi_points) < expected_manual_points:
                    current_roi_points.append(_last_clicked_point)
                else:
                    print("All manual points already clicked for this ROI.")
                _last_clicked_point = None # Reset after processing

            elif key == ord('c'): # Clear last point
                if current_roi_points:
                    current_roi_points.pop()
                    print("Cleared last point.")

            elif key == ord('r'): # Reset ROI
                print(f"Resetting {current_roi_name}.")
                current_roi_points = []

            elif key == ord('x'): # Complete ROI
                print(f"Debug: Attempting to complete ROI {current_roi_name}")
                valid_points = [p for p in current_roi_points if p is not None]
                print(f"Debug: len(current_roi_points): {len(current_roi_points)}, expected_manual_points: {expected_manual_points}")
                
                if len(current_roi_points) == expected_manual_points:
                    roi_data[current_roi_name] = valid_points
                    print(f"Completed {current_roi_name} with {len(valid_points)} points.")
                    roi_completed = True

                else:
                    print(f"Please click all {expected_manual_points} manual points. Currently clicked: {len(current_roi_points)}")

            elif key == ord('s'): # Save progress
                save_rois_to_json(roi_data, img_original.shape[0], img_original.shape[1])

            elif key == ord('q'): # Quit
                print("Quitting calibration.")
                save_rois_to_json(roi_data, img_original.shape[0], img_original.shape[1])
                cv2.destroyAllWindows()
                return

    cv2.destroyAllWindows()
    print("All ROIs defined. Displaying final confirmation.")

    # Infer ramp ROIs after all manual ROIs are defined
    infer_ramp_rois(roi_data)
    infer_hole_quadrants(roi_data)
    save_rois_to_json(roi_data, img_original.shape[0], img_original.shape[1]) # Save again with inferred ROIs

    # --- New Interactive Final Confirmation Screen ---
    print("\n--- Final ROI Confirmation ---")
    print("Press SPACE to cycle forward, 'b' to cycle backward.")
    print("Press 's' to save and quit at any time.")
    print("Press 'q' to quit without saving.")

    confirmation_order = [
        "PUTTING_MAT_ROI", "RAMP_ROI", "RAMP_LEFT_ROI", "RAMP_CENTER_ROI", "RAMP_RIGHT_ROI",
        "HOLE_ROI", "HOLE_TOP_ROI", "HOLE_RIGHT_ROI", "HOLE_LOW_ROI", "HOLE_LEFT_ROI",
        "CATCH_ROI", "RETURN_TRACK_ROI", "LEFT_OF_MAT_ROI", "IGNORE_AREA_ROI"
    ]
    hole_quadrant_labels = {
        "HOLE_TOP_ROI": "TO", "HOLE_RIGHT_ROI": "RE",
        "HOLE_LOW_ROI": "LO", "HOLE_LEFT_ROI": "LE"
    }

    current_roi_index = 0
    while True:  # Loop indefinitely until user saves or quits
        final_display_img = img_original.copy()

        # Draw all ROIs, highlighting the current one
        for i, roi_name in enumerate(confirmation_order):
            data = roi_data.get(roi_name)
            if not data: continue

            pts = np.array([p for p in data if p is not None], np.int32)
            if len(pts) == 0: continue

            is_current = (i == current_roi_index)
            color = (0, 255, 255) if is_current else (255, 0, 255)  # Yellow if current, Magenta otherwise
            thickness = 3 if is_current else 2

            cv2.polylines(final_display_img, [pts.reshape((-1, 1, 2))], True, color, thickness)

            # Use abbreviated labels for hole quadrants and skip labeling for HOLE_ROI
            if roi_name != "HOLE_ROI":
                label = hole_quadrant_labels.get(roi_name, roi_name)
                M = cv2.moments(pts)
                if M["m00"] != 0:
                    cx = int(M["m10"] / M["m00"])
                    cy = int(M["m01"] / M["m00"])
                    cv2.putText(final_display_img, label, (cx - 20, cy + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color, 2)

        # Display instructions
        roi_to_confirm = confirmation_order[current_roi_index]
        cv2.putText(final_display_img, f"Confirming: {roi_to_confirm}", (10, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        cv2.putText(final_display_img, "SPACE: Next | b: Back | s: Save & Quit | q: Quit", (10, final_display_img.shape[0] - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 1)

        cv2.imshow("Final ROI Confirmation", final_display_img)
        key = cv2.waitKey(0) & 0xFF

        if key == ord(' '):  # Spacebar to go to the next ROI
            current_roi_index = (current_roi_index + 1) % len(confirmation_order)
        elif key == ord('b'):  # 'b' to go back
            current_roi_index = (current_roi_index - 1 + len(confirmation_order)) % len(confirmation_order)
        elif key == ord('s'):
            save_rois_to_json(roi_data, img_original.shape[0], img_original.shape[1])
            print("ROI configuration saved. Exiting.")
            break
        elif key == ord('q'):
            print("Quitting without saving. Exiting.")
            break

    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
