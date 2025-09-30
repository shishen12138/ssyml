import asyncio
import websockets
import psutil
import platform
import socket
import json
import time
import os
import subprocess
import uuid
import requests
import sys

# ---------------- 配置 ----------------
SERVER = "ws://47.236.6.215:9001"  # 控制端地址
REPORT_INTERVAL = 2                 # 上报间隔秒
TOKEN_FILE = "agent_token.txt"
PID_FILE = "/tmp/agent.pid"

# ---------------- 单实例运行 ----------------
def ensure_single_instance():
    if os.path.exists(PID_FILE):
        try:
            old_pid = int(open(PID_FILE).read())
            os.kill(old_pid, 0)  # 检查进程是否存在
            print(f"[agent] 已有运行中的实例 (pid={old_pid})，退出")
            sys.exit(0)
        except ProcessLookupError:
            pass  # 老 PID 不存在，继续运行
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

# ---------------- Token ----------------
def get_or_create_token():
    if os.path.exists(TOKEN_FILE):
        return open(TOKEN_FILE).read().strip()
    token = str(uuid.uuid4())
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    return token

AGENT_ID = get_or_create_token()

# ---------------- 工具函数 ----------------
def safe(func, default=None):
    try:
        return func()
    except Exception:
        return default

def get_uptime():
    return safe(lambda: int(time.time() - psutil.boot_time()), 0)

def get_lan_ip(retry=3, delay=1):
    for _ in range(retry):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            time.sleep(delay)
    return "unknown"

def get_public_ip(retry=3, delay=1):
    for _ in range(retry):
        try:
            return requests.get("https://api.ipify.org", timeout=2).text
        except:
            time.sleep(delay)
    return "unknown"

def get_sysinfo():
    cpu_percent = safe(lambda: psutil.cpu_percent(interval=0.5), 0)
    mem = safe(lambda: psutil.virtual_memory(), None)
    disk_info = []
    for d in safe(lambda: psutil.disk_partitions(), []):
        try:
            usage = psutil.disk_usage(d.mountpoint)
            disk_info.append({
                "mount": d.mountpoint,
                "total": usage.total,
                "used": usage.used,
                "percent": usage.percent
            })
        except:
            continue
    net = safe(lambda: psutil.net_io_counters(), None)
    procs = []
    try:
        for p in sorted(psutil.process_iter(["pid","name","cpu_percent","memory_percent"]),
                        key=lambda x: x.info["cpu_percent"], reverse=True)[:5]:
            procs.append(p.info)
    except:
        pass
    return {
        "type": "update",
        "agent_id": AGENT_ID,
        "hostname": safe(socket.gethostname, "unknown"),
        "os": safe(platform.platform, "unknown"),
        "public_ip": get_public_ip(),
        "lan_ip": get_lan_ip(),
        "cpu": cpu_percent,
        "memory": mem.percent if mem else 0,
        "disk": disk_info,
        "net": {"bytes_sent": net.bytes_sent, "bytes_recv": net.bytes_recv} if net else {"bytes_sent":0,"bytes_recv":0},
        "uptime": get_uptime(),
        "top5": procs
    }

# ---------------- 命令执行 ----------------
def exec_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    except Exception as e:
        return {"stdout":"", "stderr": str(e), "returncode": -1}

# ---------------- Agent 主逻辑 ----------------
async def run_agent():
    while True:
        try:
            async with websockets.connect(SERVER) as ws:
                # 注册
                await ws.send(json.dumps({"type": "register", "agent_id": AGENT_ID}))
                print(f"[agent] 已连接 server {SERVER}，ID={AGENT_ID}")

                # 定时上报
                async def reporter():
                    while True:
                        try:
                            info = get_sysinfo()
                            await ws.send(json.dumps(info))
                        except Exception as e:
                            print("[agent] reporter 错误:", e)
                        await asyncio.sleep(REPORT_INTERVAL)

                # 接收命令
                async def listener():
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            if data.get("type") == "exec":
                                cmd = data.get("cmd")
                                print(f"[agent] 执行命令: {cmd}")
                                res = exec_cmd(cmd)
                                await ws.send(json.dumps({
                                    "type": "cmd_result",
                                    "agent_id": AGENT_ID,
                                    "payload": res
                                }))
                        except Exception as e:
                            print("[agent] listener 错误:", e)

                await asyncio.gather(reporter(), listener())

        except Exception as e:
            print("[agent] 连接失败，重试中...", e)
            await asyncio.sleep(5)

# ---------------- 启动 ----------------
if __name__ == "__main__":
    ensure_single_instance()
    asyncio.run(run_agent())
