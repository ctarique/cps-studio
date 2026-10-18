"""Explicit two-device catalog. Only Device 1 has a runtime transport."""
import hashlib
import json

PROFILES = {
    "led-status-v1": {"id":"esp32-cam", "number":1, "name":"ESP32-CAM",
        "experiment":"led-status-v1", "experiment_name":"LED Experiment", "status":"AVAILABLE"},
    "autonomous-car-v1": {"id":"esp32-wrover", "number":2, "name":"ESP32-WROVER",
        "experiment":"autonomous-car-v1", "experiment_name":"Autonomous Car Experiment", "status":"IN_DEVELOPMENT"},
}

def catalog():
    return [dict(value) for value in PROFILES.values()]

def policy_reference(config):
    spec={"experiment":"led-status-v1", "max_steps":config.led_policy_max_steps,
          "max_duration_ms":config.led_policy_max_duration_ms, "allow_led":config.led_policy_allow_led}
    return hashlib.sha256(json.dumps(spec,sort_keys=True).encode()).hexdigest()

def policy_rejections(config, artifact):
    reasons=[]
    if artifact["steps"] > config.led_policy_max_steps:reasons.append("POLICY_STEP_LIMIT")
    if artifact["duration_ms"] > config.led_policy_max_duration_ms:reasons.append("POLICY_DURATION_LIMIT")
    if artifact["uses_led"] and not config.led_policy_allow_led:reasons.append("POLICY_LED_DISABLED")
    return reasons
