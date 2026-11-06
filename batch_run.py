"""Run the video-to-SPADL chain on every clip in batch/clips."""

import subprocess
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
PYTHON = Path(r"C:\Users\LOQ\Desktop\Footbal Ai\Eagle\.venv\Scripts\python.exe")
CLIPS = HERE / "batch" / "clips"
SUMMARY = HERE / "batch" / "summary.csv"


def main():
    rows = []
    clips = sorted(CLIPS.glob("*.mp4"))
    for index, clip in enumerate(clips, start=1):
        print(f"\n=== {index}/{len(clips)} {clip.name} ===", flush=True)
        result = subprocess.run(
            [str(PYTHON), str(HERE / "run.py"), "--video", str(clip), "--period_id", "1"],
            cwd=HERE,
        )
        workbook = HERE / "output" / clip.stem / "spadl.xlsx"
        row = {"clip": clip.name, "exit_code": result.returncode, "events": 0, "on_pitch": 0, "workbook": ""}
        if workbook.exists():
            table = pd.read_excel(workbook, sheet_name="actions")
            row["events"] = int(len(table))
            row["on_pitch"] = int(table["on_pitch"].fillna(False).sum()) if "on_pitch" in table.columns else 0
            row["workbook"] = str(workbook)
        rows.append(row)
        pd.DataFrame(rows).to_csv(SUMMARY, index=False)
        print(row, flush=True)
    print("Summary", SUMMARY, flush=True)


if __name__ == "__main__":
    sys.exit(main())
