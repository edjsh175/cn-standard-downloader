"""Deterministic executors used by offline Agent flow tests and demos."""

from __future__ import annotations

import json
import os
from typing import Any


class FakeSearchExecutor:
    def __init__(self, records: list[dict[str, Any]] | None = None):
        self.records = [dict(record) for record in records or []]
        self.calls: list[dict[str, Any]] = []

    def __call__(self, keywords, *, output_filename, log_file, cancel_checker, per_keyword_limit):
        self.calls.append({"keywords": list(keywords), "per_keyword_limit": per_keyword_limit})
        os.makedirs(os.path.dirname(output_filename), exist_ok=True)
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        with open(output_filename, "w", encoding="utf-8") as stream:
            json.dump(self.records, stream, ensure_ascii=False)
        with open(log_file, "w", encoding="utf-8") as stream:
            stream.write("fake search completed\n")
        return {
            "keywords": list(keywords),
            "per_keyword_limit": per_keyword_limit,
            "raw_count": len(self.records),
            "deduplicated_count": len(self.records),
            "per_keyword_counts": {keyword: len(self.records) for keyword in keywords},
            "records": [dict(record) for record in self.records],
        }


class FakeCrawler:
    def __init__(self, *, log_file, cancel_checker, duplicate_policy, scenario, records):
        self.log_file = log_file
        self.cancel_checker = cancel_checker
        self.duplicate_policy = duplicate_policy
        self.scenario = scenario
        self.records = [dict(record) for record in records]
        self.failed_items: list[dict[str, Any]] = []
        self.processed_results: dict[str, dict[str, Any]] = {}
        self.download_summaries: dict[str, dict[str, Any]] = {}

    def save_db(self, meta, path, table_name):
        return {"status": "inserted", "table_name": table_name}

    def run(self, search_output, *, generate_failed_output, failed_keywords, failed_output_dir=None):
        summaries = {}
        for index, item in enumerate(self.records):
            detail_url = item["detail_url"]
            if self.scenario == "partial" and index == len(self.records) - 1:
                self.failed_items.append(
                    {
                        "detail_url": detail_url,
                        "error_type": "timeout",
                        "fail_reason": "upstream request timeout",
                        "error_code": "SITE_TIMEOUT",
                    }
                )
                continue
            if self.scenario == "captcha":
                self.failed_items.append(
                    {
                        "detail_url": detail_url,
                        "error_type": "captcha",
                        "fail_reason": "captcha recognize failed: 无可用题分",
                        "error_code": "CAPTCHA_NO_BALANCE",
                    }
                )
                continue

            pdf_dir = os.path.join(os.path.dirname(self.log_file), "pdf")
            os.makedirs(pdf_dir, exist_ok=True)
            pdf_path = os.path.join(pdf_dir, f"fake-{index + 1}.pdf")
            with open(pdf_path, "wb") as stream:
                stream.write(b"%PDF-1.4 fake document")
            meta = dict(item)
            meta["download_summary"] = {
                "pdf_saved": True,
                "direct_download_used": True,
                "download_url_resolved": True,
            }
            self.processed_results[detail_url] = {"meta": meta, "pdf_path": pdf_path}
            summaries[detail_url] = dict(meta["download_summary"])
            self.save_db(meta, pdf_path, "gb_standards")
        return {
            "failed_output_file": None,
            "download_summary": {
                "total_items": len(self.records),
                "tracked_items": len(summaries),
                "direct_download_used": len(summaries),
                "download_url_resolved": len(summaries),
                "session_extracted": 0,
                "pdf_saved": len(summaries),
            },
        }

    def generate_failed_excel(self, keywords=None, output_dir=None):
        return None


class FakeCrawlerFactory:
    def __init__(self, scenario="success"):
        if scenario not in {"success", "partial", "captcha"}:
            raise ValueError("unsupported fake crawler scenario")
        self.scenario = scenario
        self.records: list[dict[str, Any]] = []
        self.created: list[FakeCrawler] = []

    def __call__(self, *, log_file, cancel_checker, duplicate_policy):
        crawler = FakeCrawler(
            log_file=log_file,
            cancel_checker=cancel_checker,
            duplicate_policy=duplicate_policy,
            scenario=self.scenario,
            records=self.records,
        )
        self.created.append(crawler)
        return crawler
