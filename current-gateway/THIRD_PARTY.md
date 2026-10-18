# Third-party components

Gateway dependencies are pinned with hashes in `requirements.lock`: Flask, Werkzeug, Jinja2, MarkupSafe, Click, ItsDangerous, Blinker, and Waitress. They are installed separately and retain their respective license terms. Dependency wheels and their bundled license files are not distributed in this source copy; consult the installed distributions or upstream projects for license texts.

ESP32 firmware source uses the separately installed Espressif Arduino core and its Wi-Fi, network, and Mbed TLS libraries. The retained build helper targets Espressif Arduino core 3.3.7. Toolchain binaries and provisioned firmware binaries are not included.

Supporting Observer source imports BCC. Offline AI source imports NumPy, scikit-learn, and Joblib. Those dependencies are separate from the Gateway lockfile and are not vendored here.

The public presentation uses generic hand-authored SVG replacements for omitted photographs and institutional logo assets. No omitted image rights or permissions are inferred.

No project `LICENSE` file was included in the supplied archive, and no project license is selected by this sanitization. See [publication notes](../PUBLICATION.md). Historical dependency, compile, and test statements are not new verification results for this copy.
