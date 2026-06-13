## Email Ingestor Service

This service periodically fetches emails from configured IMAP mailboxes, processes them, stores them in a PostgreSQL database, and publishes them to a RabbitMQ queue for further analysis.

## 1. Database Schema

The database schema consists of three main tables: `mailboxes`, `emails`, and `blocked_senders`.

### 1.1. `mailboxes` Table
Stores configuration for each monitored mailbox.

| Column                  | Type                             | Constraints                                  | Description                                                                 |
|-------------------------|----------------------------------|----------------------------------------------|-----------------------------------------------------------------------------|
| `id`                    | `INTEGER`                        | `PK, SERIAL`                                 | Unique identifier for the mailbox.                                          |
| `email_address`         | `VARCHAR`                        | `UNIQUE, NOT NULL`                           | Email address of the mailbox (e.g., `user@example.com`).                      |
| `imap_host`             | `VARCHAR`                        | `NOT NULL`                                   | IMAP server hostname (e.g., `imap.example.com`).                             |
| `imap_port`             | `INTEGER`                        | `NOT NULL`                                   | IMAP server port (e.g., 993 for SSL).                                        |
| `imap_login`            | `VARCHAR`                        | `NOT NULL`                                   | Login username for the IMAP server.                                         |
| `imap_password_encrypted` | `VARCHAR`                        | `NOT NULL`                                   | Encrypted IMAP password.                                                    |
| `monitored_folders`     | `JSONB`                          | `NOT NULL, DEFAULT ['INBOX']`                | List of folder names to monitor (e.g., `["INBOX", "Orders"]`).              |
| `is_active`             | `BOOLEAN`                        | `NOT NULL, DEFAULT TRUE`                     | Whether the mailbox is currently being monitored.                             |
| `last_checked_uid_map`  | `JSONB`                          | `NULLABLE`                                   | Dictionary mapping folder names to the last processed email UID in that folder (e.g., `{"INBOX": 12345}`). |
| `created_at`            | `TIMESTAMP WITH TIME ZONE`       | `NOT NULL, DEFAULT CURRENT_TIMESTAMP`        | Timestamp of creation.                                                      |
| `updated_at`            | `TIMESTAMP WITH TIME ZONE`       | `NOT NULL, DEFAULT CURRENT_TIMESTAMP, ON UPDATE CURRENT_TIMESTAMP` | Timestamp of last update.                                                   |

**Indexes:**
*   `idx_mailboxes_email_address` (UNIQUE on `email_address`)
*   Primary key on `id`

### 1.2. `emails` Table
Stores information about each fetched email.

| Column                       | Type                             | Constraints                               | Description                                                                  |
|------------------------------|----------------------------------|-------------------------------------------|------------------------------------------------------------------------------|
| `id`                         | `INTEGER`                        | `PK, SERIAL`                              | Unique identifier for the email record.                                      |
| `mailbox_id`                 | `INTEGER`                        | `FK (mailboxes.id), NOT NULL`             | Foreign key referencing the mailbox this email came from.                    |
| `message_uid`                | `VARCHAR`                        | `NOT NULL`                                | Unique ID of the email on the IMAP server (unique per folder).               |
| `folder_name`                | `VARCHAR`                        | `NOT NULL`                                | Name of the IMAP folder from which the email was fetched.                    |
| `message_id_header`          | `VARCHAR`                        | `NULLABLE`                                | Value of the `Message-ID` email header.                                      |
| `sender_address`             | `VARCHAR`                        | `NOT NULL`                                | Sender's email address.                                                      |
| `recipient_address`          | `VARCHAR`                        | `NOT NULL`                                | Original recipient address (from the mailbox configuration).                 |
| `subject`                    | `TEXT`                           | `NULLABLE`                                | Email subject.                                                               |
| `body_html`                  | `TEXT`                           | `NULLABLE`                                | HTML body content of the email.                                              |
| `body_text`                  | `TEXT`                           | `NULLABLE`                                | Plain text body content of the email.                                        |
| `received_at_header`         | `TIMESTAMP WITH TIME ZONE`       | `NULLABLE`                                | Timestamp from the email's `Date` header (or `INTERNALDATE`).                 |
| `ingested_at`                | `TIMESTAMP WITH TIME ZONE`       | `NOT NULL, DEFAULT CURRENT_TIMESTAMP`     | Timestamp when the email was added to this system.                           |
| `raw_headers`                | `JSONB`                          | `NULLABLE`                                | All raw email headers stored as JSON.                                        |
| `processing_status`          | `VARCHAR`                        | `NOT NULL, DEFAULT 'new'`                 | Current status: `new`, `spam_quarantined`, `queued_for_deepseek`, `error_ingestion`. |
| `apt_from_recipient_address` | `VARCHAR(20)`                    | `NULLABLE`                                | Extracted `apt*****` string from the recipient address (e.g., from `user+apt123@example.com`). |
| `error_details`              | `TEXT`                           | `NULLABLE`                                | Details of any error if `processing_status` is `error_ingestion`.            |
| `hash_body_text`             | `VARCHAR(64)`                    | `NULLABLE`                                | SHA256 hash of the `body_text` for deduplication or uniqueness checks.       |

