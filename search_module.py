import os
import re
import time
from urllib.parse import quote

from selenium.webdriver.common.by import By

from config import DEFAULT_KEYWORDS
from utils import build_detail_url, clean_text, init_driver, init_logger, write_excel


def get_keywords_from_input():
    print("\n" + "=" * 60)
    print("Standard search keywords")
    print("=" * 60)
    print("Use comma, Chinese comma, space, or semicolon to separate keywords.")
    print("Example: 测绘, 地理信息, 人工智能")
    print("Press Enter to use the default keyword list.")
    print("=" * 60)

    user_input = input("\n请输入要搜索的关键词（支持多个）: ").strip()
    if not user_input:
        print(f"Using default keywords: {DEFAULT_KEYWORDS}")
        return DEFAULT_KEYWORDS

    keywords = [kw.strip() for kw in re.split(r"[、，,\s;]+", user_input) if kw.strip()]
    if not keywords:
        print(f"Invalid input. Using default keywords: {DEFAULT_KEYWORDS}")
        return DEFAULT_KEYWORDS

    unique_keywords = []
    for keyword in keywords:
        if keyword not in unique_keywords:
            unique_keywords.append(keyword)

    print(f"Loaded {len(unique_keywords)} keyword(s):")
    for index, keyword in enumerate(unique_keywords, 1):
        print(f"  {index}. {keyword}")
    return unique_keywords


def get_total_pages(driver):
    try:
        match = re.search(r"totalPages:\s*(\d+)", driver.page_source)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    return 1


class Searcher:
    def __init__(self, log_file=None, cancel_checker=None):
        self.logger = init_logger(log_file)
        self.driver = None
        self.cancel_checker = cancel_checker
        self._init_driver()

    def _init_driver(self):
        self.driver = init_driver()
        self.logger.info("Search browser initialized")

    def _ensure_driver_alive(self):
        try:
            if self.driver is None:
                self._init_driver()
            else:
                _ = self.driver.current_window_handle
        except Exception:
            self.logger.warning("Search browser disconnected, restarting")
            try:
                self.driver.quit()
            except Exception:
                pass
            self._init_driver()

    def _check_cancelled(self):
        if self.cancel_checker and self.cancel_checker():
            raise RuntimeError("Task cancelled")

    def run(self, keywords, output_filename=None, return_metadata=False):
        self._ensure_driver_alive()
        search_keywords = keywords
        self.logger.info(f"Using keywords: {', '.join(search_keywords)}")
        all_data = []

        try:
            self.logger.info("Starting standard search")
            for keyword in search_keywords:
                self._check_cancelled()
                try:
                    self.logger.info(f"Searching keyword: {keyword}")
                    search_url = f"https://std.samr.gov.cn/search/stdPage?q={quote(keyword)}&tid="
                    self.driver.get(search_url)
                    time.sleep(2)

                    try:
                        nums_elem = self.driver.find_element(By.CSS_SELECTOR, "div.nums span")
                        total_count = nums_elem.text.strip()
                        self.logger.info(f"  Found about {total_count} results")
                        if total_count == "0":
                            self.logger.info(f"  No results for keyword: {keyword}")
                            continue
                    except Exception:
                        pass

                    total_pages = get_total_pages(self.driver)
                    self.logger.info(f"  Total pages: {total_pages}")

                    keyword_count = 0
                    skipped_type = 0
                    skipped_status = 0

                    for page_num in range(1, total_pages + 1):
                        self._check_cancelled()
                        if page_num > 1:
                            page_url = f"{search_url}&pageNo={page_num}"
                            self.driver.get(page_url)
                            time.sleep(1.5)

                        panels = self.driver.find_elements(By.CSS_SELECTOR, "div.panel.panel-default.post")
                        for panel in panels:
                            try:
                                link = panel.find_element(By.CSS_SELECTOR, "table.s-title a[tid][pid]")
                                tid = link.get_attribute("tid")
                                pid = link.get_attribute("pid")

                                if tid not in ["BV_GB", "BV_HB", "BV_DB"]:
                                    skipped_type += 1
                                    continue

                                try:
                                    status_elem = panel.find_element(By.CSS_SELECTOR, "span.s-status.label")
                                    status = clean_text(status_elem.text)
                                except Exception:
                                    status = ""

                                if status != "现行":
                                    skipped_status += 1
                                    continue

                                detail_url = build_detail_url(tid, pid)
                                if not detail_url:
                                    continue

                                code_elem = link.find_element(By.CSS_SELECTOR, "span.en-code")
                                code = clean_text(code_elem.text)
                                full_text = clean_text(link.text)
                                name = full_text.replace(code, "").strip()
                                name = re.sub(r"^[\s\-\u2014]+", "", name)

                                if detail_url.startswith("http"):
                                    all_data.append(
                                        {
                                            "keyword": keyword,
                                            "code": code,
                                            "name": name,
                                            "detail_url": detail_url,
                                            "status": status,
                                        }
                                    )
                                    keyword_count += 1
                            except Exception:
                                continue

                        if page_num % 10 == 0:
                            self.logger.info(f"  Progress: {page_num}/{total_pages} pages")

                    self.logger.info(
                        f"  Keyword complete: {keyword_count} valid, "
                        f"{skipped_type} skipped by type, {skipped_status} skipped by status"
                    )
                except Exception as exc:
                    self.logger.error(f"Keyword search failed for {keyword}: {exc}")
                    try:
                        self.driver.refresh()
                        time.sleep(3)
                    except Exception:
                        pass
        finally:
            if self.driver is not None:
                self.driver.quit()

        if not all_data:
            self.logger.warning("No search results found")
            if return_metadata:
                return {"records": [], "output_file": None}
            return []

        import pandas as pd

        df = pd.DataFrame(all_data)
        initial_count = len(df)
        df = df.drop_duplicates(subset=["detail_url"])
        final_count = len(df)
        df = df.sort_values(by=["keyword", "code"])

        keywords_str = "_".join(keywords)
        resolved_output_filename = output_filename or f"待抓取清单_全标准_{keywords_str}.xlsx"

        counter = 1
        while os.path.exists(resolved_output_filename):
            if output_filename:
                base, ext = os.path.splitext(output_filename)
                resolved_output_filename = f"{base}_{counter}{ext}"
            else:
                resolved_output_filename = f"待抓取清单_全标准_{keywords_str}_{counter}.xlsx"
            counter += 1

        write_excel(df.to_dict("records"), resolved_output_filename)

        keyword_stats = df["keyword"].value_counts()
        self.logger.info("=" * 60)
        self.logger.info("Task list generated")
        self.logger.info(f"Raw hits: {initial_count}")
        self.logger.info(f"Deduplicated hits: {final_count}")
        self.logger.info(f"Output file: {os.path.abspath(resolved_output_filename)}")
        for keyword, count in keyword_stats.items():
            self.logger.info(f"  {keyword}: {count}")

        records = df.to_dict("records")
        if return_metadata:
            return {
                "records": records,
                "output_file": os.path.abspath(resolved_output_filename),
            }
        return records


def search_standards(keywords=None):
    if keywords is None:
        search_keywords = get_keywords_from_input()
        searcher = Searcher()
        return searcher.run(search_keywords)

    searcher = Searcher()
    return searcher.run(keywords)


def search_standards_with_output(keywords, output_filename=None, log_file=None, cancel_checker=None):
    searcher = Searcher(log_file=log_file, cancel_checker=cancel_checker)
    return searcher.run(
        keywords,
        output_filename=output_filename,
        return_metadata=True,
    )


if __name__ == "__main__":
    search_standards()
