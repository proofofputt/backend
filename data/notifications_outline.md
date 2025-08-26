## Comprehensive Notification System Outline with Technical Implementation Strategy

This outline builds upon the previous one, adding a "Technical Implementation Strategy" section for each notification category. This strategy is designed to be extraordinarily detailed for use with Gemini Code Assist.

### General Notification System Architecture

Before diving into specific notifications, let's establish a foundational architecture:

1.  **Database Schema (`notifications` table):**
    *   `id` (INTEGER, PRIMARY KEY, AUTOINCREMENT)
    *   `player_id` (INTEGER, NOT NULL, FOREIGN KEY to `players.id`)
    *   `type` (TEXT, NOT NULL) - A unique identifier for the notification type (e.g., 'DUEL_CHALLENGE', 'PASSWORD_CHANGED', 'LEAGUE_INVITE'). This helps with rendering and filtering.
    *   `message` (TEXT, NOT NULL) - A concise, user-facing message (e.g., "You've been challenged by John Doe!").
    *   `details` (TEXT, JSONB/JSON string) - A JSON string containing all dynamic data needed for rendering the notification and its associated email/content (e.g., `{'opponent_name': 'John Doe', 'duel_id': 123}`).
    *   `read_status` (BOOLEAN, DEFAULT FALSE) - Tracks whether the user has viewed the in-app notification.
    *   `created_at` (TIMESTAMP, DEFAULT CURRENT_TIMESTAMP)
    *   `link_path` (TEXT, NULLABLE) - An optional internal application path to navigate to when the notification is clicked (e.g., `/duels`, `/settings`).
    *   `email_sent` (BOOLEAN, DEFAULT FALSE) - Flag to prevent duplicate email sends.
    *   `push_sent` (BOOLEAN, DEFAULT FALSE) - (Future) Flag for push notifications.

2.  **Backend Notification Service (`notification_service.py`):**
    *   A new Python module (`notification_service.py`) will encapsulate all logic for creating, storing, and dispatching notifications.
    *   Functions like `create_in_app_notification(player_id, type, message, details, link_path)` and `send_email_notification(player_id, type, message, details, template_name)`.
    *   This service will interact with `data_manager.py` to save to the `notifications` table and with an email sending utility.

3.  **Email Sending Utility (`email_utility.py`):**
    *   A dedicated module for integrating with an email API (e.g., SendGrid, Mailgun, or a simple SMTP client).
    *   Functions like `send_templated_email(to_email, subject, template_name, template_vars)`.
    *   Email templates will be defined externally (e.g., HTML files, or within the email service provider).

4.  **Frontend Notification Context (`NotificationContext.js`):**
    *   A new React Context to manage notification state for the frontend.
    *   Provides functions to fetch notifications, mark them as read, and get an unread count.
    *   Integrates with the `AuthContext.js` to get the current `player_id`.
    *   The `NotificationsPage.jsx` will consume this context.
    *   A global component (e.g., `Header.jsx` or a dedicated `NotificationBell.jsx`) will display the unread count.

5.  **Asynchronous Processing (Future Enhancement):**
    *   For high-volume notifications (especially emails), consider integrating a message queue (e.g., Celery with Redis/RabbitMQ).
    *   Instead of direct calls to `send_email_notification`, the backend would push a task to the queue, and a worker process would handle the actual sending.

---

### 1. Account & Security Notifications

| Notification | Trigger | Delivery Method(s) | Content / Data Needed |
| :--- | :--- | :--- | :--- |
| **Welcome to Proof of Putt!** | New user successfully registers (`/register` endpoint). | Email | Welcome message, link to their new dashboard, quick start guide. |
| **Password Changed** | User successfully changes their password (`/player/<id>/password`). | Email, In-App | Confirmation that the password was changed. Includes timestamp and IP address for security. |
| **Email Address Updated** | *(Missing Feature)* User changes their account email. | Email (to OLD and NEW address) | Notification of the change. Old email gets a "this wasn't you?" link. New email gets a verification link. |
| **Subscription Upgraded** | User successfully redeems a coupon or completes a purchase (`/redeem-coupon`, Zaprite webhook). | In-App, Email | Confirmation of subscription, summary of new features unlocked, receipt/billing info. |
| **Subscription Canceled** | User cancels their subscription (via Zaprite webhook). | Email | Confirmation of cancellation, effective date, option to provide feedback. |
| **Subscription Payment Failed** | Payment issue detected (via Zaprite webhook `subscription.past_due`). | Email, In-App | Notice of payment failure, link to update billing information to prevent service interruption. |

#### Technical Implementation Strategy:

