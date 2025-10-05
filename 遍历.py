import tkinter as tk
from tkinter import ttk, scrolledtext
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor
import threading
from collections import Counter

# 代理配置
PROXY = "http://yhvbjsyeu54467-zone-abc-region-US:hhdjshs7@na.1fa7a9d3999e70e8.abcproxy.vip:4950"

# AWS 区域列表
AWS_REGIONS = [
    "us-east-1", "us-east-2", "us-west-1", "us-west-2",
    "ap-south-1", "ap-northeast-1", "ap-northeast-2",
    "ap-southeast-1", "ap-southeast-2", "ca-central-1",
    "eu-central-1", "eu-west-1", "eu-west-2", "eu-west-3",
    "sa-east-1"
]

# EC2 状态
EC2_STATES = ["running", "stopped", "pending", "stopping"]

class AWSCheckerTreeview:
    def __init__(self, root):
        self.root = root
        self.root.title("AWS EC2 检查工具 - Treeview 版")
        self.root.geometry("1000x700")

        # 输入框
        tk.Label(root, text="请输入 AWS 账号（每行一个，格式：email----access_key----secret_key）").pack()
        self.input_box = scrolledtext.ScrolledText(root, height=10)
        self.input_box.pack(fill=tk.X, padx=5, pady=5)

        # 开始按钮
        tk.Button(root, text="开始检查", command=self.start_check).pack(pady=5)

        # Treeview 表格
        self.tree_frame = tk.Frame(root)
        self.tree_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        columns = ["账号", "区域"] + EC2_STATES
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120, anchor="center")
        self.tree.pack(fill=tk.BOTH, expand=True)

        # 滚动条
        scrollbar = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscroll=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

    def start_check(self):
        aws_keys_text = self.input_box.get("1.0", tk.END).strip()
        aws_keys_lines = [line.strip() for line in aws_keys_text.splitlines() if line.strip()]
        if not aws_keys_lines:
            tk.messagebox.showwarning("提示", "请输入至少一个 AWS 账号")
            return

        # 清空表格
        for item in self.tree.get_children():
            self.tree.delete(item)

        threading.Thread(target=self.process_accounts, args=(aws_keys_lines,), daemon=True).start()

    def process_accounts(self, aws_keys_lines):
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = []
            for aws_keys in aws_keys_lines:
                futures.append(executor.submit(self.check_account, aws_keys))
            for future in futures:
                future.result()

    def check_account(self, aws_keys):
        aws_keys_list = aws_keys.split("----")
        if len(aws_keys_list) < 3:
            self.insert_tree([aws_keys, "Key格式错误"] + [""]*len(EC2_STATES))
            return

        email = aws_keys_list[0].strip()
        access_key = aws_keys_list[1].strip()
        secret_key = aws_keys_list[2].strip()

        for region in AWS_REGIONS:
            config = Config(
                region_name=region,
                proxies={"http": PROXY, "https": PROXY},
                retries={'max_attempts': 3}
            )
            ec2 = boto3.client(
                'ec2',
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                config=config
            )
            try:
                response = ec2.describe_instances()
                reservations = response.get('Reservations', [])
                status_counter = Counter()
                for reservation in reservations:
                    for instance in reservation['Instances']:
                        state = instance['State']['Name']
                        if state in EC2_STATES:
                            status_counter[state] += 1

                row = [email, region] + [status_counter.get(state, 0) for state in EC2_STATES]
                self.insert_tree(row)

            except ClientError as e:
                row = [email, region] + [f"错误: {str(e)}"] + [""]*(len(EC2_STATES)-1)
                self.insert_tree(row)
            except Exception as e:
                row = [email, region] + [f"异常: {str(e)}"] + [""]*(len(EC2_STATES)-1)
                self.insert_tree(row)

    def insert_tree(self, row):
        # 主线程安全插入
        self.root.after(0, lambda: self.tree.insert("", tk.END, values=row))

if __name__ == "__main__":
    root = tk.Tk()
    app = AWSCheckerTreeview(root)
    root.mainloop()
