"""
upload_to_r2.py — sync PS5 scraper outputs to Cloudflare R2 (bucket: ps5)
Reads creds from env vars: R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY,
                           R2_ACCOUNT_ID, R2_BUCKET

R2 key layout:
  games.json
  games_cache.json
  {game-slug}/cover.jpg
  {game-slug}/screenshot_1.jpg
  ...

The local screenshots/ prefix is stripped so files land at the bucket
root level inside their game slug folder, not under screenshots/.

SPEED: list_objects_v2() fetches ALL existing keys in one paginated bulk call,
stores them in a set, then skips any file already in the set with zero extra
API calls. Only genuinely new files are uploaded.
"""
import os, mimetypes, sys
from pathlib import Path
import boto3
from botocore.config import Config

_REQUIRED_ENV = ["R2_ACCOUNT_ID", "R2_BUCKET", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY"]
_missing = [v for v in _REQUIRED_ENV if not os.environ.get(v)]
if _missing:
    print(f"ERROR: missing required environment variable(s): {', '.join(_missing)}", file=sys.stderr)
    sys.exit(1)

R2_ENDPOINT = f"https://{os.environ['R2_ACCOUNT_ID']}.r2.cloudflarestorage.com"
R2_BUCKET   = os.environ["R2_BUCKET"]

s3 = boto3.client(
    "s3",
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
    aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
    config=Config(signature_version="s3v4"),
    region_name="auto",
)

SCREENSHOTS_DIR = Path("screenshots")

# ── Bulk-fetch all existing R2 keys once ─────────────────────────────────────
print("Fetching existing R2 keys (one-time bulk list)...")
_existing_keys: set[str] = set()
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(Bucket=R2_BUCKET):
    for obj in page.get("Contents", []):
        _existing_keys.add(obj["Key"])
print(f"  {len(_existing_keys):,} keys already in R2 bucket '{R2_BUCKET}'")

def upload(local: Path, key: str):
    if key in _existing_keys:
        return  # already in R2 — skip silently
    ct = mimetypes.guess_type(str(local))[0] or "application/octet-stream"
    print(f"  upload  {key}  ({local.stat().st_size:,} bytes)")
    s3.upload_file(str(local), R2_BUCKET, key, ExtraArgs={"ContentType": ct})

uploaded = 0
skipped  = 0

# ── JSON outputs ──────────────────────────────────────────────────────────────
# Deduplicate both JSON files by 'url' before uploading.
# Duplicates cause double entries in the game UI.
import json as _json

def _dedup_json_file(name: str) -> bool:
    """
    Read a JSON array file, remove duplicate entries by 'url' (first wins),
    write it back if any dupes were found, return True if file exists.
    """
    p = Path(name)
    if not p.exists():
        print(f"  missing: {name}")
        return False
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = _json.load(f)
        if not isinstance(data, list):
            print(f"  [WARN] {name} is not a JSON array — skipping dedup")
            return True
        seen_urls: set = set()
        deduped = []
        dupes = 0
        for entry in data:
            url = (entry.get("url") or "").strip().rstrip("/") + "/"
            if url and url in seen_urls:
                dupes += 1
                continue
            if url:
                seen_urls.add(url)
            deduped.append(entry)
        if dupes:
            print(f"  [dedup] {name}: removed {dupes} duplicate(s) ({len(data)} → {len(deduped)} entries)")
            tmp = str(p) + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                _json.dump(deduped, f, ensure_ascii=False, indent=2)
            os.replace(tmp, str(p))
        else:
            print(f"  [dedup] {name}: no duplicates found ({len(deduped)} entries)")
    except Exception as e:
        print(f"  [WARN] dedup failed for {name}: {e}")
    return True

for name in ["games_ps5.json", "games_ps5_cache.json"]:
    if _dedup_json_file(name):
        p = Path(name)
        ct = mimetypes.guess_type(name)[0] or "application/octet-stream"
        print(f"  upload  {name}  ({p.stat().st_size:,} bytes)")
        s3.upload_file(str(p), R2_BUCKET, name, ExtraArgs={"ContentType": ct})
        uploaded += 1

# ── Screenshots ───────────────────────────────────────────────────────────────
if SCREENSHOTS_DIR.exists():
    for f in sorted(SCREENSHOTS_DIR.rglob("*")):
        if not f.is_file():
            continue
        relative_key = f.relative_to(SCREENSHOTS_DIR)
        key = str(relative_key).replace("\\", "/")
        if key in _existing_keys:
            skipped += 1
            continue
        upload(f, key)
        uploaded += 1
else:
    print("  screenshots/ not found — skipping")

print(f"\nDone. {uploaded} file(s) uploaded, {skipped} already existed in R2 (skipped).")
