import logging
import fcntl
import os
from waitress import serve
from .app import create_app
from .config import load_config
def main():
    try:
        config=load_config(os.environ["SENTINEL_CONFIG"])
        config.data_dir.mkdir(mode=0o700,parents=True,exist_ok=True)
        instance_lock=(config.data_dir/".instance.lock").open("a")
        fcntl.flock(instance_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        app=create_app(config)
    except Exception:raise SystemExit("Gateway configuration or evidence storage unavailable; startup refused.") from None
    # No access logs, request headers, exception paths or network identities in public output.
    logging.getLogger("waitress").setLevel(logging.CRITICAL)
    serve(app,host="127.0.0.1",port=8080,threads=4,connection_limit=32,
          max_request_body_size=4096,max_request_header_size=4096,
          channel_timeout=15,ident="",clear_untrusted_proxy_headers=True,
          trusted_proxy="127.0.0.1",trusted_proxy_headers={"x-forwarded-proto"})
if __name__=="__main__":main()
