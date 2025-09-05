# -*- coding: utf-8 -*-
import boto3

def import_aws_instances(accounts, batch_size=5):
    """
    accounts: list of tuples [(access_key, secret_key), ...]
    batch_size: 每次处理的账号数
    return: list of dict, 每个 dict 为主机信息
    """
    all_hosts = []

    for i in range(0, len(accounts), batch_size):
        batch_accounts = accounts[i:i+batch_size]
        for access_key, secret_key in batch_accounts:
            session = boto3.Session(
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key
            )
            try:
                ec2_client = session.client('ec2', region_name='us-east-1')
                regions_resp = ec2_client.describe_regions()['Regions']
                all_regions = [r['RegionName'] for r in regions_resp]
            except Exception as e:
                print(f"AWS账号 {access_key} 获取区域失败: {e}")
                continue

            for region in all_regions:
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
                                all_hosts.append(host_info)
                except Exception as e:
                    print(f"AWS账号 {access_key} 区域 {region} 获取实例失败: {e}")
    return all_hosts
