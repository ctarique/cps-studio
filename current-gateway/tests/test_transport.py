import hashlib
import http.client
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from gateway.config import Config
from gateway.protocol import parse_status,sign,verify,work
from gateway.simulator import Simulator,make_server
from gateway.transport import HTTPTransport,TransportError,verify_wifi_route

class TransportTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.cfg=Config(
            data_dir=Path(self.tmp.name),
            admin_token="2"*64,
            device_key="3"*64,
            mode="simulator_http",
        )
        self.sim=Simulator();self.server=make_server(self.cfg.device_key,sim=self.sim)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.transport=HTTPTransport(replace(self.cfg,device_port=self.server.server_port))
    def tearDown(self):self.server.shutdown();self.server.server_close();self.thread.join();self.tmp.cleanup()
    def post_raw(self,body,signature=None):
        c=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=2)
        c.request("POST","/v1/work",body,{"X-Sentinel-Signature":signature or sign(self.cfg.device_key,"POST\n/v1/work\n",body)})
        r=c.getresponse();code=r.status;r.read();c.close();return code
    def test_real_http_contract(self):
        s=self.transport.status();self.assertEqual(s["origin"],"SIMULATOR")
        r=self.transport.command("a"*32,"RUN","L1,W100,L0")
        self.assertEqual(r["run_id"],"a"*32);self.assertEqual(r["next_seq"],2)
        r=self.transport.command("b"*32,"STOP");self.assertEqual(r["state"],"STOPPED");self.assertEqual(r["led_reported"],0)
        self.assertEqual(self.transport.command("c"*32,"RESET")["state"],"IDLE")
    def test_replay_rejected(self):
        body=work(self.sim.boot,1,"a"*32,"RUN","S0")
        self.assertEqual(self.post_raw(body),200);self.assertEqual(self.post_raw(body),409)
    def test_wrong_key_rejected_without_action(self):
        body=work(self.sim.boot,1,"a"*32,"RUN","S0")
        self.assertEqual(self.post_raw(body,"0"*64),409);self.assertEqual(self.sim.seq,1)
    def test_old_boot_rejected(self):
        body=work("0"*32,1,"a"*32,"RUN","S0")
        self.assertEqual(self.post_raw(body),409);self.assertEqual(self.sim.seq,1)
    def test_bad_program_rejected(self):
        for program in ("L1","W9999","L0,","S1"):
            self.assertEqual(self.post_raw(work(self.sim.boot,1,"a"*32,"RUN",program)),409)
    def test_wrong_response_key_rejected(self):
        self.transport.config=replace(self.transport.config,device_key="4"*64)
        with self.assertRaisesRegex(TransportError,"DEVICE_AUTHENTICATION_FAILED"):self.transport.status()
    def test_response_nonce_binding(self):
        body=self.sim.raw_status();sig=sign(self.cfg.device_key,"STATUS\n"+"a"*32+"\n",body)
        self.assertFalse(verify(self.cfg.device_key,"STATUS\n"+"b"*32+"\n",body,sig))
    def test_response_schema_rejects_private_payload(self):
        for raw in (b"private address",b"x"*385,self.sim.raw_status().replace(b"|IDLE|",b"|SECRET|")):
            with self.assertRaises(ValueError):parse_status(raw)
    def test_wifi_will_not_accept_simulator_origin(self):
        cfg=replace(self.transport.config,mode="wifi",device_host="192.168.99.2")
        transport=HTTPTransport(cfg,route_check=lambda c:None)
        original=http.client.HTTPConnection
        with patch("gateway.transport.http.client.HTTPConnection",side_effect=lambda *a,**k:original("127.0.0.1",self.server.server_port,timeout=2)):
            with self.assertRaisesRegex(TransportError,"DEVICE_ORIGIN_MISMATCH"):transport.status()
    def test_route_failure_prevents_network(self):
        cfg=replace(self.cfg,mode="wifi",device_host="192.168.99.2")
        transport=HTTPTransport(cfg,route_check=lambda c:(_ for _ in ()).throw(TransportError("WIFI_ROUTE_MISMATCH")))
        with patch("gateway.transport.http.client.HTTPConnection") as connection:
            with self.assertRaises(TransportError):transport.status()
            connection.assert_not_called()
    def test_gpio_disabled(self):
        self.sim.enabled=False
        with self.assertRaises(TransportError):self.transport.command("a"*32,"RUN","L1,W10,L0")
        self.assertEqual(self.transport.command("b"*32,"RUN","S0")["state"],"COMPLETE")
    def test_simulator_timing_and_stop(self):
        now=[1.0];s=Simulator(clock=lambda:now[0]);s.command("a"*32,"RUN","L1,W100,L0")
        self.assertEqual(s.status()["led_reported"],1);now[0]+=0.1;self.assertEqual(s.status()["state"],"COMPLETE")

    def test_gateway_through_real_http_fixture(self):
        from gateway.app import create_app

        app=create_app(self.transport.config,self.transport)
        client=app.test_client()

        workstation={"Origin":"http://localhost"}
        admin={
            "Origin":"http://localhost",
            "X-Sentinel-Token":self.cfg.admin_token,
        }

        submitted=client.post(
            "/api/submissions",
            json={
                "source":"void experiment(){status();}",
                "experiment":"led-status-v1",
            },
            headers=workstation,
        )

        self.assertEqual(submitted.status_code,201,submitted.json)
        self.assertEqual(submitted.json["state"],"READY_TO_RUN")

        rid=submitted.json["run_id"]

        unlocked=client.post(
            "/api/admin/recovery",
            json={"action":"UNLOCK"},
            headers=admin,
        )
        self.assertEqual(unlocked.status_code,200,unlocked.json)
        self.assertFalse(unlocked.json["locked"])

        # Unlock is a recovery boundary: preserve the old attempt as invalidated
        # and require a fresh Check before issuing new run-bound authority.
        self.assertEqual(app.extensions["ledger"].run(rid)["state"],"INVALIDATED")
        submitted=client.post(
            "/api/submissions",
            json={"source":"void experiment(){status();}","experiment":"led-status-v1"},
            headers=workstation,
        )
        self.assertEqual(submitted.status_code,201,submitted.json)
        rid=submitted.json["run_id"]

        executed=client.post(
            f"/api/runs/{rid}/execute",
            json={},
            headers=workstation,
        )
        self.assertEqual(executed.status_code,200,executed.json)

        record=app.extensions["ledger"].export(rid)

        self.assertTrue(
            all(
                e["mode"]=="simulator_http"
                for e in record["events"]
            )
        )

        app.extensions["ledger"].db.close()
    def test_total_network_deadline(self):
        import socketserver
        class Slow(socketserver.BaseRequestHandler):
            def handle(self):
                self.request.recv(4096)
                try:
                    for b in b"HTTP/1.1 200 OK\r\nContent-Length: 300\r\n\r\n":
                        self.request.sendall(bytes([b]));time.sleep(.02)
                except OSError:pass
        server=socketserver.TCPServer(("127.0.0.1",0),Slow)
        thread=threading.Thread(target=server.handle_request,daemon=True);thread.start()
        t=HTTPTransport(replace(self.cfg,device_port=server.server_address[1],timeout=.15))
        start=time.monotonic()
        with self.assertRaises(TransportError):t.status()
        self.assertLess(time.monotonic()-start,.75)
        thread.join(2);server.server_close()
    def test_simulator_runtime_deadline(self):
        now=[0.0];s=Simulator(clock=lambda:now[0]);s.command("a"*32,"RUN","L1,W1000,L0")
        now[0]=6;self.assertEqual(s.status()["state"],"STOPPED");self.assertFalse(s.led)

    def test_signed_impossible_status_rejected(self):
        original=self.sim.raw_status
        for fields in ((b"|IDLE|0|1|",b"|STOPPED|1|1|"),
                       (b"|IDLE|0|1|",b"|RUNNING|1|0|")):
            with self.subTest(fields=fields):
                self.sim.raw_status=lambda:original().replace(*fields)
                with self.assertRaisesRegex(TransportError,"DEVICE_RESPONSE_INVALID"):
                    self.transport.status()
        self.sim.raw_status=original

    def test_signed_run_state_and_gpio_consistency(self):
        original=self.sim.command
        for field,value in (("state","IDLE"),("state","STOPPED"),("enabled",False)):
            with self.subTest(field=field,value=value):
                def changed(rid,action,program=""):
                    result=original(rid,action,program)
                    if action=="RUN":
                        setattr(self.sim,field,value)
                        self.sim.led=0
                    return result
                self.sim.command=changed
                with self.assertRaisesRegex(TransportError,"DEVICE_RUN_INCONSISTENT") as caught:
                    self.transport.command("a"*32,"RUN","L1,W100,L0")
                self.assertTrue(caught.exception.uncertain)
                self.sim.command=original;self.sim.enabled=True
                original("b"*32,"RESET")

    def test_signed_command_identity_and_program_binding(self):
        original=self.sim.command
        for field,value,code in (("boot","c"*32,"DEVICE_RESPONSE_MISMATCH"),
                                 ("seq",20,"DEVICE_RESPONSE_MISMATCH"),
                                 ("rid","c"*32,"DEVICE_RESPONSE_MISMATCH"),
                                 ("digest","c"*64,"DEVICE_PROGRAM_MISMATCH")):
            with self.subTest(field=field):
                before=getattr(self.sim,field)
                def changed(rid,action,program=""):
                    result=original(rid,action,program)
                    if action=="RUN":setattr(self.sim,field,value)
                    return result
                self.sim.command=changed
                with self.assertRaisesRegex(TransportError,code) as caught:
                    self.transport.command("a"*32,"RUN","S0")
                self.assertTrue(caught.exception.uncertain)
                self.sim.command=original;setattr(self.sim,field,before)
                original("b"*32,"RESET")

    def test_result_signature_is_bound_to_request(self):
        body=self.sim.raw_status()
        first=work(self.sim.boot,1,"a"*32,"RUN","S0")
        second=work(self.sim.boot,1,"b"*32,"RUN","S0")
        signature=sign(self.cfg.device_key,"RESULT\n"+hashlib.sha256(first).hexdigest()+"\n",body)
        self.assertFalse(verify(self.cfg.device_key,"RESULT\n"+hashlib.sha256(second).hexdigest()+"\n",body,signature))

    def test_simulator_rejects_duplicate_framing_without_mutation(self):
        body=work(self.sim.boot,1,"a"*32,"RUN","S0")
        for duplicate in ("Content-Length","X-Sentinel-Signature"):
            with self.subTest(duplicate=duplicate):
                c=http.client.HTTPConnection("127.0.0.1",self.server.server_port,timeout=2)
                c.putrequest("POST","/v1/work")
                headers={"Content-Length":str(len(body)),
                         "X-Sentinel-Signature":sign(self.cfg.device_key,"POST\n/v1/work\n",body)}
                for name,value in headers.items():c.putheader(name,value)
                c.putheader(duplicate,headers[duplicate]);c.endheaders(body)
                response=c.getresponse();code=response.status;response.read();c.close()
                self.assertEqual(code,400);self.assertEqual(self.sim.seq,1)

    def test_simulator_header_and_body_trickles_have_absolute_deadline(self):
        import socket
        body=work(self.sim.boot,1,"a"*32,"RUN","S0")
        signature=sign(self.cfg.device_key,"POST\n/v1/work\n",body)
        partials=(b"GET /v1/status?nonce="+b"a"*32+b" HTTP/1.1\r\nX-Test: ",
                  ("POST /v1/work HTTP/1.1\r\nContent-Length: "+str(len(body))+
                   "\r\nX-Sentinel-Signature: "+signature+"\r\n\r\n").encode())
        for partial in partials:
            with self.subTest(stage="header" if partial.startswith(b"GET") else "body"):
                stalled=socket.create_connection(("127.0.0.1",self.server.server_port),timeout=2)
                start=time.monotonic()
                try:
                    stalled.sendall(partial)
                    # Each byte arrives within the idle timeout; only the total deadline closes it.
                    for _ in range(12):
                        try:stalled.sendall(b" ")
                        except OSError:break
                        time.sleep(.1)
                    self.assertEqual(self.transport.status()["origin"],"SIMULATOR")
                finally:stalled.close()
                self.assertLess(time.monotonic()-start,2.5)
                self.assertEqual(self.sim.seq,1)

    def test_sequence_exhaustion_matches_firmware(self):
        self.sim.seq=99999998
        result=self.transport.command("a"*32,"RUN","S0")
        self.assertEqual(result["next_seq"],99999999)
        with self.assertRaisesRegex(TransportError,"DEVICE_SEQUENCE_EXHAUSTED"):
            self.sim.command("b"*32,"RESET")
        with self.assertRaisesRegex(TransportError,"DEVICE_SEQUENCE_EXHAUSTED"):
            self.transport.command("b"*32,"RESET")
        self.assertEqual(self.sim.seq,99999999)
