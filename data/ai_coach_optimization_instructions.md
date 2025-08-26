# AI Coach Optimization: On-Demand Insight Generation

This document outlines the necessary changes to optimize the AI Coach feature, ensuring that daily insights are generated only when explicitly requested by the user, thereby avoiding unnecessary resource consumption (e.g., Gemini API calls, server processing).

## 1. `api.py` Modifications

### 1.1. Remove Automatic Trigger from `login()` function

Locate the `login()` function in `api.py`. Remove the line that asynchronously triggers the `_create_daily_ai_chat_if_needed` function.

**Before:**
```python
@app.route('/login', methods=['POST'])
def login():
    # ... existing code ...
    if player_id is not None:
        # Asynchronously trigger the daily AI chat creation check
        thread = threading.Thread(target=_create_daily_ai_chat_if_needed, args=(player_id,))
        thread.start()
        # ... rest of login success response ...
```

**After:**
```python
@app.route('/login', methods=['POST'])
def login():
    # ... existing code ...
    if player_id is not None:
        # Removed asynchronous trigger for daily AI chat creation
        # thread = threading.Thread(target=_create_daily_ai_chat_if_needed, args=(player_id,))
        # thread.start()
        # ... rest of login success response ...
```

### 1.2. Create New API Endpoint for On-Demand Generation

Add a new API endpoint in `api.py` that the frontend can call to explicitly request a daily AI insight. This endpoint should be protected (e.g., using `@subscription_required` if applicable) and should call the `_create_daily_ai_chat_if_needed` function.

```python
@app.route('/coach/generate_insight', methods=['POST'])
@subscription_required # Apply if only subscribed users can generate insights
def generate_coach_insight():
    data = request.get_json()
    player_id = data.get('player_id') # Ensure player_id is passed from frontend

    if not player_id:
        return jsonify({"error": "Player ID is required."}), 400

    try:
        # Call the function directly or in a new thread if it's long-running
        # For immediate response, consider running in a thread and returning a "processing" status
        _create_daily_ai_chat_if_needed(player_id)
        return jsonify({"message": "AI Coach insight generation initiated."}), 200
    except Exception as e:
        app.logger.error(f"Failed to generate AI Coach insight for player {player_id}: {e}", exc_info=True)
        return jsonify({"error": "An internal error occurred during insight generation."}), 500

```

## 2. `vercel.json` Modifications

Update `vercel.json` to include the new `/coach/generate_insight` endpoint in its routing rules, ensuring it's correctly directed to `api.py`.

**Example `routes` entry:**

```json
{
  "src": "/coach/generate_insight",
  "methods": ["POST", "OPTIONS"],
  "dest": "api.py"
}
```

Ensure this new rule is placed appropriately within your `routes` array, typically before the broad `/(.*)` catch-all rule.

## 3. Frontend Modifications

Update the frontend application to:

*   **Remove automatic calls:** Ensure no part of the frontend automatically calls the AI Coach generation logic on login or page load.
*   **Implement explicit trigger:** Add a button or other UI element (e.g., "Generate New Insight", "Ask AI Coach") that, when clicked, makes a `POST` request to the new `/coach/generate_insight` endpoint, passing the `player_id`.
*   **Handle loading states:** Implement appropriate loading indicators and success/error messages in the UI while the insight is being generated.
*   **Display generated insights:** Ensure the frontend can fetch and display the newly generated AI coach conversations (e.g., by calling `/coach/conversations` after successful generation).

## 4. Testing

*   Verify that AI Coach insights are no longer generated automatically on login.
*   Test the new "Generate Insight" button (or equivalent) to confirm it successfully triggers insight generation.
*   Monitor backend logs to ensure `_create_daily_ai_chat_if_needed` is only called when the new endpoint is hit.
*   Verify that generated insights appear correctly in the UI.
