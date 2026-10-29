"""UTF-8 JSON-lines leaderboard storage, independent of plotting and game state."""

from datetime import datetime
import json
from pathlib import Path
import sys

from . import game_data as data


def valid_record(record):
    if not isinstance(record, dict):
        return False
    if type(record.get("score")) is not int or record["score"] < data.MIN_SCORE:
        return False
    if not isinstance(record.get("gravity_mode"), str) or record["gravity_mode"] not in data.GRAVITY_MODES:
        return False
    direction, level = record.get("wind_direction"), record.get("wind_level")
    if type(direction) is not int or type(level) is not int or (direction, level) not in data.WIND_OPTIONS:
        return False
    try:
        timestamp = datetime.fromisoformat(record["played_at"])
        return timestamp.utcoffset() is not None
    except (KeyError, TypeError, ValueError):
        return False


class ScoreStore:
    def __init__(self, path=None):
        if path is not None:
            self.path = Path(path)
        else:
            # Frozen __file__ points inside the bundle (temporary for onefile).
            # Portable builds keep writable, persistent scores beside the EXE.
            # Source launches keep them beside main.py, outside the package.
            folder = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
                      else Path(__file__).resolve().parents[1])
            self.path = folder / "scores.txt"

    def load(self):
        records, skipped = [], 0
        try:
            with self.path.open("r", encoding="utf-8", errors="replace") as source:
                for line in source:
                    if not line.strip():
                        continue
                    try:
                        record = json.loads(line)
                    except (ValueError, TypeError):
                        skipped += 1
                        continue
                    if valid_record(record):
                        records.append(record)
                    else:
                        skipped += 1
        except FileNotFoundError:
            return [], ""
        except (OSError, UnicodeError) as error:
            return records, f"Could not read scores: {error}"
        return records, f"Skipped {skipped} invalid score record(s)." if skipped else ""

    def save(self, record):
        if not valid_record(record):
            return False, "Score record was invalid; the result has not been saved."
        try:
            payload = (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
            # Preserve a new record even if an older damaged line lacks a newline.
            with self.path.open("a+b") as destination:
                if destination.tell():
                    destination.seek(-1, 2)
                    if destination.read(1) != b"\n":
                        destination.write(b"\n")
                destination.write(payload)
        except (OSError, UnicodeError) as error:
            return False, f"Could not save score: {error}"
        return True, "Timed score saved."

    def leaderboard(self, gravity_mode, limit=data.LEADERBOARD_LIMIT):
        records, warning = self.load()
        records = [record for record in records if record["gravity_mode"] == gravity_mode]
        records.sort(key=lambda record: (-record["score"],
                                        datetime.fromisoformat(record["played_at"]).timestamp()))
        return records[:limit], warning
