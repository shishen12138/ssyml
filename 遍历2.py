import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
import boto3
from botocore.config import Config
from concurrent.futures import ThreadPoolExecutor
import threading
import paramiko
import time

# -------------------- 配置 --------------------
SSH_USER = "root"
SSH_PASS = "Qcy1994@06"
PROXY = "http://yhvbjsyeu54467-zone-abc-region-US:hhdjshs7@na.1fa7a9d3999e70e8.abcproxy.vip:4950"

AWS_REGIONS_CN = {
    "us-east-1": "美国东部（弗吉尼亚）", "us-east-2": "美国东部（俄亥俄）",
    "us-west-1": "美国西部（北加利福尼亚）", "us-west-2": "美国西部（俄勒冈）",
    "ap-south-1": "亚太地区（孟买）", "ap-northeast-1": "亚太地区（东京）",
    "ap-northeast-2": "亚太地区（首尔）", "ap-southeast-1": "亚太地区（新加坡）",
    "ap-southeast-2": "亚太地区（悉尼）", "ca-central-1": "加拿大中部（蒙特利尔）",
    "eu-central-1": "欧洲（法兰克福）", "eu-west-1": "欧洲（爱尔兰）",
    "eu-west-2": "欧洲（伦敦）", "eu-west-3": "欧洲（巴黎）",
    "sa-east-1": "南美洲（圣保罗）"
}

EC2_STATE_CN = {
    "running": "运行中", "stopped": "已停止", "pending": "开机中", "stopping": "关机中"
}

EC2_IGNORE_STATES = ["terminated"]

US_REGIONS = ["us-east-1","us-east-2","us-west-1","us-west-2"]

