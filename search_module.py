# search_module.py - 搜索功能模块
# 完整迁移search_v1.1.py中的业务逻辑及条件分支

import os
import re
import time
from urllib.parse import quote
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from config import DEFAULT_KEYWORDS, OUTPUT_FILE
from utils import init_driver, init_logger, write_excel, clean_text, build_detail_url

# ================= 关键词处理函数 =================
def get_keywords_from_input():
    """从用户输入获取关键词列表
    
    Returns:
        list: 处理后的关键词列表
    """
    print("\n" + "="*60)
    print("🔍 标准搜索关键词输入")
    print("="*60)
    print("提示：")
    print("1. 输入多个关键词时，用以下任意分隔符分隔：")
    print("   - 中文顿号：、")
    print("   - 中文逗号：，")
    print("   - 英文逗号：,")
    print("   - 空格")
    print("   - 分号：;")
    print("2. 示例输入：供后管理、土地征收、人工智能")
    print("3. 直接按Enter键将使用默认关键词：人工智能")
    print("="*60)
    
    user_input = input("\n请输入要搜索的关键词（支持多个）：").strip()
    
    if not user_input:
        print(f"⚠️ 未输入关键词，使用默认关键词: {DEFAULT_KEYWORDS}")
        return DEFAULT_KEYWORDS
    
    # 使用正则表达式分割多种分隔符
    # 原脚本分支保留：支持多种分隔符
    separators = r'[、，,\s;]+'
    keywords = re.split(separators, user_input)
    
    # 清理空格和空字符串
    keywords = [kw.strip() for kw in keywords if kw.strip()]
    
    if not keywords:
        print(f"⚠️ 输入的关键词格式不正确，使用默认关键词: {DEFAULT_KEYWORDS}")
        return DEFAULT_KEYWORDS
    
    # 去重
    unique_keywords = []
    for kw in keywords:
        if kw not in unique_keywords:
            unique_keywords.append(kw)
    
    print(f"✅ 成功提取 {len(unique_keywords)} 个关键词:")
    for i, kw in enumerate(unique_keywords, 1):
        print(f"   {i}. {kw}")
    
    return unique_keywords

# ================= 辅助函数 =================
def get_total_pages(driver):
    """从页面JS中提取总页数
    
    Args:
        driver: 浏览器实例
    
    Returns:
        int: 总页数
    """
    try:
        page_source = driver.page_source
        match = re.search(r'totalPages:\s*(\d+)', page_source)
        if match:
            return int(match.group(1))
    except:
        pass
    return 1

