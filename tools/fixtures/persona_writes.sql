-- Apply only to a private experimental store, quiescent during backfill.
-- Administration must assign a fresh nonzero generation to every persona.
ALTER TABLE personas ADD generation BINARY(9) NULL;
CREATE TABLE persona_operations (
    namespace VARBINARY(64) NOT NULL,
    operation_id BINARY(9) NOT NULL,
    name_key BINARY(9) NULL,
    status VARCHAR(16) CHARACTER SET ascii NOT NULL,
    kind VARCHAR(8) CHARACTER SET ascii NOT NULL DEFAULT 'UPDATE',
    cursor_key BINARY(9) NULL,
    generation BINARY(9) NULL,
    revision BIGINT UNSIGNED NULL,
    before_words JSON NULL,
    after_words JSON NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (namespace, operation_id)
) ENGINE=InnoDB;
