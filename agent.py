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

SERVER = "ws://47.236.6.215:9001"
REPORT_INTERVAL = 0.5
TOKEN_FILE = "agent_token.txt"

# ---------------- Token ----------------
def get_or_create_token():
    try:
        if os.path.exists(TOKEN_FILE):
            return open(TOKEN_FILE).read().strip()
        token = str(uuid.uuid4())
        with open(TOKEN_FILE, "w") as f:
            f.write(token)
        return token
    except:
        return str(uuid.uuid4())

AGENT_ID = get_or_create_token()

# ---------------- 系统信息 ----------------
def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
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

_last_net = {"bytes_sent": 0, "bytes_recv": 0, "time": time.time()}

def get_sysinfo():
    global _last_net
    try:
        cpu = psutil.cpu_percent(interval=0.2)
    except:
        cpu = 0
    try:
        mem = psutil.virtual_memory().percent
    except:
        mem = 0

    disks = []
    try:
        for d in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(d.mountpoint)
                disks.append({"mount": d.mountpoint, "total": usage.total, "used": usage.used, "percent": usage.percent})
            except:
                continue
    except:
        pass

    try:
        net = psutil.net_io_counters()
        now = time.time()
        elapsed = now - _last_net["time"] if _last_net["time"] > 0 else 1
        up_speed = (net.bytes_sent - _last_net["bytes_sent"]) / elapsed
        down_speed = (net.bytes_recv - _last_net["bytes_recv"]) / elapsed
        _last_net = {"bytes_sent": net.bytes_sent, "bytes_recv": net.bytes_recv, "time": now}
    except:
        up_speed, down_speed = 0, 0
        net = type("obj", (), {"bytes_sent": 0, "bytes_recv": 0})()

    top5 = []
    try:
        for p in sorted(psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]),
                        key=lambda x: x.info.get("cpu_percent", 0), reverse=True)[:5]:
            top5.append(p.info)
    except:
        pass

    try:
        uptime = int(time.time() - psutil.boot_time())
    except:
        uptime = 0

    return {
        "type": "update",
        "agent_id": AGENT_ID,
        "hostname": socket.gethostname(),
        "os": platform.platform(),
        "public_ip": get_public_ip(),
        "lan_ip": get_lan_ip(),
        "cpu": cpu,
        "memory": mem,
        "disk": disks,
        "process_top5": top5,
        "net": {
            "up_speed": round(up_speed, 2),
            "down_speed": round(down_speed, 2),
            "total_sent": getattr(net, "bytes_sent", 0),
            "total_recv": getattr(net, "bytes_recv", 0)
        },
        "uptime": uptime,
    }

# ---------------- 执行任务 ----------------
def exec_cmd(cmd):
    try:
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return {"stdout": res.stdout, "stderr": res.stderr, "returncode": res.returncode}
    except:
        return {"stdout": "", "stderr": "", "returncode": -1}

# ---------------- 主逻辑 ----------------
async def run_agent():
    while True:
        try:
            async with websockets.connect(SERVER, ping_interval=None) as ws:
                await ws.send(json.dumps({"type": "register", "agent_id": AGENT_ID}))

                async def reporter():
                    while True:
                        try:
                            await ws.send(json.dumps(get_sysinfo()))
                        except:
                            pass
                        await asyncio.sleep(REPORT_INTERVAL)

                async def listener():
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            if data.get("type") == "exec":
                                cmd = data.get("cmd", "")
                                res = exec_cmd(cmd)
                                await ws.send(json.dumps({"type": "cmd_result", "agent_id": AGENT_ID, "payload": res}))
                        except:
                            pass

                await asyncio.gather(reporter(), listener())

        except:
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(run_agent())
