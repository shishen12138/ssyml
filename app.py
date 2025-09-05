# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import asyncio
import asyncssh
import boto3
import json
import os
import eventlet
import threading

eventlet.monkey_patch()  # async 与 Flask-SocketIO 兼容

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='eventlet')

HOSTS_FILE = '/root/ssh_panel/hosts.json'
LOG_FILE = '/root/ssh_panel/ssh_web_panel.log'

REFRESH_INTERVAL_DEFAULT = 5
status_loop_started = False
status_loop_lock = threading.Lock()
connected_clients = set()  # 当前连接客户端 session_id

# -------------------- 文件操作 --------------------
def load_hosts():
    if not os.path.exists(HOSTS_FILE):
        return []
    with open(HOSTS_FILE, 'r') as f:
        return json.load(f)

def save_hosts(hosts):
    with open(HOSTS_FILE, 'w') as f:
        json.dump(hosts, f, indent=4)

# -------------------- 异步 SSH --------------------
async def async_ssh_connect(host):
    result = {}
    try:
        conn = await asyncssh.connect(
            host['ip'],
            port=host.get('port', 22),
            username=host.get('username', 'root'),
            password=host.get('password', ''),
            known_hosts=None,
            connect_timeout=5
        )

        cpu = await (await conn.create_process("top -bn1 | grep 'Cpu(s)' | awk '{print $2+$4}'")).stdout.read()
        memory = await (await conn.create_process("free -m | awk 'NR==2{printf \"%.2f\", $3*100/$2 }'")).stdout.read()
        disk = await (await conn.create_process("df -h / | awk 'NR==2 {print $5}'")).stdout.read()
        net_info = await (await conn.create_process(
            "cat /proc/net/dev | grep -v lo | awk 'NR>1{print $1,$2,$10}' | head -n1"
        )).stdout.read()
        if net_info:
            parts = net_info.split()
            net_rx = parts[1]
            net_tx = parts[2]
        else:
            net_rx = net_tx = 'N/A'
        latency = await (await conn.create_process("ping -c 1 8.8.8.8 | tail -1 | awk -F '/' '{print $5}'")).stdout.read()
        top_processes = await (await conn.create_process("ps aux --sort=-%cpu | head -n 6")).stdout.read()

        result.update({
            'cpu': cpu.strip(),
            'memory': memory.strip(),
            'disk': disk.strip(),
            'net_rx': net_rx,
            'net_tx': net_tx,
            'latency': latency.strip(),
            'top_processes': top_processes.strip().split('\n')
        })
        conn.close()
    except Exception as e:
        result['error'] = str(e)
    return result

async def async_exec_command(host, cmd):
    try:
        conn = await asyncssh.connect(
            host['ip'],
            port=host.get('port', 22),
            username=host.get('username', 'root'),
            password=host.get('password', ''),
            known_hosts=None,
            connect_timeout=5
        )
        process = await conn.create_process(cmd)
        out = await process.stdout.read()
        err = await process.stderr.read()
        conn.close()
        return out + err
    except Exception as e:
        return str(e)

# -------------------- 后台实时刷新 --------------------
def start_status_loop():
    global status_loop_started
    with status_loop_lock:
        if status_loop_started:
            return
        status_loop_started = True

    def loop():
        while True:
            if not connected_clients:
                eventlet.sleep(1)
                continue
            hosts = load_hosts()
            async def get_status():
                tasks = [async_ssh_connect(h) for h in hosts]
                results = await asyncio.gather(*tasks)
                all_data = {h['ip']: r for h, r in zip(hosts, results)}
                socketio.emit('status', all_data)
            eventlet.spawn(asyncio.run, get_status())
            eventlet.sleep(REFRESH_INTERVAL_DEFAULT)
    eventlet.spawn(loop)

# -------------------- WebSocket --------------------
@socketio.on('connect')
def handle_connect():
    emit('log', {'msg': '连接成功！'})
    connected_clients.add(request.sid)
    start_status_loop()

@socketio.on('disconnect')
def handle_disconnect():
    connected_clients.discard(request.sid)

