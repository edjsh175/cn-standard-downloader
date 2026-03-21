# grab_module.py - 抓取功能模块
# 完整迁移grab_v1.py中的业务逻辑及条件分支

import os
import time
import re
import shutil
import pandas as pd
import pymysql
import requests
import pyautogui
from hashlib import md5
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, NoSuchWindowException
from config import (
    INPUT_FILE, BASE_PDF_DIR, TEMP_DIR, IMG_PATH, DEBUG_DIR,
    DB_CONFIG, CHAOJIYING_USER, CHAOJIYING_PASS, CHAOJIYING_SOFT_ID,
    CAPTCHA_CODE_TYPE, XPATHS_MAPPING, ELEMENT_TIMEOUT, PDF_DOWNLOAD_TIMEOUT
)
from utils import init_driver, init_logger, read_excel, ensure_dir, get_standard_type

# ================= 超级鹰验证码类 =================
class Chaojiying_Client:
    def __init__(self, username, password, soft_id):
        self.username = username
        self.password = md5(password.encode('utf-8')).hexdigest()
        self.soft_id = soft_id
        self.base_params = {'user': self.username, 'pass2': self.password, 'softid': self.soft_id}
        self.headers = {'Connection': 'Keep-Alive', 'User-Agent': 'Mozilla/4.0 (compatible; MSIE 8.0; Windows NT 5.1; Trident/4.0)'}
    
    def PostPic(self, im, codetype):
        params = {'codetype': codetype}
        params.update(self.base_params)
        files = {'userfile': ('captcha.jpg', im)}
        try:
            return requests.post('http://upload.chaojiying.net/Upload/Processing.php', data=params, files=files, headers=self.headers).json()
        except Exception as e:
            logger = init_logger()
            logger.error(f"❌ 验证码平台请求异常: {e}")
            return {"err_no": -1, "err_str": "平台请求失败"}

