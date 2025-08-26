import cv2
from ultralytics import YOLO

class VideoProcessor:
    def __init__(self, model_path, min_bbox_area=50):
        """
        Initializes the VideoProcessor with the YOLO model.

        Args:
            model_path (str): The path to the YOLOv8 model file (e.g., 'best.pt').
            min_bbox_area (int): The minimum area of a bounding box to be considered a valid detection.
        """
        self.model = YOLO(model_path)
        # These are placeholders; they will be updated by the first frame processed.
        self.original_width = 1920
        self.original_height = 1080
        self.min_bbox_area = min_bbox_area

    def process_frame(self, frame):
        """
        Processes a single frame to detect golf balls.

        Args:
            frame: The video frame (as a NumPy array) to process.

        Returns:
            A list of tuples, where each tuple contains the detected ball's
            center coordinates, bounding box, and confidence score.
        """
        # Update frame dimensions from the first frame
        if self.original_height != frame.shape[0] or self.original_width != frame.shape[1]:
            self.original_height, self.original_width = frame.shape[:2]

        results = self.model(frame, verbose=False)
        detected_balls = []

        for r in results:
            for box in r.boxes:
                if box.cls == 0:  # Assuming class 0 is 'golf_ball'
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy()
                    w, h = x2 - x1, y2 - y1
                    if w * h >= self.min_bbox_area:
                        center_x, center_y = (x1 + x2) / 2, (y1 + y2) / 2
                        confidence = box.conf[0].cpu().numpy()
                        detected_balls.append((center_x, center_y, x1, y1, x2, y2, confidence))

        return detected_balls
