# Launch Deployment Guide: Proof of Putt

**Version:** 2.0
**Date:** 2025-08-21
**Author:** Gemini Code Assist

---

## 1. Introduction

This guide provides step-by-step instructions for deploying the full-stack Proof of Putt application. The architecture consists of three main components:

-   **Vercel:** For hosting the Python (Flask) backend API and the React (Vite) frontend.
-   **Render:** For hosting the persistent, background scheduler process (`scheduler.py`).
-   **Neon.tech:** For the serverless PostgreSQL database.

This multi-platform approach is necessary because Vercel's serverless environment is not designed for long-running, scheduled tasks, which our application now requires for notifications.

## 2. Prerequisites

Before you begin, ensure you have the following:

-   A **GitHub** account with the project repository pushed.
-   A **Vercel** account, linked to your GitHub account.
-   A **Render** account, linked to your GitHub account.
-   A **Neon.tech** account.
-   Your **Gemini API Key** for the AI Coach feature.

---

## 3. Part 1: Database Setup (Neon.tech)

1.  **Create Project:** Log in to your Neon.tech dashboard and create a new project.
2.  **Get Connection Details:** Once the project is created, find the **Connection Details** section on your project's dashboard. You will need the following individual values for your environment variables:
    *   Host (`PGHOST`)
    *   Database (`PGDATABASE`)
    *   User (`PGUSER`)
    *   Password (`PGPASSWORD`)
3.  Keep these details safe; you will need them for both the Vercel and Render services.

---

## 4. Part 2: Backend API & Frontend Deployment (Vercel)

1.  **Import Project:** Log in to Vercel and **Add New... -> Project**. Select your project's GitHub repository.
2.  **Configure Backend (API):**
    *   Vercel should automatically detect this is a Flask application.
    *   **Root Directory:** Leave as the project root (`.`)
    *   **Environment Variables:** Add the following, replacing the values with your Neon and Gemini credentials:
        *   `INSTANCE_CONNECTION_NAME`: The **Host** from Neon (e.g., `ep-tight-union-123456.us-east-2.aws.neon.tech`).
        *   `DB_NAME`: The **Database** name from Neon.
        *   `DB_USER`: The **User** from Neon.
        *   `DB_PASS`: The **Password** from Neon.
        *   `GEMINI_API_KEY`: Your Google Gemini API Key.
3.  **Configure Frontend (WebApp):**
    *   Expand the "Web" section if it's not already visible.
    *   **Framework Preset:** Ensure it is set to **Vite**.
    *   **Root Directory:** Set this to `webapp`.
4.  **Deploy:** Click the **Deploy** button. After the initial deployment, Vercel will provide you with the public URL for your backend (e.g., `https://your-project.vercel.app`).
5.  **Update Frontend URL:** Go back into your Vercel project settings, find the Environment Variables, and add one more:
    *   `VITE_API_BASE_URL`: The full URL of your Vercel deployment from the previous step.
    *   Redeploy the project one more time for this variable to take effect.

---

## 5. Part 3: Scheduler Operation

The scheduler (`scheduler.py`) is a critical component that handles all time-based notifications (e.g., duel expirations, league reminders). It must be running continuously for these features to work. You have two main options for running it.

### Option A: Cloud Deployment (Recommended for Production)

For a real-world application where notifications must be sent reliably 24/7, a cloud-based background worker is the best solution.

1.  **Create New Service:** Log in to your **Render** dashboard and click **New -> Background Worker**.
2.  **Connect Repository:** Connect the same GitHub repository you used for Vercel.
3.  **Configure the Worker:**
    *   **Name:** Give it a clear name, like `proofofputt-scheduler`.
    *   **Region:** Choose a region close to your users.
    *   **Build Command:** `pip install -r requirements.txt`
    *   **Start Command:** `python scheduler.py`
4.  **Add Environment Variables:** Go to the "Environment" tab for your new service and add the *exact same* variables you added to Vercel:
    *   `INSTANCE_CONNECTION_NAME`
    *   `DB_NAME`
    *   `DB_USER`
    *   `DB_PASS`
    *   `GEMINI_API_KEY`
5.  **Create Service:** Click **Create Background Worker**. Render will build and start your `scheduler.py` script.

### Option B: Local Machine Operation (Cost-Saving)

To avoid hosting costs, you can run the scheduler on a local computer (like a desktop or home server) that is always on.

**Important:** If this computer is turned off or the script stops, **no time-based notifications will be sent**.

1.  **Set Environment Variables:** On the chosen machine, you must set the same environment variables that you configured in Vercel. How you do this depends on your operating system (e.g., using a `.env` file, `.zshrc`, `.bash_profile`, or System Environment Variables on Windows).
2.  **Run the Script:** Open a terminal, navigate to the project's root directory, and run the following command:

    ```bash
    nohup python scheduler.py &
    ```
    *   `nohup` ensures the script keeps running even if you close the terminal.
    *   `&` runs the script in the background.
    *   A `nohup.out` file will be created in the directory, which will contain any logs or errors from the script.
3.  **To stop the script**, you will need to find its Process ID (PID) using `ps aux | grep scheduler.py` and then use the `kill` command.

---

## 6. Part 4: Desktop Application Packaging

This process remains the same. It is a **manual build step** performed on your local machine for both macOS and Windows to create native executables.

1.  **Install PyInstaller:** `pip install pyinstaller`
2.  **Build Command:** From the project root, run:
    ```bash
    pyinstaller --onefile --windowed --add-data "models/best.pt:models" run_tracker.py
    ```
3.  **Distribute:** The executables will be in the `dist/` folder. Upload these to a public hosting service (like a GitHub Release) for users to download.

---

## 7. Part 5: Final Configuration & Launch

1.  **Database Initialization:** The first time the Vercel API is accessed, the `initialize_database()` function will run automatically, creating all the necessary tables in your Neon database.
2.  **Test End-to-End:**
    *   Register a new user on your live Vercel frontend.
    *   Verify the user appears in your Neon database.
    *   Change the user's password and confirm you receive an in-app notification.
    *   Run the desktop tracker application and ensure it can communicate with the live Vercel API URL.

You have now fully deployed the application. The Vercel app will serve user requests, and the Render worker will handle all time-based background tasks.
