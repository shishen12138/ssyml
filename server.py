#!/usr/bin/env python3
import asyncio, websockets, json, time, os
from http.server import SimpleHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from threading import Thread

# ---------------- 配置 ----------------
UI_PORT, AGENT_PORT, HTTP_PORT = 8000, 9002, 8080
HEARTBEAT_TIMEOUT = 30
AUTH_TOKEN = "super-secret-token-CHANGE_ME"

# ---------------- 全局变量 ----------------
agents = {}  # agent_id -> {ws, last, info, online}
ui_clients = set()
agents_lock = asyncio.Lock()

# ---------------- 工具函数 ----------------
def agent_info(aid, v, now=None):
    now = now or time.time()
    online = bool(v.get("ws") and (now - v.get("last",0) < HEARTBEAT_TIMEOUT))
    info = v.get("info", {}).copy() if v.get("info") else {}
    info.update({"agent_id": aid, "online": online})
    return info

async def broadcast_ui(data):
    msg = json.dumps(data)
    for u in list(ui_clients):
        try: await u.send(msg)
        except: ui_clients.discard(u)

# ---------------- Agent 处理 ----------------
async def handle_agent(ws):
    aid = None
    print("[Controller] 新 agent 连接")
    try:
        async for msg in ws:
            try: data = json.loads(msg)
            except: continue

            # 注册
            if data.get("type")=="register":
                aid = data.get("agent_id")
                if not aid: continue
                async with agents_lock:
                    agents[aid] = {"ws": ws, "last": time.time(), "info": {}, "online": True}
                print(f"[Controller] Agent 注册 ID={aid}")
                await broadcast_ui({"type":"agent_add","agent":agent_info(aid, agents[aid])})

            # 状态更新
            elif data.get("type")=="update" and aid:
                async with agents_lock:
                    a = agents.get(aid)
                    if a: a.update({"last":time.time(),"online":True,"info":data})

                # ✅ 打印完整上报信息
                print(f"[Controller] Agent {aid} 上报: {json.dumps(data, ensure_ascii=False)}")

                await broadcast_ui({"type":"agent_update","agent":agent_info(aid, agents[aid])})

            # 命令返回
            elif data.get("type")=="cmd_result" and aid:
                print(f"[Controller] Agent {aid} 执行命令返回: {json.dumps(data.get('payload'), ensure_ascii=False)}")
                await broadcast_ui({"type":"cmd_result","agent_id":aid,"payload":data.get("payload")})

    except Exception as e:
        print(f"[Controller] Agent {aid} 异常: {e}")
    finally:
        if aid:
            async with agents_lock:
                a = agents.get(aid)
                if a: a["ws"]=None
            await broadcast_ui({"type":"agent_status","agent_id":aid,"online":False})
            print(f"[Controller] Agent {aid} 断开")

# ---------------- UI 处理 ----------------
async def handle_ui(ws):
    ui_clients.add(ws)
    print("[Controller] UI 客户端连接")
    try:
        # 发送全量快照
        async with agents_lock:
            now = time.time()
            snapshot = {"type":"full_snapshot","agents":[agent_info(aid,v,now) for aid,v in agents.items()]}
        await ws.send(json.dumps(snapshot))

        async for msg in ws:
            try: data = json.loads(msg)
            except: continue
            # 执行命令
            if data.get("type")=="exec" and data.get("auth")==AUTH_TOKEN:
                cmd = data.get("cmd")
                targets = data.get("agents") or []
                async with agents_lock:
                    for aid in targets:
                        a = agents.get(aid)
                        if a and a.get("ws"):
                            try: 
                                await a["ws"].send(json.dumps({"type":"exec","cmd":cmd}))
                                print(f"[Controller] 向 Agent {aid} 下发命令: {cmd}")
                            except: pass

            # 删除 agent
            elif data.get("type")=="remove" and data.get("auth")==AUTH_TOKEN:
                aid = data.get("agent_id")
                async with agents_lock:
                    if aid in agents:
                        agents.pop(aid)
                        print(f"[Controller] Agent {aid} 已被删除")
                        # 通知 UI 移除
                        await broadcast_ui({"type":"agent_removed","agent_id":aid})

    except Exception as e:
        print(f"[Controller] UI 异常: {e}")
    finally:
        ui_clients.discard(ws)
        print("[Controller] UI 客户端断开")

# ---------------- 心跳 ----------------
async def heartbeat():
    while True:
        now=time.time()
        async with agents_lock:
            for aid,v in list(agents.items()):
                online=bool(v.get("ws") and (now-v.get("last",0)<HEARTBEAT_TIMEOUT))
                if v.get("online")!=online:
                    v["online"]=online
                    asyncio.create_task(broadcast_ui({"type":"agent_status","agent_id":aid,"online":online}))
                    print(f"[Controller] Agent {aid} 在线状态更新: {online}")
        await asyncio.sleep(5)

# ---------------- HTTP 前端 ----------------
class ThreadedHTTP(ThreadingMixIn, HTTPServer): daemon_threads=True
def start_http():
    dir_path = os.path.dirname(os.path.abspath(__file__))
    ThreadedHTTP(("", HTTP_PORT), lambda *a, **kw: SimpleHTTPRequestHandler(*a, directory=dir_path, **kw)).serve_forever()
    print(f"[Controller] HTTP 前端启动在端口 {HTTP_PORT}")

# ---------------- 主程序 ----------------
async def main():
    # 启动 Agent WebSocket 服务
    await websockets.serve(handle_agent, "0.0.0.0", AGENT_PORT)
    print(f"[Controller] Agent server listening on port {AGENT_PORT}")

    # 启动 UI WebSocket 服务
    await websockets.serve(handle_ui, "0.0.0.0", UI_PORT)
    print(f"[Controller] UI server listening on port {UI_PORT}")

    # 启动 HTTP 前端线程
    Thread(target=start_http, daemon=True).start()

    # 启动心跳检测任务
    asyncio.create_task(heartbeat())

    # 保持主线程运行
    await asyncio.Future()  # 永远阻塞，保持服务运行

if __name__=="__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("[Controller] 退出")
