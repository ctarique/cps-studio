import hashlib
import http.client
import json
import platform
import secrets
import subprocess
import socket
import threading
import time
from pathlib import Path
from .status_rtt import StatusRTT
from .protocol import (
    MAX_COMMAND_SEQUENCE,
    car_work,
    parse_car_status,
    parse_status,
    sign,
    verify,
    work,
)

class TransportError(RuntimeError):
    def __init__(self,code,uncertain=False):
        self.code=code;self.uncertain=uncertain
        super().__init__(code)

def verify_wifi_route(config):
    if platform.system()!="Linux" or not Path("/sys/class/net",config.wifi_interface,"wireless").exists():
        raise TransportError("WIFI_INTERFACE_UNAVAILABLE")
    try:
        p=subprocess.run(["ip","-j","route","get",config.device_host],capture_output=True,timeout=1,check=True)
        routes=json.loads(p.stdout)
        if len(routes)!=1 or routes[0].get("dev")!=config.wifi_interface:
            raise TransportError("WIFI_ROUTE_MISMATCH")
    except (OSError,ValueError,subprocess.SubprocessError):
        raise TransportError("WIFI_ROUTE_UNAVAILABLE") from None

class HTTPTransport:
    def __init__(self,config,route_check=verify_wifi_route):
        self.config=config;self.route_check=route_check
    def exchange(self,method,path,body,context):
        if self.config.mode=="wifi":self.route_check(self.config)
        conn=http.client.HTTPConnection(self.config.device_host,self.config.device_port,timeout=self.config.timeout)
        deadline=time.monotonic()+self.config.timeout
        timer=None
        try:
            conn.connect()
            wire_socket=conn.sock
            def abort():
                try:wire_socket.shutdown(socket.SHUT_RDWR)
                except OSError:pass
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TransportError("TRANSPORT_DEADLINE",method=="POST")
            timer=threading.Timer(remaining,abort);timer.daemon=True;timer.start()
            headers={"Connection":"close","Content-Type":"text/plain"}
            if method=="POST":headers["X-Sentinel-Signature"]=sign(self.config.device_key,"POST\n/v1/work\n",body)
            conn.request(method,path,body=body if method=="POST" else None,headers=headers)
            response=conn.getresponse()
            raw=response.read(385)
            if response.status!=200:raise TransportError("DEVICE_HTTP_REJECTED",method=="POST")
            if not verify(self.config.device_key,context,raw,response.getheader("X-Sentinel-Signature")):
                raise TransportError("DEVICE_AUTHENTICATION_FAILED",method=="POST")
            try:status=parse_status(raw)
            except (ValueError,UnicodeError):raise TransportError("DEVICE_RESPONSE_INVALID",method=="POST") from None
            expected="DEVICE" if self.config.mode=="wifi" else "SIMULATOR"
            if status["origin"]!=expected:raise TransportError("DEVICE_ORIGIN_MISMATCH",method=="POST")
            return status
        except (OSError,http.client.HTTPException):
            raise TransportError("TRANSPORT_UNAVAILABLE",method=="POST") from None
        finally:
            if timer:timer.cancel()
            conn.close()
    def status(self):
        nonce=secrets.token_hex(16)
        return self.exchange("GET","/v1/status?nonce="+nonce,b"","STATUS\n"+nonce+"\n")
    def command(self,rid,action,program="",before_dispatch=None):
        before=self.status()
        if before["next_seq"]>MAX_COMMAND_SEQUENCE:
            raise TransportError("DEVICE_SEQUENCE_EXHAUSTED")
        if action=="RUN" and before["state"]=="RUNNING":
            raise TransportError("DEVICE_BUSY")
        if before_dispatch is not None:
            # The caller can retain this authenticated preflight before mutation.
            # Pass a copy so recording cannot change the wire freshness binding.
            before_dispatch(dict(before))
        body=work(before["boot"],before["next_seq"],rid,action,program)
        result=self.exchange("POST","/v1/work",body,"RESULT\n"+hashlib.sha256(body).hexdigest()+"\n")
        if result["boot"]!=before["boot"] or result["next_seq"]!=before["next_seq"]+1 or result["run_id"]!=rid:
            raise TransportError("DEVICE_RESPONSE_MISMATCH",True)
        if action=="RUN" and result["program_sha256"]!=hashlib.sha256(program.encode()).hexdigest():
            raise TransportError("DEVICE_PROGRAM_MISMATCH",True)
        if action=="RUN" and (result["state"] not in ("RUNNING","COMPLETE") or
                              (any(op.startswith("L") for op in program.split(",")) and not result["gpio_enabled"])):
            raise TransportError("DEVICE_RUN_INCONSISTENT",True)
        if action=="RESET" and (result["state"]!="IDLE" or result["led_reported"]!=0):
            raise TransportError("DEVICE_RESET_INCONSISTENT",True)
        if action=="STOP" and (result["state"]!="STOPPED" or result["led_reported"]!=0):
            raise TransportError("DEVICE_STOP_INCONSISTENT",True)
        return result