*   **Backend (`api.py`, `data_manager.py`, `notification_service.py`, `email_utility.py`):
    *   **`notification_service.py`:
        *   `create_account_notification(player_id, type, message, details, link_path=None)`: Generic function for account-related notifications.
    *   **`email_utility.py`:
        *   `send_welcome_email(to_email, player_name)`
        *   `send_password_changed_email(to_email, player_name, timestamp, ip_address)`
        *   `send_email_updated_email(old_email, new_email, player_name, verification_link=None)`
        *   `send_subscription_status_email(to_email, player_name, status, details)`
    *   **`api.py` modifications:
        *   **`/register` endpoint:
            *   After successful `data_manager.register_player`, call `notification_service.send_email_notification(player_id, 'WELCOME', 'Welcome to Proof of Putt!', {'player_name': player_name}, 'welcome_template')`.
        *   **`/player/<int:player_id>/password` endpoint (`change_password_api`):
            *   After successful `data_manager.change_password`, call:
                *   `notification_service.create_in_app_notification(player_id, 'PASSWORD_CHANGED', 'Your password has been changed.', {'timestamp': datetime.now().isoformat(), 'ip_address': request.remote_addr}, '/settings')`
                *   `notification_service.send_email_notification(player_id, 'PASSWORD_CHANGED', 'Your password has been changed.', {'player_name': player_name, 'timestamp': datetime.now().isoformat(), 'ip_address': request.remote_addr}, 'password_changed_template')`
        *   **`/player/<int:player_id>/email` endpoint (NEW - for Email Address Update):
            *   Implement a new endpoint for email changes. This should involve a verification step (sending a token to the new email).
            *   On successful verification:
                *   `notification_service.send_email_notification(old_email, 'EMAIL_UPDATED_OLD', 'Your email was changed.', {'player_name': player_name, 'new_email': new_email}, 'email_updated_old_template')`
                *   `notification_service.send_email_notification(new_email, 'EMAIL_UPDATED_NEW', 'Your email has been updated.', {'player_name': player_name, 'old_email': old_email}, 'email_updated_new_template')`
        *   **`/player/<int:player_id>/redeem-coupon` endpoint:
            *   After `data_manager.upgrade_player_subscription_with_code`:
                *   `notification_service.create_in_app_notification(player_id, 'SUBSCRIPTION_UPGRADED', 'Your subscription has been upgraded!', {'status': 'active'}, '/upgrade')`
                *   `notification_service.send_email_notification(player_id, 'SUBSCRIPTION_UPGRADED', 'Your subscription has been upgraded!', {'player_name': player_name, 'status': 'active'}, 'subscription_upgraded_template')`
        *   **`/zaprite-webhook` endpoint:
            *   Modify to handle `subscription.canceled` and `subscription.past_due` events.
            *   For `subscription.canceled`:
                *   `notification_service.send_email_notification(player_id, 'SUBSCRIPTION_CANCELED', 'Your subscription has been canceled.', {'player_name': player_name, 'effective_date': data.get('cancel_at_period_end')}, 'subscription_canceled_template')`
            *   For `subscription.past_due`:
                *   `notification_service.create_in_app_notification(player_id, 'PAYMENT_FAILED', 'Your subscription payment failed.', {'reason': 'past_due'}, '/upgrade')`
                *   `notification_service.send_email_notification(player_id, 'PAYMENT_FAILED', 'Your subscription payment failed.', {'reason': 'past_due'}, 'payment_failed_template')`

*   **Frontend (`NotificationsPage.jsx`, `SettingsPage.jsx`, `AuthContext.js`):
    *   **`AuthContext.js`:
        *   Add a `fetchNotifications` function that calls a new backend API endpoint (`/notifications/<player_id>`).
        *   Maintain a state for `unreadNotificationCount`.
    *   **`NotificationsPage.jsx`:
        *   Fetch notifications using `NotificationContext` (or `AuthContext`).
        *   Display notifications, grouped by type or date.
        *   Implement a "Mark as Read" button/action.
        *   When a notification is clicked, navigate to `link_path` and mark as read.
    *   **`SettingsPage.jsx`:
        *   The existing `showNotification` can be replaced by a more robust in-app toast/banner system that consumes `NotificationContext` for displaying transient messages.
    *   **`Header.jsx` (or similar global component):
        *   Display an icon (e.g., bell) with `unreadNotificationCount` badge.

---

### 2. Duel Notifications (Player vs. Player)

These notifications are crucial for driving engagement and guiding users through the duel lifecycle.

| Notification | Trigger | Delivery Method(s) | Content / Data Needed |
| :--- | :--- | :--- | :--- |
| **You've Been Challenged!** | Another player creates a duel inviting the user (`/duels` POST). | In-App, Email | `Challenger's Name`, link to the Duels page to accept/reject. |
| **Duel Accepted** | An invited opponent accepts the user's duel challenge (`/duels/<id>/accept`). | In-App | `Opponent's Name` has accepted your duel. Link to the Duels page. |
| **Duel Rejected** | An invited opponent rejects the user's duel challenge (`/duels/<id>/reject`). | In-App | `Opponent's Name` has declined your duel. |
| **Opponent's Score Submitted** | The opponent in an active duel submits their session score (`/duels/<id>/submit-session`). | In-App, Email | `Opponent's Name` has submitted their score of `[Score]`. "It's your turn to putt!" Link to start session. |
| **Duel Result: You Won!** | Both players have submitted scores and the user is the winner. | In-App | "You defeated `Opponent's Name` `[Your Score]` to `[Opponent's Score]`!" Link to duel results. |
| **Duel Result: You Lost.** | Both players have submitted scores and the user is the loser. | In-App | "You lost to `Opponent's Name` `[Your Score]` to `[Opponent's Score]`." Link to duel results. |
| **Duel Result: It's a Draw!** | Both players submitted identical scores. | In-App | "Your duel with `Opponent's Name` was a draw! `[Score]` to `[Score]`." |
| **Duel Expired** | A pending or active duel expires based on its time limit. | In-App | "Your duel with `Opponent's Name` has expired." |

#### Technical Implementation Strategy:

