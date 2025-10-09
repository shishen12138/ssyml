"""
依赖：pip install boto3
运行：python aws_instance_checker.py
"""

import os
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import boto3
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# 美国四区
REGIONS_USA = [
    ("us-east-1", "美国东部 - 弗吉尼亚"),
    ("us-east-2", "美国东部 - 俄亥俄"),
    ("us-west-1", "美国西部 - 北加州"),
    ("us-west-2", "美国西部 - 俄勒冈"),
]
# 区域中文映射，可根据需要扩展
REGION_CN_MAP = {
    # 美国
    "us-east-1": "美国东部 - 弗吉尼亚北部",
    "us-east-2": "美国东部 - 俄亥俄",
    "us-west-1": "美国西部 - 北加州",
    "us-west-2": "美国西部 - 俄勒冈",
    "us-gov-west-1": "美国 GovCloud 西部",
    "us-gov-east-1": "美国 GovCloud 东部",
    # 加拿大
    "ca-central-1": "加拿大 - 中部",
    # 南美
    "sa-east-1": "南美 - 圣保罗",
    # 欧洲
    "eu-north-1": "欧洲 - 斯德哥尔摩",
    "eu-west-1": "欧洲 - 爱尔兰",
    "eu-west-2": "欧洲 - 伦敦",
    "eu-west-3": "欧洲 - 巴黎",
    "eu-central-1": "欧洲 - 法兰克福",
    "eu-south-1": "欧洲 - 米兰",
    "eu-south-2": "欧洲 - 西班牙",
    "eu-central-2": "欧洲 - 苏黎世",
    # 中东
    "me-south-1": "中东 - 巴林",
    "me-central-1": "中东 - 阿布扎比",
    # 非洲
    "af-south-1": "非洲 - 开普敦",
    # 亚太
    "ap-east-1": "亚太 - 香港",
    "ap-east-2": "亚太 - 台北",
    "ap-south-1": "亚太 - 孟买",
    "ap-south-2": "亚太 - 海得拉巴",
    "ap-northeast-1": "亚太 - 东京",
    "ap-northeast-2": "亚太 - 首尔",
    "ap-northeast-3": "亚太 - 大阪",
    "ap-southeast-1": "亚太 - 新加坡",
    "ap-southeast-2": "亚太 - 悉尼",
    "ap-southeast-3": "亚太 - 雅加达",
    "ap-southeast-4": "亚太 - 墨尔本",
    "ap-southeast-5": "亚太 - 马来西亚",
    "ap-southeast-6": "亚太 - 新西兰",
    "ap-southeast-7": "亚太 - 泰国",
}

DEFAULT_PROXY = "http://yhvbjsyeu54467-zone-abc-region-US:hhdjshs7@na.1fa7a9d3999e70e8.abcproxy.vip:4950"
STATE_MAP = {
    'running': 'running (运行中)',
    'stopped': 'stopped (关机)',
    'terminated': 'terminated (已删除)'
}

