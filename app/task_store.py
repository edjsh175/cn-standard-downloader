import json
import uuid
from contextlib import closing
from typing import Any

import pymysql

import config
from app.db_utils import build_business_table_sql, validate_table_name

DEFAULT_BUSINESS_TABLE_NAME = "gb_standards"
BUSINESS_REQUIRED_COLUMNS = {
    "id",
    "standard_code",
    "keyword",
    "draft_unit",
    "drafter",
    "chinese_name",
    "english_name",
    "release_date",
    "implement_date",
    "release_unit",
    "charge_unit",
    "replace_standard",
    "standard_status",
    "application_scope",
    "reference_standard",
    "pdf_path",
    "ps",
}


class TaskStore:
    def __init__(self):
        self.ensure_task_tables()
        self.ensure_business_table(DEFAULT_BUSINESS_TABLE_NAME)

    def _connect(self):
        return pymysql.connect(**config.DB_CONFIG, charset="utf8mb4", autocommit=True)

    @staticmethod
    def _dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _loads(value: Any):
        if not value:
            return None
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)

    def ensure_task_tables(self):
        tasks_sql = """
        CREATE TABLE IF NOT EXISTS crawl_tasks (
            id VARCHAR(36) PRIMARY KEY,
            task_type VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL,
            table_name VARCHAR(255) NOT NULL,
            request_payload LONGTEXT NOT NULL,
            idempotency_key VARCHAR(128) NULL,
            result_payload LONGTEXT NULL,
            error_message TEXT NULL,
            cancel_requested TINYINT(1) NOT NULL DEFAULT 0,
            lease_owner VARCHAR(128) NULL,
            lease_until DATETIME NULL,
            heartbeat_at DATETIME NULL,
            attempt_count INT NOT NULL DEFAULT 0,
            timeout_seconds INT NULL,
            priority INT NOT NULL DEFAULT 0,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at DATETIME NULL,
            finished_at DATETIME NULL,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uniq_task_idempotency (idempotency_key)
        ) CHARACTER SET utf8mb4
        """
        items_sql = """
        CREATE TABLE IF NOT EXISTS crawl_task_items (
            id BIGINT PRIMARY KEY AUTO_INCREMENT,
            task_id VARCHAR(36) NOT NULL,
            detail_url VARCHAR(1024) NOT NULL,
            code VARCHAR(255) NULL,
            name VARCHAR(512) NULL,
            keyword VARCHAR(255) NULL,
            item_status VARCHAR(32) NOT NULL DEFAULT 'pending',
            pdf_path VARCHAR(1024) NULL,
            error_message TEXT NULL,
            meta_payload LONGTEXT NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uniq_task_url (task_id, detail_url(255))
        ) CHARACTER SET utf8mb4
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(tasks_sql)
            cursor.execute(items_sql)
            self._ensure_task_columns(cursor)

    @staticmethod
    def _ensure_task_columns(cursor):
        """Add lifecycle columns to databases created before task leases existed."""

        cursor.execute("SHOW COLUMNS FROM crawl_tasks")
        existing = {row[0] for row in cursor.fetchall()}
        definitions = {
            "idempotency_key": "VARCHAR(128) NULL",
            "lease_owner": "VARCHAR(128) NULL",
            "lease_until": "DATETIME NULL",
            "heartbeat_at": "DATETIME NULL",
            "attempt_count": "INT NOT NULL DEFAULT 0",
            "timeout_seconds": "INT NULL",
            "priority": "INT NOT NULL DEFAULT 0",
        }
        for column, definition in definitions.items():
            if column not in existing:
                cursor.execute(f"ALTER TABLE crawl_tasks ADD COLUMN {column} {definition}")

        cursor.execute("SHOW INDEX FROM crawl_tasks")
        indexes = {row[2] for row in cursor.fetchall() if len(row) > 2}
        if "uniq_task_idempotency" not in indexes:
            cursor.execute("ALTER TABLE crawl_tasks ADD UNIQUE KEY uniq_task_idempotency (idempotency_key)")

    @staticmethod
    def _table_columns(cursor, table_name: str) -> set[str]:
        cursor.execute(f"SHOW COLUMNS FROM `{table_name}`")
        return {row[0] for row in cursor.fetchall()}

    @staticmethod
    def _is_business_table(cursor, table_name: str) -> bool:
        try:
            columns = TaskStore._table_columns(cursor, table_name)
        except pymysql.MySQLError:
            return False
        return BUSINESS_REQUIRED_COLUMNS.issubset(columns)

    def ensure_business_table(self, table_name: str):
        sql = build_business_table_sql(table_name)
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql)
            if not self._is_business_table(cursor, table_name):
                raise ValueError(
                    f"table_name '{table_name}' is not a compatible crawler business table; "
                    f"use '{DEFAULT_BUSINESS_TABLE_NAME}' or another table created by the crawler"
                )

    def create_task(self, task_type: str, payload: dict[str, Any]) -> str:
        idempotency_key = str(payload.get("idempotency_key") or "").strip() or None
        if idempotency_key:
            sql = "SELECT id FROM crawl_tasks WHERE idempotency_key=%s LIMIT 1"
            with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
                cursor.execute(sql, (idempotency_key,))
                row = cursor.fetchone()
            if row:
                return str(row[0])

        raw_table_name = str(payload.get("table_name") or "").strip()
        table_name = ""
        if task_type == "search_only":
            if raw_table_name:
                table_name = validate_table_name(raw_table_name)
        else:
            table_name = validate_table_name(raw_table_name or DEFAULT_BUSINESS_TABLE_NAME)
            payload["table_name"] = table_name
            self.ensure_business_table(table_name)
        task_id = str(uuid.uuid4())
        sql = """
        INSERT INTO crawl_tasks (id, task_type, status, table_name, request_payload, idempotency_key)
        VALUES (%s, %s, 'pending', %s, %s, %s)
        """
        params = (
            task_id,
            task_type,
            table_name,
            self._dumps(payload),
            idempotency_key,
        )
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql, params)
        return task_id

    def list_tables(self):
        sql = "SHOW TABLES"
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
            tables = [row[0] for row in rows]
            return [table for table in tables if self._is_business_table(cursor, table)]

    def mark_running(self, task_id: str):
        sql = """
        UPDATE crawl_tasks
        SET status='running', started_at=NOW()
        WHERE id=%s
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql, (task_id,))

    def claim_task(self, task_id: str, lease_owner: str, lease_seconds: int = 300) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        sql = """
        UPDATE crawl_tasks
        SET status='running',
            started_at=COALESCE(started_at, NOW()),
            heartbeat_at=NOW(),
            lease_owner=%s,
            lease_until=DATE_ADD(NOW(), INTERVAL %s SECOND),
            attempt_count=attempt_count+1
        WHERE id=%s
          AND status IN ('pending', 'queued')
          AND cancel_requested=0
          AND (lease_until IS NULL OR lease_until < NOW())
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql, (lease_owner, lease_seconds, task_id))
            return cursor.rowcount == 1

    def heartbeat_task(self, task_id: str, lease_owner: str, lease_seconds: int = 300) -> bool:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        sql = """
        UPDATE crawl_tasks
        SET heartbeat_at=NOW(), lease_until=DATE_ADD(NOW(), INTERVAL %s SECOND)
        WHERE id=%s AND status='running' AND lease_owner=%s
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql, (lease_seconds, task_id, lease_owner))
            return cursor.rowcount == 1

    def release_lease(self, task_id: str, lease_owner: str | None = None):
        sql = """
        UPDATE crawl_tasks
        SET lease_owner=NULL, lease_until=NULL, heartbeat_at=NULL
        WHERE id=%s AND (%s IS NULL OR lease_owner=%s)
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql, (task_id, lease_owner, lease_owner))

    def recover_expired_tasks(self) -> int:
        sql = """
        UPDATE crawl_tasks
        SET status='pending', lease_owner=NULL, lease_until=NULL, heartbeat_at=NULL
        WHERE status='running' AND lease_until IS NOT NULL AND lease_until < NOW()
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql)
            return cursor.rowcount

    def list_runnable_task_ids(self) -> list[str]:
        sql = """
        SELECT id
        FROM crawl_tasks
        WHERE status IN ('pending', 'queued') AND cancel_requested=0
        ORDER BY priority DESC, created_at ASC
        """
        with closing(self._connect()) as conn, closing(conn.cursor(pymysql.cursors.DictCursor)) as cursor:
            cursor.execute(sql)
            rows = cursor.fetchall()
        return [str(row["id"] if isinstance(row, dict) else row[0]) for row in rows]

    def mark_succeeded(self, task_id: str, result_payload: dict[str, Any]):
        sql = """
        UPDATE crawl_tasks
        SET status='succeeded', result_payload=%s, finished_at=NOW()
        WHERE id=%s
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql, (self._dumps(result_payload), task_id))

    def mark_completed(
        self,
        task_id: str,
        status: str,
        result_payload: dict[str, Any],
        error_message: str | None = None,
    ):
        sql = """
        UPDATE crawl_tasks
        SET status=%s, result_payload=%s, error_message=%s, finished_at=NOW()
        WHERE id=%s
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql, (status, self._dumps(result_payload), error_message, task_id))

    def mark_failed(self, task_id: str, error_message: str):
        sql = """
        UPDATE crawl_tasks
        SET status='failed', error_message=%s, finished_at=NOW()
        WHERE id=%s
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql, (error_message, task_id))

    def mark_cancelled(self, task_id: str, result_payload: dict[str, Any] | None = None):
        sql = """
        UPDATE crawl_tasks
        SET status='cancelled', result_payload=%s, finished_at=NOW()
        WHERE id=%s
        """
        payload = self._dumps(result_payload) if result_payload is not None else None
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql, (payload, task_id))

    def request_cancel(self, task_id: str):
        sql = """
        UPDATE crawl_tasks
        SET cancel_requested=1
        WHERE id=%s
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql, (task_id,))

    def is_cancel_requested(self, task_id: str) -> bool:
        sql = "SELECT cancel_requested FROM crawl_tasks WHERE id=%s"
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(sql, (task_id,))
            row = cursor.fetchone()
        return bool(row and row[0])

    def get_task(self, task_id: str):
        sql = """
        SELECT id, task_type, status, table_name, request_payload, result_payload,
               error_message, cancel_requested, created_at, started_at, finished_at, updated_at
        FROM crawl_tasks
        WHERE id=%s
        """
        with closing(self._connect()) as conn, closing(conn.cursor(pymysql.cursors.DictCursor)) as cursor:
            cursor.execute(sql, (task_id,))
            row = cursor.fetchone()
        if not row:
            return None
        row["request_payload"] = self._loads(row["request_payload"])
        row["result_payload"] = self._loads(row["result_payload"])
        row["cancel_requested"] = bool(row["cancel_requested"])
        for key in ("created_at", "started_at", "finished_at", "updated_at"):
            value = row.get(key)
            if value is not None:
                row[key] = value.isoformat()
        return row

    def upsert_task_items(self, task_id: str, items: list[dict[str, Any]], item_status: str = "pending"):
        sql = """
        INSERT INTO crawl_task_items (task_id, detail_url, code, name, keyword, item_status, meta_payload)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            code=VALUES(code),
            name=VALUES(name),
            keyword=VALUES(keyword),
            item_status=VALUES(item_status),
            meta_payload=VALUES(meta_payload),
            updated_at=CURRENT_TIMESTAMP
        """
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            for item in items:
                cursor.execute(
                    sql,
                    (
                        task_id,
                        item["detail_url"],
                        item.get("code"),
                        item.get("name"),
                        item.get("keyword"),
                        item_status,
                        self._dumps(item),
                    ),
                )

    def update_task_item(
        self,
        task_id: str,
        detail_url: str,
        item_status: str,
        pdf_path: str | None = None,
        error_message: str | None = None,
        meta_payload: dict[str, Any] | None = None,
        code: str | None = None,
        name: str | None = None,
        keyword: str | None = None,
    ):
        sql = """
        UPDATE crawl_task_items
        SET item_status=%s,
            pdf_path=%s,
            error_message=%s,
            meta_payload=%s,
            code=COALESCE(%s, code),
            name=COALESCE(%s, name),
            keyword=COALESCE(%s, keyword)
        WHERE task_id=%s AND detail_url=%s
        """
        payload = self._dumps(meta_payload) if meta_payload is not None else None
        with closing(self._connect()) as conn, closing(conn.cursor()) as cursor:
            cursor.execute(
                sql,
                (
                    item_status,
                    pdf_path,
                    error_message,
                    payload,
                    code,
                    name,
                    keyword,
                    task_id,
                    detail_url,
                ),
            )

    def list_task_items(self, task_id: str):
        sql = """
        SELECT id, detail_url, code, name, keyword, item_status, pdf_path, error_message, meta_payload
        FROM crawl_task_items
        WHERE task_id=%s
        ORDER BY id ASC
        """
        with closing(self._connect()) as conn, closing(conn.cursor(pymysql.cursors.DictCursor)) as cursor:
            cursor.execute(sql, (task_id,))
            rows = cursor.fetchall()
        for row in rows:
            row["meta_payload"] = self._loads(row["meta_payload"])
        return rows

    def get_task_item(self, task_id: str, item_id: int):
        sql = """
        SELECT id, detail_url, code, name, keyword, item_status, pdf_path, error_message, meta_payload
        FROM crawl_task_items
        WHERE task_id=%s AND id=%s
        LIMIT 1
        """
        with closing(self._connect()) as conn, closing(conn.cursor(pymysql.cursors.DictCursor)) as cursor:
            cursor.execute(sql, (task_id, item_id))
            row = cursor.fetchone()
        if not row:
            return None
        row["meta_payload"] = self._loads(row["meta_payload"])
        return row
