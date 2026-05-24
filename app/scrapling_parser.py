import os
import re
import sqlite3
from typing import Any

from utils import build_detail_url, clean_text


CURRENT_STATUS = "\u73b0\u884c"
DETAIL_FIELD_JOIN_KEYS = {"draft_unit", "drafter"}
SUPPORTED_TIDS = {"BV_GB", "BV_HB", "BV_DB"}


def _adaptive_storage_args(url: str | None = None) -> dict[str, str | None]:
    import config

    configured_file = os.environ.get("STD_SCRAPLING_STORAGE_FILE")
    if configured_file:
        storage_file = os.path.realpath(os.path.abspath(configured_file))
        parent_dir = os.path.dirname(storage_file)
        if parent_dir:
            os.makedirs(parent_dir, exist_ok=True)
        return {"storage_file": storage_file, "url": url}

    storage_dir = os.environ.get("STD_SCRAPLING_STORAGE_DIR")
    if storage_dir:
        storage_dir = os.path.realpath(os.path.abspath(storage_dir))
    else:
        storage_dir = os.path.join(os.path.realpath(config.get_base_dir()), ".tmp", "scrapling")
    os.makedirs(storage_dir, exist_ok=True)
    return {
        "storage_file": os.path.join(storage_dir, "elements_storage.db"),
        "url": url,
    }


def _storage_file_is_usable(storage_file: str | None) -> bool:
    if not storage_file or os.path.isdir(storage_file):
        return False
    parent_dir = os.path.dirname(storage_file)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)
    try:
        connection = sqlite3.connect(storage_file)
        connection.execute("PRAGMA journal_mode=WAL")
        connection.close()
        return True
    except (OSError, sqlite3.Error):
        return False


def _selector(html: str, *, url: str | None = None, adaptive: bool = False):
    from scrapling import Selector

    try:
        kwargs: dict[str, Any] = {}
        if adaptive:
            storage_args = _adaptive_storage_args(url)
            if _storage_file_is_usable(storage_args.get("storage_file")):
                kwargs["adaptive"] = True
                kwargs["storage_args"] = storage_args
        if url:
            kwargs["url"] = url
        return Selector(html or "", **kwargs)
    except (OSError, sqlite3.Error):
        if not adaptive:
            raise
        plain_kwargs = {"url": url} if url else {}
        return Selector(html or "", **plain_kwargs)


def _adaptive_selector(html: str, url: str | None):
    from scrapling import Selector

    storage_args = _adaptive_storage_args(url)
    if not _storage_file_is_usable(storage_args.get("storage_file")):
        plain_kwargs = {"url": url} if url else {}
        return Selector(html or "", **plain_kwargs), False

    try:
        kwargs: dict[str, Any] = {"adaptive": True, "storage_args": storage_args}
        if url:
            kwargs["url"] = url
        return Selector(html or "", **kwargs), True
    except (OSError, sqlite3.Error):
        plain_kwargs = {"url": url} if url else {}
        return Selector(html or "", **plain_kwargs), False


def _selection_items(selection) -> list[Any]:
    if not selection:
        return []
    try:
        return list(selection)
    except TypeError:
        return [selection]


def _first(selection):
    items = _selection_items(selection)
    return items[0] if items else None


def _text(element) -> str:
    if element is None:
        return ""
    value = getattr(element, "text", "")
    if callable(value):
        value = value()
    value = clean_text(value)
    if value:
        return value

    try:
        text_nodes = element.css("::text").getall()
    except Exception:
        return ""
    return clean_text(" ".join(clean_text(text) for text in text_nodes if clean_text(text)))


def _first_text(selection) -> str:
    return _text(_first(selection))


def _attr(element, name: str) -> str:
    if element is None:
        return ""
    attrs = getattr(element, "attrib", None) or {}
    try:
        return clean_text(attrs.get(name, ""))
    except AttributeError:
        return ""


def _record_from_panel(panel, keyword: str):
    link = _first(panel.css("table.s-title a[tid][pid]"))
    tid = _attr(link, "tid")
    pid = _attr(link, "pid")
    if not tid or not pid:
        return None, "missing_link"
    if tid not in SUPPORTED_TIDS:
        return None, "skipped_type"

    status = _first_text(panel.css("span.s-status.label"))
    if status != CURRENT_STATUS:
        return None, "skipped_status"

    detail_url = build_detail_url(tid, pid)
    if not detail_url:
        return None, "missing_detail_url"

    code = _first_text(link.css("span.en-code"))
    full_text = _text(link)
    name = full_text.replace(code, "").strip()
    name = re.sub(r"^[\s\-\u2014]+", "", name)

    return (
        {
            "keyword": keyword,
            "code": code,
            "name": clean_text(name),
            "detail_url": detail_url,
            "status": status,
        },
        None,
    )


def parse_search_results(html: str, keyword: str) -> dict[str, Any]:
    page = _selector(html)
    panels = _selection_items(page.css("div.panel.panel-default.post"))
    records = []
    skipped_type = 0
    skipped_status = 0

    for panel in panels:
        record, skip_reason = _record_from_panel(panel, keyword)
        if record:
            records.append(record)
        elif skip_reason == "skipped_type":
            skipped_type += 1
        elif skip_reason == "skipped_status":
            skipped_status += 1

    return {
        "records": records,
        "skipped_type": skipped_type,
        "skipped_status": skipped_status,
        "panel_count": len(panels),
    }


def _xpath_items(page, xpath: str, identifier: str, adaptive_enabled: bool) -> list[Any]:
    if not adaptive_enabled:
        return _selection_items(page.xpath(xpath))

    exact = _selection_items(page.xpath(xpath, auto_save=True, identifier=identifier))
    if exact:
        return exact
    return _selection_items(page.xpath(xpath, adaptive=True, identifier=identifier))


def _extract_xpath_value(page, key: str, xpath: str, identifier: str, adaptive_enabled: bool):
    if not xpath:
        return None

    items = _xpath_items(page, xpath, identifier, adaptive_enabled)
    if not items:
        return None

    if key in DETAIL_FIELD_JOIN_KEYS:
        values = [_text(item) for item in items]
        values = [value for value in values if value]
        return "\uff1b".join(values) if values else None

    value = _text(items[0])
    return value or None


def parse_detail_meta(html: str, xpaths: dict[str, str], url: str, standard_type: str) -> dict[str, Any]:
    page, adaptive_enabled = _adaptive_selector(html, url)
    type_key = clean_text(standard_type) or "default"
    results: dict[str, Any] = {}

    for key, xpath in xpaths.items():
        identifier = f"{type_key}.{key}"
        try:
            results[key] = _extract_xpath_value(page, key, xpath or "", identifier, adaptive_enabled)
        except Exception:
            results[key] = None

    return results
