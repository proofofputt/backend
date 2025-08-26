import cv2
import numpy as np
import time

class PuttStatus:
    WAITING = "Waiting for Putt"
    PUTT_IN_PROGRESS = "Putt in Progress"
    AWAITING_RETURN = "Awaiting Return"
    BALL_IN_CATCH = "Ball in Catch Area"
    BALL_IN_HOLE = "Ball in Hole"

class PuttClassifier:
    # Time constants for refined classification
    SHORT_MAKE_THRESHOLD = 0.5  # seconds for quick direct makes
    MISS_CATCH_THRESHOLD = 0.5  # seconds for confirming catch entry
    MAKE_TIME_WINDOW = 0.5      # seconds for catch -> ramp -> hole sequence
    CATCH_TO_RETURN_THRESHOLD = 1.2  # seconds for catch to return track

    def __init__(self, yolo_model, rois, logger, ramp_exit_timeout=3.0):
        self.logger = logger
        self.model = yolo_model
        self.rois = {}
        for name, data in rois.items():
            if name == "camera_index":
                self.rois[name] = data
            elif isinstance(data, dict) and 'points' in data:
                self.rois[name] = np.array(data['points'], dtype=np.int32)
            else:
                self.rois[name] = np.array(data, dtype=np.int32)
        self.RAMP_EXIT_TIMEOUT = ramp_exit_timeout

        self.current_state = PuttStatus.WAITING
        self.putt_start_time = 0
        self.ramp_entry_time = 0
        self.ball_on_mat_initially = False
        self.catch_entry_time = 0
        self.hole_entry_time = 0
        self.has_crossed_catch_roi = False
        self.ramp_exit_time = 0
        self.has_entered_hole = False
        self.last_ramp_reentry_time = 0  # Track re-entry to ramp after catch

        # ROI entry counters
        self.hole_entry_count = 0
        self.ramp_entry_count = 0
        self.putting_mat_entry_count = 0
        self.catch_entry_count = 0
        self.left_of_mat_entry_count = 0

        # Previous frame ROI states
        self.prev_ball_in_hole = False
        self.prev_ball_in_ramp = False
        self.prev_ball_in_putting_mat = False
        self.prev_ball_in_catch = False
        self.prev_ball_in_left_of_mat = False
        self.prev_ball_in_hole_top = False
        self.prev_ball_in_hole_right = False
        self.prev_ball_in_hole_low = False
        self.prev_ball_in_hole_left = False
        self.prev_ball_in_ramp_left = False
        self.prev_ball_in_ramp_center = False
        self.prev_ball_in_ramp_right = False
        self.prev_ball_in_return_track = False
        self.previous_putt_classified_as_returned = False # New state variable

        # Metrics for consecutive makes
        self.total_makes = 0
        self.total_misses = 0
        self.current_consecutive_makes = 0
        self.max_consecutive_makes = 0

        # For transition tracking
        self.transition_history = []
        self.previous_roi = None
        self.previous_ramp_roi = None
        self.first_hole_entry_roi = None
        self.first_ramp_entry_roi = None
        self.first_ramp_sub_roi = None
        self.last_ramp_exit_roi = None
        self.last_ramp_sub_roi = None # To track the last specific ramp part
        self.last_ramp_exit_time = 0
        self.ball_was_on_mat = False
        self.last_mat_time = 0
        self.is_classified_and_logged = False

    def _check_bbox_intersection_roi(self, bbox, roi):
        # bbox is (x1, y1, x2, y2)
        # roi is a list of points forming a polygon
        if len(roi) == 0:
            return False

        # Create a polygon from the bounding box corners
        bbox_poly = np.array([
            [bbox[0], bbox[1]],
            [bbox[2], bbox[1]],
            [bbox[2], bbox[3]],
            [bbox[0], bbox[3]]
        ], dtype=np.int32)

        # Check if any corner of the bbox is inside the ROI
        for i in range(4):
            if cv2.pointPolygonTest(roi, (int(bbox_poly[i][0]), int(bbox_poly[i][1])), False) >= 0:
                return True
        
        # Check if the center of the bbox is inside the ROI
        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        if cv2.pointPolygonTest(roi, (int(center_x), int(center_y)), False) >= 0:
            return True

        # Check if any corner of the ROI is inside the bbox
        # This is important for cases where the ROI is small and entirely within the bbox
        for p in roi:
            if bbox[0] <= p[0] <= bbox[2] and bbox[1] <= p[1] <= bbox[3]:
                return True

        return False

    def _check_point_in_roi(self, point, roi):
        if len(roi) == 0:
            return False
        return cv2.pointPolygonTest(roi, (int(point[0]), int(point[1])), False) >= 0

    def update_and_classify(self, frame, detected_balls, current_frame_time):
        self.logger.debug(f"--- Frame {current_frame_time:.2f}s ---")

        # --- Process Detected Balls ---

        # Initialize ROI states and ball center
        self.ball_in_return_track = False
        ball_in_ramp = False
        ball_in_putting_mat = False
        ball_in_left_of_mat = False
        ball_in_catch = False
        ball_in_hole = False
        ball_in_hole_top = False
        ball_in_hole_right = False
        ball_in_hole_low = False
        ball_in_hole_left = False
        ball_in_ramp_left = False
        ball_in_ramp_center = False
        ball_in_ramp_right = False
        overall_detected_ball_center = None
        transition_history = [] # Initialize transition_history

        # Define ROI processing order based on state
        if self.current_state == PuttStatus.WAITING:
            # When waiting for a new putt, prioritize the mat. Ignore balls from previous putts.
            roi_priority = [
                ("PUTTING_MAT_ROI", "ball_in_putting_mat"),
                ("LEFT_OF_MAT_ROI", "ball_in_left_of_mat"),
                ("RAMP_LEFT_ROI", "ball_in_ramp_left"),
                ("RAMP_CENTER_ROI", "ball_in_ramp_center"),
                ("RAMP_RIGHT_ROI", "ball_in_ramp_right"),
                ("RAMP_ROI", "ball_in_ramp"),
                ("CATCH_ROI", "ball_in_catch"),
                ("HOLE_TOP_ROI", "ball_in_hole_top"),
                ("HOLE_RIGHT_ROI", "ball_in_hole_right"),
                ("HOLE_LOW_ROI", "ball_in_hole_low"),
                ("HOLE_LEFT_ROI", "ball_in_hole_left"),
                ("HOLE_ROI", "ball_in_hole"),
                ("RETURN_TRACK_ROI", "ball_in_return_track"),
            ]
        else: # Putt is in progress
            # Prioritize the ROIs that are part of an active putt
            roi_priority = [
                ("HOLE_TOP_ROI", "ball_in_hole_top"),
                ("HOLE_RIGHT_ROI", "ball_in_hole_right"),
                ("HOLE_LOW_ROI", "ball_in_hole_low"),
                ("HOLE_LEFT_ROI", "ball_in_hole_left"),
                ("HOLE_ROI", "ball_in_hole"),
                ("RETURN_TRACK_ROI", "ball_in_return_track"),
                ("CATCH_ROI", "ball_in_catch"),
                ("RAMP_LEFT_ROI", "ball_in_ramp_left"),
                ("RAMP_CENTER_ROI", "ball_in_ramp_center"),
                ("RAMP_RIGHT_ROI", "ball_in_ramp_right"),
                ("RAMP_ROI", "ball_in_ramp"),
                ("PUTTING_MAT_ROI", "ball_in_putting_mat"),
                ("LEFT_OF_MAT_ROI", "ball_in_left_of_mat"),
            ]

        # Process detected balls
        primary_ball = None
        highest_priority_roi_for_frame = None # Initialize here
        if detected_balls:
            # Sort by confidence to prioritize more confident detections
            detected_balls.sort(key=lambda x: x[6], reverse=True) 
            
            # Find the primary ball for classification
            primary_ball_candidates = []
            for ball_data in detected_balls:
                scaled_center_x, scaled_center_y, scaled_x1, scaled_y1, scaled_x2, scaled_y2, confidence = ball_data
                detected_center = (int(scaled_center_x), int(scaled_center_y))

                # Check if the detected ball is in the ignore ROI
                if self._check_point_in_roi(detected_center, self.rois["IGNORE_AREA_ROI"]):
                    self.logger.debug(f"Ignoring ball in IGNORE_AREA_ROI at {detected_center}")
                    continue # Skip this detected ball

                # Prioritize balls in PUTTING_MAT_ROI or RAMP_ROI when WAITING
                if self.current_state == PuttStatus.WAITING:
                    if self._check_point_in_roi(detected_center, self.rois["PUTTING_MAT_ROI"]):
                        primary_ball_candidates.append((ball_data, "PUTTING_MAT_ROI"))
                    elif self._check_point_in_roi(detected_center, self.rois["RAMP_ROI"]):
                        primary_ball_candidates.append((ball_data, "RAMP_ROI"))
                else:
                    # When in progress, any ROI is a candidate, sorted by priority
                    for roi_name, flag_name in roi_priority:
                        is_in_roi = self._check_point_in_roi(detected_center, self.rois[roi_name])
                        if is_in_roi:
                            primary_ball_candidates.append((ball_data, roi_name))
                            break # Found a primary ball in a prioritized ROI
            
            # Create a priority map for faster, cleaner sorting
            roi_priority_map = {roi_name: i for i, (roi_name, _) in enumerate(roi_priority)}

            if primary_ball_candidates:
                # Sort candidates: first by state priority, then by confidence
                if self.current_state == PuttStatus.WAITING:
                    # For WAITING, prioritize PUTTING_MAT_ROI then RAMP_ROI
                    primary_ball_candidates.sort(key=lambda x: (x[1] != "PUTTING_MAT_ROI", x[1] != "RAMP_ROI", -x[0][6]))
                else:
                    primary_ball_candidates.sort(key=lambda x: (roi_priority_map.get(x[1], len(roi_priority)), -x[0][6]))
                
                primary_ball = primary_ball_candidates[0][0] # Get the ball_data tuple
                highest_priority_roi_for_frame = primary_ball_candidates[0][1] # Get the ROI name
            else:
                primary_ball = None
                highest_priority_roi_for_frame = None

            # If no ball found in any prioritized ROI, pick the most confident one overall (if any)
            if not primary_ball and detected_balls:
                primary_ball = detected_balls[0] # Already sorted by confidence
                highest_priority_roi_for_frame = "UNKNOWN_ROI" # Indicate it's not in a specific prioritized ROI

            if primary_ball:
                scaled_center_x, scaled_center_y, scaled_x1, scaled_y1, scaled_x2, scaled_y2, confidence = primary_ball
                overall_detected_ball_center = (int(scaled_center_x), int(scaled_center_y))
                detected_bbox = (int(scaled_x1), int(scaled_y1), int(scaled_x2), int(scaled_y2))

                # Draw bounding box and center for the primary ball
                cv2.rectangle(frame, (int(scaled_x1), int(scaled_y1)), (int(scaled_x2), int(scaled_y2)), (0, 255, 0), 2)
                cv2.circle(frame, overall_detected_ball_center, 5, (0, 0, 255), -1)

                # Update ROI flags for the primary ball
                # Check all relevant ROIs for the primary ball
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["HOLE_TOP_ROI"]):
                    ball_in_hole_top = True
                    if self.first_hole_entry_roi is None:
                        self.first_hole_entry_roi = "HOLE_TOP_ROI"
                        self.transition_history.append(f"Entered HOLE_TOP_ROI at {current_frame_time:.2f}s")
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["HOLE_RIGHT_ROI"]):
                    ball_in_hole_right = True
                    if self.first_hole_entry_roi is None:
                        self.first_hole_entry_roi = "HOLE_RIGHT_ROI"
                        self.transition_history.append(f"Entered HOLE_RIGHT_ROI at {current_frame_time:.2f}s")
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["HOLE_LOW_ROI"]):
                    ball_in_hole_low = True
                    if self.first_hole_entry_roi is None:
                        self.first_hole_entry_roi = "HOLE_LOW_ROI"
                        self.transition_history.append(f"Entered HOLE_LOW_ROI at {current_frame_time:.2f}s")
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["HOLE_LEFT_ROI"]):
                    ball_in_hole_left = True
                    if self.first_hole_entry_roi is None:
                        self.first_hole_entry_roi = "HOLE_LEFT_ROI"
                        self.transition_history.append(f"Entered HOLE_LEFT_ROI at {current_frame_time:.2f}s")
                if self._check_bbox_intersection_roi(detected_bbox, self.rois["HOLE_ROI"]):
                    ball_in_hole = True
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["RETURN_TRACK_ROI"]):
                    self.ball_in_return_track = True
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["CATCH_ROI"]):
                    ball_in_catch = True
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["RAMP_LEFT_ROI"]):
                    ball_in_ramp_left = True
                    self.last_ramp_sub_roi = "RAMP_LEFT_ROI"
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["RAMP_CENTER_ROI"]):
                    ball_in_ramp_center = True
                    self.last_ramp_sub_roi = "RAMP_CENTER_ROI"
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["RAMP_RIGHT_ROI"]):
                    ball_in_ramp_right = True
                    self.last_ramp_sub_roi = "RAMP_RIGHT_ROI"
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["RAMP_ROI"]):
                    ball_in_ramp = True
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["PUTTING_MAT_ROI"]):
                    ball_in_putting_mat = True
                    self.ball_was_on_mat = True
                    self.last_mat_time = current_frame_time
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["LEFT_OF_MAT_ROI"]):
                    ball_in_left_of_mat = True

                # Update transition history for ramp ROIs
                if self.current_state == PuttStatus.PUTT_IN_PROGRESS:
                    current_ramp_sub_roi = None
                    if ball_in_ramp_left:
                        current_ramp_sub_roi = "RAMP_LEFT_ROI"
                    elif ball_in_ramp_center:
                        current_ramp_sub_roi = "RAMP_CENTER_ROI"
                    elif ball_in_ramp_right:
                        current_ramp_sub_roi = "RAMP_RIGHT_ROI"

                    if current_ramp_sub_roi and self.first_ramp_entry_roi is None:
                        self.first_ramp_entry_roi = current_ramp_sub_roi
                        self.transition_history.append(f"Entered {current_ramp_sub_roi} at {current_frame_time:.2f}s")

                    if self.previous_roi and "RAMP" in self.previous_roi and not current_ramp_sub_roi and self.previous_roi != "RAMP_ROI":
                        self.last_ramp_exit_roi = self.previous_roi
                        self.transition_history.append(f"Exited {self.previous_roi} at {current_frame_time:.2f}s")
                    
                    if current_ramp_sub_roi:
                        self.previous_roi = current_ramp_sub_roi
                    elif ball_in_putting_mat:
                        self.previous_roi = "PUTTING_MAT_ROI"
                    elif ball_in_left_of_mat:
                        self.previous_roi = "LEFT_OF_MAT_ROI"
                    elif ball_in_hole:
                        self.previous_roi = "HOLE_ROI"
                    elif self.ball_in_return_track:
                        self.previous_roi = "RETURN_TRACK_ROI"
                    elif ball_in_catch:
                        self.previous_roi = "CATCH_ROI"
                    else:
                        self.previous_roi = None # Ball is not in any tracked ROI

                self.logger.debug(f"Primary ball detected at {overall_detected_ball_center}. ROI states: PUTTING_MAT_ROI={ball_in_putting_mat}, RAMP_ROI={ball_in_ramp}, LEFT_OF_MAT_ROI={ball_in_left_of_mat}, HOLE_ROI={ball_in_hole}, CATCH_ROI={ball_in_catch}, RETURN_TRACK_ROI={self.ball_in_return_track}")
            else:
                self.logger.debug("No primary ball detected in this frame.")

        ball_in_hole = ball_in_hole_top or ball_in_hole_right or ball_in_hole_low or ball_in_hole_left

        # --- Quick Putt Detection ---
        # A "Quick Putt" occurs if a new putt starts (ball enters ramp from mat)
        # while the previous putt has not yet returned to the return track.
        if self.current_state == PuttStatus.WAITING and ball_in_ramp and \
           not self.previous_putt_classified_as_returned and not self.ball_in_return_track and \
           ball_in_left_of_mat: # New putt entered left of mat
            
            classification = "MISS"
            detailed_classification = "MISS - QUICK PUTT"
            self.logger.debug(f"QUICK PUTT detected at {current_frame_time:.2f}s. Previous putt not returned.")
            self.current_consecutive_makes = 0
            # self.total_misses += 1 # Handled by run_tracker.py
            self.current_state = PuttStatus.WAITING # Reset state
            self.prepare_for_new_putt() # Reset putt-specific variables
            self.is_classified_and_logged = True # Mark as classified for logging
            
            # Return immediately as this putt is classified
            return self.current_state, classification, detailed_classification, overall_detected_ball_center, \
                   ball_in_putting_mat, ball_in_ramp, self.ball_in_return_track, ball_in_left_of_mat, \
                   ball_in_catch, ball_in_hole, ball_in_hole_top, ball_in_hole_right, \
                   ball_in_hole_low, ball_in_hole_left, ball_in_ramp_left, ball_in_ramp_center, \
                   ball_in_ramp_right, transition_history

        # Update ROI entry counts
        if self.current_state == PuttStatus.PUTT_IN_PROGRESS:
            if ball_in_hole and not self.prev_ball_in_hole:
                self.hole_entry_count += 1
                self.logger.debug(f"Ball entered HOLE_ROI #{self.hole_entry_count} at {current_frame_time:.2f}s")
                if overall_detected_ball_center:
                    if self._check_point_in_roi(overall_detected_ball_center, self.rois["HOLE_TOP_ROI"]):
                        self.first_hole_entry_roi = "HOLE_TOP_ROI"
                    elif self._check_point_in_roi(overall_detected_ball_center, self.rois["HOLE_RIGHT_ROI"]):
                        self.first_hole_entry_roi = "HOLE_RIGHT_ROI"
                    elif self._check_point_in_roi(overall_detected_ball_center, self.rois["HOLE_LOW_ROI"]):
                        self.first_hole_entry_roi = "HOLE_LOW_ROI"
                    elif self._check_point_in_roi(overall_detected_ball_center, self.rois["HOLE_LEFT_ROI"]):
                        self.first_hole_entry_roi = "HOLE_LEFT_ROI"
                    else:
                        self.first_hole_entry_roi = "UNKNOWN_HOLE_QUADRANT" # Fallback
                    self.transition_history.append(f"Entered {self.first_hole_entry_roi} at {current_frame_time:.2f}s")

            if ball_in_ramp and not self.prev_ball_in_ramp:
                self.ramp_entry_count += 1
                self.logger.debug(f"Ball entered RAMP_ROI #{self.ramp_entry_count} at {current_frame_time:.2f}s")
            if ball_in_putting_mat and not self.prev_ball_in_putting_mat:
                self.putting_mat_entry_count += 1
                self.logger.debug(f"Ball entered PUTTING_MAT_ROI #{self.putting_mat_entry_count} at {current_frame_time:.2f}s")
            if ball_in_catch and not self.prev_ball_in_catch:
                self.catch_entry_count += 1
                self.logger.debug(f"Ball entered CATCH_ROI #{self.catch_entry_count} at {current_frame_time:.2f}s")
            if ball_in_left_of_mat and not self.prev_ball_in_left_of_mat:
                self.left_of_mat_entry_count += 1
                self.logger.debug(f"Ball entered LEFT_OF_MAT_ROI #{self.left_of_mat_entry_count} at {current_frame_time:.2f}s")

        # State Machine Logic
        classification = ""
        detailed_classification = ""

        if self.current_state == PuttStatus.WAITING:
            # Timeout for the ball_was_on_mat flag
            if self.ball_was_on_mat and (current_frame_time - self.last_mat_time) > 1.0: # 1 second timeout
                self.ball_was_on_mat = False

            if self.ball_was_on_mat and ball_in_ramp:
                # Ball was on mat and is now on the ramp, initiate putt
                self.current_state = PuttStatus.PUTT_IN_PROGRESS
                self.logger.debug(f"New Putt Started at {current_frame_time:.2f}s (Mat to Ramp)")
                self.putt_start_time = current_frame_time
                self.ramp_entry_time = current_frame_time # Record ramp entry time
                
                # Determine the specific ramp entry ROI name for classification output
                if self._check_point_in_roi(overall_detected_ball_center, self.rois["RAMP_LEFT_ROI"]):
                    self.first_ramp_entry_roi = "RAMP_LEFT_ROI"
                elif self._check_point_in_roi(overall_detected_ball_center, self.rois["RAMP_CENTER_ROI"]):
                    self.first_ramp_entry_roi = "RAMP_CENTER_ROI"
                elif self._check_point_in_roi(overall_detected_ball_center, self.rois["RAMP_RIGHT_ROI"]):
                    self.first_ramp_entry_roi = "RAMP_RIGHT_ROI"
                else:
                    self.first_ramp_entry_roi = "RAMP_ROI" # Fallback if not in a specific sub-ROI

                self.logger.debug(f"First ramp entry ROI: {self.first_ramp_entry_roi}")

        elif self.current_state == PuttStatus.AWAITING_RETURN:
            self.logger.debug(f"Current State: {self.current_state}")
            # If the returning ball is no longer in the return track, transition back to WAITING
            if not self.ball_in_return_track and self.prev_ball_in_return_track:
                self.logger.debug(f"Ball exited return track at {current_frame_time:.2f}s. Transitioning to WAITING.")
                self.current_state = PuttStatus.WAITING

        elif self.current_state == PuttStatus.PUTT_IN_PROGRESS:
            self.logger.debug(f"Current State: {self.current_state}")
            self.logger.debug(f"has_entered_hole: {self.has_entered_hole}, ball_in_return_track: {self.ball_in_return_track}, has_crossed_catch_roi: {self.has_crossed_catch_roi}")
            self.logger.debug(f"ramp_exit_time: {self.ramp_exit_time}, catch_entry_time: {self.catch_entry_time}, ramp_entry_time: {self.ramp_entry_time}")
            # Update entry times for ROIs
            if overall_detected_ball_center and ball_in_ramp and self.ramp_entry_time == 0:
                self.ramp_entry_time = current_frame_time
                self.logger.debug(f"Ball entered RAMP_ROI at {self.ramp_entry_time:.2f}s")

            if overall_detected_ball_center and ball_in_catch and self.catch_entry_time == 0:
                self.catch_entry_time = current_frame_time
                self.has_crossed_catch_roi = True # Set the flag here
                self.logger.debug(f"Ball entered CATCH_ROI at {self.catch_entry_time:.2f}s")

            if overall_detected_ball_center and ball_in_hole and self.hole_entry_time == 0:
                self.hole_entry_time = current_frame_time
                self.has_entered_hole = True
                self.logger.debug(f"Ball entered HOLE_ROI at {self.hole_entry_time:.2f}s")

            # Track ramp exit time
            if self.prev_ball_in_ramp and not ball_in_ramp:
                self.ramp_exit_time = current_frame_time
                self.logger.debug(f"Ball exited RAMP_ROI at {self.ramp_exit_time:.2f}s")

            # --- Classification Logic ---
            temp_classification = ""
            temp_detailed_classification = ""

            # Create consistently formatted strings for detailed classification
            entry_roi_str = str(self.first_ramp_entry_roi).replace('_ROI', '').replace('RAMP_', '') if self.first_ramp_entry_roi else "UNKNOWN"
            exit_roi_str = str(self.last_ramp_sub_roi).replace('_ROI', '').replace('RAMP_', '') if self.last_ramp_sub_roi else "UNKNOWN"
            hole_entry_str = str(self.first_hole_entry_roi).replace('_ROI', '').replace('HOLE_', '') if self.first_hole_entry_roi else "UNKNOWN"

            # --- Classification Logic ---
            # The order of these checks is important for accuracy.

            # MISS - RETURN: Ball has returned to the mat after the putt was initiated.
            # This is a high-priority check to terminate the current putt attempt.
            # A small delay is used to prevent false triggers at the very start of the putt.
            if (ball_in_putting_mat or ball_in_left_of_mat) and (current_frame_time - self.putt_start_time > 0.25):
                temp_classification = "MISS"
                temp_detailed_classification = f"MISS - RETURN: {entry_roi_str} - {exit_roi_str}"
                self.logger.debug(f"MISS (Return) triggered at {current_frame_time:.2f}s. Ball re-entered mat from ramp.")
                self.current_consecutive_makes = 0
                # self.total_misses += 1 # Handled by run_tracker.py
                self.current_state = PuttStatus.WAITING
                self.prepare_for_new_putt()
                self.is_classified_and_logged = True
                self.previous_putt_classified_as_returned = True # Mark previous putt as returned
                classification = temp_classification
                detailed_classification = temp_detailed_classification

            # MAKE condition: Ball enters hole and then return track, without crossing catch ROI
            elif self.has_entered_hole and self.ball_in_return_track and not self.has_crossed_catch_roi:
                temp_classification = "MAKE"
                temp_detailed_classification = f"MAKE - HOLE: {hole_entry_str} - {entry_roi_str}"
                self.logger.debug(f"Direct MAKE triggered at {current_frame_time:.2f}s. Time in hole: {current_frame_time - self.hole_entry_time:.2f}s")
                # self.total_makes += 1 # Handled by run_tracker.py
                self.current_consecutive_makes += 1
                if self.current_consecutive_makes > self.max_consecutive_makes:
                    self.max_consecutive_makes = self.current_consecutive_makes
                self.current_state = PuttStatus.AWAITING_RETURN # Transition to AWAITING_RETURN
                self.prepare_for_new_putt() # Reset putt-specific variables
                self.is_classified_and_logged = True
                self.previous_putt_classified_as_returned = True # Mark previous putt as returned
                classification = temp_classification
                detailed_classification = temp_detailed_classification

            # MISS - Return from Catch: Ball enters catch, then return track
            elif self.ball_in_return_track and self.has_crossed_catch_roi:
                temp_classification = "MISS"
                temp_detailed_classification = f"MISS - CATCH: {entry_roi_str} - {exit_roi_str}"
                self.logger.debug(f"MISS (Return from Catch) triggered at {current_frame_time:.2f}s. Ball returned from catch area.")
                self.current_consecutive_makes = 0
                # self.total_misses += 1 # Handled by run_tracker.py
                self.current_state = PuttStatus.AWAITING_RETURN # Transition to AWAITING_RETURN
                self.prepare_for_new_putt()
                self.is_classified_and_logged = True
                self.previous_putt_classified_as_returned = True # Mark previous putt as returned
                classification = temp_classification
                detailed_classification = temp_detailed_classification

            # MISS - Timeout: Ball leaves RAMP_ROI and doesn't reach subsequent ROIs in time
            elif self.ramp_exit_time > 0 and not self.ball_in_return_track and (current_frame_time - self.ramp_exit_time) > self.RAMP_EXIT_TIMEOUT:
                temp_classification = "MISS"
                temp_detailed_classification = f"MISS - TIMEOUT: {entry_roi_str}"
                self.logger.debug(f"MISS (Timeout) triggered at {current_frame_time:.2f}s. Time since ramp exit: {current_frame_time - self.ramp_exit_time:.2f}s")
                self.current_consecutive_makes = 0
                # self.total_misses += 1 # Handled by run_tracker.py
                self.current_state = PuttStatus.WAITING # Transition to WAITING
                self.prepare_for_new_putt()
                self.is_classified_and_logged = True
                classification = temp_classification
                detailed_classification = temp_detailed_classification

        

        

        # Update previous frame ROI states at the very end of the function
        self.prev_ball_in_hole = ball_in_hole
        self.prev_ball_in_ramp = ball_in_ramp
        self.prev_ball_in_putting_mat = ball_in_putting_mat
        self.prev_ball_in_catch = ball_in_catch
        self.prev_ball_in_left_of_mat = ball_in_left_of_mat
        self.prev_ball_in_hole_top = ball_in_hole_top
        self.prev_ball_in_hole_right = ball_in_hole_right
        self.prev_ball_in_hole_low = ball_in_hole_low
        self.prev_ball_in_hole_left = ball_in_hole_left
        self.prev_ball_in_ramp_left = ball_in_ramp_left
        self.prev_ball_in_ramp_center = ball_in_ramp_center
        self.prev_ball_in_ramp_right = ball_in_ramp_right
        self.prev_ball_in_return_track = self.ball_in_return_track # Update new prev state

        self.logger.debug(f"Returning classification: '{classification}', detailed: '{detailed_classification}'")
        return self.current_state, classification, detailed_classification, overall_detected_ball_center, \
               ball_in_putting_mat, ball_in_ramp, self.ball_in_return_track, ball_in_left_of_mat, \
               ball_in_catch, ball_in_hole, ball_in_hole_top, ball_in_hole_right, \
               ball_in_hole_low, ball_in_hole_left, ball_in_ramp_left, ball_in_ramp_center, \
               ball_in_ramp_right, transition_history

    def prepare_for_new_putt(self):
        self.logger.debug("Preparing for new putt...")
        self.current_state = PuttStatus.WAITING # Always reset to WAITING
        self.putt_start_time = 0
        self.ramp_entry_time = 0
        self.ball_on_mat_initially = False
        self.catch_entry_time = 0
        self.hole_entry_time = 0
        self.has_crossed_catch_roi = False
        self.ramp_exit_time = 0
        self.has_entered_hole = False
        self.hole_entry_count = 0
        self.ramp_entry_count = 0
        self.putting_mat_entry_count = 0
        self.catch_entry_count = 0
        self.left_of_mat_entry_count = 0
        self.transition_history = []
        self.previous_roi = None
        self.previous_ramp_roi = None
        self.first_hole_entry_roi = None
        self.first_ramp_entry_roi = None
        self.last_ramp_exit_roi = None
        self.last_ramp_sub_roi = None # Reset the new variable
        self.ball_was_on_mat = False
        self.last_mat_time = 0
        self.is_classified_and_logged = False
        self.previous_putt_classified_as_returned = False # Reset for new putt