*   **Backend (`api.py`, `data_manager.py`, `notification_service.py`):
    *   **`notification_service.py`:
        *   `create_duel_notification(player_id, type, message, details, link_path='/duels')`: Specific function for duel notifications.
    *   **`api.py` modifications:
        *   **`/duels` POST (create_duel_api):
            *   After `data_manager.create_duel`, get `creator_name` and `invited_player_name`.
            *   Call `notification_service.create_duel_notification(invited_player_id, 'DUEL_CHALLENGE', f'You\'ve been challenged by {creator_name}!', {'challenger_name': creator_name, 'duel_id': duel_id})`
            *   `notification_service.send_email_notification(invited_player_id, 'DUEL_CHALLENGE', f'You\'ve been challenged by {creator_name}!', {'challenger_name': creator_name, 'duel_id': duel_id}, 'duel_challenge_template')`
        *   **`/duels/<int:duel_id>/accept` (accept_duel_api):
            *   After `data_manager.accept_duel`, get `creator_id` and `invited_player_name`.
            *   Call `notification_service.create_duel_notification(creator_id, 'DUEL_ACCEPTED', f'{invited_player_name} has accepted your duel!', {'opponent_name': invited_player_name, 'duel_id': duel_id})`
        *   **`/duels/<int:duel_id>/reject` (reject_duel_api):
            *   After `data_manager.reject_duel`, get `creator_id` and `invited_player_name`.
            *   Call `notification_service.create_duel_notification(creator_id, 'DUEL_REJECTED', f'{invited_player_name} has declined your duel.', {'opponent_name': invited_player_name, 'duel_id': duel_id})`
        *   **`/duels/<int:duel_id>/submit-session` (submit_duel_session_api):
            *   After `data_manager.submit_duel_session`, determine the *other* player's ID and name.
            *   Call `notification_service.create_duel_notification(other_player_id, 'OPPONENT_SCORE_SUBMITTED', f'{player_name} has submitted their score of {score}!', {'opponent_name': player_name, 'score': score, 'duel_id': duel_id})`
            *   `notification_service.send_email_notification(other_player_id, 'OPPONENT_SCORE_SUBMITTED', f'{player_name} has submitted their score of {score}!', {'opponent_name': player_name, 'score': score, 'duel_id': duel_id}, 'opponent_score_template')`
            *   **Crucially:** If *both* players have now submitted, trigger duel resolution logic in `data_manager.py`. This logic will determine the winner/loser/draw and then call `notification_service` for both players.
                *   `data_manager.resolve_duel(duel_id)` will return `winner_id`, `loser_id`, `draw_ids`, `creator_score`, `invited_score`.
                *   Based on the result, call `notification_service.create_duel_notification` for each player with appropriate `type` ('DUEL_WON', 'DUEL_LOST', 'DUEL_DRAW') and `message`.
        *   **Scheduled Task (Cron Job/Celery Beat):
            *   A daily or hourly job to check for expired duels.
            *   Function in `data_manager.py` like `get_expired_duels()`.
            *   For each expired duel, update its status to 'expired' and call `notification_service.create_duel_notification` for both participants.

*   **Frontend (`DuelsPage.jsx`, `NotificationContext.js`):
    *   **`DuelsPage.jsx`:
        *   Display a clear call to action for pending challenges.
        *   When a user accepts/rejects, trigger the backend API call.
    *   **`NotificationContext.js`:
        *   Poll for new notifications or use WebSockets (future) for real-time updates.
        *   When a new duel notification arrives, update the unread count and display a toast/banner.

---

### 3. League Notifications (Group Competition)

Leagues involve multiple players and scheduled events, requiring more complex triggers.

| Notification | Trigger | Delivery Method(s) | Content / Data Needed |
| :--- | :--- | :--- | :--- |
| **Invited to League** | User is invited to a private league (`/leagues/<id>/invite`). | In-App, Email | "`Inviter's Name` has invited you to join the `League Name` league." Link to Leagues page to accept/decline. |
| **League Joined** | User successfully joins a league. | In-App | "Welcome to `League Name`!" Link to the league detail page. |
| **New League Round Starting** | A new round begins based on the league's schedule settings. | In-App, Email | "Round `[Round #]` of `League Name` is starting! You have `[Time]` to complete your session." Link to start session. |
| **League Session Completed** | User completes a putting session for a league round. | In-App | "Your score of `[Score]` has been submitted for Round `[Round #]` of `League Name`." |
| **Round Results Are In** | A league round ends and results are calculated. | In-App, Email | "Round `[Round #]` of `League Name` has ended. You placed `[Rank]` with a score of `[Score]`." Link to round leaderboard. |
| **Final League Results** | The entire league competition concludes. | In-App, Email | "`League Name` has concluded! You finished `[Final Rank]`." Link to final league leaderboard. |
| **Reminder: Submit Your Score** | 24 hours (or configurable time) before a league round deadline and user hasn't submitted. | In-App, Email | "Don't forget to submit your score for Round `[Round #]` of `League Name`! Deadline is `[Date/Time]`." |
| **Removed from League** | A league admin removes the user from the league. | In-App | "You have been removed from `League Name` by an administrator." |

#### Technical Implementation Strategy:

