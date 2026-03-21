# gui_main.py - 国标爬虫GUI主入口
# 新增tkinter GUI界面，保留原有所有功能不变

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import sys
import os
import re
import pymysql
import threading
from search_module import search_standards
from grab_module import BatchCrawler
from config import DB_CONFIG, load_config, save_config, update_config, get_base_dir

# 引入ttkbootstrap实现现代样式
from ttkbootstrap import Style
from ttkbootstrap.constants import *

# ================= 配置界面类 =================
class ConfigFrame:
    """配置界面 - 用于输入数据库和超级鹰的敏感信息"""

    def __init__(self, root, on_config_complete):
        self.root = root
        self.on_config_complete = on_config_complete
        self.result = None

        # 创建主容器
        self.frame = tk.Frame(root, bg="#F5F5F5")
        self.frame.pack(fill=tk.BOTH, expand=True)

        # 加载当前配置
        self.config_data = load_config()

        # 创建控件
        self.create_widgets()

        # 居中窗口
        self.center_window()

    def center_window(self):
        """窗口居中显示"""
        self.root.update_idletasks()
        width = 500
        height = 700
        x = (self.root.winfo_screenwidth() // 2) - (width // 2)
        y = (self.root.winfo_screenheight() // 2) - (height // 2)
        self.root.geometry(f'{width}x{height}+{x}+{y}')

    def create_widgets(self):
        """创建界面控件"""
        # 标题
        title_frame = tk.Frame(self.frame, bg="#2C3E50", height=60)
        title_frame.pack(fill=tk.X)
        title_frame.pack_propagate(False)

        title_label = tk.Label(
            title_frame,
            text="⚙️ 系统配置",
            font=("微软雅黑", 16, "bold"),
            bg="#2C3E50",
            fg="#FFFFFF"
        )
        title_label.pack(expand=True)

        # 主内容区
        content_frame = tk.Frame(self.frame, bg="#F5F5F5", padx=20, pady=15)
        content_frame.pack(fill=tk.BOTH, expand=True)

        # 数据库配置区域
        db_frame = ttk.LabelFrame(content_frame, text="📦 数据库配置", padding="10")
        db_frame.pack(fill=tk.X, pady=(0, 10))

        # 数据库配置项
        self.db_vars = {}
        db_fields = [
            ("主机地址", "db_host", self.config_data.get("db_host", "localhost")),
            ("端口", "db_port", str(self.config_data.get("db_port", 3306))),
            ("用户名", "db_user", self.config_data.get("db_user", "root")),
            ("密码", "db_password", self.config_data.get("db_password", "root")),
            ("数据库名", "db_database", self.config_data.get("db_database", "disaster_knowledge"))
        ]

        for i, (label_text, var_name, default_value) in enumerate(db_fields):
            tk.Label(
                db_frame,
                text=label_text + "：",
                font=("微软雅黑", 10),
                bg="#F5F5F5",
                fg="#34495E"
            ).grid(row=i, column=0, sticky=tk.W, padx=5, pady=5)

            var = tk.StringVar(value=default_value)
            self.db_vars[var_name] = var

            entry = tk.Entry(
                db_frame,
                textvariable=var,
                font=("微软雅黑", 10),
                width=30,
                show="*" if var_name == "db_password" else "",
                bd=1,
                relief=tk.SOLID,
                highlightbackground="#DDDDDD",
                highlightcolor="#2C3E50",
                highlightthickness=1
            )
            entry.grid(row=i, column=1, sticky=tk.W, padx=5, pady=5)

        # 超级鹰配置区域
        cjy_frame = ttk.LabelFrame(content_frame, text="🦅 超级鹰验证码配置", padding="10")
        cjy_frame.pack(fill=tk.X, pady=(0, 10))

        self.cjy_vars = {}
        cjy_fields = [
            ("用户名", "chaojiying_user", self.config_data.get("chaojiying_user", "")),
            ("密码", "chaojiying_pass", self.config_data.get("chaojiying_pass", "")),
            ("软件ID", "chaojiying_softid", self.config_data.get("chaojiying_softid", ""))
        ]

        for i, (label_text, var_name, default_value) in enumerate(cjy_fields):
            tk.Label(
                cjy_frame,
                text=label_text + "：",
                font=("微软雅黑", 10),
                bg="#F5F5F5",
                fg="#34495E"
            ).grid(row=i, column=0, sticky=tk.W, padx=5, pady=5)

            var = tk.StringVar(value=default_value)
            self.cjy_vars[var_name] = var

            entry = tk.Entry(
                cjy_frame,
                textvariable=var,
                font=("微软雅黑", 10),
                width=30,
                show="*" if var_name == "chaojiying_pass" else "",
                bd=1,
                relief=tk.SOLID,
                highlightbackground="#DDDDDD",
                highlightcolor="#2C3E50",
                highlightthickness=1
            )
            entry.grid(row=i, column=1, sticky=tk.W, padx=5, pady=5)

        # 文件存储路径配置区域
        file_frame = ttk.LabelFrame(content_frame, text="📁 文件存储路径配置", padding="10")
        file_frame.pack(fill=tk.X, pady=(0, 10))

        self.file_vars = {}
        file_fields = [
            ("PDF存储目录", "pdf_dir", self.config_data.get("pdf_dir", "")),
            ("临时目录", "temp_dir", self.config_data.get("temp_dir", "")),
            ("调试输出目录", "debug_dir", self.config_data.get("debug_dir", ""))
        ]

        for i, (label_text, var_name, default_value) in enumerate(file_fields):
            tk.Label(
                file_frame,
                text=label_text + "：",
                font=("微软雅黑", 10),
                bg="#F5F5F5",
                fg="#34495E"
            ).grid(row=i, column=0, sticky=tk.W, padx=5, pady=5)

            var = tk.StringVar(value=default_value)
            self.file_vars[var_name] = var

            entry = tk.Entry(
                file_frame,
                textvariable=var,
                font=("微软雅黑", 10),
                width=30,
                bd=1,
                relief=tk.SOLID,
                highlightbackground="#DDDDDD",
                highlightcolor="#2C3E50",
                highlightthickness=1
            )
            entry.grid(row=i, column=1, sticky=tk.W, padx=5, pady=5)

            # 添加提示文本
            hint_text = ""
            if var_name == "pdf_dir":
                hint_text = "留空则使用默认目录./pdf"
            elif var_name == "temp_dir":
                hint_text = "留空则使用默认目录./temp_step2"
            elif var_name == "debug_dir":
                hint_text = "留空则使用默认目录./debug_output"

            tk.Label(
                file_frame,
                text=hint_text,
                font=("微软雅黑", 8),
                bg="#F5F5F5",
                fg="#7F8C8D"
            ).grid(row=i, column=2, sticky=tk.W, padx=5, pady=5)

        # 记住配置复选框
        self.remember_var = tk.BooleanVar(value=self.config_data.get("remember_config", False))
        remember_frame = tk.Frame(content_frame, bg="#F5F5F5")
        remember_frame.pack(fill=tk.X, pady=(5, 10))

        remember_check = tk.Checkbutton(
            remember_frame,
            text="💾 记住配置（下次启动自动填充，敏感信息会保存到本地文件）",
            variable=self.remember_var,
            font=("微软雅黑", 9),
            bg="#F5F5F5",
            fg="#34495E",
            activebackground="#F5F5F5",
            activeforeground="#34495E",
            selectcolor="#ECF0F1"
        )
        remember_check.pack(anchor=tk.W)

        # 按钮区域
        button_frame = tk.Frame(content_frame, bg="#F5F5F5")
        button_frame.pack(fill=tk.X, pady=10)

        # 确定按钮
        confirm_btn = tk.Button(
            button_frame,
            text="确定",
            command=self.save_and_continue,
            bg="#27AE60",  # 成功按钮背景色
            fg="#FFFFFF",  # 文字颜色
            font=("微软雅黑", 10),
            width=10,
            bd=2,  # 边框宽度
            relief=tk.SOLID,  # 边框样式
            highlightbackground="#4A90E2",  # 边框颜色
            cursor="hand2",  # 鼠标悬停时的光标
            pady=20  # 垂直内边距，增加按钮高度
        )
        confirm_btn.pack()
        # 绑定鼠标事件
        confirm_btn.bind("<Enter>", self.on_enter)
        confirm_btn.bind("<Leave>", self.on_leave)

    def on_enter(self, event):
        """鼠标进入按钮时的处理"""
        widget = event.widget
        # 为每个按钮单独保存原始背景色
        widget.original_bg = widget.cget("bg")
        # 应用简洁的悬浮效果
        widget.configure(bg="#2E4B84")

    def on_leave(self, event):
        """鼠标离开按钮时的处理"""
        widget = event.widget
        # 恢复按钮的原始背景色
        if hasattr(widget, "original_bg"):
            widget.configure(bg=widget.original_bg)

    def save_and_continue(self):
        """保存配置并进入主界面"""
        new_config = {
            "db_host": self.db_vars["db_host"].get(),
            "db_port": self.db_vars["db_port"].get(),
            "db_user": self.db_vars["db_user"].get(),
            "db_password": self.db_vars["db_password"].get(),
            "db_database": self.db_vars["db_database"].get(),
            "chaojiying_user": self.cjy_vars["chaojiying_user"].get(),
            "chaojiying_pass": self.cjy_vars["chaojiying_pass"].get(),
            "chaojiying_softid": self.cjy_vars["chaojiying_softid"].get(),
            # 文件存储路径配置
            "pdf_dir": self.file_vars["pdf_dir"].get(),
            "temp_dir": self.file_vars["temp_dir"].get(),
            "debug_dir": self.file_vars["debug_dir"].get(),
            "remember_config": self.remember_var.get()
        }

        # 验证必填项
        required_fields = {
            "数据库主机地址": new_config["db_host"],
            "数据库端口": new_config["db_port"],
            "数据库用户名": new_config["db_user"],
            "数据库密码": new_config["db_password"],
            "数据库名称": new_config["db_database"],
            "超级鹰用户名": new_config["chaojiying_user"],
            "超级鹰密码": new_config["chaojiying_pass"],
            "超级鹰软件ID": new_config["chaojiying_softid"]
        }

        empty_fields = [name for name, value in required_fields.items() if not value or not str(value).strip()]

        if empty_fields:
            messagebox.showwarning("输入不完整", f"请填写以下必填项：\n\n" + "\n".join(f"• {field}" for field in empty_fields))
            return

        if self.remember_var.get():
            save_config(new_config)

        self.result = new_config
        self.frame.destroy()
        self.on_config_complete(new_config)

# ================= 日志重定向类 =================
class StdoutRedirector:
    def __init__(self, text_widget):
        self.text_widget = text_widget
        # 配置标签颜色
        self._config_tags()
    
    def _config_tags(self):
        """配置日志文本标签颜色"""
        self.text_widget.tag_config("success", foreground="#27AE60")  # 绿色
        self.text_widget.tag_config("error", foreground="#E74C3C")    # 红色
        self.text_widget.tag_config("warning", foreground="#F39C12")  # 橙色
        self.text_widget.tag_config("info", foreground="#34495E")      # 深灰
    
    def write(self, string):
        """写入日志文本，根据前缀区分颜色"""
        self.text_widget.config(state=tk.NORMAL)
        
        # 按前缀判断颜色
        if string.startswith("✅"):
            self.text_widget.insert(tk.END, string, "success")
        elif string.startswith("❌"):
            self.text_widget.insert(tk.END, string, "error")
        elif string.startswith("⚠️"):
            self.text_widget.insert(tk.END, string, "warning")
        else:
            self.text_widget.insert(tk.END, string, "info")
        
        self.text_widget.config(state=tk.DISABLED)
        self.text_widget.see(tk.END)
    
    def flush(self):
        pass

# ================= GUI主类 =================
class StandardCrawlerGUI:
    def __init__(self, root):
        # 初始化ttkbootstrap样式
        self.style = Style(theme="flatly")
        
        # 自定义样式
        self._customize_styles()
        
        self.root = root
        self.root.title("国标爬虫系统")
        self.root.geometry("1300x1050")
        self.root.resizable(True, True)
        
        # 设置窗口图标
        icon_path = os.path.join(get_base_dir(), "icon.ico")
        if os.path.exists(icon_path):
            self.root.iconbitmap(icon_path)
        
        # 设置窗口背景色
        self.root.configure(bg="#F5F5F5")
        
        # 初始化变量
        self.table_names = []
        self.selected_table = tk.StringVar()
        self.db_connected = False
        # 跟踪当前运行的线程和crawler实例
        self.current_threads = []
        self.current_crawler = None
        
        # 设置字体
        self.font = ("微软雅黑", 10)
        self.title_font = ("微软雅黑", 11, "bold")
        self.log_font = ("Consolas", 9)
        
        # 创建主框架
        self.main_frame = ttk.Frame(root, padding="10")
        self.main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 创建控件
        self.create_widgets()
        
        # 读取数据库表名
        self.load_database_tables()
    
    def _customize_styles(self):
        """自定义控件样式"""
        # 主色调：深蓝色 #2C3E50
        # 辅助色：绿色 #27AE60，红色 #E74C3C，浅灰 #ECF0F1
        # 文字色：深灰 #34495E，浅灰 #7F8C8D，白色 #FFFFFF
        
        # 自定义按钮样式
        self.style.configure(
            "Primary.TButton",
            font=("微软雅黑", 10),
            padding=(10, 5),
            height=35,
            borderwidth=2,
            relief="solid",
            bordercolor="#4A90E2"
        )
        
        self.style.configure(
            "Success.TButton",
            font=("微软雅黑", 10),
            padding=(10, 5),
            height=35,
            borderwidth=2,
            relief="solid",
            bordercolor="#4A90E2"
        )
        
        self.style.configure(
            "Danger.TButton",
            font=("微软雅黑", 10),
            padding=(10, 5),
            height=35,
            borderwidth=2,
            relief="solid",
            bordercolor="#4A90E2"
        )
        
        # 为Outline.TButton添加边框
        self.style.configure(
            "Outline.TButton",
            font=("微软雅黑", 10),
            padding=(10, 5),
            height=35,
            borderwidth=2,
            relief="solid",
            bordercolor="#4A90E2"
        )
        
        # 自定义标签样式
        self.style.configure(
            "Title.TLabel",
            font=("微软雅黑", 11, "bold"),
            foreground="#2C3E50"
        )
        
        # 自定义输入框样式
        self.style.configure(
            "TEntry",
            font=("微软雅黑", 10),
            padding=5
        )
        
        # 自定义下拉框样式
        self.style.configure(
            "TCombobox",
            font=("微软雅黑", 10),
            padding=5
        )
        
        # 自定义标签框样式
        self.style.configure(
            "TLabelframe.Label",
            font=("微软雅黑", 11, "bold"),
            foreground="#2C3E50"
        )
    
    def create_widgets(self):
        """创建所有GUI控件"""
        # 1. 关键词输入区域
        keyword_frame = ttk.LabelFrame(self.main_frame, text="关键词输入", padding="10")
        keyword_frame.grid(row=0, column=0, columnspan=2, padx=5, pady=5, sticky=tk.NSEW)
        
        # 关键词文本框
        self.keyword_text = tk.Text(
            keyword_frame, 
            height=4, 
            width=80, 
            font=self.font,
            bg="#FFFFFF",
            bd=1,
            relief=tk.SOLID,
            highlightbackground="#DDDDDD",
            highlightcolor="#2C3E50",
            highlightthickness=1,
            wrap=tk.WORD
        )
        self.keyword_text.grid(row=0, column=0, padx=5, pady=5, sticky=tk.NSEW)
        
        # 添加垂直滚动条
        keyword_scrollbar = ttk.Scrollbar(
            keyword_frame, 
            orient=tk.VERTICAL, 
            command=self.keyword_text.yview
        )
        keyword_scrollbar.grid(row=0, column=1, sticky=tk.NS)
        self.keyword_text['yscrollcommand'] = keyword_scrollbar.set
        
        # 添加默认提示文本
        self.keyword_text.insert(tk.END, "请输入搜索关键词（多个用顿号/逗号/空格分隔），示例：人工智能、大数据")
        self.keyword_text.config(fg="#999999")
        
        # 添加格式提示
        ttk.Label(
            keyword_frame, 
            text="💡 多个关键词用顿号/逗号/空格分隔", 
            font=("微软雅黑", 9),
            foreground="#7F8C8D"
        ).grid(row=1, column=0, padx=5, pady=2, sticky=tk.W)
        
        # 绑定事件
        self.keyword_text.bind("<FocusIn>", self.clear_placeholder)
        self.keyword_text.bind("<FocusOut>", self.show_placeholder)
        
        # 2. 数据库表名选择区域
        db_frame = ttk.LabelFrame(self.main_frame, text="数据库配置", padding="10")
        db_frame.grid(row=1, column=0, columnspan=2, padx=5, pady=5, sticky=tk.NSEW)
        
        # 表名标签
        ttk.Label(
            db_frame, 
            text="目标表名：", 
            font=self.title_font,
            style="Title.TLabel"
        ).grid(row=0, column=0, padx=5, pady=5, sticky=tk.E)
        
        # 表名下拉框
        self.table_combobox = ttk.Combobox(
            db_frame, 
            textvariable=self.selected_table, 
            width=40, 
            font=self.font
        )
        self.table_combobox.grid(row=0, column=1, padx=5, pady=5, sticky=tk.W)
        self.table_combobox['values'] = []
        
        # 数据库连接状态
        self.db_status_var = tk.StringVar(value="❌ 未连接")
        self.db_status_label = ttk.Label(
            db_frame, 
            textvariable=self.db_status_var,
            font=self.font,
            foreground="#E74C3C"
        )
        self.db_status_label.grid(row=0, column=2, padx=5, pady=5, sticky=tk.W)
        
        # 3. 功能按钮区域
        button_frame = ttk.Frame(self.main_frame, padding="10")
        button_frame.grid(row=2, column=0, columnspan=2, padx=5, pady=5, sticky=tk.NSEW)
        
        # 按钮容器，用于水平居中
        button_container = ttk.Frame(button_frame)
        button_container.pack(expand=True)
        
        # 完整流程按钮
        self.full_process_btn = tk.Button(
            button_container, 
            text="完整流程（搜索→爬取→入库）", 
            command=self.run_full_process,
            bg="#27AE60",  # 成功按钮背景色
            fg="#FFFFFF",  # 文字颜色
            font=("微软雅黑", 10),
            width=25,
            height=2,
            bd=2,  # 边框宽度
            relief=tk.SOLID,  # 边框样式
            highlightbackground="#4A90E2",  # 边框颜色
            cursor="hand2"  # 鼠标悬停时的光标
        )
        self.full_process_btn.grid(row=0, column=0, padx=15, pady=10)
        # 绑定鼠标事件
        self.full_process_btn.bind("<Enter>", self.on_enter)
        self.full_process_btn.bind("<Leave>", self.on_leave)
        
        # 仅生成待爬取Excel按钮
        self.only_excel_btn = tk.Button(
            button_container, 
            text="仅生成待爬取Excel", 
            command=self.run_only_excel,
            bg="#FFFFFF",  # 白色背景
            fg="#34495E",  # 文字颜色
            font=("微软雅黑", 10),
            width=20,
            height=2,
            bd=2,  # 边框宽度
            relief=tk.SOLID,  # 边框样式
            highlightbackground="#4A90E2",  # 边框颜色
            cursor="hand2"  # 鼠标悬停时的光标
        )
        self.only_excel_btn.grid(row=0, column=1, padx=15, pady=10)
        # 绑定鼠标事件
        self.only_excel_btn.bind("<Enter>", self.on_enter)
        self.only_excel_btn.bind("<Leave>", self.on_leave)
        
        # 仅爬取按钮
        self.only_grab_btn = tk.Button(
            button_container, 
            text="仅爬取（用已有Excel）", 
            command=self.run_only_grab,
            bg="#FFFFFF",  # 白色背景
            fg="#34495E",  # 文字颜色
            font=("微软雅黑", 10),
            width=25,
            height=2,
            bd=2,  # 边框宽度
            relief=tk.SOLID,  # 边框样式
            highlightbackground="#4A90E2",  # 边框颜色
            cursor="hand2"  # 鼠标悬停时的光标
        )
        self.only_grab_btn.grid(row=1, column=0, padx=15, pady=10)
        # 绑定鼠标事件
        self.only_grab_btn.bind("<Enter>", self.on_enter)
        self.only_grab_btn.bind("<Leave>", self.on_leave)
        
        # 退出按钮
        self.exit_btn = tk.Button(
            button_container, 
            text="退出", 
            command=self.exit_app,
            bg="#E74C3C",  # 红色背景
            fg="#FFFFFF",  # 文字颜色
            font=("微软雅黑", 10),
            width=20,
            height=2,
            bd=2,  # 边框宽度
            relief=tk.SOLID,  # 边框样式
            highlightbackground="#4A90E2",  # 边框颜色
            cursor="hand2"  # 鼠标悬停时的光标
        )
        self.exit_btn.grid(row=1, column=1, padx=15, pady=10)
        # 绑定鼠标事件
        self.exit_btn.bind("<Enter>", self.on_enter)
        self.exit_btn.bind("<Leave>", self.on_leave)
        
        # 4. 日志输出区域
        log_frame = ttk.LabelFrame(self.main_frame, text="运行日志", padding="10")
        log_frame.grid(row=3, column=0, columnspan=2, padx=5, pady=5, sticky=tk.NSEW)
        
        # 日志框顶部
        log_top_frame = ttk.Frame(log_frame)
        log_top_frame.grid(row=0, column=0, columnspan=2, padx=5, pady=2, sticky=tk.EW)
        
        # 清空日志按钮
        self.clear_log_btn = tk.Button(
            log_top_frame, 
            text="清空日志", 
            command=self.clear_log,
            bg="#FFFFFF",  # 白色背景
            fg="#34495E",  # 文字颜色
            font=("微软雅黑", 10),
            width=10,
            height=1,
            bd=2,  # 边框宽度
            relief=tk.SOLID,  # 边框样式
            highlightbackground="#4A90E2",  # 边框颜色
            cursor="hand2"  # 鼠标悬停时的光标
        )
        self.clear_log_btn.pack(side=tk.RIGHT, padx=5)
        # 绑定鼠标事件
        self.clear_log_btn.bind("<Enter>", self.on_enter)
        self.clear_log_btn.bind("<Leave>", self.on_leave)
        
        # 日志文本框
        self.log_text = tk.Text(
            log_frame, 
            height=15, 
            width=80, 
            font=self.log_font,
            state=tk.DISABLED,
            bg="#FFFFFF",
            bd=1,
            relief=tk.SOLID,
            highlightbackground="#DDDDDD",
            highlightcolor="#2C3E50",
            highlightthickness=1
        )
        self.log_text.grid(row=1, column=0, padx=5, pady=5, sticky=tk.NSEW)
        
        # 添加滚动条
        log_scrollbar = ttk.Scrollbar(
            log_frame, 
            orient=tk.VERTICAL, 
            command=self.log_text.yview
        )
        log_scrollbar.grid(row=1, column=1, sticky=tk.NS)
        self.log_text['yscrollcommand'] = log_scrollbar.set
        
        # 配置网格权重
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.rowconfigure(3, weight=1)
        keyword_frame.columnconfigure(0, weight=1)
        db_frame.columnconfigure(1, weight=1)
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(1, weight=1)
        
        # 重定向标准输出到日志文本框
        sys.stdout = StdoutRedirector(self.log_text)
        

    
    def load_database_tables(self):
        """加载数据库表名到下拉框"""
        try:
            # 连接数据库
            conn = pymysql.connect(**DB_CONFIG, charset='utf8mb4')
            cursor = conn.cursor()
            
            # 执行SHOW TABLES
            cursor.execute("SHOW TABLES")
            tables = cursor.fetchall()
            
            # 提取表名
            self.table_names = [table[0] for table in tables]
            
            # 填充到下拉框
            if self.table_names:
                self.table_combobox['values'] = self.table_names
                self.selected_table.set(self.table_names[0])
                print(f"✅ 数据库连接成功，读取到 {len(self.table_names)} 个表")
            else:
                print("⚠️ 数据库连接成功，但未找到表")
            
            # 关闭连接
            cursor.close()
            conn.close()
            
            # 更新数据库连接状态
            self.update_db_status(True)
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ 数据库连接失败：{error_msg}")
            messagebox.showerror("数据库连接失败", f"数据库连接失败：{error_msg}")
            # 下拉框置空，但仍可手动输入
            self.table_combobox['values'] = []
            # 更新数据库连接状态
            self.update_db_status(False, error_msg[:50])
    
    def clear_placeholder(self, event):
        """清除关键词输入框的默认提示文本"""
        content = self.keyword_text.get(1.0, tk.END).strip()
        if content == "请输入搜索关键词（多个用顿号/逗号/空格分隔），示例：人工智能、大数据":
            self.keyword_text.delete(1.0, tk.END)
            self.keyword_text.config(fg="#34495E")
    
    def show_placeholder(self, event):
        """显示关键词输入框的默认提示文本"""
        content = self.keyword_text.get(1.0, tk.END).strip()
        if not content:
            self.keyword_text.insert(tk.END, "请输入搜索关键词（多个用顿号/逗号/空格分隔），示例：人工智能、大数据")
            self.keyword_text.config(fg="#999999")
    
    def on_enter(self, event):
        """鼠标进入按钮时的处理"""
        widget = event.widget
        # 为每个按钮单独保存原始背景色
        widget.original_bg = widget.cget("bg")
        # 应用简洁的悬浮效果，与ttk.Combobox交互样式保持一致
        widget.configure(bg="#2E4B84")
    
    def on_leave(self, event):
        """鼠标离开按钮时的处理"""
        widget = event.widget
        # 恢复按钮的原始背景色
        if hasattr(widget, "original_bg"):
            widget.configure(bg=widget.original_bg)
    
    def clear_log(self):
        """清空日志文本框"""
        self.log_text.config(state=tk.NORMAL)
        self.log_text.delete(1.0, tk.END)
        self.log_text.config(state=tk.DISABLED)
        print("✅ 日志已清空")
    
    def update_db_status(self, connected, error_msg=""):
        """更新数据库连接状态"""
        self.db_connected = connected
        if connected:
            self.db_status_var.set("✅ 已连接")
            self.db_status_label.configure(foreground="#27AE60")
        else:
            self.db_status_var.set(f"❌ 未连接: {error_msg}")
            self.db_status_label.configure(foreground="#E74C3C")
    
    def get_keywords(self):
        """获取并处理关键词输入"""
        # 获取文本框内容
        content = self.keyword_text.get(1.0, tk.END).strip()
        
        # 移除默认提示文本
        if content == "请输入搜索关键词（多个用顿号/逗号/空格分隔），示例：人工智能、大数据":
            content = ""
        
        # 校验输入
        if not content:
            messagebox.showwarning("输入错误", "请输入关键词")
            return None
        
        # 处理多关键词（兼容原脚本的多分隔符）
        separators = r'[、，,\s;]+'
        keywords = re.split(separators, content)
        
        # 清理空格和空字符串
        keywords = [kw.strip() for kw in keywords if kw.strip()]
        
        # 去重
        unique_keywords = []
        for kw in keywords:
            if kw not in unique_keywords:
                unique_keywords.append(kw)
        
        print(f"✅ 提取到 {len(unique_keywords)} 个关键词: {', '.join(unique_keywords)}")
        return unique_keywords
    
    def get_table_name(self):
        """获取选中的表名"""
        table_name = self.table_combobox.get().strip()
        if not table_name:
            messagebox.showwarning("输入错误", "请选择或输入表名")
            return None
        return table_name
    
    def run_full_process(self):
        """完整流程：搜索→爬取→入库"""
        # 获取关键词
        keywords = self.get_keywords()
        if not keywords:
            return
        
        # 获取表名
        table_name = self.get_table_name()
        if not table_name:
            return
        
        # 设置按钮为加载状态
        original_text = self.full_process_btn.cget("text")
        self.full_process_btn.config(text="处理中...", state=tk.DISABLED)
        
        # 创建并启动子线程
        task_thread = threading.Thread(
            target=self._execute_full_process,
            args=(keywords, table_name, original_text)
        )
        task_thread.daemon = False  # 设置为非守护线程，确保能够执行完成
        # 添加到线程列表
        self.current_threads.append(task_thread)
        task_thread.start()
    
    def _execute_full_process(self, keywords, table_name, original_text):
        """在子线程中运行的完整流程逻辑"""
        try:
            print("=" * 80)
            print("🚀 开始完整流程模式")
            print("=" * 80)
            
            # 1. 执行搜索功能
            print("\n📋 步骤1：执行标准搜索")
            search_standards(keywords)
            
            # 2. 执行抓取功能
            print("\n📋 步骤2：执行标准抓取")
            crawler = BatchCrawler()
            # 保存crawler实例引用
            self.current_crawler = crawler
            # 修改save_db方法，支持表名参数
            original_save_db = crawler.save_db
            
            def custom_save_db(m, path):
                original_save_db(m, path, table_name)
            
            crawler.save_db = custom_save_db
            crawler.run()
            
            # 3. 生成失败Excel
            print("\n📋 步骤3：生成失败Excel")
            crawler.generate_failed_excel(keywords=keywords)
            
            print("\n🎉 完整流程执行完成！")
            # 在主线程中显示浮动提示
            self.root.after(0, lambda: self.show_toast("执行完成", "完整流程执行完成！", "success"))
            
        except Exception as e:
            error_msg = f"执行过程中出错：{str(e)}"
            print(f"❌ {error_msg}")
            # 在主线程中显示错误提示
            self.root.after(0, lambda: self.show_toast("执行错误", error_msg, "error"))
        finally:
            # 在主线程中恢复按钮状态
            self.root.after(0, lambda: self.full_process_btn.config(text=original_text, state=tk.NORMAL))
    
    def run_only_excel(self):
        """仅生成待爬取Excel"""
        # 获取关键词
        keywords = self.get_keywords()
        if not keywords:
            return
        
        # 设置按钮为加载状态
        original_text = self.only_excel_btn.cget("text")
        self.only_excel_btn.config(text="处理中...", state=tk.DISABLED)
        
        # 创建并启动子线程
        task_thread = threading.Thread(
            target=self._execute_only_excel,
            args=(keywords, original_text)
        )
        task_thread.daemon = False  # 设置为非守护线程，确保能够执行完成
        # 添加到线程列表
        self.current_threads.append(task_thread)
        task_thread.start()
    
    def _execute_only_excel(self, keywords, original_text):
        """在子线程中运行的仅生成Excel逻辑"""
        try:
            print("=" * 80)
            print("🚀 开始仅生成待爬取Excel模式")
            print("=" * 80)
            
            # 执行搜索功能
            search_standards(keywords)
            
            print("\n🎉 待爬取Excel生成完成！")
            # 在主线程中显示浮动提示
            self.root.after(0, lambda: self.show_toast("执行完成", "待爬取Excel生成完成！", "success"))
            
        except Exception as e:
            error_msg = f"执行过程中出错：{str(e)}"
            print(f"❌ {error_msg}")
            # 在主线程中显示错误提示
            self.root.after(0, lambda: self.show_toast("执行错误", error_msg, "error"))
        finally:
            # 在主线程中恢复按钮状态
            self.root.after(0, lambda: self.only_excel_btn.config(text=original_text, state=tk.NORMAL))
    
    def run_only_grab(self):
        """仅爬取（用已有Excel）"""
        # 获取表名
        table_name = self.get_table_name()
        if not table_name:
            return
        
        # 弹出文件选择框（在主线程中执行，因为需要用户交互）
        file_path = filedialog.askopenfilename(
            title="选择待爬取Excel文件",
            filetypes=[("Excel文件", "*.xlsx"), ("所有文件", "*.*")]
        )
        
        if not file_path:
            return
        
        # 设置按钮为加载状态
        original_text = self.only_grab_btn.cget("text")
        self.only_grab_btn.config(text="处理中...", state=tk.DISABLED)
        
        # 创建并启动子线程
        task_thread = threading.Thread(
            target=self._execute_only_grab,
            args=(table_name, file_path, original_text)
        )
        task_thread.daemon = False  # 设置为非守护线程，确保能够执行完成
        # 添加到线程列表
        self.current_threads.append(task_thread)
        task_thread.start()
    
    def _execute_only_grab(self, table_name, file_path, original_text):
        """在子线程中运行的仅爬取逻辑"""
        try:
            print("=" * 80)
            print("🚀 开始仅爬取模式")
            print(f"📁 指定Excel文件：{file_path}")
            print("=" * 80)
            
            # 执行抓取功能
            crawler = BatchCrawler()
            # 保存crawler实例引用
            self.current_crawler = crawler
            # 修改save_db方法，支持表名参数
            original_save_db = crawler.save_db
            
            def custom_save_db(m, path):
                original_save_db(m, path, table_name)
            
            crawler.save_db = custom_save_db
            crawler.run(file_path)
            
            # 生成失败Excel
            print("\n📋 步骤2：生成失败Excel")
            # 尝试从Excel文件中提取关键词
            keywords = []
            try:
                import pandas as pd
                df = pd.read_excel(file_path)
                if 'keyword' in df.columns:
                    keywords = list(df['keyword'].unique())
                    keywords = [kw for kw in keywords if pd.notna(kw) and str(kw).strip()]
            except Exception as e:
                print(f"⚠️ 无法从Excel文件中提取关键词: {e}")
            
            crawler.generate_failed_excel(keywords=keywords)
            
            print("\n🎉 仅爬取模式执行完成！")
            # 在主线程中显示浮动提示
            self.root.after(0, lambda: self.show_toast("执行完成", "仅爬取模式执行完成！", "success"))
            
        except Exception as e:
            error_msg = f"执行过程中出错：{str(e)}"
            print(f"❌ {error_msg}")
            # 在主线程中显示错误提示
            self.root.after(0, lambda: self.show_toast("执行错误", error_msg, "error"))
        finally:
            # 在主线程中恢复按钮状态
            self.root.after(0, lambda: self.only_grab_btn.config(text=original_text, state=tk.NORMAL))
    
    def exit_app(self):
        """退出应用"""
        if messagebox.askokcancel("退出", "确定要退出吗？"):
            # 1. 立即安全终止当前正在进行的所有爬取任务，确保资源得到正确释放
            print("📋 正在清理资源...")
            
            # 2. 调用已有的输出失败列表函数，完整输出所有爬取失败的标准信息
            if self.current_crawler:
                print("📋 正在生成失败列表...")
                try:
                    # 尝试生成失败Excel
                    result = self.current_crawler.generate_failed_excel()
                    if result:
                        print(f"✅ 失败列表生成完成: {result}")
                    else:
                        print("✅ 失败列表生成完成")
                except Exception as e:
                    print(f"⚠️ 生成失败列表时出错: {e}")
                    # 即使出错，也要尝试保存已有的失败信息
                    try:
                        if hasattr(self.current_crawler, 'failed_items') and self.current_crawler.failed_items:
                            print(f"⚠️ 尝试保存已收集的{len(self.current_crawler.failed_items)}条失败信息...")
                            # 简化版的失败列表生成
                            import pandas as pd
                            df = pd.DataFrame(self.current_crawler.failed_items)
                            filename = "失败列表_紧急保存.xlsx"
                            df.to_excel(filename, index=False)
                            print(f"✅ 已紧急保存失败列表: {filename}")
                    except Exception as e2:
                        print(f"⚠️ 紧急保存失败: {e2}")
            
            # 3. 清理线程列表
            self.current_threads.clear()
            self.current_crawler = None
            
            # 4. 退出应用
            self.root.destroy()
            import os
            os._exit(0)
    
    def show_toast(self, title, message, type="info"):
        """显示浮动通知消息
        
        Args:
            title: 通知标题
            message: 通知内容
            type: 通知类型 (info/success/error/warning)
        """
        # 创建顶级窗口作为通知
        toast = tk.Toplevel(self.root)
        toast.overrideredirect(True)  # 无边框
        toast.attributes('-topmost', True)  # 置顶显示
        
        # 设置通知样式
        if type == "success":
            bg_color = "#27AE60"
            fg_color = "#FFFFFF"
            icon = "✅"
        elif type == "error":
            bg_color = "#E74C3C"
            fg_color = "#FFFFFF"
            icon = "❌"
        elif type == "warning":
            bg_color = "#F39C12"
            fg_color = "#FFFFFF"
            icon = "⚠️"
        else:
            bg_color = "#3498DB"
            fg_color = "#FFFFFF"
            icon = "ℹ️"
        
        # 设置通知大小和位置
        width, height = 300, 80
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        x = screen_width - width - 20
        y = screen_height - height - 20
        toast.geometry(f"{width}x{height}+{x}+{y}")
        
        # 创建通知内容
        toast.configure(bg=bg_color)
        
        # 标题和消息
        title_label = tk.Label(
            toast, 
            text=f"{icon} {title}", 
            font=("微软雅黑", 10, "bold"), 
            bg=bg_color, 
            fg=fg_color
        )
        title_label.pack(pady=(10, 5), padx=10, anchor="w")
        
        message_label = tk.Label(
            toast, 
            text=message, 
            font=("微软雅黑", 9), 
            bg=bg_color, 
            fg=fg_color, 
            wraplength=width-20
        )
        message_label.pack(pady=(0, 10), padx=10, anchor="w")
        
        # 添加轻微阴影效果
        toast.attributes('-alpha', 0.95)
        
        # 3秒后自动消失
        toast.after(3000, toast.destroy)

# ================= 主执行流程 =================
if __name__ == "__main__":
    print("程序启动...")

    # 创建根窗口
    root = tk.Tk()
    root.title("系统配置")
    root.resizable(False, False)

    # 设置窗口图标
    icon_path = os.path.join(get_base_dir(), "icon.ico")
    if os.path.exists(icon_path):
        root.iconbitmap(icon_path)

    # 设置窗口背景色
    root.configure(bg="#F5F5F5")

    # 存储配置和主GUI实例
    config_storage = {'config': None}
    app_storage = {'app': None}

    # 配置完成后的回调函数
    def on_config_complete(config):
        config_storage['config'] = config

        # 更新config模块中的值
        if config:
            update_config(config)

        # 重置窗口设置
        root.title("国标爬虫系统")
        root.geometry("1300x1050")
        root.resizable(True, True)

        # 创建主GUI界面
        print("正在创建主GUI界面...")
        app_storage['app'] = StandardCrawlerGUI(root)
        print("主GUI界面已创建")

    # 先显示配置界面
    print("正在弹出配置界面...")
    config_frame = ConfigFrame(root, on_config_complete)

    # 进入主循环
    print("进入主循环")
    root.mainloop()
