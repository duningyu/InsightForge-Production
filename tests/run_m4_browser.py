"""Loopback browser/operator rehearsal for M4, using temporary data only."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for key in list(os.environ):
    if key.startswith(("INSIGHTFORGE_", "BETA_", "MANAGED_", "OPENAI_")) or any(
        marker in key.upper() for marker in ("API_KEY", "TOKEN", "PASSWORD")
    ):
        os.environ.pop(key, None)

original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex
blocked = []


def loopback_connect(sock, address):
    if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
        blocked.append("external")
        raise AssertionError("External connection forbidden")
    return original_connect(sock, address)


def loopback_connect_ex(sock, address):
    if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
        blocked.append("external")
        return 13
    return original_connect_ex(sock, address)


socket.socket.connect = loopback_connect
socket.socket.connect_ex = loopback_connect_ex

with tempfile.TemporaryDirectory(prefix="insightforge-m4-browser-") as temporary:
    temporary_path = Path(temporary)
    os.environ["INSIGHTFORGE_DATABASE_PATH"] = str(temporary_path / "unused.sqlite3")
    os.environ["RUNTIME_DIR"] = str(temporary_path / "runtime")
    from app.config import Settings
    from app.main import create_app
    import uvicorn

    app = create_app(
        seed=False,
        settings_override=Settings(
            accounts_enabled=True,
            accounts_dir=temporary_path / "accounts",
            beta_mode=False,
            beta_managed_mode=False,
            daily_user_limits_enabled=False,
        ),
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        for _ in range(200):
            if server.started:
                break
            time.sleep(0.05)
        assert server.started, "lifespan startup failed"
        data = {
            "url": f"http://127.0.0.1:{port}",
            "invites": [app.state.accounts.issue_invite() for _ in range(3)],
        }
        result = subprocess.run(
            ["node", str(ROOT / "tests" / "m4_flow_browser.cjs")],
            input=json.dumps(data),
            text=True,
            cwd=ROOT,
        )
        assert result.returncode == 0, "M4 browser scenario failed"
        assert not blocked, "External attempt detected"
        print("M4 browser/operator rehearsal completed; external=0")
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
