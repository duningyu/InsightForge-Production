"""SQLite-safe backups for participant instances (read-only source)."""
from __future__ import annotations
import argparse, hashlib, json, sqlite3
from datetime import datetime, timezone
from pathlib import Path

def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument('--instances-root', required=True); ap.add_argument('--output-dir', required=True)
    a = ap.parse_args(); out = Path(a.output_dir); out.mkdir(parents=True, exist_ok=True); manifest=[]
    for src in sorted(Path(a.instances_root).glob('beta_*/insightforge.sqlite3')):
        dst = out / f'{src.parent.name}.sqlite'; src_db=sqlite3.connect(src); dst_db=sqlite3.connect(dst)
        with dst_db: src_db.backup(dst_db)
        src_db.close(); dst_db.close(); digest=hashlib.sha256(dst.read_bytes()).hexdigest()
        db=sqlite3.connect(dst); projects=db.execute('select count(*) from projects').fetchone()[0]; docs=db.execute('select count(*) from documents').fetchone()[0]; db.close()
        manifest.append({'participant_id':src.parent.name,'source_db':str(src),'backup_file':str(dst),'sha256':digest,'project_count':projects,'document_count':docs,'created_at':datetime.now(timezone.utc).isoformat()})
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2), encoding='utf-8')
if __name__ == '__main__': main()
