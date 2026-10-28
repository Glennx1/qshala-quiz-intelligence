import os
import sys
import time
import mimetypes
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import boto3
from botocore.config import Config

account_id = os.environ.get("R2_ACCOUNT_ID", "2645378d746252bf15f26689feadc92a")
access_key_id = os.environ.get("R2_ACCESS_KEY_ID", "8a98d96e8ab35fa98e940687a97dbdd4")
secret_access_key = os.environ.get("R2_SECRET_ACCESS_KEY", "3b991993a8a7ef56eb1103c74743b1826982ed78af1ee3ddabf283cfbd880f5e")
bucket_name = os.environ.get("R2_BUCKET_NAME", "qshala-media")
endpoint_url = f"https://{account_id}.r2.cloudflarestorage.com"

s3 = boto3.client(
    "s3",
    endpoint_url=endpoint_url,
    aws_access_key_id=access_key_id,
    aws_secret_access_key=secret_access_key,
    config=Config(signature_version="s3v4", max_pool_connections=30),
    region_name="auto",
)

slides_dir = Path("frontend/public/static/slides")
if not slides_dir.exists():
    print(f"Error: {slides_dir} does not exist.")
    sys.exit(1)

print("1. Fetching existing objects in R2 to avoid re-uploading...")
paginator = s3.get_paginator('list_objects_v2')
existing_keys = set()
for page in paginator.paginate(Bucket=bucket_name, Prefix="slides/"):
    for obj in page.get('Contents', []):
        existing_keys.add(obj['Key'])

print(f"Found {len(existing_keys)} existing slide files in R2.")

files_to_sync = []
total_bytes = 0
for doc_dir in slides_dir.iterdir():
    if not doc_dir.is_dir():
        continue
    for f in doc_dir.rglob("*"):
        if f.is_file():
            rel = f.relative_to(slides_dir).as_posix()
            r2_key = f"slides/{rel}"
            if r2_key not in existing_keys:
                sz = f.stat().st_size
                files_to_sync.append((f, r2_key, sz))
                total_bytes += sz

print(f"2. Files to upload: {len(files_to_sync)} ({total_bytes / (1024*1024):.1f} MB)")
if not files_to_sync:
    print("All slide files are already synced to R2!")
    sys.exit(0)

uploaded_count = 0
uploaded_bytes = 0
failed_files = []
start_time = time.time()

def upload_single_file(item):
    file_path, key, size = item
    content_type, _ = mimetypes.guess_type(key)
    if not content_type:
        content_type = "application/octet-stream"
    try:
        s3.upload_file(
            Filename=str(file_path),
            Bucket=bucket_name,
            Key=key,
            ExtraArgs={"ContentType": content_type}
        )
        return True, key, size, None
    except Exception as e:
        return False, key, size, str(e)

print(f"3. Uploading with 16 parallel threads...")
with ThreadPoolExecutor(max_workers=16) as executor:
    futures = [executor.submit(upload_single_file, item) for item in files_to_sync]
    for future in as_completed(futures):
        success, key, size, err = future.result()
        if success:
            uploaded_count += 1
            uploaded_bytes += size
        else:
            failed_files.append((key, err))
        
        if uploaded_count % 50 == 0 or uploaded_count == len(files_to_sync):
            elapsed = time.time() - start_time
            mb = uploaded_bytes / (1024 * 1024)
            speed = mb / elapsed if elapsed > 0 else 0
            pct = (uploaded_count / len(files_to_sync)) * 100
            print(f"[{pct:5.1f}%] {uploaded_count}/{len(files_to_sync)} files uploaded ({mb:.1f} MB @ {speed:.2f} MB/s)")

total_elapsed = time.time() - start_time
print("\n" + "="*50)
print(f"Sync complete in {total_elapsed:.1f}s!")
print(f"Uploaded: {uploaded_count} files ({uploaded_bytes / (1024*1024):.1f} MB)")
if failed_files:
    print(f"Failed: {len(failed_files)} files")
    for k, err in failed_files[:5]:
        print(f" - {k}: {err}")
else:
    print("All files uploaded successfully with 0 errors!")
print("="*50)
