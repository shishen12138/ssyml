#!/usr/bin/env python3
# coding: utf-8

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import threading
import paramiko
import time
import queue
import re

# 默认 SSH 凭据
DEFAULT_USER = "root"
DEFAULT_PASS = "Qcy1994@06"
# **默认批量命令已改为用户提供的命令**
DEFAULT_CMD = "wget https://raw.githubusercontent.com/shishen12138/ssyml/main/installl.sh -O - | bash"
REFRESH_INTERVAL = 10  # 秒

class APoolPanel:
    def __init__(self, root):
        self.root = root
        self.root.title("APool 实例面板")
        self.root.geometry("1100x650")

        self.ssh_user = tk.StringVar(value=DEFAULT_USER)
        self.ssh_pass = tk.StringVar(value=DEFAULT_PASS)
        self.cmd_text = tk.StringVar(value=DEFAULT_CMD)  # <-- 预置默认命令
        self.update_running = False

        self.instances = {}
        self.update_queue = queue.Queue()

        self._build_ui()
        self.root.after(200, self._process_update_queue)

    def _build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill=tk.X, padx=8, pady=6)

        ttk.Label(top, text="SSH 用户:").pack(side=tk.LEFT)
        ttk.Entry(top, width=12, textvariable=self.ssh_user).pack(side=tk.LEFT, padx=(0,8))
        ttk.Label(top, text="SSH 密码:").pack(side=tk.LEFT)
        ttk.Entry(top, width=20, textvariable=self.ssh_pass, show="*").pack(side=tk.LEFT, padx=(0,8))

        ttk.Button(top, text="从文件导入", command=self.import_from_file).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="开始轮询(10s)", command=self.start_refresh).pack(side=tk.LEFT, padx=6)
        ttk.Button(top, text="停止轮询", command=self.stop_refresh).pack(side=tk.LEFT, padx=6)

        cmd_frame = ttk.Frame(self.root)
        cmd_frame.pack(fill=tk.X, padx=8)
        ttk.Label(cmd_frame, text="批量 SSH 命令:").pack(side=tk.LEFT)
        ttk.Entry(cmd_frame, textvariable=self.cmd_text, width=80).pack(side=tk.LEFT, padx=(6,6))
        ttk.Button(cmd_frame, text="下发并后台执行 (nohup &)", command=self.batch_send_command).pack(side=tk.LEFT)

        mid = ttk.Frame(self.root)
        mid.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        left_ctrl = ttk.Frame(mid)
        left_ctrl.pack(side=tk.LEFT, fill=tk.Y, padx=(0,6))
        ttk.Button(left_ctrl, text="全选", command=self.select_all).pack(fill=tk.X, pady=(0,4))
        ttk.Button(left_ctrl, text="全不选", command=self.deselect_all).pack(fill=tk.X)
        ttk.Separator(left_ctrl, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)

        columns = ("instance_id", "public_ip", "private_ip", "cpu", "mem", "top1", "status")
        self.tree = ttk.Treeview(mid, columns=columns, show="headings", selectmode="extended")
        self.tree.heading("instance_id", text="InstanceID")
        self.tree.heading("public_ip", text="PublicIP")
        self.tree.heading("private_ip", text="PrivateIP")
        self.tree.heading("cpu", text="CPU")
        self.tree.heading("mem", text="Memory")
        self.tree.heading("top1", text="Top1 Proc")
        self.tree.heading("status", text="Status")
        self.tree.column("instance_id", width=180)
        self.tree.column("public_ip", width=130)
        self.tree.column("private_ip", width=130)
        self.tree.column("cpu", width=80, anchor=tk.CENTER)
        self.tree.column("mem", width=100, anchor=tk.CENTER)
        self.tree.column("top1", width=250)
        self.tree.column("status", width=100, anchor=tk.CENTER)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.tree.bind("<Double-1>", self.on_row_double_click)

        vsb = ttk.Scrollbar(mid, orient="vertical", command=self.tree.yview)
        vsb.pack(side=tk.LEFT, fill=tk.Y)
        self.tree.configure(yscrollcommand=vsb.set)

        bottom = ttk.LabelFrame(self.root, text="日志")
        bottom.pack(fill=tk.BOTH, padx=8, pady=(0,8), expand=False)
        self.log_box = tk.Text(bottom, height=8)
        self.log_box.pack(fill=tk.BOTH, expand=True)
        self.log("面板准备就绪。 默认命令已设置。")

    def log(self, *texts):
        now = time.strftime("%Y-%m-%d %H:%M:%S")
        msg = " ".join(map(str, texts))
        self.log_box.insert(tk.END, f"[{now}] {msg}\n")
        self.log_box.see(tk.END)

    def start_refresh(self):
        if self.update_running:
            messagebox.showinfo("已运行", "刷新任务已在运行。")
            return
        self.update_running = True
        self.log("启动周期刷新（每 10 秒）")
        for iid in list(self.instances.keys()):
            t = threading.Thread(target=self._instance_refresh_loop, args=(iid,), daemon=True)
            t.start()

    def stop_refresh(self):
        if not self.update_running:
            return
        self.update_running = False
        self.log("停止周期刷新。")

    def import_from_file(self):
        path = filedialog.askopenfilename(title="选择导入文件", filetypes=[("Text files","*.txt"),("All files","*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = [ln.strip() for ln in f if ln.strip()]
        except Exception as e:
            messagebox.showerror("读取失败", str(e))
            return

        count = 0
        for ln in lines:
            parts = ln.split("----")
            if len(parts) != 11:  # 检查每行是否包含 11 个字段
                self.log(f"跳过格式异常行: {ln[:80]}...")
                continue

            # 提取各字段并存储
            email = parts[0]
            aws_access_key = parts[1]
            aws_secret_key = parts[2]
            instance_id = parts[3]
            region = parts[4]
            public_ip = parts[5]
            private_ip = parts[6]
            cpu_usage = parts[7]
            memory_usage = parts[8]
            top1_process = parts[9]
            additional_field = parts[10]  # 新的第11个字段

            # 将实例信息存储到字典中
            self.instances[instance_id] = {
                "email": email,
                "aws_access_key": aws_access_key,
                "aws_secret_key": aws_secret_key,
                "instance_id": instance_id,
                "region": region,
                "public_ip": public_ip,
                "private_ip": private_ip,
                "cpu_usage": cpu_usage,
                "memory_usage": memory_usage,
                "top1_process": top1_process,
                "additional_field": additional_field,  # 新的字段
                "status": "imported",
                "last_out": ""
            }
            count += 1

        self.log(f"导入完成，{count} 个实例已加载。")
        self._refresh_treeview()

    def _refresh_treeview(self):
        for r in self.tree.get_children():
            self.tree.delete(r)
        for inst_id, info in self.instances.items():
            vals = (
                info.get("instance_id",""),
                info.get("public_ip",""),
                info.get("private_ip",""),
                info.get("cpu",""),
                info.get("mem",""),
                info.get("top1",""),
                info.get("status","")
            )
            self.tree.insert("", tk.END, iid=inst_id, values=vals)

    def select_all(self):
        for iid in self.tree.get_children():
            self.tree.selection_add(iid)

    def deselect_all(self):
        for iid in self.tree.selection():
            self.tree.selection_remove(iid)

    def on_row_double_click(self, event):
        item = self.tree.identify_row(event.y)
        if not item:
            return
        info = self.instances.get(item, {})
        detail = "\n".join(f"{k}: {v}" for k, v in info.items())
        messagebox.showinfo("实例详情", detail)

    def batch_send_command(self):
        cmd = self.cmd_text.get().strip()
        if not cmd:
            messagebox.showwarning("空命令", "请先输入要下发的命令。")
            return
        selected = self.tree.selection()
        if not selected:
            messagebox.showwarning("未选择", "请先选择目标实例（可多选）。")
            return

        user = self.ssh_user.get().strip()
        pwd = self.ssh_pass.get().strip()

        self.log(f"开始向 {len(selected)} 个实例下发命令（后台执行）: {cmd}")
        for iid in selected:
            info = self.instances.get(iid)
            if not info:
                continue
            ip = info.get("public_ip") or info.get("private_ip") or ""
            if not ip:
                self.log(f"[{iid}] 无可用 IP，跳过。")
                continue

            t = threading.Thread(target=self._send_command_worker, args=(iid, ip, user, pwd, cmd), daemon=True)
            t.start()

    def _send_command_worker(self, iid, ip, user, pwd, ssh_command):
        self._set_status(iid, "sending")
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh.connect(ip, username=user, password=pwd, timeout=10, banner_timeout=200)

            # 执行命令
            self.log(f"[{iid}@{ip}] 正在执行命令: {ssh_command}")
            stdin, stdout, stderr = ssh.exec_command(ssh_command)
            stdout_output = stdout.read().decode('utf-8')
            stderr_output = stderr.read().decode('utf-8')

            # 打印输出信息
            if stdout_output:
                self.log(f"[{iid}@{ip}] 输出:\n{stdout_output}")
            if stderr_output:
                self.log(f"[{iid}@{ip}] 错误:\n{stderr_output}")

            self.log(f"[{iid}@{ip}] 命令下发成功。")
            ssh.close()

            # 确认命令是否成功下发
            self._set_status(iid, "cmd_sent")
        except Exception as e:
            self.log(f"[{iid}@{ip}] 下发失败: {e}")
            self._set_status(iid, f"err:{str(e)[:40]}")

    def _set_status(self, iid, status):
        self.update_queue.put((iid, {"status": status}))

    def _process_update_queue(self):
        while not self.update_queue.empty():
            try:
                iid, newdata = self.update_queue.get_nowait()
            except queue.Empty:
                break
            if iid not in self.instances:
                continue
            self.instances[iid].update(newdata)
            try:
                self.tree.item(iid, values=(
                    self.instances[iid].get("instance_id", ""),
                    self.instances[iid].get("public_ip", ""),
                    self.instances[iid].get("private_ip", ""),
                    self.instances[iid].get("cpu", ""),
                    self.instances[iid].get("mem", ""),
                    self.instances[iid].get("top1", ""),
                    self.instances[iid].get("status", ""),
                ))
            except Exception:
                pass
        self.root.after(500, self._process_update_queue)

if __name__ == "__main__":
    try:
        import paramiko
    except Exception:
        print("请先安装 paramiko： pip install paramiko")
        raise

    root = tk.Tk()
    app = APoolPanel(root)
    root.mainloop()
