#!/usr/bin/env python3
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
import threading

# ---------------- 配置 ----------------
SERVER = "ws://47.236.6.215:9001"  # 控制端地址
REPORT_INTERVAL = 2                 # 上报间隔秒
TOKEN_FILE = "/root/agent_token.txt"
LOG_FILE = "/root/agent.log"
LOCK_FILE = "/tmp/agent.lock"

# ---------------- 单实例保护 ----------------
def check_single_instance():
    if os.path.exists(LOCK_FILE):
        try:
            with open(LOCK_FILE) as f:
                pid = int(f.read())
            os.kill(pid, 0)
            log(f"[agent] 已有运行实例 PID={pid}, 退出")
            return False
        except:
            pass
    with open(LOCK_FILE, "w") as f:
        f.write(str(os.getpid()))
    return True

# ---------------- 日志 ----------------
def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    try:
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except:
        pass

# ---------------- Token ----------------
def get_or_create_token():
    if os.path.exists(TOKEN_FILE):
        return open(TOKEN_FILE).read().strip()
    token = str(uuid.uuid4())
    with open(TOKEN_FILE, "w") as f:
        f.write(token)
    return token

AGENT_ID = get_or_create_token()

# ---------------- 系统信息 ----------------
def get_uptime():
    try:
        return int(time.time() - psutil.boot_time())
    except:
        return 0

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(2)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "unknown"

def get_public_ip():
    try:
        return requests.get("https://api.ipify.org", timeout=3).text
    except:
        return "unknown"

def get_sysinfo():
    try:
        cpu_percent = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        disk_info = []
        for d in psutil.disk_partitions():
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
        net = psutil.net_io_counters()
        procs = []
        for p in sorted(psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
                        key=lambda x: x.info["cpu_percent"], reverse=True)[:5]:
            procs.append(p.info)
        return {
            "type": "update",
            "agent_id": AGENT_ID,
            "hostname": socket.gethostname(),
            "os": platform.platform(),
            "public_ip": get_public_ip(),
            "lan_ip": get_lan_ip(),
            "cpu": cpu_percent,
            "memory": mem.percent,
            "disk": disk_info,
            "net": {"bytes_sent": net.bytes_sent, "bytes_recv": net.bytes_recv},
            "uptime": get_uptime(),
            "top5": procs
        }
    except Exception as e:
        log(f"[agent] 获取系统信息异常: {e}")
        return {"type": "update", "agent_id": AGENT_ID}

# ---------------- 命令执行 ----------------
def exec_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return {"stdout": result.stdout, "stderr": result.stderr, "returncode": result.returncode}
    except Exception as e:
        return {"stdout": "", "stderr": str(e), "returncode": -1}

# ---------------- Agent 主逻辑 ----------------
async def run_agent():
    retry_delay = 1
    while True:
        try:
            async with websockets.connect(
                SERVER,
                ping_interval=15,
                ping_timeout=15,
                close_timeout=5
            ) as ws:
                retry_delay = 1  # 重置延迟
                await ws.send(json.dumps({"type": "register", "agent_id": AGENT_ID}))
                log(f"[agent] 已连接 server {SERVER}，ID={AGENT_ID}")

                async def reporter():
                    while True:
                        try:
                            info = get_sysinfo()
                            await ws.send(json.dumps(info))
                        except Exception as e:
                            log(f"[agent] 上报失败: {e}")
                        await asyncio.sleep(REPORT_INTERVAL)

                async def listener():
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            if data.get("type") == "exec":
                                cmd = data.get("cmd")
                                log(f"[agent] 执行命令: {cmd}")
                                res = exec_cmd(cmd)
                                await ws.send(json.dumps({
                                    "type": "cmd_result",
                                    "agent_id": AGENT_ID,
                                    "payload": res
                                }))
                        except Exception as e:
                            log(f"[agent] 处理命令异常: {e}")

                await asyncio.gather(reporter(), listener(), return_exceptions=True)

        except Exception as e:
            log(f"[agent] 连接失败或异常，重试中... {e}")
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)  # 指数退避

# ---------------- 启动 ----------------
if __name__ == "__main__":
    if not check_single_instance():
        sys.exit(0)

    while True:
        try:
            asyncio.run(run_agent())
        except Exception as e:
            log(f"[agent] 异常退出: {e}")
            time.sleep(5)