**Indexes:**
*   `idx_emails_mailbox_folder_uid` (UNIQUE on `mailbox_id`, `folder_name`, `message_uid`)
*   `idx_emails_processing_status` (on `processing_status`)
*   `idx_emails_sender_address` (on `sender_address`)
*   `idx_emails_received_at_header` (on `received_at_header`)
*   `idx_emails_hash_body_text` (on `hash_body_text`)
*   Primary key on `id`

### 1.3. `blocked_senders` Table
Stores information about senders who are blocked.

| Column                   | Type                             | Constraints                               | Description                                                               |
|--------------------------|----------------------------------|-------------------------------------------|---------------------------------------------------------------------------|
| `id`                     | `INTEGER`                        | `PK, SERIAL`                              | Unique identifier for the blocked sender record.                            |
| `sender_address`         | `VARCHAR`                        | `UNIQUE, NOT NULL`                        | Email address of the blocked sender.                                        |
| `reason`                 | `TEXT`                           | `NULLABLE`                                | Reason for blocking (e.g., "Manually blocked").                           |
| `spam_strike_count`      | `INTEGER`                        | `NOT NULL, DEFAULT 0`                     | Count of spam strikes against the sender.                                 |
| `first_strike_at`        | `TIMESTAMP WITH TIME ZONE`       | `NULLABLE`                                | Timestamp of the first spam strike.                                       |
| `last_strike_at`         | `TIMESTAMP WITH TIME ZONE`       | `NULLABLE`                                | Timestamp of the most recent spam strike.                                 |
| `blocked_at`             | `TIMESTAMP WITH TIME ZONE`       | `NULLABLE`                                | Timestamp when the sender was effectively blocked.                        |
| `is_permanently_blocked` | `BOOLEAN`                        | `NOT NULL, DEFAULT FALSE`                 | Flag indicating if the sender is permanently blocked.                     |
| `created_at`             | `TIMESTAMP WITH TIME ZONE`       | `NOT NULL, DEFAULT CURRENT_TIMESTAMP`     | Timestamp of creation.                                                    |
| `updated_at`             | `TIMESTAMP WITH TIME ZONE`       | `NOT NULL, DEFAULT CURRENT_TIMESTAMP, ON UPDATE CURRENT_TIMESTAMP` | Timestamp of last update.                                                 |

**Indexes:**
*   `idx_blocked_senders_sender_address` (UNIQUE on `sender_address`)
*   Primary key on `id`

## 2. Service Logic

The Email Ingestor Service (`main.py`) operates in a continuous loop:

1.  **Initialization**:
    *   Loads configuration from environment variables (`app/config.py`).
    *   Sets up logging.
    *   Registers signal handlers for graceful shutdown.

