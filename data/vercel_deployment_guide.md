## Phase 1: Prepare and Deploy the Backend Project

1.  **Create a New Directory:**
    *   Outside your current `proofofputt` project, create a new, empty directory. Let's call it `proofofputt-backend`. This will be a new Git repository.

2.  **Copy Backend Files:**
    *   Copy the following files from your current `proofofputt` project into the new `proofofputt-backend` directory:
        *   `api.py`
        *   `requirements.txt`
        *   `data_manager.py` (since `api.py` imports it)
        *   `notification_service.py` (since `api.py` imports it)
        *   `utils.py` (since `api.py` imports it)

3.  **Create `vercel.json` for Backend:**
    *   Inside the `proofofputt-backend` directory, create a file named `vercel.json` with this content:

    ```json
    {
      "builds": [
        {
          "src": "api.py",
          "use": "@vercel/python",
          "config": { "runtime": "python3.12" }
        }
      ],
      "routes": [
        {
          "src": "/(.*)",
          "dest": "api.py"
        }
      ]
    }
    ```

4.  **Deploy Backend to Vercel:**
    *   **Initialize Git:** In your `proofofputt-backend` directory, run `git init`, then `git add .`, and `git commit -m "Initial backend commit"`.
    *   **Create Remote Repository:** Go to GitHub (or your preferred Git host) and create a *new, empty* repository (e.g., `proofofputt-backend`).
    *   **Push Code:** Link your local `proofofputt-backend` to this new remote repository and push your code.
    *   **Import to Vercel:** Go to your Vercel dashboard, click "Add New..." -> "Project", and import the `proofofputt-backend` GitHub repository.
    *   **Note URL:** Once deployed, Vercel will give you a deployment URL (e.g., `https://proofofputt-backend.vercel.app`). **Save this URL; it's crucial for the frontend.**

## Phase 2: Prepare and Deploy the Frontend Project

1.  **Modify Frontend `vercel.json`:**
    *   In your *original* `proofofputt` project (the monorepo), open the `vercel.json` file.
    *   Replace its entire content with this, which configures it to *only* build the frontend:

    ```json
    {
      "builds": [
        {
          "src": "webapp/package.json",
          "use": "@vercel/static-build",
          "config": { "distDir": "dist" }
        }
      ],
      "routes": [
        {
          "src": "/(.*)",
          "dest": "/index.html"
        }
      ]
    }
    ```

2.  **Update Frontend API Base URL:**
    *   In your *original* `proofofputt` project, open `webapp/src/api.js`.
    *   Modify the `API_BASE_URL` line to point to your newly deployed backend's Vercel URL (the one you saved from Phase 1, Step 4).

    *   **Option A (Hardcode for testing - less ideal):**
        ```javascript
        const API_BASE_URL = 'https://proofofputt-backend.vercel.app'; // Replace with your actual backend URL
        ```
    *   **Option B (Recommended - uses Vercel Environment Variables):**
        *   Keep the line as: `const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '/api';`
        *   Go to your Vercel dashboard for your *frontend* project (the original `proofofputt` project).
        *   Go to "Settings" -> "Environment Variables".
        *   Add a new environment variable:
            *   **Name:** `VITE_API_BASE_URL`
            *   **Value:** `https://proofofputt-backend.vercel.app` (your actual backend URL)
            *   **Environments:** Select "Production", "Preview", and "Development".

3.  **Deploy Frontend to Vercel:**
    *   In your *original* `proofofputt` project, commit the changes to `vercel.json` and `webapp/src/api.js`.
    *   Push these changes to your existing GitHub repository. Vercel will automatically redeploy your frontend project.

## Phase 3: Test End-to-End

1.  **Visit Frontend:** Open your frontend Vercel URL (e.g., `https://www.proofofputt.com/`) in your browser.
2.  **Test Functionality:** Try to register, log in, or interact with features that make API calls.
3.  **Monitor Logs:** Check the Vercel deployment and function logs for *both* your frontend and backend projects for any errors.