@socketio.on('exec_command')
def handle_exec_command(data):
    cmd = data.get('cmd')
    ips = data.get('ips', [])
    hosts = load_hosts()
    selected_hosts = [h for h in hosts if h['ip'] in ips]

    async def send_cmd():
        results = await asyncio.gather(*(async_exec_command(h, cmd) for h in selected_hosts))
        socketio.emit('cmd_result', {h['ip']: r for h, r in zip(selected_hosts, results)})
    eventlet.spawn(asyncio.run, send_cmd())

@socketio.on('tail_log')
def handle_tail_log():
    def tail_f(file_path):
        if not os.path.exists(file_path):
            socketio.emit('log', {'msg': '日志文件不存在'})
            return
        with open(file_path, 'r') as f:
            f.seek(0, os.SEEK_END)
            while True:
                line = f.readline()
                if not line:
                    eventlet.sleep(0.5)
                    continue
                socketio.emit('log', {'msg': line.strip()})
    eventlet.spawn(tail_f, LOG_FILE)

@socketio.on('set_interval')
def handle_set_interval(data):
    global REFRESH_INTERVAL_DEFAULT
    interval = int(data.get('interval', REFRESH_INTERVAL_DEFAULT))
    REFRESH_INTERVAL_DEFAULT = max(1, interval)
    emit('log', {'msg': f'刷新间隔已设置为 {REFRESH_INTERVAL_DEFAULT} 秒'})

# -------------------- 路由 --------------------
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
    socketio.emit('status', {ip: {'cpu': '-', 'memory': '-', 'disk': '-', 'net_rx': '-', 'net_tx': '-', 'latency': '-', 'top_processes': ['手动添加主机'], 'error': ''}})
    return jsonify({"status":"ok"})

@app.route('/import_aws', methods=['POST'])
def import_aws():
    hosts = load_hosts()
    accounts_raw = request.form['accounts']
    accounts = []
    for line in accounts_raw.splitlines():
        parts = line.strip().split('----')
        if len(parts) >= 3:
            access_key = parts[1].strip()
            secret_key = parts[2].strip()
            accounts.append((access_key, secret_key))

    ALL_REGIONS = [
        'us-east-1','us-east-2','us-west-1','us-west-2',
        'eu-west-1','eu-central-1','ap-southeast-1','ap-northeast-1'
    ]

    new_hosts = []
    for idx, (access_key, secret_key) in enumerate(accounts, 1):
        socketio.emit('log', {'msg': f"[AWS] 开始导入账号 {idx}/{len(accounts)}..."})
        for region in ALL_REGIONS:
            socketio.emit('log', {'msg': f"[AWS] 连接区域 {region} ..."})

            try:
                ec2 = boto3.client(
                    'ec2',
                    aws_access_key_id=access_key,
                    aws_secret_access_key=secret_key,
                    region_name=region
                )
                reservations = ec2.describe_instances().get('Reservations', [])
                socketio.emit('log', {'msg': f"[AWS] 区域 {region} 共 {len(reservations)} 个预订..."})

                for res in reservations:
                    for inst in res.get('Instances', []):
                        ip = inst.get('PublicIpAddress') or inst.get('PrivateIpAddress')
                        if ip and ip not in [h['ip'] for h in hosts]:
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
                            socketio.emit('log', {'msg': f"[AWS] 添加实例 {ip} 到面板"})
            except Exception as e:
                socketio.emit('log', {'msg': f"[AWS] 区域 {region} 错误: {e}"})

    save_hosts(hosts)
    socketio.emit('status', {h['ip']: {'cpu':'-','memory':'-','disk':'-','net_rx':'-','net_tx':'-','latency':'-','top_processes':['AWS 主机导入'], 'error':''} for h in new_hosts})
    socketio.emit('log', {'msg': f"[AWS] 导入完成，共添加 {len(new_hosts)} 台主机"})
    return jsonify({"status":"ok","added":len(new_hosts)})

@app.route('/log')
def log():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            content = f.read()
        return "<pre style='white-space: pre-wrap;'>"+content+"</pre>"
    return "日志文件不存在"

@app.route('/')
def index():
    return render_template('index_ws.html')

# -------------------- 启动 --------------------
if __name__ == '__main__':
    port = int(os.environ.get("PANEL_PORT", 12138))
    host = '0.0.0.0'
    socketio.run(app, host=host, port=port, debug=False)
