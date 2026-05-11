import json
import os
import sys
from typing import Any


def get_resource_path(relative_path: str) -> str:
    try:
        base_path = sys._MEIPASS  # type: ignore[attr-defined]
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)


def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_appdata_config_path() -> str:
    if hasattr(sys, "_MEIPASS"):
        appdata_dir = os.path.join(os.environ.get("APPDATA", ""), "国标爬虫系统")
        os.makedirs(appdata_dir, exist_ok=True)
        return os.path.join(appdata_dir, "config_user.json")
    return os.path.join(get_base_dir(), "config_user.json")


CONFIG_FILE = get_appdata_config_path()

DEFAULT_CONFIG = {
    "db_host": "localhost",
    "db_port": 3306,
    "db_user": "root",
    "db_password": "",
    "db_database": "disaster_knowledge",
    "chaojiying_user": "",
    "chaojiying_pass": "",
    "chaojiying_softid": "",
    "pdf_dir": "",
    "input_file": "待抓取标准清单_全标准.xlsx",
    "output_file": "待抓取标准清单_全标准.xlsx",
    "temp_dir": "temp_step2",
    "debug_dir": "debug_output",
    "remember_config": False,
    "headless_browser": False,
    "worker_host": "127.0.0.1",
    "worker_port": 8765,
}

ENV_CONFIG_MAP = {
    "STD_DB_HOST": "db_host",
    "STD_DB_PORT": "db_port",
    "STD_DB_USER": "db_user",
    "STD_DB_PASSWORD": "db_password",
    "STD_DB_DATABASE": "db_database",
    "STD_CHAOJIYING_USER": "chaojiying_user",
    "STD_CHAOJIYING_PASS": "chaojiying_pass",
    "STD_CHAOJIYING_SOFTID": "chaojiying_softid",
    "STD_PDF_DIR": "pdf_dir",
    "STD_INPUT_FILE": "input_file",
    "STD_OUTPUT_FILE": "output_file",
    "STD_TEMP_DIR": "temp_dir",
    "STD_DEBUG_DIR": "debug_dir",
    "STD_HEADLESS_BROWSER": "headless_browser",
    "STD_WORKER_HOST": "worker_host",
    "STD_WORKER_PORT": "worker_port",
}


def _coerce_value(key: str, value: Any) -> Any:
    if key in {"db_port", "worker_port"}:
        return int(value)
    if key in {"remember_config", "headless_browser"}:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on"}
    return value


def _resolve_path(value: str, default_dir_name: str) -> str:
    if value:
        if os.path.isabs(value):
            return value
        return os.path.join(get_base_dir(), value)
    return os.path.join(get_base_dir(), default_dir_name)


def load_config() -> dict[str, Any]:
    loaded_config = dict(DEFAULT_CONFIG)

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as file_obj:
                loaded_config.update(json.load(file_obj))
        except Exception as exc:
            print(f"Warning: failed to load config file, using defaults: {exc}")

    for env_name, config_key in ENV_CONFIG_MAP.items():
        env_value = os.environ.get(env_name)
        if env_value is not None and env_value != "":
            loaded_config[config_key] = _coerce_value(config_key, env_value)

    return loaded_config


def save_config(config: dict[str, Any]) -> bool:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as file_obj:
            json.dump(config, file_obj, indent=4, ensure_ascii=False)
        return True
    except Exception as exc:
        print(f"Error: failed to save config file: {exc}")
        return False


DEFAULT_KEYWORDS = ["人工智能"]
CAPTCHA_CODE_TYPE = 1902
DRIVER_TIMEOUT = 30
ELEMENT_TIMEOUT = 5
PDF_DOWNLOAD_TIMEOUT = 90