class AWSInstanceChecker(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AWS 实例检测面板")
        self.geometry("1050x720")
        self.all_results = {}  # 缓存详细数据
        self._build_ui()

    def _build_ui(self):
        frm_top = ttk.Frame(self)
        frm_top.pack(fill=tk.X, padx=8, pady=6)

        ttk.Label(frm_top, text="批量账号 (每行: email----ACCESS----SECRET):").pack(anchor=tk.W)
        self.txt_accounts = scrolledtext.ScrolledText(frm_top, width=100, height=5)
        self.txt_accounts.pack(fill=tk.X, padx=4, pady=4)

        ttk.Label(frm_top, text="HTTP(S) Proxy:").pack(anchor=tk.W)
        self.entry_proxy = ttk.Entry(frm_top, width=100)
        self.entry_proxy.pack(fill=tk.X, padx=4, pady=2)
        self.entry_proxy.insert(0, DEFAULT_PROXY)

        # 区域选择
        frm_region_choice = ttk.Frame(frm_top)
        frm_region_choice.pack(fill=tk.X, pady=4)
        ttk.Label(frm_region_choice, text="选择区域: ").pack(side=tk.LEFT)
        self.region_choice_var = tk.StringVar(value='USA')
        ttk.Radiobutton(frm_region_choice, text="美国四区", variable=self.region_choice_var, value='USA').pack(side=tk.LEFT, padx=6)
        ttk.Radiobutton(frm_region_choice, text="全区（实际可用区）", variable=self.region_choice_var, value='ALL').pack(side=tk.LEFT, padx=6)

        frm_ops = ttk.Frame(self)
        frm_ops.pack(fill=tk.X, padx=8, pady=6)

        self.btn_check = ttk.Button(frm_ops, text="开始检测", command=self.start_check)
        self.btn_check.pack(side=tk.LEFT)

        self.lbl_status = ttk.Label(frm_ops, text="就绪")
        self.lbl_status.pack(side=tk.LEFT, padx=10)

        # PanedWindow 自适应高度
        paned = ttk.Panedwindow(self, orient=tk.VERTICAL)
        paned.pack(fill=tk.BOTH, expand=True, padx=8, pady=6)

        # 汇总表
        frame_summary = ttk.Frame(paned)
        paned.add(frame_summary, weight=3)

        columns_sum = ("account", "region_count", "total_running", "longest_region", "longest_time")
        self.tree_sum = ttk.Treeview(frame_summary, columns=columns_sum, show='headings')
        for col, text, width in zip(columns_sum, ["账号", "开机区域数", "总开机数量", "最长运行时长区域", "最长运行时长"], [220, 160, 130, 180, 200]):
            self.tree_sum.heading(col, text=text)
            self.tree_sum.column(col, width=width, anchor=tk.CENTER)
        self.tree_sum.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        self.tree_sum.bind('<Double-1>', self.show_detail_popup)

        # 日志
        self.log = scrolledtext.ScrolledText(paned)
        paned.add(self.log, weight=1)

    def start_check(self):
        self.btn_check.config(state=tk.DISABLED)
        self.lbl_status.config(text="检测中...")
        threading.Thread(target=self._check_instances, daemon=True).start()

    def _log(self, msg):
        ts = datetime.now().strftime('%H:%M:%S')
        self.log.insert(tk.END, f"[{ts}] {msg}\n")
        self.log.see(tk.END)

    def _fetch_region_data(self, acc_email, acc_key, acc_secret, region, region_cn, now_utc):
        details = []
        try:
            session = boto3.Session(
                aws_access_key_id=acc_key,
                aws_secret_access_key=acc_secret,
                region_name=region
            )
            ec2 = session.client('ec2')
            paginator = ec2.get_paginator('describe_instances')
            for page in paginator.paginate():
                for res in page.get('Reservations', []):
                    for inst in res.get('Instances', []):
                        state = inst.get('State', {}).get('Name', 'unknown')
                        instance_id = inst.get('InstanceId', 'N/A')
                        uptime_min = 0
                        if state == 'running':
                            lt = inst.get('LaunchTime')
                            if lt:
                                if lt.tzinfo is None:
                                    lt = lt.replace(tzinfo=timezone.utc)
                                delta = now_utc - lt
                                uptime_min = delta.days*1440 + delta.seconds//60
                        d,h = divmod(uptime_min,1440)
                        h,m = divmod(h,60)
                        uptime_str = f"{d}天 {h}小时 {m}分钟" if state=='running' else '0'
                        details.append({
                            'InstanceId': instance_id,
                            'Region': f'{region} ({region_cn})',
                            'State': STATE_MAP.get(state,state),
                            'Uptime': uptime_str
                        })
            return details
        except Exception as e:
            msg = str(e)
            # 判断是否为认证失败
            if "AuthFailure" in msg or "UnrecognizedClientException" in msg:
                self._log(f"[{acc_email}] 区域 {region}：认证失败，请检查 Key 或权限 ❌")
                # 返回统一占位数据，面板显示“请检查 Key 或权限”
                details.append({
                    'InstanceId': '请检查 Key 或权限',
                    'Region': f'{region} ({region_cn})',
                    'State': '请检查 Key 或权限',
                    'Uptime': '请检查 Key 或权限'
                })
            else:
                self._log(f"[{acc_email}] 区域 {region}：{msg}")
            return details


    def _get_account_enabled_regions(self, acc_key, acc_secret):
        """获取账号实际可用区域"""
        try:
            session = boto3.Session(aws_access_key_id=acc_key, aws_secret_access_key=acc_secret)
            ec2 = session.client("ec2", region_name="us-east-1")
            response = ec2.describe_regions(AllRegions=False)
            regions = [(r['RegionName'], REGION_CN_MAP.get(r['RegionName'], r['RegionName'])) for r in response['Regions']]
            return regions
        except Exception as e:
            self._log(f"获取账号可用区域失败: {e}")
            return []

    def _process_account(self, acc_email, acc_key, acc_secret, now_utc):
        results = []
        # 根据区域选择
        if self.region_choice_var.get() == 'USA':
            selected_regions = REGIONS_USA
        else:
            selected_regions = self._get_account_enabled_regions(acc_key, acc_secret)
        if not selected_regions:
            self._log(f"账号 {acc_email} 没有可用区域或获取失败")
            return results

        with ThreadPoolExecutor(max_workers=4) as exec_region:
            futures = [exec_region.submit(self._fetch_region_data, acc_email, acc_key, acc_secret, r[0], r[1], now_utc) for r in selected_regions]
            for f in as_completed(futures):
                results.extend(f.result())
        return results

    def _update_summary(self, acc_email, details):
        self.all_results[acc_email] = details
        # 判断是否为认证失败占位
        if details and all(d.get('State') == '请检查 Key 或权限' for d in details):
            self.tree_sum.insert('', tk.END, values=(
                acc_email,  # 账号
                '请检查 Key 或权限',  # 开机区域数
                '请检查 Key 或权限',  # 总开机数量
                '请检查 Key 或权限',  # 最长运行时长区域
                '请检查 Key 或权限'   # 最长运行时长
            ))
            return

        regions = set(d['Region'] for d in details if '运行中' in d['State'])
        total_running = sum(1 for d in details if '运行中' in d['State'])
        longest_region,longest_time='无','无'
        max_uptime=-1
        for d in details:
            if '运行中' in d['State']:
                hms = d['Uptime']
                parts = hms.split()
                mins = int(parts[0][:-1])*1440 + int(parts[1][:-2])*60 + int(parts[2][:-2])
                if mins>max_uptime:
                    max_uptime=mins
                    longest_region=d['Region']
                    longest_time=d['Uptime']
        self.tree_sum.insert('',tk.END,values=(acc_email,len(regions),total_running,longest_region,longest_time))

    def show_detail_popup(self,event):
        item=self.tree_sum.selection()
        if not item:
            return
        acc_email=self.tree_sum.item(item[0],'values')[0]
        details=self.all_results.get(acc_email,[])
        popup=tk.Toplevel(self)
        popup.title(f"账号 {acc_email} 详细信息")
        popup.geometry("800x500")
        tree=ttk.Treeview(popup,columns=("InstanceId","Region","State","Uptime"),show='headings')
        for col,text,width in zip(("InstanceId","Region","State","Uptime"),["实例ID","区域","状态","运行时长"],[200,250,150,200]):
            tree.heading(col,text=text)
            tree.column(col,width=width,anchor=tk.CENTER)
        tree.pack(fill=tk.BOTH,expand=True,padx=6,pady=6)
        for d in details:
            tree.insert('',tk.END,values=(d['InstanceId'],d['Region'],d['State'],d['Uptime']))

    def _check_instances(self):
        try:
            # 清空汇总表和缓存
            for i in self.tree_sum.get_children():
                self.tree_sum.delete(i)
            self.all_results.clear()

            accounts_raw = self.txt_accounts.get('1.0', tk.END).strip()
            if not accounts_raw:
                messagebox.showwarning("账号未填写","请填写至少一行账号")
                self.btn_check.config(state=tk.NORMAL)
                return

            # 解析账号，支持三种格式
            accounts=[]
            lines = [line.strip() for line in accounts_raw.splitlines() if line.strip()]
            i = 0
            while i < len(lines):
                line = lines[i]
                # 情况1: email----ACCESS----SECRET
                if '----' in line:
                    parts = line.split('----')
                    if len(parts) >= 3:
                        accounts.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
                    i += 1
                # 情况2: ACCESS 和 SECRET 分两行，下一行可能是 email
                elif '@' not in line and i+1 < len(lines):
                    access = line
                    secret = lines[i+1]
                    email = ''
                    if i+2 < len(lines) and '@' in lines[i+2]:
                        email = lines[i+2].strip()
                        i += 1
                    accounts.append((email, access.strip(), secret.strip()))
                    i += 2
                # 情况3: 空格分隔多个字段
                elif ' ' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        accounts.append((parts[0].strip(), parts[1].strip(), parts[2].strip()))
                    i += 1
                else:
                    # 无效行跳过
                    i += 1

            if not accounts:
                messagebox.showwarning("账号解析失败","未解析到有效账号")
                self.btn_check.config(state=tk.NORMAL)
                return

            # 设置代理
            proxy = self.entry_proxy.get().strip()
            if proxy:
                os.environ['HTTP_PROXY']=proxy
                os.environ['HTTPS_PROXY']=proxy
                os.environ['http_proxy']=proxy
                os.environ['https_proxy']=proxy

            now_utc = datetime.now(timezone.utc)

            # 外层账号线程池
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_acc = {executor.submit(self._process_account, acc_email, acc_key, acc_secret, now_utc): acc_email for acc_email, acc_key, acc_secret in accounts}
                for future in as_completed(future_to_acc):
                    acc_email = future_to_acc[future]
                    try:
                        details = future.result()
                        self.after(0, self._update_summary, acc_email, details)
                        self._log(f"账号 {acc_email} 查询完成")
                    except Exception as e:
                        self._log(f"账号 {acc_email} 检测异常: {e}")

            self._log("全部检测完成 ✅")

        finally:
            self.btn_check.config(state=tk.NORMAL)
            self.lbl_status.config(text="就绪")


if __name__=='__main__':
    app=AWSInstanceChecker()
    app.mainloop()
