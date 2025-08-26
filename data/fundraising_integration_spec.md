# Technical Specification: Fundraising Feature Integration & Testing

**Version:** 1.0
**Date:** 2025-08-19
**Author:** Gemini Code Assist
**Status:** For Handover & Implementation

---

## 1. Introduction

This document outlines the final development and testing stages for the "Fundraising" feature. The objective is to integrate a third-party payment processor for handling real financial transactions and to define the stress testing protocols required to ensure the system is secure, scalable, and reliable.

The core application logic, database schema, and preliminary API endpoints have been established. This specification focuses on the critical path to production readiness.

## 2. Current State

The following components are already implemented:

- **Database Schema:** `fundraisers` and `pledges` tables are created.
- **Backend API:** Endpoints exist for creating/listing fundraisers, viewing details, and creating pledges.
- **Core Logic:** The system can calculate the total amount raised for a fundraiser based on the player's performance (`total_putts_made`) and the sum of pledges (`amount_per_putt`).
- **Frontend UI:** Basic pages for listing fundraisers and a placeholder for creating them are in place.

**Crucially, the current implementation does not handle any real payment processing.** The `create_pledge` function is a placeholder where the payment integration must occur.

## 3. Payment Processor Integration (Zaprite)

We will use **Zaprite** for its invoice-based system, which is well-suited for collecting pledges after a campaign ends, and its native support for Bitcoin (on-chain and Lightning Network).

### 3.1. Initial Setup

1.  **Zaprite Account:** Create a Zaprite account.
2.  **API Keys:** Obtain your Zaprite API Key. Store it securely as an environment variable (e.g., `ZAPRITE_API_KEY`) and do not commit it to version control.
3.  **Webhook Endpoint:** Create a webhook in the Zaprite Dashboard that points to a new API endpoint (e.g., `https://your-api-domain.com/zaprite-webhooks`). Subscribe to the `order.paid` event.

### 3.2. Pledge Creation Flow

The pledge creation flow is simplified, as no payment information is collected upfront.

1.  **Frontend (Pledge Modal):** A user enters their pledge amount (e.g., 100 sats per putt) and an optional maximum donation cap. No payment details are required at this stage.
2.  **Backend (`data_manager.py` - `create_pledge` function):** The function simply records the `pledger_player_id`, `fundraiser_id`, `amount_per_putt`, and `max_donation` in the `pledges` table.

### 3.3. Donation Collection Flow (Automated Backend Task)

This process should be handled by a scheduled task (e.g., a cron job) that runs periodically (e.g., every hour).

1.  **Trigger:** The scheduled task will query the database for fundraisers whose `status` is `active` and `end_time` has passed, and for which donation orders have not yet been created.

2.  **Processing Logic (for each completed fundraiser):**
    -   **A. Calculate Final Amounts:**
        -   Fetch all `active` pledges for the fundraiser.
        -   For each pledge, calculate the final donation amount: `total_putts_made * amount_per_putt`.
        -   Crucially, cap this amount at the `max_donation` if one was set for the pledge.
    -   **B. Create/Retrieve Zaprite Contact:**
        -   For each pledger, check if they have a `zaprite_contact_id` in our `players` table.
        -   If not, use the Zaprite API to create a new `Contact` using the player's email and name. Store the returned `con_...` ID in our `players` table.
    -   **C. Create Zaprite Order:**
        -   For each pledge, use the Zaprite API to create a new `Order`.
        -   The order should be associated with the pledger's `zaprite_contact_id`.
        -   The order should contain a line item with the final calculated donation amount and a description (e.g., "Donation for '[Fundraiser Name]'").
        -   Store the returned `ord_...` ID in the `zaprite_order_id` column of our `pledges` table.
    -   **D. Notify User:**
        -   Zaprite will generate a hosted URL for the newly created order.
        -   Trigger an email to the pledger containing this unique payment link, asking them to complete their donation.
    -   **E. Update Fundraiser Status:**
        -   Once all orders are created, update the fundraiser's `status` to `completed` in our database.

### 3.4. Webhook Handling

1.  **Create Endpoint (`api.py`):**
    -   Create a new endpoint at `/zaprite-webhooks`.
2.  **Verify Signature:**
    -   The first step in the webhook handler **must** be to verify the webhook signature provided by Zaprite. This prevents CSRF attacks and ensures the request is genuine. Reject any request that fails verification.