*   **Backend (`api.py`, `data_manager.py`, `notification_service.py`, `scheduler.py`):
    *   **`notification_service.py`:
        *   `create_league_notification(player_id, type, message, details, link_path='/leagues')`: Specific function for league notifications.
    *   **`api.py` modifications:
        *   **`/leagues/<int:league_id>/invite` (invite_to_league_api):
            *   After `data_manager.invite_to_league`, get `inviter_name` and `league_name`.
            *   Call `notification_service.create_league_notification(invitee_id, 'LEAGUE_INVITE', f'{inviter_name} has invited you to join {league_name}!', {'inviter_name': inviter_name, 'league_name': league_name, 'league_id': league_id})`
            *   `notification_service.send_email_notification(invitee_id, 'LEAGUE_INVITE', f'{inviter_name} has invited you to join {league_name}!', {'inviter_name': inviter_name, 'league_name': league_name, 'league_id': league_id}, 'league_invite_template')`
        *   **`/leagues/<int:league_id>/join` (NEW - for joining public leagues):
            *   After `data_manager.join_league`:
                *   `notification_service.create_league_notification(player_id, 'LEAGUE_JOINED', f'Welcome to {league_name}!', {'league_name': league_name, 'league_id': league_id})`
        *   **`run_tracker.py` (or a new `session_completion_hook`):
            *   When a session is completed and associated with a `league_round_id`:
                *   After `data_manager.submit_league_session_score`:
                    *   `notification_service.create_league_notification(player_id, 'LEAGUE_SESSION_COMPLETED', f'Your score of {score} has been submitted for Round {round_num} of {league_name}.', {'score': score, 'round_num': round_num, 'league_name': league_name, 'league_id': league_id})`
        *   **`/leagues/<int:league_id>/remove-member` (NEW - for admin actions):
            *   After `data_manager.remove_league_member`:
                *   `notification_service.create_league_notification(removed_player_id, 'LEAGUE_REMOVED', f'You have been removed from {league_name}.', {'league_name': league_name, 'league_id': league_id})`

*   **Scheduled Tasks (`scheduler.py` - a new module for cron-like jobs):
    *   **Daily/Hourly Job: `check_league_round_starts()`:
        *   Query `data_manager.get_upcoming_league_rounds(within_timeframe)`.
        *   For each starting round, iterate through all league members:
            *   `notification_service.create_league_notification(member_id, 'LEAGUE_ROUND_STARTING', f'Round {round_num} of {league_name} is starting!', {'round_num': round_num, 'league_name': league_name, 'league_id': league_id, 'deadline': deadline_time})`
            *   `notification_service.send_email_notification(member_id, 'LEAGUE_ROUND_STARTING', f'Round {round_num} of {league_name} is starting!', {'round_num': round_num, 'league_name': league_name, 'league_id': league_id, 'deadline': deadline_time}, 'league_round_start_template')`
    *   **Daily/Hourly Job: `check_league_round_ends()`:
        *   Query `data_manager.get_ending_league_rounds(within_timeframe)`.
        *   For each ending round, trigger score calculation and ranking in `data_manager.py`.
        *   For each league member, after results are calculated:
            *   `notification_service.create_league_notification(member_id, 'LEAGUE_ROUND_RESULTS', f'Round {round_num} results for {league_name} are in!', {'round_num': round_num, 'league_name': league_name, 'league_id': league_id, 'rank': player_rank, 'score': player_score})`
            *   `notification_service.send_email_notification(member_id, 'LEAGUE_ROUND_RESULTS', f'Round {round_num} results for {league_name} are in!', {'round_num': round_num, 'league_name': league_name, 'league_id': league_id, 'rank': player_rank, 'score': player_score}, 'league_round_results_template')`
    *   **Daily Job: `check_league_reminders()`:
        *   Query `data_manager.get_players_needing_league_reminders()`.
        *   For each player/round combination:
            *   `notification_service.create_league_notification(player_id, 'LEAGUE_REMINDER', f'Reminder: Submit your score for Round {round_num} of {league_name}!', {'round_num': round_num, 'league_name': league_name, 'league_id': league_id, 'deadline': deadline_time})`
            *   `notification_service.send_email_notification(player_id, 'LEAGUE_REMINDER', f'Reminder: Submit your score for Round {round_num} of {league_name}!', {'round_num': round_num, 'league_name': league_name, 'league_id': league_id, 'deadline': deadline_time}, 'league_reminder_template')`
    *   **Daily Job: `check_league_final_results()`:
        *   Query `data_manager.get_completed_leagues_without_final_notifications()`.
        *   For each completed league, trigger final ranking and then notify all members.
            *   `notification_service.create_league_notification(member_id, 'LEAGUE_FINAL_RESULTS', f'{league_name} has concluded! You finished {final_rank}.', {'league_name': league_name, 'league_id': league_id, 'final_rank': final_rank})`
            *   `notification_service.send_email_notification(member_id, 'LEAGUE_FINAL_RESULTS', f'{league_name} has concluded! You finished {final_rank}.', {'league_name': league_name, 'league_id': league_id, 'final_rank': final_rank}, 'league_final_results_template')`

*   **Frontend (`LeaguesPage.jsx`, `LeagueDetailPage.jsx`, `NotificationContext.js`):
    *   **`LeaguesPage.jsx`:
        *   Display pending invites prominently.
    *   **`LeagueDetailPage.jsx`:
        *   Show current round status and deadlines.
        *   Provide a clear "Start Session for League" button.
    *   **`NotificationContext.js`:
        *   Handle display of league-specific notifications.

---

### 4. Session & Performance Notifications

These notifications focus on individual progress and achievements, encouraging continued use.

| Notification | Trigger | Delivery Method(s) | Content / Data Needed |
| :--- | :--- | :--- | :--- |
| **Session Report Ready** | `session_reporter.py` finishes processing a session. | In-App | "Your session report is ready." Link to the session detail page. Includes key stats like `Makes`, `Misses`, `MPM`. |
| **New Personal Best!** | A completed session sets a new record for a key metric (e.g., Max Streak, Makes Per Minute). | In-App | "New Personal Best! You set a new record for `[Metric Name]` with a value of `[Value]`." |
| **Weekly Performance Summary** | A scheduled, weekly job that aggregates the user's stats for the past 7 days. | Email | Summary of the week's activity: total putts, total sessions, makes/misses, and comparison to the previous week. |
| **AI Coach Insight** | *(Subscription Feature)* The AI Coach identifies a significant trend or provides a new analysis. | In-App | "Your AI Coach has a new insight for you." Link to the Coach page. |

