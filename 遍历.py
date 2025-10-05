import tkinter as tk
from tkinter import ttk, scrolledtext
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from concurrent.futures import ThreadPoolExecutor
import threading

# 代理配置
PROXY = "http://yhvbjsyeu54467-zone-abc-region-US:hhdjshs7@na.1fa7a9d3999e70e8.abcproxy.vip:4950"

# AWS 区域映射：英文 -> 中文
AWS_REGIONS_CN = {
    "us-east-1": "美国东部（弗吉尼亚）",
    "us-east-2": "美国东部（俄亥俄）",
    "us-west-1": "美国西部（北加利福尼亚）",
    "us-west-2": "美国西部（俄勒冈）",
    "ap-south-1": "亚太地区（孟买）",
    "ap-northeast-1": "亚太地区（东京）",
    "ap-northeast-2": "亚太地区（首尔）",
    "ap-southeast-1": "亚太地区（新加坡）",
    "ap-southeast-2": "亚太地区（悉尼）",
    "ca-central-1": "加拿大中部（蒙特利尔）",
    "eu-central-1": "欧洲（法兰克福）",
    "eu-west-1": "欧洲（爱尔兰）",
    "eu-west-2": "欧洲（伦敦）",
    "eu-west-3": "欧洲（巴黎）",
    "sa-east-1": "南美洲（圣保罗）"
}

# EC2 状态，过滤 terminated
EC2_IGNORE_STATES = ["terminated"]

class AWSCheckerTreeviewCN:
    def __init__(self, root):
        self.root = root
        self.root.title("AWS EC2 检查工具 - 中文区域显示")
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

        columns = ["账号", "区域", "实例ID", "实例IP", "状态"]
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show="headings")
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=180, anchor="center")
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
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=16) as executor:
            futures = []
            for aws_keys in aws_keys_lines:
                futures.append(executor.submit(self.check_account, aws_keys))
            for future in futures:
                future.result()

    def check_account(self, aws_keys):
        aws_keys_list = aws_keys.split("----")
        if len(aws_keys_list) < 3:
            self.insert_tree([aws_keys, "", "Key格式错误", "", ""])
            return

        email = aws_keys_list[0].strip()
        access_key = aws_keys_list[1].strip()
        secret_key = aws_keys_list[2].strip()

        for region in AWS_REGIONS_CN.keys():
            region_cn = AWS_REGIONS_CN.get(region, region)
            region_display = f"{region_cn} [{region}]"

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
                for reservation in reservations:
                    for instance in reservation['Instances']:
                        state = instance['State']['Name']
                        if state in EC2_IGNORE_STATES:
                            continue
                        instance_id = instance['InstanceId']
                        ip = instance.get("PublicIpAddress") or instance.get("PrivateIpAddress") or ""
                        self.insert_tree([email, region_display, instance_id, ip, state])
            except ClientError as e:
                self.insert_tree([email, region_display, "", f"错误: {str(e)}", ""])
            except Exception as e:
                self.insert_tree([email, region_display, "", f"异常: {str(e)}", ""])

    def insert_tree(self, row):
        self.root.after(0, lambda: self.tree.insert("", tk.END, values=row))


if __name__ == "__main__":
    root = tk.Tk()
    app = AWSCheckerTreeviewCN(root)
    root.mainloop()