XPATHS_MAPPING = {
    "国标": {
        "release_date": '//dt[contains(text(), "发布日期")]/following-sibling::dd[1]',
        "implement_date": '//dt[contains(text(), "实施日期")]/following-sibling::dd[1]',
        "charge_unit": '//dt[contains(text(), "归口单位")]/following-sibling::dd[1]',
        "release_unit": '//dt[contains(text(), "主管部门")]/following-sibling::dd[1]',
        "draft_unit": "/html/body/div[3]/div/div/div/div[10]//dl//dd",
        "drafter": "/html/body/div[3]/div/div/div/div[12]//dl//dd",
        "scope": "",
        "english_name": "",
        "replace_info": "",
        "reference": '//h2[contains(text(), "相关标准(计划)")]/following-sibling::div[1]//li',
        "view_text_btn": "/html/body/div[5]/div/div[1]",
        "download_standard_btn": "/html/body/div[3]/div/div/div/div/table[2]/tbody/tr[4]/td/button[2]",
        "captcha_input": '//input[@id="verifyCode"]',
        "captcha_img": '//img[@class="verifyCode"]',
        "verify_btn": '//button[contains(@class, "btn-primary") and text()="验证"]',
        "unincluded_h1": '//h1[contains(text(), "您所查询的标准系统尚未收录")]',
        "copyright_span": '//span[contains(@class, "text-danger") and contains(text(), "涉及版权保护问题")]',
    },
    "地标": {
        "release_date": '//dt[contains(text(), "发布日期")]/following-sibling::dd[1]',
        "implement_date": '//dt[contains(text(), "实施日期")]/following-sibling::dd[1]',
        "charge_unit": '//dt[contains(text(), "归口单位")]/following-sibling::dd[1]',
        "release_unit": '//dt[contains(text(), "主管部门")]/following-sibling::dd[1]',
        "draft_unit": "/html/body/div[3]/div/div/div/div[11]/dl[1]/dd/a",
        "drafter": "/html/body/div[3]/div/div/div/div[13]/dl[1]/dd",
        "scope": '//h2[contains(text(), "适用范围")]/following-sibling::p[1]',
        "english_name": "",
        "replace_info": "",
        "reference": '//h2[contains(text(), "相关标准(计划)")]/following-sibling::div[1]//li',
        "view_text_btn": "/html/body/div[5]/div/div",
        "captcha_img": "/html/body/div/div/div/div/div/div/div[2]/form/img",
        "captcha_input": "/html/body/div/div/div/div/div/div/div[2]/form/div[1]/input",
        "download_btn": "/html/body/div/div/div/div/div/div/div[3]/button[2]",
    },
    "行标": {
        "release_date": '//dt[contains(text(), "发布日期")]/following-sibling::dd[1]',
        "implement_date": '//dt[contains(text(), "实施日期")]/following-sibling::dd[1]',
        "charge_unit": '//dt[contains(text(), "技术归口")]/following-sibling::dd[1]',
        "release_unit": '//dt[contains(text(), "批准发布部门")]/following-sibling::dd[1]',
        "draft_unit": "/html/body/div[3]/div/div/div/div[11]/dl[1]/dd/a",
        "drafter": "/html/body/div[3]/div/div/div/div[13]/dl[1]/dd",
        "scope": '//h2[contains(text(), "适用范围")]/parent::div/following-sibling::p[1]',
        "english_name": '//dt[contains(text(), "英文名称")]/following-sibling::dd[1]',
        "replace_info": '//dt[contains(text(), "替代情况")]/following-sibling::dd[1]',
        "reference": '//div[contains(@class, "referencedStandards")]//table',
        "view_text_btn": '//a[contains(., "查看文本")]',
        "captcha_img": '//*[@id="validate-code"]',
        "captcha_input": '//*[@id="captcha-input"]',
        "download_btn": '//*[@id="download-btn"]',
    },
}

STANDARD_TYPE_MAPPING = {
    "GB": "国标",
    "DB": "地标",
}


user_config = load_config()

DB_CONFIG: dict[str, Any] = {}
DOWNLOAD_PREFS: dict[str, Any] = {}
INPUT_FILE = ""
OUTPUT_FILE = ""
BASE_PDF_DIR = ""
TEMP_DIR = ""
IMG_PATH = ""
DEBUG_DIR = ""
CHAOJIYING_USER = ""
CHAOJIYING_PASS = ""
CHAOJIYING_SOFT_ID = ""
HEADLESS_BROWSER = False
WORKER_HOST = "127.0.0.1"
WORKER_PORT = 8765


