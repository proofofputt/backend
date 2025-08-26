import sys
import os

# Print the Python version and executable path to confirm which one is being used
print(f"--- Python Environment ---")
print(f"Executable: {sys.executable}")
print(f"Version: {sys.version}")

# Print the paths Python will search for modules
print(f"\n--- Python Search Paths (sys.path) ---")
for path in sys.path:
    print(f"- {path}")

# Check if the project directory is in the path
project_dir = os.path.dirname(os.path.abspath(__file__))
print(f"\n--- Project Directory Check ---")
print(f"Current project directory: {project_dir}")

# Now, try the import
try:
    print("\n--- Import Test ---")
    print("Attempting: from video_processor import VideoProcessor")
    from video_processor import VideoProcessor
    print("\nSUCCESS: 'VideoProcessor' was imported successfully.")
    print(f"Type of imported object: {type(VideoProcessor)}")
except ImportError as e:
    print(f"\nFAILURE: The import failed. This confirms the issue is with the environment or file access.")
    print(f"Error: {e}")