#!/usr/bin/env python3
import asyncio, json, websockets, time, os, sys
import platform, psutil, uuid, subprocess, socket, logging

# ---------------- 配置 ----------------
SERVER = "ws://47.236.6.215:9002"   # 替换为你的 server 地址
AGENT_ID = str(uuid.uuid4())
REPORT_INTERVAL = 0.5  # 上报间隔秒
LOG_FILE = os.path.join(os.path.expanduser("~"), "agent.log")

# ---------------- 日志 ----------------
logger = logging.getLogger("AgentLogger")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")
console_handler = logging.StreamHandler(); console_handler.setFormatter(formatter); logger.addHandler(console_handler)
def log(msg): logger.info(msg)

# ---------------- 系统信息 ----------------
def get_sysinfo():
    net_io = psutil.net_io_counters()
    net_speed = getattr(get_sysinfo, "last_net", None)
    now = time.time()

    # 计算流量速度
    if net_speed:
        dt = now - net_speed["time"]
        up_speed = (net_io.bytes_sent - net_speed["sent"]) / dt
        down_speed = (net_io.bytes_recv - net_speed["recv"]) / dt
    else:
        up_speed = down_speed = 0
    get_sysinfo.last_net = {"time": now, "sent": net_io.bytes_sent, "recv": net_io.bytes_recv}

    # CPU/内存
    cpu = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory().percent

    # uptime
    uptime = time.time() - psutil.boot_time()

    # IP
    public_ip = get_public_ip()
    lan_ip = get_lan_ip()

    # 磁盘
    disks=[]
    for part in psutil.disk_partitions(all=False):
        usage = psutil.disk_usage(part.mountpoint)
        disks.append({
            "mount": part.mountpoint,
            "total": usage.total,
            "used": usage.used,
            "percent": int(usage.percent)
        })

    # Top5 进程
    procs=[]
    for p in sorted(psutil.process_iter(["pid","name","cpu_percent","memory_percent"]), key=lambda x: x.info["cpu_percent"], reverse=True)[:5]:
        procs.append({
            "pid": p.info["pid"],
            "name": p.info["name"],
            "cpu_percent": p.info["cpu_percent"],
            "memory_percent": p.info["memory_percent"]
        })

    return {
        "agent_id": AGENT_ID,
        "cpu": cpu,
        "memory": memory,
        "uptime": int(uptime),
        "net": {"up_speed": up_speed, "down_speed": down_speed, "bytes_sent": net_io.bytes_sent, "bytes_recv": net_io.bytes_recv},
        "disk": disks,
        "top5": procs,
        "public_ip": public_ip,
        "lan_ip": lan_ip,
        "hostname": platform.node(),
        "os": platform.platform()
    }

def get_public_ip():
    # 尝试获取公网IP
    return getattr(get_sysinfo, "public_ip", "")

def get_lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except: return "127.0.0.1"

# ---------------- 执行命令 ----------------
def exec_cmd(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
        return result.stdout + result.stderr
    except Exception as e:
        return str(e)

# ---------------- Agent 主逻辑 ----------------
async def run_agent():
    retry_delay=1
    while True:
        try:
            async with websockets.connect(SERVER, ping_interval=15, ping_timeout=15, close_timeout=5) as ws:
                retry_delay=1
                await ws.send(json.dumps({"type":"register","agent_id":AGENT_ID}))
                log(f"[agent] 已连接 server {SERVER}，ID={AGENT_ID}")

                async def reporter():
                    while True:
                        try:
                            await ws.send(json.dumps({"type":"update", **get_sysinfo()}))
                        except Exception as e:
                            log(f"[agent] 上报失败: {e}")
                        await asyncio.sleep(REPORT_INTERVAL)

                async def listener():
                    async for msg in ws:
                        try:
                            data=json.loads(msg)
                            if data.get("type")=="exec":
                                cmd=data.get("cmd")
                                log(f"[agent] 执行命令: {cmd}")
                                res = await asyncio.to_thread(exec_cmd, cmd)
                                await ws.send(json.dumps({"type":"cmd_result","agent_id":AGENT_ID,"payload":res}))
                                # 执行完命令后立即上报一次状态
                                await ws.send(json.dumps({"type":"update", **get_sysinfo()}))
                        except Exception as e:
                            log(f"[agent] 处理命令异常: {e}")

                await asyncio.gather(reporter(), listener(), return_exceptions=True)

        except Exception as e:
            log(f"[agent] 连接失败或异常，重试中... {e}")
            await asyncio.sleep(retry_delay)
            retry_delay=min(retry_delay*2,60)

if __name__=="__main__":
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        log("Agent 手动停止")
