#!/usr/bin/env python3
import asyncio
import json
import websockets
import time
import sys
import os
from http.server import SimpleHTTPRequestHandler, HTTPServer
import threading

# ---------------- 配置 ----------------
UI_WS_PORT = 8000
AGENT_WS_PORT = 9001
HTTP_PORT = 8080
AUTH_TOKEN = "super-secret-token-CHANGE_ME"

# {agent_id: {"ws": ws, "last": timestamp, "info": {...}, "conn_id": int, "remote": (ip,port)}} 
agents = {}
# map conn_id -> agent_id (帮助在 finally 中查找)
ws_map = {}

ui_clients = set()

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
                    old_conn = old.get("conn_id")
                    print(f"[!] agent {aid} 新连接 {conn_id} 替换旧连接 {old_conn}，远端: {remote}")
                    # 尝试优雅关闭旧 ws（旧 ws 的 finally 会被调用，但会被识别为被替换）
                    try:
                        await old["ws"].close()
                    except Exception:
                        pass

                # 注册/覆盖记录（保留原 info，避免 info 被清空）
                agents[aid] = {
                    "ws": ws,
                    "last": time.time(),
                    "info": agents.get(aid, {}).get("info", {}),
                    "conn_id": conn_id,
                    "remote": remote
                }
                ws_map[conn_id] = aid
                print(f"[+] agent {aid} 注册 conn={conn_id} remote={remote}")
                await broadcast_summary()

            elif data.get("type") == "update":
                aid = data.get("agent_id")
                if aid in agents:
                    # 只有当当前连接是活跃连接才更新时间（防止旧连接篡改 last）
                    if agents[aid].get("conn_id") == conn_id:
                        agents[aid]["last"] = time.time()
                        agents[aid]["info"] = data
                        await broadcast_summary()
                    else:
                        # 旧连接的 update，忽略
                        pass

            elif data.get("type") == "cmd_result":
                await broadcast_ui({
                    "type": "cmd_result",
                    "agent_id": data.get("agent_id"),
                    "payload": data.get("payload")
                })

    except Exception as e:
        print("agent error:", e)
    finally:
        # finally 时，通过 conn_id 找到对应的 agent_id（如果有）
        aid = ws_map.pop(conn_id, None)
        if aid:
            cur = agents.get(aid)
            # 只有当被关闭的连接仍是 agents[aid] 的当前连接（conn_id 相同）时，才把 agent 标为下线
            if cur and cur.get("conn_id") == conn_id:
                print(f"[-] agent {aid} 连接断开 conn={conn_id} remote={remote}")
                # 标记为离线（保留 record），但清除 ws & conn_id
                agents[aid]["ws"] = None
                agents[aid]["conn_id"] = None
                agents[aid]["remote"] = None
                await broadcast_summary()
            else:
                # 连接断开但已被替换，不当作 agent 下线
                print(f"[-] conn {conn_id} 已断开，但 agent {aid} 已被替换，忽略下线 (替换不触发下线广播)")

# ---------------- UI 处理 ----------------
async def handle_ui(ws):
    ui_clients.add(ws)
    print("[+] UI 连接")
    await broadcast_summary()
    try:
        async for msg in ws:
            data = json.loads(msg)

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
                            print(f"[!] 发命令到 {aid} 失败:", e)

            # 删除 agent
            elif data.get("type") == "remove":
                if data.get("auth") != AUTH_TOKEN:
                    await ws.send(json.dumps({"type":"error","msg":"auth failed"}))
                    continue
                aid = data.get("agent_id")
                if aid:
                    await remove_agent(aid)

    except Exception as e:
        print("ui error:", e)
    finally:
        ui_clients.discard(ws)
        print("[-] UI 断开")

# ---------------- 手动删除 agent ----------------
async def remove_agent(agent_id):
    agent = agents.get(agent_id)
    if not agent:
        print(f"[!] agent {agent_id} 不存在")
        return
    ws = agent.get("ws")
    if ws:
        try:
            await ws.close()
        except:
            pass
    agents.pop(agent_id, None)
    # 若该连接仍在 ws_map 中，移除映射
    # （某些旧连接 id 可能仍在 map 中）
    to_remove = [k for k,v in ws_map.items() if v == agent_id]
    for k in to_remove:
        ws_map.pop(k, None)
    print(f"[!] agent {agent_id} 已删除")
    await broadcast_summary()

# ---------------- 广播 ----------------
async def broadcast_ui(data: dict):
    if not ui_clients:
        return
    msg = json.dumps(data)
    await asyncio.gather(*[u.send(msg) for u in list(ui_clients)], return_exceptions=True)

async def broadcast_summary():
    total = len(agents)
    online, offline = 0, 0
    now = time.time()
    agents_list = []
    for aid, v in agents.items():
        alive = bool(v.get("ws") and (now - v.get("last", 0) < 30))
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

# ---------------- HTTP 服务器 ----------------
def start_http_server():
    class MyHandler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    httpd = HTTPServer(("", HTTP_PORT), MyHandler)
    print(f"[HTTP] 前端面板服务已启动: http://<IP>:{HTTP_PORT}/index.html")
    httpd.serve_forever()

# ---------------- 主程序 ----------------
async def main():
    agent_srv = await websockets.serve(handle_agent, "0.0.0.0", AGENT_WS_PORT)
    ui_srv = await websockets.serve(handle_ui, "0.0.0.0", UI_WS_PORT, ping_interval=None)
    print(f"[WS] UI端口 {UI_WS_PORT}, agent端口 {AGENT_WS_PORT}")

    threading.Thread(target=start_http_server, daemon=True).start()
    await asyncio.Future()  # 永远阻塞

# ---------------- 启动 ----------------
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("服务器手动停止")
    except Exception as e:
        print("服务器异常:", e)
    finally:
        if sys.platform.startswith("win"):
            input("按回车退出...")
