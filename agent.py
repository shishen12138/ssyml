#!/usr/bin/env python3
import asyncio, websockets, psutil, platform, socket, json, time, subprocess, uuid, requests

SERVER = "ws://47.236.6.215:9002"   # 控制端地址
REPORT_INTERVAL = 0.5                 # 上报间隔

# 生成唯一 ID
try:
    AGENT_ID = open("/tmp/agent_id.txt").read().strip()
except:
    AGENT_ID = str(uuid.uuid4())
    try: open("/tmp/agent_id.txt","w").write(AGENT_ID)
    except: pass

_net_last = {"s":0, "r":0, "t":time.time()}

def get_public_ip():
    try: return requests.get("http://ifconfig.me", timeout=3).text.strip()
    except: return None

def get_lan_ip():
    try: return socket.gethostbyname(socket.gethostname())
    except: return None

def get_sysinfo():
    global _net_last
    now = time.time()
    try:
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent
        disk = []
        for d in psutil.disk_partitions():
            try:
                du = psutil.disk_usage(d.mountpoint)
                disk.append({"mount": d.mountpoint, "total": du.total,
                             "used": du.used, "percent": du.percent})
            except: pass

        net = psutil.net_io_counters()
        dt = now - _net_last["t"]
        up_speed = (net.bytes_sent - _net_last["s"]) / dt if dt > 0 else 0
        down_speed = (net.bytes_recv - _net_last["r"]) / dt if dt > 0 else 0
        _net_last = {"s": net.bytes_sent, "r": net.bytes_recv, "t": now}

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
            "net": {"bytes_sent": net.bytes_sent, "bytes_recv": net.bytes_recv,
                    "up_speed": up_speed, "down_speed": down_speed},
            "uptime": int(time.time() - psutil.boot_time()),
        }
    except Exception as e:
        return {"type": "update", "agent_id": AGENT_ID, "error": str(e)}

def exec_cmd(cmd):
    try:
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, timeout=15)
        return {"ok": True, "output": out.decode(errors="ignore")}
    except Exception as e:
        return {"ok": False, "error": str(e)}

async def agent_loop():
    while True:
        try:
            async with websockets.connect(SERVER, ping_interval=10, ping_timeout=10) as ws:
                print(f"[Agent] 已连接控制端 {SERVER}")
                await ws.send(json.dumps({"type": "register", "agent_id": AGENT_ID}))
                print(f"[Agent] 已注册 ID={AGENT_ID}")
                await ws.send(json.dumps(get_sysinfo()))

                async def reporter():
                    while True:
                        info = get_sysinfo()
                        await ws.send(json.dumps(info))
                        print(f"[Agent] 周期上报: CPU={info.get('cpu')} MEM={info.get('memory')}")
                        await asyncio.sleep(REPORT_INTERVAL)

                async def listener():
                    async for msg in ws:
                        data = json.loads(msg)
                        if data.get("type") == "exec":
                            cmd = data.get("cmd")
                            print(f"[Agent] 收到命令: {cmd}")
                            res = await asyncio.to_thread(exec_cmd, cmd)
                            await ws.send(json.dumps({
                                "type": "cmd_result",
                                "agent_id": AGENT_ID,
                                "payload": res
                            }))
                            await ws.send(json.dumps(get_sysinfo()))

                # ⚡ 如果 reporter 或 listener 出错，整个连接退出，触发重连
                await asyncio.gather(reporter(), listener())

        except Exception as e:
            print(f"[Agent] 连接断开或失败: {e}，3秒后重试")
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(agent_loop())
