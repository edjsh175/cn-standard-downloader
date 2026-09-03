import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

import config


_SUPPORTED_DETAIL_PATHS = {
    "/gb/search/gbDetailed": "GB",
    "/hb/search/stdHBDetailed": "HB",
    "/db/search/stdDBDetailed": "DB",
}

_DETAIL_URL_EXTRACT_PATTERN = re.compile(
    r"https?://std\.samr\.gov\.cn/(?:gb/search/gbDetailed|hb/search/stdHBDetailed|db/search/stdDBDetailed)\?id=[^\s<>'\"，。；、]+",
    re.IGNORECASE,
)


def _parse_version_tuple(version):
    text = str(version or "").strip()
    match = re.findall(r"\d+", text)
    return tuple(int(part) for part in match) if match else tuple()


def _candidate_driver_paths():
    candidates = []

    explicit = os.environ.get("STD_CHROMEDRIVER_PATH")
    if explicit:
        candidates.append(Path(explicit))

    drivers_root = Path(config.get_base_dir()) / "drivers"
    candidates.append(drivers_root / "chromedriver.exe")
    candidates.append(drivers_root / "chromedriver")
    if drivers_root.exists():
        candidates.extend(drivers_root.rglob("chromedriver.exe"))
        candidates.extend(drivers_root.rglob("chromedriver"))

    wdm_root = Path.home() / ".wdm" / "drivers" / "chromedriver" / "win64"
    if wdm_root.exists():
        candidates.extend(wdm_root.glob("*/chromedriver-win32/chromedriver.exe"))
    wdm_linux_root = Path.home() / ".wdm" / "drivers" / "chromedriver" / "linux64"
    if wdm_linux_root.exists():
        candidates.extend(wdm_linux_root.glob("*/chromedriver-linux64/chromedriver"))

    candidates.extend(
        [
            Path("/usr/bin/chromedriver"),
            Path("/usr/local/bin/chromedriver"),
        ]
    )

    seen = set()
    unique = []
    for path in candidates:
        resolved = str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    return unique


