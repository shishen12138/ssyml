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

agents = {}    # {agent_id: {"ws": ws, "last": timestamp, "info": {...}}}
ui_clients = set()

# ---------------- Agent 处理 ----------------
async def handle_agent(ws):
    try:
        async for msg in ws:
            data = json.loads(msg)
            if data.get("type") == "register":
                aid = data.get("agent_id")
                if not aid: continue
                agents[aid] = {"ws": ws, "last": time.time(), "info": {}}
                print(f"[+] agent {aid} 注册")
                await broadcast_summary()
            elif data.get("type") == "update":
                aid = data.get("agent_id")
                if aid in agents:
                    agents[aid]["last"] = time.time()
                    agents[aid]["info"] = data
                    await broadcast_summary()
            elif data.get("type") == "cmd_result":
                await broadcast_ui({
                    "type": "cmd_result",
                    "agent_id": data.get("agent_id"),
                    "payload": data.get("payload")
                })
    except Exception as e:
        print("agent error:", e)
    finally:
        dead = None
        for aid, v in list(agents.items()):
            if v["ws"] == ws:
                dead = aid
        if dead:
            print(f"[-] agent {dead} 下线")
            # 保留离线状态，不删除
            agents[dead]["ws"] = None
            await broadcast_summary()

# ---------------- UI 处理 ----------------
async def handle_ui(ws):
    ui_clients.add(ws)
    print("[+] UI 连接")
    await broadcast_summary()
    try:
        async for msg in ws:
            data = json.loads(msg)
            if data.get("type") == "exec":
                if data.get("auth") != AUTH_TOKEN:
                    await ws.send(json.dumps({"type":"error","msg":"auth failed"}))
                    continue
                cmd = data.get("cmd")
                targets = data.get("agents") or []
                for aid in targets:
                    agent = agents.get(aid)
                    if agent and agent["ws"]:
                        try:
                            await agent["ws"].send(json.dumps({"type":"exec","cmd":cmd}))
                        except Exception as e:
                            print(f"[!] 发命令到 {aid} 失败:", e)
    except Exception as e:
        print("ui error:", e)
    finally:
        ui_clients.discard(ws)
        print("[-] UI 断开")

# ---------------- 广播 ----------------
async def broadcast_ui(data: dict):
    if not ui_clients: return
    msg = json.dumps(data)
    await asyncio.gather(*[u.send(msg) for u in list(ui_clients)], return_exceptions=True)

async def broadcast_summary():
    total = len(agents)
    online, offline = 0, 0
    now = time.time()
    agents_list = []
    for aid, v in agents.items():
        alive = (v.get("ws") and (now - v["last"]) < 15)
        if alive: online += 1
        else: offline += 1
        info = v.get("info", {}).copy()
        info["agent_id"] = aid
        info["online"] = alive
        agents_list.append(info)  # 离线也加入
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
            pass  # 屏蔽日志
    os.chdir(os.path.dirname(os.path.abspath(__file__)))  # 当前目录
    httpd = HTTPServer(("", HTTP_PORT), MyHandler)
    print(f"[HTTP] 前端面板服务已启动: http://<IP>:{HTTP_PORT}/index.html")
    httpd.serve_forever()

# ---------------- 主程序 ----------------
async def main():
    # WebSocket server
    agent_srv = await websockets.serve(handle_agent, "0.0.0.0", AGENT_WS_PORT)
    ui_srv = await websockets.serve(handle_ui, "0.0.0.0", UI_WS_PORT, ping_interval=None)
    print(f"[WS] UI端口 {UI_WS_PORT}, agent端口 {AGENT_WS_PORT}")
    
    # 启动 HTTP server 线程
    threading.Thread(target=start_http_server, daemon=True).start()

    # 阻塞
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
