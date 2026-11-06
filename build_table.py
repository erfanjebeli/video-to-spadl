"""Turn one T-DEED event file and one Eagle tracking folder into a SPADL-like workbook.

Start is the ball at the event frame. End is the ball at the next event.
Body part and result stay empty for an operator. Player id is the Eagle
track id of the person closest to the ball. Team 0 is the side whose goal
is x = 0, the goal on the left of the image.
"""

import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "Eagle"))

from eagle.orient import image_left_is_eagle_right, to_image_left_origin

FIELD_LENGTH = 105.0
FIELD_WIDTH = 68.0
GOAL_MOUTH_Y = 34.0

SPADL_TYPE_ID = {
    "PASS": 0,
    "CROSS": 1,
    "THROW IN": 2,
    "PLAYER SUCCESSFUL TACKLE": 9,
    "SHOT": 11,
    "DRIVE": 21,
}

COLUMNS = [
    "game_id",
    "original_event_id",
    "period_id",
    "time_seconds",
    "team_id",
    "team_name",
    "team_side",
    "player_id",
    "jersey_number",
    "player_name",
    "start_x",
    "start_y",
    "end_x",
    "end_y",
    "action_id",
    "type_id",
    "type_name",
    "result_id",
    "result_name",
    "bodypart_id",
    "bodypart_name",
    "tdeed_frame",
    "end_frame",
    "tdeed_confidence",
    "player_distance_m",
    "ball_observed_start",
    "ball_observed_end",
    "on_pitch",
    "review_status",
    "operator_note",
    "event_source",
]


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def finite_pair(value):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    x, y = value
    if x is None or y is None:
        return None
    x, y = float(x), float(y)
    if math.isnan(x) or math.isnan(y):
        return None
    return x, y


def on_pitch(point):
    if point is None:
        return False
    x, y = point
    return 0.0 <= x <= FIELD_LENGTH and 0.0 <= y <= FIELD_WIDTH


def ball_point(frame):
    for item in frame.get("Coordinates") or []:
        if item.get("ID") == "Ball":
            return finite_pair(item.get("Coordinates"))
    return None


def people(frame):
    found = []
    for item in frame.get("Coordinates") or []:
        if item.get("Type") not in ("Player", "Goalkeeper"):
            continue
        point = finite_pair(item.get("Coordinates"))
        if point is None:
            continue
        found.append({"id": int(item["ID"]), "type": item["Type"], "point": point})
    return found


def observed_ball_frames(raw):
    frames = set()
    for key, frame in raw.items():
        balls = (frame.get("Coordinates") or {}).get("Ball") or {}
        if isinstance(balls, dict) and balls:
            frames.add(int(key))
    return frames


def median(values):
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def side_by_goalkeeper(processed, team_mapping, mirror):
    """Map each Eagle color group to left or right from where its goalkeeper stands.

    Left means the goal at x = 0. A keeper standing past the halfway line belongs
    to the right goal even if no other keeper is visible.
    """
    tracks = {}
    for frame in processed:
        for person in people(frame):
            if person["type"] != "Goalkeeper":
                continue
            point = to_image_left_origin(person["point"], mirror)
            tracks.setdefault(person["id"], []).append(point)

    sides = {}
    for track_id, points in tracks.items():
        eagle_team = team_mapping.get(track_id)
        if eagle_team is None:
            continue
        x = median(p[0] for p in points)
        y = median(p[1] for p in points)
        # Prefer the keeper actually in a goal mouth over one standing wide of it.
        score = abs(y - GOAL_MOUTH_Y)
        side = "left" if x <= FIELD_LENGTH / 2 else "right"
        current = sides.get(eagle_team)
        if current is None or score < current[0]:
            sides[eagle_team] = (score, side)
    return {team: side for team, (_score, side) in sides.items()}


def nearest_person(frame, ball):
    if ball is None:
        return None, None
    chosen = None
    distance = None
    for person in people(frame):
        dist = math.hypot(person["point"][0] - ball[0], person["point"][1] - ball[1])
        if distance is None or dist < distance:
            chosen = person
            distance = dist
    return chosen, distance


