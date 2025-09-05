import os
import json
import time
import threading
import psutil
import paramiko
import boto3
from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

HOSTS_FILE = os.path.join(os.path.dirname(__file__), 'hosts.json')

# ---------- 读取/保存主机信息 ----------
def load_hosts():
    if not os.path.exists(HOSTS_FILE):
        return []
    with open(HOSTS_FILE, 'r') as f:
        return json.load(f)

def save_hosts(hosts):
    with open(HOSTS_FILE, 'w') as f:
        json.dump(hosts, f, indent=2)

# ---------- SSH 执行命令 ----------
def ssh_exec(ip, port, username, password, cmd):
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, port=int(port), username=username, password=password, timeout=5)
        stdin, stdout, stderr = client.exec_command(cmd)
        out = stdout.read().decode()
        err = stderr.read().decode()
        client.close()
        return out + err
    except Exception as e:
        return f"连接失败: {e}"

# ---------- CPU/内存/磁盘/网络/延迟/前五进程 ----------
def get_host_info():
    info = {
        'cpu': psutil.cpu_percent(interval=1),
        'mem': psutil.virtual_memory().percent,
        'disk': psutil.disk_usage('/').percent,
        'net': psutil.net_io_counters(),
        'processes': [(p.info['name'], p.info['cpu_percent'], p.info['memory_percent']) 
                      for p in psutil.process_iter(['name','cpu_percent','memory_percent'])]
    }
    return info

# ---------- Flask 路由 ----------
@app.route('/')
def index():
    hosts = load_hosts()
    return render_template('index.html', hosts=hosts)

# ---------- 高级日志功能 ----------
LOG_FILE = os.environ.get("LOG_FILE", "/var/log/ssh_web_panel.log")

@app.route('/logs')
def view_logs():
    keyword = request.args.get('keyword','')
    if os.path.exists(LOG_FILE):
        with open(LOG_FILE, 'r') as f:
            lines = f.readlines()
        if keyword:
            lines = [line for line in lines if keyword.lower() in line.lower()]
        return jsonify({"log": "".join(lines)})
    else:
        return jsonify({"log": "日志文件不存在"})

@app.route('/logs/download')
def download_logs():
    if os.path.exists(LOG_FILE):
        from flask import send_file
        return send_file(LOG_FILE, as_attachment=True)
    else:
        return "日志文件不存在"

# ---------- 启动 ----------
if __name__ == "__main__":
    port = int(os.environ.get("PANEL_PORT", 8080))
    host = '0.0.0.0'
    app.run(host=host, port=port, debug=False)
