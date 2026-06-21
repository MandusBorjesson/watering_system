from __future__ import annotations

import csv
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


WATERING_FIELDS = ("timestamp", "pot_id", "duration_s", "source")
ERROR_FIELDS = ("timestamp", "pot_id", "source", "message")


@dataclass(frozen=True)
class WateringEvent:
    timestamp: str
    pot_id: str
    duration_s: float
    source: str


@dataclass(frozen=True)
class ErrorEvent:
    timestamp: str
    pot_id: str
    source: str
    message: str


class HistoryStore:
    def __init__(self, watering_path: str | Path, error_path: str | Path):
        self.watering_path = Path(watering_path)
        self.error_path = Path(error_path)
        self._lock = threading.Lock()
        self._ensure_file(self.watering_path, WATERING_FIELDS)
        self._ensure_file(self.error_path, ERROR_FIELDS)

    @staticmethod
    def _ensure_file(path: Path, fieldnames: tuple[str, ...]) -> None:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, fieldnames=fieldnames).writeheader()

    @staticmethod
    def _timestamp() -> str:
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    def append_watering(
        self,
        pot_id: str,
        duration_s: float,
        source: str,
        timestamp: str | None = None,
    ) -> WateringEvent:
        event = WateringEvent(
            timestamp=timestamp or self._timestamp(),
            pot_id=pot_id,
            duration_s=float(duration_s),
            source=source,
        )
        with self._lock:
            with open(self.watering_path, "a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=WATERING_FIELDS)
                writer.writerow(
                    {
                        "timestamp": event.timestamp,
                        "pot_id": event.pot_id,
                        "duration_s": event.duration_s,
                        "source": event.source,
                    }
                )
        return event

    def append_error(
        self,
        message: str,
        source: str,
        pot_id: str = "",
        timestamp: str | None = None,
    ) -> ErrorEvent:
        event = ErrorEvent(
            timestamp=timestamp or self._timestamp(),
            pot_id=pot_id,
            source=source,
            message=message,
        )
        with self._lock:
            with open(self.error_path, "a", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=ERROR_FIELDS)
                writer.writerow(
                    {
                        "timestamp": event.timestamp,
                        "pot_id": event.pot_id,
                        "source": event.source,
                        "message": event.message,
                    }
                )
        return event

    def load_waterings(self) -> list[WateringEvent]:
        with self._lock:
            if not self.watering_path.exists():
                return []
            with open(self.watering_path, "r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

        events = [
            WateringEvent(
                timestamp=row["timestamp"],
                pot_id=row["pot_id"],
                duration_s=float(row["duration_s"]),
                source=row["source"],
            )
            for row in rows
            if row.get("timestamp")
        ]
        events.sort(key=lambda event: event.timestamp, reverse=True)
        return events

    def last_watering_for_pot(self, pot_id: str) -> WateringEvent | None:
        for event in self.load_waterings():
            if event.pot_id == pot_id:
                return event
        return None

    def waterings_for_pot(self, pot_id: str) -> list[WateringEvent]:
        return [event for event in self.load_waterings() if event.pot_id == pot_id]
