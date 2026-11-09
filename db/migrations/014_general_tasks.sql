-- Tasks can be anything the owner still has to do, so there are no fixed types. The model pairs a confirmation
-- with its task, so the columns that matched them by company and sender aren't needed either.

ALTER TABLE tracked_tasks
    DROP COLUMN kind,
    DROP COLUMN company_key,
    DROP COLUMN sender_domain,
    DROP COLUMN subject_key;

ALTER TABLE tracked_tasks RENAME COLUMN invite_message_id TO request_message_id;
ALTER TABLE tracked_tasks RENAME COLUMN invite_date TO request_date;

ALTER TABLE scanned_emails
    DROP COLUMN kind,
    DROP COLUMN company_key,
    DROP COLUMN sender_domain,
    DROP CONSTRAINT scanned_emails_verdict_check,
    ADD CONSTRAINT scanned_emails_verdict_check
        CHECK (verdict IN ('task', 'same_task', 'completion', 'neither', 'discarded'));

ALTER TABLE task_scan_state RENAME COLUMN needs_model_count TO waiting_count;
