from flask import Flask, render_template, request, jsonify
import paramiko
import boto3
import json
import os
import threading
import time

app = Flask(__name__)
HOSTS_FILE = 'hosts.json'
REFRESH_INTERVAL = 5  # 秒

# -------------------- 文件操作 --------------------
def load_hosts():
    if not os.path.exists(HOSTS_FILE):
        return []
    with open(HOSTS_FILE, 'r') as f:
        return json.load(f)

def save_hosts(hosts):
    with open(HOSTS_FILE, 'w') as f:
        json.dump(hosts, f, indent=4)

# -------------------- SSH 连接 --------------------
def ssh_connect(host):
    ip = host['ip']
    port = host.get('port', 22)
    username = host.get('username', 'root')
    password = host.get('password', 'Qcy1994@06')
    result = {}
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(ip, port=port, username=username, password=password, timeout=5)

        # CPU
        stdin, stdout, stderr = ssh.exec_command("top -bn1 | grep 'Cpu(s)' | awk '{print $2+$4}'")
        result['cpu'] = stdout.read().decode().strip()

        # 内存
        stdin, stdout, stderr = ssh.exec_command("free -m | awk 'NR==2{printf \"%.2f\", $3*100/$2 }'")
        result['memory'] = stdout.read().decode().strip()

        # 磁盘
        stdin, stdout, stderr = ssh.exec_command("df -h / | awk 'NR==2 {print $5}'")
        result['disk'] = stdout.read().decode().strip()

        # 网络流量（eth0）
        stdin, stdout, stderr = ssh.exec_command("cat /proc/net/dev | grep eth0")
        net_info = stdout.read().decode().strip().split()
        if len(net_info) >= 17:
            rx = int(net_info[1])
            tx = int(net_info[9])
            result['net_rx'] = str(rx)
            result['net_tx'] = str(tx)
        else:
            result['net_rx'] = result['net_tx'] = 'N/A'

        # 延迟
        stdin, stdout, stderr = ssh.exec_command("ping -c 1 8.8.8.8 | tail -1 | awk -F '/' '{print $5}'")
        result['latency'] = stdout.read().decode().strip()

        # 前五进程
        stdin, stdout, stderr = ssh.exec_command("ps aux --sort=-%cpu | head -n 6")
        result['top_processes'] = stdout.read().decode().strip().split('\n')

        ssh.close()
    except Exception as e:
        result['error'] = str(e)
    return result

# -------------------- 后端路由 --------------------
@app.route('/')
def index():
    hosts = load_hosts()
    return render_template('index.html', hosts=hosts)

# 添加手动主机
@app.route('/add_host', methods=['POST'])
def add_host():
    hosts = load_hosts()
    ip = request.form['ip']
    port = int(request.form.get('port', 22))
    username = request.form.get('username', 'root')
    password = request.form.get('password', 'Qcy1994@06')
    hosts.append({
        "ip": ip,
        "port": port,
        "username": username,
        "password": password,
        "source": "manual"
    })
    save_hosts(hosts)
    return jsonify({"status":"ok"})

# AWS 导入实例
@app.route('/import_aws', methods=['POST'])
def import_aws():
    hosts = load_hosts()
    accounts_raw = request.form['accounts']  # 每行 AccessKey,SecretKey
    accounts = [line.strip().split(',') for line in accounts_raw.splitlines() if ',' in line]
    ALL_REGIONS = [
        'us-east-1','us-east-2','us-west-1','us-west-2',
        'eu-west-1','eu-central-1','ap-southeast-1','ap-northeast-1'
    ]
    for access_key, secret_key in accounts:
        for region in ALL_REGIONS:
            try:
                ec2 = boto3.client(
                    'ec2',
                    aws_access_key_id=access_key.strip(),
                    aws_secret_access_key=secret_key.strip(),
                    region_name=region
                )
                reservations = ec2.describe_instances()['Reservations']
                for res in reservations:
                    for inst in res['Instances']:
                        ip = inst.get('PublicIpAddress') or inst.get('PrivateIpAddress')
                        if ip:
                            hosts.append({
                                "ip": ip,
                                "port": 22,
                                "username": "root",
                                "password": "Qcy1994@06",
                                "region": region,
                                "source": "aws"
                            })
            except Exception as e:
                print(f"[{region}] Error: {e}")
    save_hosts(hosts)
    return jsonify({"status":"ok"})

# 执行自定义命令
@app.route('/exec', methods=['POST'])
def exec_command():
    hosts = load_hosts()
    ips = request.json.get('ips', [])
    cmd = request.json.get('cmd', '')
    results = {}
    selected_hosts = [h for h in hosts if h['ip'] in ips]

    threads = []
    def worker(host):
        res = ssh_connect(host)
        if 'error' in res:
            results[host['ip']] = res['error']
        else:
            try:
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                ssh.connect(host['ip'], port=host.get('port',22), username=host.get('username','root'), password=host.get('password','Qcy1994@06'), timeout=5)
                stdin, stdout, stderr = ssh.exec_command(cmd)
                out = stdout.read().decode().strip()
                ssh.close()
                results[host['ip']] = out
            except Exception as e:
                results[host['ip']] = str(e)
    for h in selected_hosts:
        t = threading.Thread(target=worker,args=(h,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    return jsonify(results)

# 获取实时监控数据
@app.route('/status')
def status():
    hosts = load_hosts()
    all_data = {}
    threads = []
    def worker(host):
        all_data[host['ip']] = ssh_connect(host)
    for host in hosts:
        t = threading.Thread(target=worker, args=(host,))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    return jsonify(all_data)

# ---------- 启动 ----------
if __name__ == "__main__":
    port = int(os.environ.get("PANEL_PORT", 8080))
    host = '0.0.0.0'
    app.run(host=host, port=port, debug=False)
