import argparse
import json
import os
import sys
import time
from urllib.parse import urljoin

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from app.agent_contract import build_agent_status


def api_url(base_url, path):
    return urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))


def request_json(method, base_url, path, token=None, **kwargs):
    headers = dict(kwargs.pop("headers", {}) or {})
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = requests.request(method, api_url(base_url, path), headers=headers, timeout=kwargs.pop("timeout", 10), **kwargs)
    payload = None
    if response.content:
        try:
            payload = response.json()
        except ValueError:
            payload = response.text[:500]
    return response.status_code, payload


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def poll_task(base_url, token, task_id, timeout_seconds):
    deadline = time.time() + timeout_seconds
    last_payload = None
    while time.time() < deadline:
        status, payload = request_json("GET", base_url, f"/api/tasks/{task_id}", token=token, timeout=10)
        check(status == 200, f"task poll returned HTTP {status}: {payload}")
        last_payload = payload
        agent_status = payload.get("agent_status") or {}
        if agent_status.get("terminal"):
            return payload
        time.sleep(2)
    raise TimeoutError(f"task {task_id} did not reach a terminal state; last payload: {last_payload}")


def run_contract_examples():
    examples = {
        "search_results": build_agent_status(
            "search_only",
            "succeeded",
            {"summary": {"total": 1, "succeeded": 1, "failed": 0, "skipped": 0}},
            None,
        ),
        "direct_downloaded": build_agent_status(
            "direct_grab",
            "succeeded",
            {"summary": {"total": 1, "succeeded": 1, "failed": 0, "skipped": 0}},
            None,
        ),
        "captcha_blocked": build_agent_status(
            "direct_grab",
            "failed",
            {
                "summary": {"total": 1, "succeeded": 0, "failed": 1, "skipped": 0},
                "errors": [{"message": "captcha recognize failed: \u65e0\u53ef\u7528\u9898\u5206"}],
            },
            None,
        ),
    }
    check(examples["search_results"]["outcome"] == "results_available", "search contract example failed")
    check(examples["direct_downloaded"]["outcome"] == "downloaded", "direct contract example failed")
    check(examples["captcha_blocked"]["error_code"] == "CAPTCHA_NO_BALANCE", "captcha contract example failed")
    return examples


def run_fake_flow():
    """Exercise the Agent status contract without network, browser, or database."""

    search_result = {
        "summary": {"total": 1, "succeeded": 1, "failed": 0, "skipped": 0},
        "errors": [],
    }
    download_result = {
        "summary": {"total": 1, "succeeded": 1, "failed": 0, "skipped": 0},
        "download_summary": {"pdf_saved": 1},
        "errors": [],
    }
    return {
        "search": {
            "agent_status": build_agent_status("search_only", "succeeded", search_result, None),
            "summary": search_result["summary"],
        },
        "download": {
            "agent_status": build_agent_status("direct_grab", "succeeded", download_result, None),
            "summary": download_result["summary"],
        },
    }


def run_real_search(base_url, token, keyword, per_keyword_limit, timeout_seconds):
    payload = {
        "task_type": "search_only",
        "keywords": [keyword],
        "per_keyword_limit": per_keyword_limit,
        "headless": True,
    }
    status, body = request_json("POST", base_url, "/api/tasks", token=token, json=payload, timeout=20)
    check(status == 201, f"search task create returned HTTP {status}: {body}")
    task = poll_task(base_url, token, body["id"], timeout_seconds)
    result_status, result_body = request_json("GET", base_url, f"/api/tasks/{body['id']}/result", token=token, timeout=20)
    check(result_status == 200, f"search result returned HTTP {result_status}: {result_body}")
    return {"task": task, "result": result_body}


def main():
    parser = argparse.ArgumentParser(description="Smoke-test the AI worker API contract.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8765")
    parser.add_argument("--token", default=os.environ.get("STD_WORKER_API_TOKEN", ""))
    parser.add_argument("--real-search-keyword", default="")
    parser.add_argument("--fake-flow", action="store_true", help="run the offline Agent contract flow")
    parser.add_argument("--per-keyword-limit", type=int, default=1)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    args = parser.parse_args()

    if not args.token:
        raise SystemExit("--token is required, or set STD_WORKER_API_TOKEN")

    report = {"base_url": args.base_url, "checks": {}}

    if args.fake_flow:
        report["checks"]["local_contract_examples"] = run_contract_examples()
        report["checks"]["fake_flow"] = run_fake_flow()
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    status, body = request_json("GET", args.base_url, "/health", timeout=5)
    check(status == 200 and body == {"status": "ok"}, f"health failed: HTTP {status}: {body}")
    report["checks"]["health"] = body

    status, body = request_json("GET", args.base_url, "/api/capabilities", timeout=5)
    check(status == 401, f"capabilities without token should be 401, got HTTP {status}: {body}")
    report["checks"]["capabilities_requires_auth"] = body

    status, capabilities = request_json("GET", args.base_url, "/api/capabilities", token=args.token, timeout=10)
    check(status == 200, f"capabilities failed: HTTP {status}: {capabilities}")
    check(capabilities.get("recommended_workflow") == ["search_only", "direct_grab"], "unexpected recommended workflow")
    report["checks"]["capabilities"] = capabilities

    report["checks"]["local_contract_examples"] = run_contract_examples()

    if args.real_search_keyword:
        report["checks"]["real_search"] = run_real_search(
            args.base_url,
            args.token,
            args.real_search_keyword,
            args.per_keyword_limit,
            args.timeout_seconds,
        )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False, indent=2))
        raise SystemExit(1)
