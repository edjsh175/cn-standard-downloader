import re


TABLE_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


BUSINESS_TABLE_SQL_TEMPLATE = """
CREATE TABLE IF NOT EXISTS `{table_name}` (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    standard_code VARCHAR(255) NOT NULL,
    keyword VARCHAR(255) NULL,
    draft_unit TEXT NULL,
    drafter TEXT NULL,
    chinese_name VARCHAR(512) NOT NULL,
    english_name VARCHAR(512) NULL,
    release_date VARCHAR(64) NULL,
    implement_date VARCHAR(64) NULL,
    release_unit VARCHAR(512) NULL,
    charge_unit VARCHAR(512) NULL,
    replace_standard TEXT NULL,
    standard_status VARCHAR(64) NULL,
    application_scope LONGTEXT NULL,
    reference_standard LONGTEXT NULL,
    pdf_path VARCHAR(1024) NULL,
    ps TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_standard_code (standard_code)
) CHARACTER SET utf8mb4
"""


def validate_table_name(table_name: str) -> str:
    normalized = str(table_name or "").strip()
    if not normalized:
        raise ValueError("table_name is required")
    if not TABLE_NAME_PATTERN.fullmatch(normalized):
        raise ValueError("table_name must match ^[A-Za-z_][A-Za-z0-9_]{0,63}$")
    return normalized


def build_business_table_sql(table_name: str) -> str:
    return BUSINESS_TABLE_SQL_TEMPLATE.format(table_name=validate_table_name(table_name))
