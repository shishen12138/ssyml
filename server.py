#!/usr/bin/env python3
import asyncio
import json
import websockets
import time
import sys
import os
from http.server import SimpleHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import threading
import logging
from logging.handlers import TimedRotatingFileHandler
from functools import partial

# ---------------- 配置 ----------------
UI_WS_PORT = 8000
AGENT_WS_PORT = 9001
HTTP_PORT = 8080
AUTH_TOKEN = "super-secret-token-CHANGE_ME"
HEARTBEAT_TIMEOUT = 30  # 心跳超时秒数

# ---------------- 日志配置 ----------------
if sys.platform.startswith("win"):
    desktop = os.path.join(os.path.expanduser("~"), "Desktop")
    log_path = desktop
else:
    log_path = "/root"
    if not os.access(log_path, os.W_OK):
        log_path = os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(log_path, "server.log")

# 日志初始化
logger = logging.getLogger("ServerLogger")
logger.setLevel(logging.INFO)

formatter = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")

# 控制台日志
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# 文件日志，按天轮转，保留最近7天
file_handler = TimedRotatingFileHandler(LOG_FILE, when="midnight", interval=1, backupCount=7, encoding="utf-8")
file_handler.setFormatter(formatter)
file_handler.suffix = "%Y-%m-%d"
logger.addHandler(file_handler)

def log(msg):
    logger.info(msg)

# ---------------- 全局状态 ----------------
agents = {}      # agent_id -> {ws, last, info, conn_id, remote, replaced, online}
ws_map = {}      # conn_id -> agent_id
ui_clients = set()
agents_lock = asyncio.Lock()  # 并发保护

# ---------------- Agent 处理 ----------------
async def handle_agent(ws):
    conn_id = id(ws)
    remote = getattr(ws, "remote_address", None)
    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
            except Exception:
                continue

            if data.get("type") == "register":
                aid = data.get("agent_id")
                if not aid:
                    continue

                async with agents_lock:
                    old = agents.get(aid)
                    if old and old.get("ws") and old["ws"] is not ws:
                        old["replaced"] = True
                        try:
                            await old["ws"].close()
                        except:
                            pass
                        log(f"[!] agent {aid} 新连接 {conn_id} 替换旧连接 {old.get('conn_id')}")

                    agents[aid] = {
                        "ws": ws,
                        "last": time.time(),
                        "info": agents.get(aid, {}).get("info", {}),
                        "conn_id": conn_id,
                        "remote": remote,
                        "replaced": False,
                        "online": True
                    }
                    ws_map[conn_id] = aid
                    log(f"[+] agent {aid} 注册 conn={conn_id} remote={remote}")
                await broadcast_summary()

            elif data.get("type") == "update":
                aid = data.get("agent_id")
                async with agents_lock:
                    if aid in agents and agents[aid].get("conn_id") == conn_id:
                        agents[aid]["last"] = time.time()
                        agents[aid]["info"] = data
                        agents[aid]["online"] = True
                await broadcast_summary()

            elif data.get("type") == "cmd_result":
                await broadcast_ui({
                    "type": "cmd_result",
                    "agent_id": data.get("agent_id"),
                    "payload": data.get("payload")
                })

    except websockets.ConnectionClosed:
        log(f"agent {conn_id} 连接关闭")
    except Exception as e:
        log(f"agent error: {e}")
    finally:
        async with agents_lock:
            aid = ws_map.pop(conn_id, None)
            if aid:
                cur = agents.get(aid)
                if cur and cur.get("conn_id") == conn_id:
                    if cur.get("replaced"):
                        log(f"[-] agent {aid} 旧连接断开，被替换，忽略下线")
                    else:
                        log(f"[-] agent {aid} 连接断开 conn={conn_id} remote={remote}")
                        agents[aid].update({
                            "ws": None,
                            "conn_id": None,
                            "remote": None,
                            "online": False
                        })
        await broadcast_summary()

