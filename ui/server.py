"""Local page: choose a video, run the existing pipeline.

Outputs stay where run.py already writes them. This page does not show them.
"""

import atexit
import json
import math
import os
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote
from urllib.request import urlopen

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PYTHON = ROOT.parent / "Eagle" / ".venv" / "Scripts" / "python.exe"
RUN = ROOT / "run.py"
PICK = HERE / "pick-video.ps1"
HOST = "127.0.0.1"
PORT = 8765
APP = "video-to-spadl"

VIDEO_SUFFIXES = {
    ".mp4",
    ".mov",
    ".mkv",
    ".avi",
    ".webm",
    ".m4v",
    ".ogv",
    ".wmv",
    ".mpeg",
    ".mpg",
}

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

lock = threading.Lock()
pick_lock = threading.Lock()
state = {
    "app": APP,
    "status": "idle",
    "message": "آماده",
    "name": "",
    "path": "",
}
process = None


def say(text):
    try:
        print(text, flush=True)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"), flush=True)


def set_state(**kwargs):
    with lock:
        state.update(kwargs)


def snapshot():
    with lock:
        return dict(state)


def stop_pipeline():
    global process
    with lock:
        proc = process
    if proc is None or proc.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
        capture_output=True,
        creationflags=NO_WINDOW,
    )


atexit.register(stop_pipeline)


def phase(line):
    text = line.strip()
    if text.startswith("T-DEED"):
        return "در حال تشخیص رویداد."
    if text.startswith("Eagle"):
        return "در حال ردیابی بازیکن و توپ."
    if text.startswith("Wrote"):
        return "در حال ذخیره."
    return None


def friendly_error(tail):
    blob = "\n".join(tail)
    if "Video not found" in blob:
        return "فایل ویدیو پیدا نشد."
    if "T-DEED events were not written" in blob:
        return "متوقف شد. رویدادها ساخته نشد."
    if "Eagle output was not written" in blob:
        return "متوقف شد. ردیابی ساخته نشد."
    return "متوقف شد. شرح خطا در پنجره مشکی است."


def output_dir(stem):
    folder = (ROOT / "output" / stem).resolve()
    output = (ROOT / "output").resolve()
    if folder.parent != output:
        return None
    return folder


def safe_stem(raw):
    name = unquote(raw or "").strip().strip("/")
    if not name or name != Path(name).name or any(part in name for part in ("..", "/", "\\")):
        return None
    folder = output_dir(name)
    if folder is None or not folder.is_dir():
        return None
    return name


def remember_source(video):
    folder = output_dir(video.stem)
    if folder is None:
        return
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"video": str(video)}
    (folder / "source.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def source_video(stem):
    folder = output_dir(stem)
    if folder is None:
        return None
    pointer = folder / "source.json"
    if not pointer.is_file():
        return None
    try:
        payload = json.loads(pointer.read_text(encoding="utf-8"))
        video = Path(payload.get("video", "")).expanduser().resolve()
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None
    if video.is_file() and video.suffix.lower() in VIDEO_SUFFIXES:
        return video
    return None


def number(value):
    try:
        if value is None or value == "":
            return None
        number_value = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number_value) or math.isinf(number_value):
        return None
    return round(number_value, 2)


def load_events(stem):
    folder = output_dir(stem)
    workbook = folder / "spadl.xlsx" if folder else None
    if workbook is None or not workbook.is_file():
        return None
    import pandas as pd

    frame = pd.read_excel(workbook, sheet_name="actions")
    events = []
    for record in frame.to_dict(orient="records"):
        events.append(
            {
                "time": number(record.get("time_seconds")) or 0,
                "type": None if record.get("type_name") is None or (isinstance(record.get("type_name"), float) and math.isnan(record.get("type_name"))) else str(record.get("type_name")),
                "x": number(record.get("start_x")),
                "y": number(record.get("start_y")),
            }
        )
    return events


def list_clips():
    output = ROOT / "output"
    found = []
    if not output.is_dir():
        return found
    for folder in sorted(output.iterdir()):
        if not folder.is_dir() or not (folder / "spadl.xlsx").is_file():
            continue
        video = source_video(folder.name)
        found.append({"stem": folder.name, "video_name": video.name if video else "", "has_video": video is not None})
    return found