# ================= 搜索类 =================
class Searcher:
    """搜索标准的核心类"""
    
    def __init__(self):
        """初始化搜索器"""
        self.logger = init_logger()
        self.driver = None
        self._init_driver()
    
    def _init_driver(self):
        """初始化浏览器"""
        self.driver = init_driver()
        self.logger.info("✅ 搜索模块浏览器初始化成功")
    
    def _ensure_driver_alive(self):
        """检查浏览器是否存活，若失效则重启"""
        try:
            if self.driver is None:
                self._init_driver()
            else:
                _ = self.driver.current_window_handle
        except Exception:
            self.logger.warning("⚠️ 搜索模块检测到浏览器已关闭，正在重启...")
            try: 
                self.driver.quit()
            except: 
                pass
            self._init_driver()
    
    def run(self, keywords):
        """运行搜索流程
        
        Args:
            keywords: 关键词列表
        
        Returns:
            list: 搜索结果数据
        """
        self._ensure_driver_alive() # 确保点击按钮后浏览器是开着的
        
        search_keywords = keywords
        self.logger.info(f"✅ 使用传入的关键词: {', '.join(search_keywords)}")
        
        wait = WebDriverWait(self.driver, 20)
        all_data = []

        try:
            self.logger.info("🚀 启动国标搜索程序...")
            
            for kw in search_keywords:
                try:
                    self.logger.info(f"🔎 正在搜索关键词: {kw}")
                    
                    # 直接访问搜索结果页（iframe内部地址）
                    search_url = f"https://std.samr.gov.cn/search/stdPage?q={quote(kw)}&tid="
                    self.driver.get(search_url)
                    time.sleep(2)
                    
                    # 获取结果数量
                    try:
                        nums_elem = self.driver.find_element(By.CSS_SELECTOR, "div.nums span")
                        total_count = nums_elem.text.strip()
                        self.logger.info(f"   📊 找到约 {total_count} 条结果")
                        # 原脚本分支保留：搜索结果为空时的跳过处理逻辑
                        if total_count == "0":
                            self.logger.info(f"   ⚠️ 关键词【{kw}】无搜索结果")
                            continue
                    except:
                        pass
                    
                    # 获取总页数
                    total_pages = get_total_pages(self.driver)
                    self.logger.info(f"   📑 共 {total_pages} 页，开始遍历...")
                    
                    keyword_count = 0
                    skipped_type = 0
                    skipped_status = 0
                    
                    # 遍历所有页
                    for page_num in range(1, total_pages + 1):
                        if page_num > 1:
                            page_url = f"{search_url}&pageNo={page_num}"
                            self.driver.get(page_url)
                            time.sleep(1.5)
                        
                        # 解析当前页的所有标准条目
                        panels = self.driver.find_elements(By.CSS_SELECTOR, "div.panel.panel-default.post")
                        
                        for panel in panels:
                            try:
                                # 获取链接元素（包含tid, pid）
                                link = panel.find_element(By.CSS_SELECTOR, "table.s-title a[tid][pid]")
                                tid = link.get_attribute("tid")
                                pid = link.get_attribute("pid")
                                
                                # 原脚本分支保留：文档类型的筛选功能
                                # 筛选类型：只要国标、行标、地标
                                if tid not in ['BV_GB', 'BV_HB', 'BV_DB']:
                                    skipped_type += 1
                                    continue
                                
                                # 提取状态
                                try:
                                    status_elem = panel.find_element(By.CSS_SELECTOR, "span.s-status.label")
                                    status = clean_text(status_elem.text)
                                except:
                                    status = ""
                                
                                # 原脚本分支保留：文档状态的筛选功能
                                # 筛选状态：只要"现行"
                                if status != "现行":
                                    skipped_status += 1
                                    continue
                                
                                # 构造详情页URL
                                detail_url = build_detail_url(tid, pid)
                                if not detail_url:
                                    continue
                                
                                # 提取标准号
                                code_elem = link.find_element(By.CSS_SELECTOR, "span.en-code")
                                code = clean_text(code_elem.text)
                                
                                # 提取中文名称
                                full_text = clean_text(link.text)
                                name = full_text.replace(code, '').strip()
                                name = re.sub(r'^[\s\-—]+', '', name)
                                
                                # 保存数据
                                if detail_url and detail_url.startswith("http"):
                                    all_data.append({
                                        "keyword": kw,
                                        "code": code,
                                        "name": name,
                                        "detail_url": detail_url,
                                        "status": status
                                    })
                                    keyword_count += 1
                                    
                            except Exception as row_e:
                                continue
                        
                        # 每10页打印一次进度
                        if page_num % 10 == 0:
                            self.logger.info(f"   ... 已处理 {page_num}/{total_pages} 页")
                    
                    self.logger.info(f"   ✅ 关键词【{kw}】抓取到 {keyword_count} 条有效数据")
                    self.logger.info(f"   ⏭️ 跳过: 类型不符 {skipped_type} 条, 状态不符 {skipped_status} 条")
                    
                except Exception as e:
                    self.logger.error(f"❌ 关键词【{kw}】搜索异常: {e}")
                    try: 
                        self.driver.refresh()
                        time.sleep(3)
                    except: 
                        pass

        finally:
            self.driver.quit()
            
            # ================= 保存结果 =================
            if all_data:
                import pandas as pd
                df = pd.DataFrame(all_data)
                
                # 原脚本分支保留：基于URL的重复数据去重机制
                # 去重：不同关键词可能搜到同一个标准
                initial_count = len(df)
                df = df.drop_duplicates(subset=['detail_url'])
                final_count = len(df)
                
                # 按关键词排序，方便查看
                df = df.sort_values(by=['keyword', 'code'])
                
                # 生成带关键词的文件名
                keywords_str = "，".join(keywords)
                output_filename = f"待爬取清单_全标准_{keywords_str}.xlsx"
                
                # 确保文件名唯一性
                counter = 1
                while os.path.exists(output_filename):
                    output_filename = f"待爬取清单_全标准_{keywords_str}_{counter}.xlsx"
                    counter += 1
                
                # 写入Excel
                write_excel(df.to_dict('records'), output_filename)
                
                # 生成统计报告
                keyword_stats = df['keyword'].value_counts()
                
                self.logger.info("="*60)
                self.logger.info(f"🎉 任务清单生成完毕！")
                self.logger.info(f"📊 原始抓取: {initial_count} 条")
                self.logger.info(f"📉 去重后: {final_count} 条")
                self.logger.info(f"📂 文件路径: {os.path.abspath(output_filename)}")
                self.logger.info("📈 关键词统计:")
                for kw, count in keyword_stats.items():
                    self.logger.info(f"   • {kw}: {count} 条")
                self.logger.info("👉 请继续运行抓取模块进行数据提取与下载。")
                
                return df.to_dict('records')
            else:
                self.logger.warning("⚠️ 没有搜索到任何数据，请检查网络或网站结构变化。")
                return []

# ================= 主搜索函数 =================
def search_standards(keywords=None):
    """搜索标准并生成Excel清单
    
    Args:
        keywords: 可选的关键词列表，如果为None则从控制台获取
    
    Returns:
        list: 搜索结果数据
    """
    if keywords is None:
        search_keywords = get_keywords_from_input()
        searcher = Searcher()
        return searcher.run(search_keywords)
    else:
        searcher = Searcher()
        return searcher.run(keywords)

if __name__ == "__main__":
    search_standards()
