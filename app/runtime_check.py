"""Safe dependency verification used by the local launcher."""

from __future__ import annotations

import importlib
import sys


REQUIRED_LAUNCH_MODULES = ("fastapi", "uvicorn")
WINDOWS_REQUIRED_LAUNCH_MODULES = ("keyring",)


def main() -> int:
    try:
        required_modules = REQUIRED_LAUNCH_MODULES
        if sys.platform == "win32":
            required_modules += WINDOWS_REQUIRED_LAUNCH_MODULES
        for module_name in required_modules:
            importlib.import_module(module_name)
    except Exception:
        print(
            "[InsightForge] runtime-dependencies=missing; run the launcher bootstrap again",
            file=sys.stderr,
        )
        return 1
    print("[InsightForge] runtime-dependencies=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
