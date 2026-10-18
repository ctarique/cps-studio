# Local software simulator

Requires macOS or Linux, Python 3.11 or newer, and a C++17 compiler for the native firmware checks. Initial dependency installation requires Internet access.

From `current-gateway/`:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python tools/verify_bundle.py
python tools/test.py
python tools/home.py
```

The test command runs Python tests and two native host firmware checks. The launcher starts the Gateway on loopback port 8080 with the in-process, nonphysical simulator. It does not configure a vehicle device.

1. Open `http://127.0.0.1:8080` and Administration at `http://127.0.0.1:8080/admin`.
2. Read the administrator credential privately from `.local/home.env` and enter it on the Administration page. There is no student token to enter.
3. Establish the simulator's default state through instructor recovery if needed, then Unlock. Unlock invalidates earlier preparation.
4. Select LED Flasher. Use Guided ON/OFF, or enter a permitted Custom Program, select Check, and select Run once when Ready to Run.
5. Inspect completion feedback and `http://127.0.0.1:8080/display`. Use a fresh Check for another Custom Program execution.
6. Stop with Ctrl-C.

The launcher creates or reuses private credentials and simulator evidence under `.local/`. Keep that directory out of Git and preserve earlier attempts when retaining demonstration history. Use a separate copy for a separate demonstration history.

Simulation does not establish Wi-Fi association, ESP32 firmware execution, physical stopping behavior, or HDMI presentation. Seasonal slideshow assets and runtime state are external to this repository. See [source status](../../SOURCE-STATUS.md) for limitations and [verification](../../VERIFICATION.md) for recorded public-copy checks.