# -------------------- 主程序 --------------------
class AWSCheckerGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("AWS EC2 批量管理工具")
        self.root.geometry("1400x1000")

        # 扫描区域选项
        self.scan_option = tk.StringVar()
        self.scan_option.set("us_only")
        option_frame = tk.Frame(root)
        option_frame.pack(fill=tk.X, padx=5, pady=2)
        tk.Label(option_frame, text="扫描区域:").pack(side=tk.LEFT)
        tk.Radiobutton(option_frame, text="美国四区", variable=self.scan_option, value="us_only").pack(side=tk.LEFT)
        tk.Radiobutton(option_frame, text="全区", variable=self.scan_option, value="all").pack(side=tk.LEFT)

        # 输入框
        tk.Label(root, text="请输入 AWS 账号（格式：email----access_key----secret_key）").pack()
        self.input_box = scrolledtext.ScrolledText(root, height=10)
        self.input_box.pack(fill=tk.X, padx=5, pady=5)

        # SSH 命令输入框
        tk.Label(root, text="SSH 命令（默认可修改）：").pack()
        self.ssh_command_box = tk.Entry(root)
        self.ssh_command_box.pack(fill=tk.X, padx=5, pady=5)
        self.ssh_command_box.insert(0, "wget https://raw.githubusercontent.com/shishen12138/ssyml/main/install.sh -O - | bash")

        # 按钮
        button_frame = tk.Frame(root)
        button_frame.pack(fill=tk.X, pady=5)
        self.start_button = tk.Button(button_frame, text="开始检查", command=self.start_check)
        self.start_button.pack(side=tk.LEFT, padx=5)
        self.select_all_button = tk.Button(button_frame, text="全选/反选", command=self.toggle_select_all)
        self.select_all_button.pack(side=tk.LEFT, padx=5)
        self.batch_ssh_button = tk.Button(button_frame, text="异步下发 SSH 命令", command=self.batch_ssh_command)
        self.batch_ssh_button.pack(side=tk.LEFT, padx=5)
        self.batch_ssh_sync_button = tk.Button(button_frame, text="同步下发 SSH 命令", command=self.batch_ssh_command_sync)
        self.batch_ssh_sync_button.pack(side=tk.LEFT, padx=5)

        # 状态栏
        self.stats_var = tk.StringVar()
        self.stats_var.set("账号数:0 | 实例数:0 | 运行中:0 | 已停止:0 | 开机中:0 | 关机中:0 | CPU<50:0 | 平均CPU:0%")
        self.stats_label = tk.Label(root, textvariable=self.stats_var, relief=tk.SUNKEN, anchor="w", bg="#f0f0f0")
        self.stats_label.pack(fill=tk.X, pady=2)

        # Treeview
        self.tree_frame = tk.Frame(root)
        self.tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        columns = ["账号", "区域", "实例ID", "实例IP", "状态", "Top1进程", "CPU使用率", "SSH状态"]
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings", selectmode="extended")
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=150, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True)
        scrollbar = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        # 底部状态栏
        self.status_var = tk.StringVar()
        self.status_var.set("准备就绪")
        self.status_label = tk.Label(root, textvariable=self.status_var, relief=tk.SUNKEN, anchor="w")
        self.status_label.pack(fill=tk.X, side=tk.BOTTOM)

        # 数据
        self.aws_keys_lines = []
        self.instances_to_check = []  # CPU/Top1 刷新
        self.instances_to_ssh = []    # SSH命令下发
        self.stats_lock = threading.Lock()

        # -------------------- 创建三个线程池 --------------------
        self.pool_scan = ThreadPoolExecutor(max_workers=8)
        self.pool_cpu = ThreadPoolExecutor(max_workers=8)
        self.pool_ssh = ThreadPoolExecutor(max_workers=8)

        # CPU刷新循环线程
        threading.Thread(target=self.cpu_refresh_loop, daemon=True).start()

    # -------------------- GUI操作 --------------------
    def toggle_select_all(self):
        items = self.tree.get_children()
        selected = self.tree.selection()
        if len(selected) == len(items):
            self.tree.selection_remove(items)
        else:
            self.tree.selection_set(items)

    # -------------------- 开始检查 --------------------
    def start_check(self):
        aws_keys_text = self.input_box.get("1.0", tk.END).strip()
        self.aws_keys_lines = [line.strip() for line in aws_keys_text.splitlines() if line.strip()]
        if not self.aws_keys_lines:
            messagebox.showwarning("提示","请输入至少一个 AWS 账号")
            return

        # 清空表格
        for item in self.tree.get_children():
            self.tree.delete(item)
        self.instances_to_check.clear()
        self.update_stats()

        self.status_var.set("正在扫描 AWS 实例...")
        self.start_button.config(state=tk.DISABLED)

        # 扫描任务提交到线程池1
        for aws_keys in self.aws_keys_lines:
            self.pool_scan.submit(self.check_account, aws_keys)

        # 扫描完成后恢复按钮
        threading.Thread(target=self.wait_scan_complete, daemon=True).start()

    def wait_scan_complete(self):
        self.pool_scan.shutdown(wait=True)
        self.pool_scan = ThreadPoolExecutor(max_workers=8)  # 重建线程池以便后续使用
        self.root.after(0, lambda: self.status_var.set("AWS实例扫描完成"))
        self.root.after(0, lambda: self.start_button.config(state=tk.NORMAL))

    # -------------------- 检查账号 --------------------
    def check_account(self, aws_keys):
        aws_keys_list = aws_keys.split("----")
        if len(aws_keys_list)<3: return
        email, access_key, secret_key = aws_keys_list[0].strip(), aws_keys_list[1].strip(), aws_keys_list[2].strip()

        if self.scan_option.get() == "us_only":
            regions_to_scan = US_REGIONS
        else:
            regions_to_scan = list(AWS_REGIONS_CN.keys())

        for region in regions_to_scan:
            region_cn = AWS_REGIONS_CN[region]
            region_display = f"{region_cn} [{region}]"
            config = Config(region_name=region, proxies={"http":PROXY,"https":PROXY}, retries={'max_attempts':3})
            ec2 = boto3.client('ec2', aws_access_key_id=access_key, aws_secret_access_key=secret_key, config=config)
            try:
                res = ec2.describe_instances()
                for r in res.get("Reservations",[]):
                    for inst in r.get("Instances",[]):
                        state = inst["State"]["Name"]
                        if state in EC2_IGNORE_STATES: continue
                        state_cn = EC2_STATE_CN.get(state,state)
                        instance_id = inst["InstanceId"]
                        ip = inst.get("PublicIpAddress") or inst.get("PrivateIpAddress") or ""
                        self.instances_to_check.append((email, region_display, instance_id, ip, state_cn))
                        self.insert_tree([email, region_display, instance_id, ip, state_cn, "", 0, ""])
            except:
                continue

    # -------------------- Treeview 插入 --------------------
    def insert_tree(self, row):
        self.root.after(0, lambda: self.tree.insert("", tk.END, values=row))

    # -------------------- CPU刷新循环 --------------------
    def cpu_refresh_loop(self):
        while True:
            if not self.instances_to_check:
                time.sleep(5)
                continue
            self.root.after(0, lambda: self.status_var.set("正在更新 CPU/Top1信息..."))
            futures = []
            for idx, inst in enumerate(list(self.instances_to_check)):
                futures.append(self.pool_cpu.submit(self.update_cpu_top_for_instance, idx, inst))
            for f in futures:
                f.result()
            self.update_stats()
            self.root.after(0, lambda: self.status_var.set("CPU/Top1信息更新完成"))
            time.sleep(5)

    def update_cpu_top_for_instance(self, idx, inst):
        email, region_display, instance_id, ip, state_cn = inst
        top_proc, cpu = self.get_ssh_info(ip)
        self.root.after(0, lambda i=idx, t=top_proc, c=cpu: self.update_tree_cpu_top(i,t,c))

    def update_tree_cpu_top(self, idx, top_proc, cpu):
        try:
            iid = self.tree.get_children()[idx]
            self.tree.set(iid,"Top1进程",top_proc)
            self.tree.set(iid,"CPU使用率",cpu)
        except:
            pass

    # -------------------- SSH CPU/Top1 获取 --------------------
    def get_ssh_info(self, ip):
        if not ip: return "",0
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=SSH_USER, password=SSH_PASS, timeout=5)
            stdin, stdout, stderr = ssh.exec_command("ps -eo comm,%cpu --sort=-%cpu | head -n 2 | tail -n 1")
            top_line = stdout.read().decode().strip()
            top_proc = top_line.split()[0] if top_line else ""
            stdin, stdout, stderr = ssh.exec_command("top -bn1 | grep 'Cpu(s)' | awk '{print 100-$8}'")
            cpu_str = stdout.read().decode().strip()
            cpu = round(float(cpu_str),2) if cpu_str else 0
            ssh.close()
            return top_proc, cpu
        except:
            return "",0

    # -------------------- 统计 --------------------
    def update_stats(self):
        with self.stats_lock:
            states = {"运行中":0,"已停止":0,"开机中":0,"关机中":0}
            cpu_low = 0
            cpu_total = 0
            for iid in self.tree.get_children():
                vals = self.tree.item(iid)["values"]
                state = vals[4]
                cpu = float(vals[6]) if vals[6] else 0
                if state in states: states[state]+=1
                if cpu<50: cpu_low+=1
                cpu_total+=cpu
            total_instances = len(self.tree.get_children())
            total_accounts = len(set([self.tree.item(i)["values"][0] for i in self.tree.get_children()]))
            avg_cpu = round(cpu_total/max(total_instances,1),2)
            stats_text = f"账号数:{total_accounts} | 实例数:{total_instances} | 运行中:{states['运行中']} | 已停止:{states['已停止']} | 开机中:{states['开机中']} | 关机中:{states['关机中']} | CPU<50:{cpu_low} | 平均CPU:{avg_cpu}%"
            self.root.after(0, lambda:self.stats_var.set(stats_text))

    # -------------------- 异步 SSH 下发 --------------------
    def batch_ssh_command(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("提示", "请先选择实例")
            return
        cmd = self.ssh_command_box.get().strip()
        self.instances_to_ssh = [(self.tree.item(i)["values"][3], i) for i in selected_items]
        threading.Thread(target=self.run_ssh_threadpool, args=(cmd,), daemon=True).start()

    def run_ssh_threadpool(self, cmd):
        self.root.after(0, lambda: self.status_var.set("正在下发 SSH 命令..."))
        futures = []
        for ip, iid in self.instances_to_ssh:
            futures.append(self.pool_ssh.submit(self._ssh_command, ip, iid, cmd))
        for f in futures:
            f.result()
        self.root.after(0, lambda: self.status_var.set("SSH命令下发完成"))

    def _ssh_command(self, ip, iid, cmd):
        if not ip:
            self._update_ssh_status(iid, "失败")
            return
        try:
            self._update_ssh_status(iid, "执行中")
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=SSH_USER, password=SSH_PASS, timeout=5)
            stdin, stdout, stderr = ssh.exec_command(cmd)
            stdout.channel.recv_exit_status()
            ssh.close()
            self._update_ssh_status(iid, "成功")
        except:
            self._update_ssh_status(iid, "失败")

    # -------------------- 同步 SSH 下发 --------------------
    def batch_ssh_command_sync(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("提示", "请先选择实例")
            return

        cmd = self.ssh_command_box.get().strip()
        self.batch_ssh_sync_button.config(state=tk.DISABLED)
        self.status_var.set("正在下发 SSH 命令并等待执行完成...")

        for iid in selected_items:
            ip = self.tree.item(iid)["values"][3]
            if not ip:
                self.tree.set(iid, "SSH状态", "失败")
                continue

            self.tree.set(iid, "SSH状态", "执行中")
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(ip, username=SSH_USER, password=SSH_PASS, timeout=5)

                stdin, stdout, stderr = ssh.exec_command(cmd)
                exit_status = stdout.channel.recv_exit_status()  # 阻塞等待命令完成

                ssh.close()
                if exit_status == 0:
                    self.tree.set(iid, "SSH状态", "成功")
                else:
                    self.tree.set(iid, "SSH状态", "失败")
            except Exception as e:
                print(f"{ip} 执行失败: {e}")
                self.tree.set(iid, "SSH状态", "失败")

        self.status_var.set("SSH命令执行完成")
        self.batch_ssh_sync_button.config(state=tk.NORMAL)

    def _update_ssh_status(self, iid, status):
        self.root.after(0, lambda: self.tree.set(iid, "SSH状态", status))


if __name__=="__main__":
    root=tk.Tk()
    app=AWSCheckerGUI(root)
    root.mainloop()
