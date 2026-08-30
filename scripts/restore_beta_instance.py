"""Restore exactly one participant SQLite database from a validated backup."""
from __future__ import annotations
import argparse, shutil, sqlite3
from pathlib import Path

def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument('--participant', required=True); ap.add_argument('--backup', required=True); ap.add_argument('--instances-root', required=True); a = ap.parse_args()
    if not a.participant.startswith('beta_'):
        raise SystemExit('participant must be beta_###')
    src = Path(a.backup); dst = Path(a.instances_root) / a.participant / 'insightforge.sqlite3'
    if not src.is_file(): raise SystemExit('backup not found')
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists(): shutil.copy2(dst, dst.with_suffix('.before_restore.sqlite3'))
    shutil.copy2(src, dst)
    db = sqlite3.connect(dst)
    try:
        if db.execute('pragma integrity_check').fetchone()[0] != 'ok' or db.execute('pragma foreign_key_check').fetchall():
            raise SystemExit('restored database integrity check failed')
    finally: db.close()
if __name__ == '__main__': main()