def build(video_stem, tdeed_path, eagle_dir, output_path, period_id, fps, frame_width=None):
    eagle_dir = Path(eagle_dir)
    processed = load_json(eagle_dir / "processed_data.json")
    raw = load_json(eagle_dir / "raw_coordinates.json")
    metadata = load_json(eagle_dir / "metadata.json")
    events = sorted(load_json(tdeed_path)["predictions"], key=lambda event: int(event["frame"]))

    fps = float(fps or metadata["fps"])
    team_mapping = {int(track_id): int(team) for track_id, team in metadata["team_mapping"].items()}
    capture_width = frame_width
    if not capture_width:
        capture_width = 1
        for frame in raw.values():
            for point in (frame.get("Keypoints") or {}).values():
                if isinstance(point, (list, tuple)) and point:
                    capture_width = max(capture_width, float(point[0]))
    mirror = image_left_is_eagle_right(raw, capture_width)
    if mirror is None:
        mirror = False
        origin = "unknown_kept_eagle_axes"
    else:
        origin = "image_left_goal_is_x0"
    sides = side_by_goalkeeper(processed, team_mapping, mirror)
    if len(sides) == 1:
        known_team, known_side = next(iter(sides.items()))
        other_side = "right" if known_side == "left" else "left"
        for eagle_team in set(team_mapping.values()):
            sides.setdefault(eagle_team, other_side if eagle_team != known_team else known_side)
    seen_ball = observed_ball_frames(raw)

    rows = []
    for index, event in enumerate(events):
        start_frame = int(event["frame"])
        end_frame = int(events[index + 1]["frame"]) if index + 1 < len(events) else None
        if start_frame < 0 or start_frame >= len(processed):
            raise ValueError(f"T-DEED frame {start_frame} is outside Eagle's {len(processed)} frames")

        start_eagle = ball_point(processed[start_frame])
        end_eagle = ball_point(processed[end_frame]) if end_frame is not None and 0 <= end_frame < len(processed) else None
        actor, distance = nearest_person(processed[start_frame], start_eagle)
        eagle_team = team_mapping.get(actor["id"]) if actor else None
        team_id = eagle_team
        team_name = None if eagle_team is None else f"team_{eagle_team}"
        team_side = sides.get(eagle_team)

        start = to_image_left_origin(start_eagle, mirror)
        end = to_image_left_origin(end_eagle, mirror)
        label = str(event["label"])
        rows.append(
            {
                "game_id": video_stem,
                "original_event_id": index,
                "period_id": period_id,
                "time_seconds": start_frame / fps,
                "team_id": team_id,
                "team_name": team_name,
                "team_side": team_side,
                "player_id": actor["id"] if actor else None,
                "jersey_number": None,
                "player_name": None,
                "start_x": None if start is None else round(start[0], 2),
                "start_y": None if start is None else round(start[1], 2),
                "end_x": None if end is None else round(end[0], 2),
                "end_y": None if end is None else round(end[1], 2),
                "action_id": index,
                "type_id": SPADL_TYPE_ID.get(label),
                "type_name": label,
                "result_id": None,
                "result_name": None,
                "bodypart_id": None,
                "bodypart_name": None,
                "tdeed_frame": start_frame,
                "end_frame": end_frame,
                "tdeed_confidence": float(event["confidence"]),
                "player_distance_m": None if distance is None else round(distance, 2),
                "ball_observed_start": start_frame in seen_ball,
                "ball_observed_end": end_frame in seen_ball if end_frame is not None else None,
                "on_pitch": on_pitch(start) and (end is None or on_pitch(end)),
                "review_status": "pending",
                "operator_note": None,
                "event_source": "model",
            }
        )

    frame = pd.DataFrame(rows, columns=COLUMNS)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(output_path, sheet_name="actions", index=False)
    notes = {
        "origin": origin,
        "mirrored": bool(mirror),
        "eagle_team_side": {str(team): side for team, side in sides.items()},
        "frame_width_used": capture_width,
        "team_name_meaning": "team_0 and team_1 are Eagle's two shirt-color groups. team_side is left or right only when a goalkeeper shows which goal that group defends.",
        "player_id_meaning": "Eagle track id of the person closest to the ball. Shirt number is empty.",
        "fps": fps,
        "frames": len(processed),
    }
    output_path.with_suffix(".notes.json").write_text(json.dumps(notes, indent=2), encoding="utf-8")
    return output_path, frame
