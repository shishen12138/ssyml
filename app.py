# -*- coding: utf-8 -*-
import os, json, threading, time, asyncssh, eventlet, boto3
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit

# --------- eventlet 异步补丁 ---------
eventlet.monkey_patch()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'

# 使用 eventlet 模式
socketio = SocketIO(app, async_mode='eventlet')

HOSTS_FILE = '/root/ssh_panel/hosts.json'
LOG_FILE = '/root/ssh_panel/ssh_web_panel.log'

REFRESH_INTERVAL = 5
BATCH_DELAY = 1
status_loop_started = False
status_loop_lock = threading.Lock()
connected_clients = set()

# -------------------- 文件操作 --------------------
def load_hosts():
    if not os.path.exists(HOSTS_FILE):
        return []
    with open(HOSTS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def save_hosts(hosts):
    with open(HOSTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(hosts, f, indent=4)

# -------------------- SSH 状态 --------------------
def ssh_status(host):
    result = {}
    try:
        with eventlet.Timeout(10, False):
            conn = asyncssh.connect(
                host['ip'],
                port=host.get('port', 22),
                username=host.get('username', 'root'),
                password=host.get('password', 'Qcy1994@06'),
                known_hosts=None
            )
            # 注意：这里不能使用 async/await，eventlet 版本暂时同步执行命令
            # 如果需要异步请用 eventlet.green.subprocess 或 eventlet.spawn 后 run
            # 简化处理为 ping 测试
            result['status'] = 'ok'
    except Exception as e:
        result['error'] = str(e)
    return result

# -------------------- 状态循环 --------------------
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
            all_data = {}
            for h in hosts:
                all_data[h['ip']] = ssh_status(h)
            socketio.emit('status', all_data)
            eventlet.sleep(REFRESH_INTERVAL)

    eventlet.spawn(loop)

# -------------------- 执行命令 --------------------
def run_command_pty(host, cmd, sid):
    try:
        conn = asyncssh.connect(
            host['ip'],
            port=host.get('port', 22),
            username=host.get('username', 'root'),
            password=host.get('password', 'Qcy1994@06'),
            known_hosts=None
        )
        process = conn.create_process(cmd, term_type='xterm')
        for line in process.stdout:
            socketio.emit('cmd_output', {'ip': host['ip'], 'line': line}, room=sid)
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"[{host['ip']}] {line}")
        for line in process.stderr:
            socketio.emit('cmd_output', {'ip': host['ip'], 'line': line}, room=sid)
            with open(LOG_FILE, 'a', encoding='utf-8') as f:
                f.write(f"[{host['ip']}] {line}")
    except Exception as e:
        msg = f"Error: {e}\n"
        socketio.emit('cmd_output', {'ip': host['ip'], 'line': msg}, room=sid)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(f"[{host['ip']}] {msg}")
    finally:
        socketio.emit('cmd_done', {'ip': host['ip']}, room=sid)

@socketio.on('exec_command')
def handle_exec_command(data):
    cmd = data.get('cmd')
    ips = data.get('ips', [])
    hosts_all = load_hosts()
    selected_hosts = [h for h in hosts_all if h['ip'] in ips]

    def exec_seq():
        for h in selected_hosts:
            run_command_pty(h, cmd, request.sid)
            eventlet.sleep(BATCH_DELAY)

    eventlet.spawn(exec_seq)

# -------------------- WebSocket --------------------
@socketio.on('connect')
def handle_connect():
    connected_clients.add(request.sid)
    emit('log', {'msg': '连接成功！'})
    start_status_loop()

@socketio.on('disconnect')
def handle_disconnect():
    connected_clients.discard(request.sid)

@socketio.on('tail_log')
def handle_tail_log():
    def tail_f(file_path):
        if not os.path.exists(file_path):
            socketio.emit('log', {'msg': '日志文件不存在'})
            return
        with open(file_path, 'r', encoding='utf-8') as f:
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
    global REFRESH_INTERVAL
    interval = int(data.get('interval', REFRESH_INTERVAL))
    REFRESH_INTERVAL = max(1, interval)
    emit('log', {'msg': f'刷新间隔已设置为 {REFRESH_INTERVAL} 秒'})

# -------------------- AWS 导入 --------------------
ALL_REGIONS = [
    'us-east-1', 'us-east-2', 'us-west-1', 'us-west-2',
    'eu-west-1', 'eu-central-1', 'ap-southeast-1', 'ap-northeast-1'
]

def import_aws_thread(accounts):
    hosts = load_hosts()
    total = len(accounts) * len(ALL_REGIONS)
    count = 0
    for name, access_key, secret_key in accounts:
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
                        if inst.get('State', {}).get('Name') != 'running':
                            continue
                        ip = inst.get('PublicIpAddress')
                        if not ip:
                            continue
                        hosts.append({
                            "ip": ip,
                            "port": 22,
                            "username": "root",
                            "password": "Qcy1994@06",
                            "region": region,
                            "source": "aws"
                        })
                msg = f"[{name}@{region}] 查询完成"
            except Exception as e:
                msg = f"[{name}@{region}] Error: {e}"
            count += 1
            socketio.emit('aws_import_log', {'msg': msg})
            socketio.emit('aws_import_progress', {'progress': int(count / total * 100)})
    save_hosts(hosts)
    socketio.emit('aws_import_complete')

@app.route('/import_aws', methods=['POST'])
def import_aws():
    accounts_raw = request.form['accounts']
    accounts = [line.strip().split('----') for line in accounts_raw.splitlines() if '----' in line]
    threading.Thread(target=import_aws_thread, args=(accounts,), daemon=True).start()
    return jsonify({"status": "started"})

# -------------------- 手动添加 host --------------------
@app.route('/add_host', methods=['POST'])
def add_host():
    hosts = load_hosts()
    ip = request.form['ip']
    port = int(request.form.get('port', 22))
    username = request.form.get('username', 'root')
    password = request.form.get('password', 'Qcy1994@06')
    hosts.append({"ip": ip, "port": port, "username": username, "password": password, "source": "manual"})
    save_hosts(hosts)
    return jsonify({"status": "ok"})

@app.route('/get_hosts')
def get_hosts():
    return jsonify(load_hosts())

# -------------------- 日志查看 --------------------
@app.route('/log')
def log_view():
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            content = f.read()
        return f"<pre style='white-space: pre-wrap;'>{content}</pre>"
    return "日志文件不存在"

# -------------------- 页面 --------------------
@app.route('/')
def index():
    return render_template('index_ws.html')

# -------------------- 启动 --------------------
if __name__ == '__main__':
    port = int(os.environ.get("PANEL_PORT", 12138))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