def _get_chrome_binary_path():
    explicit = os.environ.get("STD_CHROME_BINARY")
    candidates = [
        explicit,
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if path.exists():
            return path
    return None


def _get_chrome_version():
    chrome_path = _get_chrome_binary_path()
    if chrome_path is None:
        return tuple()
    try:
        return _get_binary_version(chrome_path)
    except Exception:
        return tuple()


def _get_binary_version(path: Path):
    if not path.exists():
        return tuple()

    try:
        output = subprocess.check_output(
            [str(path), "--version"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        parsed = _parse_version_tuple(output)
        if parsed:
            return parsed
    except Exception:
        pass

    if os.name == "nt":
        command = [
            "powershell",
            "-NoProfile",
            "-Command",
            f"(Get-Item '{path}').VersionInfo.ProductVersion",
        ]
        try:
            output = subprocess.check_output(command, text=True, stderr=subprocess.DEVNULL).strip()
            return _parse_version_tuple(output)
        except Exception:
            return tuple()

    return tuple()


def _get_driver_version(path: Path):
    parent_hints = [path.parent.name, path.parent.parent.name if path.parent.parent else ""]
    for hint in parent_hints:
        parsed = _parse_version_tuple(hint)
        if parsed:
            return parsed
    return _get_binary_version(path)


def _pick_cached_driver():
    existing = [path for path in _candidate_driver_paths() if path.exists()]
    if not existing:
        return None

    chrome_version = _get_chrome_version()
    chrome_major = chrome_version[:1]

    def score(path):
        version = _get_driver_version(path)
        version_major = version[:1]
        is_exact_major = 1 if chrome_major and version_major == chrome_major else 0
        is_full_match = 1 if chrome_version and version == chrome_version else 0
        repo_bias = 1 if Path(config.get_base_dir()) / "drivers" in path.parents else 0
        return (is_exact_major, is_full_match, repo_bias, version)

    return max(existing, key=score)


def _build_chrome_service():
    cached_driver = _pick_cached_driver()
    if cached_driver is not None:
        return Service(str(cached_driver))
    return Service(ChromeDriverManager().install())


def build_chrome_arguments(
    headless: bool,
    allow_insecure_browser_flags: bool = False,
    allow_remote_debugging: bool = False,
) -> list[str]:
    arguments = [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-software-rasterizer",
        "--hide-scrollbars",
        "--window-size=1920,1080",
    ]
    if allow_insecure_browser_flags:
        arguments.extend(
            [
                "--ignore-certificate-errors",
                "--allow-running-insecure-content",
                "--disable-web-security",
            ]
        )
    if headless:
        arguments.append("--headless=new")
        if allow_remote_debugging:
            arguments.append("--remote-debugging-port=9222")
    return arguments


def init_driver(download_dir=None):
    opts = Options()
    opts.page_load_strategy = "eager"
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option("useAutomationExtension", False)
    for argument in build_chrome_arguments(
        headless=config.HEADLESS_BROWSER,
        allow_insecure_browser_flags=config.ALLOW_INSECURE_BROWSER_FLAGS,
        allow_remote_debugging=config.ALLOW_BROWSER_REMOTE_DEBUGGING,
    ):
        opts.add_argument(argument)
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL", "browser": "ALL"})

    prefs = config.DOWNLOAD_PREFS.copy()
    if download_dir:
        prefs["download.default_directory"] = os.path.abspath(download_dir)
    opts.add_experimental_option("prefs", prefs)

    chrome_binary = _get_chrome_binary_path()
    if chrome_binary is not None:
        opts.binary_location = str(chrome_binary)

    driver = webdriver.Chrome(service=_build_chrome_service(), options=opts)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        driver.execute_cdp_cmd(
            "Page.setDownloadBehavior",
            {
                "behavior": "allow",
                "downloadPath": os.path.abspath(download_dir or config.TEMP_DIR),
            },
        )
    except Exception:
        pass

    try:
        driver.execute_cdp_cmd("Network.enable", {})
    except Exception:
        pass

    return driver


def init_logger(log_file=None):
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)

    if logger.handlers:
        logger.handlers.clear()

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    formatter = logging.Formatter("%(asctime)s - %(message)s")
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    return logger


def read_excel(file_path):
    try:
        return pd.read_excel(file_path).dropna(how="all").reset_index(drop=True)
    except Exception as exc:
        raise Exception(f"failed to read excel file: {exc}")


def write_excel(data, file_path):
    try:
        pd.DataFrame(data).to_excel(file_path, index=False)
    except Exception as exc:
        raise Exception(f"failed to write excel file: {exc}")


def clean_text(text):
    if text is None or pd.isna(text):
        return ""
    normalized = str(text)
    if not normalized.strip():
        return ""
    return re.sub(r"\s+", " ", normalized).strip()


def build_detail_url(tid, pid):
    if tid == "BV_GB":
        return f"https://std.samr.gov.cn/gb/search/gbDetailed?id={pid}"
    if tid == "BV_HB":
        return f"https://std.samr.gov.cn/hb/search/stdHBDetailed?id={pid}"
    if tid == "BV_DB":
        return f"https://std.samr.gov.cn/db/search/stdDBDetailed?id={pid}"
    return None


def ensure_dir(directory):
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)


def normalize_detail_url(detail_url):
    raw_value = str(detail_url or "").strip()
    if not raw_value:
        return None

    cleaned = raw_value.strip(" \t\r\n\"'<>[](){}.,，。；;、")
    parsed = urlparse(cleaned)
    if parsed.scheme.lower() not in {"http", "https"}:
        return None
    if parsed.netloc.lower() != "std.samr.gov.cn":
        return None

    canonical_path = next(
        (path for path in _SUPPORTED_DETAIL_PATHS if parsed.path.lower() == path.lower()),
        None,
    )
    if canonical_path is None:
        return None

    query = parse_qs(parsed.query)
    standard_id = str((query.get("id") or [""])[0]).strip()
    if not standard_id:
        return None

    return urlunparse(
        (
            "https",
            "std.samr.gov.cn",
            canonical_path,
            "",
            urlencode({"id": standard_id}),
            "",
        )
    )


def extract_detail_urls_from_text(text):
    candidates = _DETAIL_URL_EXTRACT_PATTERN.findall(str(text or ""))
    normalized = []
    seen = set()
    for candidate in candidates:
        canonical = normalize_detail_url(candidate)
        if not canonical or canonical in seen:
            continue
        seen.add(canonical)
        normalized.append(canonical)
    return normalized


def infer_standard_type(detail_url=None, code=None):
    canonical_url = normalize_detail_url(detail_url)
    if canonical_url:
        parsed = urlparse(canonical_url)
        mapped_prefix = _SUPPORTED_DETAIL_PATHS.get(parsed.path)
        if mapped_prefix:
            return get_standard_type(mapped_prefix)
    return get_standard_type(code)


def get_standard_type(code):
    if not code or pd.isna(code):
        return "行标"
    code_prefix = str(code).strip().upper()[:2]
    if code_prefix == "GB":
        return "国标"
    if code_prefix == "DB":
        return "地标"
    return "行标"
