-- Run all statements in DBeaver with an administrator connection.
-- Existing accounts, public capabilities, and conversations are preserved.
USE agent_base;

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

USE agent_base_test;

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
  CONSTRAINT fk_test_user_cap_owner FOREIGN KEY (user_id) REFERENCES accounts(user_id)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS user_agent_capabilities (
  user_id VARCHAR(32) NOT NULL,
  agent_id VARCHAR(32) NOT NULL,
  capability_id VARCHAR(32) NOT NULL,
  PRIMARY KEY (user_id, agent_id, capability_id),
  CONSTRAINT fk_test_user_agent_cap_owner FOREIGN KEY (user_id, capability_id)
    REFERENCES user_capabilities(user_id, capability_id) ON DELETE CASCADE,
  CONSTRAINT fk_test_user_agent_cap_agent FOREIGN KEY (agent_id)
    REFERENCES agent_profiles(agent_id)
) ENGINE=InnoDB;
