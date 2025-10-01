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
HEARTBEAT_TIMEOUT = 30  # 超过30秒没收到update标离线

# ---------------- 日志 ----------------
if sys.platform.startswith("win"):
    log_path = os.path.join(os.path.expanduser("~"), "Desktop")
else:
    log_path = "/root"
    if not os.access(log_path, os.W_OK):
        log_path = os.path.dirname(os.path.abspath(__file__))

LOG_FILE = os.path.join(log_path, "server.log")
logger = logging.getLogger("ServerLogger")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("[%(asctime)s] %(message)s", "%Y-%m-%d %H:%M:%S")

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = TimedRotatingFileHandler(LOG_FILE, when="midnight", interval=1, backupCount=7, encoding="utf-8")
file_handler.setFormatter(formatter)
file_handler.suffix = "%Y-%m-%d"
logger.addHandler(file_handler)

def log(msg):
    logger.info(msg)

# ---------------- 全局状态 ----------------
agents = {}      # agent_id -> {ws, last, info, online}
ui_clients = set()
agents_lock = asyncio.Lock()
_last_summary_broadcast = 0  # 用于每秒广播 summary counts

# ---------------- 辅助构造 agent info ----------------
def _build_agent_info(aid, v, now=None):
    if now is None:
        now = time.time()
    alive = bool(v.get("online") and v.get("ws") and (now - v.get("last", 0) < HEARTBEAT_TIMEOUT))
    info = v.get("info", {}).copy() if v.get("info") else {}
    info.update({"agent_id": aid, "online": alive})
    return info

# ---------------- 广播基础 ----------------
async def broadcast_ui(data: dict):
    if not ui_clients:
        return
    msg = json.dumps(data)
    for u in list(ui_clients):
        try:
            await u.send(msg)
        except:
            ui_clients.discard(u)

# 发单个 agent 的增量（新增/更新）
async def broadcast_agent_update(agent_id):
    async with agents_lock:
        v = agents.get(agent_id)
        if not v:
            return
        info = _build_agent_info(agent_id, v)
    await broadcast_ui({"type": "agent_update", "agent": info})

# 发 agent 新增（register）
async def broadcast_agent_add(agent_id):
    async with agents_lock:
        v = agents.get(agent_id)
        if not v:
            return
        info = _build_agent_info(agent_id, v)
    await broadcast_ui({"type": "agent_add", "agent": info})
    await broadcast_summary_counts()  # 更新计数

# 发 agent 删除
async def broadcast_agent_remove(agent_id):
    await broadcast_ui({"type": "agent_remove", "agent_id": agent_id})
    await broadcast_summary_counts()

# 发 agent 在线/离线状态变更（仅发送状态）
async def broadcast_agent_status(agent_id, online):
    await broadcast_ui({"type": "agent_status", "agent_id": agent_id, "online": bool(online)})
    await broadcast_summary_counts()

# 发全量快照给单个 UI（用于 UI 首次连接）
async def send_full_snapshot(ws):
    now = time.time()
    async with agents_lock:
        total = len(agents)
        online, offline = 0, 0
        agents_list = []
        for aid, v in agents.items():
            info = _build_agent_info(aid, v, now)
            if info.get("online"):
                online += 1
            else:
                offline += 1
            agents_list.append(info)
    payload = {
        "type": "full_snapshot",
        "summary": {"total": total, "online": online, "offline": offline},
        "agents": agents_list
    }
    try:
        await ws.send(json.dumps(payload))
    except:
        pass

# 只广播 summary counts（每秒一次或强制）
async def broadcast_summary_counts(force=False):
    global _last_summary_broadcast
    now = time.time()
    if not force and (now - _last_summary_broadcast < 1):
        return
    _last_summary_broadcast = now

    async with agents_lock:
        total = len(agents)
        online = 0
        for aid, v in agents.items():
            alive = bool(v.get("online") and v.get("ws") and (now - v.get("last", 0) < HEARTBEAT_TIMEOUT))
            if alive:
                online += 1
        offline = total - online
    payload = {"type": "summary", "summary": {"total": total, "online": online, "offline": offline}, "clients": len(ui_clients)}
    await broadcast_ui(payload)

