# Deployment Guide: Proof of Putt on Vercel & Neon

**Version:** 1.0
**Date:** 2025-08-19
**Author:** Gemini Code Assist

---

## 1. Introduction

This guide provides step-by-step instructions for deploying the full-stack Proof of Putt application. We will use:

-   **Vercel:** For hosting the Python (Flask) backend and the React (Vite) frontend.
-   **Neon.tech:** For the serverless PostgreSQL database.
-   **PyInstaller:** For packaging the desktop computer vision application.

## 2. Prerequisites

Before you begin, ensure you have the following:

-   A **GitHub** account with the project repository pushed.
-   A **Vercel** account, linked to your GitHub account.
-   A **Neon.tech** account.
-   A **Zaprite** account with API keys and a subscription product configured as per the technical specification.

---

## 3. Part 1: Database Setup (Neon.tech)

1.  **Create Project:** Log in to your Neon.tech dashboard and create a new project.
2.  **Get Connection String:** Once the project is created, navigate to the **Connection Details** section on your project's dashboard.
3.  **Copy Pooled URL:** Find and copy the **Pooled connection string**. It will start with `postgres://`. This is your `DATABASE_URL`. Keep it safe; you will need it for the backend configuration.

---

## 4. Part 2: Backend & Frontend Deployment (Vercel)

Vercel can deploy both the frontend and backend from the same repository.

### 4.1. Import Project

1.  Log in to Vercel and click **Add New... -> Project**.
2.  Select your project's GitHub repository. Vercel will analyze the project structure.

### 4.2. Configure the Backend (Flask API)

Vercel should automatically detect the Python environment.

1.  **Framework Preset:** Ensure it is set to **Flask**.
2.  **Build & Development Settings:**
    -   **Build Command:** `pip install -r requirements.txt`
    -   **Root Directory:** Should be the project root (`.`).
3.  **Environment Variables:** This is the most critical step. Add the following variables:
    -   `DATABASE_URL`: Paste the pooled connection string you copied from Neon.
    -   `ZAPRITE_API_KEY`: Your secret API key from the Zaprite dashboard.
    -   `ZAPRITE_WEBHOOK_SECRET`: Your webhook signing secret from Zaprite.

### 4.3. Configure the Frontend (React App)

Vercel should also detect the `webapp` directory.

1.  **Framework Preset:** Ensure it is set to **Vite**.
2.  **Root Directory:** Set this to `webapp`.
3.  **Environment Variables:** Add the following variable, prefixed with `VITE_` to expose it to the frontend:
    -   `VITE_API_BASE_URL`: This must be the URL of your deployed Vercel backend (e.g., `https://your-project-name.vercel.app`). You can leave this blank for now and edit it after the first deployment provides you with the URL.

### 4.4. Deploy

Click the **Deploy** button. Vercel will build and deploy both the backend and frontend.

---

## 5. Part 3: Code Modification for Database Connection

To make the backend seamlessly connect to Neon using the `DATABASE_URL`, a small modification to `data_manager.py` is recommended. This change makes the connection logic more robust and platform-agnostic.

**File:** `data_manager.py`

```python
import os
import logging
import sqlalchemy
from google.cloud.sql.connector import Connector, IPTypes
# ... (rest of the imports)

# --- Database Configuration ---
DATABASE_URL = os.environ.get("DATABASE_URL") # For Vercel/Neon
INSTANCE_CONNECTION_NAME = os.environ.get("INSTANCE_CONNECTION_NAME") # For Google Cloud SQL
# ... (rest of the config variables)

def get_db_connection():
    """
    Initializes a connection pool. Prefers a direct DATABASE_URL if set,
    then falls back to Google Cloud SQL, then to local SQLite.
    """
    global connector, pool
    if pool:
        return pool

    if DATABASE_URL:
        logger.info("Using DATABASE_URL for database connection (Vercel/Neon).")
        pool = sqlalchemy.create_engine(DATABASE_URL)
    elif all([INSTANCE_CONNECTION_NAME, DB_USER, DB_PASS, DB_NAME]):
        # ... (existing Google Cloud SQL logic remains unchanged)
    else:
        # ... (existing SQLite fallback logic remains unchanged)

    return pool
```

*This change should be committed to your repository before deploying to Vercel.*

---

## 6. Part 4: Desktop Application Packaging

This is a **manual build step** performed on your local machine. You must build one version on macOS and one on Windows to create native executables for each.

1.  **Install PyInstaller:** `pip install pyinstaller`
2.  **Build Command:** From the project root, run the following command. This bundles the script, the model file, and all dependencies into a single executable.
    ```bash
    pyinstaller --onefile --windowed --add-data "models/best.pt:models" run_tracker.py
    ```
    *(Repeat for `calibration.py` if a separate calibration app is desired).*
3.  **Distribute:** The executables will be in the `dist/` folder. Upload these files to a public hosting service (e.g., create a "Release" on GitHub) so users can download them.

---

## 7. Part 5: Final Configuration

1.  **Update Zaprite Webhooks:** In your Zaprite dashboard, update your webhook endpoint URL to point to your live Vercel backend: `https://your-project-name.vercel.app/zaprite-webhooks`.
2.  **Database Initialization:** The first time you access the deployed web application, the `initialize_database()` function will run automatically, creating all the necessary tables in your Neon database.
3.  **Test:** Perform a full end-to-end test: register a new user, create a league, and test the desktop application's ability to communicate with the live backend API.