#### Technical Implementation Strategy:

*   **Backend (`session_reporter.py`, `data_manager.py`, `api.py`, `notification_service.py`, `scheduler.py`):
    *   **`notification_service.py`:
        *   `create_performance_notification(player_id, type, message, details, link_path)`: Specific function for performance notifications.
    *   **`session_reporter.py` (or a new post-processing hook):
        *   After `reporter.generate_report` and `data_manager.save_session_report`:
            *   Call a new function in `data_manager.py`, e.g., `check_for_personal_bests(player_id, session_stats)`.
            *   `data_manager.check_for_personal_bests` will compare current session stats (`total_makes`, `max_consecutive_makes`, `makes_per_minute`, etc.) against stored career bests for the player.
            *   If a new personal best is achieved:
                *   `notification_service.create_performance_notification(player_id, 'NEW_PERSONAL_BEST', f'New Personal Best! You set a new record for {metric_name} with {value}!', {'metric_name': metric_name, 'value': value}, '/career-stats')`
            *   Always create a "Session Report Ready" notification:
                *   `notification_service.create_performance_notification(player_id, 'SESSION_REPORT_READY', 'Your session report is ready!', {'session_id': session_id, 'makes': total_makes, 'misses': total_misses, 'mpm': makes_per_minute}, f'/session/{session_id}')`
    *   **`api.py` modifications:
        *   **`/coach/chat` endpoint:
            *   When a new conversation is created (initial analysis):
                *   `notification_service.create_performance_notification(player_id, 'AI_COACH_INSIGHT', 'Your AI Coach has a new insight for you!', {'conversation_id': new_conversation_id, 'title': title}, f'/coach/{new_conversation_id}')`
    *   **Scheduled Task (`scheduler.py`):
        *   **Weekly Job: `send_weekly_performance_summaries()`:
            *   Iterate through all active players.
            *   For each player, query `data_manager.get_weekly_stats_summary(player_id)`.
            *   `notification_service.send_email_notification(player_id, 'WEEKLY_SUMMARY', 'Your Weekly Proof of Putt Summary is here!', {'player_name': player_name, 'summary_data': summary_data}, 'weekly_summary_template')`

*   **Frontend (`Dashboard.jsx`, `PlayerCareerPage.jsx`, `SessionHistoryPage.jsx`, `NotificationContext.js`):
    *   **`Dashboard.jsx`:
        *   Could display a small "New Personal Best" badge if a recent notification indicates one.
    *   **`SessionHistoryPage.jsx`:
        *   Link directly from the "Session Report Ready" notification.
    *   **`PlayerCareerPage.jsx`:
        *   This page would be the destination for "New Personal Best" notifications.
    *   **`NotificationContext.js`:
        *   Handle display of performance-related notifications.

---

### 5. Fundraising Notifications

These notifications are critical for motivating fundraisers and pledgers.

| Notification | Trigger | Delivery Method(s) | Content / Data Needed |
| :--- | :--- | :--- | :--- |
| **Fundraiser Created** | User successfully creates a new fundraiser (`/fundraisers` POST). | In-App | "Your fundraiser `Fundraiser Name` is live!" Includes a shareable link. |
| **New Pledge Received** | Another user makes a pledge to the fundraiser. | In-App, Email | "`Pledger's Name` has pledged `[$X.XX]` per putt to your fundraiser!" |
| **Fundraising Milestone Reached** | The total amount raised crosses a key threshold (e.g., 25%, 50%, 75%, 100%). | In-App, Email | "You've just passed `[Milestone %]` of your goal for `Fundraiser Name`, raising `[$Amount]` so far!" |
| **Fundraiser Goal Reached!** | The total amount raised meets or exceeds the goal amount. | In-App, Email | "Congratulations! You've reached your goal for `Fundraiser Name`!" |
| **Fundraiser Ending Soon** | 24 hours before the fundraiser's scheduled end time. | In-App, Email | "Your fundraiser `Fundraiser Name` is ending soon. Make one last push!" |
| **Fundraiser Concluded** | The fundraiser's end time is reached. | In-App, Email | "Your fundraiser `Fundraiser Name` has ended. You raised a total of `[$Amount]` for `[Cause]`! Thank you!" |

#### Technical Implementation Strategy:

