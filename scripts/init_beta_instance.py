"""Create a clean participant SQLite/runtime pair without copying production data."""
from __future__ import annotations
import argparse, hashlib, json, re, sqlite3
from datetime import datetime, timezone
from pathlib import Path
from app.db import Database
from app.services.beta_runtime import RuntimePaths, validate_participant_id

def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument('--participant-id', required=True); ap.add_argument('--database-path', required=True); ap.add_argument('--runtime-dir', required=True); ap.add_argument('--beta-release-id', required=True); args = ap.parse_args()
    participant = validate_participant_id(args.participant_id); db_path = Path(args.database_path).expanduser().resolve()
    if db_path.exists() and db_path.stat().st_size:
        raise SystemExit('INSTANCE_ALREADY_INITIALIZED')
    db_path.parent.mkdir(parents=True, exist_ok=True); runtime = RuntimePaths.from_root(args.runtime_dir)
    db = Database(db_path); db.init_schema()
    receipt = {'participant_id':participant,'database_path':str(db_path),'runtime_root':str(runtime.root),'schema_version':'3.0','beta_release_id':args.beta_release_id,'demo_initialized':False,'project_count':0,'database_sha256':hashlib.sha256(db_path.read_bytes()).hexdigest(),'created_at':datetime.now(timezone.utc).isoformat()}
    print(json.dumps(receipt, ensure_ascii=False))
if __name__ == '__main__': main()
