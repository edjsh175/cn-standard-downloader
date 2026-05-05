# config.py - 配置管理模块
# 集中管理所有可配置参数，敏感信息使用占位符

import os
import sys
import json

# ================= 资源路径处理 =================
def get_resource_path(relative_path):
    """获取资源文件的绝对路径，兼容PyInstaller打包环境"""
    try:
        # PyInstaller创建的临时文件夹
        base_path = sys._MEIPASS
    except AttributeError:
        # 正常Python环境
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

def get_base_dir():
    """获取基础目录（脚本目录或exe所在目录）"""
    if getattr(sys, 'frozen', False):
        # PyInstaller打包的exe
        return os.path.dirname(sys.executable)
    else:
        # 正常Python环境
        return os.path.dirname(os.path.abspath(__file__))

def get_appdata_config_path():
    """获取用户配置文件的路径（AppData目录）"""
    if hasattr(sys, '_MEIPASS'):  # 打包环境
        appdata_dir = os.path.join(os.environ.get('APPDATA', ''), '国标爬虫系统')
        os.makedirs(appdata_dir, exist_ok=True)
        return os.path.join(appdata_dir, 'config_user.json')
    else:
        # 开发环境，使用脚本同目录
        return "config_user.json"

# ================= 配置文件管理 =================
CONFIG_FILE = get_appdata_config_path()

def load_config():
    """从配置文件加载用户配置"""
    default_config = {
        # 数据库配置
        "db_host": "localhost",
        "db_port": 3306,
        "db_user": "root",
        "db_password": "",
        "db_database": "disaster_knowledge",
        # 超级鹰配置
        "chaojiying_user": "",
        "chaojiying_pass": "",
        "chaojiying_softid": "",
        # 文件存储路径配置
        "pdf_dir": "",  # PDF存储目录，为空时使用相对路径"./pdf"
        "input_file": "待抓取标准清单_全标准.xlsx",  # 输入Excel文件名
        "output_file": "待抓取标准清单_全标准.xlsx",  # 输出Excel文件名
        "temp_dir": "temp_step2",  # 临时目录
        "debug_dir": "debug_output",  # 调试输出目录
        "remember_config": False
    }

    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                # 合并配置，以加载的为准，缺失的使用默认值
                default_config.update(loaded)
        except Exception as e:
            print(f"⚠️ 加载配置文件失败，使用默认值: {e}")

    return default_config

def save_config(config):
    """保存配置到文件"""
    try:
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"❌ 保存配置文件失败: {e}")
        return False

# 加载用户配置
user_config = load_config()

# ================= 搜索模块配置 =================
# 默认关键词
DEFAULT_KEYWORDS = ["人工智能"]
# 搜索结果输出文件（从配置读取，如果配置为空则使用默认文件名）
OUTPUT_FILE = user_config.get("output_file", "待抓取标准清单_全标准.xlsx")

# ================= 抓取模块配置 =================
# 输入文件路径（从配置读取，如果配置为空则使用默认文件名）
INPUT_FILE = user_config.get("input_file", "待抓取标准清单_全标准.xlsx")
# PDF存储基础目录（从配置读取，如果配置为空则使用相对路径"./pdf"）
pdf_dir_config = user_config.get("pdf_dir", "")
if pdf_dir_config:
    # 如果用户提供了路径，检查是否是绝对路径
    if os.path.isabs(pdf_dir_config):
        BASE_PDF_DIR = pdf_dir_config
    else:
        # 相对路径基于脚本目录解析
        BASE_PDF_DIR = os.path.join(get_base_dir(), pdf_dir_config)
else:
    BASE_PDF_DIR = os.path.join(get_base_dir(), "pdf")
# 临时目录（从配置读取，如果配置为空则使用默认值）
temp_dir_config = user_config.get("temp_dir", "")
if temp_dir_config:
    # 如果用户提供了路径，检查是否是绝对路径
    if os.path.isabs(temp_dir_config):
        TEMP_DIR = temp_dir_config
    else:
        # 相对路径基于脚本目录解析
        TEMP_DIR = os.path.join(get_base_dir(), temp_dir_config)
else:
    TEMP_DIR = os.path.join(get_base_dir(), "temp_step2")
# 验证码图片路径
IMG_PATH = os.path.join(get_base_dir(), "captcha_step2.png")
# 调试输出目录（从配置读取，如果配置为空则使用默认值）
debug_dir_config = user_config.get("debug_dir", "")
if debug_dir_config:
    # 如果用户提供了路径，检查是否是绝对路径
    if os.path.isabs(debug_dir_config):
        DEBUG_DIR = debug_dir_config
    else:
        # 相对路径基于脚本目录解析
        DEBUG_DIR = os.path.join(get_base_dir(), debug_dir_config)
