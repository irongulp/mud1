-- Legacy format-1 fixture, retained for compatibility/corrupt-row tests.
-- New schema initialization uses tools.persona_columns.table_ddl(), format 2.
-- The runtime getter requires SELECT only and never executes this DDL.
CREATE TABLE personas (
    namespace VARBINARY(64) NOT NULL,
    name_key BINARY(9) NOT NULL,
    format_version SMALLINT UNSIGNED NOT NULL,
    words JSON NOT NULL,
    revision BIGINT UNSIGNED NOT NULL DEFAULT 1,
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (namespace, name_key)
) ENGINE=InnoDB;