# ---------------- Agent 处理 ----------------
async def handle_agent(ws):
    aid = None
    try:
        async for msg in ws:
            try:
                data = json.loads(msg)
            except:
                continue

            if data.get("type") == "register":
                aid = data.get("agent_id")
                if not aid:
                    continue
                async with agents_lock:
                    agents[aid] = {
                        "ws": ws,
                        "last": time.time(),
                        "info": agents.get(aid, {}).get("info", {}),
                        "online": True,
                    }
                log(f"[+] agent {aid} 注册")
                # 新增直接发送新增消息和 summary counts
                await broadcast_agent_add(aid)

            elif data.get("type") == "update" and aid:
                async with agents_lock:
                    agent = agents.get(aid)
                    if agent:
                        agent["info"] = data
                        agent["last"] = time.time()
                        agent["online"] = True
                # 只发送该 agent 的更新（节约带宽，前端更新对应条目）
                await broadcast_agent_update(aid)
                # 也尝试每秒发送 summary counts（内部节流）
                await broadcast_summary_counts()

            elif data.get("type") == "cmd_result" and aid:
                await broadcast_ui({
                    "type": "cmd_result",
                    "agent_id": aid,
                    "payload": data.get("payload")
                })

    except websockets.ConnectionClosed:
        pass
    finally:
        if aid:
            async with agents_lock:
                agent = agents.get(aid)
                if agent:
                    agent["ws"] = None  # 连接断开，先置空 ws；heartbeat_check 会根据 last 判定 online 状态
        log(f"[-] agent {aid} 断开")
        # 立即通知 UI 该 agent 连接断开（状态变化）
        await broadcast_agent_status(aid, False)

# ---------------- UI 处理 ----------------
async def handle_ui(ws):
    ui_clients.add(ws)
    log("[+] UI 连接")
    # 给新 UI 发送全量快照（一次）
    await send_full_snapshot(ws)
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
                            except:
                                pass

            elif data.get("type") == "remove":
                if data.get("auth") != AUTH_TOKEN:
                    await ws.send(json.dumps({"type":"error","msg":"auth failed"}))
                    continue
                aid = data.get("agent_id")
                if aid:
                    await remove_agent(aid)

    except websockets.ConnectionClosed:
        log("UI 连接关闭")
    finally:
        ui_clients.discard(ws)
        log("[-] UI 断开")

# ---------------- 删除 agent ----------------
async def remove_agent(agent_id):
    async with agents_lock:
        agent = agents.pop(agent_id, None)
        if agent and agent.get("ws"):
            try:
                await agent["ws"].close()
            except:
                pass
    log(f"[!] agent {agent_id} 已删除")
    await broadcast_agent_remove(agent_id)

# ---------------- 心跳检查（检测 online 状态变化） ----------------
async def heartbeat_check():
    while True:
        changed = False
        now = time.time()
        async with agents_lock:
            for aid, v in list(agents.items()):
                online = bool(v.get("ws") and (now - v.get("last", 0) < HEARTBEAT_TIMEOUT))
                if v.get("online") != online:
                    v["online"] = online
                    changed = True
                    # 立即推送该 agent 的状态变更（在线/离线）
                    # 放在循环外面异步调用，收集所有变化后再 push summary
                    asyncio.create_task(broadcast_agent_status(aid, online))
        if changed:
            # 强制发送一次 summary counts（不会被频繁调用，因为 heartbeat_check 每5s）
            await broadcast_summary_counts(force=True)
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
    await websockets.serve(handle_agent, "0.0.0.0", AGENT_WS_PORT, ping_interval=20, ping_timeout=20)
    await websockets.serve(handle_ui, "0.0.0.0", UI_WS_PORT, ping_interval=20, ping_timeout=20)
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
