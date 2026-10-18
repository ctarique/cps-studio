import hashlib
import hmac
import json
import re
import sqlite3
import threading
import time
import uuid
from functools import wraps
from contextlib import ExitStack
from flask import send_file
from .cps_slideshow import slideshow_snapshot, slide_path, SlideshowUnavailable, set_slideshow_season
from flask import Flask, jsonify, request, g, render_template, redirect
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from .evidence import Evidence, EvidenceError
from .source import prepare, SourceError
from .transport import CARHTTPTransport, HTTPTransport, TransportError
from .simulator import Simulator
from .admin_auth import AdminSessions
from .workstation_auth import WorkstationSessions
from .experiments import PROFILES, catalog, policy_reference, policy_rejections
from .lab_display import LabDisplay, DisplayError, TRACKS, catalog as track_catalog

class WorkflowError(Exception):
    def __init__(self,code,status=409):self.code=code;self.status=status

def no_duplicate_keys(pairs):
    data={}
    for k,v in pairs:
        if k in data:raise ValueError()
        data[k]=v
    return data

def create_app(config,transport=None,car_transport=None):
    app=Flask(__name__)

    # Supported deployments place the browser-facing TLS proxy in front of
    # the loopback-only application server. Trust exactly one local proxy for
    # the original scheme and host so origin checks and Secure cookies use
    # the browser-visible HTTPS origin.
    app.wsgi_app=ProxyFix(app.wsgi_app,x_proto=1)

    app.config.update(MAX_CONTENT_LENGTH=4096,MAX_FORM_MEMORY_SIZE=4096,
                      TRUSTED_HOSTS=["localhost","127.0.0.1","gateway.lab.example","sentinel-cps.local"])
    ledger=Evidence(config)
    device=transport or (Simulator() if config.mode=="simulator" else HTTPTransport(config))

    devices={"esp32-cam":device}

    if car_transport is not None:
        devices["esp32-wrover"]=car_transport
    elif config.car_device_host and config.car_device_key:
        devices["esp32-wrover"]=CARHTTPTransport(config)

    app.extensions["devices"]=devices
    mutex=threading.RLock()
    admin_sessions=AdminSessions()
    app.extensions["admin_sessions"]=admin_sessions
    workstation_sessions=WorkstationSessions()
    app.extensions["workstation_sessions"]=workstation_sessions
    state={
        "locked":True,
        "degraded":False,
        "latest_run":None,
        "latest_stage":"STARTUP_LOCKED",
        "cam_health":"NOT_CHECKED",
        "active_device_run":None,
        "cam_report":None,
        "cam_execution":None,
        "car_health":"NOT_CHECKED" if "esp32-wrover" in devices else "NOT_CONFIGURED",
        "car_report":None,
        "car_active_run":None,

        # Gateway action state, not device telemetry.
        # Set only after an authenticated JPEG has been verified.
        "car_camera_activity_until":0.0,
    }
    direct_led_owners={}

    # CAR_EXPERIMENT_SNAPSHOT_V1
    #
    # Short-lived in-memory verified JPEG cache.
    # Images are never treated as physical-observation evidence.
    car_snapshot_cache={}

    # Recent camera captures remain memory-only and workstation-scoped.
    # Retention is bounded to 15 minutes and never exceeds the
    # workstation session lifetime.
    car_snapshot_ttl=min(
        900.0,
        float(workstation_sessions.ttl),
    )

    def prune_car_snapshots():
        now=time.monotonic()

        for token,record in list(car_snapshot_cache.items()):
            if now-record["created"] > car_snapshot_ttl:
                car_snapshot_cache.pop(token,None)

        while len(car_snapshot_cache)>12:
            oldest=next(iter(car_snapshot_cache))
            car_snapshot_cache.pop(oldest,None)

    lab_display=LabDisplay()
    app.extensions["lab_display"]=lab_display
    app.extensions.update(ledger=ledger,transport=device,workflow=state,config=config,mutex=mutex)

    def twin_led_timeline(program):
        if not isinstance(program,str):
            return None

        led_state=0
        timeline=[]
        duration_ms=0

        for token in program.split(","):
            if token=="L0":
                led_state=0

            elif token=="L1":
                led_state=1

            elif token=="S0":
                continue

            elif token.startswith("W"):
                value=token[1:]

                if not value.isdigit():
                    return None

                wait_ms=int(value)

                if not 10 <= wait_ms <= 1000:
                    return None

                duration_ms += wait_ms

                if duration_ms > 5000:
                    return None

                if timeline and timeline[-1]["led"]==led_state:
                    timeline[-1]["duration_ms"] += wait_ms
                else:
                    timeline.append({
                        "led":led_state,
                        "duration_ms":wait_ms,
                    })

            else:
                return None

        return {
            "timeline":timeline,
            "duration_ms":duration_ms,
        }
    # Never automatically resume interrupted transmission or carry approval across restart.
    try:
        with ledger.db:
            for row in ledger.db.execute("SELECT id,state FROM runs WHERE state IN ('APPROVED','COMMUNICATING','READY_TO_RUN','APPROVED_EXCEPTION')").fetchall():
                new="INCOMPLETE" if row["state"]=="COMMUNICATING" else ("PREPARED" if row["state"]=="APPROVED" else "INVALIDATED")
                ledger.state(row["id"],new)
                ledger.event(row["id"],"recovery","STARTUP_INVALIDATED",
                             previous_state=row["state"],physical_observation="NOT_OBSERVED",
                             actor_role="system",actor_id=None)
    except (sqlite3.Error,EvidenceError):
        state["degraded"]=True
        lab_display.recovery()

    def event(rid,category,outcome,**detail):
        if category in ("display_presentation","recovery"):
            # Named instructor authentication can populate g.actor_id later.
            # The existing shared credential identifies a role, not a named person.
            detail.setdefault("actor_role",getattr(g,"role","system"))
            detail.setdefault("actor_id",getattr(g,"actor_id",None))
        ledger.event(rid,category,outcome,**detail)
    def invalidate_pending(initiating_rid,reason):
        # Prepared content remains immutable evidence; execution authority does not
        # survive a shared-target recovery boundary, even in the same browser.
        pending=ledger.db.execute(
            """SELECT r.id FROM runs r JOIN run_submissions s ON s.run_id=r.id
               WHERE r.state IN ('READY_TO_RUN','APPROVED_EXCEPTION')
                 AND s.device_id='esp32-cam'"""
        ).fetchall()
        for row in pending:
            ledger.state(row["id"],"INVALIDATED")
            event(row["id"],"authorization","INVALIDATED",
                  initiating_run_id=initiating_rid,reason=reason,
                  device_id="esp32-cam",new_check_required=True)
    def presentation(rid,outcome,change,**detail):
        # Durable intent precedes the in-memory screen change. This is not an
        # acknowledgement from HDMI/Chromium and never establishes physical behavior.
        event(rid,"display_presentation",outcome,presentation_only=True,
              physical_observation="NOT_OBSERVED",**detail)
        ledger.db.commit()
        change()

    def display_owner():
        if g.role=="workstation":
            return "workstation:"+g.workstation_owner_ref
        return "instructor"

    def display_scope(experiment):
        if experiment not in PROFILES:
            raise WorkflowError("EXPERIMENT_NOT_ALLOWED",422)

    def display_access():
        # The shared surface is independent of run authorization. Only its owner
        # (or an instructor) can change an occupied display.
        if state["locked"]:raise WorkflowError("GATEWAY_LOCKED",409)
        if g.role=="instructor":return
        if state["active_device_run"] is not None:
            raise WorkflowError("DISPLAY_IN_USE",409)
        snapshot=lab_display.snapshot()
        if snapshot["mode"]=="SETUP_REQUIRED":raise WorkflowError("DISPLAY_SETUP_REQUIRED",409)
        if snapshot["mode"]=="RECOVERY":raise WorkflowError("DISPLAY_RECOVERY_REQUIRED",409)
        if snapshot["mode"] not in ("IDLE","SELECT_EXPERIMENT") and not lab_display.owned_by(display_owner()):
            raise WorkflowError("DISPLAY_IN_USE",409)

    def car_workstation_access():
        """
        Require the designated workstation to own an active
        Autonomous Car display context before it can exercise
        bounded CAR controls or request camera frames.
        """

        display_scope("autonomous-car-v1")
        display_access()

        snapshot=lab_display.snapshot()

        if (
            snapshot["experiment"]!="autonomous-car"
            or snapshot["mode"] not in (
                "AUTONOMOUS_CAR_SETUP",
                "TRACK_ACTIVE",
            )
        ):
            raise WorkflowError(
                "CAR_EXPERIMENT_NOT_READY",
                409,
            )

    def led_display_owned(owner=None):
        return (lab_display.snapshot()["mode"] in ("LED_SETUP","LED_READY","LED_COMPLETE") and
                lab_display.experiment=="led-status-v1" and lab_display.owned_by(owner or display_owner()))

    def led_display_ready(rid,owner=None):
        if led_display_owned(owner):
            def ready():
                try:lab_display.bind_led_run(rid)
                except DisplayError:lab_display.recovery()
            presentation(rid,"LED_READY",ready,experiment="led-status-v1")

    def led_display_report(rid,result):
        if not lab_display.owns_run(rid):return
        r=ledger.run(rid)
        same=(r is not None and r["program"] is not None and result["run_id"]==rid and
              result["program_sha256"]==hashlib.sha256(r["program"].encode()).hexdigest())
        if not same:
            presentation(rid,"DISPLAY_RECOVERY",lab_display.recovery)
        elif result["state"]=="RUNNING":
            # Only a durably recorded, fresh correlated report extends the display.
            ledger.db.commit()
            lab_display.led_phase(rid,"RUNNING")
        elif result["state"] in ("COMPLETE","STOPPED","IDLE") and result["led_reported"]==0:
            presentation(rid,"LED_COMPLETION_REPORTED",
                         lambda:lab_display.led_phase(rid,"REPORTED_COMPLETE"),
                         experiment="led-status-v1",
                         device_state=result["state"],
                         led_reported=0)
        else:
            presentation(rid,"DISPLAY_RECOVERY",lab_display.recovery)

    def close_stopped_run(command_rid,result):
        """Link a STOP command to its authenticated prior run without relabeling it."""
        prior=result.get("preflight")
        if (not prior or result["state"]!="STOPPED" or result["led_reported"]!=0):
            return None
        stopped_rid=prior["run_id"]
        original=ledger.run(stopped_rid)
        if (not original or original["config_ref"]!=config.reference or not original["program"]
                or original["state"] not in ("COMMUNICATING","DEVICE_REPORTED","INCOMPLETE","DEVICE_REPORTED_COMPLETE")
                or prior["program_sha256"]!=hashlib.sha256(original["program"].encode()).hexdigest()):
            return None
        submission=ledger.submission(stopped_rid)
        if submission and submission["device_id"]!="esp32-cam":
            return None
        if not submission and original["program"]!="L1,W1000,W1000,W1000,W1000,W1000,L0":
            return None
        event(command_rid,"recovery","STOP_CONFIRMED",
              stopped_run_id=stopped_rid,stop_command_id=command_rid,
              previous_device_state=prior["state"],physical_observation="NOT_OBSERVED")
        event(stopped_rid,"recovery","STOP_CONFIRMED",
              stopped_run_id=stopped_rid,stop_command_id=command_rid,
              previous_device_state=prior["state"],physical_observation="NOT_OBSERVED")
        ledger.state(stopped_rid,"DEVICE_REPORTED_COMPLETE")
        direct_led_owners.pop(stopped_rid,None)
        if lab_display.owns_run(stopped_rid):
            presentation(stopped_rid,"LED_STOP_COMPLETION_REPORTED",
                         lambda:lab_display.led_phase(stopped_rid,"REPORTED_COMPLETE"),
                         stop_command_id=command_rid,device_state="STOPPED",led_reported=0)
        return stopped_rid

    def body(keys):
        if request.mimetype!="application/json":raise WorkflowError("JSON_REQUIRED",415)
        try:value=json.loads(request.get_data(),object_pairs_hook=no_duplicate_keys)
        except (ValueError,UnicodeError,RecursionError):raise WorkflowError("JSON_INVALID",400) from None
        if not isinstance(value,dict) or set(value)!=set(keys):raise WorkflowError("REQUEST_SCHEMA",400)
        return value
    def run(rid,expected=None,*,current_config=True):
        if not re.fullmatch(r"[0-9a-f]{32}",rid):raise WorkflowError("RUN_NOT_FOUND",404)
        r=ledger.run(rid)
        if not r:raise WorkflowError("RUN_NOT_FOUND",404)
        if getattr(g,"role",None)=="workstation":
            submission=ledger.submission(rid)
            if (not submission
                    or submission["access_model"]!="workstation_session"
                    or submission["owner_ref"]!=g.workstation_owner_ref):
                raise WorkflowError("RUN_NOT_FOUND",404)
        if expected and r["state"] not in expected:raise WorkflowError("WORKFLOW_ORDER")
        if current_config and r["config_ref"]!=config.reference:raise WorkflowError("CONFIGURATION_CHANGED")
        return r
    def degrade(stage="EVIDENCE_UNAVAILABLE"):
        try:ledger.db.rollback()
        except (sqlite3.Error,OSError):pass
        state.update(locked=True,degraded=True,latest_stage=stage)
        lab_display.recovery()

    def workstation_control(fn):
        @wraps(fn)
        def handler(*args,**kwargs):
            with mutex:
                g.attempt_id=uuid.uuid4().hex
                g.role="workstation"
                rid=g.attempt_id
                new_sid=None
                try:
                    # This path relies on the designated-workstation network boundary.
                    # Browser-origin checks prevent a cross-site page from driving it.
                    origin=request.headers.get("Origin")
                    expected_origin=request.host_url.rstrip("/")
                    if origin != expected_origin:
                        raise WorkflowError("ORIGIN_REQUIRED",403)
                    if request.headers.get("Sec-Fetch-Site")=="cross-site":
                        raise WorkflowError("ORIGIN_REJECTED",403)

                    sid=request.cookies.get(workstation_sessions.cookie_name,"")
                    workstation=workstation_sessions.get(sid,expected_origin)
                    new_sid=None
                    if workstation is None:
                        new_sid=workstation_sessions.create(expected_origin,sid)
                        if new_sid is None:
                            raise WorkflowError("SESSION_CAPACITY",429)
                        workstation=workstation_sessions.get(new_sid,expected_origin)
                        if workstation is None:
                            raise WorkflowError("SESSION_UNAVAILABLE",503)

                    g.workstation_owner_ref=workstation["owner_ref"]

                    if state["degraded"]:
                        return jsonify(error="EVIDENCE_UNAVAILABLE"),503

                    event(
                        rid,
                        "authorization",
                        "ACCEPTED",
                        role="workstation",
                        action=fn.__name__,
                        owner_ref=g.workstation_owner_ref,
                    )
                    ledger.db.commit()

                    result=fn(*args,**kwargs)
                    ledger.db.commit()

                    response=app.make_response(result)
                    if new_sid is not None:
                        response.set_cookie(
                            workstation_sessions.cookie_name,
                            new_sid,
                            max_age=workstation_sessions.ttl,
                            httponly=True,
                            secure=request.is_secure,
                            samesite="Strict",
                            path="/",
                        )
                    return response
                except (WorkflowError,SourceError,DisplayError,HTTPException) as error:
                    code=error.code if isinstance(error,WorkflowError) else (
                        str(error) if isinstance(error,(SourceError,DisplayError))
                        else "REQUEST_REJECTED")
                    status=error.status if isinstance(error,WorkflowError) else (
                        409 if isinstance(error,DisplayError) and str(error)=="DISPLAY_ORDER"
                        else 422 if isinstance(error,(SourceError,DisplayError))
                        else error.code)
                    try:
                        event(rid,"workflow","REJECTED",reason=code)
                        ledger.db.commit()
                    except (sqlite3.Error,EvidenceError,OSError):
                        degrade()
                        return jsonify(error="EVIDENCE_UNAVAILABLE"),503
                    response=jsonify(error=code,attempt_id=g.attempt_id)
                    if new_sid is not None:
                        response.set_cookie(
                            workstation_sessions.cookie_name,
                            new_sid,
                            max_age=workstation_sessions.ttl,
                            httponly=True,
                            secure=request.is_secure,
                            samesite="Strict",
                            path="/",
                        )
                    return response,status
                except (sqlite3.Error,EvidenceError,OSError):
                    degrade()
                    return jsonify(error="EVIDENCE_UNAVAILABLE"),503
                except Exception:
                    degrade("INTERNAL_FAILURE_LOCKED")
                    return jsonify(error="INTERNAL_FAILURE_LOCKED"),500
        return handler

    def protected(*roles,evidence_read=False):
        def decorator(fn):
            @wraps(fn)
            def handler(*args,**kwargs):
                with mutex:
                    g.attempt_id=uuid.uuid4().hex
                    requested_rid=kwargs.get("rid",g.attempt_id)
                    if not re.fullmatch(r"[0-9a-f]{32}",requested_rid):
                        requested_rid=g.attempt_id

                    new_sid=None
                    recovery_reserved=False
                    capacity_scope=ExitStack()

                    def attach(response):
                        response=app.make_response(response)
                        if new_sid is not None:
                            response.set_cookie(
                                workstation_sessions.cookie_name,
                                new_sid,
                                max_age=workstation_sessions.ttl,
                                httponly=True,
                                secure=request.is_secure,
                                samesite="Strict",
                                path="/",
                            )
                        return response

                    try:
                        role="none"
                        g.workstation_owner_ref=None

                        explicit_token="X-Sentinel-Token" in request.headers
                        token=request.headers.get("X-Sentinel-Token","")

                        if (explicit_token
                                and re.fullmatch(r"[0-9a-f]{64}",token)
                                and hmac.compare_digest(token,config.admin_token)):
                            role="instructor"

                        if not explicit_token:
                            admin_sid=request.cookies.get(
                                admin_sessions.cookie_name,""
                            )
                            if admin_sessions.authorized(
                                    admin_sid,
                                    request.host_url.rstrip("/"),
                                    request.headers.get("X-Sentinel-CSRF","")):
                                role="instructor"

                            elif "workstation" in roles:
                                expected_origin=request.host_url.rstrip("/")
                                origin=request.headers.get("Origin")

                                if request.method=="GET":
                                    if origin and origin!=expected_origin:
                                        raise WorkflowError(
                                            "ORIGIN_REJECTED",403
                                        )
                                elif origin!=expected_origin:
                                    raise WorkflowError(
                                        "ORIGIN_REQUIRED",403
                                    )

                                if request.headers.get(
                                        "Sec-Fetch-Site"
                                    )=="cross-site":
                                    raise WorkflowError(
                                        "ORIGIN_REJECTED",403
                                    )

                                wsid=request.cookies.get(
                                    workstation_sessions.cookie_name,""
                                )
                                workstation=workstation_sessions.get(
                                    wsid,expected_origin
                                )

                                if workstation is None:
                                    new_sid=workstation_sessions.create(
                                        expected_origin,wsid
                                    )
                                    if new_sid is None:
                                        raise WorkflowError(
                                            "SESSION_CAPACITY",429
                                        )
                                    workstation=workstation_sessions.get(
                                        new_sid,expected_origin
                                    )

                                if workstation is None:
                                    raise WorkflowError(
                                        "SESSION_UNAVAILABLE",503
                                    )

                                role="workstation"
                                g.workstation_owner_ref=workstation[
                                    "owner_ref"
                                ]

                        g.role=role

                        if role=="instructor":
                            origin=request.headers.get("Origin")
                            if origin and origin!=request.host_url.rstrip("/"):
                                raise WorkflowError(
                                    "ORIGIN_REJECTED",403
                                )
                            if request.headers.get(
                                    "Sec-Fetch-Site"
                                )=="cross-site":
                                raise WorkflowError(
                                    "ORIGIN_REJECTED",403
                                )

                        if role not in roles:
                            if not state["degraded"]:
                                try:
                                    event(
                                        g.attempt_id,
                                        "authorization",
                                        "REJECTED",
                                        role=role
                                    )
                                    ledger.db.commit()
                                except (
                                    sqlite3.Error,
                                    EvidenceError,
                                    OSError
                                ):
                                    degrade()

                            status=401 if role=="none" else 403
                            return attach((
                                jsonify(
                                    error="AUTHORIZATION_REQUIRED"
                                ),
                                status
                            ))

                        if role=="workstation" and "rid" in kwargs:
                            owned=ledger.submission(kwargs["rid"])
                            if (not owned
                                    or owned["access_model"]!="workstation_session"
                                    or owned["owner_ref"]!=g.workstation_owner_ref):
                                if not state["degraded"]:
                                    event(
                                        g.attempt_id,
                                        "authorization",
                                        "REJECTED",
                                        role=role,
                                        reason="RUN_NOT_FOUND"
                                    )
                                    ledger.db.commit()

                                return attach((
                                    jsonify(error="RUN_NOT_FOUND"),
                                    404
                                ))

                        rid=requested_rid

                        can_read=(
                            evidence_read
                            and role=="instructor"
                            and request.method=="GET"
                        )

                        if role=="instructor" and fn.__name__=="recovery":
                            recovery_body=body(("action",))
                            if recovery_body["action"] in ("LOCK_STOP","RESET"):
                                # Count every pending invalidation plus a conservative
                                # complete-attempt budget before any device dispatch.
                                pending=ledger.db.execute(
                                    """SELECT count(*) FROM runs r JOIN run_submissions s ON s.run_id=r.id
                                       WHERE r.state IN ('READY_TO_RUN','APPROVED_EXCEPTION')
                                         AND s.device_id='esp32-cam'"""
                                ).fetchone()[0]
                                required_events=pending+16
                                if state["degraded"] or not ledger.regular_capacity_available(required_events):
                                    degrade()
                                    capacity_scope.enter_context(
                                        ledger.recovery_capacity(required_events=required_events)
                                    )
                                    recovery_reserved=True

                        if state["degraded"] and not can_read and not recovery_reserved:
                            return attach((
                                jsonify(error="EVIDENCE_UNAVAILABLE"),
                                503
                            ))

                        if not state["degraded"] or recovery_reserved:
                            try:
                                detail={
                                    "role":role,
                                    "action":fn.__name__,
                                }
                                if role=="workstation":
                                    detail["owner_ref"]=(
                                        g.workstation_owner_ref
                                    )

                                event(
                                    rid,
                                    "authorization",
                                    "ACCEPTED",
                                    **detail
                                )
                                ledger.db.commit()

                            except (
                                sqlite3.Error,
                                EvidenceError,
                                OSError
                            ):
                                degrade()
                                if not can_read:
                                    return attach((
                                        jsonify(
                                            error="EVIDENCE_UNAVAILABLE"
                                        ),
                                        503
                                    ))

                        result=fn(*args,**kwargs)

                        if state["degraded"] and not recovery_reserved:
                            response=app.make_response(result)
                            data=response.get_json()
                            data.update(
                                audit_logging="UNAVAILABLE",
                                workflow_locked=True
                            )
                            return attach((
                                jsonify(data),
                                response.status_code
                            ))

                        ledger.db.commit()
                        if recovery_reserved:
                            response=app.make_response(result)
                            data=response.get_json()
                            data.update(audit_logging="RECOVERY_ONLY",workflow_locked=True)
                            return attach((jsonify(data),response.status_code))
                        return attach(result)

                    except (
                        WorkflowError,
                        SourceError,
                        DisplayError,
                        HTTPException
                    ) as error:
                        code=(
                            error.code
                            if isinstance(error,WorkflowError)
                            else str(error)
                            if isinstance(
                                error,(SourceError,DisplayError)
                            )
                            else "REQUEST_REJECTED"
                        )

                        status=(
                            error.status
                            if isinstance(error,WorkflowError)
                            else 409
                            if (
                                isinstance(error,DisplayError)
                                and str(error)=="DISPLAY_ORDER"
                            )
                            else 422
                            if isinstance(
                                error,(SourceError,DisplayError)
                            )
                            else error.code
                        )

                        if state["degraded"] and not recovery_reserved:
                            return attach((
                                jsonify(
                                    error=code,
                                    attempt_id=g.attempt_id,
                                    audit_logging="UNAVAILABLE",
                                    workflow_locked=True
                                ),
                                status
                            ))

                        try:
                            event(
                                requested_rid,
                                "workflow",
                                "REJECTED",
                                reason=code
                            )
                            ledger.db.commit()
                        except (
                            sqlite3.Error,
                            EvidenceError,
                            OSError
                        ):
                            degrade()
                            return attach((
                                jsonify(
                                    error="EVIDENCE_UNAVAILABLE"
                                ),
                                503
                            ))

                        return attach((
                            jsonify(
                                error=code,
                                attempt_id=g.attempt_id
                            ),
                            status
                        ))

                    except (
                        sqlite3.Error,
                        EvidenceError,
                        OSError
                    ):
                        degrade()
                        return attach((
                            jsonify(error="EVIDENCE_UNAVAILABLE"),
                            503
                        ))

                    except Exception:
                        degrade("INTERNAL_FAILURE_LOCKED")
                        return attach((
                            jsonify(
                                error="INTERNAL_FAILURE_LOCKED"
                            ),
                            500
                        ))

                    finally:
                        capacity_scope.close()

            return handler
        return decorator

    def reported(rid,result,action):
        # Whitelist fields; no endpoint address, credentials, boot nonce or arbitrary device text.
        detail={k:result[k] for k in ("state","led_reported","gpio_enabled","program_sha256","origin")}
        same=result["run_id"]==rid
        if action in ("RUN","STATUS"):
            stored=ledger.run(rid)
            same=same and stored is not None and stored["program"] is not None and (
                result["program_sha256"]==hashlib.sha256(stored["program"].encode()).hexdigest())
        detail.update(reported_run_id=result["run_id"],requested_action=action,
                      correlation="MATCHED" if same else "NOT_CURRENT_DEVICE_RUN")
        event(rid,"simulated_device_response" if config.mode!="wifi" else "device_response",
              "REPORTED",**detail,physical_observation="NOT_OBSERVED")
        return detail
    # CAM_LIVE_HEALTH_V1
    #
    # Read-only authenticated ESP32-CAM refresh for transient
    # connectivity state. This path does not create an experiment
    # run, write evidence, or dispatch an actuator command.
    cam_health_stop=threading.Event()
    cam_transport_mutex=threading.RLock()

    app.extensions["cam_health_stop"]=cam_health_stop
    app.extensions["cam_health_thread"]=None
    app.extensions["cam_transport_mutex"]=cam_transport_mutex

    def exchange(rid,action,program=""):
        submission=ledger.submission(rid)
        device_id=submission["device_id"] if submission else "esp32-cam"
        target=devices.get(device_id)
        if target is None:raise WorkflowError("EXPERIMENT_UNAVAILABLE",422)
        category="wifi_communication" if config.mode=="wifi" else "simulator_transport"
        event(rid,category,"DISPATCH_INTENT",action=action)
        ledger.db.commit()  # Durable intent before any external mutation.
        preflight={}
        def retain_preflight(report):
            # Never retain routing, credentials, boot nonce or arbitrary text.
            fields=("run_id","state","led_reported","gpio_enabled","program_sha256","origin")
            preflight.update({key:report[key] for key in fields})
            event(rid,"device_preflight" if config.mode=="wifi" else "simulated_device_preflight",
                  "REPORTED",requested_action=action,**preflight,
                  physical_observation="NOT_OBSERVED")
            ledger.db.commit()

            if config.mode=="wifi" and device_id=="esp32-cam" and action=="RUN":
                prepared=twin_led_timeline(program)

                state["cam_execution"]=(
                    {
                        **prepared,
                        "started":time.monotonic(),
                    }
                    if prepared is not None
                    else None
                )

        try:
            if config.mode=="wifi" and device_id=="esp32-cam":
                with cam_transport_mutex:
                    result=(
                        target.command(
                            rid,
                            action,
                            program,
                            before_dispatch=retain_preflight
                        )
                        if action!="STATUS"
                        else target.status()
                    )
            else:
                result=(
                    target.command(
                        rid,
                        action,
                        program,
                        before_dispatch=retain_preflight
                    )
                    if action!="STATUS"
                    else target.status()
                )
        except TransportError as error:
            if error.code=="DEVICE_BUSY" and not error.uncertain:
                if config.mode=="wifi" and device_id=="esp32-cam":
                    state["cam_health"]="CONNECTED"
                event(
                    rid,
                    category,
                    "REJECTED",
                    reason="DEVICE_BUSY",
                    action=action
                )
                raise WorkflowError("DEVICE_BUSY",409)

            state["locked"]=True
            if config.mode=="wifi" and device_id=="esp32-cam":
                state["cam_health"]="UNAVAILABLE"
                state["cam_report"]=None
            event(
                rid,
                category,
                "UNCERTAIN" if error.uncertain else "FAILED",
                reason=error.code,
                action=action
            )
            invalidate_pending(rid,error.code)
            event(
                rid,
                "recovery",
                "LOCAL_LOCKED",
                physical_observation="NOT_OBSERVED"
            )
            presentation(
                rid,
                "DISPLAY_RECOVERY",
                lab_display.recovery
            )
            return None
        if config.mode=="wifi" and device_id=="esp32-cam":
            state["cam_health"]="CONNECTED"
        event(rid,category,"RESPONSE_RECEIVED",action=action)
        reported(rid,result,action)

        if config.mode=="wifi" and device_id=="esp32-cam":
            state["cam_report"]={
                "state":result["state"],
                "led_reported":result["led_reported"],
                "gpio_enabled":result["gpio_enabled"],
                "origin":result["origin"],
                "updated":time.monotonic(),
            }

        if (
            config.mode=="wifi"
            and device_id=="esp32-cam"
            and action=="STOP"
            and result["led_reported"]==0
        ):
            state["cam_execution"]=None

        state["active_device_run"]=result["run_id"] if result["state"]=="RUNNING" else None
        if preflight:
            result={**result,"preflight":preflight}
        if action in ("RUN","STATUS"):led_display_report(rid,result)
        return result
    def cam_health_worker():
        target=devices.get("esp32-cam")

        while not cam_health_stop.is_set():
            try:
                with cam_transport_mutex:
                    result=target.status()

            except TransportError:
                with mutex:
                    state["cam_health"]="UNAVAILABLE"

            else:
                with mutex:
                    state["cam_health"]="CONNECTED"

                    state["cam_report"]={
                        "state":result["state"],
                        "led_reported":result["led_reported"],
                        "gpio_enabled":result["gpio_enabled"],
                        "origin":result["origin"],
                        "updated":time.monotonic(),
                    }

            cam_health_stop.wait(1.0)

    # Never poll injected test doubles or simulator deployments.
    # Only the application's real Wi-Fi ESP32-CAM transport is used.
    cam_target=devices.get("esp32-cam")

    if (
        config.mode=="wifi"
        and transport is None
        and isinstance(cam_target,HTTPTransport)
    ):
        cam_thread=threading.Thread(
            target=cam_health_worker,
            name="sentinel-cam-health",
            daemon=True,
        )

        app.extensions["cam_health_thread"]=cam_thread
        cam_thread.start()

    def car_safe_report(result):
        # Whitelist bounded authenticated CAR telemetry. Never retain
        # routing, credentials, boot identifiers, sequence values or
        # arbitrary device-provided text.
        fields=(
            "state",
            "last_action",
            "motor_a_active",
            "motor_b_active",
            "ldr32",
            "ldr33",
            "camera_ready",
            "rssi_dbm",
            "origin",
        )
        return {key:result[key] for key in fields}

    # CAR_LIVE_TELEMETRY_V1
    #
    # Read-only authenticated device refresh for the Digital Twin and
    # Experiment 2 display. This path deliberately bypasses car_exchange():
    # periodic telemetry is transient display state, not durable experiment
    # evidence, and must never dispatch an actuator command.
    car_telemetry_stop=threading.Event()
    car_transport_mutex=threading.RLock()

    app.extensions["car_telemetry_stop"]=car_telemetry_stop
    app.extensions["car_telemetry_thread"]=None
    app.extensions["car_transport_mutex"]=car_transport_mutex

    def car_telemetry_worker():
        target=devices.get("esp32-wrover")

        while not car_telemetry_stop.is_set():
            try:
                with car_transport_mutex:
                    result=target.status()

                safe=car_safe_report(result)

            except TransportError:
                # Keep the last authenticated report in memory so its age
                # remains observable, but do not refresh its timestamp.
                # The existing display freshness boundary will expire it.
                with mutex:
                    state["car_health"]="UNAVAILABLE"

            else:
                with mutex:
                    state["car_health"]="CONNECTED"

                    state["car_report"]={
                        **safe,
                        "run_id":result["run_id"],
                        "updated":time.monotonic(),
                    }

                    state["car_active_run"]=(
                        result["run_id"]
                        if result["state"]=="RUNNING"
                        else None
                    )

            car_telemetry_stop.wait(1.0)

    # Never start this worker for injected test doubles or simulator
    # deployments. Only the application's real Wi-Fi CAR transport is polled.
    car_target=devices.get("esp32-wrover")

    if (
        config.mode=="wifi"
        and car_transport is None
        and isinstance(car_target,CARHTTPTransport)
    ):
        car_thread=threading.Thread(
            target=car_telemetry_worker,
            name="sentinel-car-telemetry",
            daemon=True,
        )

        app.extensions["car_telemetry_thread"]=car_thread
        car_thread.start()

    def car_exchange(rid,action):
        target=devices.get("esp32-wrover")

        if target is None:
            raise WorkflowError("EXPERIMENT_UNAVAILABLE",422)

        allowed=(
            "STATUS",
            "MOTOR_A_TEST",
            "MOTOR_A_CW_TEST",
            "MOTOR_A_CCW_TEST",
            "MOTOR_B_TEST",
            "MOTOR_B_CW_TEST",
            "MOTOR_B_CCW_TEST",
            "STOP",
        )

        if action not in allowed:
            raise WorkflowError("CAR_ACTION_NOT_ALLOWED",422)

        category="car_device_communication"

        event(
            rid,
            category,
            "DISPATCH_INTENT",
            device_id="esp32-wrover",
            action=action,
            physical_observation="NOT_OBSERVED",
        )

        # Make command intent durable before any external mutation.
        ledger.db.commit()

        preflight={}

        def retain_preflight(report):
            safe=car_safe_report(report)
            preflight.update(safe)

            event(
                rid,
                "device_preflight",
                "REPORTED",
                device_id="esp32-wrover",
                requested_action=action,
                **safe,
                physical_observation="NOT_OBSERVED",
            )

            # CARHTTPTransport calls this only after authenticated
            # status and before command dispatch.
            ledger.db.commit()

        try:
            with car_transport_mutex:
                if action=="STATUS":
                    result=target.status()
                else:
                    result=target.command(
                        rid,
                        action,
                        before_dispatch=retain_preflight,
                    )

        except TransportError as error:
            known_ready_rejections={
                "DEVICE_BUSY",
                "DEVICE_NOT_READY",
                "DEVICE_SEQUENCE_EXHAUSTED",
            }

            if error.code in known_ready_rejections:
                state["car_health"]="CONNECTED"
            else:
                state["car_health"]="UNAVAILABLE"
                state["car_report"]=None

            disposition=(
                "UNCERTAIN"
                if error.uncertain
                else "REJECTED"
                if error.code in known_ready_rejections
                else "FAILED"
            )

            event(
                rid,
                category,
                disposition,
                device_id="esp32-wrover",
                reason=error.code,
                action=action,
                physical_observation="NOT_OBSERVED",
            )

            # TransportError.uncertain identifies a possibly dispatched POST.
            # A known pre-dispatch refusal is terminal, while an unverified
            # command outcome must remain explicitly incomplete.
            stage="INCOMPLETE" if error.uncertain else disposition
            ledger.state(rid,stage)
            state.update(latest_run=rid,latest_stage=stage)

            if error.uncertain:
                state["locked"]=True
                state["car_active_run"]=None

                event(
                    rid,
                    "recovery",
                    "LOCAL_LOCKED",
                    device_id="esp32-wrover",
                    reason=error.code,
                    physical_observation="NOT_OBSERVED",
                )

            status=(
                409
                if error.code in known_ready_rejections
                else 422
                if error.code=="CAR_NOT_CONFIGURED"
                else 502
            )

            raise WorkflowError(
                error.code,
                status,
            )

        state["car_health"]="CONNECTED"

        safe=car_safe_report(result)

        event(
            rid,
            category,
            "RESPONSE_RECEIVED",
            device_id="esp32-wrover",
            action=action,
        )

        event(
            rid,
            "device_response",
            "REPORTED",
            device_id="esp32-wrover",
            requested_action=action,
            reported_run_id=result["run_id"],
            **safe,
            physical_observation="NOT_OBSERVED",
        )

        state["car_report"]={
            **safe,
            "run_id":result["run_id"],
            "updated":time.monotonic(),
        }

        state["car_active_run"]=(
            result["run_id"]
            if result["state"]=="RUNNING"
            else None
        )

        if preflight:
            result={
                **result,
                "preflight":preflight,
            }

        return result

    @app.after_request
    def headers(response):
        response.headers.update({
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Referrer-Policy": "no-referrer",
            "Content-Security-Policy":
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'none'; "
                "form-action 'self'"
        })

        # The read-only Lab Display may be embedded only by
        # Sentinel-CPS itself for the Administration preview.
        if request.path == "/display":
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self'; "
                "frame-ancestors 'self'; "
                "base-uri 'none'; "
                "form-action 'self'"
            )

        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        return jsonify(error="REQUEST_REJECTED"),error.code

    @app.get("/")
    def home():return render_template("home.html")
    @app.get("/source-submission")
    @app.get("/student")
    @app.get("/student/led-flasher")
    @app.get("/workflow")
    def legacy_led_workflow():
        return redirect("/experiments/led-flasher",code=302)
    @app.get("/contact")
    def contact():return render_template("contact.html")
    @app.get("/about")
    def about():return render_template("about.html")
    def same_origin():
        origin=request.headers.get("Origin")
        return (not origin or origin==request.host_url.rstrip("/")) and request.headers.get("Sec-Fetch-Site")!="cross-site"


    @app.get("/admin/login")
    def admin_login_page():
        record=admin_sessions.get(request.cookies.get(admin_sessions.cookie_name,""),request.host_url.rstrip("/"))
        if record:return redirect("/admin")
        return render_template("admin_login.html")

    @app.post("/api/admin/session")
    def admin_login():
        # Login uses only the existing instructor credential, never an existing session.
        if not same_origin():return jsonify(error="ORIGIN_REJECTED"),403
        if not admin_sessions.allow_attempt(request.remote_addr or "unknown"):
            response=jsonify(error="LOGIN_RATE_LIMITED")
            response.headers["Retry-After"]="60"
            return response,429
        token=request.headers.get("X-Sentinel-Token", "")
        if not re.fullmatch(r"[0-9a-f]{64}",token) or not hmac.compare_digest(token,config.admin_token):
            return jsonify(error="AUTHORIZATION_REQUIRED"),401
        try:body(())
        except (WorkflowError,HTTPException):return jsonify(error="REQUEST_SCHEMA"),400
        sid=admin_sessions.create(request.host_url.rstrip("/"),request.cookies.get(admin_sessions.cookie_name,""))
        if sid is None:return jsonify(error="SESSION_CAPACITY"),429
        response=jsonify(authenticated=True,expires_in=admin_sessions.ttl)
        response.set_cookie(admin_sessions.cookie_name,sid,max_age=admin_sessions.ttl,
                            httponly=True,secure=request.is_secure,samesite="Strict",path="/")
        return response

    @app.post("/api/admin/logout")
    def admin_logout():
        # Revocation must work even if evidence storage is unavailable.
        sid=request.cookies.get(admin_sessions.cookie_name, "")
        if not same_origin():return jsonify(error="ORIGIN_REJECTED"),403
        if not admin_sessions.authorized(sid,request.host_url.rstrip("/"),request.headers.get("X-Sentinel-CSRF", "")):
            return jsonify(error="AUTHORIZATION_REQUIRED"),401
        try:body(())
        except (WorkflowError,HTTPException):return jsonify(error="REQUEST_SCHEMA"),400
        admin_sessions.revoke(sid)
        response=jsonify(authenticated=False)
        response.delete_cookie(admin_sessions.cookie_name,path="/",httponly=True,
                               secure=request.is_secure,samesite="Strict")
        return response

    @app.get("/admin")
    def admin():
        record=admin_sessions.get(request.cookies.get(admin_sessions.cookie_name,""),request.host_url.rstrip("/"))
        if not record:return redirect("/admin/login")
        return render_template("admin.html",csrf_token=record["csrf"])

    # CPS Studio 1.1 RC2: presentation-only season setting; never executes sudo.
    @app.post("/api/admin/slideshow/season")
    def admin_slideshow_change():
        if (request.headers.get("Origin") != request.host_url.rstrip("/")
                or request.headers.get("Sec-Fetch-Site") == "cross-site"):
            return jsonify(error="ORIGIN_REJECTED"), 403
        sid = request.cookies.get(admin_sessions.cookie_name, "")
        if not admin_sessions.authorized(
                sid, request.host_url.rstrip("/"),
                request.headers.get("X-Sentinel-CSRF", "")):
            return jsonify(error="AUTHORIZATION_REQUIRED"), 401
        if (not request.is_json or request.content_length is None
                or request.content_length > 256):
            return jsonify(error="REQUEST_SCHEMA"), 400
        data = request.get_json(silent=True)
        if (type(data) is not dict or set(data) != {"season"}
                or type(data["season"]) is not str
                or data["season"] not in ("fall", "spring", "winter")):
            return jsonify(error="SEASON_NOT_ALLOWED"), 422
        try:
            return jsonify(set_slideshow_season(data["season"]))
        except SlideshowUnavailable:
            return jsonify(error="SLIDESHOW_UNAVAILABLE"), 503

    @app.get("/experiments")
    def experiments():return render_template("experiments.html")
    @app.get("/experiments/led-flasher")
    def led_flasher():return render_template("experiment_led.html")
    @app.get("/experiments/autonomous-car")
    def autonomous_car():return render_template("experiment_car.html")

    @app.get("/experiments/autonomous-car/gallery")
    @protected(
        "workstation",
        evidence_read=True,
    )
    def autonomous_car_gallery():
        prune_car_snapshots()

        now=time.monotonic()
        captures=[]

        for token,record in reversed(
            list(car_snapshot_cache.items())
        ):
            if (
                record["owner_ref"]
                != g.workstation_owner_ref
            ):
                continue

            captures.append({
                "url":(
                    "/api/experiments/autonomous-car/"
                    "snapshot/"
                    +token
                ),
                "sha256":record["sha256"],
                "length":record["length"],
                "age_seconds":max(
                    0,
                    int(now-record["created"]),
                ),
            })

        return render_template(
            "experiment_car_gallery.html",
            captures=captures,
        )

    @app.get("/display")
    def display():return render_template("display.html")
    @app.post("/api/experiments/led/control")
    @workstation_control
    def led_control():
        data=body(("action",))
        action=data["action"]
        if action not in ("ON","OFF"):
            raise WorkflowError("LED_ACTION_NOT_ALLOWED",422)

        rid=g.attempt_id
        program="L1,W1000,W1000,W1000,W1000,W1000,L0" if action=="ON" else None

        if action=="ON" and state["locked"]:
            raise WorkflowError("GATEWAY_LOCKED",409)

        if action=="ON":
            if len(direct_led_owners)>=128:
                direct_led_owners.pop(next(iter(direct_led_owners)))
            direct_led_owners[rid]=g.workstation_owner_ref

        ledger.create(rid,"COMMUNICATING")
        if program is not None:
            ledger.state(rid,"COMMUNICATING",program)

        event(rid,"workstation_control","DISPATCH_INTENT",
              experiment="led-status-v1",action=action,
              physical_observation="NOT_OBSERVED")
        ledger.db.commit()

        if action=="ON" and led_display_owned():
            led_display_ready(rid)
        elif action=="OFF":
            invalidate_pending(rid,"GUIDED_OFF")

        try:
            result=exchange(rid,"RUN",program) if action=="ON" else exchange(rid,"STOP")
        except WorkflowError as error:
            if error.code=="DEVICE_BUSY":
                direct_led_owners.pop(rid,None)
                ledger.state(rid,"DEVICE_BUSY")
                state.update(
                    latest_run=rid,
                    latest_stage="DEVICE_BUSY"
                )
            raise

        stage="DEVICE_REPORTED" if result else "INCOMPLETE"
        ledger.state(rid,stage)
        state.update(latest_run=rid,latest_stage=stage)

        stopped_run_id=None
        if result is not None:
            if action=="ON":
                led_display_report(rid,result)
            else:
                stopped_run_id=close_stopped_run(rid,result)

        if result is None:
            return jsonify(
                run_id=rid,
                action=action,
                state=stage,
                physical_validation="UNVALIDATED"
            ),502

        return jsonify(
            run_id=rid,
            action=action,
            state=stage,
            stopped_run_id=stopped_run_id,
            stopped_run_state="DEVICE_REPORTED_COMPLETE" if stopped_run_id else None,
            reported={
                "state":result["state"],
                "led_reported":result["led_reported"],
                "gpio_enabled":result["gpio_enabled"],
                "origin":result["origin"]
            },
            physical_validation="UNVALIDATED"
        )

    @app.post("/api/experiments/led/status")
    @workstation_control
    def led_control_status():
        data=body(("run_id",))
        rid=data["run_id"]

        if not isinstance(rid,str) or not re.fullmatch(r"[0-9a-f]{32}",rid):
            raise WorkflowError("RUN_NOT_FOUND",404)

        recorded=ledger.run(rid)
        expected_program="L1,W1000,W1000,W1000,W1000,W1000,L0"

        if (
            recorded is None
            or recorded["program"]!=expected_program
            or recorded["config_ref"]!=config.reference
        ):
            raise WorkflowError("RUN_NOT_FOUND",404)

        if direct_led_owners.get(rid)!=g.workstation_owner_ref:
            raise WorkflowError("RUN_NOT_FOUND",404)

        result=exchange(rid,"STATUS")

        if result is None:
            return jsonify(
                error="STATUS_UNAVAILABLE",
                run_id=rid,
                physical_validation="UNVALIDATED"
            ),502

        same=(
            result["run_id"]==rid
            and result["program_sha256"]
                == hashlib.sha256(expected_program.encode()).hexdigest()
        )

        if not same:
            raise WorkflowError("NOT_CURRENT_DEVICE_RUN",409)

        complete=(
            result["state"] in ("COMPLETE","STOPPED","IDLE")
            and result["led_reported"]==0
        )

        stage=(
            "DEVICE_REPORTED_COMPLETE"
            if complete
            else "DEVICE_REPORTED"
        )

        ledger.state(rid,stage)
        state.update(
            latest_run=rid,
            latest_stage=stage
        )

        if lab_display.owns_run(rid):
            led_display_report(rid,result)

        if complete:
            direct_led_owners.pop(rid,None)

        return jsonify(
            run_id=rid,
            current_device_run=True,
            state=stage,
            reported={
                "run_id":result["run_id"],
                "state":result["state"],
                "led_reported":result["led_reported"],
                "gpio_enabled":result["gpio_enabled"],
                "origin":result["origin"]
            },
            physical_validation="UNVALIDATED"
        )


    # ========================================================
    # Experiment 2 · bounded workstation CAR operations
    # ========================================================

    @app.post("/api/experiments/autonomous-car/control")
    @workstation_control
    def car_experiment_control():
        data=body(("action",))
        action=data["action"]

        if action not in (
            "MOTOR_A_TEST",
            "MOTOR_A_CW_TEST",
            "MOTOR_A_CCW_TEST",
            "MOTOR_B_TEST",
            "MOTOR_B_CW_TEST",
            "MOTOR_B_CCW_TEST",
        ):
            raise WorkflowError(
                "CAR_ACTION_NOT_ALLOWED",
                422,
            )

        car_workstation_access()

        rid=g.attempt_id

        ledger.create(
            rid,
            "COMMUNICATING",
        )

        event(
            rid,
            "car_experiment_control",
            "REQUESTED",
            device_id="esp32-wrover",
            action=action,
            authority="workstation_session",
            physical_observation="NOT_OBSERVED",
        )

        ledger.db.commit()

        result=car_exchange(
            rid,
            action,
        )

        ledger.state(
            rid,
            "DEVICE_REPORTED",
        )

        state.update(
            latest_run=rid,
            latest_stage="DEVICE_REPORTED",
        )

        return jsonify(
            run_id=rid,
            action=action,
            state="DEVICE_REPORTED",
            reported={
                "run_id":result["run_id"],
                **car_safe_report(result),
            },
            physical_validation="UNVALIDATED",
        )


    @app.post("/api/experiments/autonomous-car/snapshot")
    @workstation_control
    def car_experiment_snapshot():
        data=body(("mode",))
        mode=data["mode"]

        if mode not in (
            "single",
            "series",
        ):
            raise WorkflowError(
                "CAR_CAMERA_MODE_NOT_ALLOWED",
                422,
            )

        car_workstation_access()

        target=devices.get(
            "esp32-wrover"
        )

        if target is None or not hasattr(target,"camera"):
            raise WorkflowError(
                "CAR_NOT_CONFIGURED",
                422,
            )

        count=1 if mode=="single" else 3
        rid=g.attempt_id

        ledger.create(
            rid,
            "COMMUNICATING",
        )

        event(
            rid,
            "car_camera",
            "REQUESTED",
            device_id="esp32-wrover",
            mode=mode,
            frame_count=count,
            authority="workstation_session",
            physical_observation="NOT_OBSERVED",
        )

        ledger.db.commit()

        prune_car_snapshots()

        frames=[]

        for index in range(count):
            try:
                frame=target.camera()

            except TransportError as error:
                status=(
                    409
                    if error.code=="CAR_CAMERA_BUSY"
                    else 503
                    if error.code=="CAR_CAMERA_UNAVAILABLE"
                    else 502
                )

                event(
                    rid,
                    "car_camera",
                    "FAILED",
                    device_id="esp32-wrover",
                    reason=error.code,
                    frame_index=index,
                    physical_observation="NOT_OBSERVED",
                )

                # Camera reads cannot dispatch actuator work. Retain the
                # failed request as terminal rather than still communicating.
                ledger.state(rid,"FAILED")
                state.update(latest_run=rid,latest_stage="FAILED")

                raise WorkflowError(
                    error.code,
                    status,
                )

            token=uuid.uuid4().hex

            car_snapshot_cache[token]={
                "owner_ref":g.workstation_owner_ref,
                "jpeg":frame["jpeg"],
                "sha256":frame["sha256"],
                "length":frame["length"],
                "created":time.monotonic(),
            }

            frames.append({
                "index":index+1,
                "url":(
                    "/api/experiments/autonomous-car/"
                    "snapshot/"
                    +token
                ),
                "sha256":frame["sha256"],
                "length":frame["length"],
                "origin":frame["origin"],
            })

            state["car_health"]="CONNECTED"

            # CAM activity means an authenticated JPEG has
            # actually been verified by the Gateway.
            state["car_camera_activity_until"]=(
                time.monotonic()+1.5
            )

            event(
                rid,
                "car_camera",
                "FRAME_VERIFIED",
                device_id="esp32-wrover",
                frame_index=index+1,
                sha256=frame["sha256"],
                length=frame["length"],
                origin=frame["origin"],
                physical_observation="NOT_OBSERVED",
            )

            ledger.db.commit()

            if index < count-1:
                # Fixed bounded interval. Browser cannot choose
                # an arbitrary burst rate or frame count.
                time.sleep(0.35)

        prune_car_snapshots()

        ledger.state(
            rid,
            "DEVICE_REPORTED",
        )

        state.update(
            latest_run=rid,
            latest_stage="DEVICE_REPORTED",
        )

        return jsonify(
            run_id=rid,
            mode=mode,
            frame_count=len(frames),
            frames=frames,
            origin="DEVICE",
            physical_validation="UNVALIDATED",
        )


    @app.get(
        "/api/experiments/autonomous-car/snapshot/<token>"
    )
    @protected(
        "workstation",
        evidence_read=True,
    )
    def car_experiment_snapshot_image(token):
        if not re.fullmatch(
            r"[0-9a-f]{32}",
            token,
        ):
            raise WorkflowError(
                "SNAPSHOT_NOT_FOUND",
                404,
            )

        prune_car_snapshots()

        record=car_snapshot_cache.get(
            token
        )

        if (
            record is None
            or record["owner_ref"]
                != g.workstation_owner_ref
        ):
            raise WorkflowError(
                "SNAPSHOT_NOT_FOUND",
                404,
            )

        response=app.response_class(
            record["jpeg"],
            mimetype="image/jpeg",
        )

        response.headers["Content-Length"]=str(
            record["length"]
        )

        response.headers["X-Sentinel-Frame-SHA256"]=(
            record["sha256"]
        )

        return response


    @app.post("/api/admin/car/control")
    @protected("instructor")
    def admin_car_control():
        data=body(("action",))
        action=data["action"]

        allowed=(
            "STATUS",
            "MOTOR_A_TEST",
            "MOTOR_A_CW_TEST",
            "MOTOR_A_CCW_TEST",
            "MOTOR_B_TEST",
            "MOTOR_B_CW_TEST",
            "MOTOR_B_CCW_TEST",
            "STOP",
        )

        if not isinstance(action,str) or action not in allowed:
            raise WorkflowError(
                "CAR_ACTION_NOT_ALLOWED",
                422,
            )

        # STATUS and STOP remain available for diagnosis/recovery.
        # Motor tests require an administratively unlocked Gateway.
        if action in (
            "MOTOR_A_TEST",
            "MOTOR_A_CW_TEST",
            "MOTOR_A_CCW_TEST",
            "MOTOR_B_TEST",
            "MOTOR_B_CW_TEST",
            "MOTOR_B_CCW_TEST",
        ):
            if state["locked"]:
                raise WorkflowError(
                    "GATEWAY_LOCKED",
                    409,
                )

            if state["active_device_run"] is not None:
                raise WorkflowError(
                    "DEVICE_BUSY",
                    409,
                )

        rid=g.attempt_id

        ledger.create(
            rid,
            "COMMUNICATING",
        )

        event(
            rid,
            "car_control",
            "REQUESTED",
            device_id="esp32-wrover",
            action=action,
            authority="instructor",
            physical_observation="NOT_OBSERVED",
        )

        result=car_exchange(
            rid,
            action,
        )

        stage="DEVICE_REPORTED"

        ledger.state(
            rid,
            stage,
        )

        state.update(
            latest_run=rid,
            latest_stage=stage,
        )

        return jsonify(
            run_id=rid,
            action=action,
            state=stage,
            reported={
                "run_id":result["run_id"],
                **car_safe_report(result),
            },
            physical_validation="UNVALIDATED",
        )

    @app.get("/api/health")
    def health():
        return jsonify(service="Sentinel-CPS",transport=config.mode,locked=state["locked"],
            esp32_cam_health=state["cam_health"],
            esp32_wrover_health=state["car_health"],
            evidence_available=not state["degraded"],run_id=state["latest_run"],
            stage=state["latest_stage"],physical_validation="UNVALIDATED",
            limitation="Gateway status and device reports do not prove physical behavior."),503 if state["degraded"] else 200

    # CPS Studio 1.1: read-only synchronized seasonal slideshow.
    @app.get("/api/display/slideshow")
    def cps_slideshow_status():
        try:
            return jsonify(slideshow_snapshot())
        except SlideshowUnavailable:
            return jsonify(error="SLIDESHOW_UNAVAILABLE"), 503

    @app.get("/display/slides/<season>/<filename>")
    def cps_slideshow_image(season, filename):
        try:
            path = slide_path(season, filename)
        except SlideshowUnavailable:
            path = None
        if path is None:
            return jsonify(error="SLIDE_NOT_FOUND"), 404
        return send_file(path, mimetype="image/jpeg", conditional=True)

    @app.get("/api/display/status")
    def display_status():
        # This read never acquires the device-operation mutex, writes evidence,
        # or queries a device. The persistent kiosk can poll during a command.
        return jsonify(lab_display.snapshot()),503 if state["degraded"] else 200

    @app.get("/api/display/devices")
    def display_devices():
        cam={
            "reachable":None,
            "authenticated":None,
            "fresh":False,
            "state":None,
            "led_reported":None,
            "gpio_enabled":None,
            "age_ms":None,
        }

        cached=state["cam_report"]

        if cached is not None:
            age=max(0.0,time.monotonic()-cached["updated"])
            cam["age_ms"]=int(age*1000)

            if age <= 8.0:
                cam.update(
                    reachable=True,
                    authenticated=cached["origin"]=="DEVICE",
                    fresh=True,
                    state=cached["state"],
                    led_reported=cached["led_reported"],
                    gpio_enabled=cached["gpio_enabled"],
                )

        elif state["cam_health"]=="UNAVAILABLE":
            cam.update(
                reachable=False,
                authenticated=False,
            )

        car={
            "reachable":None,
            "authenticated":None,
            "fresh":False,
            "state":None,
            "last_action":None,
            "motor_a_active":None,
            "motor_b_active":None,
            "ldr32":None,
            "ldr33":None,
            "camera_ready":None,

            # Gateway action state: a recently verified
            # authenticated JPEG, not a device readiness claim.
            "camera_active":(
                time.monotonic()
                < state["car_camera_activity_until"]
            ),

            "rssi_dbm":None,
            "age_ms":None,
            # Read-only Gateway-to-CAR application RTT; no extra device poll.
            # Timing never enters authenticated device reports or the ledger.
            "status_rtt":{
                "state":"UNAVAILABLE",
                "ms":None,
                "age_ms":None,
            },
        }

        car_target=devices.get("esp32-wrover")
        if isinstance(car_target,CARHTTPTransport):
            car["status_rtt"]=car_target.status_rtt()

        cached=state["car_report"]

        if cached is not None:
            age=max(0.0,time.monotonic()-cached["updated"])
            car["age_ms"]=int(age*1000)

            if age <= 8.0:
                car.update(
                    reachable=True,
                    authenticated=cached["origin"]=="DEVICE",
                    fresh=True,
                    state=cached["state"],
                    last_action=cached["last_action"],
                    motor_a_active=cached["motor_a_active"],
                    motor_b_active=cached["motor_b_active"],
                    ldr32=cached["ldr32"],
                    ldr33=cached["ldr33"],
                    camera_ready=cached["camera_ready"],
                    rssi_dbm=cached["rssi_dbm"],
                )

        elif state["car_health"]=="UNAVAILABLE":
            car.update(
                reachable=False,
                authenticated=False,
            )

        return jsonify(
            cam=cam,
            car=car,
        )

    @app.get("/api/display/execution")
    def display_execution():
        led={
            "active":False,
            "elapsed_ms":None,
            "duration_ms":None,
            "timeline":[],
        }

        cached=state["cam_execution"]

        if cached is not None:
            elapsed=max(
                0,
                int(
                    (
                        time.monotonic()
                        - cached["started"]
                    )
                    * 1000
                )
            )

            duration=cached["duration_ms"]

            if elapsed <= duration:
                led.update(
                    active=True,
                    elapsed_ms=elapsed,
                    duration_ms=duration,
                    timeline=[
                        dict(segment)
                        for segment
                        in cached["timeline"]
                    ],
                )

        return jsonify(led=led)

    @app.get("/api/display/tracks")
    def display_tracks():
        return jsonify(tracks=track_catalog())

    @app.post("/api/display/select-experiment")
    @protected("workstation","instructor")
    def display_select_experiment():
        body(())

        if state["locked"]:
            raise WorkflowError("GATEWAY_LOCKED",409)

        snapshot=lab_display.snapshot()

        # Do not replace an actively running LED presentation.
        if snapshot["mode"]=="LED_RUNNING":
            raise WorkflowError("DISPLAY_IN_USE",409)

        display_access()

        presentation(
            g.attempt_id,
            "DISPLAY_EXPERIMENT_SELECTION",
            lab_display.select_experiment,
            display_mode="SELECT_EXPERIMENT"
        )

        return jsonify(lab_display.snapshot())

    @app.post("/api/display/prepare")
    @protected("workstation","instructor")
    def display_prepare():
        data=body(("experiment",));experiment=data["experiment"]
        if not isinstance(experiment,str) or experiment not in PROFILES:
            raise WorkflowError("EXPERIMENT_NOT_ALLOWED",422)
        display_scope(experiment);display_access()
        expiry=None
        owner=display_owner()
        presentation(g.attempt_id,"DISPLAY_PREPARED",
            lambda:lab_display.prepare(experiment,owner,expiry),experiment=experiment)
        return jsonify(lab_display.snapshot())

    @app.post("/api/display/track")
    @protected("workstation","instructor")
    def display_track():
        data=body(("track_id",));track_id=data["track_id"]
        if not isinstance(track_id,str) or track_id not in TRACKS:
            raise WorkflowError("TRACK_NOT_ALLOWED",422)
        display_scope("autonomous-car-v1");display_access()
        if lab_display.snapshot()["mode"] not in ("AUTONOMOUS_CAR_SETUP","TRACK_ACTIVE"):
            raise WorkflowError("DISPLAY_ORDER",409)
        event(g.attempt_id,"display_presentation","TRACK_SELECTED",track_id=track_id,
              presentation_only=True,physical_observation="NOT_OBSERVED")
        presentation(g.attempt_id,"TRACK_PRESENTATION_REQUESTED",
            lambda:lab_display.select_track(track_id),track_id=track_id,experiment="autonomous-car-v1")
        return jsonify(lab_display.snapshot())

    @app.post("/api/display/home")
    @protected("workstation","instructor")
    def display_home():
        body(())

        if state["locked"]:
            raise WorkflowError("GATEWAY_LOCKED",409)

        display_access()

        presentation(
            g.attempt_id,
            "DISPLAY_HOME",
            lab_display.idle
        )

        return jsonify(lab_display.snapshot())

    @app.post("/api/display/idle")
    @protected("instructor")
    def display_idle():
        body(())
        display_access()
        presentation(g.attempt_id,"DISPLAY_IDLE",lab_display.idle)
        return jsonify(lab_display.snapshot())

    @app.post("/api/display/state")
    @protected("instructor")
    def display_state():
        data=body(("mode",))
        mode=data["mode"]

        allowed={
            "TRACK_STRAIGHT",
            "TRACK_WIDE_STRAIGHT",
            "TRACK_CURVE",
            "TRACK_WIDE_CURVE",
            "TRACK_CHALLENGE",
            "TRACK_WIDE_CHALLENGE",
            "TRACK_CIRCLE",
            "TRACK_WIDE_CIRCLE",
            "TRACK_OVAL",
            "TRACK_ELLIPTICAL",
            "TRACK_INFINITY",
            "TRACK_WIDE_INFINITY",
            "READY",
            "SELECT_EXPERIMENT",
            "LED_FLASHER",
            "AUTONOMOUS_CAR",
        }

        if not isinstance(mode,str) or mode not in allowed:
            raise WorkflowError("DISPLAY_STATE_NOT_ALLOWED",422)

        # Presentation states other than Locked are meaningful only
        # after the real Gateway access state has been unlocked.
        if state["locked"]:
            raise WorkflowError("GATEWAY_LOCKED",409)

        def apply_display_state():
            if mode=="READY":
                return lab_display.idle()

            if mode=="SELECT_EXPERIMENT":
                return lab_display.select_experiment()

            if mode=="LED_FLASHER":
                return lab_display.prepare(
                    "led-status-v1",
                    "instructor"
                )

            if mode=="AUTONOMOUS_CAR":
                return lab_display.prepare(
                    "autonomous-car-v1",
                    "instructor"
                )

            track_id={
                "TRACK_STRAIGHT":"straight",
                "TRACK_WIDE_STRAIGHT":"wide-straight",
                "TRACK_CURVE":"curve",
                "TRACK_WIDE_CURVE":"wide-curve",
                "TRACK_CHALLENGE":"challenge",
                "TRACK_WIDE_CHALLENGE":"wide-challenge",
                "TRACK_CIRCLE":"circle",
                "TRACK_WIDE_CIRCLE":"wide-circle",
                "TRACK_OVAL":"oval",
                "TRACK_ELLIPTICAL":"elliptical",
                "TRACK_INFINITY":"infinity",
                "TRACK_WIDE_INFINITY":"wide-infinity",
            }[mode]

            lab_display.prepare(
                "autonomous-car-v1",
                "instructor"
            )

            return lab_display.select_track(
                track_id
            )

        presentation(
            g.attempt_id,
            "DISPLAY_ADMIN_STATE",
            apply_display_state,
            display_mode=mode
        )

        return jsonify(
            lab_display.snapshot()
        )

    def is_known_credential(value):
        return any(
            secret and hmac.compare_digest(value,secret)
            for secret in (
                config.admin_token,
                config.device_key,
                config.car_device_key,
            )
        )

    def retained_source(value):
        if not isinstance(value,str):return None,None
        try:encoded=value.encode("utf-8")
        except UnicodeEncodeError:return None,None
        digest=hashlib.sha256(encoded).hexdigest()
        if not 1 <= len(value) <= 2048:return None,digest
        # Never turn a pasted bearer secret into retained source, including revoked tokens.
        for match in re.finditer(r"(?=([0-9a-f]{64}))",value):
            if is_known_credential(match[1]):return None,digest
        return value,digest

    def checked_artifact(rid):
        r=ledger.run(rid);submission=ledger.submission(rid)
        if not r or not submission or not submission["source_available"]:
            raise WorkflowError("IMMUTABLE_SUBMISSION_REQUIRED",409)
        if submission["experiment"] not in PROFILES or PROFILES[submission["experiment"]]["status"]!="AVAILABLE":
            raise WorkflowError("EXPERIMENT_UNAVAILABLE",422)
        if submission["policy_ref"]!=policy_reference(config):raise WorkflowError("CONFIGURATION_CHANGED",409)
        try:artifact=prepare(r["source"])
        except SourceError:raise WorkflowError("EXCEPTION_HARD_LIMIT",422)
        if (artifact["source_sha256"]!=submission["source_sha256"] or
            artifact["sha256"]!=submission["program_sha256"] or
            r["program"]!=artifact["bytecode"]):
            raise WorkflowError("SUBMISSION_INTEGRITY_FAILED",409)
        return artifact,submission

    @app.post("/api/submissions")
    @protected("workstation")
    def submit():
        data=body(("source","experiment"))
        experiment=data["experiment"]

        if not isinstance(experiment,str) or experiment not in PROFILES:
            raise WorkflowError("EXPERIMENT_NOT_ALLOWED",422)

        profile=PROFILES[experiment]

        if profile["status"]!="AVAILABLE":
            raise WorkflowError("EXPERIMENT_UNAVAILABLE",422)

        rid=g.attempt_id
        owner_ref=g.workstation_owner_ref

        source,source_hash=retained_source(data["source"])
        ledger.create(rid,source=source)

        event(
            rid,
            "submission",
            "RECEIVED",
            source_sha256=source_hash,
            submission_ref=rid,
            requested_workflow=experiment,
            device_id=profile["id"],
            access_model="workstation_session",
            owner_ref=owner_ref
        )

        artifact=None
        hard_error=None

        try:
            artifact=prepare(data["source"])
        except SourceError as error:
            hard_error=str(error)

        reasons=[hard_error] if hard_error else policy_rejections(
            config,artifact
        )

        eligible=bool(reasons and not hard_error)
        stage="REJECTED" if reasons else "READY_TO_RUN"

        ledger.state(
            rid,
            stage,
            artifact["bytecode"] if artifact else None
        )

        ledger.record_submission(
            rid,
            owner_ref,
            experiment,
            profile["id"],
            source_hash,
            artifact["sha256"] if artifact else None,
            policy_reference(config),
            reasons,
            eligible,
            source is not None,
            owner_ref=owner_ref,
            access_model="workstation_session"
        )

        event(
            rid,
            "checking",
            "REJECTED" if reasons else "ACCEPTED",
            reasons=reasons,
            source_sha256=source_hash,
            source_retained=source is not None,
            exception_eligible=eligible
        )

        if artifact:
            event(
                rid,
                "preparation",
                "BOUNDED_PROGRAM",
                source_sha256=artifact["source_sha256"],
                program_sha256=artifact["sha256"],
                steps=artifact["steps"],
                duration_ms=artifact["duration_ms"],
                firmware_binary_built=False
            )

        if not reasons:
            event(
                rid,
                "authorization",
                "READY_TO_RUN",
                authority="workstation_session",
                physical_execution=False
            )
            led_display_ready(rid)

        state.update(
            latest_run=rid,
            latest_stage=stage
        )

        value={
            "run_id":rid,
            "state":stage,
            "reasons":reasons,
            "exception_eligible":eligible,
            "can_request_exception":bool(
                reasons and source is not None
            )
        }

        if artifact:
            value["artifact"]=artifact

        if reasons:
            value["error"]=reasons[0]

        return jsonify(value),422 if reasons else 201

    @app.get("/api/runs/<rid>")
    @protected("workstation","instructor",evidence_read=True)
    def run_details(rid):
        r=run(rid,current_config=False);submission=ledger.submission(rid)
        current=r["config_ref"]==config.reference
        return jsonify(run_id=rid,state=r["state"],experiment=submission["experiment"] if submission else None,
            reasons=submission["reasons"] if submission else [],
            exception_eligible=bool(submission and submission["exception_eligible"]),
            can_run=bool(current and not state["locked"] and r["state"] in ("READY_TO_RUN","APPROVED_EXCEPTION")),
            can_request_exception=False)

    @app.post("/api/runs/<rid>/prepare")
    @protected("workstation")
    def preparation(rid):
        body(());run(rid)
        return jsonify(error="PREPARATION_IS_AUTOMATIC",state=ledger.run(rid)["state"]),410

    @app.get("/api/admin/runs/<rid>/review")
    @protected("instructor",evidence_read=True)
    def review(rid):
        r=run(rid,current_config=False)
        submission=ledger.submission(rid)

        exception=ledger.db.execute(
            """SELECT requested_at,decided_at,decision
               FROM exception_requests
               WHERE run_id=?""",
            (rid,)
        ).fetchone()

        return jsonify(
            run_id=rid,
            state=r["state"],
            source=r["source"],
            program=r["program"],
            config_ref=r["config_ref"],
            access_model=(
                submission["access_model"]
                if submission else None
            ),
            owner_ref=(
                submission["owner_ref"]
                if submission else None
            ),
            experiment=(
                submission["experiment"]
                if submission else None
            ),
            submitted_at=r["created"],
            requested_at=(
                exception["requested_at"]
                if exception else None
            ),
            decided_at=(
                exception["decided_at"]
                if exception else None
            ),
            source_sha256=(
                submission["source_sha256"]
                if submission else None
            ),
            program_sha256=(
                submission["program_sha256"]
                if submission else None
            ),
            reasons=(
                submission["reasons"]
                if submission else []
            ),
            exception_eligible=bool(
                submission
                and submission["exception_eligible"]
            ),
            source_available=bool(
                submission
                and submission["source_available"]
            )
        )

    @app.post("/api/admin/runs/<rid>/approve")
    @protected("instructor")
    def approve(rid):
        body(());run(rid,current_config=False)
        return jsonify(error="ROUTINE_APPROVAL_REMOVED"),410

    @app.post("/api/runs/<rid>/exception")
    @protected("workstation")
    def request_exception(rid):
        body(())
        run(rid,current_config=False)
        return jsonify(error="EXCEPTION_WORKFLOW_REMOVED"),410

    @app.post("/api/admin/runs/<rid>/exception")
    @protected("instructor")
    def decide_exception(rid):
        body(("decision",))
        run(rid,current_config=False)
        return jsonify(error="EXCEPTION_WORKFLOW_REMOVED"),410

    @app.get("/api/admin/exception-requests")
    @protected("instructor",evidence_read=True)
    def pending_exceptions():
        rows=ledger.db.execute(
            """SELECT r.id,x.requested_at
               FROM runs r
               JOIN exception_requests x
                 ON x.run_id=r.id
               WHERE r.state='EXCEPTION_REQUESTED'
               ORDER BY x.requested_at"""
        ).fetchall()

        result=[]

        for row in rows:
            submission=ledger.submission(row["id"])

            result.append({
                "run_id":row["id"],
                "access_model":submission["access_model"],
                "owner_ref":submission["owner_ref"],
                "experiment":submission["experiment"],
                "submitted_at":submission["created"],
                "requested_at":row["requested_at"],
                "reasons":submission["reasons"],
                "exception_eligible":submission[
                    "exception_eligible"
                ]
            })

        return jsonify(
            pending_count=len(result),
            requests=result
        )

    @app.get("/api/admin/devices")
    @protected("instructor",evidence_read=True)
    def device_catalog():return jsonify(devices=catalog())

    @app.post("/api/runs/<rid>/execute")
    @protected("workstation")
    def execute(rid):
        body(());r=run(rid,("READY_TO_RUN","APPROVED_EXCEPTION"))
        artifact,submission=checked_artifact(rid)
        if r["state"]=="READY_TO_RUN" and policy_rejections(config,artifact):raise WorkflowError("POLICY_REJECTED",422)
        if r["state"]=="APPROVED_EXCEPTION":
            decision=ledger.db.execute("SELECT decision FROM exception_requests WHERE run_id=?",(rid,)).fetchone()
            if not decision or decision["decision"]!="approve":raise WorkflowError("EXCEPTION_NOT_APPROVED",409)
        if state["locked"]:raise WorkflowError("GATEWAY_LOCKED")
        ledger.state(rid,"COMMUNICATING")
        state.update(latest_run=rid,latest_stage="COMMUNICATING")
        if led_display_owned():
            def running_presentation():
                try:
                    lab_display.bind_led_run(rid)
                    lab_display.led_phase(rid,"RUNNING")
                except DisplayError:lab_display.recovery()
            presentation(rid,"LED_INTERACTION_STARTED",running_presentation,experiment="led-status-v1")
        try:
            result=exchange(rid,"RUN",r["program"])
        except WorkflowError as error:
            if error.code=="DEVICE_BUSY":
                ledger.state(rid,r["state"])
                state.update(
                    latest_run=rid,
                    latest_stage="DEVICE_BUSY"
                )
            raise

        stage="DEVICE_REPORTED" if result else "INCOMPLETE"
        ledger.state(rid,stage);state.update(latest_run=rid,latest_stage=stage)
        return jsonify(run_id=rid,state=stage,physical_validation="UNVALIDATED"),200 if result else 502

    @app.post("/api/runs/<rid>/status")
    @protected("workstation","instructor")
    def status(rid):
        body(());r=run(rid)
        result=exchange(rid,"STATUS")
        if result:
            same=(result["run_id"]==rid and r["program"] is not None
                  and result["program_sha256"]==hashlib.sha256(r["program"].encode()).hexdigest())
            event(rid,"correlation","MATCHED" if same else "NOT_CURRENT_DEVICE_RUN")
            if (same and r["state"] in ("COMMUNICATING","DEVICE_REPORTED","INCOMPLETE","DEVICE_REPORTED_COMPLETE")
                    and result["state"] in ("IDLE","STOPPED","COMPLETE") and result["led_reported"]==0):
                ledger.state(rid,"DEVICE_REPORTED_COMPLETE")
                state.update(latest_run=rid,latest_stage="DEVICE_REPORTED_COMPLETE")
            return jsonify(run_id=rid,current_device_run=same,
                           state=ledger.run(rid)["state"],
                           reported={k:result[k] for k in ("run_id","state","led_reported","gpio_enabled","origin")},
                           physical_validation="UNVALIDATED")
        return jsonify(error="STATUS_UNAVAILABLE"),502

    @app.post("/api/runs/<rid>/stop")
    @protected("workstation","instructor")
    def stop(rid):
        body(());run(rid,("DEVICE_REPORTED","INCOMPLETE"))
        if g.role=="workstation":
            current=exchange(rid,"STATUS")
            if not current or current["run_id"]!=rid:
                raise WorkflowError("NOT_CURRENT_DEVICE_RUN")
        state["locked"]=True
        invalidate_pending(rid,"STOP")
        presentation(rid,"DISPLAY_RECOVERY",lab_display.recovery)
        result=exchange(rid,"STOP")
        event(rid,"recovery","STOP_REPORTED" if result else "STOP_UNCONFIRMED",
              authority=g.role,physical_observation="NOT_OBSERVED")
        return jsonify(run_id=rid,locked=True,stop_reported=result is not None,
                       physical_validation="UNVALIDATED"),200 if result else 502

    @app.post("/api/admin/recovery")
    @protected("instructor")
    def recovery():
        data=body(("action",))
        if data["action"] not in ("LOCK_STOP","RESET","UNLOCK"):raise WorkflowError("RECOVERY_ACTION",422)
        rid=g.attempt_id;ledger.create(rid,"RECOVERY")
        action=data["action"]
        state["locked"]=True
        invalidate_pending(rid,action)
        presentation(rid,"DISPLAY_RECOVERY",lab_display.recovery)

        result=None
        if action=="UNLOCK":
            # Administrative Gateway state is independent of target availability.
            # Fresh authenticated target readiness remains an execution-time gate.
            state["locked"]=False
            presentation(rid,"DISPLAY_IDLE",lab_display.idle)
        else:
            # The durable dispatch-intent commit includes a conservative
            # incomplete state. A crash or failed result write never leaves
            # an apparently completed recovery or an unclassified RECOVERY.
            ledger.state(rid,"INCOMPLETE")
            result=exchange(rid,"STOP" if action=="LOCK_STOP" else "RESET")

        event(rid,"recovery","LOCAL_RESULT",authority="instructor",action=action,locked=state["locked"],
              device_response_available=result is not None,physical_observation="NOT_OBSERVED")
        stage="RECOVERY_RECORDED" if action=="UNLOCK" or result else "INCOMPLETE"
        ledger.state(rid,stage);state.update(latest_run=rid,latest_stage=stage)
        return jsonify(run_id=rid,locked=state["locked"],response_available=result is not None,
                       physical_validation="UNVALIDATED"),200 if action=="UNLOCK" or result else 502

    @app.get("/api/runs")
    @protected("workstation","instructor",evidence_read=True)
    def runs():
        if g.role=="workstation":
            rows=ledger.db.execute(
                """SELECT r.id,r.state,r.created,r.config_ref
                   FROM runs r
                   JOIN run_submissions s
                     ON s.run_id=r.id
                   WHERE s.owner_ref=?
                     AND s.access_model='workstation_session'
                   ORDER BY r.created DESC
                   LIMIT 50""",
                (g.workstation_owner_ref,)
            ).fetchall()
        else:
            rows=ledger.db.execute(
                """SELECT id,state,created,config_ref
                   FROM runs
                   ORDER BY created DESC
                   LIMIT 50"""
            ).fetchall()

        return jsonify(
            runs=[dict(r) for r in rows]
        )

    @app.get("/api/admin/events")
    @protected("instructor",evidence_read=True)
    def recent_events():
        rows=ledger.db.execute("SELECT * FROM events ORDER BY seq DESC LIMIT 100").fetchall()
        return jsonify(events=[{**dict(r),"detail":json.loads(r["detail"])} for r in rows])
    @app.get("/api/admin/runs/<rid>/evidence")
    @protected("instructor",evidence_read=True)
    def evidence(rid):
        run(rid,current_config=False);return jsonify(ledger.export(rid))
    @app.post("/api/admin/runs/<rid>/observation")
    @protected("instructor")
    def observation(rid):
        run(rid);data=body(("sha256","kind"))
        if not isinstance(data["sha256"],str) or not re.fullmatch(r"[0-9a-f]{64}",data["sha256"]) or data["kind"] not in ("photo","video","notes"):
            raise WorkflowError("OBSERVATION_REFERENCE_INVALID",422)
        if is_known_credential(data["sha256"]):
            raise WorkflowError("OBSERVATION_REFERENCE_INVALID",422)
        event(rid,"direct_observation_reference","REFERENCE_ATTACHED_UNVERIFIED",
              artifact_sha256=data["sha256"],kind=data["kind"],authority="instructor")
        return jsonify(recorded=True,physical_validation="UNVALIDATED")
    return app