*   **Backend (`api.py`, `data_manager.py`, `notification_service.py`, `scheduler.py`):
    *   **`notification_service.py`:
        *   `create_fundraiser_notification(player_id, type, message, details, link_path)`: Specific function for fundraiser notifications.
    *   **`api.py` modifications:
        *   **`/fundraisers` POST (create_fundraiser_api):
            *   After `data_manager.create_fundraiser`:
                *   `notification_service.create_fundraiser_notification(player_id, 'FUNDRAISER_CREATED', f'Your fundraiser {fundraiser_name} is live!', {'fundraiser_name': fundraiser_name, 'fundraiser_id': fundraiser_id}, f'/fundraisers/{fundraiser_id}')`
        *   **`/fundraisers/<id>/pledge` (NEW - for making pledges):
            *   After `data_manager.create_pledge`:
                *   Get `fundraiser_owner_id` and `pledger_name`.
                *   `notification_service.create_fundraiser_notification(fundraiser_owner_id, 'NEW_PLEDGE_RECEIVED', f'{pledger_name} has pledged ${amount_per_putt:.2f} per putt!', {'pledger_name': pledger_name, 'amount_per_putt': amount_per_putt, 'fundraiser_id': fundraiser_id}, f'/fundraisers/{fundraiser_id}')`
                *   `notification_service.send_email_notification(fundraiser_owner_id, 'NEW_PLEDGE_RECEIVED', f'{pledger_name} has pledged ${amount_per_putt:.2f} per putt!', {'pledger_name': pledger_name, 'amount_per_putt': amount_per_putt, 'fundraiser_id': fundraiser_id}, 'new_pledge_template')`
        *   **`session_reporter.py` (or a new post-processing hook):
            *   After a session is processed and `data_manager.update_fundraiser_progress` is called:
                *   `data_manager.update_fundraiser_progress` should return `current_amount_raised` and `milestones_reached` (e.g., `[25, 50]`).
                *   For each `milestone_percent` reached:
                    *   `notification_service.create_fundraiser_notification(fundraiser_owner_id, 'FUNDRAISER_MILESTONE', f'You\'ve passed {milestone_percent}% of your goal for {fundraiser_name}!', {'milestone_percent': milestone_percent, 'amount_raised': current_amount_raised, 'fundraiser_name': fundraiser_name, 'fundraiser_id': fundraiser_id}, f'/fundraisers/{fundraiser_id}')`
                    *   `notification_service.send_email_notification(fundraiser_owner_id, 'FUNDRAISER_MILESTONE', f'You\'ve passed {milestone_percent}% of your goal for {fundraiser_name}!', {'milestone_percent': milestone_percent, 'amount_raised': current_amount_raised, 'fundraiser_name': fundraiser_name, 'fundraiser_id': fundraiser_id}, 'fundraiser_milestone_template')`
                *   If `current_amount_raised >= goal_amount`:
                    *   `notification_service.create_fundraiser_notification(fundraiser_owner_id, 'FUNDRAISER_GOAL_REACHED', f'Congratulations! You\'ve reached your goal for {fundraiser_name}!', {'amount_raised': current_amount_raised, 'fundraiser_name': fundraiser_name, 'fundraiser_id': fundraiser_id}, f'/fundraisers/{fundraiser_id}')`
                    *   `notification_service.send_email_notification(fundraiser_owner_id, 'FUNDRAISER_GOAL_REACHED', f'Congratulations! You\'ve reached your goal for {fundraiser_name}!', {'amount_raised': current_amount_raised, 'fundraiser_name': fundraiser_name, 'fundraiser_id': fundraiser_id}, 'fundraiser_goal_reached_template')`

*   **Scheduled Tasks (`scheduler.py`):
    *   **Daily Job: `check_fundraiser_deadlines()`:
        *   Query `data_manager.get_fundraisers_ending_soon(24_hours_out)`.
        *   For each:
            *   `notification_service.create_fundraiser_notification(fundraiser_owner_id, 'FUNDRAISER_ENDING_SOON', f'Your fundraiser {fundraiser_name} is ending soon!', {'fundraiser_name': fundraiser_name, 'fundraiser_id': fundraiser_id}, f'/fundraisers/{fundraiser_id}')`
            *   `notification_service.send_email_notification(fundraiser_owner_id, 'FUNDRAISER_ENDING_SOON', f'Your fundraiser {fundraiser_name} is ending soon!', {'fundraiser_name': fundraiser_name, 'fundraiser_id': fundraiser_id}, 'fundraiser_ending_soon_template')`
        *   Query `data_manager.get_concluded_fundraisers_without_notification()`.
        *   For each:
            *   `notification_service.create_fundraiser_notification(fundraiser_owner_id, 'FUNDRAISER_CONCLUDED', f'Your fundraiser {fundraiser_name} has ended. You raised ${total_raised:.2f}!', {'fundraiser_name': fundraiser_name, 'total_raised': total_raised, 'fundraiser_id': fundraiser_id}, f'/fundraisers/{fundraiser_id}')`
            *   `notification_service.send_email_notification(fundraiser_owner_id, 'FUNDRAISER_CONCLUDED', f'Your fundraiser {fundraiser_name} has ended. You raised ${total_raised:.2f}!', {'fundraiser_name': fundraiser_name, 'total_raised': total_raised, 'fundraiser_id': fundraiser_id}, 'fundraiser_concluded_template')`

*   **Frontend (`FundraisingPage.jsx`, `FundraiserDetailPage.jsx`, `NotificationContext.js`):
    *   **`FundraisingPage.jsx`:
        *   Display a "Create Fundraiser" button.
    *   **`FundraiserDetailPage.jsx`:
        *   Show progress towards goal.
        *   Provide a "Pledge Now" button.
    *   **`NotificationContext.js`:
        *   Handle display of fundraising-related notifications.

---

### 6. Core Notification API Endpoints

To support the frontend's ability to fetch, display, and manage notifications, a dedicated set of API endpoints is required.

#### Technical Implementation Strategy:

