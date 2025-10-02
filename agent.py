#!/usr/bin/env python3
import asyncio, websockets, psutil, platform, socket, json, time, subprocess, uuid, requests, os, glob

SERVER = "ws://47.236.6.215:9002"
REPORT_INTERVAL = 5

# agent ID 保持不变
AGENT_ID_FILE = "/root/agent_id.txt"
try:
    AGENT_ID = open(AGENT_ID_FILE).read().strip()
except:
    AGENT_ID = str(uuid.uuid4())
    with open(AGENT_ID_FILE, "w") as f:
        f.write(AGENT_ID)

# 命令日志目录
CMD_LOG_DIR = "/root/agent_cmd_logs"
os.makedirs(CMD_LOG_DIR, exist_ok=True)

_net_last = {"s": psutil.net_io_counters().bytes_sent,
             "r": psutil.net_io_counters().bytes_recv,
             "t": time.time()}

# ---------------- 系统信息 ----------------
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
        up_speed = (net.bytes_sent - _net_last["s"]) / dt if dt>0 else 0
        down_speed = (net.bytes_recv - _net_last["r"]) / dt if dt>0 else 0
        _net_last = {"s": net.bytes_sent, "r": net.bytes_recv, "t": now}

        return {
            "type":"update",
            "agent_id":AGENT_ID,
            "hostname":socket.gethostname(),
            "os":platform.platform(),
            "public_ip":get_public_ip(),
            "lan_ip":get_lan_ip(),
            "cpu":cpu,
            "memory":mem,
            "disk":disk,
            "net":{
                "bytes_sent":net.bytes_sent,
                "bytes_recv":net.bytes_recv,
                "up_speed":up_speed,
                "down_speed":down_speed
            },
            "processes":top_processes(5),
            "uptime":int(time.time()-psutil.boot_time())
        }
    except Exception as e:
        return {"type":"update","agent_id":AGENT_ID,"error":str(e)}

# ---------------- 命令执行 ----------------
def exec_cmd_detached(cmd: str):
    """脱离 Agent 执行命令，日志写入文件"""
    log_file = os.path.join(CMD_LOG_DIR, f"{int(time.time())}_{uuid.uuid4().hex}.log")
    system = platform.system()
    try:
        if system == "Windows":
            subprocess.Popen(f'start /b cmd /c "{cmd} > {log_file} 2>&1"', shell=True)
        else:
            # Linux/macOS
            full_cmd = f"bash -c '{cmd}'"
            subprocess.Popen(f'nohup {full_cmd} > {log_file} 2>&1', shell=True, preexec_fn=os.setsid)
        return {"cmd": cmd, "status":"started", "log_file":log_file}
    except Exception as e:
        return {"cmd": cmd, "status":"fail", "error": str(e)}

async def send_cmd_result(ws, result: dict):
    try:
        await ws.send(json.dumps({
            "type":"cmd_result",
            "agent_id":AGENT_ID,
            "payload":result
        }))
    except Exception as e:
        print(f"[Agent] 发送命令结果失败: {e}")

async def run_cmd_async(ws, cmd):
    """异步脱离 Agent 执行命令"""
    result = exec_cmd_detached(cmd)
    await send_cmd_result(ws, result)

# ---------------- 重启后上报未发送日志 ----------------
async def report_pending_logs(ws):
    logs = sorted(glob.glob(os.path.join(CMD_LOG_DIR, "*.log")))
    for log_file in logs:
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            result = {
                "cmd":"<detached command>",
                "status":"completed",
                "log_file":log_file,
                "output": content
            }
            await send_cmd_result(ws, result)
            os.remove(log_file)
        except Exception as e:
            print(f"[Agent] 发送日志失败 {log_file}: {e}")

# ---------------- 主循环 ----------------
async def agent_loop():
    while True:
        try:
            async with websockets.connect(SERVER, ping_interval=30, ping_timeout=30) as ws:
                print(f"[Agent] 已连接控制端 {SERVER}")
                await ws.send(json.dumps({"type":"register","agent_id":AGENT_ID}))

                async def reporter():
                    while True:
                        try:
                            info = get_sysinfo()
                            await ws.send(json.dumps(info))
                        except Exception as e:
                            print(f"[Agent] 状态上报失败: {e}")
                        await asyncio.sleep(REPORT_INTERVAL)

                async def listener():
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                            if data.get("type") == "exec":
                                agents_list = data.get("agents", [])
                                if AGENT_ID not in agents_list:
                                    continue
                                cmd = data.get("cmd")
                                if cmd:
                                    asyncio.create_task(run_cmd_async(ws, cmd))
                        except Exception as e:
                            print(f"[Agent] 处理消息出错: {e}")

                # 重启后上报未发送的日志
                await report_pending_logs(ws)

                await asyncio.gather(reporter(), listener())

        except Exception as e:
            print(f"[Agent] 连接失败或断开: {e}，3秒后重试")
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(agent_loop())
