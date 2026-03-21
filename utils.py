# utils.py - 通用工具模块
# 实现项目通用工具函数

import os
import sys
import logging
import re
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from config import DOWNLOAD_PREFS

# ================= 浏览器初始化 =================
def init_driver(download_dir=None):
    """初始化Chrome浏览器实例（含反爬参数）
    
    Args:
        download_dir: 下载目录路径，默认为None
    
    Returns:
        webdriver.Chrome: 配置好的Chrome浏览器实例
    """
    opts = Options()
    # 反爬配置
    opts.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
    opts.add_experimental_option('useAutomationExtension', False)
    opts.add_argument('--disable-blink-features=AutomationControlled')
    opts.add_argument('--start-maximized')
    opts.add_argument('--no-sandbox')
    opts.add_argument('--disable-dev-shm-usage')
    opts.add_argument('--ignore-certificate-errors')
    opts.add_argument('--allow-running-insecure-content')
    opts.add_argument('--disable-web-security')
    
    # 下载设置
    prefs = DOWNLOAD_PREFS.copy()
    if download_dir:
        prefs["download.default_directory"] = os.path.abspath(download_dir)
    opts.add_experimental_option("prefs", prefs)
    
    # 初始化浏览器
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=opts)
    # 进一步反爬处理
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver

# ================= 日志系统初始化 =================
def init_logger(log_file=None):
    """初始化日志系统
    
    Args:
        log_file: 日志文件路径，默认为None
    
    Returns:
        logging.Logger: 配置好的日志记录器
    """
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # 清空现有处理器
    if logger.handlers:
        logger.handlers.clear()
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    # 日志格式
    formatter = logging.Formatter('%(asctime)s - %(message)s')
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # 文件处理器（如果指定）
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger

# ================= Excel文件操作 =================
def read_excel(file_path):
    """读取Excel文件
    
    Args:
        file_path: Excel文件路径
    
    Returns:
        pandas.DataFrame: 读取的数据
    """
    try:
        df = pd.read_excel(file_path).dropna(how='all').reset_index(drop=True)
        return df
    except Exception as e:
        raise Exception(f"读取Excel文件失败: {e}")

def write_excel(data, file_path):
    """写入Excel文件
    
    Args:
        data: 要写入的数据列表
        file_path: Excel文件路径
    """
    try:
        df = pd.DataFrame(data)
        df.to_excel(file_path, index=False)
    except Exception as e:
        raise Exception(f"写入Excel文件失败: {e}")

# ================= 文本处理 =================
def clean_text(text):
    """清理文本中的多余空白
    
    Args:
        text: 原始文本
    
    Returns:
        str: 清理后的文本
    """
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

# ================= URL构造 =================
def build_detail_url(tid, pid):
    """根据标准类型构造详情页URL
    
    Args:
        tid: 标准类型ID
        pid: 标准ID
    
    Returns:
        str: 详情页URL
    """
    if tid == 'BV_GB':
        return f"https://std.samr.gov.cn/gb/search/gbDetailed?id={pid}"
    elif tid == 'BV_HB':
        return f"https://std.samr.gov.cn/hb/search/stdHBDetailed?id={pid}"
    elif tid == 'BV_DB':
        return f"https://std.samr.gov.cn/db/search/stdDBDetailed?id={pid}"
    else:
        return None

# ================= 目录操作 =================
def ensure_dir(directory):
    """确保目录存在，如果不存在则创建
    
    Args:
        directory: 目录路径
    """
    if not os.path.exists(directory):
        os.makedirs(directory, exist_ok=True)

# ================= 标准类型判断 =================
def get_standard_type(code):
    """根据标准号判断标准类型
    
    Args:
        code: 标准号
    
    Returns:
        str: 标准类型（"国标"、"地标"或"行标"）
    """
    if not code or pd.isna(code):
        return "行标"
    code_prefix = str(code).strip().upper()[:2]
    if code_prefix == "GB":
        return "国标"
    elif code_prefix == "DB":
        return "地标"
    else:
        return "行标"
