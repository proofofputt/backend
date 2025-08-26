# Technical Report: Diagnosis and Fix for Session Start Failures

**Date:** 2023-10-27
**Author:** Gemini Code Assist
**Status:** For Review & Implementation

---

## 1. Executive Summary

The "Start New Session" and "Start Duel Session" features are currently non-functional due to critical structural errors within the `run_tracker.py` script. The root cause is a significant duplication of initialization code within the script's `main()` function, likely the result of an incorrect version control merge. This duplication leads to an unstable and incorrect execution flow, preventing sessions from starting.

This document provides a diagnosis of the problem and a clear, multi-step plan to refactor the code, restore functionality, and properly implement duel session logic.

## 2. Root Cause Analysis

When a user starts a session, the `api.py` backend correctly launches `run_tracker.py` as a separate process. However, an inspection of `run_tracker.py` reveals that the `main()` function contains a large, duplicated block of code.

**Key Issues Identified:**

*   **Redundant Initialization:** Critical components like `VideoProcessor`, `PuttClassifier`, and `cv2.VideoCapture` are instantiated twice. This is inefficient and can lead to resource conflicts (e.g., trying to open the same camera twice).
*   **State Corruption:** Variables are declared and initialized at the top of the function, only to be re-declared and re-initialized again inside a nested `try` block. This completely nullifies the initial setup, including the parsing of command-line arguments like `video_path` or `camera_index`.
*   **Incorrect Execution Flow:** The main processing loop (`while True:`) is buried inside the second, duplicated block. This makes the first block of initializations effectively dead code and creates a confusing and error-prone structure.

The presence of this duplicated code is the definitive reason for the failure. The script cannot reliably initialize and run the tracker.

## 3. Step-by-Step Resolution Plan

The following steps should be executed in order to resolve the issue. This is a hand-off document for the development team.

### Step 1: Refactor `run_tracker.py` to Remove Duplication

The highest priority is to clean up the `main()` function in `run_tracker.py`.

1.  **Identify the duplicated code block:** Locate the second block of code that re-initializes `video_processor`, `putt_classifier`, `cap`, etc., starting from the first nested `try:` statement inside the `main` function.
2.  **Delete the entire duplicated block:** This includes the `try:` statement that encloses it and all the re-initializations down to the second `overall_detected_ball_center = None` line.
3.  **Consolidate the main loop:** Ensure the `try...while True:` block that contains the core frame processing logic is located at the top level of the function, immediately after the single, correct block of initializations.

### Step 2: Correctly Implement Duel Session Logic

Currently, the system is not wired to pass a `duel_id` from the frontend to the tracker script.

1.  **Update `api.py`:** Modify the `/start-session` endpoint. It should check for an optional `duel_id` in the JSON payload from the frontend. If present, this `duel_id` must be passed as a command-line argument (`--duel_id`) to the `subprocess.Popen` call that starts `run_tracker.py`.
2.  **Update `run_tracker.py`:** At the end of a session (i.e., when the `while` loop breaks or the script exits), check if `args.duel_id` was provided. If it was, use the existing `submit_duel_session` helper function to post the session results to the API. This will link the session to the duel in the database.

## 4. Conclusion

The session start failure is a direct result of a severe but straightforward structural problem in `run_tracker.py`. By executing the refactoring plan outlined above, the code duplication will be eliminated, restoring the correct execution flow. Further implementing the duel session logic will complete the feature as intended. This will create a stable and maintainable foundation for the tracker's functionality.