def _sync_dependent_modules() -> None:
    module_overrides = {
        "grab_module": {
            "INPUT_FILE": INPUT_FILE,
            "BASE_PDF_DIR": BASE_PDF_DIR,
            "TEMP_DIR": TEMP_DIR,
            "IMG_PATH": IMG_PATH,
            "DEBUG_DIR": DEBUG_DIR,
            "DB_CONFIG": DB_CONFIG,
            "CHAOJIYING_USER": CHAOJIYING_USER,
            "CHAOJIYING_PASS": CHAOJIYING_PASS,
            "CHAOJIYING_SOFT_ID": CHAOJIYING_SOFT_ID,
            "CAPTCHA_CODE_TYPE": CAPTCHA_CODE_TYPE,
            "XPATHS_MAPPING": XPATHS_MAPPING,
            "ELEMENT_TIMEOUT": ELEMENT_TIMEOUT,
            "PDF_DOWNLOAD_TIMEOUT": PDF_DOWNLOAD_TIMEOUT,
        },
        "search_module": {
            "DEFAULT_KEYWORDS": DEFAULT_KEYWORDS,
            "OUTPUT_FILE": OUTPUT_FILE,
        },
        "utils": {
            "DOWNLOAD_PREFS": DOWNLOAD_PREFS,
            "HEADLESS_BROWSER": HEADLESS_BROWSER,
        },
        "gui_main": {
            "DB_CONFIG": DB_CONFIG,
        },
    }
    for module_name, attributes in module_overrides.items():
        module = sys.modules.get(module_name)
        if module is None:
            continue
        for attr_name, attr_value in attributes.items():
            setattr(module, attr_name, attr_value)


def _recompute_runtime_fields() -> None:
    global INPUT_FILE, OUTPUT_FILE, BASE_PDF_DIR, TEMP_DIR, IMG_PATH, DEBUG_DIR
    global CHAOJIYING_USER, CHAOJIYING_PASS, CHAOJIYING_SOFT_ID, HEADLESS_BROWSER
    global WORKER_HOST, WORKER_PORT

    OUTPUT_FILE = str(user_config.get("output_file", DEFAULT_CONFIG["output_file"]))
    INPUT_FILE = str(user_config.get("input_file", DEFAULT_CONFIG["input_file"]))
    BASE_PDF_DIR = _resolve_path(str(user_config.get("pdf_dir", "")), "pdf")
    TEMP_DIR = _resolve_path(str(user_config.get("temp_dir", "")), "temp_step2")
    DEBUG_DIR = _resolve_path(str(user_config.get("debug_dir", "")), "debug_output")
    IMG_PATH = os.path.join(get_base_dir(), "captcha_step2.png")

    DB_CONFIG.clear()
    DB_CONFIG.update(
        {
            "host": str(user_config.get("db_host", DEFAULT_CONFIG["db_host"])),
            "port": int(user_config.get("db_port", DEFAULT_CONFIG["db_port"])),
            "user": str(user_config.get("db_user", DEFAULT_CONFIG["db_user"])),
            "password": str(user_config.get("db_password", DEFAULT_CONFIG["db_password"])),
            "database": str(user_config.get("db_database", DEFAULT_CONFIG["db_database"])),
        }
    )

    CHAOJIYING_USER = str(user_config.get("chaojiying_user", ""))
    CHAOJIYING_PASS = str(user_config.get("chaojiying_pass", ""))
    CHAOJIYING_SOFT_ID = str(user_config.get("chaojiying_softid", ""))
    HEADLESS_BROWSER = bool(user_config.get("headless_browser", False))
    WORKER_HOST = str(user_config.get("worker_host", DEFAULT_CONFIG["worker_host"]))
    WORKER_PORT = int(user_config.get("worker_port", DEFAULT_CONFIG["worker_port"]))

    DOWNLOAD_PREFS.clear()
    DOWNLOAD_PREFS.update(
        {
            "download.default_directory": os.path.abspath(TEMP_DIR),
            "plugins.always_open_pdf_externally": True,
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
            "safebrowsing.enabled": False,
            "safebrowsing.disable_download_protection": True,
            "profile.default_content_setting_values.automatic_downloads": 1,
        }
    )

    _sync_dependent_modules()


def update_config(new_config: dict[str, Any]) -> None:
    for key, value in new_config.items():
        user_config[key] = _coerce_value(key, value)
    _recompute_runtime_fields()


_recompute_runtime_fields()
