Handover Document: Vercel Deployment Troubleshooting for Proof of Putt

1. Introduction
This document details the troubleshooting steps and configuration attempts made to resolve a persistent 404 error during the Vercel deployment of the `proofofputt` application. The application is a monorepo consisting of a Python Flask API at the repository root and a React frontend located in the `webapp/` subdirectory.

2. Project Structure
*   **Backend API:** `api.py` (Python/Flask) located at the repository root (`/Users/nw/proofofputt/api.py`).
*   **Frontend Application:** React application located in `webapp/` (`/Users/nw/proofofputt/webapp/`).
    *   Build output is generated into `webapp/dist/`.
    *   Uses Vite for development and build.

3. Vercel Project Settings Manipulated
The following settings in the Vercel Project Dashboard were adjusted during troubleshooting:

*   **Root Directory:** Specifies the directory within the project where the main application code is located.
*   **Output Directory:** Specifies the directory where the build output is expected.

4. `vercel.json` Configurations and Outcomes

Below is a chronological log of `vercel.json` configurations attempted, along with the rationale for each change and the observed deployment outcome.

---
**Iteration 1: Initial `vercel.json` (from Handover Report)**

**Rationale:** This was the `vercel.json` present at the start of the troubleshooting, as identified from the `handover_report_20250823.md`. It aimed to define both Python functions and static builds.

**`vercel.json` Content:**
```json
{
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
**Vercel Project Settings (Assumed/Initial):**
*   Root Directory: (Empty)
*   Output Directory: (Default/Unknown)

**Observed Outcome:** Persistent `404: NOT_FOUND` for the root URL (`https://www.proofofputt.com/`). This indicated Vercel was not correctly serving the static frontend assets (`index.html`).

---
**Iteration 2: Re-add Frontend Catch-All Route & `functions` block**

**Rationale:** Based on the `handover_report_20250823.md`'s "Action Plan," the frontend catch-all route was re-added, and a `functions` block was introduced for `api.py`.

**`vercel.json` Content:**
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
      "src": "/(.*)",
      "dest": "webapp/dist/$1"
    }
  ]
}
```
**Vercel Project Settings (Assumed):**
*   Root Directory: (Empty)
*   Output Directory: (Default/Unknown)

**Observed Outcome:** Deployment failed with a warning about "Conflicting Functions and Builds Configuration" (as reported by user via GitHub warning). The `404: NOT_FOUND` persisted.

---
**Iteration 3: Resolve `functions` vs `builds` Conflict**

**Rationale:** Removed the redundant `api.py` definition from the `builds` section, keeping it only in the `functions` block, as per Vercel documentation's recommendation to use one or the other.

**`vercel.json` Content:**
```json
{
  "functions": {
    "api.py": {
      "runtime": "python3.12"
    }
  },
  "builds": [
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
      "handle": "filesystem"
    },
    {
      "src": "/(.*)",
      "dest": "/index.html"
    }
  ]
}
```
**Vercel Project Settings (Assumed):**
*   Root Directory: (Empty)
*   Output Directory: (Default/Unknown)

**Observed Outcome:** Deployment failed. The user reported "All checks have failed" and "Vercel - Deployment failed."

---
**Iteration 4: Revert to `builds` for both API and Webapp**

**Rationale:** Given the continued deployment failures and the `functions` vs `builds` conflict, reverted to using the `builds` array for both the Python API and the React webapp, removing the top-level `functions` block entirely. This was a configuration that was implied to be working in the handover report.

**`vercel.json` Content:**
```json
{
  "builds": [
    {
      "src": "api.py",
      "use": "@vercel/python"
    },
    {
      "src": "webapp/package.json",
      "use": "@vercel/static-build",
      "config": {
        "distDir": "webapp/dist"
      }
    }
  ],
  "outputDirectory": "webapp/dist",
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "api.py"
    },
    {
      "handle": "filesystem"
    },
    {
      "src": "/(.*)",
      "dest": "/index.html"
    }
  ]
}
```
**Vercel Project Settings (Assumed):**
*   Root Directory: (Empty)
*   Output Directory: (Default/Unknown)

**Observed Outcome:** Build completed successfully. However, the frontend still showed a 404 error in the browser console, specifically for `index-MH_dlGXQ.js`. This indicated a problem with asset loading.

---
**Iteration 5: Fix Frontend Script Path in `index.html`**

**Rationale:** Identified that `webapp/index.html` had an absolute script path (`/src/main.jsx`) which was not being correctly handled by Vite in production. Changed it to a relative path (`./src/main.jsx`). Also added a `shortcut icon` link for favicon.

**`webapp/index.html` Content (relevant changes):**
```html
    <link rel="icon" type="image/png" href="/POP.Proof_Of_Putt.Log.576.png" />
    <link rel="shortcut icon" href="/POP.Proof_Of_Putt.Log.576.png" />
    ...
    <script type="module" src="./src/main.jsx"></script>