def run_job(video):
    global process
    set_state(status="running", message="شروع شد.", name=video.name, path=str(video))
    say(f"RUN {video}")
    tail = []
    try:
        proc = subprocess.Popen(
            [str(PYTHON), "-u", str(RUN), "--video", str(video), "--period_id", "1"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=NO_WINDOW,
        )
        with lock:
            process = proc
        assert proc.stdout is not None
        for line in proc.stdout:
            say(line.rstrip("\n"))
            tail.append(line.rstrip())
            del tail[:-40]
            message = phase(line)
            if message:
                set_state(message=message)
        code = proc.wait()
        if code == 0:
            set_state(status="done", message="تمام شد.")
            say("DONE")
        else:
            set_state(status="error", message=friendly_error(tail))
            say(f"FAIL {code}")
    except Exception as exc:
        set_state(status="error", message="متوقف شد. شرح خطا در پنجره مشکی است.")
        say(f"FAIL {exc}")
    finally:
        with lock:
            process = None


def pick_video():
    dest = HERE / f".pick-{threading.get_ident()}.txt"
    if dest.exists():
        dest.unlink()
    subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-STA",
            "-File",
            str(PICK),
            "-OutFile",
            str(dest),
        ],
        check=False,
        cwd=ROOT,
        creationflags=NO_WINDOW,
    )
    if not dest.exists():
        return ""
    try:
        return dest.read_text(encoding="utf-8-sig").strip()
    finally:
        dest.unlink(missing_ok=True)


