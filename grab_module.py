import json
import os
import re
import shutil
import time
from html import unescape
from hashlib import md5
from urllib.parse import urljoin, urlparse

import pandas as pd
import pymysql
import requests
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from app.db_utils import validate_table_name
from app.agent_contract import classify_error_code
from app.scrapling_parser import parse_detail_meta
from config import (
    BASE_PDF_DIR,
    CAPTCHA_CODE_TYPE,
    CHAOJIYING_PASS,
    CHAOJIYING_SOFT_ID,
    CHAOJIYING_USER,
    DB_CONFIG,
    DEBUG_DIR,
    ELEMENT_TIMEOUT,
    IMG_PATH,
    INPUT_FILE,
    PDF_DOWNLOAD_TIMEOUT,
    TEMP_DIR,
    XPATHS_MAPPING,
)
from utils import (
    clean_text,
    ensure_dir,
    infer_standard_type,
    init_driver,
    init_logger,
    read_excel,
)


class Chaojiying_Client:
    def __init__(self, username, password, soft_id):
        self.username = username
        self.password = md5(password.encode("utf-8")).hexdigest()
        self.soft_id = soft_id
        self.base_params = {"user": self.username, "pass2": self.password, "softid": self.soft_id}
        self.headers = {
            "Connection": "Keep-Alive",
            "User-Agent": "Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 5.1; Trident/4.0)",
        }

    def PostPic(self, im, codetype):
        params = {"codetype": codetype}
        params.update(self.base_params)
        files = {"userfile": ("captcha.jpg", im)}
        try:
            return requests.post(
                "http://upload.chaojiying.net/Upload/Processing.php",
                data=params,
                files=files,
                headers=self.headers,
            ).json()
        except Exception as exc:
            logger = init_logger()
            logger.error(f"captcha platform request failed: {exc}")
            return {"err_no": -1, "err_str": "captcha platform request failed"}


