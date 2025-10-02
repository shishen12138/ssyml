#!/usr/bin/env python3
import asyncio, websockets, json, time, os
from http.server import SimpleHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from threading import Thread

# ---------------- 配置 ----------------
UI_PORT, AGENT_PORT, HTTP_PORT = 8000, 9002, 8080
HEARTBEAT_TIMEOUT = 60  # 超过60秒未上报则认为离线
AUTH_TOKEN = "super-secret-token-CHANGE_ME"

# ---------------- 全局变量 ----------------
agents = {}  # agent_id -> {ws, last, info, online}
ui_clients = set()
agents_lock = asyncio.Lock()

# ---------------- 工具函数 ----------------
def agent_info(aid, v, now=None):
    """返回 Agent 信息，包括在线状态"""
    now = now or time.time()
    online = (now - v.get("last", 0) < HEARTBEAT_TIMEOUT)
    info = v.get("info", {}).copy() if v.get("info") else {}
    info.update({"agent_id": aid, "online": online})
    return info

async def broadcast_ui(data):
    """向所有 UI 客户端广播消息"""
    msg = json.dumps(data)
    to_remove = []
    for u in ui_clients:
        try:
            await u.send(msg)
        except:
            to_remove.append(u)
    for u in to_remove:
        ui_clients.discard(u)

async def broadcast_ui_client_count():
    """向所有 UI 客户端广播当前连接数"""
    count = len(ui_clients)
    await broadcast_ui({"type": "client_count", "count": count})

# ---------------- Agent 处理 ----------------
async def handle_agent_message(aid, data):
    msg_type = data.get("type")
    if msg_type == "update":
        async with agents_lock:
            a = agents.get(aid)
            if a:
                a.update({"last": time.time(), "ws": a["ws"], "info": data})
        await broadcast_ui({"type": "agent_update", "agent": agent_info(aid, agents[aid])})
    elif msg_type == "cmd_result":
        payload = data.get("payload")
        print(f"[Controller] Agent {aid} 执行命令返回: {json.dumps(payload, ensure_ascii=False)}")
        await broadcast_ui({"type": "cmd_result", "agent_id": aid, "payload": payload})

async def handle_agent(ws):
    aid = None
    print("[Controller] 新 agent 连接")
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
                    agents[aid] = {"ws": ws, "last": time.time(), "info": {}, "online": True}
                print(f"[Controller] Agent 注册 ID={aid}")
                await broadcast_ui({"type": "agent_add", "agent": agent_info(aid, agents[aid])})

            elif data.get("type") in ["update", "cmd_result"] and aid:
                await handle_agent_message(aid, data)

    except Exception as e:
        print(f"[Controller] Agent {aid} 异常: {e}")
    finally:
        if aid:
            print(f"[Controller] Agent {aid} WebSocket 断开")

# ---------------- UI 处理 ----------------
async def handle_exec_command(data):
    if data.get("auth") != AUTH_TOKEN:
        print("[Controller] 执行命令失败：认证错误")
        return

    cmd = data.get("cmd")
    targets = data.get("agents")  # 可选
    async with agents_lock:
        if not targets:
            now = time.time()
            targets = [aid for aid, v in agents.items() if now - v.get("last",0) < HEARTBEAT_TIMEOUT]

        sent_agents = []
        for aid in targets:
            a = agents.get(aid)
            if a and a.get("ws"):
                try:
                    await a["ws"].send(json.dumps({"type": "exec", "cmd": cmd, "agents": [aid]}))
                    sent_agents.append(aid)
                except Exception as e:
                    print(f"[Controller] 下发命令到 Agent {aid} 失败: {e}")

    if sent_agents:
        print(f"[Controller] 命令 '{cmd}' 已下发到 Agent(s): {', '.join(sent_agents)}")
    else:
        print("[Controller] 未找到可用 Agent 发送命令")

async def handle_ui(ws):
    ui_clients.add(ws)
    await broadcast_ui_client_count()  # 新增：连接数广播
    print("[Controller] UI 客户端连接")
    try:
        async with agents_lock:
            now = time.time()
            snapshot = {"type": "full_snapshot",
                        "agents": [agent_info(aid, v, now) for aid, v in agents.items()]}
        await ws.send(json.dumps(snapshot))

        async for msg in ws:
            try:
                data = json.loads(msg)
            except:
                continue

            if data.get("type") == "exec":
                await handle_exec_command(data)

            elif data.get("type") == "remove" and data.get("auth") == AUTH_TOKEN:
                aid = data.get("agent_id")
                async with agents_lock:
                    if aid in agents:
                        agents.pop(aid)
                        print(f"[Controller] Agent {aid} 已被删除")
                        await broadcast_ui({"type": "agent_removed", "agent_id": aid})

    except Exception as e:
        print(f"[Controller] UI 异常: {e}")
    finally:
        ui_clients.discard(ws)
        await broadcast_ui_client_count()  # 新增：断开时也广播
        print("[Controller] UI 客户端断开")

# ---------------- 心跳 ----------------
async def heartbeat():
    """纯时间判断在线/离线，不发送 ping"""
    while True:
        now = time.time()
        async with agents_lock:
            for aid, v in agents.items():
                last_seen = v.get("last", 0)
                online_before = v.get("online", True)

                if last_seen and (now - last_seen >= HEARTBEAT_TIMEOUT):
                    if online_before:
                        v["online"] = False
                        asyncio.create_task(broadcast_ui({"type": "agent_status", "agent_id": aid, "online": False}))
                        print(f"[Heartbeat] Agent {aid} 超过 {HEARTBEAT_TIMEOUT}s 未更新，标记离线")
                else:
                    if not online_before:
                        v["online"] = True
                        asyncio.create_task(broadcast_ui({"type": "agent_status", "agent_id": aid, "online": True}))
                        print(f"[Heartbeat] Agent {aid} 收到上报，标记在线")
        await asyncio.sleep(5)

# ---------------- HTTP 前端 ----------------
class ThreadedHTTP(ThreadingMixIn, HTTPServer):
    daemon_threads = True

def start_http():
    dir_path = os.path.dirname(os.path.abspath(__file__))
    ThreadedHTTP(("", HTTP_PORT),
                 lambda *a, **kw: SimpleHTTPRequestHandler(*a, directory=dir_path, **kw)).serve_forever()
    print(f"[Controller] HTTP 前端启动在端口 {HTTP_PORT}")

# ---------------- 主程序 ----------------
async def main():
    await websockets.serve(handle_agent, "0.0.0.0", AGENT_PORT)
    print(f"[Controller] Agent server listening on port {AGENT_PORT}")

    await websockets.serve(handle_ui, "0.0.0.0", UI_PORT)
    print(f"[Controller] UI server listening on port {UI_PORT}")

    Thread(target=start_http, daemon=True).start()
    asyncio.create_task(heartbeat())

    await asyncio.Future()  # 永远阻塞

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[Controller] 退出")