def font_file(url_path):
    name = url_path.rsplit("/", 1)[-1]
    if not name or name != Path(name).name or Path(name).suffix.lower() != ".woff2":
        return None
    candidate = (HERE / "fonts" / name).resolve()
    fonts = (HERE / "fonts").resolve()
    if candidate.parent != fonts or not candidate.is_file():
        return None
    return candidate


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        return

    def origin_ok(self):
        host, port = self.server.server_address[:2]
        allowed = {f"http://{host}:{port}", f"http://localhost:{port}"}
        origin = self.headers.get("Origin")
        if origin and origin not in allowed:
            self.send_json(403, {"ok": False, "message": "درخواست پذیرفته نشد."})
            return False
        return True

    def send_json(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def send_bytes(self, code, body, content_type):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if not getattr(self, "_head_only", False):
            self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            page = (HERE / "index.html").read_bytes()
            self.send_bytes(200, page, "text/html; charset=utf-8")
            return
        if path == "/watch":
            page = (HERE / "watch.html").read_bytes()
            self.send_bytes(200, page, "text/html; charset=utf-8")
            return
        if path == "/api/status":
            self.send_json(200, snapshot())
            return
        if path == "/api/clips":
            self.send_json(200, {"clips": list_clips()})
            return
        if path.startswith("/api/clips/"):
            self.handle_clip(path.removeprefix("/api/clips/"))
            return
        if path.startswith("/media/"):
            self.handle_media(path.removeprefix("/media/"))
            return
        font = font_file(path) if path.startswith("/fonts/") else None
        if font is not None:
            self.send_bytes(200, font.read_bytes(), "font/woff2")
            return
        self.send_json(404, {"ok": False, "message": "پیدا نشد."})

    def do_HEAD(self):
        self.close_connection = True
        self._head_only = True
        try:
            self.do_GET()
        finally:
            self._head_only = False

    def handle_clip(self, raw_stem):
        stem = safe_stem(raw_stem)
        if stem is None:
            self.send_json(404, {"ok": False, "message": "این اجرا پیدا نشد."})
            return
        try:
            events = load_events(stem)
        except (OSError, ValueError, ImportError) as exc:
            self.send_json(500, {"ok": False, "message": "جدول ایونت‌ها خوانده نشد."})
            say(f"READ {stem} {exc}")
            return
        if events is None:
            self.send_json(404, {"ok": False, "message": "جدول ایونت‌ها هنوز ساخته نشده."})
            return
        video = source_video(stem)
        self.send_json(
            200,
            {
                "stem": stem,
                "video_name": video.name if video else "",
                "media": f"/media/{stem}" if video else "",
                "events": events,
            },
        )

    def handle_media(self, raw_stem):
        stem = safe_stem(raw_stem)
        video = source_video(stem) if stem else None
        if video is None:
            self.send_json(404, {"ok": False, "message": "فایل ویدیو پیدا نشد."})
            return
        kind = {
            ".mp4": "video/mp4",
            ".m4v": "video/mp4",
            ".webm": "video/webm",
            ".ogv": "video/ogg",
            ".mov": "video/quicktime",
            ".mkv": "video/x-matroska",
            ".avi": "video/x-msvideo",
        }.get(video.suffix.lower(), "application/octet-stream")
        self.serve_range(video, kind)

    def serve_range(self, file_path, content_type):
        size = file_path.stat().st_size
        start, end = 0, size - 1
        status = 200
        range_header = self.headers.get("Range")
        if range_header and range_header.startswith("bytes="):
            piece = range_header.split("=", 1)[1].split(",", 1)[0].strip()
            left, _, right = piece.partition("-")
            try:
                if left == "":
                    length = int(right)
                    start = max(0, size - length)
                else:
                    start = int(left)
                    end = int(right) if right else size - 1
            except ValueError:
                self.send_error(416)
                return
            end = min(end, size - 1)
            if start < 0 or start > end or start >= size:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{size}")
                self.end_headers()
                return
            status = 206
        length = end - start + 1
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(length))
        if status == 206:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.end_headers()
        if getattr(self, "_head_only", False):
            return
        try:
            with file_path.open("rb") as handle:
                handle.seek(start)
                remaining = length
                while remaining > 0:
                    chunk = handle.read(min(256 * 1024, remaining))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (ConnectionError, OSError):
            return

    def do_POST(self):
        if not self.origin_ok():
            return
        path = self.path.split("?", 1)[0]
        if path == "/api/pick":
            self.handle_pick()
            return
        if path == "/api/run":
            self.handle_run()
            return
        if path.startswith("/api/clips/") and path.endswith("/source"):
            self.handle_bind_source(path[len("/api/clips/"):-len("/source")])
            return
        self.send_json(404, {"ok": False, "message": "پیدا نشد."})

    def handle_bind_source(self, raw_stem):
        stem = safe_stem(raw_stem.strip("/"))
        if stem is None:
            self.send_json(404, {"ok": False, "message": "این اجرا پیدا نشد."})
            return
        kind = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        length = int(self.headers.get("Content-Length", "0") or "0")
        if kind != "application/json" or length > 8192:
            self.send_json(400, {"ok": False, "message": "مسیر ویدیو خوانده نشد."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            video = Path(payload.get("path", "")).expanduser().resolve()
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            self.send_json(400, {"ok": False, "message": "مسیر ویدیو خوانده نشد."})
            return
        if video.stem != stem or not video.is_file() or video.suffix.lower() not in VIDEO_SUFFIXES:
            self.send_json(400, {"ok": False, "message": "این فایل با اجرای انتخاب‌شده یکی نیست."})
            return
        remember_source(video)
        self.send_json(200, {"ok": True, "video_name": video.name})

    def handle_pick(self):
        if snapshot()["status"] == "running":
            self.send_json(409, {"ok": False, "message": "یک اجرا در جریان است."})
            return
        if not pick_lock.acquire(blocking=False):
            self.send_json(409, {"ok": False, "message": "پنجره انتخاب فایل همین حالا باز است."})
            return
        try:
            chosen = pick_video()
        finally:
            pick_lock.release()
        if not chosen:
            self.send_json(200, {"ok": True, "path": "", "name": ""})
            return
        video = Path(chosen)
        self.send_json(200, {"ok": True, "path": str(video), "name": video.name})

    def handle_run(self):
        kind = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if kind != "application/json":
            self.send_json(400, {"ok": False, "message": "درخواست نامعتبر است."})
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length > 8192:
            self.send_json(400, {"ok": False, "message": "درخواست نامعتبر است."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            video = Path(payload.get("path", "")).expanduser().resolve()
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            self.send_json(400, {"ok": False, "message": "مسیر ویدیو خوانده نشد."})
            return
        if snapshot()["status"] == "running":
            self.send_json(409, {"ok": False, "message": "یک اجرا در جریان است."})
            return
        if not video.is_file():
            self.send_json(400, {"ok": False, "message": "فایل ویدیو پیدا نشد."})
            return
        if video.suffix.lower() not in VIDEO_SUFFIXES:
            self.send_json(400, {"ok": False, "message": "این پسوند ویدیو نیست."})
            return
        if not PYTHON.exists():
            self.send_json(500, {"ok": False, "message": "محیط اجرای مدل پیدا نشد."})
            return
        remember_source(video)
        set_state(status="running", message="شروع شد.", name=video.name, path=str(video))
        worker = threading.Thread(target=run_job, args=(video,), daemon=True)
        worker.start()
        self.send_json(202, {"ok": True, "status": "running"})


def already_running():
    try:
        with urlopen(f"http://{HOST}:{PORT}/api/status", timeout=2) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return body.get("app") == APP


def main():
    if not PYTHON.exists():
        say(f"Python not found: {PYTHON}")
        raise SystemExit(1)
    if not RUN.exists() or not (HERE / "index.html").exists():
        say("UI files are missing.")
        raise SystemExit(1)
    if already_running():
        if os.environ.get("V2S_NO_BROWSER") != "1":
            webbrowser.open(f"http://{HOST}:{PORT}")
        say("صفحه از قبل باز است.")
        return

    try:
        server = ThreadingHTTPServer((HOST, PORT), Handler)
    except OSError:
        say(f"پورت {PORT} اشغال است.")
        raise SystemExit(1)

    server.daemon_threads = True
    url = f"http://{HOST}:{PORT}"
    say(url)
    say("اینجا چیزی تایپ نکن.")
    say("برای بستن برنامه، همین پنجره را ببند.")
    if os.environ.get("V2S_NO_BROWSER") != "1":
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        say("بسته شد.")
    finally:
        stop_pipeline()
        server.server_close()


if __name__ == "__main__":
    main()
