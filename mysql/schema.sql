-- Run as a MySQL administrator. The application account is created separately.
CREATE DATABASE IF NOT EXISTS agent_base
  CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

USE agent_base;

CREATE TABLE IF NOT EXISTS accounts (
  user_id VARCHAR(32) NOT NULL PRIMARY KEY,
  role ENUM('admin', 'user') NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  disabled BOOLEAN NOT NULL DEFAULT FALSE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS login_sessions (
  token_hash CHAR(64) NOT NULL PRIMARY KEY,
  user_id VARCHAR(32) NOT NULL,
  secret_hash CHAR(64) NOT NULL,
  expires_at BIGINT NOT NULL,
  INDEX login_sessions_user_id (user_id),
  CONSTRAINT fk_login_user FOREIGN KEY (user_id) REFERENCES accounts(user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS sessions (
  session_id CHAR(32) NOT NULL PRIMARY KEY,
  user_id VARCHAR(32) NOT NULL,
  INDEX sessions_user_id (user_id),
  CONSTRAINT fk_chat_user FOREIGN KEY (user_id) REFERENCES accounts(user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS messages (
  id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
  session_id CHAR(32) NOT NULL,
  user_id VARCHAR(32) NOT NULL,
  role ENUM('user', 'assistant') NOT NULL,
  content MEDIUMTEXT NOT NULL,
  provider VARCHAR(64) NULL,
  model VARCHAR(128) NULL,
  created_at BIGINT NOT NULL,
  INDEX messages_session_id (session_id, id),
  INDEX messages_user_created (user_id, created_at),
  CONSTRAINT fk_message_session FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
  CONSTRAINT fk_message_user FOREIGN KEY (user_id) REFERENCES accounts(user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS login_attempts (
  key_hash CHAR(64) NOT NULL PRIMARY KEY,
  failures INT NOT NULL DEFAULT 0,
  first_failure BIGINT NOT NULL DEFAULT 0,
  locked_until BIGINT NOT NULL DEFAULT 0,
  INDEX login_attempts_first_failure (first_failure)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS model_catalog (
  provider VARCHAR(64) NOT NULL,
  model_id VARCHAR(128) NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  user_enabled BOOLEAN NOT NULL DEFAULT TRUE,
  PRIMARY KEY (provider, model_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS agent_profiles (
  agent_id VARCHAR(32) NOT NULL PRIMARY KEY,
  name VARCHAR(80) NOT NULL,
  instructions TEXT NOT NULL,
  delegate_id VARCHAR(32) NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_agent_grants (
  user_id VARCHAR(32) NOT NULL,
  agent_id VARCHAR(32) NOT NULL,
  PRIMARY KEY (user_id, agent_id),
  CONSTRAINT fk_grant_user FOREIGN KEY (user_id) REFERENCES accounts(user_id),
  CONSTRAINT fk_grant_agent FOREIGN KEY (agent_id) REFERENCES agent_profiles(agent_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS session_agents (
  session_id CHAR(32) NOT NULL PRIMARY KEY,
  agent_id VARCHAR(32) NOT NULL,
  CONSTRAINT fk_session_agent_session FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
  CONSTRAINT fk_session_agent_agent FOREIGN KEY (agent_id) REFERENCES agent_profiles(agent_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS session_engines (
  session_id CHAR(32) NOT NULL PRIMARY KEY,
  engine_id VARCHAR(64) NOT NULL,
  CONSTRAINT fk_session_engine_session FOREIGN KEY (session_id)
    REFERENCES sessions(session_id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS capability_catalog (
  capability_id VARCHAR(32) NOT NULL PRIMARY KEY,
  kind ENUM('prompt', 'skill', 'mcp') NOT NULL,
  name VARCHAR(80) NOT NULL,
  content MEDIUMTEXT NULL,
  endpoint VARCHAR(2048) NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS agent_capabilities (
  agent_id VARCHAR(32) NOT NULL,
  capability_id VARCHAR(32) NOT NULL,
  PRIMARY KEY (agent_id, capability_id),
  CONSTRAINT fk_agent_cap_agent FOREIGN KEY (agent_id) REFERENCES agent_profiles(agent_id),
  CONSTRAINT fk_agent_cap_catalog FOREIGN KEY (capability_id) REFERENCES capability_catalog(capability_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_capabilities (
  user_id VARCHAR(32) NOT NULL,
  capability_id VARCHAR(32) NOT NULL,
  kind ENUM('prompt', 'skill', 'mcp') NOT NULL,
  name VARCHAR(80) NOT NULL,
  content MEDIUMTEXT NULL,
  endpoint VARCHAR(2048) NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  approved BOOLEAN NOT NULL DEFAULT FALSE,
  PRIMARY KEY (user_id, capability_id),
  CONSTRAINT fk_user_cap_owner FOREIGN KEY (user_id) REFERENCES accounts(user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_agent_capabilities (
  user_id VARCHAR(32) NOT NULL,
  agent_id VARCHAR(32) NOT NULL,
  capability_id VARCHAR(32) NOT NULL,
  PRIMARY KEY (user_id, agent_id, capability_id),
  CONSTRAINT fk_user_agent_cap_owner FOREIGN KEY (user_id, capability_id)
    REFERENCES user_capabilities(user_id, capability_id) ON DELETE CASCADE,
  CONSTRAINT fk_user_agent_cap_agent FOREIGN KEY (agent_id)
    REFERENCES agent_profiles(agent_id)
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

INSERT IGNORE INTO agent_profiles (agent_id, name, instructions, enabled)
VALUES ('default', '通用助手', '', TRUE);

INSERT IGNORE INTO model_catalog (provider, model_id) VALUES
('deepseek-official', 'deepseek-v4-flash'), ('deepseek-official', 'deepseek-v4-pro'),
('qwen-bailian', 'qwen-plus'), ('qwen-bailian', 'qwen3.8-max'),
('qwen-bailian', 'qwen3.8-flash'), ('qwen-bailian', 'qwen3.7-max'),
('qwen-bailian', 'qwen3.7-plus'), ('qwen-bailian', 'qwen3.7-flash'),
('qwen-bailian', 'qwen3.6-plus'), ('qwen-bailian', 'qwen3.6-flash'),
('qwen-bailian', 'qwen3.5-plus'), ('qwen-bailian', 'qwen3.5-flash'),
('qwen-bailian', 'qwen3-max'), ('qwen-bailian', 'qwen-flash'),
('qwen-bailian', 'qwen-turbo'), ('qwen-bailian', 'qwen3-coder-plus'),
('qwen-bailian', 'qwen3-coder-flash'), ('openai', 'gpt-4.1-mini'),
('openai', 'gpt-4.1'), ('openai', 'gpt-4o-mini'), ('openai', 'gpt-4o'),
('openai', 'gpt-5-mini'), ('openai', 'gpt-5'),
('anthropic', 'claude-sonnet-4-5'), ('anthropic', 'claude-sonnet-4-6'),
('anthropic', 'claude-haiku-4-5'), ('anthropic', 'claude-opus-4-5'),
('anthropic', 'claude-opus-4-6'), ('moonshotai', 'kimi-k2.5'),
('moonshotai', 'kimi-k2-thinking'), ('moonshotai', 'kimi-k2-0905-preview'),
('moonshotai', 'kimi-k3'), ('zai', 'glm-4.7'), ('zai', 'glm-5.2');
