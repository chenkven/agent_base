-- Run the whole script in DBeaver as a MySQL administrator.
-- Existing account and chat data is preserved. Safe to run again.

USE agent_base;

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

INSERT IGNORE INTO agent_profiles (agent_id, name, instructions, enabled)
VALUES ('default', '通用助手', '', TRUE);

INSERT IGNORE INTO model_catalog (provider, model_id) VALUES
('deepseek-official', 'deepseek-v4-flash'),
('deepseek-official', 'deepseek-v4-pro'),
('qwen-bailian', 'qwen-plus'),
('qwen-bailian', 'qwen3.8-max'),
('qwen-bailian', 'qwen3.8-flash'),
('qwen-bailian', 'qwen3.7-max'),
('qwen-bailian', 'qwen3.7-plus'),
('qwen-bailian', 'qwen3.7-flash'),
('qwen-bailian', 'qwen3.6-plus'),
('qwen-bailian', 'qwen3.6-flash'),
('qwen-bailian', 'qwen3.5-plus'),
('qwen-bailian', 'qwen3.5-flash'),
('qwen-bailian', 'qwen3-max'),
('qwen-bailian', 'qwen-flash'),
('qwen-bailian', 'qwen-turbo'),
('qwen-bailian', 'qwen3-coder-plus'),
('qwen-bailian', 'qwen3-coder-flash'),
('openai', 'gpt-4.1-mini'),
('openai', 'gpt-4.1'),
('openai', 'gpt-4o-mini'),
('openai', 'gpt-4o'),
('openai', 'gpt-5-mini'),
('openai', 'gpt-5'),
('anthropic', 'claude-sonnet-4-5'),
('anthropic', 'claude-sonnet-4-6'),
('anthropic', 'claude-haiku-4-5'),
('anthropic', 'claude-opus-4-5'),
('anthropic', 'claude-opus-4-6'),
('moonshotai', 'kimi-k2.5'),
('moonshotai', 'kimi-k2-thinking'),
('moonshotai', 'kimi-k2-0905-preview'),
('moonshotai', 'kimi-k3'),
('zai', 'glm-4.7'),
('zai', 'glm-5.2');

USE agent_base_test;

CREATE TABLE IF NOT EXISTS model_catalog LIKE agent_base.model_catalog;
CREATE TABLE IF NOT EXISTS agent_profiles LIKE agent_base.agent_profiles;
CREATE TABLE IF NOT EXISTS user_agent_grants (
  user_id VARCHAR(32) NOT NULL,
  agent_id VARCHAR(32) NOT NULL,
  PRIMARY KEY (user_id, agent_id),
  CONSTRAINT fk_test_grant_user FOREIGN KEY (user_id) REFERENCES accounts(user_id),
  CONSTRAINT fk_test_grant_agent FOREIGN KEY (agent_id) REFERENCES agent_profiles(agent_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS session_agents (
  session_id CHAR(32) NOT NULL PRIMARY KEY,
  agent_id VARCHAR(32) NOT NULL,
  CONSTRAINT fk_test_session_agent_session FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE,
  CONSTRAINT fk_test_session_agent_agent FOREIGN KEY (agent_id) REFERENCES agent_profiles(agent_id)
) ENGINE=InnoDB;
CREATE TABLE IF NOT EXISTS capability_catalog LIKE agent_base.capability_catalog;
CREATE TABLE IF NOT EXISTS agent_capabilities (
  agent_id VARCHAR(32) NOT NULL,
  capability_id VARCHAR(32) NOT NULL,
  PRIMARY KEY (agent_id, capability_id),
  CONSTRAINT fk_test_agent_cap_agent FOREIGN KEY (agent_id) REFERENCES agent_profiles(agent_id),
  CONSTRAINT fk_test_agent_cap_catalog FOREIGN KEY (capability_id) REFERENCES capability_catalog(capability_id)
) ENGINE=InnoDB;
INSERT IGNORE INTO agent_profiles (agent_id, name, instructions, enabled)
VALUES ('default', '通用助手', '', TRUE);
INSERT IGNORE INTO model_catalog (provider, model_id)
SELECT provider, model_id FROM agent_base.model_catalog;
INSERT IGNORE INTO model_catalog (provider, model_id) VALUES
('deepseek-official', 'test-model'),
('deepseek-official', 'deepseek-v4-pro'),
('zai', 'bad-model');