class CARHTTPTransport:
    """Authenticated Gateway transport for CAR-01.

    CAR-01 uses its own endpoint and credential. Browser-facing callers
    provide only fixed semantic actions; GPIO identities and durations
    never cross this interface.
    """

    def __init__(self,config,route_check=None):
        self.config=config
        self.route_check=route_check or self._verify_route
        self._status_rtt=StatusRTT()

    def _configured(self):
        return bool(
            self.config.mode=="wifi"
            and self.config.car_device_host
            and self.config.car_device_key
        )

    def _verify_route(self,config):
        if not self._configured():
            raise TransportError("CAR_NOT_CONFIGURED")

        if (platform.system()!="Linux"
                or not Path(
                    "/sys/class/net",
                    config.wifi_interface,
                    "wireless"
                ).exists()):
            raise TransportError("WIFI_INTERFACE_UNAVAILABLE")

        try:
            p=subprocess.run(
                [
                    "ip",
                    "-j",
                    "route",
                    "get",
                    config.car_device_host,
                ],
                capture_output=True,
                timeout=1,
                check=True
            )
            routes=json.loads(p.stdout)

            if (len(routes)!=1
                    or routes[0].get("dev")!=config.wifi_interface):
                raise TransportError("WIFI_ROUTE_MISMATCH")

        except TransportError:
            raise
        except (OSError,ValueError,subprocess.SubprocessError):
            raise TransportError("WIFI_ROUTE_UNAVAILABLE") from None

    def exchange(self,method,path,body,context):
        if not self._configured():
            raise TransportError("CAR_NOT_CONFIGURED")

        self.route_check(self.config)

        conn=http.client.HTTPConnection(
            self.config.car_device_host,
            self.config.car_device_port,
            timeout=self.config.timeout
        )

        deadline=time.monotonic()+self.config.timeout
        timer=None

        try:
            conn.connect()
            wire_socket=conn.sock

            def abort():
                try:
                    wire_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            remaining=deadline-time.monotonic()

            if remaining<=0:
                raise TransportError(
                    "TRANSPORT_DEADLINE",
                    method=="POST"
                )

            timer=threading.Timer(remaining,abort)
            timer.daemon=True
            timer.start()

            headers={
                "Connection":"close",
                "Content-Type":"text/plain"
            }

            if method=="POST":
                headers["X-Sentinel-Signature"]=sign(
                    self.config.car_device_key,
                    "POST\n/v1/work\n",
                    body
                )

            conn.request(
                method,
                path,
                body=body if method=="POST" else None,
                headers=headers
            )

            response=conn.getresponse()
            raw=response.read(385)

            if response.status!=200:
                raise TransportError(
                    "DEVICE_HTTP_REJECTED",
                    method=="POST"
                )

            if not verify(
                self.config.car_device_key,
                context,
                raw,
                response.getheader("X-Sentinel-Signature")
            ):
                raise TransportError(
                    "DEVICE_AUTHENTICATION_FAILED",
                    method=="POST"
                )

            try:
                status=parse_car_status(raw)
            except (ValueError,UnicodeError):
                raise TransportError(
                    "DEVICE_RESPONSE_INVALID",
                    method=="POST"
                ) from None

            if status["origin"]!="DEVICE":
                raise TransportError(
                    "DEVICE_ORIGIN_MISMATCH",
                    method=="POST"
                )

            return status

        except TransportError:
            raise
        except (OSError,http.client.HTTPException):
            raise TransportError(
                "TRANSPORT_UNAVAILABLE",
                method=="POST"
            ) from None

        finally:
            if timer:
                timer.cancel()
            conn.close()

    def camera(self):
        """Fetch one authenticated bounded JPEG from CAR-01."""

        if not self._configured():
            raise TransportError("CAR_NOT_CONFIGURED")

        self.route_check(self.config)

        nonce=secrets.token_hex(16)

        conn=http.client.HTTPConnection(
            self.config.car_device_host,
            self.config.car_device_port,
            timeout=self.config.timeout
        )

        deadline=time.monotonic()+self.config.timeout
        timer=None

        try:
            conn.connect()
            wire_socket=conn.sock

            def abort():
                try:
                    wire_socket.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            remaining=deadline-time.monotonic()

            if remaining<=0:
                raise TransportError(
                    "TRANSPORT_DEADLINE"
                )

            timer=threading.Timer(
                remaining,
                abort
            )

            timer.daemon=True
            timer.start()

            conn.request(
                "GET",
                "/v1/camera?nonce="+nonce,
                headers={
                    "Connection":"close"
                }
            )

            response=conn.getresponse()

            if response.status==409:
                raise TransportError(
                    "CAR_CAMERA_BUSY"
                )

            if response.status==503:
                raise TransportError(
                    "CAR_CAMERA_UNAVAILABLE"
                )

            if response.status!=200:
                raise TransportError(
                    "DEVICE_HTTP_REJECTED"
                )

            if response.getheader("Transfer-Encoding") is not None:
                raise TransportError(
                    "DEVICE_CAMERA_RESPONSE_INVALID"
                )

            if response.getheader("Content-Type")!="image/jpeg":
                raise TransportError(
                    "DEVICE_CAMERA_RESPONSE_INVALID"
                )

            length_text=response.getheader(
                "Content-Length"
            )

            digest=response.getheader(
                "X-Sentinel-Frame-SHA256"
            )

            signature=response.getheader(
                "X-Sentinel-Signature"
            )

            if (
                not isinstance(length_text,str)
                # The maximum supported frame is 65536 bytes (five digits).
                # Bound the header before scanning or converting untrusted
                # decimal text, including Python's integer digit limit.
                or not 1<=len(length_text)<=5
                or not length_text.isascii()
                or not length_text.isdigit()
                or (
                    len(length_text)>1
                    and length_text.startswith("0")
                )
            ):
                raise TransportError(
                    "DEVICE_CAMERA_RESPONSE_INVALID"
                )

            length=int(length_text)

            if not 1<=length<=65536:
                raise TransportError(
                    "DEVICE_CAMERA_RESPONSE_INVALID"
                )

            if (
                not isinstance(digest,str)
                or len(digest)!=64
                or any(
                    c not in "0123456789abcdef"
                    for c in digest
                )
            ):
                raise TransportError(
                    "DEVICE_CAMERA_RESPONSE_INVALID"
                )

            frame=response.read(
                65537
            )

            if len(frame)!=length:
                raise TransportError(
                    "DEVICE_CAMERA_LENGTH_MISMATCH"
                )

            computed=hashlib.sha256(
                frame
            ).hexdigest()

            if computed!=digest:
                raise TransportError(
                    "DEVICE_CAMERA_DIGEST_MISMATCH"
                )

            context=(
                "CAMERA\n"
                +nonce
                +"\n"
                +computed
                +"\n"
                +str(length)
                +"\n"
            )

            if not verify(
                self.config.car_device_key,
                context,
                b"",
                signature
            ):
                raise TransportError(
                    "DEVICE_AUTHENTICATION_FAILED"
                )

            return {
                "jpeg":frame,
                "sha256":computed,
                "length":length,
                "origin":"DEVICE",
            }

        except TransportError:
            raise

        except (
            OSError,
            http.client.HTTPException
        ):
            raise TransportError(
                "TRANSPORT_UNAVAILABLE"
            ) from None

        finally:
            if timer:
                timer.cancel()

            conn.close()


    def status(self):
        # Time the existing nonce-bound authenticated status transaction only.
        # The measurement includes route/connection/request/response validation;
        # it is application RTT, not an ICMP ping or actuator-response time.
        started=self._status_rtt.start()
        nonce=secrets.token_hex(16)

        try:
            result=self.exchange(
                "GET",
                "/v1/status?nonce="+nonce,
                b"",
                "STATUS\n"+nonce+"\n"
            )
        except TransportError:
            self._status_rtt.failed()
            raise

        self._status_rtt.succeeded(started)
        return result

    def status_rtt(self):
        """Return memory-only timing without making a device request."""
        return self._status_rtt.snapshot(available=self._configured())

    def command(self,rid,action,before_dispatch=None):
        before=self.status()

        if before["next_seq"]>MAX_COMMAND_SEQUENCE:
            raise TransportError("DEVICE_SEQUENCE_EXHAUSTED")

        if action!="STOP" and before["state"]=="RUNNING":
            raise TransportError("DEVICE_BUSY")

        if before["state"]=="FAULT" and action!="STOP":
            raise TransportError("DEVICE_NOT_READY")

        if before_dispatch is not None:
            # Retain authenticated preflight before any physical mutation.
            before_dispatch(dict(before))

        body=car_work(
            before["boot"],
            before["next_seq"],
            rid,
            action
        )

        result=self.exchange(
            "POST",
            "/v1/work",
            body,
            "RESULT\n"+hashlib.sha256(body).hexdigest()+"\n"
        )

        if (
            result["boot"]!=before["boot"]
            or result["next_seq"]!=before["next_seq"]+1
            or result["run_id"]!=rid
        ):
            raise TransportError(
                "DEVICE_RESPONSE_MISMATCH",
                True
            )

        if result["last_action"]!=action:
            raise TransportError(
                "DEVICE_ACTION_MISMATCH",
                True
            )

        if action in ("MOTOR_A_TEST","MOTOR_A_CW_TEST","MOTOR_A_CCW_TEST"):
            valid=(
                (
                    result["state"]=="RUNNING"
                    and result["motor_a_active"]
                    and not result["motor_b_active"]
                )
                or
                (
                    result["state"]=="COMPLETE"
                    and not result["motor_a_active"]
                    and not result["motor_b_active"]
                )
            )

            if not valid:
                raise TransportError(
                    "DEVICE_CAR_RESULT_INCONSISTENT",
                    True
                )

        elif action in ("MOTOR_B_TEST","MOTOR_B_CW_TEST","MOTOR_B_CCW_TEST"):
            valid=(
                (
                    result["state"]=="RUNNING"
                    and result["motor_b_active"]
                    and not result["motor_a_active"]
                )
                or
                (
                    result["state"]=="COMPLETE"
                    and not result["motor_a_active"]
                    and not result["motor_b_active"]
                )
            )

            if not valid:
                raise TransportError(
                    "DEVICE_CAR_RESULT_INCONSISTENT",
                    True
                )

        elif action=="STOP":
            if (
                result["state"]!="STOPPED"
                or result["motor_a_active"]
                or result["motor_b_active"]
            ):
                raise TransportError(
                    "DEVICE_STOP_INCONSISTENT",
                    True
                )

        return result
