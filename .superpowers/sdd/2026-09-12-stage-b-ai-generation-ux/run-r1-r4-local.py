"""Run explicitly selected pytest cases with outbound sockets disabled."""
import os
from pathlib import Path
import socket
import sys

root = Path(__file__).resolve().parents[3]
os.chdir(root)
sys.path.insert(0, str(root))
for name in list(os.environ):
    if any(token in name.upper() for token in ("OPENAI", "ANTHROPIC", "PROVIDER", "GEMINI", "DEEPSEEK", "SEARCH", "INSIGHTFORGE")):
        os.environ.pop(name, None)
os.environ["REAL_PROVIDER_STAGE_B"] = "false"
os.environ["PYTHONUTF8"] = "1"
attempts = []
original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex


def guarded(original):
    def connect(sock, address):
        if sock.family in (socket.AF_INET, socket.AF_INET6) and address[0] not in {"127.0.0.1", "::1", "localhost"}:
            attempts.append(True)
            raise RuntimeError("External transport disabled for R1-R4 tests")
        return original(sock, address)
    return connect


socket.socket.connect = guarded(original_connect)
socket.socket.connect_ex = guarded(original_connect_ex)
import pytest

status = pytest.main(sys.argv[1:])
print(f"EXTERNAL_CONNECTION_ATTEMPTS={len(attempts)}")
raise SystemExit(status or bool(attempts))
