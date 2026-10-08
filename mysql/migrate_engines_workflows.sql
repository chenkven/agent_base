-- Run with a MySQL administrator account in DBeaver.
-- Re-running this file keeps existing rows.
USE agent_base;

CREATE TABLE IF NOT EXISTS session_engines (
  session_id CHAR(32) NOT NULL PRIMARY KEY,
  engine_id VARCHAR(64) NOT NULL,
  CONSTRAINT fk_session_engine_session FOREIGN KEY (session_id)
    REFERENCES sessions(session_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS workflows (
  workflow_id CHAR(32) NOT NULL PRIMARY KEY,
  user_id VARCHAR(32) NOT NULL,
  name VARCHAR(80) NOT NULL,
  description VARCHAR(500) NOT NULL DEFAULT '',
  engine_id VARCHAR(64) NOT NULL,
  steps_json LONGTEXT NOT NULL,
  updated_at BIGINT NOT NULL,
  INDEX workflows_owner (user_id, updated_at),
  CONSTRAINT fk_workflow_owner FOREIGN KEY (user_id) REFERENCES accounts(user_id)
    ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS workflow_runs (
  run_id CHAR(32) NOT NULL PRIMARY KEY,
  workflow_id CHAR(32) NOT NULL,
  user_id VARCHAR(32) NOT NULL,
  engine_id VARCHAR(64) NOT NULL,
  status ENUM('running', 'completed', 'failed') NOT NULL,
  input_text TEXT NOT NULL,
  output_text MEDIUMTEXT NULL,
  error_text TEXT NULL,
  started_at BIGINT NOT NULL,
  finished_at BIGINT NULL,
  INDEX workflow_runs_owner (user_id, started_at),
  CONSTRAINT fk_workflow_run_workflow FOREIGN KEY (workflow_id)
    REFERENCES workflows(workflow_id) ON DELETE CASCADE,
  CONSTRAINT fk_workflow_run_owner FOREIGN KEY (user_id)
    REFERENCES accounts(user_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS workflow_step_runs (
  run_id CHAR(32) NOT NULL,
  step_index INT NOT NULL,
  step_kind VARCHAR(20) NOT NULL,
  step_name VARCHAR(80) NOT NULL,
  status ENUM('running', 'completed', 'failed') NOT NULL,
  input_text MEDIUMTEXT NOT NULL,
  output_text MEDIUMTEXT NULL,
  error_text TEXT NULL,
  duration_ms BIGINT NULL,
  PRIMARY KEY (run_id, step_index),
  CONSTRAINT fk_workflow_step_run FOREIGN KEY (run_id)
    REFERENCES workflow_runs(run_id) ON DELETE CASCADE
) ENGINE=InnoDB;

USE agent_base_test;

CREATE TABLE IF NOT EXISTS session_engines (
  session_id CHAR(32) NOT NULL PRIMARY KEY,
  engine_id VARCHAR(64) NOT NULL,
  CONSTRAINT fk_test_session_engine_session FOREIGN KEY (session_id)
    REFERENCES sessions(session_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS workflows LIKE agent_base.workflows;
CREATE TABLE IF NOT EXISTS workflow_runs LIKE agent_base.workflow_runs;
CREATE TABLE IF NOT EXISTS workflow_step_runs LIKE agent_base.workflow_step_runs;
