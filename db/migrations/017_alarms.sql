-- Health alarms: one row each time a check starts failing, closed when it works again.
-- Only one alarm per check can be active at a time.

CREATE TABLE alarms (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id      BIGINT NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    check_key    TEXT NOT NULL,  -- e.g. "database", "job:task_scan", "integration:mcp:3"
    name         TEXT NOT NULL,  -- what failed, as the owner sees it
    problem      TEXT NOT NULL,
    started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at  TIMESTAMPTZ
);

CREATE UNIQUE INDEX alarms_one_active_per_check_idx ON alarms (user_id, check_key) WHERE resolved_at IS NULL;
CREATE INDEX alarms_user_id_started_at_idx ON alarms (user_id, started_at DESC);