# ================= 核心爬虫类 =================
class BatchCrawler:
    def __init__(self):
        # 先初始化logger
        self.logger = init_logger("s2_all_standard_db_adapt.log")
        # 然后再调用setup_env
        self.setup_env()
        self.cjy = Chaojiying_Client(CHAOJIYING_USER, CHAOJIYING_PASS, CHAOJIYING_SOFT_ID)
        self.WAIT_TIME = ELEMENT_TIMEOUT
        self.current_code = ""
        # 【新增失败Excel】初始化失败条目列表
        self.failed_items = []

    def setup_env(self):
        """设置环境"""
        # 创建必要的目录
        ensure_dir(TEMP_DIR)
        ensure_dir(BASE_PDF_DIR)
        ensure_dir(DEBUG_DIR)
        
        self.logger.info(f"📁 临时目录: {os.path.abspath(TEMP_DIR)}")
        self.logger.info(f"📁 PDF存储目录: {os.path.abspath(BASE_PDF_DIR)}")
        self.logger.info(f"📁 调试目录: {os.path.abspath(DEBUG_DIR)}")
        
        # 数据库连接
        try:
            self.db = pymysql.connect(**DB_CONFIG, charset='utf8mb4')
            self.cursor = self.db.cursor()
            self.logger.info("✅ 数据库连接成功")
        except Exception as e:
            self.logger.error(f"❌ 数据库连接失败: {e}")
            raise
        
        # 初始化浏览器
        self._init_driver()
        
    def _init_driver(self):
        """初始化浏览器"""
        self.driver = init_driver(TEMP_DIR)
        self.driver.set_page_load_timeout(30)
        self.logger.info("✅ 浏览器初始化成功")
        
    def _ensure_driver_alive(self):
        """检查浏览器是否存活，若失效则彻底重启"""
        need_restart = False
        if self.driver is None:
            need_restart = True
        else:
            try:
                # 尝试获取窗口句柄，如果浏览器被手动关闭，这里会抛出异常
                _ = self.driver.current_window_handle
            except Exception:
                self.logger.warning("⚠️ 检测到浏览器已关闭或连接失效，正在尝试重新启动...")
                need_restart = True
        
        if need_restart:
            try:
                if self.driver:
                    self.driver.quit()
            except:
                pass
            self._init_driver() # 重新初始化浏览器

    def quick_extract_meta(self, xpaths):
        """批量提取元数据
        
        Args:
            xpaths: XPath映射字典
        
        Returns:
            dict: 提取的元数据
        """
        results = {}
        for key, xpath in xpaths.items():
            if not xpath:
                results[key] = None
                continue
            try:
                els = self.driver.find_elements(By.XPATH, xpath)
                if els:
                    if key in ["draft_unit", "drafter"]:
                        text_list = [el.text.strip() for el in els if el.text.strip()]
                        text = "；".join([t.replace("，", "；").replace("、", "；") for t in text_list])
                    else:
                        text = els[0].text.strip()
                    results[key] = text if text else None
                    if text:
                        self.logger.info(f"   📝 [{self.current_code}] {key}: {text[:50]}{'...' if len(text) > 50 else ''}")
                else:
                    results[key] = None
                    self.logger.warning(f"   ⚪ [{self.current_code}] {key}: 未找到任何有效文本内容")
            except Exception as e:
                results[key] = None
                self.logger.error(f"   ❌ [{self.current_code}] {key}: 提取失败（{e.__class__.__name__}）")
        return results

    def save_db(self, m, path, table_name="standard_norm_detail"):
        """保存数据到数据库
        
        Args:
            m: 元数据字典
            path: PDF文件路径
            table_name: 数据库表名，默认为standard_norm_detail
        """
        draft_unit_val = m.get('draft_unit') or "无"
        drafter_val = m.get('drafter') or "无"
        keyword_val = m.get('keyword') or "无"
        
        self.logger.info(f"📥 入库参数 - 标准号: {m['code']} | 关键词: {keyword_val} | 表名: {table_name}")
        
        sql = f"""INSERT INTO {table_name} 
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
            m['code'],
            keyword_val,
            draft_unit_val,
            drafter_val,
            m.get('name') or "无",
            m.get('english_name') or "无",
            m.get('release_date') or None,
            m.get('implement_date') or None,
            m.get('release_unit') or "无",
            m.get('charge_unit') or "无",
            m.get('replace_standard') or "无",
            m.get('status') or "现行",
            m.get('application_scope') or "无",
            m.get('reference_standard') or "无",
            path or "无",
            m.get('ps') or "无"
        )
        
        try:
            self.cursor.execute(sql, params)
            self.db.commit()
            self.logger.info(f"💾 入库成功 -> {m.get('ps')}")
        except Exception as e:
            # 原脚本分支保留：数据入库异常时的事务回滚处理
            self.db.rollback()
            error_msg = f"❌ 入库失败: {e}"
            self.logger.error(error_msg)
            # 【新增失败Excel】记录失败条目
            self._add_failed_item(m, f"数据库入库失败：{str(e)[:50]}")

    def get_pdf_save_path(self, row, code, name):
        """获取PDF保存路径（按关键词分类）
        
        Args:
            row: 数据行
            code: 标准号
            name: 标准名称
        
        Returns:
            str: PDF保存路径
        """
        keyword = str(row.get('keyword', '')).strip()
        if not keyword or keyword.lower() == 'nan':
            keyword = '其他'
        
        # 清理关键词中的非法字符
        safe_keyword = re.sub(r'[\\/*?"<>|:]', '_', keyword)
        
        # 创建关键词目录
        keyword_dir = os.path.join(BASE_PDF_DIR, safe_keyword)
        ensure_dir(keyword_dir)
        
        # 清理标准号和名称中的非法字符
        safe_code = re.sub(r'[\\/*?"<>|:]', '_', str(code))
        safe_name = re.sub(r'[\\/*?"<>|:]', '_', str(name))
        
        return os.path.join(keyword_dir, f"{safe_code} {safe_name}.pdf")

    def clear_temp(self):
        """清空临时下载目录"""
        self.logger.info(f"🧹 清空临时下载目录...")
        count = 0
        for f in os.listdir(TEMP_DIR):
            try:
                os.remove(os.path.join(TEMP_DIR, f))
                count += 1
            except:
                pass
        self.logger.info(f"🧹 临时目录清理完成，共删除 {count} 个文件")

    def _add_failed_item(self, row, fail_reason):
        """添加失败条目到内存列表
        
        Args:
            row: 标准数据行
            fail_reason: 失败原因
        """
        import time
        
        # 自动分类错误类型
        error_type = self._classify_error(fail_reason)
        
        # 构造失败条目
        failed_item = {
            'detail_url': row.get('detail_url'),
            'code': row.get('code'),
            'name': row.get('name'),
            'fail_reason': fail_reason,
            'error_type': error_type,
            'execution_time': time.strftime('%Y-%m-%d %H:%M:%S'),
            'keyword': row.get('keyword'),
            'standard_type': row.get('type', '未知')
        }
        
        # 按detail_url去重：同一标准多次失败仅保留最后一次
        detail_url = failed_item['detail_url']
        existing_index = None
        for i, item in enumerate(self.failed_items):
            if item['detail_url'] == detail_url:
                existing_index = i
                break
        
        if existing_index is not None:
            # 更新现有条目
            self.failed_items[existing_index] = failed_item
            self.logger.info(f"🔄 更新失败条目: {detail_url} - {fail_reason[:30]}")
        else:
            # 添加新条目
            self.failed_items.append(failed_item)
            self.logger.info(f"📝 记录失败条目: {detail_url} - {fail_reason[:30]}")
    
    def _classify_error(self, fail_reason):
        """自动分类错误类型
        
        Args:
            fail_reason: 失败原因
        
        Returns:
            str: 错误类型
        """
        error_type_map = {
            '网络错误': ['网络', '超时', '连接', 'download', 'timeout', 'connection'],
            '数据格式错误': ['格式', '数据', '字段', '缺失'],
            '权限不足': ['权限', '未公开', '版权', '无法访问'],
            '验证码错误': ['验证码', 'captcha'],
            '系统错误': ['系统', '异常', '崩溃', '错误'],
            '其他错误': []
        }
        
        fail_reason_lower = fail_reason.lower()
        for error_type, keywords in error_type_map.items():
            if error_type == '其他错误':
                continue
            for keyword in keywords:
                if keyword in fail_reason_lower:
                    return error_type
        return '其他错误'

    def safe_close_window(self, main_handle):
        """安全关闭窗口
        
        Args:
            main_handle: 主窗口句柄
        """
        try:
            if len(self.driver.window_handles) > 1 and self.driver.current_window_handle != main_handle:
                self.driver.close()
            self.driver.switch_to.window(main_handle)
        except:
            pass

    def physical_bypass_download_block(self):
        """国标专用物理模拟按键绕过下载拦截"""
        self.logger.info(f"   ⌨️ [{self.current_code}] 启动物理外挂：修正击键序列...")
        time.sleep(2.5) 
        
        pyautogui.hotkey('ctrl', 'j')
        self.logger.info(f"   ⌨️ [{self.current_code}] 已打开下载管理页")
        time.sleep(2.5) 
        
        self.logger.info(f"   ⌨️ [{self.current_code}] 正在执行 Tab 导航 (3次)...")
        for _ in range(3):
            pyautogui.press('tab')
            time.sleep(0.3)
        
        pyautogui.press('enter')
        self.logger.info(f"   ⌨️ [{self.current_code}] 按下『向下键』切换焦点到'保留'选项...")
        pyautogui.press('down') 
        time.sleep(0.5)
        
        pyautogui.press('enter')
        self.logger.info(f"   ⌨️ [{self.current_code}] 已发送确认指令")
        
        time.sleep(1)
        pyautogui.hotkey('ctrl', 'w')
        self.logger.info(f"   ⌨️ [{self.current_code}] 物理模拟操作流结束，返回主页面。")

    def process_one(self, row):
        """处理单个标准
        
        Args:
            row: 标准数据行
        """
        try:
            # 尝试获取句柄，如果这里崩了，说明 session 没了
            _ = self.driver.current_window_handle
        except Exception:
            self.logger.error("❌ 运行中连接断开，尝试紧急重连...")
            self._ensure_driver_alive()
        
        code = row.get('code')
        name = row.get('name')
        detail_url = row.get('detail_url')
        keyword = row.get('keyword')  # 获取关键词
        
        self.current_code = code
        
        if not code or not name or not detail_url:
            self.logger.error(f"❌ 信息缺失: code={code}, name={name}, url={detail_url}，直接跳过")
            # 【新增失败Excel】记录失败条目
            self._add_failed_item(row, "页面解析失败：核心字段（标准号/名称/URL）为空")
            return
        
        # 原脚本分支保留：针对国标、行标、地标等不同类型文档的XPath适配处理
        standard_type = get_standard_type(code)
        current_xpaths = XPATHS_MAPPING[standard_type]
        
        self.logger.info(f"\n{'='*80}")
        self.logger.info(f"▶️ 处理 [{standard_type}] {code} - {name[:50]}{'...' if len(name) > 50 else ''}")
        self.logger.info(f"🔗 详情链接: {detail_url}")
        self.logger.info(f"🏷️  关键词: {keyword}")
        
        meta = row.copy()
        meta['status'] = '现行'
        meta['ps'] = "提取中"
        final_pdf = ""
        
        # 获取主窗口句柄
        try:
            main_handle = self.driver.current_window_handle
        except Exception:
            self.logger.warning("⚠️ 检测到当前窗口句柄已失效，正在尝试切回主窗口...")
            all_handles = self.driver.window_handles
            if all_handles:
                self.driver.switch_to.window(all_handles[0])
                main_handle = self.driver.current_window_handle
                self.logger.info(f"✅ 已成功切回主窗口: {main_handle}")
            else:
                self.logger.error("❌ 浏览器所有窗口均已关闭，无法继续！")
                raise
        
        try:
            self.driver.get(detail_url)
            
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.XPATH, current_xpaths["release_date"]))
                )
            except:
                self.logger.warning(f"等待元数据超时，尝试直接提取...")
            
            self.logger.info(f"✅ 打开详情页，页面关键元素已加载")
            self.logger.info(f"📄 提取 [{standard_type}] 元数据...")
            
            # 使用批量提取方法
            fast_meta = self.quick_extract_meta({
                'release_date': current_xpaths['release_date'],
                'implement_date': current_xpaths['implement_date'],
                'charge_unit': current_xpaths['charge_unit'],
                'release_unit': current_xpaths['release_unit'],
                'draft_unit': current_xpaths['draft_unit'],
                'drafter': current_xpaths['drafter'],
                'scope': current_xpaths['scope'],
                'english_name': current_xpaths['english_name'],
                'replace_info': current_xpaths['replace_info'],
                'reference': current_xpaths['reference']
            })
            
            # 更新元数据
            meta['release_date'] = fast_meta['release_date']
            meta['implement_date'] = fast_meta['implement_date']
            meta['charge_unit'] = fast_meta['charge_unit']
            meta['release_unit'] = fast_meta['release_unit']
            meta['draft_unit'] = fast_meta['draft_unit']
            meta['drafter'] = fast_meta['drafter']
            meta['application_scope'] = fast_meta['scope']
            meta['english_name'] = fast_meta['english_name']
            meta['replace_standard'] = fast_meta['replace_info']
            meta['reference_standard'] = fast_meta['reference']
            
            if standard_type == "地标" and (not meta['english_name'] or pd.isna(meta['english_name'])):
                meta['english_name'] = "无"
                self.logger.info(f"   📝 英文名称: 无（地标自动填充）")
            
            # 验证并填充空值
            if not meta.get('draft_unit'):
                meta['draft_unit'] = "无"
                self.logger.warning(f"   ⚠️ 起草单位未提取到，填充为「无」")
            if not meta.get('drafter'):
                meta['drafter'] = "无"
                self.logger.warning(f"   ⚠️ 起草人未提取到，填充为「无」")
            
            meta['ps'] = "元数据提取完毕"
            self.logger.info(f"✅ [{standard_type}] 元数据提取完成")
            
            # 查看文本按钮、验证码处理、下载等逻辑
            view_text_xpath = current_xpaths.get('view_text_btn')
            if not view_text_xpath:
                meta['ps'] = "无查看文本按钮配置，跳过下载"
                self.save_db(meta, final_pdf)
                return
            
            view_btns = self.driver.find_elements(By.XPATH, view_text_xpath)
            if not view_btns:
                fail_reason = f"未找到查看文本按钮（XPath：{view_text_xpath}）"
                meta['ps'] = fail_reason
                self.logger.warning(f"⚪ {meta['ps']}")
                # 添加失败记录到失败清单
                self._add_failed_item(row, fail_reason)
                self.save_db(meta, final_pdf)
                return
            
            view_btn = WebDriverWait(self.driver, self.WAIT_TIME).until(
                EC.element_to_be_clickable((By.XPATH, view_text_xpath))
            )
            cur_handles = self.driver.window_handles
            view_btn.click()
            self.logger.info(f"🖱️ 点击查看文本按钮，等待新窗口弹出")
            
            WebDriverWait(self.driver, self.WAIT_TIME).until(EC.new_window_is_opened(cur_handles))
            preview_window = [h for h in self.driver.window_handles if h not in cur_handles][0]
            self.driver.switch_to.window(preview_window)
            
            try:
                WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.TAG_NAME, "h1")))
            except:
                pass
            
            self.logger.info(f"✅ 切换到预览窗口，开始执行后续流程")
            
            # 原脚本分支保留：国标文档未公开状态的判断与处理逻辑
            if standard_type == "国标":
                self.logger.info(f"[{standard_type}] 执行双未公开判断")
                unpublic_reason = None
                try:
                    unincluded_h1 = self.driver.find_element(By.XPATH, current_xpaths['unincluded_h1'])
                    if unincluded_h1 and unincluded_h1.text.strip():
                        unpublic_reason = "系统尚未收录（" + unincluded_h1.text.strip() + "）"
                except NoSuchElementException:
                    pass
                
                if not unpublic_reason:
                    try:
                        copyright_span = self.driver.find_element(By.XPATH, current_xpaths['copyright_span'])
                        if copyright_span and copyright_span.text.strip():
                            unpublic_reason = "涉及版权保护，暂不提供在线阅读服务"
                    except NoSuchElementException:
                        pass
                
                if unpublic_reason:
                    meta['ps'] = f"未公开: {unpublic_reason[:50]}"
                    self.logger.warning(f"⚠️ {meta['ps']}")
                    # 【新增失败Excel】记录失败条目
                    self._add_failed_item(row, f"标准未公开：{unpublic_reason}")
                    self.safe_close_window(main_handle)
                    self.save_db(meta, final_pdf)
                    return
                
                self.logger.info(f"[{standard_type}] 未命中未公开场景，继续执行专属流程")
            
            # 行标未公开判断
            if standard_type == "行标":
                self.logger.info(f"[{standard_type}] 执行优化后的未公开判断逻辑")
                unpublic_reason = None
                
                # 1. 优先检查是否存在验证码图片。如果存在验证码，说明页面是可访问的，不应判定为"未公开"
                captcha_xpath = current_xpaths.get('captcha_img')
                captcha_elements = self.driver.find_elements(By.XPATH, captcha_xpath) if captcha_xpath else []
                
                if not captcha_elements:
                    # 2. 只有在没有验证码的情况下，才去检查是否有真正的"未公开"提示
                    danger_span = self.driver.find_elements(By.CSS_SELECTOR, "span.text-danger")
                    tip_p = self.driver.find_elements(By.CSS_SELECTOR, "div.tip p")
                    tip_h3 = self.driver.find_elements(By.CSS_SELECTOR, "div.tip h3")
                    
                    if danger_span and danger_span[0].text.strip():
                        text = danger_span[0].text.strip()
                        # 排除掉通用的免责声明，只有包含核心关键词时才判定为未公开
                        deny_keywords = ["不公开", "未公开", "暂无", "未授权", "没有找到", "公开属性：否"]
                        if any(kw in text for kw in deny_keywords):
                            unpublic_reason = text
                    elif tip_p and tip_p[0].text.strip():
                        text = tip_p[0].text.strip()
                        # 排除掉通用的免责声明（温馨提示：本系统所提供的电子文本仅供参考...）
                        # 只有包含"不公开"、"未公开"等关键词时才判定为失败
                        deny_keywords = ["不公开", "未公开", "暂无", "未授权", "没有找到", "公开属性：否"]
                        if any(kw in text for kw in deny_keywords):
                            unpublic_reason = text
                    elif tip_h3 and tip_h3[0].text.strip():
                        text = tip_h3[0].text.strip()
                        # 排除掉通用的"温馨提示"
                        if "温馨提示" not in text:
                            # 同样检查是否包含未公开关键词
                            deny_keywords = ["不公开", "未公开", "暂无", "未授权", "没有找到", "公开属性：否"]
                            if any(kw in text for kw in deny_keywords):
                                unpublic_reason = text
                else:
                    self.logger.info(f"[{standard_type}] 检测到验证码环境，跳过未公开判定，准备进入识别流程")
                
                if unpublic_reason:
                    meta['ps'] = f"未公开: {unpublic_reason[:50]}"
                    self.logger.warning(f"⚠️ {meta['ps']}")
                    # 【新增失败Excel】记录失败条目
                    self._add_failed_item(row, f"标准未公开：{unpublic_reason}")
                    self.safe_close_window(main_handle)
                    self.save_db(meta, final_pdf)
                    return
            
            if standard_type == "地标":
                self.logger.info(f"[{standard_type}] 跳过未公开判断，直接进入验证码流程")
            
            # 国标下载标准按钮
            if standard_type == "国标":
                self.logger.info(f"[{standard_type}] 定位下载标准按钮（JS点击）...")
                download_standard_xpath = current_xpaths.get('download_standard_btn')
                if not download_standard_xpath:
                    meta['ps'] = "国标未配置下载标准按钮路径，无法继续"
                    self.logger.warning(f"⚪ {meta['ps']}")
                    self.safe_close_window(main_handle)
                    self.save_db(meta, final_pdf)
                    return
                
                pre_download_handles = self.driver.window_handles
                download_standard_btn = WebDriverWait(self.driver, self.WAIT_TIME).until(
                    EC.element_to_be_clickable((By.XPATH, download_standard_xpath))
                )
                self.driver.execute_script("arguments[0].click();", download_standard_btn)
                self.logger.info(f"🖱️ 点击国标下载标准按钮（JS方式），等待验证码新窗口...")
                
                WebDriverWait(self.driver, 10).until(EC.new_window_is_opened(pre_download_handles))
                new_captcha_handle = self.driver.window_handles[-1]
                self.driver.switch_to.window(new_captcha_handle)
                
                snapshot_path = os.path.join(DEBUG_DIR, f"{code}_captcha_window.png")
                self.driver.save_screenshot(snapshot_path)
                self.logger.info(f"✅ 已成功切换到验证码窗口: {self.driver.current_url}")
                self.logger.info(f"📸 验证码窗口快照已保存: {snapshot_path}")
            
            # 验证码处理
            captcha_img_xpath = current_xpaths.get('captcha_img')
            captcha_input_xpath = current_xpaths.get('captcha_input')
            action_btn_xpath = current_xpaths.get('verify_btn') if standard_type == "国标" else current_xpaths.get('download_btn')
            
            if not all([captcha_img_xpath, captcha_input_xpath, action_btn_xpath]):
                meta['ps'] = "验证码相关元素路径未配置，无法下载"
                self.logger.warning(f"⚪ {meta['ps']}")
                self.safe_close_window(main_handle)
                self.save_db(meta, final_pdf)
                return
            
            self.clear_temp()
            
            try:
                self.logger.info(f"🔍 定位验证码图片（XPath：{captcha_img_xpath}）| 最长等待{self.WAIT_TIME}秒")
                captcha_img = WebDriverWait(self.driver, self.WAIT_TIME).until(
                    EC.visibility_of_element_located((By.XPATH, captcha_img_xpath))
                )
                time.sleep(1)
                captcha_img.screenshot(IMG_PATH)
                
                debug_captcha_path = os.path.join(DEBUG_DIR, f"{code}_captcha.png")
                captcha_img.screenshot(debug_captcha_path)
                self.logger.info(f"📸 验证码截图成功，存储路径: {IMG_PATH} | 调试路径: {debug_captcha_path}")
                
                with open(IMG_PATH, 'rb') as f:
                    captcha_res = self.cjy.PostPic(f.read(), CAPTCHA_CODE_TYPE)
                
                # 原脚本分支保留：超级鹰验证码识别失败的重试与异常处理分支
                if captcha_res.get('err_no') != 0:
                    err_str = captcha_res.get('err_str', '未知错误')
                    meta['ps'] = f"验证码识别失败: {err_str}"
                    self.logger.error(f"❌ {meta['ps']}")
                    # 【新增失败Excel】记录失败条目
                    self._add_failed_item(row, f"验证码识别失败：{err_str}")
                    self.safe_close_window(main_handle)
                    self.save_db(meta, final_pdf)
                    return
                
                vcode = captcha_res['pic_str'].strip()
                self.logger.info(f"🔑 验证码识别成功: {vcode}")
                
                self.logger.info(f"🔍 定位验证码输入框（XPath：{captcha_input_xpath}）")
                captcha_input = WebDriverWait(self.driver, self.WAIT_TIME).until(
                    EC.visibility_of_element_located((By.XPATH, captcha_input_xpath))
                )
                captcha_input.click()
                captcha_input.clear()
                captcha_input.send_keys(vcode)
                self.logger.info(f"✅ 验证码输入完成: {vcode}")
                
                btn_type = "验证" if standard_type == "国标" else "下载"
                self.logger.info(f"🔍 定位{btn_type}按钮（XPath：{action_btn_xpath}）")
                action_btn = WebDriverWait(self.driver, self.WAIT_TIME).until(
                    EC.element_to_be_clickable((By.XPATH, action_btn_xpath))
                )
                time.sleep(0.5)
                self.driver.execute_script("arguments[0].click();", action_btn)
                self.logger.info(f"🖱️ 点击{btn_type}按钮（JS方式），开始监控PDF下载（超时{PDF_DOWNLOAD_TIMEOUT}秒）")
                
                # 国标流程调用物理绕过下载拦截
                if standard_type == "国标":
                    self.physical_bypass_download_block()
                
                # 原脚本分支保留：PDF文件下载超时的捕获与重试机制
                download_success = False
                start_time = time.time()
                timeout = PDF_DOWNLOAD_TIMEOUT
                
                while time.time() - start_time < timeout:
                    temp_files = os.listdir(TEMP_DIR)
                    temp_pdfs = [
                        f for f in temp_files
                        if f.endswith('.pdf') 
                        and not f.endswith('.crdownload') 
                        and os.path.getsize(os.path.join(TEMP_DIR, f)) > 100
                    ]
                    
                    if int(time.time() - start_time) % 5 == 0:
                        self.logger.info(f"⏳ 下载等待 {int(time.time() - start_time)}s | 临时目录有效PDF: {temp_pdfs}")
                    
                    if temp_pdfs:
                        src_pdf = os.path.join(TEMP_DIR, temp_pdfs[0])
                        time.sleep(2)
                        file_size_1 = os.path.getsize(src_pdf)
                        time.sleep(2)
                        file_size_2 = os.path.getsize(src_pdf)
                        
                        if file_size_1 == file_size_2:
                            # 获取PDF保存路径（按关键词分类）
                            dst_pdf = self.get_pdf_save_path(row, code, name)
                            
                            if os.path.exists(dst_pdf):
                                os.remove(dst_pdf)
                                self.logger.info(f"🔄 发现同名旧PDF，已删除并准备覆盖: {os.path.basename(dst_pdf)}")
                            
                            try:
                                shutil.move(src_pdf, dst_pdf)
                            except Exception as e:
                                meta['ps'] = f"PDF移动异常: {str(e)[:20]}"
                                self.logger.error(f"❌ {meta['ps']}")
                                break
                            
                            if os.path.exists(dst_pdf):
                                final_pdf = dst_pdf
                                meta['ps'] = "下载成功（已覆盖同名文件）" if meta['ps'] == "元数据提取完毕" else "下载成功"
                                download_success = True
                                self.logger.info(f"🎉 PDF下载并覆盖成功: {final_pdf}")
                            else:
                                meta['ps'] = "PDF移动失败，文件丢失"
                                self.logger.error(f"❌ {meta['ps']}")
                            break
                    
                    time.sleep(1)
                
                if not download_success and meta['ps'] == "元数据提取完毕":
                    meta['ps'] = f"PDF下载超时（{timeout}秒未检测到完整PDF文件）"
                    self.logger.error(f"❌ {meta['ps']}")
                    # 【新增失败Excel】记录失败条目
                    self._add_failed_item(row, meta['ps'])
                    
            except TimeoutException:
                meta['ps'] = f"验证码元素定位超时（最长等待{self.WAIT_TIME}秒）"
                self.logger.error(f"❌ {meta['ps']}")
                # 【新增失败Excel】记录失败条目
                self._add_failed_item(row, meta['ps'])
            except Exception as e:
                meta['ps'] = f"验证码/下载流程异常: {str(e)[:30]}"
                self.logger.error(f"❌ {meta['ps']}", exc_info=True)
                # 【新增失败Excel】记录失败条目
                self._add_failed_item(row, meta['ps'])
            
            self.safe_close_window(main_handle)
            
        except Exception as e:
            meta['ps'] = f"整体流程异常: {str(e)[:30]}"
            self.logger.error(f"❌ {meta['ps']}", exc_info=True)
            # 【新增失败Excel】记录失败条目
            self._add_failed_item(row, meta['ps'])
            self.safe_close_window(main_handle)
        
        # 保存到数据库
        self.save_db(meta, final_pdf)

    def run(self, excel_file=None):
        """运行抓取流程
        
        Args:
            excel_file: Excel文件路径，默认为None
        """
        try:
            # 只要点击了"仅爬取"或"完整流程"，就会触发这里
            self._ensure_driver_alive()
            
            # 使用指定的Excel文件或默认文件
            file_path = excel_file or INPUT_FILE
            df = read_excel(file_path)
            total_task = len(df)
            
            if total_task == 0:
                self.logger.error(f"❌ 待抓取Excel文件为空，程序直接退出")
                return
            
            self.logger.info(f"📂 成功加载Excel任务清单: {file_path} | 共 {total_task} 条待处理标准")
            
            necessary_cols = ['code', 'name', 'detail_url', 'keyword']
            missing_cols = [col for col in necessary_cols if col not in df.columns]
            
            if missing_cols:
                self.logger.error(f"❌ Excel文件缺少必要字段: {missing_cols} | 必须包含: {necessary_cols}")
                return
            
            for idx, (_, row) in enumerate(df.iterrows(), 1):
                self.process_one(row.to_dict())
                time.sleep(2)
                self.logger.info(f"📋 处理进度: {idx}/{total_task} | 剩余 {total_task - idx} 条")
            
            self.clear_temp()
            self.logger.info(f"\n{'='*80}")
            self.logger.info(f"🎉 所有 {total_task} 条标准处理完成！")
            self.logger.info(f"📄 详细执行日志: s2_all_standard_db_adapt.log")
            self.logger.info(f"📁 调试截图目录: {os.path.abspath(DEBUG_DIR)}")
            self.logger.info(f"📁 PDF存储目录: {os.path.abspath(BASE_PDF_DIR)}（按关键词分类存储）")
        
        except FileNotFoundError:
            self.logger.error(f"❌ 未找到Excel文件: {file_path}，请检查文件路径/文件名是否正确")
        except Exception as e:
            self.logger.error(f"❌ 爬虫主流程异常: {e}", exc_info=True)
        finally:
            try:
                self.driver.quit()
                self.logger.info("✅ 浏览器已正常关闭")
            except:
                pass
            try:
                self.cursor.close()
                self.db.close()
                self.logger.info("✅ 数据库连接已正常关闭")
            except:
                pass

    def generate_failed_excel(self, keywords=None, sort_by='error_type'):
        """生成失败Excel文件
        
        功能：
        - 无失败条目时，日志提示不生成文件
        - 有失败条目时，按指定方式排序
        - 按detail_url去重，保留最后一次失败原因
        - 生成带关键词的失败清单文件
        - 捕获异常，确保不中断主流程
        
        Args:
            keywords: 关键词列表，用于文件名
            sort_by: 排序方式 ('error_type', 'time', 'frequency')
        """
        # 【新增失败Excel】检查失败条目数量
        if not self.failed_items:
            self.logger.info("📭 无失败标准条目，不生成失败Excel")
            return
        
        try:
            self.logger.info(f"🔄 开始生成失败Excel，共 {len(self.failed_items)} 条失败记录")
            
            # 【新增失败Excel】按detail_url去重，保留最后一次失败原因
            unique_items = {}
            for item in self.failed_items:
                unique_items[item['detail_url']] = item
            
            # 转换回列表
            final_items = list(unique_items.values())
            
            # 【新增排序】根据sort_by参数排序
            if sort_by == 'time':
                # 按执行时间排序
                final_items.sort(key=lambda x: x['execution_time'], reverse=True)
            elif sort_by == 'frequency':
                # 按错误类型频率排序
                error_counts = {}
                for item in final_items:
                    error_counts[item['error_type']] = error_counts.get(item['error_type'], 0) + 1
                final_items.sort(key=lambda x: (-error_counts[x['error_type']], x['error_type']))
            else:  # error_type
                # 按错误类型排序
                final_items.sort(key=lambda x: (x['error_type'], x['execution_time'], x['code']))
            
            self.logger.info(f"🔄 去重后剩余 {len(final_items)} 条失败记录")
            
            # 【新增失败Excel】构建DataFrame并确保字段顺序
            import pandas as pd
            df = pd.DataFrame(final_items, columns=['code', 'name', 'detail_url', 'error_type', 'fail_reason', 'execution_time', 'keyword', 'standard_type'])
            
            # 生成文件名：失败清单_${关键词}
            if keywords:
                keyword_str = "，".join(keywords)
                filename = f"失败清单_{keyword_str}.xlsx"
            else:
                filename = "失败清单.xlsx"
            
            # 确保文件名唯一性
            filename = self._ensure_unique_filename(filename)
            
            # 写入Excel文件
            df.to_excel(filename, index=False)
            
            self.logger.info(f"💾 失败Excel已生成: {filename}")
            self.logger.info(f"📁 存储位置: {os.path.abspath(filename)}")
            
            return filename
            
        except Exception as e:
            # 【新增失败Excel】捕获异常，确保不中断主流程
            self.logger.error(f"❌ 生成失败Excel时出错: {e}")
            self.logger.info("⚠️ 失败Excel生成失败，但主流程继续执行")
            return None
    
    def _ensure_unique_filename(self, filename):
        """确保文件名唯一性
        
        Args:
            filename: 原始文件名
        
        Returns:
            str: 唯一的文件名
        """
        if not os.path.exists(filename):
            return filename
        
        base, ext = os.path.splitext(filename)
        counter = 1
        while True:
            new_filename = f"{base}_{counter}{ext}"
            if not os.path.exists(new_filename):
                return new_filename
            counter += 1

if __name__ == "__main__":
    crawler = BatchCrawler()
    try:
        crawler.run()
        # 【新增失败Excel】调用生成失败Excel函数
        crawler.generate_failed_excel()
    except KeyboardInterrupt:
        crawler.logger.info(f"\n⚠️ 用户手动终止程序")
    except Exception as e:
        crawler.logger.error(f"❌ 程序启动失败: {e}", exc_info=True)
