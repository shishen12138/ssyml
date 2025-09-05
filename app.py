# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit
import asyncio
import asyncssh
import json
import os
import eventlet
import threading
import subprocess

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

# -------------------- 后台实时刷新 --------------------
def start_status_loop():
    global status_loop_started
    with status_loop_lock:
        if status_loop_started:
            return
        status_loop_started = True

    BATCH_SIZE = 5  # 每批主机数，可调

    async def worker_loop():
        while True:
            if not connected_clients:
                await asyncio.sleep(1)
                continue

            hosts = load_hosts()
            for i in range(0, len(hosts), BATCH_SIZE):
                batch = hosts[i:i+BATCH_SIZE]
                tasks = [async_ssh_connect(h) for h in batch]
                results = await asyncio.gather(*tasks)
                for h, r in zip(batch, results):
                    socketio.emit('status', {h['ip']: r})
            await asyncio.sleep(REFRESH_INTERVAL_DEFAULT)

    def loop_func():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(worker_loop())

    eventlet.spawn(loop_func)

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

    async def send_cmd_batch(batch):
        results = await asyncio.gather(*(async_ssh_connect(h) for h in batch))
        for h, r in zip(batch, results):
            socketio.emit('cmd_result', {h['ip']: r})

    def thread_func():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        BATCH_SIZE = 5
        for i in range(0, len(selected_hosts), BATCH_SIZE):
            batch = selected_hosts[i:i+BATCH_SIZE]
            try:
                loop.run_until_complete(send_cmd_batch(batch))
            except Exception as e:
                socketio.emit('log', {'msg': f"命令执行错误: {e}"})

    eventlet.spawn(thread_func)

# -------------------- AWS 导入 --------------------
@app.route('/import_aws', methods=['POST'])
def import_aws_route():
    accounts_file = '/tmp/aws_accounts.txt'
    with open(accounts_file, 'w') as f:
        f.write(request.form['accounts'])

    # 调用独立 AWS 导入脚本，不在 Flask 线程中执行
    subprocess.Popen(['python3', '/root/ssh_panel/aws_importer.py', accounts_file])

    return jsonify({"status": "ok", "msg": "AWS 导入已启动，导入日志在 /root/ssh_panel/aws_import.log"})

# -------------------- 其他路由 --------------------
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

@app.route('/log')
def log_route():
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