3.  **Handle Events:**
    -   `order.paid`: When this event is received, use the `order.id` from the event payload to find the corresponding pledge in our database (via the `zaprite_order_id` column). Update the pledge's `status` to `fulfilled`.

---

## 4. Stress Testing Requirements

The following tests are critical to ensure the system's stability and correctness under load.

### 4.1. Concurrency Testing

-   **Pledge Creation:**
    -   **Objective:** Verify that multiple users can pledge to the same fundraiser simultaneously without data corruption.
    -   **Method:** Use a load testing tool (e.g., `locust`, `jmeter`) to send a high volume of concurrent requests to the `/fundraisers/<id>/pledge` endpoint.
    -   **Success Criteria:** The database should correctly record one pledge per user, and the `PRIMARY KEY (fundraiser_id, pledger_player_id)` constraint should prevent any duplicates.

### 4.2. Load Testing

-   **Fundraiser Detail Page:**
    -   **Objective:** Ensure the `get_fundraiser_details` calculation remains performant for a popular campaign.
    -   **Method:** Populate a test fundraiser with 10,000+ pledges. Populate the associated player's `sessions` table with 50,000+ putts within the campaign's time range. Measure the response time of the `GET /fundraisers/<id>` endpoint.
    -   **Success Criteria:** Response time should remain under 500ms. If performance degrades, the `_calculate_amount_raised` function must be optimized, likely by denormalizing the `total_putts_made` onto the `fundraisers` table and updating it via a database trigger on session completion.

-   **Donation Collection Task:**
    -   **Objective:** Ensure the automated donation collection process can handle a large number of pledges without timing out.
    -   **Method:** Simulate the completion of the fundraiser from the previous test (10,000+ pledges). Manually trigger the collection script.
    -   **Success Criteria:** The script should complete successfully without errors. Monitor API calls to Zaprite to ensure they are not exceeding rate limits. The process should be designed to be idempotent (i.e., running it twice on the same completed fundraiser does not result in double-billing).

### 4.3. Edge Case Testing

-   **Zero Putts:** A fundraiser ends with `total_putts_made` = 0.
    -   **Expected:** `amount_raised` is $0.00. No invoices are created.
-   **Zero Pledges:** A fundraiser ends with no pledges.
    -   **Expected:** `amount_raised` is $0.00. No invoices are created.
-   **Max Donation Cap:** A pledge has a `max_donation` that is lower than the calculated `total_putts * amount_per_putt`.
    -   **Expected:** The Zaprite `Order` is created for the `max_donation` amount, not the higher calculated amount.
-   **User Deletion:** A player who has made a pledge deletes their account.
    -   **Expected:** The `ON DELETE CASCADE` on the `pledges` table's foreign key should remove their pledge automatically. This must be verified.

---

## 5. Security & Compliance

-   **API Keys:** The Zaprite API key and webhook secrets must be stored in a secure secrets management system (e.g., Google Secret Manager) and accessed as environment variables. They must never be hardcoded.
-   **Webhook Security:** The webhook endpoint must rigorously enforce Zaprite's signature verification on every incoming request.

---

## 6. Subscription Tiers & Feature Gating

This section details the monetization strategy through user subscriptions.

### 6.1. Tier Definitions

-   **Free Tier:**
    -   Access to camera calibration.
    -   Access to session recording.
    -   View of recent session history (e.g., last 3 sessions).
-   **Full Subscriber Tier (Paid):**
    -   All Free Tier features.
    -   Full, unlimited session history.
    -   Access to Career Stats page.
    -   Ability to create, join, and participate in Leagues.
    -   Ability to create Fundraisers.
    -   Ability to create Duels with any player (including non-subscribers).

### 6.2. Other Access Rules

-   **Fundraiser Donors:** Do not need a subscription. They will be required to provide full billing address details during the Zaprite order checkout process, as handled by Zaprite's hosted invoice page.
-   **Duel Participants:** A non-subscriber can participate in a duel if invited by a Full Subscriber.

### 6.3. Technical Implementation

-   **Database Schema (`data_manager.py`):**
    -   Add a `subscription_status` column to the `players` table with a `DEFAULT 'free'`. Possible values: `free`, `active`, `past_due`, `cancelled`.
    -   Add a `zaprite_subscription_id` column to the `players` table to link to the recurring payment in Zaprite.

