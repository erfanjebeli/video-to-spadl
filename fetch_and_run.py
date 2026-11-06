"""Download ten openly licensed wide football clips and run the SPADL pipeline.

Sources are Creative Commons files from Wikimedia Commons, listed in
clips_manifest.tsv. Each file is trimmed to the first 8 seconds so Eagle can
finish on a CPU laptop. Broadcast rips are not used.
"""

import csv
import subprocess
import sys
import urllib.request
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "clips_manifest.tsv"
INBOX = HERE / "wide_clips" / "source"
CLIPS = HERE / "wide_clips" / "first8s"
PYTHON = Path(r"C:\Users\LOQ\Desktop\Footbal Ai\Eagle\.venv\Scripts\python.exe")
SECONDS = 8


def download(url, dest):
    if dest.exists() and dest.stat().st_size > 100_000:
        return
    request = urllib.request.Request(url, headers={"User-Agent": "video-to-spadl/1.0 (local research)"})
    with urllib.request.urlopen(request, timeout=180) as response, dest.open("wb") as handle:
        while True:
            chunk = response.read(1024 * 256)
            if not chunk:
                break
            handle.write(chunk)


def trim(src, dest):
    capture = cv2.VideoCapture(str(src))
    if not capture.isOpened():
        raise RuntimeError(f"OpenCV could not open {src.name}")
    fps = capture.get(cv2.CAP_PROP_FPS) or 25
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    limit = max(1, int(round(fps * SECONDS)))
    writer = cv2.VideoWriter(str(dest), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not write {dest.name}")
    written = 0
    while written < limit:
        ok, frame = capture.read()
        if not ok:
            break
        writer.write(frame)
        written += 1
    capture.release()
    writer.release()
    if written < fps:
        raise RuntimeError(f"{src.name} produced only {written} frames")
    return fps, width, height, written


def read_manifest():
    rows = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = line.strip().lstrip("\ufeff")
        if not line:
            continue
        title, size, url = line.split("\t")
        rows.append((title.replace("File:", ""), url))
    return rows


def main():
    INBOX.mkdir(parents=True, exist_ok=True)
    CLIPS.mkdir(parents=True, exist_ok=True)
    summary = HERE / "wide_clips" / "summary.txt"
    lines = []
    for index, (title, url) in enumerate(read_manifest(), start=1):
        slug = f"wide_{index:02d}"
        source = INBOX / f"{slug}{Path(url).suffix or '.webm'}"
        clip = CLIPS / f"{slug}.mp4"
        print(f"DOWNLOAD {slug} {title}", flush=True)
        download(url, source)
        print(f"TRIM {slug}", flush=True)
        fps, width, height, frames = trim(source, clip)
        print(f"RUN {slug} {width}x{height} {frames} frames @ {fps:.2f}", flush=True)
        result = subprocess.run(
            [str(PYTHON), str(HERE / "run.py"), "--video", str(clip), "--period_id", "1"],
            cwd=HERE,
        )
        status = "ok" if result.returncode == 0 else f"fail {result.returncode}"
        workbook = HERE / "output" / slug / "spadl.xlsx"
        lines.append(f"{slug}\t{status}\t{workbook.exists()}\t{title}")
        summary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"DONE {slug} {status}", flush=True)
    print("BATCH FINISHED", flush=True)


if __name__ == "__main__":
    sys.exit(main())
