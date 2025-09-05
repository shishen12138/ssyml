# -*- coding: utf-8 -*-
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO
import asyncio, asyncssh, json, os, eventlet, threading
from aws_helper import import_aws_instances

eventlet.monkey_patch()

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, async_mode='eventlet')

HOSTS_FILE = '/root/ssh_panel/hosts.json'
REFRESH_INTERVAL_DEFAULT = 5
status_loop_started = False
status_loop_lock = threading.Lock()
connected_clients = set()

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
        top_processes = await (await conn.create_process("ps aux --sort=-%cpu | head -n 6")).stdout.read()

        result.update({
            'cpu': cpu.strip(),
            'memory': memory.strip(),
            'disk': disk.strip(),
            'status': '在线',
            'top_processes': top_processes.strip().split('\n')
        })
        conn.close()
    except Exception as e:
        result['status'] = '离线'
        result['top_processes'] = ['-']
        result['cpu'] = result['memory'] = result['disk'] = 0
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
        output = ''
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            output += line
            socketio.emit('cmd_result', {host['ip']: line.strip()})
        await process.wait()
        conn.close()
        return output
    except Exception as e:
        socketio.emit('cmd_result', {host['ip']: f"ERROR: {e}"})
        return str(e)

# -------------------- 后台刷新 --------------------
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
                all_data = {h['ip']: {**h, **r} for h, r in zip(hosts, results)}
                socketio.emit('status', all_data)
            eventlet.spawn(asyncio.run, get_status())
            eventlet.sleep(REFRESH_INTERVAL_DEFAULT)
    eventlet.spawn(loop)

# -------------------- WebSocket --------------------
@socketio.on('connect')
def handle_connect():
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

    def thread_func():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        async def main():
            tasks = [async_exec_command(h, cmd) for h in selected_hosts]
            await asyncio.gather(*tasks)
        loop.run_until_complete(main())
    eventlet.spawn(thread_func)

# -------------------- 路由 --------------------
@app.route('/')
def index():
    return render_template('index_ws.html')

@app.route('/add_host', methods=['POST'])
def add_host():
    hosts = load_hosts()
    ip = request.form['ip']
    username = request.form.get('username', 'root')
    password = request.form.get('password', 'Qcy1994@06')
    hosts.append({
        "ip": ip,
        "port": 22,
        "username": username,
        "password": password,
        "source": "manual"
    })
    save_hosts(hosts)
    return jsonify({"status":"ok"})

@app.route('/import_aws', methods=['POST'])
def import_aws():
    accounts_raw = request.form['accounts']

    def import_thread():
        hosts = load_hosts()
        accounts = []
        for line in accounts_raw.splitlines():
            parts = line.strip().split('----')
            if len(parts) >= 3:
                accounts.append((parts[1].strip(), parts[2].strip()))
        new_hosts = import_aws_instances(accounts, batch_size=5)
        hosts.extend(new_hosts)
        save_hosts(hosts)
        socketio.emit('status', {h['ip']: h for h in hosts})

    threading.Thread(target=import_thread).start()
    return jsonify({"status":"ok", "msg":"AWS 导入任务已启动"})


# -------------------- 启动 --------------------
if __name__ == '__main__':
    port = int(os.environ.get("PANEL_PORT", 12138))
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