class BatchCrawler:
    STANDARD_CODE_PATTERN = re.compile(
        r"\b(?:[A-Z]{2,3})(?:/[A-Z])?(?:\s*[A-Z])?\s*\d[\dA-Z.\-\/ ]{1,40}\d\b"
    )

    def __init__(self, log_file=None, cancel_checker=None, duplicate_policy="overwrite"):
        self.logger = init_logger(log_file or "s2_all_standard_db_adapt.log")
        self.cancel_checker = cancel_checker
        self.duplicate_policy = duplicate_policy if duplicate_policy in {"overwrite", "skip"} else "overwrite"
        self.WAIT_TIME = ELEMENT_TIMEOUT
        self.current_code = ""
        self.failed_items = []
        self.download_summaries = {}
        self.write_results = {}
        self.processed_results = {}
        self.setup_env()
        self.cjy = Chaojiying_Client(CHAOJIYING_USER, CHAOJIYING_PASS, CHAOJIYING_SOFT_ID)

    def _check_cancelled(self):
        if self.cancel_checker and self.cancel_checker():
            raise RuntimeError("Task cancelled")

    def setup_env(self):
        ensure_dir(TEMP_DIR)
        ensure_dir(BASE_PDF_DIR)
        ensure_dir(DEBUG_DIR)

        self.logger.info(f"temp dir: {os.path.abspath(TEMP_DIR)}")
        self.logger.info(f"pdf dir: {os.path.abspath(BASE_PDF_DIR)}")
        self.logger.info(f"debug dir: {os.path.abspath(DEBUG_DIR)}")

        self.db = pymysql.connect(**DB_CONFIG, charset="utf8mb4")
        self.cursor = self.db.cursor()
        self.logger.info("database connected")

        self._init_driver()

    def _init_driver(self):
        self.driver = init_driver(TEMP_DIR)
        self.driver.set_page_load_timeout(30)
        self.logger.info("browser initialized")

    def _ensure_driver_alive(self):
        need_restart = False
        if self.driver is None:
            need_restart = True
        else:
            try:
                _ = self.driver.current_window_handle
            except Exception:
                need_restart = True
        if not need_restart:
            return

        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
        self._init_driver()

    def _safe_name(self, value):
        return re.sub(r'[\\/*?"<>|:]+', "_", str(value or "")).strip() or "unknown"

    def _debug_prefix(self):
        return self._safe_name(self.current_code or "task")

    def _debug_path(self, suffix, ext):
        return os.path.join(DEBUG_DIR, f"{self._debug_prefix()}_{suffix}.{ext}")

    def _write_debug_file(self, suffix, content, ext="txt"):
        path = self._debug_path(suffix, ext)
        mode = "wb" if isinstance(content, bytes) else "w"
        kwargs = {} if mode == "wb" else {"encoding": "utf-8"}
        with open(path, mode, **kwargs) as file_obj:
            file_obj.write(content)
        return path

    def _save_page_source(self, suffix):
        try:
            return self._write_debug_file(suffix, self.driver.page_source, "html")
        except Exception as exc:
            self.logger.warning(f"save page source failed: {exc}")
            return None

    def _save_screenshot(self, suffix):
        path = self._debug_path(suffix, "png")
        try:
            self.driver.save_screenshot(path)
            return path
        except Exception as exc:
            self.logger.warning(f"save screenshot failed: {exc}")
            return None

    def _save_element_screenshot(self, element, suffix):
        path = self._debug_path(suffix, "png")
        try:
            element.screenshot(path)
            return path
        except Exception as exc:
            self.logger.warning(f"save element screenshot failed: {exc}")
            return None

    def _switch_to_available_window(self, known_handles=None, preferred_handle=None):
        try:
            handles = list(self.driver.window_handles)
        except Exception:
            return False
        if not handles:
            return False

        target = None
        if preferred_handle in handles:
            target = preferred_handle
        elif known_handles:
            new_handles = [handle for handle in handles if handle not in set(known_handles)]
            target = new_handles[-1] if new_handles else handles[-1]
        else:
            target = handles[-1]

        try:
            self.driver.switch_to.window(target)
            return True
        except Exception:
            return False

    @staticmethod
    def _first_visible_enabled(elements):
        for element in elements:
            try:
                if element.is_displayed() and element.is_enabled():
                    return element
            except Exception:
                continue
        return elements[0] if elements else None

    def _safe_current_url(self, default=""):
        try:
            return self.driver.current_url
        except Exception:
            if self._switch_to_available_window():
                try:
                    return self.driver.current_url
                except Exception:
                    return default
            return default

    def _new_download_summary(self, row, standard_type):
        return {
            "code": row.get("code"),
            "detail_url": row.get("detail_url"),
            "standard_type": standard_type,
            "direct_download_used": False,
            "download_url_resolved": False,
            "session_extracted": False,
            "pdf_saved": False,
            "transport": None,
            "request_url": None,
            "request_method": None,
            "http_status": None,
            "content_type": None,
            "error_stage": None,
            "debug_files": [],
        }

    def _record_download_summary(self, detail_url, summary):
        if detail_url:
            self.download_summaries[detail_url] = dict(summary)

    def _has_failed_item(self, detail_url):
        if not detail_url:
            return False
        return any(item.get("detail_url") == detail_url for item in self.failed_items)

    def _first_non_empty_text(self, xpath_candidates):
        for xpath in xpath_candidates:
            try:
                elements = self.driver.find_elements(By.XPATH, xpath)
            except Exception:
                continue
            for element in elements:
                text = clean_text(element.text)
                if text:
                    return text
        return ""

    def _normalize_standard_code(self, value):
        code = clean_text(value).upper()
        code = re.sub(r"\s+", " ", code)
        code = re.sub(r"\s*([\-－])\s*", r"\1", code)
        return code.strip()

    def _extract_identity_from_text(self, text):
        cleaned = clean_text(text)
        if not cleaned:
            return "", ""

        match = self.STANDARD_CODE_PATTERN.search(cleaned)
        if not match:
            return "", ""

        code = self._normalize_standard_code(match.group(0))
        name = cleaned[match.end():].strip(" :-：|_/")
        return code, clean_text(name)

    def _extract_name_from_current_standard_panel(self, code):
        if not code:
            return ""

        try:
            html = self.driver.page_source or ""
        except Exception:
            return ""

        pattern = re.compile(
            rf"{re.escape(code)}[\s\S]{{0,1200}}?<div[^>]*class=[\"'][^\"']*replA[^\"']*[\"'][^>]*>([\s\S]*?)</div>",
            re.IGNORECASE,
        )
        for match in pattern.finditer(html):
            candidate = re.sub(r"<[^>]+>", " ", match.group(1))
            candidate = clean_text(unescape(candidate))
            if candidate and candidate != "\u76ee\u5f55":
                return candidate
        return ""

    def _extract_standard_identity(self, code, name):
        resolved_code = clean_text(code)
        resolved_name = clean_text(name)

        if not resolved_code:
            code_text = self._first_non_empty_text(
                [
                    '//dt[contains(text(), "标准号")]/following-sibling::dd[1]',
                    '//dt[contains(text(), "标准编号")]/following-sibling::dd[1]',
                    '//dt[contains(text(), "标准代号")]/following-sibling::dd[1]',
                ]
            )
            if code_text:
                extracted_code, extracted_name = self._extract_identity_from_text(code_text)
                resolved_code = extracted_code or self._normalize_standard_code(code_text)
                if not resolved_name and extracted_name:
                    resolved_name = extracted_name

        if not resolved_name or resolved_name == "\u76ee\u5f55":
            panel_name = self._extract_name_from_current_standard_panel(resolved_code)
            if panel_name:
                resolved_name = panel_name

        if not resolved_name:
            resolved_name = self._first_non_empty_text(
                [
                    '//dt[contains(text(), "标准名称")]/following-sibling::dd[1]',
                    '//dt[contains(text(), "中文标准名称")]/following-sibling::dd[1]',
                    "//h1",
                    "//h2",
                ]
            )

        combined_candidates = [
            resolved_name,
            self._first_non_empty_text(["//h1", "//h2"]),
            clean_text(getattr(self.driver, "title", "")),
        ]
        try:
            body_text = clean_text(self.driver.find_element(By.TAG_NAME, "body").text)
            combined_candidates.append(body_text[:500])
        except Exception:
            pass

        for candidate in combined_candidates:
            extracted_code, extracted_name = self._extract_identity_from_text(candidate)
            if not resolved_code and extracted_code:
                resolved_code = extracted_code
            if not resolved_name and extracted_name:
                resolved_name = extracted_name
            if resolved_code and resolved_name:
                break

        if resolved_code and resolved_name.startswith(resolved_code):
            resolved_name = clean_text(resolved_name[len(resolved_code):].strip(" :-：|_/"))

        if resolved_name == "\u76ee\u5f55":
            panel_name = self._extract_name_from_current_standard_panel(resolved_code)
            if panel_name:
                resolved_name = panel_name

        return clean_text(resolved_code), clean_text(resolved_name)

    def _build_run_summary(self, total_items, failed_output_file=None):
        unique_failures = {item["detail_url"]: item for item in self.failed_items if item.get("detail_url")}
        failed_count = len(unique_failures)
        succeeded_count = max(int(total_items) - failed_count, 0)
        tracked_downloads = list(self.download_summaries.values())
        resolved_failed_output = os.path.abspath(failed_output_file) if failed_output_file else None
        write_results = [result for result in self.write_results.values() if result]
        inserted_count = sum(1 for result in write_results if result.get("status") == "inserted")
        updated_count = sum(1 for result in write_results if result.get("status") == "updated")
        skipped_count = sum(1 for result in write_results if result.get("status") == "skipped")
        return {
            "total": int(total_items),
            "succeeded": succeeded_count,
            "failed": failed_count,
            "inserted": inserted_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "failed_output_file": resolved_failed_output,
            "write_summary": {
                "total_items": int(total_items),
                "inserted": inserted_count,
                "updated": updated_count,
                "skipped": skipped_count,
                "failed": failed_count,
                "duplicate_policy": self.duplicate_policy,
            },
            "download_summary": {
                "total_items": int(total_items),
                "tracked_items": len(tracked_downloads),
                "direct_download_used": sum(1 for item in tracked_downloads if item.get("direct_download_used")),
                "download_url_resolved": sum(1 for item in tracked_downloads if item.get("download_url_resolved")),
                "session_extracted": sum(1 for item in tracked_downloads if item.get("session_extracted")),
                "pdf_saved": sum(1 for item in tracked_downloads if item.get("pdf_saved")),
            },
        }

    def quick_extract_meta(self, xpaths, standard_type=""):
        try:
            return parse_detail_meta(
                self.driver.page_source or "",
                xpaths,
                self._safe_current_url(default=""),
                standard_type,
            )
        except Exception as exc:
            self.logger.warning(f"Scrapling detail parsing failed, falling back to Selenium: {exc}")

        results = {}
        for key, xpath in xpaths.items():
            if not xpath:
                results[key] = None
                continue
            try:
                elements = self.driver.find_elements(By.XPATH, xpath)
                if not elements:
                    results[key] = None
                    continue
                if key in {"draft_unit", "drafter"}:
                    values = [element.text.strip() for element in elements if element.text.strip()]
                    results[key] = "；".join(values) if values else None
                else:
                    text = elements[0].text.strip()
                    results[key] = text or None
            except Exception:
                results[key] = None
        return results

    def _build_db_params(self, meta, path):
        return (
            meta["code"],
            meta.get("keyword") or "无",
            meta.get("draft_unit") or "无",
            meta.get("drafter") or "无",
            meta.get("name") or "无",
            meta.get("english_name") or "无",
            meta.get("release_date") or None,
            meta.get("implement_date") or None,
            meta.get("release_unit") or "无",
            meta.get("charge_unit") or "无",
            meta.get("replace_standard") or "无",
            meta.get("status") or "现行",
            meta.get("application_scope") or "无",
            meta.get("reference_standard") or "无",
            path or "无",
            meta.get("ps") or "无",
        )

    def _existing_standard_row(self, table_name, standard_code):
        sql = f"SELECT id FROM `{table_name}` WHERE standard_code=%s LIMIT 1"
        self.cursor.execute(sql, (standard_code,))
        return self.cursor.fetchone()

    def save_db(self, m, path, table_name="standard_norm_detail"):
        validated_table_name = validate_table_name(table_name)
        standard_code = clean_text(m.get("code"))
        detail_url = m.get("detail_url")
        if not standard_code:
            result = {
                "status": "failed",
                "standard_code": "",
                "detail_url": detail_url,
                "message": "standard_code missing",
            }
            if detail_url:
                self.write_results[detail_url] = result
            self._add_failed_item(m, "database write failed: standard_code missing")
            return result

        insert_sql = f"""INSERT INTO `{validated_table_name}`
        (standard_code, keyword, draft_unit, drafter, chinese_name, english_name, release_date, implement_date,
         release_unit, charge_unit, replace_standard, standard_status, application_scope, reference_standard,
         pdf_path, ps)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"""
        update_sql = f"""UPDATE `{validated_table_name}` SET
            keyword=%s,
            draft_unit=%s,
            drafter=%s,
            chinese_name=%s,
            english_name=%s,
            release_date=%s,
            implement_date=%s,
            release_unit=%s,
            charge_unit=%s,
            replace_standard=%s,
            standard_status=%s,
            application_scope=%s,
            reference_standard=%s,
            pdf_path=%s,
            ps=%s
        WHERE standard_code=%s"""
        insert_params = self._build_db_params(m, path)
        update_params = insert_params[1:] + (standard_code,)

        try:
            existing = self._existing_standard_row(validated_table_name, standard_code)
            if existing and self.duplicate_policy == "skip":
                result = {
                    "status": "skipped",
                    "standard_code": standard_code,
                    "detail_url": detail_url,
                    "message": "record already exists and was skipped",
                }
                if detail_url:
                    self.write_results[detail_url] = result
                return result

            if existing:
                self.cursor.execute(update_sql, update_params)
                status = "updated"
                message = "existing record updated"
            else:
                self.cursor.execute(insert_sql, insert_params)
                status = "inserted"
                message = "new record inserted"

            self.db.commit()
            result = {
                "status": status,
                "standard_code": standard_code,
                "detail_url": detail_url,
                "message": message,
            }
            if detail_url:
                self.write_results[detail_url] = result
            return result
        except Exception as exc:
            self.db.rollback()
            self.logger.error(f"database write failed: {exc}")
            message = f"database write failed: {str(exc)[:80]}"
            self._add_failed_item(m, message)
            result = {
                "status": "failed",
                "standard_code": standard_code,
                "detail_url": detail_url,
                "message": message,
            }
            if detail_url:
                self.write_results[detail_url] = result
            return result

        validated_table_name = validate_table_name(table_name)
        draft_unit_val = m.get("draft_unit") or "无"
        drafter_val = m.get("drafter") or "无"
        keyword_val = m.get("keyword") or "无"

        sql = f"""INSERT INTO `{validated_table_name}`
        (standard_code, keyword, draft_unit, drafter, chinese_name, english_name, release_date, implement_date,
         release_unit, charge_unit, replace_standard, standard_status, application_scope, reference_standard,
         pdf_path, ps)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON DUPLICATE KEY UPDATE
            keyword=VALUES(keyword),
            draft_unit=VALUES(draft_unit),
            drafter=VALUES(drafter),
            chinese_name=VALUES(chinese_name),
            english_name=VALUES(english_name),
            release_date=VALUES(release_date),
            implement_date=VALUES(implement_date),
            release_unit=VALUES(release_unit),
            charge_unit=VALUES(charge_unit),
            replace_standard=VALUES(replace_standard),
            standard_status=VALUES(standard_status),
            application_scope=VALUES(application_scope),
            reference_standard=VALUES(reference_standard),
            pdf_path=VALUES(pdf_path),
            ps=VALUES(ps)"""

        params = (
            m["code"],
            keyword_val,
            draft_unit_val,
            drafter_val,
            m.get("name") or "无",
            m.get("english_name") or "无",
            m.get("release_date") or None,
            m.get("implement_date") or None,
            m.get("release_unit") or "无",
            m.get("charge_unit") or "无",
            m.get("replace_standard") or "无",
            m.get("status") or "现行",
            m.get("application_scope") or "无",
            m.get("reference_standard") or "无",
            path or "无",
            m.get("ps") or "无",
        )

        try:
            self.cursor.execute(sql, params)
            self.db.commit()
            return True
        except Exception as exc:
            self.db.rollback()
            self.logger.error(f"database write failed: {exc}")
            self._add_failed_item(m, f"database write failed: {str(exc)[:80]}")
            return False

    def get_pdf_save_path(self, row, code, name):
        keyword = str(row.get("keyword", "")).strip()
        if not keyword or keyword.lower() == "nan":
            keyword = "其他"
        keyword_dir = os.path.join(BASE_PDF_DIR, self._safe_name(keyword))
        ensure_dir(keyword_dir)
        return os.path.join(keyword_dir, f"{self._safe_name(code)} {self._safe_name(name)}.pdf")

    def clear_temp(self):
        for filename in os.listdir(TEMP_DIR):
            try:
                os.remove(os.path.join(TEMP_DIR, filename))
            except Exception:
                pass

    def _add_failed_item(self, row, fail_reason):
        failed_item = {
            "detail_url": row.get("detail_url"),
            "code": row.get("code"),
            "name": row.get("name"),
            "fail_reason": fail_reason,
            "error_type": self._classify_error(fail_reason),
            "error_code": classify_error_code(fail_reason),
            "execution_time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "keyword": row.get("keyword"),
            "standard_type": row.get("type", "unknown"),
        }
        detail_url = failed_item["detail_url"]
        for index, item in enumerate(self.failed_items):
            if item["detail_url"] == detail_url:
                self.failed_items[index] = failed_item
                return
        self.failed_items.append(failed_item)

    def _classify_error(self, fail_reason):
        reason = str(fail_reason).lower()
        if "captcha" in reason or "验证码" in reason:
            return "验证码错误"
        if "download" in reason or "pdf" in reason or "下载" in reason:
            return "网络错误"
        if "database" in reason or "入库" in reason:
            return "系统错误"
        if "公开" in reason or "版权" in reason:
            return "权限不足"
        return "其他错误"

    def safe_close_window(self, main_handle):
        try:
            if len(self.driver.window_handles) > 1 and self.driver.current_window_handle != main_handle:
                self.driver.close()
            self.driver.switch_to.window(main_handle)
        except Exception:
            pass

    def _get_user_agent(self):
        try:
            return self.driver.execute_script("return navigator.userAgent")
        except Exception:
            return (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )

    def _build_requests_session(self, referer=None):
        session = requests.Session()
        for cookie in self.driver.get_cookies():
            session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain"), path=cookie.get("path"))
        session.headers.update(
            {
                "User-Agent": self._get_user_agent(),
                "Accept": "application/pdf,application/octet-stream,*/*",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            }
        )
        if referer:
            session.headers["Referer"] = referer
        return session

    def _clear_performance_logs(self):
        try:
            self.driver.get_log("performance")
        except Exception:
            pass

    def _score_download_candidate(self, candidate):
        score = 0
        url = str(candidate.get("url") or "").lower()
        content_type = str(candidate.get("content_type") or "").lower()
        if "application/pdf" in content_type:
            score += 100
        if ".pdf" in url:
            score += 80
        if any(token in url for token in ("download", "export", "attachment", "file", "preview")):
            score += 30
        if candidate.get("status") == 200:
            score += 10
        if candidate.get("method") == "POST":
            score += 5
        return score

    def _collect_download_candidates(self):
        requests_by_id = {}
        candidates = []
        try:
            perf_logs = self.driver.get_log("performance")
        except Exception:
            return []

        for entry in perf_logs:
            try:
                message = json.loads(entry["message"])["message"]
            except Exception:
                continue
            method = message.get("method")
            params = message.get("params", {})
            request_id = params.get("requestId")

            if method == "Network.requestWillBeSent" and request_id:
                request = params.get("request", {})
                requests_by_id[request_id] = {
                    "url": request.get("url"),
                    "method": request.get("method"),
                    "headers": request.get("headers") or {},
                    "post_data": request.get("postData"),
                }
                continue

            if method != "Network.responseReceived" or not request_id:
                continue

            response = params.get("response", {})
            request_data = requests_by_id.get(request_id, {})
            headers = response.get("headers") or {}
            content_type = str(headers.get("Content-Type") or headers.get("content-type") or response.get("mimeType") or "")
            url = response.get("url") or request_data.get("url")
            candidate = {
                "request_id": request_id,
                "url": url,
                "method": request_data.get("method", "GET"),
                "headers": request_data.get("headers") or {},
                "post_data": request_data.get("post_data"),
                "status": response.get("status"),
                "content_type": content_type,
            }
            score = self._score_download_candidate(candidate)
            if score > 0:
                candidate["score"] = score
                candidates.append(candidate)

        current_url = ""
        try:
            current_url = self.driver.current_url
        except Exception:
            current_url = ""
        if current_url and current_url != "about:blank":
            fallback_candidate = {
                "request_id": "current_url",
                "url": current_url,
                "method": "GET",
                "headers": {},
                "post_data": None,
                "status": None,
                "content_type": None,
            }
            score = self._score_download_candidate(fallback_candidate)
            if score > 0:
                fallback_candidate["score"] = score
                candidates.append(fallback_candidate)

        unique = {}
        for candidate in candidates:
            key = (candidate.get("method"), candidate.get("url"), candidate.get("post_data"))
            if key not in unique or candidate.get("score", 0) > unique[key].get("score", 0):
                unique[key] = candidate

        return sorted(unique.values(), key=lambda item: item.get("score", 0), reverse=True)

    def _try_resolve_anchor_download(self):
        try:
            anchors = self.driver.find_elements(By.XPATH, "//a[@href]")
        except Exception:
            return []
        candidates = []
        for anchor in anchors:
            href = (anchor.get_attribute("href") or "").strip()
            if not href:
                continue
            absolute = urljoin(self.driver.current_url, href)
            candidate = {
                "request_id": "anchor",
                "url": absolute,
                "method": "GET",
                "headers": {},
                "post_data": None,
                "status": None,
                "content_type": None,
            }
            score = self._score_download_candidate(candidate)
            if score > 0:
                candidate["score"] = score
                candidates.append(candidate)
        return sorted(candidates, key=lambda item: item.get("score", 0), reverse=True)

    def _save_request_summary(self, candidates):
        return self._write_debug_file("download_requests", json.dumps(candidates, ensure_ascii=False, indent=2), "json")

    def _download_via_session(self, candidate, dest_path, referer, summary):
        session = self._build_requests_session(referer=referer)
        summary["session_extracted"] = True
        summary["request_url"] = candidate.get("url")
        summary["request_method"] = candidate.get("method", "GET")
        summary["download_url_resolved"] = bool(summary["request_url"])
        summary["direct_download_used"] = True
        summary["transport"] = "session_request"

        headers = {}
        for key, value in (candidate.get("headers") or {}).items():
            normalized = str(key).lower()
            if normalized in {"host", "content-length", "cookie", "origin", "referer"}:
                continue
            headers[key] = value
        if referer:
            headers["Referer"] = referer

        response = session.request(
            method=candidate.get("method", "GET"),
            url=candidate["url"],
            headers=headers,
            data=candidate.get("post_data"),
            timeout=60,
            allow_redirects=True,
            stream=True,
        )
        summary["http_status"] = response.status_code
        summary["content_type"] = response.headers.get("Content-Type")
        summary["request_url"] = response.url or summary["request_url"]

        if response.status_code != 200:
            raise RuntimeError(f"download request returned status {response.status_code}")

        temp_output = f"{dest_path}.download"
        try:
            with open(temp_output, "wb") as file_obj:
                for chunk in response.iter_content(chunk_size=1024 * 128):
                    self._check_cancelled()
                    if chunk:
                        file_obj.write(chunk)

            with open(temp_output, "rb") as file_obj:
                magic = file_obj.read(5)

            content_type = str(summary["content_type"] or "").lower()
            if magic != b"%PDF-" and "application/pdf" not in content_type:
                raise RuntimeError(f"direct download did not return pdf, content-type={summary['content_type']}")

            if os.path.exists(dest_path):
                os.remove(dest_path)
            shutil.move(temp_output, dest_path)
            summary["pdf_saved"] = True
            return dest_path
        except Exception:
            if os.path.exists(temp_output):
                os.remove(temp_output)
            raise

    def _move_downloaded_pdf_from_temp(self, dest_path, summary):
        start_time = time.time()
        while time.time() - start_time < PDF_DOWNLOAD_TIMEOUT:
            self._check_cancelled()
            temp_pdfs = []
            for filename in os.listdir(TEMP_DIR):
                full_path = os.path.join(TEMP_DIR, filename)
                if not filename.endswith(".pdf"):
                    continue
                if filename.endswith(".crdownload"):
                    continue
                if not os.path.isfile(full_path):
                    continue
                if os.path.getsize(full_path) <= 100:
                    continue
                temp_pdfs.append(full_path)

            if temp_pdfs:
                src_pdf = temp_pdfs[0]
                size_one = os.path.getsize(src_pdf)
                time.sleep(2)
                size_two = os.path.getsize(src_pdf)
                if size_one == size_two:
                    if os.path.exists(dest_path):
                        os.remove(dest_path)
                    shutil.move(src_pdf, dest_path)
                    summary["transport"] = summary.get("transport") or "browser_download_fallback"
                    summary["pdf_saved"] = True
                    return dest_path
            time.sleep(1)
        return None

    def _wait_for_download_candidate(self, timeout_seconds=15):
        end_time = time.time() + timeout_seconds
        candidates = []
        while time.time() < end_time:
            self._check_cancelled()
            candidates.extend(self._collect_download_candidates())
            if candidates:
                break
            time.sleep(1)
        if not candidates:
            candidates = self._try_resolve_anchor_download()
        unique = {}
        for candidate in candidates:
            key = (candidate.get("method"), candidate.get("url"), candidate.get("post_data"))
            if key not in unique or candidate.get("score", 0) > unique[key].get("score", 0):
                unique[key] = candidate
        return sorted(unique.values(), key=lambda item: item.get("score", 0), reverse=True)

    def _extract_interstitial_download_candidate(self):
        if self._read_browser_error_page() is not None:
            return None

        try:
            reload_button = self.driver.find_element(By.ID, "reload-button")
        except Exception:
            return None

        data_url = (reload_button.get_attribute("data-url") or "").strip()
        if not data_url:
            return None

        return {
            "request_id": "interstitial_reload_button",
            "url": data_url,
            "method": "GET",
            "headers": {},
            "post_data": None,
            "status": None,
            "content_type": None,
            "score": 200,
        }

    def _read_browser_error_page(self):
        try:
            page_source = self.driver.page_source or ""
        except Exception:
            return None

        if 'id="main-frame-error"' not in page_source:
            return None

        error_code_match = re.search(r'"errorCode":"([^"]+)"', page_source)
        reload_url_match = re.search(r'"reloadUrl":"([^"]+)"', page_source)

        title = ""
        try:
            title = (self.driver.title or "").strip()
        except Exception:
            pass

        return {
            "title": title,
            "current_url": self._safe_current_url(""),
            "error_code": error_code_match.group(1) if error_code_match else "",
            "reload_url": unescape(reload_url_match.group(1)) if reload_url_match else "",
        }

    def _raise_browser_error_page(self, summary):
        browser_error = self._read_browser_error_page()
        if browser_error is None:
            return

        request_url = browser_error.get("reload_url") or browser_error.get("current_url") or ""
        parsed = urlparse(request_url)
        endpoint = parsed.netloc or browser_error.get("title") or "download endpoint"
        error_code = browser_error.get("error_code") or "BROWSER_NET_ERROR"

        if request_url:
            summary["request_url"] = request_url
            summary["request_method"] = "GET"
            summary["download_url_resolved"] = True
        summary["transport"] = "browser_error_page"
        summary["error_stage"] = "upstream_unavailable"
        raise RuntimeError(f"national standard download endpoint unavailable: {endpoint} returned {error_code}")

    def _standard_unpublic_reason(self, standard_type, current_xpaths):
        if standard_type == "国标":
            try:
                unincluded = self.driver.find_element(By.XPATH, current_xpaths["unincluded_h1"])
                if unincluded.text.strip():
                    return unincluded.text.strip()
            except NoSuchElementException:
                pass
            try:
                copyright_span = self.driver.find_element(By.XPATH, current_xpaths["copyright_span"])
                if copyright_span.text.strip():
                    return copyright_span.text.strip()
            except NoSuchElementException:
                pass
            return None

        if standard_type == "行标":
            captcha_xpath = current_xpaths.get("captcha_img")
            if captcha_xpath and self.driver.find_elements(By.XPATH, captcha_xpath):
                return None
            deny_keywords = ["不公开", "未公开", "暂无", "未授权", "没有找到", "公开属性：否"]
            checks = [
                (By.CSS_SELECTOR, "span.text-danger"),
                (By.CSS_SELECTOR, "div.tip p"),
                (By.CSS_SELECTOR, "div.tip h3"),
            ]
            for by, selector in checks:
                elements = self.driver.find_elements(by, selector)
                if not elements:
                    continue
                text = elements[0].text.strip()
                if text and any(keyword in text for keyword in deny_keywords):
                    return text
            return None

        return None

    def _prepare_preview_window(self, standard_type, current_xpaths, main_handle, meta, row, summary):
        view_text_xpath = current_xpaths.get("view_text_btn")
        if not view_text_xpath:
            meta["ps"] = "missing view_text button xpath"
            return False

        if current_xpaths.get("download_standard_btn"):
            view_text_xpath = "//*[contains(concat(' ', normalize-space(@class), ' '), ' openpdf ')]"

        view_buttons = self.driver.find_elements(By.XPATH, view_text_xpath)
        view_button = self._first_visible_enabled(view_buttons)
        if not view_button:
            meta["ps"] = f"view text button not found: {view_text_xpath}"
            self._add_failed_item(row, meta["ps"])
            return False

        current_handles = self.driver.window_handles
        self.driver.execute_script("arguments[0].click();", view_button)
        WebDriverWait(self.driver, self.WAIT_TIME).until(EC.new_window_is_opened(current_handles))
        preview_handle = [handle for handle in self.driver.window_handles if handle not in current_handles][0]
        self.driver.switch_to.window(preview_handle)
        summary["debug_files"].append(self._save_screenshot("preview"))
        summary["debug_files"].append(self._save_page_source("preview"))

        reason = self._standard_unpublic_reason(standard_type, current_xpaths)
        if reason:
            meta["ps"] = f"not public: {reason[:80]}"
            self._add_failed_item(row, f"standard not public: {reason}")
            self.safe_close_window(main_handle)
            return False

        if standard_type == "国标":
            download_standard_xpath = current_xpaths.get("download_standard_btn")
            if not download_standard_xpath:
                meta["ps"] = "missing national standard download button xpath"
                self.safe_close_window(main_handle)
                return False

            pre_handles = self.driver.window_handles
            button = WebDriverWait(self.driver, self.WAIT_TIME).until(
                EC.element_to_be_clickable((By.XPATH, download_standard_xpath))
            )
            self.driver.execute_script("arguments[0].click();", button)
            WebDriverWait(self.driver, 10).until(EC.new_window_is_opened(pre_handles))
            captcha_handle = self.driver.window_handles[-1]
            self.driver.switch_to.window(captcha_handle)
            summary["debug_files"].append(self._save_screenshot("captcha_window"))
            summary["debug_files"].append(self._save_page_source("captcha_window"))

        return True

    def _perform_captcha_and_download(self, row, meta, standard_type, current_xpaths, summary):
        interstitial_candidate = self._extract_interstitial_download_candidate()
        if interstitial_candidate is not None:
            summary["debug_files"].append(self._save_page_source("captcha_window"))
            summary["debug_files"].append(
                self._save_request_summary([interstitial_candidate])
            )
            dst_pdf = self.get_pdf_save_path(meta, meta.get("code"), meta.get("name"))
            referer = row.get("detail_url") or self._safe_current_url("")
            try:
                return self._download_via_session(interstitial_candidate, dst_pdf, referer, summary)
            except Exception as exc:
                summary["error_stage"] = "direct_download"
                summary["transport"] = "browser_download_fallback"
                summary["pdf_saved"] = False
                self.logger.warning(f"direct download failed, fallback to browser temp download: {exc}")
                fallback_pdf = self._move_downloaded_pdf_from_temp(dst_pdf, summary)
                if fallback_pdf:
                    return fallback_pdf
                raise

        self._raise_browser_error_page(summary)

        captcha_img_xpath = current_xpaths.get("captcha_img")
        captcha_input_xpath = current_xpaths.get("captcha_input")
        action_btn_xpath = current_xpaths.get("verify_btn") if standard_type == "国标" else current_xpaths.get("download_btn")

        if not all([captcha_img_xpath, captcha_input_xpath, action_btn_xpath]):
            raise RuntimeError("captcha or action button xpath missing")

        self.clear_temp()
        captcha_img = WebDriverWait(self.driver, self.WAIT_TIME).until(
            EC.visibility_of_element_located((By.XPATH, captcha_img_xpath))
        )
        time.sleep(1)
        captcha_img.screenshot(IMG_PATH)
        captcha_debug_path = self._save_element_screenshot(captcha_img, "captcha")
        summary["debug_files"].append(captcha_debug_path)

        with open(IMG_PATH, "rb") as file_obj:
            captcha_res = self.cjy.PostPic(file_obj.read(), CAPTCHA_CODE_TYPE)

        if captcha_res.get("err_no") != 0:
            raise RuntimeError(f"captcha recognize failed: {captcha_res.get('err_str', 'unknown')}")

        vcode = captcha_res["pic_str"].strip()
        captcha_input = WebDriverWait(self.driver, self.WAIT_TIME).until(
            EC.visibility_of_element_located((By.XPATH, captcha_input_xpath))
        )
        captcha_input.click()
        captcha_input.clear()
        captcha_input.send_keys(vcode)

        action_btn = WebDriverWait(self.driver, self.WAIT_TIME).until(
            EC.element_to_be_clickable((By.XPATH, action_btn_xpath))
        )
        pre_action_handles = list(self.driver.window_handles)
        referer = self._safe_current_url(row.get("detail_url") or "")
        self._clear_performance_logs()
        time.sleep(0.5)
        self.driver.execute_script("arguments[0].click();", action_btn)
        time.sleep(1)
        self._switch_to_available_window(known_handles=pre_action_handles)
        summary["debug_files"].append(self._save_screenshot("after_action_click"))
        summary["debug_files"].append(self._save_page_source("after_action_click"))

        candidates = self._wait_for_download_candidate(timeout_seconds=min(20, PDF_DOWNLOAD_TIMEOUT))
        if candidates:
            summary["debug_files"].append(self._save_request_summary(candidates))

        dst_pdf = self.get_pdf_save_path(meta, meta.get("code"), meta.get("name"))

        if candidates:
            summary["download_url_resolved"] = True
            try:
                return self._download_via_session(candidates[0], dst_pdf, referer, summary)
            except Exception as exc:
                summary["error_stage"] = "direct_download"
                summary["transport"] = "browser_download_fallback"
                summary["pdf_saved"] = False
                self.logger.warning(f"direct download failed, fallback to browser temp download: {exc}")

        fallback_pdf = self._move_downloaded_pdf_from_temp(dst_pdf, summary)
        if fallback_pdf:
            return fallback_pdf

        raise RuntimeError("download failed: unable to resolve download request or save pdf")

    def process_one(self, row):
        self._ensure_driver_alive()
        code = row.get("code")
        name = row.get("name")
        detail_url = row.get("detail_url")
        self.current_code = clean_text(code) or clean_text(detail_url) or "task"

        if not detail_url:
            self._add_failed_item(row, "page parse failed: detail_url missing")
            return

        standard_type = infer_standard_type(detail_url=detail_url, code=code)
        current_xpaths = XPATHS_MAPPING[standard_type]
        meta = row.copy()
        meta["code"] = clean_text(code)
        meta["name"] = clean_text(name)
        meta["status"] = "现行"
        meta["type"] = standard_type
        meta["ps"] = "metadata extracted"
        final_pdf = ""
        download_summary = self._new_download_summary(row, standard_type)

        try:
            main_handle = self.driver.current_window_handle
        except Exception:
            if not self.driver.window_handles:
                raise RuntimeError("browser window lost")
            self.driver.switch_to.window(self.driver.window_handles[0])
            main_handle = self.driver.current_window_handle

        try:
            try:
                self.driver.get(detail_url)
            except TimeoutException:
                self.logger.warning("detail page load timed out, stopping page load and continuing")
                try:
                    self.driver.execute_script("window.stop();")
                except Exception:
                    pass
            download_summary["debug_files"].append(self._save_screenshot("detail"))
            download_summary["debug_files"].append(self._save_page_source("detail"))

            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, current_xpaths["release_date"]))
                )
            except TimeoutException:
                self.logger.warning("detail metadata wait timed out, continuing")

            resolved_code, resolved_name = self._extract_standard_identity(code, name)
            meta["code"] = resolved_code
            meta["name"] = resolved_name or resolved_code
            self.current_code = resolved_code or self.current_code
            download_summary["code"] = resolved_code

            if not resolved_code:
                meta["ps"] = "metadata extraction failed: standard code missing"
                self._add_failed_item(meta, meta["ps"])
                return

            fast_meta = self.quick_extract_meta(
                {
                    "release_date": current_xpaths["release_date"],
                    "implement_date": current_xpaths["implement_date"],
                    "charge_unit": current_xpaths["charge_unit"],
                    "release_unit": current_xpaths["release_unit"],
                    "draft_unit": current_xpaths["draft_unit"],
                    "drafter": current_xpaths["drafter"],
                    "scope": current_xpaths["scope"],
                    "english_name": current_xpaths["english_name"],
                    "replace_info": current_xpaths["replace_info"],
                    "reference": current_xpaths["reference"],
                },
                standard_type=standard_type,
            )
            meta["release_date"] = fast_meta["release_date"]
            meta["implement_date"] = fast_meta["implement_date"]
            meta["charge_unit"] = fast_meta["charge_unit"]
            meta["release_unit"] = fast_meta["release_unit"]
            meta["draft_unit"] = fast_meta["draft_unit"] or "无"
            meta["drafter"] = fast_meta["drafter"] or "无"
            meta["application_scope"] = fast_meta["scope"]
            meta["english_name"] = fast_meta["english_name"] or "无"
            meta["replace_standard"] = fast_meta["replace_info"]
            meta["reference_standard"] = fast_meta["reference"]

            if not self._prepare_preview_window(standard_type, current_xpaths, main_handle, meta, meta, download_summary):
                meta["download_summary"] = download_summary
                self._record_download_summary(detail_url, download_summary)
                return

            final_pdf = self._perform_captcha_and_download(meta, meta, standard_type, current_xpaths, download_summary) or ""
            meta["ps"] = "download succeeded" if final_pdf else meta["ps"]
            download_summary["pdf_saved"] = bool(final_pdf)

        except TimeoutException as exc:
            meta["ps"] = f"element timeout: {str(exc)[:120]}"
            download_summary["error_stage"] = "timeout"
            self._add_failed_item(meta, meta["ps"])
        except Exception as exc:
            meta["ps"] = f"process failed: {str(exc)[:160]}"
            if not download_summary.get("error_stage"):
                download_summary["error_stage"] = "process"
            self._add_failed_item(meta, meta["ps"])
            self.logger.error(meta["ps"], exc_info=True)
        finally:
            download_summary["debug_files"] = [path for path in download_summary["debug_files"] if path]
            meta["download_summary"] = download_summary
            self._record_download_summary(detail_url, download_summary)
            if detail_url:
                meta_snapshot = dict(meta)
                self.processed_results[detail_url] = {
                    "meta": meta_snapshot,
                    "pdf_path": final_pdf or "",
                }
            self.safe_close_window(main_handle)
            should_save = (
                bool(meta.get("code"))
                and bool(final_pdf)
                and bool(download_summary.get("pdf_saved"))
                and not self._has_failed_item(detail_url)
            )
            if should_save:
                self.save_db(meta, final_pdf)

    def run(self, excel_file=None, generate_failed_output=False, failed_keywords=None, failed_output_dir=None):
        total_items = 0
        failed_output_file = None
        try:
            self._ensure_driver_alive()
            file_path = excel_file or INPUT_FILE
            df = read_excel(file_path)
            if len(df) == 0:
                self.logger.error("task excel is empty")
                return self._build_run_summary(total_items=0)

            required_columns = ["detail_url"]
            missing_columns = [column for column in required_columns if column not in df.columns]
            if missing_columns:
                raise ValueError(f"excel missing required columns: {missing_columns}")

            total_items = len(df)

            for index, (_, row) in enumerate(df.iterrows(), 1):
                self._check_cancelled()
                self.process_one(row.to_dict())
                time.sleep(2)
                self.logger.info(f"progress: {index}/{len(df)}")

            if generate_failed_output:
                failed_output_file = self.generate_failed_excel(
                    keywords=failed_keywords,
                    output_dir=failed_output_dir,
                )

            self.clear_temp()
            return self._build_run_summary(total_items=total_items, failed_output_file=failed_output_file)
        finally:
            try:
                self.driver.quit()
            except Exception:
                pass
            try:
                self.cursor.close()
                self.db.close()
            except Exception:
                pass

    def generate_failed_excel(self, keywords=None, sort_by="error_type", output_dir=None):
        if not self.failed_items:
            self.logger.info("no failed items, skip failed excel")
            return None

        unique_items = {}
        for item in self.failed_items:
            unique_items[item["detail_url"]] = item
        final_items = list(unique_items.values())

        if sort_by == "time":
            final_items.sort(key=lambda item: item["execution_time"], reverse=True)
        elif sort_by == "frequency":
            counts = {}
            for item in final_items:
                counts[item["error_type"]] = counts.get(item["error_type"], 0) + 1
            final_items.sort(key=lambda item: (-counts[item["error_type"]], item["error_type"]))
        else:
            final_items.sort(key=lambda item: (item["error_type"], item["execution_time"], item["code"]))

        df = pd.DataFrame(
            final_items,
            columns=[
                "code",
                "name",
                "detail_url",
                "error_type",
                "fail_reason",
                "execution_time",
                "keyword",
                "standard_type",
            ],
        )

        if keywords:
            filename = f"failed_items_{'_'.join(str(keyword) for keyword in keywords)}.xlsx"
        else:
            filename = "failed_items.xlsx"
        if output_dir:
            ensure_dir(output_dir)
            filename = os.path.join(output_dir, filename)
        filename = self._ensure_unique_filename(filename)
        df.to_excel(filename, index=False)
        return filename

    def _ensure_unique_filename(self, filename):
        if not os.path.exists(filename):
            return filename
        base, ext = os.path.splitext(filename)
        counter = 1
        while True:
            candidate = f"{base}_{counter}{ext}"
            if not os.path.exists(candidate):
                return candidate
            counter += 1


if __name__ == "__main__":
    crawler = BatchCrawler()
    try:
        crawler.run()
        crawler.generate_failed_excel()
    except KeyboardInterrupt:
        crawler.logger.info("interrupted by user")
    except Exception as exc:
        crawler.logger.error(f"startup failed: {exc}", exc_info=True)
