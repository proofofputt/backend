## Gemini CLI Handover Report - Proof of Putt Vercel Deployment

**Date:** August 25, 2025
**Project Directory:** `/Users/nw/proofofputt` (to be copied to new machine)

**1. Project Overview:**
*   **Type:** Full-stack application.
*   **Structure:** Monorepo.
    *   **Frontend:** React application located in `webapp/`. Uses Vite.
    *   **Backend:** Flask application with `api.py` at the project root.
*   **Goal:** Deploy the application to Vercel.

**2. Core Problem:**
*   Persistent 404 errors on Vercel deployment, indicating routing issues.
*   Local `vercel dev` simulation also failed to achieve full functionality, mirroring deployment problems.

**3. Troubleshooting Steps & Findings (Chronological):**

*   **Initial `vercel.json` Fix (Step 1 of Troubleshooting Guide):**
    *   Updated `vercel.json` to include correct `builds` and `routes` for monorepo.
    *   **Result:** Deployment still failed (user reported 404).

*   **Local `vercel dev` Debugging (Step 2 of Troubleshooting Guide):**
    *   Attempted to run `vercel dev` locally to simulate Vercel environment.
    *   **Issue 1: `vercel: command not found`:** Resolved by ensuring Vercel CLI was in PATH.
    *   **Issue 2: `No existing credentials found`:** Resolved by user performing `vercel login`.
    *   **Issue 3: `The \`functions\` property cannot be used in conjunction with the \`builds\` property`:**
        *   **Cause:** `vercel.json` initially had a redundant `functions` block.
        *   **Resolution:** Removed `functions` block from `vercel.json`.
    *   **Issue 4: `sh: vite: command not found` / Port Timeout:**
        *   **Cause:** `vercel dev` was not correctly passing the assigned port to the Vite dev server, leading to timeouts.
        *   **Resolution Attempt 1:** Added `installCommand` and `devCommand` to `vercel.json` (`cd webapp && npm run dev -- --port $PORT`). This fixed `vite: command not found` but still timed out.
        *   **Resolution Attempt 2:** Modified `webapp/package.json` `dev` script to `vite --port ${PORT:-5173}` and `vercel.json` `devCommand` to `cd webapp && npm run dev`. This successfully started Vite on the correct port.
    *   **Issue 5: `Failed to parse source for import analysis because the content contains invalid JS syntax` (in `index.html`):**
        *   **Cause:** Vite was incorrectly trying to parse `index.html` as JavaScript.
        *   **Resolution Attempt:** Proposed adding `assetsInclude: ['**/*.html']` to `webapp/vite.config.js`. (User cancelled this operation initially).
    *   **Issue 6: Backend 500 Error (after `api.py` simplification):**
        *   **Cause:** The `if __name__ == '__main__': app.run()` block in `api.py` was interfering with Vercel's WSGI server.
        *   **Resolution:** Removed this block from `api.py` (both simplified and original versions).
    *   **Current Local `vercel dev` State:**
        *   `vercel dev` runs and reports `Ready! Available at http://localhost:3000`.
        *   Frontend loads a blank page with title "Proof of Putt".
        *   Console shows `Uncaught SyntaxError: The requested module '/@react-refresh' does not provide an export named 'injectIntoGlobalHook'`, indicating a frontend loading issue.
        *   **Crucially:** `curl http://localhost:3000/api/leaderboard` (and other API endpoints) still returns `index.html`, confirming the **routing issue persists in `vercel dev`**.

**4. Proposed Next Step (User found too complicated, but remains the logical path):**

*   **Separate Frontend and Backend Vercel Projects (Step 4 of Troubleshooting Guide):**
    *   **Rationale:** `vercel dev` appears unable to correctly handle the monorepo routing locally, suggesting the Vercel platform might also struggle. Separating deployments isolates the problem.
    *   **Backend Project (`proofofputt-backend`):**
        *   A new Git repository was created (`https://github.com/proofofputt/proofofputt-backend.git`).
        *   It contains `api.py`, `requirements.txt`, `data_manager.py`, `notification_service.py`, `utils.py`, and a minimal `vercel.json` (verified correct on GitHub).
        *   **Current Status:** Repository successfully pushed to GitHub. Vercel deployment of this project failed with the `functions`/`builds` conflict error, despite `vercel.json` being correct. This suggests a Vercel caching issue or project misconfiguration.
        *   **Environment Variables Needed:** `GEMINI_API_KEY`, `FRONTEND_URL` (for CORS), and database connection variables (`INSTANCE_CONNECTION_NAME`, `DB_USER`, `DB_PASS`, `DB_NAME` OR `DATABASE_URL`).
    *   **Frontend Project (original `proofofputt`):**
        *   `vercel.json` needs to be updated to only build the `webapp/` directory.
        *   `webapp/src/api.js` needs to be updated to point `API_BASE_URL` to the deployed backend URL (either hardcoded or via Vercel environment variable `VITE_API_BASE_URL`).

**5. Current Action Required from User:**

*   **For the `proofofputt-backend` Vercel project:**
    *   **Delete the existing Vercel project** (if any).
    *   **Create a brand new Vercel project** by importing `https://github.com/proofofputt/proofofputt-backend.git`.
    *   **Set Environment Variables** during project creation: `GEMINI_API_KEY`, `FRONTEND_URL` (placeholder for now), and database connection variables (e.g., `DATABASE_URL` for Neon, or the Google Cloud SQL variables).
    *   **Provide the Vercel deployment URL** for the successfully deployed backend.
