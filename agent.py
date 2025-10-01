#!/usr/bin/env python3
import asyncio, websockets, psutil, platform, socket, json, time, subprocess, uuid, requests, os

SERVER = "ws://47.236.6.215:9002"  # 后端地址
REPORT_INTERVAL = 0.5

# 生成或读取 agent_id
TOKEN_FILE = "/tmp/t.txt"
try:
    AGENT_ID = open(TOKEN_FILE).read().strip()
except:
    AGENT_ID = str(uuid.uuid4())
    try: open(TOKEN_FILE, "w").write(AGENT_ID)
    except: pass

# 网络流量记录
_net_last = {"s": 0, "r": 0, "t": time.time()}

def get_uptime():
    try: return int(time.time() - psutil.boot_time())
    except: return 0

def get_lan_ip():
    try:
        s = socket.socket()
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except: return "unknown"

def get_public_ip():
    try: return requests.get("https://api.ipify.org", timeout=3).text
    except: return "unknown"

def get_sysinfo():
    global _net_last
    try:
        now = time.time()
        cpu = psutil.cpu_percent(0.5)
        mem = psutil.virtual_memory().percent
        disk = [{"mount": d.mountpoint, "total": psutil.disk_usage(d.mountpoint).total,
                 "used": psutil.disk_usage(d.mountpoint).used,
                 "percent": psutil.disk_usage(d.mountpoint).percent} for d in psutil.disk_partitions()]

        net = psutil.net_io_counters()
        dt = now - _net_last["t"]
        up_speed = (net.bytes_sent - _net_last["s"]) / dt if dt > 0 else 0
        down_speed = (net.bytes_recv - _net_last["r"]) / dt if dt > 0 else 0
        _net_last = {"s": net.bytes_sent, "r": net.bytes_recv, "t": now}

        top5 = [p.info for p in sorted(psutil.process_iter(["pid","name","cpu_percent","memory_percent"]),
                                      key=lambda x: x.info.get("cpu_percent",0), reverse=True)[:5]]

        return {
            "type": "update",
            "agent_id": AGENT_ID,
            "hostname": socket.gethostname(),
            "os": platform.platform(),
            "public_ip": get_public_ip(),
            "lan_ip": get_lan_ip(),
            "cpu": cpu,
            "memory": mem,
            "disk": disk,
            "net": {"bytes_sent": net.bytes_sent, "bytes_recv": net.bytes_recv, "up_speed": up_speed, "down_speed": down_speed},
            "uptime": get_uptime(),
            "top5": top5
        }
    except:
        return {"type": "update", "agent_id": AGENT_ID}

def exec_cmd(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
        return {"stdout": r.stdout, "stderr": r.stderr, "returncode": r.returncode}
    except:
        return {"stdout": "", "stderr": "err", "returncode": -1}

async def agent_loop():
    retry_delay = 1
    while True:
        try:
            async with websockets.connect(S, ping_interval=30, ping_timeout=30) as ws:
                # 注册
                try:
                    await ws.send(json.dumps({"type": "register", "agent_id": AGENT_ID}))
                    print(f"[Agent] 已注册 ID={AGENT_ID}")
                except Exception as e:
                    print("注册失败:", e)

                async def reporter():
                    while True:
                        try:
                            await ws.send(json.dumps(get_sysinfo()))
                        except: pass
                        await asyncio.sleep(REPORT_INTERVAL)

                async def listener():
                    while True:
                        try:
                            msg = await ws.recv()
                            data = json.loads(msg)
                            if data.get("type") == "exec":
                                cmd = data.get("cmd")
                                res = await asyncio.to_thread(exec_cmd, cmd)
                                try: await ws.send(json.dumps({"type": "cmd_result", "agent_id": AGENT_ID, "payload": res}))
                                except: pass
                                # 执行完命令后立即上报一次状态
                                try: await ws.send(json.dumps(get_sysinfo()))
                                except: pass
                        except: await asyncio.sleep(0.1)

                await asyncio.gather(reporter(), listener())

        except: 
            await asyncio.sleep(retry_delay)
            retry_delay = min(retry_delay * 2, 60)

if __name__ == "__main__":
    try: asyncio.run(agent_loop())
    except: pass