*   **Backend (`api.py`, `data_manager.py`, `notification_service.py`):
    *   **`api.py`:
        *   **`GET /notifications/<int:player_id>`:
            *   **Purpose:** Retrieve a player's notifications.
            *   **Parameters:** `player_id` (from URL), `limit` (query param, e.g., 20), `offset` (query param, for pagination), `status` (query param, e.g., 'all', 'unread').
            *   **Logic:
                *   Authenticate and authorize `player_id`.
                *   Call `data_manager.get_player_notifications(player_id, limit, offset, status)`.
                *   Return a JSON array of notification objects, including `id`, `type`, `message`, `details`, `read_status`, `created_at`, `link_path`.
            *   **Example Response:
                ```json
                [
                    {
                        "id": 1,
                        "type": "DUEL_CHALLENGE",
                        "message": "You've been challenged by John Doe!",
                        "details": {"challenger_name": "John Doe", "duel_id": 123},
                        "read_status": false,
                        "created_at": "2025-08-20T10:00:00Z",
                        "link_path": "/duels"
                    },
                    {
                        "id": 2,
                        "type": "SESSION_REPORT_READY",
                        "message": "Your session report is ready!",
                        "details": {"session_id": 456, "makes": 15, "misses": 3},
                        "read_status": true,
                        "created_at": "2025-08-19T18:30:00Z",
                        "link_path": "/session/456"
                    }
                ]
                ```
        *   **`GET /notifications/<int:player_id>/unread_count`:
            *   **Purpose:** Get the count of unread notifications for a player.
            *   **Logic:
                *   Authenticate and authorize `player_id`.
                *   Call `data_manager.get_unread_notifications_count(player_id)`.
                *   Return `{"count": 5}`.
        *   **`POST /notifications/<int:notification_id>/mark_read`:
            *   **Purpose:** Mark a specific notification as read.
            *   **Parameters:** `notification_id` (from URL), `player_id` (from request body/auth token for authorization).
            *   **Logic:
                *   Authenticate and authorize `player_id` owns `notification_id`.
                *   Call `data_manager.mark_notification_as_read(notification_id, player_id)`.
                *   Return `{"message": "Notification marked as read."}`.
        *   **`POST /notifications/<int:player_id>/mark_all_read`:
            *   **Purpose:** Mark all notifications for a player as read.
            *   **Parameters:** `player_id` (from URL/auth token).
            *   **Logic:
                *   Authenticate and authorize `player_id`.
                *   Call `data_manager.mark_all_notifications_as_read(player_id)`.
                *   Return `{"message": "All notifications marked as read."}`.
        *   **`DELETE /notifications/<int:notification_id>`:
            *   **Purpose:** Delete a specific notification.
            *   **Parameters:** `notification_id` (from URL), `player_id` (from request body/auth token for authorization).
            *   **Logic:
                *   Authenticate and authorize `player_id` owns `notification_id`.
                *   Call `data_manager.delete_notification(notification_id, player_id)`.
                *   Return `{"message": "Notification deleted."}`.

### 7. Frontend Notification Context and UI Integration

The `NotificationContext.js` will be the central hub for managing notification state and interactions on the frontend.

#### Technical Implementation Strategy:

*   **Frontend (`NotificationContext.js`, `App.jsx`, `Header.jsx`, `NotificationsPage.jsx`, `ToastNotification.jsx`):
    *   **`NotificationContext.js` (New File):
        *   **State:
            *   `notifications`: Array of notification objects.
            *   `unreadCount`: Integer.
            *   `isLoading`: Boolean.
            *   `error`: String.
        *   **Functions (exposed via context):
            *   `fetchNotifications(limit, offset, status)`: Calls `GET /notifications/<player_id>`.
            *   `markAsRead(notificationId)`: Calls `POST /notifications/<notification_id>/mark_read`. Updates local state.
            *   `markAllAsRead()`: Calls `POST /notifications/<player_id>/mark_all_read`. Updates local state.
            *   `deleteNotification(notificationId)`: Calls `DELETE /notifications/<notification_id>`. Updates local state.
            *   `refreshUnreadCount()`: Calls `GET /notifications/<player_id>/unread_count`. Updates `unreadCount`.
            *   `addTemporaryNotification(message, type)`: For transient, non-persisted notifications (e.g., "Session started!").
        *   **Integration:
            *   Wrap `App.jsx` (or relevant parts) with `NotificationContext.Provider`.
            *   `useEffect` in the provider to `fetchNotifications` and `refreshUnreadCount` on initial load and `playerData` changes.
    *   **`Header.jsx`:
        *   Import `useNotification` hook from `NotificationContext.js`.
        *   Display a notification icon (e.g., bell) with `unreadCount` badge.
        *   On click, navigate to `/notifications`.
    *   **`NotificationsPage.jsx`:
        *   Import `useNotification` hook.
        *   Display `notifications` list.
        *   Render each notification item, showing `message`, `created_at`.
        *   If `read_status` is false, highlight it.
        *   Provide "Mark as Read" and "Delete" buttons for each.
        *   Implement "Mark All as Read" button.
        *   If `link_path` exists, make the notification clickable to navigate.
    *   **`ToastNotification.jsx` (New Component):
        *   A global component rendered at the top level (e.g., in `App.jsx`).
        *   Consumes `NotificationContext` to listen for `addTemporaryNotification` calls.
        *   Displays a small, transient pop-up (toast) for a few seconds.
        *   Useful for immediate feedback (e.g., "Duel created successfully!").

### 8. Error Handling and Logging for Notifications

Robust error handling is crucial to ensure notifications are delivered reliably and system issues are caught.

#### Technical Implementation Strategy:

*   **Backend (`api.py`, `notification_service.py`, `email_utility.py`, `data_manager.py`):
    *   **Centralized Logging:
        *   Utilize Python's `logging` module throughout `notification_service.py`, `email_utility.py`, and `data_manager.py`.
        *   Log successful notification creations, email sends, and status updates at `INFO` level.
        *   Log failures (e.g., database write errors, email API errors, invalid player IDs) at `WARNING` or `ERROR` level, including relevant context (player ID, notification type, error message).
    *   **Retry Mechanisms:
        *   Implement `tenacity` (as seen in `api.py` for Gemini API) for external calls like email sending. This ensures transient network issues don't prevent email delivery.
        *   For database operations, ensure proper transaction management and error handling.
    *   **Idempotency:
        *   When creating notifications, especially those triggered by webhooks or scheduled jobs, ensure they are idempotent. For example, if a webhook is re-sent, the system shouldn't create duplicate "Subscription Upgraded" notifications. This can be achieved by:
            *   Checking for existing notifications of the same `type` and `details` within a recent timeframe.
            *   Using a unique identifier from the external system (e.g., Zaprite subscription ID) in the `details` JSON and checking for its existence.
        *   For email sending, the `email_sent` flag in the `notifications` table helps prevent re-sending the same email for a given notification record.
    *   **Dead Letter Queues (Future):
        *   If using a message queue, configure a dead-letter queue for messages that repeatedly fail processing. This allows manual inspection and re-processing of failed notifications.