else:
    DEBUG_DIR = os.path.join(get_base_dir(), "debug_output")

# ================= 数据库配置 =================
# 从用户配置读取（默认值已在load_config中设置）
DB_CONFIG = {
    'host': user_config.get("db_host", "localhost"),
    'port': int(user_config.get("db_port", 3306)),
    'user': user_config.get("db_user", "root"),
    'password': user_config.get("db_password", ""),
    'database': user_config.get("db_database", "disaster_knowledge")
}

# ================= 超级鹰配置 =================
# 从用户配置读取（默认值已在load_config中设置为空字符串）
CHAOJIYING_USER = user_config.get("chaojiying_user", "")
CHAOJIYING_PASS = user_config.get("chaojiying_pass", "")
CHAOJIYING_SOFT_ID = user_config.get("chaojiying_softid", "")
CAPTCHA_CODE_TYPE = 1902  # 4位数字字母

# ================= 浏览器配置 =================
# 浏览器超时设置
DRIVER_TIMEOUT = 30
# 元素等待超时设置
ELEMENT_TIMEOUT = 5
# PDF下载超时设置
PDF_DOWNLOAD_TIMEOUT = 90

# ================= 核心XPATHS映射 =================
# 原脚本分支保留：针对国标、行标、地标的不同XPath配置
XPATHS_MAPPING = {
    "国标": {
        'release_date': '//dt[contains(text(), "发布日期")]/following-sibling::dd[1]',
        'implement_date': '//dt[contains(text(), "实施日期")]/following-sibling::dd[1]',
        'charge_unit': '//dt[contains(text(), "归口单位")]/following-sibling::dd[1]',
        'release_unit': '//dt[contains(text(), "主管部门")]/following-sibling::dd[1]',
        'draft_unit': '/html/body/div[3]/div/div/div/div[10]//dl//dd',
        'drafter': '/html/body/div[3]/div/div/div/div[12]//dl//dd',
        'scope': '',
        'english_name': '',
        'replace_info': '',
        'reference': '//h2[contains(text(), "相近标准(计划)")]/following-sibling::div[1]//li',
        'view_text_btn': '/html/body/div[5]/div/div[1]',
        'download_standard_btn': '/html/body/div[3]/div/div/div/div/table[2]/tbody/tr[4]/td/button[2]',
        'captcha_input': '//input[@id="verifyCode"]',
        'captcha_img': '//img[@class="verifyCode"]',
        'verify_btn': '//button[contains(@class, "btn-primary") and text()="验证"]',
        'unincluded_h1': '//h1[contains(text(), "您所查询的标准系统尚未收录")]',
        'copyright_span': '//span[contains(@class, "text-danger") and contains(text(), "涉及版权保护问题")]'
    },
    "地标": {
        'release_date': '//dt[contains(text(), "发布日期")]/following-sibling::dd[1]',
        'implement_date': '//dt[contains(text(), "实施日期")]/following-sibling::dd[1]',
        'charge_unit': '//dt[contains(text(), "归口单位")]/following-sibling::dd[1]',
        'release_unit': '//dt[contains(text(), "主管部门")]/following-sibling::dd[1]',
        'draft_unit': '/html/body/div[3]/div/div/div/div[11]/dl[1]/dd/a',
        'drafter': '/html/body/div[3]/div/div/div/div[13]/dl[1]/dd',
        'scope': '//h2[contains(text(), "适用范围")]/following-sibling::p[1]',
        'english_name': '',
        'replace_info': '',
        'reference': '//h2[contains(text(), "相近标准(计划)")]/following-sibling::div[1]//li',
        'view_text_btn': '/html/body/div[5]/div/div',
        'captcha_img': '/html/body/div/div/div/div/div/div/div[2]/form/img',
        'captcha_input': '/html/body/div/div/div/div/div/div/div[2]/form/div[1]/input',
        'download_btn': '/html/body/div/div/div/div/div/div/div[3]/button[2]'
    },
    "行标": {
        'release_date': '//dt[contains(text(), "发布日期")]/following-sibling::dd[1]',
        'implement_date': '//dt[contains(text(), "实施日期")]/following-sibling::dd[1]',
        'charge_unit': '//dt[contains(text(), "技术归口")]/following-sibling::dd[1]',
        'release_unit': '//dt[contains(text(), "批准发布部门")]/following-sibling::dd[1]',
        'draft_unit': '/html/body/div[3]/div/div/div/div[11]/dl[1]/dd/a',
        'drafter': '/html/body/div[3]/div/div/div/div[13]/dl[1]/dd',
        'scope': '//h2[contains(text(), "适用范围")]/parent::div/following-sibling::p[1]',
        'english_name': '//dt[contains(text(), "英文名称")]/following-sibling::dd[1]',
        'replace_info': '//dt[contains(text(), "替代情况")]/following-sibling::dd[1]',
        'reference': '//div[contains(@class, "referencedStandards")]//table',
        'view_text_btn': '//a[contains(., "查看文本")]',
        'captcha_img': '//*[@id="validate-code"]',
        'captcha_input': '//*[@id="captcha-input"]',
        'download_btn': '//*[@id="download-btn"]'
    }
}