-   **Subscription Flow (Zaprite):**
    -   **Zaprite Setup:**
        -   Create a recurring "Product" in the Zaprite dashboard named "Proof of Putt Full Subscription" with a price of **$2.10 per month**.
    -   Create a discount code in the Zaprite dashboard with the code **`EARLY`**. This code should provide a 100% discount to reward beta users and early adopters.
    -   **Frontend:** Create an "Upgrade" page in the UI. This page will contain a button that links to the public URL for the Zaprite subscription product. The Zaprite-hosted checkout page includes a field for users to enter a discount code.
    -   **User Action:** The user follows the link, signs up for the subscription on the Zaprite-hosted page, and is redirected back to the application upon completion.

-   **Webhook Handling (`/zaprite-webhooks`):**
    -   The existing webhook endpoint must also subscribe to `subscription.created`, `subscription.updated`, and `subscription.deleted` events.
    -   When a subscription event is received, use the `customer.email` or other identifying information in the payload to find the corresponding user in our `players` table.
    -   Update the player's `subscription_status` and `zaprite_subscription_id` based on the webhook data. For example, `subscription.created` with an `active` status sets our status to `active`. `subscription.deleted` sets our status to `cancelled`.

-   **Backend API Gating (`api.py`):**
    -   A decorator or middleware should be implemented to check a user's subscription status before executing the logic of protected endpoints.
    -   If the user's status is not `active`, the endpoint should return a `403 Forbidden` error with a message like "This feature requires a full subscription."
    -   **Protected Endpoints:** `GET /player/<id>/career-stats`, all `/leagues` endpoints, `POST /fundraisers`, and `POST /duels` (checking the creator's status).
    -   The `GET /player/<id>/data` endpoint must be modified to implement logic that returns all sessions for subscribers but only the 3 most recent sessions for free users.

-   **Frontend UI Gating:**
    -   The `playerData` object in the `AuthContext` should be updated to include `subscription_status`.
    -   Conditionally render UI elements (e.g., "Create League" button, "Career Stats" link) based on the user's subscription status.
    -   If a free user attempts to access a protected feature, display a modal or page prompting them to upgrade, with a link to the "Upgrade" page.

---

## 7. Desktop Application Packaging & Distribution

This section addresses the requirement to provide the computer vision components (calibration and session tracking) as a user-friendly desktop application, shielding the underlying Python code from the end-user.

### 7.1. Objective

The goal is to package the Python scripts (`run_tracker.py`, `calibration.py`, and their dependencies) into standalone executables for Windows and macOS. This eliminates the need for users to install Python, manage dependencies, or interact with the command line.

### 7.2. Recommended Tool: PyInstaller

**PyInstaller** is the recommended tool for this task due to its cross-platform support and maturity. It analyzes the Python scripts and bundles all necessary components into a single distributable package.

### 7.3. Packaging Process

1.  **Installation:** Install PyInstaller in the development environment: `pip install pyinstaller`.
2.  **Execution:** PyInstaller will be run against the main entry-point scripts.
3.  **Bundling:** The process will create a distributable folder (or a single executable file using the `--onefile` flag) containing the Python interpreter, all project scripts as compiled bytecode, all required Python libraries, and the YOLOv8 model file (`best.pt`).
4.  **Output:** The result will be a standard application bundle (`.app` for macOS, `.exe` for Windows) that users can download and install.

### 7.4. Code Shielding

-   **No Source Code Exposure:** The user never sees or interacts with the `.py` source files. They only have the final executable.
-   **Bytecode Compilation:** The Python code is compiled into `.pyc` (bytecode) files before being bundled. This is not encryption, but it is not human-readable and requires specialized tools to decompile, providing a significant layer of obfuscation.

### 7.5. Integration with Web Application

The existing architecture, where the Flask backend (`api.py`) uses `subprocess.Popen` to launch the tracker, remains valid. The command being executed will change from `python run_tracker.py` to the path of the packaged executable. A setup process will be required where the user installs the desktop application, and the web application is made aware of its location. A custom URL protocol handler (e.g., `proofofputt://start-session/...`) is a more advanced and seamless alternative for launching the desktop app from the browser.