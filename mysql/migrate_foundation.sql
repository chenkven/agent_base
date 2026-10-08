-- Run in DBeaver with a MySQL account that can CREATE TABLE in both databases.
-- Idempotent: existing accounts, sessions, and messages are not deleted.

USE agent_base;

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

USE agent_base_test;

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
