-- Durable one-way import receipt; persona rows and this receipt commit together.
CREATE TABLE IF NOT EXISTS persona_imports (
    namespace VARBINARY(64) NOT NULL,
    snapshot_sha256 BINARY(32) NOT NULL,
    logical_sha256 BINARY(32) NOT NULL,
    record_count INT UNSIGNED NOT NULL,
    native_slots INT UNSIGNED NOT NULL,
    completed_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (namespace)
) ENGINE=InnoDB;