# ---------------- UI 处理 ----------------
async def handle_ui(ws):
    ui_clients.add(ws)
    log("[+] UI 连接")
    await broadcast_summary()
    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
            except:
                continue

            if data.get("type") == "exec":
                if data.get("auth") != AUTH_TOKEN:
                    await ws.send(json.dumps({"type":"error","msg":"auth failed"}))
                    continue
                cmd = data.get("cmd")
                targets = data.get("agents") or []
                async with agents_lock:
                    for aid in targets:
                        agent = agents.get(aid)
                        if agent and agent.get("ws"):
                            try:
                                await agent["ws"].send(json.dumps({"type":"exec","cmd":cmd}))
                            except Exception as e:
                                log(f"[!] 发命令到 {aid} 失败: {e}")

            elif data.get("type") == "remove":
                if data.get("auth") != AUTH_TOKEN:
                    await ws.send(json.dumps({"type":"error","msg":"auth failed"}))
                    continue
                aid = data.get("agent_id")
                if aid:
                    await remove_agent(aid)

    except websockets.ConnectionClosed:
        log("UI 连接关闭")
    except Exception as e:
        log(f"ui error: {e}")
    finally:
        ui_clients.discard(ws)
        log("[-] UI 断开")

# ---------------- 删除 agent ----------------
async def remove_agent(agent_id):
    async with agents_lock:
        agent = agents.get(agent_id)
        if not agent:
            log(f"[!] agent {agent_id} 不存在")
            return
        ws = agent.get("ws")
        if ws:
            try:
                await ws.close()
            except:
                pass
        agents.pop(agent_id, None)
        to_remove = [k for k,v in ws_map.items() if v == agent_id]
        for k in to_remove:
            ws_map.pop(k, None)
        log(f"[!] agent {agent_id} 已删除")
    await broadcast_summary()

# ---------------- 广播 ----------------
async def broadcast_ui(data: dict):
    if not ui_clients:
        return
    msg = json.dumps(data)
    for u in list(ui_clients):
        try:
            await u.send(msg)
        except websockets.ConnectionClosed:
            ui_clients.discard(u)
        except Exception as e:
            log(f"[!] 广播失败: {e}")

async def broadcast_summary():
    async with agents_lock:
        total = len(agents)
        online, offline = 0, 0
        now = time.time()
        agents_list = []
        for aid, v in agents.items():
            alive = v.get("online") and bool(v.get("ws") and (now - v.get("last",0) < HEARTBEAT_TIMEOUT))
            if alive: online += 1
            else: offline += 1
            info = v.get("info", {}).copy()
            info.update({"agent_id": aid, "online": alive, "remote": v.get("remote")})
            agents_list.append(info)
        payload = {
            "type": "update",
            "summary": {"total": total,"online": online,"offline": offline},
            "agents": agents_list,
            "clients": len(ui_clients)
        }
    await broadcast_ui(payload)

# ---------------- 心跳 ----------------
async def heartbeat_check():
    while True:
        changed = False
        async with agents_lock:
            now = time.time()
            for aid, v in agents.items():
                alive = bool(v.get("ws") and (now - v.get("last",0) < HEARTBEAT_TIMEOUT))
                if v.get("online") != alive:
                    v["online"] = alive
                    changed = True
        if changed:
            await broadcast_summary()
        await asyncio.sleep(5)

# ---------------- HTTP 服务器 ----------------
def start_http_server():
    dir_path = os.path.dirname(os.path.abspath(__file__))
    handler = partial(SimpleHTTPRequestHandler, directory=dir_path)
    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
    httpd = ThreadedHTTPServer(("", HTTP_PORT), handler)
    log(f"[HTTP] 前端面板服务已启动: http://<IP>:{HTTP_PORT}/index.html")
    httpd.serve_forever()

# ---------------- 主程序 ----------------
async def main():
    agent_srv = await websockets.serve(handle_agent, "0.0.0.0", AGENT_WS_PORT,
                                       ping_interval=20, ping_timeout=20)
    ui_srv = await websockets.serve(handle_ui, "0.0.0.0", UI_WS_PORT,
                                    ping_interval=20, ping_timeout=20)
    log(f"[WS] UI端口 {UI_WS_PORT}, agent端口 {AGENT_WS_PORT}")

    threading.Thread(target=start_http_server, daemon=True).start()
    asyncio.create_task(heartbeat_check())
    await asyncio.Future()  # 永远阻塞

# ---------------- 启动 ----------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log("服务器手动停止")
    except Exception as e:
        log(f"服务器异常: {e}")
    finally:
        if sys.platform.startswith("win"):
            input("按回车退出...")