*   **Frontend (`NotificationContext.js`, UI Components):
    *   **User Feedback:
        *   Display user-friendly error messages if notification fetching or marking as read fails.
        *   Use the `error` state in `NotificationContext` to inform components.
    *   **Loading States:
        *   Show loading indicators (`isLoading` state) when fetching notifications to prevent a blank UI.

### 9. Real-time Notifications (Future Enhancement)

While polling is a good starting point, real-time updates significantly enhance user experience.

#### Technical Implementation Strategy:

*   **Backend (New Service/Library: WebSockets):
    *   **Technology Choice:** Integrate a WebSocket library (e.g., `Flask-SocketIO` for Flask, or a separate WebSocket server like `Node.js` with `Socket.IO`).
    *   **Event Emission:
        *   Whenever a new notification is created (e.g., after `notification_service.create_in_app_notification`), emit a WebSocket event to the relevant `player_id`.
        *   The event payload would include the new notification data.
    *   **Authentication:** Secure WebSocket connections to ensure only authorized users receive their notifications.
    *   **Scalability:** Consider a message broker (like Redis Pub/Sub) to fan out events to multiple WebSocket server instances if the application scales.

*   **Frontend (`NotificationContext.js`):
    *   **WebSocket Client:
        *   In `NotificationContext.js`, establish a WebSocket connection when the user logs in.
        *   Listen for incoming notification events.
        *   When an event is received, update the `notifications` state and `unreadCount` immediately, without needing to poll the API.
        *   Display a toast notification for new incoming real-time notifications.

### 10. System / Admin Notifications (New Category)

These are notifications sent by the system or administrators to all or a subset of users, often for announcements or critical information.

| Notification | Trigger | Delivery Method(s) | Content / Data Needed |
| :--- | :--- | :--- | :--- |
| **System Maintenance Alert** | Scheduled system downtime or critical bug fix. | In-App, Email | "Heads up! Proof of Putt will be undergoing maintenance from `[Start Time]` to `[End Time]`." |
| **New Feature Announcement** | Release of a significant new feature. | In-App, Email | "Exciting news! We've just launched `[Feature Name]`! Check it out." |
| **Policy Update** | Changes to Terms of Service, Privacy Policy, etc. | In-App, Email | "Important Update: Our Terms of Service have been updated. Please review them." |

#### Technical Implementation Strategy:

*   **Backend (New Admin Interface/API, `notification_service.py`):
    *   **Admin Interface:** A new admin panel (or CLI tool) would allow administrators to compose and send these notifications.
    *   **`api.py` (Admin-only endpoint):
        *   **`POST /admin/send_broadcast_notification`:
            *   **Parameters:** `type` (e.g., 'SYSTEM_MAINTENANCE', 'NEW_FEATURE'), `message`, `details` (JSON), `target_players` (e.g., 'all', 'subscribers_only', list of `player_id`s), `send_email` (boolean).
            *   **Logic:
                *   Requires admin authentication/authorization.
                *   Iterate through target players.
                *   For each player:
                    *   `notification_service.create_in_app_notification(player_id, type, message, details, link_path)`
                    *   If `send_email` is true: `notification_service.send_email_notification(player_id, type, message, details, template_name)`
    *   **`notification_service.py`:
        *   May need a new `create_broadcast_notification` function that handles iterating through users.

*   **Frontend (`NotificationsPage.jsx`):
    *   These notifications would appear in the standard `NotificationsPage.jsx`.

### 11. Inactivity / Re-engagement Notifications (New Category)

These are proactive notifications designed to bring inactive users back to the platform.

| Notification | Trigger | Delivery Method(s) | Content / Data Needed |
| :--- | :--- | :--- | :--- |
| **We Miss You!** | User has not logged in or completed a session for a configurable period (e.g., 7, 14, 30 days). | Email | "It's been a while! We miss you on the green. Come back and putt!" |
| **New Challenge Awaits** | *(Contextual)* If a user was active in duels/leagues, remind them of ongoing competitions. | Email | "Your league `[League Name]` has a new round starting soon!" (if applicable) or "A new challenge awaits you!" |

#### Technical Implementation Strategy:

*   **Backend (`scheduler.py`, `data_manager.py`, `notification_service.py`):
    *   **Scheduled Task (`scheduler.py` - Weekly/Monthly Job):
        *   **`send_inactivity_reminders()`:
            *   Query `data_manager.get_inactive_players(days_inactive)`.
            *   For each inactive player:
                *   Check if they have any pending duels or active league rounds.
                *   Compose a personalized message.
                *   `notification_service.send_email_notification(player_id, 'INACTIVITY_REMINDER', 'We miss you on the green!', {'player_name': player_name, 'contextual_message': '...' if contextual else None}, 'inactivity_reminder_template')`
            *   Ensure a cooldown period so users aren't spammed with these.

This expanded outline provides a comprehensive and highly detailed technical strategy for implementing a robust notification system within the Proof of Putt application.