# ================= 标准类型映射 =================
# 标准类型判断映射
STANDARD_TYPE_MAPPING = {
    "GB": "国标",
    "DB": "地标"
    # 其他默认为行标
}

# ================= 浏览器配置 =================
# 浏览器下载设置
DOWNLOAD_PREFS = {
    "download.default_directory": os.path.abspath(TEMP_DIR),
    "plugins.always_open_pdf_externally": True,
    "download.prompt_for_download": False,
    "download.directory_upgrade": True,
    "safebrowsing.enabled": False,
    "safebrowsing.disable_download_protection": True,
    "profile.default_content_setting_values.automatic_downloads": 1,
}

# ================= 配置更新函数 =================
def update_config(new_config):
    """更新配置并重新计算所有派生变量

    Args:
        new_config: 新的配置字典
    """
    global user_config, DB_CONFIG, CHAOJIYING_USER, CHAOJIYING_PASS, CHAOJIYING_SOFT_ID
    global INPUT_FILE, OUTPUT_FILE, BASE_PDF_DIR, TEMP_DIR, IMG_PATH, DEBUG_DIR, DOWNLOAD_PREFS

    # 更新用户配置
    user_config.update(new_config)

    # 重新计算数据库配置
    DB_CONFIG.update({
        'host': user_config.get("db_host", "localhost"),
        'port': int(user_config.get("db_port", 3306)),
        'user': user_config.get("db_user", "root"),
        'password': user_config.get("db_password", ""),
        'database': user_config.get("db_database", "disaster_knowledge")
    })

    # 重新计算超级鹰配置
    CHAOJIYING_USER = user_config.get("chaojiying_user", "")
    CHAOJIYING_PASS = user_config.get("chaojiying_pass", "")
    CHAOJIYING_SOFT_ID = user_config.get("chaojiying_softid", "")

    # 重新计算文件路径配置
    OUTPUT_FILE = user_config.get("output_file", "待抓取标准清单_全标准.xlsx")
    INPUT_FILE = user_config.get("input_file", "待抓取标准清单_全标准.xlsx")

    # PDF存储目录
    pdf_dir_config = user_config.get("pdf_dir", "")
    if pdf_dir_config:
        if os.path.isabs(pdf_dir_config):
            BASE_PDF_DIR = pdf_dir_config
        else:
            BASE_PDF_DIR = os.path.join(get_base_dir(), pdf_dir_config)
    else:
        BASE_PDF_DIR = os.path.join(get_base_dir(), "pdf")

    # 临时目录
    temp_dir_config = user_config.get("temp_dir", "")
    if temp_dir_config:
        if os.path.isabs(temp_dir_config):
            TEMP_DIR = temp_dir_config
        else:
            TEMP_DIR = os.path.join(get_base_dir(), temp_dir_config)
    else:
        TEMP_DIR = os.path.join(get_base_dir(), "temp_step2")

    # 调试输出目录
    debug_dir_config = user_config.get("debug_dir", "")
    if debug_dir_config:
        if os.path.isabs(debug_dir_config):
            DEBUG_DIR = debug_dir_config
        else:
            DEBUG_DIR = os.path.join(get_base_dir(), debug_dir_config)
    else:
        DEBUG_DIR = os.path.join(get_base_dir(), "debug_output")

    # IMG_PATH不变，因为它是相对于脚本目录的固定路径
    IMG_PATH = os.path.join(get_base_dir(), "captcha_step2.png")

    # 更新下载首选项中的临时目录
    DOWNLOAD_PREFS["download.default_directory"] = os.path.abspath(TEMP_DIR)
