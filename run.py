"""Video in, SPADL-like Excel out.

Runs T-DEED first, then Eagle, then writes one workbook. Body part and result
are left empty. x = 0 is the goal on the left of the image.
"""

import argparse
import subprocess
import sys
from pathlib import Path

import cv2

from build_table import build

FOOTBALL = Path(__file__).resolve().parents[1]
TDEED = FOOTBALL / "T-DEED"
EAGLE = FOOTBALL / "Eagle"
TDEED_PYTHON = TDEED / ".venv" / "Scripts" / "python.exe"
EAGLE_PYTHON = EAGLE / ".venv" / "Scripts" / "python.exe"


def video_info(path):
    capture = cv2.VideoCapture(str(path))
    fps = capture.get(cv2.CAP_PROP_FPS)
    frames = capture.get(cv2.CAP_PROP_FRAME_COUNT)
    width = capture.get(cv2.CAP_PROP_FRAME_WIDTH)
    capture.release()
    if not fps or fps < 1 or fps > 120:
        fps = 25.0
    return float(fps), int(frames), int(width)


def run_tdeed(video, fps, events_json):
    command = [
        str(TDEED_PYTHON),
        "inference.py",
        "--model",
        "SoccerNetBall_challenge1",
        "--video_path",
        str(video),
        "--frame_width",
        "796",
        "--frame_height",
        "448",
        "--inference_threshold",
        "0.3",
        "--fps",
        str(fps),
        "--output_dir",
        str(events_json),
    ]
    subprocess.run(command, cwd=TDEED, check=True)


def run_eagle(video, fps):
    command = [
        str(EAGLE_PYTHON),
        "main.py",
        "--video_path",
        str(video),
        "--fps",
        str(int(round(fps))),
    ]
    subprocess.run(command, cwd=EAGLE, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", required=True)
    parser.add_argument("--period_id", type=int, default=1)
    parser.add_argument("--skip_models", action="store_true", help="Reuse events.json and Eagle output already on disk")
    args = parser.parse_args()

    video = Path(args.video).resolve()
    if not video.exists():
        raise SystemExit(f"Video not found: {video}")

    stem = video.stem
    out_dir = Path(__file__).resolve().parent / "output" / stem
    out_dir.mkdir(parents=True, exist_ok=True)
    events_json = out_dir / "events.json"
    eagle_dir = EAGLE / "output" / stem
    workbook = out_dir / "spadl.xlsx"

    fps, _frames, frame_width = video_info(video)
    if not args.skip_models:
        print("T-DEED", video.name)
        run_tdeed(video, fps, events_json)
        print("Eagle", video.name)
        run_eagle(video, fps)
    if not events_json.exists():
        raise SystemExit(f"T-DEED events were not written: {events_json}")
    if not (eagle_dir / "processed_data.json").exists():
        raise SystemExit(f"Eagle output was not written: {eagle_dir}")

    path, table = build(stem, events_json, eagle_dir, workbook, args.period_id, fps, frame_width)
    shown = table[["time_seconds", "type_name", "team_name", "player_id", "start_x", "start_y", "end_x", "end_y", "on_pitch"]]
    print(shown.to_string(index=False))
    print("Wrote", path)


if __name__ == "__main__":
    sys.exit(main())
