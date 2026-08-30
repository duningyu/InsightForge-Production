"""Check participant health endpoints without exposing response bodies."""
from __future__ import annotations
import argparse, json, time, urllib.request

def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--base', action='append', required=True); args = ap.parse_args(); out = []
    for url in args.base:
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(url.rstrip('/') + '/api/health', timeout=5) as response:
                out.append({'participant': url, 'http_status': response.status, 'latency_ms': round((time.perf_counter()-started)*1000)})
        except Exception:
            out.append({'participant': url, 'http_status': None, 'latency_ms': None})
    print(json.dumps(out))

if __name__ == '__main__':
    main()
