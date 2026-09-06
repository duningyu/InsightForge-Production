"""Actual loopback HTTP/browser account flow; temporary data, no real secrets."""
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
            marker in key.upper() for marker in ("API_KEY", "TOKEN", "PASSWORD")):
        os.environ.pop(key, None)
original = socket.socket.connect
blocked = []


def loopback(sock, address):
    if not isinstance(address, tuple) or address[0] not in {"127.0.0.1", "::1"}:
        blocked.append("external")
        raise AssertionError("External connection forbidden")
    return original(sock, address)


socket.socket.connect = loopback
socket.socket.connect_ex = loopback
with tempfile.TemporaryDirectory(prefix="insightforge-account-browser-") as temporary:
    os.environ["INSIGHTFORGE_DATABASE_PATH"] = str(Path(temporary) / "unused.sqlite3")
    os.environ["RUNTIME_DIR"] = str(Path(temporary) / "unused-runtime")
    from app.config import Settings
    from app.main import create_app
    import uvicorn
    cancel = "--cancel" in sys.argv
    competitor = "--competitor" in sys.argv
    business = "--business" in sys.argv or cancel or competitor
    if cancel:
        from browser_cancel_fixture import install_transport, prepare, verify
        calls = install_transport()
    elif business:
        from browser_business_fixture import install_transport, prepare, verify
        calls = install_transport()
    app = create_app(seed=False, settings_override=Settings(
        accounts_enabled=True, accounts_dir=Path(temporary) / "accounts",
        beta_mode=business, beta_managed_mode=business, daily_user_limits_enabled=False,
        managed_qwen_api_key="TEST_ONLY_SYNTHETIC" if business else None,
        managed_bailian_api_key="TEST_ONLY_SYNTHETIC" if business else None))
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
            time.sleep(.05)
        assert server.started, "lifespan startup failed"
        import json
        data = {"url": f"http://127.0.0.1:{port}", "invites": [app.state.accounts.issue_invite() for _ in range(2)]}
        if competitor:
            from browser_business_fixture import prepare_competitor
            data.update(prepare_competitor(app, data["url"], data["invites"][0]))
        elif business:
            data.update(prepare(app, data["url"], data["invites"][0]))
        scenario = "competitor_browser.cjs" if competitor else "account_cancel_browser.cjs" if cancel else "account_business_browser.cjs" if business else "account_flow_browser.cjs"
        result = subprocess.run(["node", str(ROOT / "tests" / scenario)],
                                input=json.dumps(data), text=True, cwd=ROOT)
        assert result.returncode == 0, "Browser scenario failed"
        if competitor:
            from browser_business_fixture import verify_competitor
            verify_competitor(app, data, calls)
        elif business:
            verify(app, data, calls)
        assert not blocked, "External attempt detected"
        print("Application lifespan executed; real external connections=0; blocked attempts=0")
    finally:
        server.should_exit = True
        thread.join(timeout=15)
        listener.close()
