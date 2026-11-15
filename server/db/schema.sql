-- ark minimal schema (milestone 1 scaffold + auth tables)
-- Domain tables (runs, messages, blobs meta, overlays) land in milestone 2.
-- Apply with: .helpers/run-db-command.sh < server/db/schema.sql
-- UTC contract: store DATETIME in UTC; pool sets time_zone = '+00:00'.

SET NAMES utf8mb4;
SET time_zone = '+00:00';

CREATE TABLE IF NOT EXISTS `users` (
  `user_id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `email` varchar(255) NOT NULL,
  `password_hash` varchar(255) NOT NULL,
  `first_name` varchar(100) DEFAULT NULL,
  `last_name` varchar(100) DEFAULT NULL,
  `user_level` enum('ADMIN','USER') NOT NULL DEFAULT 'USER',
  `user_status` enum('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE',
  `timezone` varchar(100) NOT NULL DEFAULT 'America/Los_Angeles',
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`user_id`),
  UNIQUE KEY `email` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `options` (
  `option_name` varchar(191) NOT NULL,
  `option_value` text DEFAULT NULL,
  PRIMARY KEY (`option_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- sessions table is created by express-mysql-session when the app starts.

CREATE TABLE IF NOT EXISTS `api_keys` (
  `api_key_id` bigint unsigned NOT NULL AUTO_INCREMENT,
  `name` varchar(128) NOT NULL,
  `key_hash` varchar(255) NOT NULL,
  `enabled` tinyint(1) NOT NULL DEFAULT 1,
  `last_used_at` datetime DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` datetime NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`api_key_id`),
  KEY `idx_api_keys_enabled` (`enabled`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
