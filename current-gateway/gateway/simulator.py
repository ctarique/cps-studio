"""Deterministic in-process and HTTP fixture. Never identifies itself as a physical ESP32."""
import argparse
import hashlib
import os
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler,HTTPServer
from .protocol import HEX32,HEX64,MAX_COMMAND_SEQUENCE,sign,verify
from .transport import TransportError

class Simulator:
    def __init__(self,clock=time.monotonic,gpio_enabled=True):
        self.clock=clock;self.enabled=gpio_enabled;self.boot=secrets.token_hex(16);self.seq=1
        self.rid="0"*32;self.state="IDLE";self.led=0;self.digest="0"*64
        self.ops=[];self.pos=0;self.due=0;self.started=0;self.lock=threading.RLock()
    def tick(self):
        now=self.clock()
        if self.state=="RUNNING" and now-self.started>5.5:
            self.state="STOPPED";self.led=0
        while self.state=="RUNNING" and now>=self.due:
            if self.pos==len(self.ops):self.state="COMPLETE";self.led=0;break
            op=self.ops[self.pos];self.pos+=1
            if op[0]=="L":self.led=int(op[1:])
            elif op[0]=="W":self.due=now+int(op[1:])/1000;break
    def status(self):
        with self.lock:
            self.tick()
            return {"boot":self.boot,"next_seq":self.seq,"run_id":self.rid,"state":self.state,
                    "led_reported":self.led,"gpio_enabled":self.enabled,"program_sha256":self.digest,"origin":"SIMULATOR"}
    def command(self,rid,action,program="",before_dispatch=None):
        with self.lock:
            self.tick()
            if self.seq>MAX_COMMAND_SEQUENCE:raise TransportError("DEVICE_SEQUENCE_EXHAUSTED")
            if not HEX32.fullmatch(rid):raise TransportError("DEVICE_WORK_REJECTED")
            if action=="RUN" and self.state=="RUNNING":raise TransportError("DEVICE_BUSY")
            if before_dispatch is not None:
                before_dispatch(dict(self.status()))
            if action=="RUN":
                ops=program.split(",");total=0;last_led=None
                if self.state=="RUNNING":raise TransportError("DEVICE_BUSY")
                if not 1<=len(ops)<=32:raise TransportError("DEVICE_WORK_REJECTED")
                for op in ops:
                    if op in ("L0","L1"):
                        if not self.enabled:raise TransportError("GPIO_UNAVAILABLE")
                        last_led=op
                    elif op=="S0":pass
                    elif re.fullmatch(r"W[1-9][0-9]{1,3}",op) and 10<=int(op[1:])<=1000:total+=int(op[1:])
                    else:raise TransportError("DEVICE_WORK_REJECTED")
                if total>5000 or last_led not in (None,"L0"):raise TransportError("DEVICE_WORK_REJECTED")
                self.ops=ops;self.pos=0;self.due=self.clock();self.started=self.due;self.state="RUNNING"
                self.digest=hashlib.sha256(program.encode()).hexdigest()
            elif action in ("STOP","RESET") and not program:
                self.led=0;self.ops=[];self.state="STOPPED" if action=="STOP" else "IDLE"
                if action=="RESET":self.digest="0"*64
            else:raise TransportError("DEVICE_WORK_REJECTED")
            self.rid=rid;self.seq+=1
            return self.status()
    def raw_status(self):
        s=self.status()
        return f'SCPS1|{s["boot"]}|{s["next_seq"]}|{s["run_id"]}|{s["state"]}|{s["led_reported"]}|{int(s["gpio_enabled"])}|{s["program_sha256"]}|SIMULATOR'.encode()

def make_server(key,port=0,sim=None):
    sim=sim or Simulator()
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def handle(self):
            # Cover headers, body and response with one deadline, including slow trickles.
            self.connection.settimeout(1)
            def abort():
                try:self.connection.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            timer=threading.Timer(1,abort);timer.daemon=True;timer.start()
            try:super().handle()
            except (OSError,ValueError):pass
            finally:timer.cancel()
        def send_error(self,code,message=None,explain=None):
            self.close_connection=True
            self.send_response(code)
            self.send_header("Connection","close")
            self.send_header("Content-Length","0");self.end_headers()
        def parse_request(self):
            if not super().parse_request():return False
            lengths=self.headers.get_all("Content-Length",[])
            signatures=self.headers.get_all("X-Sentinel-Signature",[])
            size=len(self.raw_requestline)+sum(len(k)+len(v)+4 for k,v in self.headers.items())+2
            valid=(self.request_version=="HTTP/1.1" and len(self.path)<=99 and size<=1536
                   and len(self.headers)<=16 and len(lengths)<=1 and len(signatures)<=1
                   and self.headers.get("Transfer-Encoding") is None and self.headers.get("Expect") is None)
            self.body_length=0
            if lengths:
                valid=valid and bool(re.fullmatch(r"0|[1-9][0-9]{0,2}",lengths[0]))
                if valid:self.body_length=int(lengths[0]);valid=self.body_length<=512
            if signatures:valid=valid and bool(HEX64.fullmatch(signatures[0]))
            if self.command=="GET":valid=valid and not signatures and self.body_length==0
            elif self.command=="POST":valid=valid and bool(signatures) and self.body_length>0
            else:valid=False
            if not valid:self.send_error(400)
            return valid
        def reply(self,body,context):
            self.close_connection=True
            self.send_response(200)
            self.send_header("Connection","close")
            self.send_header("Content-Type","text/plain")
            self.send_header("Content-Length",str(len(body)))
            self.send_header("X-Sentinel-Signature",sign(key,context,body));self.end_headers();self.wfile.write(body)
        def do_GET(self):
            m=re.fullmatch(r"/v1/status\?nonce=([0-9a-f]{32})",self.path)
            if not m:self.send_error(404);return
            self.reply(sim.raw_status(),"STATUS\n"+m[1]+"\n")
        def do_POST(self):
            if self.path!="/v1/work":self.send_error(404);return
            try:
                body=self.rfile.read(self.body_length)
                if (len(body)!=self.body_length or any(b<32 or b>126 for b in body)
                    or not verify(key,"POST\n/v1/work\n",body,self.headers.get("X-Sentinel-Signature"))):raise ValueError()
                fields=body.decode("ascii").split("|")
                if len(fields)!=6:raise ValueError()
                ver,boot,seq,rid,action,program=fields
                if ver!="SCPS1" or boot!=sim.boot or seq!=str(sim.seq):raise ValueError()
                sim.command(rid,action,program)
                self.reply(sim.raw_status(),"RESULT\n"+hashlib.sha256(body).hexdigest()+"\n")
            except (ValueError,UnicodeError,TransportError):self.send_error(409)
    return HTTPServer(("127.0.0.1",port),Handler)

if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--port",type=int,default=8090);args=p.parse_args()
    key=os.environ.get("SENTINEL_DEVICE_KEY","")
    if not re.fullmatch(r"[0-9a-f]{64}",key):raise SystemExit("Device fixture key required.")
    print("NON_PHYSICAL HTTP simulator listening on loopback.",flush=True)
    make_server(key,args.port).serve_forever()
