#!/usr/bin/env python3
import asyncio, websockets, psutil, platform, socket, json, time, os, subprocess, uuid, requests, sys

# ---------------- 配置 ----------------
SERVER = "ws://47.236.6.215:9002"  # 控制端地址
REPORT_INTERVAL = 1
LOCK_FILE = "/tmp/agent.lock"

# ---------------- 日志 ----------------
log_path = os.path.join(os.path.expanduser("~"), "Desktop") if sys.platform.startswith("win") else "/root"
if not os.access(log_path, os.W_OK): log_path = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(log_path, "agent.log")
def log(msg):
    line=f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"; print(line)
    try: open(LOG_FILE,"a",encoding="utf-8").write(line+"\n")
    except: pass

# ---------------- 单实例保护 ----------------
def check_single_instance():
    if os.path.exists(LOCK_FILE):
        try:
            pid=int(open(LOCK_FILE).read())
            if psutil.pid_exists(pid): log(f"[agent] 已有运行实例 PID={pid}"); return False
        except: pass
    open(LOCK_FILE,"w").write(str(os.getpid()))
    return True

# ---------------- Token ----------------
TOKEN_FILE = os.path.join(log_path,"agent_token.txt")
def get_or_create_token():
    if os.path.exists(TOKEN_FILE): return open(TOKEN_FILE).read().strip()
    token=str(uuid.uuid4()); open(TOKEN_FILE,"w").write(token); return token
AGENT_ID = get_or_create_token()

# ---------------- 系统信息 ----------------
def get_uptime(): return int(time.time()-psutil.boot_time()) if psutil.boot_time() else 0
def get_lan_ip():
    try: s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM); s.connect(("8.8.8.8",80)); ip=s.getsockname()[0]; s.close(); return ip
    except: return "unknown"
def get_public_ip():
    try: return requests.get("https://api.ipify.org",timeout=3).text
    except: return "unknown"
def get_sysinfo():
    try:
        cpu_percent=psutil.cpu_percent(interval=0.5)
        mem=psutil.virtual_memory()
        disk_info=[]
        for d in psutil.disk_partitions():
            try: u=psutil.disk_usage(d.mountpoint); disk_info.append({"mount":d.mountpoint,"total":u.total,"used":u.used,"percent":u.percent})
            except: continue
        net=psutil.net_io_counters()
        procs=[p.info for p in sorted(psutil.process_iter(["pid","name","cpu_percent","memory_percent"]), key=lambda x:x.info["cpu_percent"], reverse=True)[:5]]
        return {"type":"update","agent_id":AGENT_ID,"hostname":socket.gethostname(),"os":platform.platform(),
                "public_ip":get_public_ip(),"lan_ip":get_lan_ip(),"cpu":cpu_percent,"memory":mem.percent,"disk":disk_info,
                "net":{"bytes_sent":net.bytes_sent,"bytes_recv":net.bytes_recv},"uptime":get_uptime(),"top5":procs}
    except: return {"type":"update","agent_id":AGENT_ID}

# ---------------- 命令执行 ----------------
def exec_cmd(cmd):
    try: r=subprocess.run(cmd,shell=True,capture_output=True,text=True,timeout=30); return {"stdout":r.stdout,"stderr":r.stderr,"returncode":r.returncode}
    except Exception as e: return {"stdout":"","stderr":str(e),"returncode":-1}

# ---------------- Agent 主逻辑 ----------------
async def run_agent():
    retry_delay=1
    while True:
        try:
            async with websockets.connect(SERVER,ping_interval=15,ping_timeout=15,close_timeout=5) as ws:
                retry_delay=1; await ws.send(json.dumps({"type":"register","agent_id":AGENT_ID})); log(f"[agent] 已连接 server {SERVER}")
                async def reporter():
                    while True: await ws.send(json.dumps(get_sysinfo())); await asyncio.sleep(REPORT_INTERVAL)
                async def listener():
                    async for msg in ws:
                        try:
                            data=json.loads(msg)
                            if data.get("type")=="exec":
                                res=exec_cmd(data.get("cmd",""))
                                await ws.send(json.dumps({"type":"cmd_result","agent_id":AGENT_ID,"payload":res}))
                        except: pass
                await asyncio.gather(reporter(),listener(),return_exceptions=True)
        except Exception as e: log(f"[agent] 连接失败,重试中 {e}"); await asyncio.sleep(retry_delay); retry_delay=min(retry_delay*2,60)

if __name__=="__main__":
    if not check_single_instance(): sys.exit(0)
    try: asyncio.run(run_agent())
    except Exception as e: log(f"[agent] 异常退出: {e}")
