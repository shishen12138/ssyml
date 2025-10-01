#!/usr/bin/env python3
import asyncio, websockets, psutil, platform, socket, json, time, subprocess, uuid, requests

SERVER = "ws://47.236.6.215:9002"
REPORT_INTERVAL = 1

# agent ID 保持不变
try:
    AGENT_ID = open("/root/agent_id.txt").read().strip()
except:
    AGENT_ID = str(uuid.uuid4())
    open("/root/agent_id.txt", "w").write(AGENT_ID)

_net_last = {"s": psutil.net_io_counters().bytes_sent,
             "r": psutil.net_io_counters().bytes_recv,
             "t": time.time()}

def get_public_ip():
    try:
        return requests.get("http://ifconfig.me", timeout=3).text.strip()
    except:
        return "N/A"

def get_lan_ip():
    try:
        return socket.gethostbyname(socket.gethostname())
    except:
        return "N/A"

def top_processes(n=5):
    procs = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            procs.append(p.info)
        except:
            pass
    procs.sort(key=lambda x: x.get("cpu_percent", 0), reverse=True)
    return procs[:n]

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
                disk.append({
                    "mount": d.mountpoint,
                    "total": du.total,
                    "used": du.used,
                    "percent": du.percent
                })
            except:
                pass

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
            "net": {
                "bytes_sent": net.bytes_sent,
                "bytes_recv": net.bytes_recv,
                "up_speed": up_speed,
                "down_speed": down_speed
            },
            "processes": top_processes(5),
            "uptime": int(time.time() - psutil.boot_time()),
        }
    except Exception as e:
        return {"type": "update", "agent_id": AGENT_ID, "error": str(e)}

def exec_cmd_background(cmd):
    """后台执行命令，不阻塞 agent"""
    try:
        subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"cmd": cmd, "output": "已在后台执行"}
    except Exception as e:
        return {"cmd": cmd, "error": str(e)}

async def run_cmd_async(ws, cmd):
    """后台异步执行命令并回报下发状态"""
    result = exec_cmd_background(cmd)
    try:
        await ws.send(json.dumps({
            "type": "cmd_result",
            "agent_id": AGENT_ID,
            "payload": result
        }))
        # 执行完命令立即更新状态
        await ws.send(json.dumps(get_sysinfo()))
    except Exception as e:
        print(f"[Agent] 发送命令结果失败: {e}")

async def agent_loop():
    while True:
        try:
            async with websockets.connect(SERVER, ping_interval=10, ping_timeout=10) as ws:
                print(f"[Agent] 已连接控制端 {SERVER}")
                await ws.send(json.dumps({"type": "register", "agent_id": AGENT_ID}))
                print(f"[Agent] 已注册 ID={AGENT_ID}")

                async def reporter():
                    while True:
                        info = get_sysinfo()
                        await ws.send(json.dumps(info))
                        await asyncio.sleep(REPORT_INTERVAL)

                async def listener():
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            print(f"[Agent] 收到消息: {data}")
                            if data.get("type") == "exec":
                                # 如果没有 agents 字段，则默认本 agent 执行
                                agents_list = data.get("agents", [AGENT_ID])
                                if AGENT_ID not in agents_list:
                                    continue
                                cmd = data.get("cmd")
                                if cmd:
                                    asyncio.create_task(run_cmd_async(ws, cmd))
                        except Exception as e:
                            print(f"[Agent] 处理消息出错: {e}")

                await asyncio.gather(reporter(), listener())

        except Exception as e:
            print(f"[Agent] 连接断开或失败: {e}，3秒后重试")
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(agent_loop())
