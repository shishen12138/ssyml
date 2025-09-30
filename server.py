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

# ---------------- 配置 ----------------
UI_WS_PORT = 8000
AGENT_WS_PORT = 9001
HTTP_PORT = 8080
AUTH_TOKEN = "super-secret-token-CHANGE_ME"
LOG_FILE = "/root/server.log"

# {agent_id: {"ws": ws, "last": timestamp, "info": {...}, "conn_id": int, "remote": (ip,port), "replaced": bool, "online": bool}} 
agents = {}
# map conn_id -> agent_id (帮助在 finally 中查找)
ws_map = {}
ui_clients = set()

# ---------------- 日志 ----------------
def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{ts}] {msg}\n")
    except:
        pass

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

                old = agents.get(aid)
                # 如果已有旧连接且不是同一个 ws，标记替换并尝试关闭旧连接
                if old and old.get("ws") and old["ws"] is not ws:
                    old["replaced"] = True
                    try:
                        await old["ws"].close()
                    except:
                        pass
                    log(f"[!] agent {aid} 新连接 {conn_id} 替换旧连接 {old.get('conn_id')}")

                # 注册/覆盖记录（保留原 info，避免 info 被清空）
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
                if aid in agents:
                    if agents[aid].get("conn_id") == conn_id:
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

    except Exception as e:
        log(f"agent error: {e}")
    finally:
        aid = ws_map.pop(conn_id, None)
        if aid:
            cur = agents.get(aid)
            if cur and cur.get("conn_id") == conn_id:
                if cur.get("replaced"):
                    log(f"[-] agent {aid} 旧连接断开，被替换，忽略下线")
                else:
                    log(f"[-] agent {aid} 连接断开 conn={conn_id} remote={remote}")
                    agents[aid]["ws"] = None
                    agents[aid]["conn_id"] = None
                    agents[aid]["remote"] = None
                    agents[aid]["online"] = False
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

            # 执行命令
            if data.get("type") == "exec":
                if data.get("auth") != AUTH_TOKEN:
                    await ws.send(json.dumps({"type":"error","msg":"auth failed"}))
                    continue
                cmd = data.get("cmd")
                targets = data.get("agents") or []
                for aid in targets:
                    agent = agents.get(aid)
                    if agent and agent.get("ws"):
                        try:
                            await agent["ws"].send(json.dumps({"type":"exec","cmd":cmd}))
                        except Exception as e:
                            log(f"[!] 发命令到 {aid} 失败: {e}")

            # 删除 agent
            elif data.get("type") == "remove":
                if data.get("auth") != AUTH_TOKEN:
                    await ws.send(json.dumps({"type":"error","msg":"auth failed"}))
                    continue
                aid = data.get("agent_id")
                if aid:
                    await remove_agent(aid)

    except Exception as e:
        log(f"ui error: {e}")
    finally:
        ui_clients.discard(ws)
        log("[-] UI 断开")

# ---------------- 手动删除 agent ----------------
async def remove_agent(agent_id):
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
        except Exception as e:
            log(f"[!] 广播失败: {e}")

async def broadcast_summary():
    total = len(agents)
    online, offline = 0, 0
    now = time.time()
    agents_list = []
    for aid, v in agents.items():
        alive = v.get("online") and bool(v.get("ws") and (now - v.get("last",0) < 30))
        if alive: online += 1
        else: offline += 1
        info = v.get("info", {}).copy()
        info["agent_id"] = aid
        info["online"] = alive
        info["remote"] = v.get("remote")
        agents_list.append(info)
    payload = {
        "type": "update",
        "summary": {"total": total,"online": online,"offline": offline},
        "agents": agents_list,
        "clients": len(ui_clients)
    }
    await broadcast_ui(payload)

# ---------------- 心跳检查 ----------------
async def heartbeat_check():
    while True:
        now = time.time()
        changed = False
        for aid, v in agents.items():
            alive = bool(v.get("ws") and (now - v.get("last",0) < 30))
            if v.get("online") != alive:
                v["online"] = alive
                changed = True
        if changed:
            await broadcast_summary()
        await asyncio.sleep(10)

# ---------------- HTTP 服务器 ----------------
def start_http_server():
    class MyHandler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
    httpd = ThreadedHTTPServer(("", HTTP_PORT), MyHandler)
    log(f"[HTTP] 前端面板服务已启动: http://<IP>:{HTTP_PORT}/index.html")
    httpd.serve_forever()

# ---------------- 主程序 ----------------
async def main():
    agent_srv = await websockets.serve(handle_agent, "0.0.0.0", AGENT_WS_PORT)
    ui_srv = await websockets.serve(handle_ui, "0.0.0.0", UI_WS_PORT, ping_interval=None)
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
