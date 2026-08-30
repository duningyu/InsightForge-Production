"""Build a deterministic closed-beta source artifact with private data excluded."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from datetime import datetime
from pathlib import Path


EXCLUDED_DIRECTORIES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "reports",
    "backups",
    "runtime",
    "data",
    "artifacts",
    "dist",
    "build",
}
EXCLUDED_SUFFIXES = {".db", ".sqlite", ".sqlite3", ".pyc", ".zip"}
REQUIRED_PATHS = {
    "Dockerfile",
    "docker-compose.yml",
    "deploy/beta/Caddyfile.template",
}


def _included(relative: Path) -> bool:
    if any(part in EXCLUDED_DIRECTORIES for part in relative.parts[:-1]):
        return False
    name = relative.name
    if name == "beta_invites_private.csv":
        return False
    if name == ".env" or (name.startswith(".env.") and name != ".env.example"):
        return False
    if name.endswith(".sha256.txt") or relative.suffix.lower() in EXCLUDED_SUFFIXES:
        return False
    return True


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(*, project_root: Path, output_dir: Path, release_date: str) -> dict[str, str | int]:
    root = project_root.resolve()
    try:
        timestamp = datetime.strptime(release_date, "%Y%m%d")
    except ValueError as exc:
        raise ValueError("RELEASE_DATE_MUST_BE_YYYYMMDD") from exc
    missing = [relative for relative in sorted(REQUIRED_PATHS) if not (root / relative).is_file()]
    if missing:
        raise ValueError("RELEASE_REQUIRED_PATH_MISSING:" + ",".join(missing))

    files = [
        path for path in root.rglob("*")
        if path.is_file() and _included(path.relative_to(root))
    ]
    output_dir.mkdir(parents=True, exist_ok=True)
    archive = output_dir / f"InsightForge_Closed_Beta_Phase_A_{release_date}.zip"
    checksum = archive.with_suffix(".sha256.txt")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(f"InsightForge/{relative}")
            info.date_time = (timestamp.year, timestamp.month, timestamp.day, 0, 0, 0)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            bundle.writestr(info, path.read_bytes(), compresslevel=9)
    sha256 = _digest(archive)
    checksum.write_text(f"{sha256}  {archive.name}\n", encoding="utf-8")
    return {
        "archive": str(archive.resolve()),
        "checksum": str(checksum.resolve()),
        "sha256": sha256,
        "file_count": len(files),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()
    try:
        receipt = build(
            project_root=Path(args.project_root),
            output_dir=Path(args.output_dir),
            release_date=args.date,
        )
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps(receipt, ensure_ascii=False))


if __name__ == "__main__":
    main()
