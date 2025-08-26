### Handover Report: Proof of Putt Vercel Deployment

**I. Project Context & Goal**

*   **Project:** `proofofputt` (React frontend in `webapp/`, Python/Flask backend `api.py` in root).
*   **Goal:** Deploy the full-stack application to Vercel, connecting to a Neon PostgreSQL database.
*   **Current Status:** Code is on GitHub, domain is connected, Vercel is deploying, but the site is not fully functional.

**II. Current Problem: Persistent `404: NOT_FOUND` for Root URL**

*   **Symptom:** When accessing `https://www.proofofputt.com/`, the browser shows a `404: NOT_FOUND` error (Vercel's error page).
*   **Observation:** This indicates Vercel is not correctly serving the static frontend assets (`index.html`).
*   **Backend Status:** We also saw `404` for `/api/register`, indicating the Python backend wasn't being found. The latest build logs show the Python build is now running, but the function might still not be correctly served.

**III. Summary of Attempted Solutions & Current `vercel.json` State**

We've made several changes to `vercel.json` and the frontend code to get to this point:

1.  **Frontend API URL:** Changed `webapp/src/api.js` to use `import.meta.env.VITE_API_BASE_URL || '/api'` for dynamic API endpoint resolution.
2.  **`vite.svg` Fix:** Removed the missing `vite.svg` reference from `webapp/index.html`.
3.  **Vercel Root Directory:** Set Vercel project's root directory to blank (`.`) to ensure it sees both `api.py` and `webapp/`.
4.  **`vercel.json` - Python Function Definition:**
    *   Initially added `functions` property.
    *   Then moved `runtime` config into `builds` entry for `api.py` to resolve `conflicting functions` error.
5.  **`requirements.txt` Size Fix:** Removed `opencv-python` and `numpy` from `requirements.txt` to resolve serverless function size limit.
6.  **`vercel.json` - Frontend Routing (Latest Attempt):** Removed the explicit `routes` entry for `/(.*)` to rely on `outputDirectory`. **This is where the current `404` likely stems from.**

**Current `vercel.json` (as of last commit):**

```json
{
  "functions": {
    "api.py": {
      "runtime": "python3.12"
    }
  },
  "builds": [
    {
      "src": "api.py",
      "use": "@vercel/python",
      "config": { "runtime": "python3.12" }
    },
    {
      "src": "webapp/package.json",
      "use": "@vercel/static-build",
      "config": { "distDir": "dist" }
    }
  ],
  "outputDirectory": "webapp/dist",
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "api.py"
    }
  ]
}
```

**IV. Next Steps / Plan for Tomorrow**

The most recent change (removing the `/(.*)` route) was likely a misstep. While `outputDirectory` is set, Vercel often still needs an explicit route to serve the root `index.html` when the static assets are in a subdirectory.

**Action Plan:**

1.  **Re-add the Frontend Catch-All Route in `vercel.json`:**
    *   We need to put back the route that directs all non-API requests to the frontend's build output.
    *   **Proposed `vercel.json` change:**
        ```json
        {
          "functions": {
            "api.py": {
              "runtime": "python3.12"
            }
          },
          "builds": [
            {
              "src": "api.py",
              "use": "@vercel/python",
              "config": { "runtime": "python3.12" }
            },
            {
              "src": "webapp/package.json",
              "use": "@vercel/static-build",
              "config": { "distDir": "dist" }
            }
          ],
          "outputDirectory": "webapp/dist",
          "routes": [
            {
              "src": "/api/(.*)",
              "dest": "api.py"
            },
            {
              "src": "/(.*)",  <-- ADD THIS BACK
              "dest": "webapp/dist/$1" <-- AND THIS
            }
          ]
        }
        ```
    *   **Commit and Push:** This change will need to be committed and pushed to trigger a new Vercel deployment.

2.  **Verify Backend Functionality:** Once the frontend 404 is resolved, we will need to re-test the registration/login to ensure the Python backend is correctly receiving and processing requests. If it still fails, we'll then dive into the `api.py` function's runtime logs on Vercel.