```
**`vercel.json` Content:** (Same as Iteration 4)

**Observed Outcome:** Still 404 and the same console log for `index-MH_dlGXQ.js`.

---
**Iteration 6: Set Vite `base` to Relative Path**

**Rationale:** To ensure Vite generates relative asset paths in the build output, added `base: './'` to `webapp/vite.config.js`.

**`webapp/vite.config.js` Content (relevant changes):**
```javascript
export default defineConfig({
  base: './',
  plugins: [react()],
  // ...
})
```
**`vercel.json` Content:** (Same as Iteration 4)

**Observed Outcome:** Build failed with "Error: No Output Directory named "dist" found after the Build completed." This indicated a conflict with Vercel's "Output Directory" setting.

---
**Iteration 7: Adjust Vercel Project Settings (Root & Output Directory)**

**Rationale:** Based on the "No Output Directory" error, instructed the user to adjust Vercel Project Settings. The goal was to align Vercel's expectations with the project structure.

**Vercel Project Settings (Changes Made by User):**
*   **Root Directory:** Changed from empty to `webapp`.
*   **Output Directory:** Changed from `dist` to `webapp/dist`.

**`vercel.json` Content:** (Same as Iteration 4)

**Observed Outcome:** Login and registration pages loaded (frontend worked!), but registration failed with a 404 for `/api/register`. This was a significant step forward, as the frontend was finally being served.

---
**Iteration 8: Explicitly Set Python Runtime for API Build**

**Rationale:** To address the `/api/register` 404, explicitly added `config: { "runtime": "python3.12" }` to the `api.py` build in `vercel.json`.

**`vercel.json` Content:**
```json
{
  "builds": [
    {
      "src": "api.py",
      "use": "@vercel/python",
      "config": { "runtime": "python3.12" }
    },
    {
      "src": "webapp/package.json",
      "use": "@vercel/static-build",
      "config": {
        "distDir": "webapp/dist"
      }
    }
  ],
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "api.py"
    },
    {
      "handle": "filesystem"
    },
    {
      "src": "/(.*)",
      "dest": "/index.html"
    }
  ]
}
```
**Vercel Project Settings (Current):**
*   Root Directory: `webapp`
*   Output Directory: `webapp/dist`

**Observed Outcome:** Still 404 for `/api/register`.

---
**Iteration 9: Revert Python Runtime Config & Reset Root Directory**

**Rationale:** User reported "no functions in deployment summary" despite explicit runtime config. Suspected conflict with "Root Directory" setting. Instructed user to reset "Root Directory" to empty, and simplified `api.py` build config in `vercel.json` by removing the `config` block.

**Vercel Project Settings (Changes Made by User):**
*   **Root Directory:** Changed from `webapp` to empty (or `.`).
*   **Output Directory:** Remained `webapp/dist`.

**`vercel.json` Content:**
```json
{
  "builds": [
    {
      "src": "api.py",
      "use": "@vercel/python"
    },
    {
      "src": "webapp/package.json",
      "use": "@vercel/static-build",
      "config": {
        "distDir": "webapp/dist"
      }
    }
  ],
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "api.py"
    },
    {
      "handle": "filesystem"
    },
    {
      "src": "/(.*)",
      "dest": "/index.html"
    }
  ]
}
```
**Observed Outcome:** `api.py` showed as a function (good!), but the page had a 404 again (frontend broken).

---
**Iteration 10: Adjust `distDir` and Frontend Route for Empty Root Directory**

**Rationale:** With "Root Directory" empty, `vercel.json` needed to be adjusted to correctly point to the frontend build output. Changed `distDir` in `static-build` to `dist` (relative to `webapp/`) and `dest` of the fallback route to `webapp/dist/$1`.

**`vercel.json` Content:**
```json
{
  "builds": [
    {
      "src": "api.py",
      "use": "@vercel/python"
    },
    {
      "src": "webapp/package.json",
      "use": "@vercel/static-build",
      "config": {
        "distDir": "dist"
      }
    }
  ],
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "api.py"
    },
    {
      "handle": "filesystem"
    },
    {
      "src": "/(.*)",
      "dest": "webapp/dist/$1"
    }
  ]
}
```
**Vercel Project Settings (Current):**
*   Root Directory: Empty
*   Output Directory: `webapp/dist`

**Observed Outcome:** Build failed with "Error: No Output Directory named "dist" found after the Build completed."

---
**Iteration 11: Re-add `outputDirectory` to `vercel.json`**

**Rationale:** To address the "No Output Directory" error, explicitly re-added `outputDirectory: "webapp/dist"` to `vercel.json`.

**`vercel.json` Content:**
```json
{
  "builds": [
    {
      "src": "api.py",
      "use": "@vercel/python"
    },
    {
      "src": "webapp/package.json",
      "use": "@vercel/static-build",
      "config": {
        "distDir": "dist"
      }
    }
  ],
  "outputDirectory": "webapp/dist",
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "api.py"
    },
    {
      "handle": "filesystem"
    },
    {
      "src": "/(.*)",
      "dest": "webapp/dist/$1"
    }
  ]
}
```
**Vercel Project Settings (Current):**
*   Root Directory: Empty
*   Output Directory: `webapp/dist`

**Observed Outcome:** Build failed with "Error: No Output Directory named "dist" found after the Build completed." (Same error as Iteration 10).

---
**Iteration 12: Rewrite API Routes to Strip `/api/` Prefix**

**Rationale:** Based on the "grok recommendation list," identified that Flask routes do not have `/api/` prefix, so Vercel needed to strip it before forwarding.

**`vercel.json` Content:**
```json
{
  "builds": [
    {
      "src": "api.py",
      "use": "@vercel/python"
    },
    {
      "src": "webapp/package.json",
      "use": "@vercel/static-build",
      "config": {
        "distDir": "webapp/dist"
      }
    }
  ],
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "/$1"
    },
    {
      "handle": "filesystem"
    },
    {
      "src": "/(.*)",
      "dest": "/index.html"
    }
  ]
}
```
**Vercel Project Settings (Current):**
*   Root Directory: Empty
*   Output Directory: `webapp/dist`

**Observed Outcome:** Build failed with "Error: No Output Directory named "dist" found after the Build completed." (Same error as Iteration 10 and 11).

---
**Iteration 13: Simplify Static Build Configuration**

**Rationale:** To address the persistent "No Output Directory" error, simplified the `static-build` configuration by removing the `config` block, relying on `@vercel/static-build` to infer `distDir`.

**`vercel.json` Content:**
```json
{
  "builds": [
    {
      "src": "api.py",
      "use": "@vercel/python"
    },
    {
      "src": "webapp/package.json",
      "use": "@vercel/static-build"
    }
  ],
  "routes": [
    {
      "src": "/api/(.*)",
      "dest": "/$1"
    },
    {
      "handle": "filesystem"
    },
    {
      "src": "/(.*)",
      "dest": "/index.html"
    }
  ]
}
```
**Vercel Project Settings (Current):**
*   Root Directory: Empty
*   Output Directory: `webapp/dist`

**Observed Outcome:** Static assets and functions are showing in deployment summary, but the 404 error persists. This is the current state.

---
**5. Key Learnings and Current Hypotheses**

*   **Persistent 404:** Despite numerous `vercel.json` and Vercel Project Settings adjustments, a 404 error for the main page (frontend) persists.
*   **API Function Deployment:** The `api.py` is now correctly recognized and deployed as a Vercel Function. This was achieved by setting the "Root Directory" to empty and ensuring `api.py` was at the repository root.
*   **Frontend Deployment Issue:** The primary remaining issue is the frontend. Vercel is either not correctly serving the `index.html` or the assets referenced within it, even though the build logs indicate a successful Vite build to `webapp/dist`.
*   **`outputDirectory` vs `distDir` Confusion:** There seems to be a persistent misunderstanding or conflict in how Vercel interprets the `outputDirectory` in `vercel.json` and the `distDir` within the `static-build` configuration, especially when combined with the "Root Directory" setting in Vercel Project Settings.
*   **`requirements.txt`:** The `requirements.txt` file exists at the root and its content seems correct. The "Missing requirements.txt" error was likely a red herring or a caching issue.
*   **`StacksProvider` Error:** The `Unable to set StacksProvider` error is likely due to a browser extension and not directly related to the application's code or deployment.

**Next Steps for Another Agent:**

The next agent should focus on why the frontend is not being served correctly, given that the build is successful and the `api.py` function is now deployed.

*   **Deep Dive into Vercel's Static Asset Serving:** Investigate Vercel's internal logs more thoroughly for clues on why `index.html` or its assets are not being served.
*   **Alternative Frontend Deployment:** Consider deploying the `webapp` as a separate Vercel project, or using a different build approach if the current `static-build` is problematic.
*   **Vercel Support:** If all else fails, contacting Vercel support with the detailed `vercel.json` and deployment logs would be advisable.

---