2.  **Main Loop**:
    *   **Fetch Active Mailboxes**: Retrieves all mailboxes marked `is_active = TRUE` from the `mailboxes` table.
        *   Includes retry logic for database connection issues.
    *   **Process Each Mailbox**: For every active mailbox:
        *   **IMAP Connection**: Connects to the IMAP server using credentials from the `mailboxes` table (password is decrypted).
        *   **Fetch New Emails**:
            *   Selects each folder specified in `monitored_folders`.
            *   Uses the `last_checked_uid_map` to fetch only emails with UIDs greater than the last processed UID for that folder.
            *   Retrieves email headers and body (both text and HTML parts).
        *   **Email Parsing & Data Extraction**:
            *   Parses standard headers (From, To, Subject, Date, Message-ID). All headers are also stored in `raw_headers` (JSONB).
            *   Extracts `apt*****` from the recipient address (from `To` or `Cc` headers, e.g., `company+apt12345@example.com` yields `apt12345`).
            *   Calculates a SHA256 hash of the plain text body (`hash_body_text`).
            *   Converts the `Date` header to a timezone-aware timestamp (`received_at_header`).
        *   **Duplicate Check**: Verifies that the email (based on `mailbox_id`, `folder_name`, `message_uid`) has not already been processed and stored in the `emails` table.
        *   **Sender Check**: Checks if the `sender_address` is listed in `blocked_senders` with `is_permanently_blocked = TRUE`.
        *   **Save to Database**:
            *   If the sender is permanently blocked, the email is saved to the `emails` table with `processing_status = 'spam_quarantined'`.
            *   If an error occurs during parsing or fetching essential data (like `received_at_header`), the email might be saved with `processing_status = 'error_ingestion'` and error details.
            *   Otherwise, the email is saved with `processing_status = 'new'`.
        *   **Update `last_checked_uid_map`**: After successfully processing emails from a folder, the `last_checked_uid_map` for the mailbox is updated with the highest UID processed in that folder.
    *   **Publish to RabbitMQ**: For each email successfully saved with `processing_status = 'new'`:
        *   A JSON message (see format below) is published to the configured RabbitMQ queue (`email_processing_queue`).
        *   Upon successful publication, the email's `processing_status` in the `emails` table is updated to `queued_for_deepseek`.
    *   **Loop Interval**: The service waits for a configurable interval (`CHECK_INTERVAL_MINUTES`) before starting the next cycle.

3.  **Graceful Shutdown**:
    *   On receiving SIGINT or SIGTERM, the service attempts to finish ongoing tasks for the current email/mailbox, stops the main loop, and closes the RabbitMQ connection.

## 3. RabbitMQ JSON Message Format

When an email is successfully processed and is not from a blocked sender, a JSON message is published to the `email_processing_queue`.

**Queue Name**: `email_processing_queue` (configurable)

**Message Format**:
```json
{
  "db_email_id": 123,
  "mailbox_email_address": "user@example.com",
  "sender": "sender@domain.com",
  "recipient": "user@example.com",
  "subject": "Example Subject",
  "received_at_header": "2023-10-26T10:30:00+00:00", // ISO 8601 format
  "apt_from_recipient_address": "apt12345", // string, nullable
  "has_html_body": true, // boolean
  "has_text_body": true // boolean
}
```

**Field Descriptions**:
*   `db_email_id` (integer): The ID of the email record in the `emails` database table.
*   `mailbox_email_address` (string): The email address of the mailbox from which this email was ingested.
*   `sender` (string): The sender's email address.
*   `recipient` (string): The recipient address (the mailbox's own address).
*   `subject` (string): The subject of the email.
*   `received_at_header` (string, ISO 8601): The timestamp from the email's `Date` header. Nullable if date couldn't be parsed.
*   `apt_from_recipient_address` (string, nullable): The extracted `apt*****` identifier, if any.
*   `has_html_body` (boolean): `true` if the email has an HTML body, `false` otherwise.
*   `has_text_body` (boolean): `true` if the email has a plain text body, `false` otherwise.

## 4. Environment Variables

The service is configured using environment variables. A `.env` file can be used for local development (see `.env.example`).

| Variable                        | Default Value                             | Description                                                                  |
|---------------------------------|-------------------------------------------|------------------------------------------------------------------------------|
| `DATABASE_URL`                  | `postgresql://user:password@localhost:5432/email_ingestor_db` | PostgreSQL connection string.                                                |
| `RABBITMQ_URL`                  | `amqp://guest:guest@localhost:5672/`        | RabbitMQ connection URL.                                                     |
| `RABBITMQ_EMAIL_PROCESSING_QUEUE` | `email_processing_queue`                  | Name of the RabbitMQ queue for processed emails.                             |
| `CHECK_INTERVAL_MINUTES`        | `5`                                       | Interval in minutes at which to check mailboxes.                             |
| `LOG_LEVEL`                     | `INFO`                                    | Logging level (e.g., `DEBUG`, `INFO`, `WARNING`, `ERROR`).                   |
| `ENCRYPTION_KEY`                | `your_default_fernet_key_32_bytes`        | **MUST BE CHANGED**. 32-byte URL-safe base64-encoded key for Fernet encryption (used for IMAP passwords). Generate one using `Fernet.generate_key().decode()`. |
| `API_BASE_URL`                  | `/api/v1`                                 | (If API is implemented) Base URL for API endpoints.                          |
| `API_KEY`                       | `default_secret_api_key`                  | (If API is implemented) **MUST BE CHANGED**. Simple API key for securing management API endpoints. |

*(Optional: Add sections for Setup, Running the Service, Running Migrations, API Endpoints if the API part of the plan is implemented)*
