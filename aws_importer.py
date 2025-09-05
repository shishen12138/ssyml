# -*- coding: utf-8 -*-
import boto3
import json
import sys
import os

HOSTS_FILE = '/root/ssh_panel/hosts.json'
LOG_FILE = '/root/ssh_panel/aws_import.log'

def load_hosts():
    if not os.path.exists(HOSTS_FILE):
        return []
    with open(HOSTS_FILE, 'r') as f:
        return json.load(f)

def save_hosts(hosts):
    with open(HOSTS_FILE, 'w') as f:
        json.dump(hosts, f, indent=4)

def log(msg):
    with open(LOG_FILE, 'a') as f:
        f.write(msg + '\n')
    print(msg)

def import_aws(accounts_raw):
    hosts = load_hosts()
    new_hosts = []

    accounts = []
    for line in accounts_raw.splitlines():
        parts = line.strip().split('----')
        if len(parts) >= 3:
            accounts.append((parts[1].strip(), parts[2].strip()))

    log(f"开始导入 AWS 账号，总账号数 {len(accounts)}")

    for idx, (access_key, secret_key) in enumerate(accounts, start=1):
        log(f"开始处理账号 {idx}")
        session = boto3.Session(aws_access_key_id=access_key, aws_secret_access_key=secret_key)
        try:
            ec2_client = session.client('ec2', region_name='us-east-1')
            regions_resp = ec2_client.describe_regions()['Regions']
            all_regions = [r['RegionName'] for r in regions_resp]
        except Exception as e:
            log(f"账号 {idx} 获取区域失败: {e}")
            continue

        for region in all_regions:
            log(f"账号 {idx} 连接区域: {region}")
            try:
                ec2 = session.client('ec2', region_name=region)
                reservations = ec2.describe_instances().get('Reservations', [])
                for res in reservations:
                    for inst in res.get('Instances', []):
                        ip = inst.get('PublicIpAddress') or inst.get('PrivateIpAddress')
                        if ip:
                            host_info = {
                                "ip": ip,
                                "port": 22,
                                "username": "root",
                                "password": "Qcy1994@06",
                                "region": region,
                                "source": "aws"
                            }
                            hosts.append(host_info)
                            new_hosts.append(host_info)
                            log(f"账号 {idx} 区域 {region} 添加实例 {ip}")
            except Exception as e:
                log(f"账号 {idx} 区域 {region} 出现错误: {e}")

    save_hosts(hosts)
    log(f"AWS 导入完成，共添加 {len(new_hosts)} 台主机")

if __name__ == '__main__':
    accounts_file = sys.argv[1]
    if os.path.exists(accounts_file):
        with open(accounts_file, 'r') as f:
            accounts_raw = f.read()
        import_aws(accounts_raw)
