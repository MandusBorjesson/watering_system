#!/usr/bin/env python3

from __future__ import annotations

import argparse
import atexit
import os
import queue
import signal
import sys
from dataclasses import dataclass
from datetime import date, datetime
from threading import Thread
from typing import Callable

from nicegui import app, ui

from .camera import STOP_CAPTURE, Webcam
from .config import Config, load_config, pot_label, pot_offset_mm
from .hardware import create_hardware
from .history import HistoryStore, WateringEvent


@dataclass(frozen=True)
class WaterJob:
    pot_id: str
    offset_mm: int
    duration_s: float
    source: str


@dataclass(frozen=True)
class StatusMessage:
    kind: str
    text: str
    pot_id: str = ""


class AppState:
    def __init__(
        self,
        config: Config,
        history: HistoryStore,
        work_queue: queue.Queue,
        status_queue: queue.Queue,
    ) -> None:
        self.config = config
        self.history = history
        self.work_queue = work_queue
        self.status_queue = status_queue
        self.watered_slots: set[tuple[str, date, int]] = set()
        self.selected_pot_id: str | None = config.pots[0].id if config.pots else None
        self.pending_pot_ids: set[str] = set()
        self.refresh_handlers: list[Callable[[], None]] = []

    def register_refresh(self, handler: Callable[[], None]) -> None:
        self.refresh_handlers.append(handler)

    def refresh(self) -> None:
        for handler in self.refresh_handlers:
            handler()

    def enqueue_job(self, pot_id: str, duration_s: float, source: str) -> None:
        pot = self.config.pot_by_id(pot_id)
        if pot is None:
            raise ValueError(f"Unknown pot id '{pot_id}'")

        self.pending_pot_ids.add(pot_id)
        self.work_queue.put(
            WaterJob(
                pot_id=pot_id,
                offset_mm=pot_offset_mm(pot),
                duration_s=duration_s,
                source=source,
            )
        )


def water_worker(
    work_queue: queue.Queue,
    status_queue: queue.Queue,
    history: HistoryStore,
    config: Config,
    stub: bool,
) -> None:
    stepper, pump = create_hardware(stub=stub)
    with stepper, pump:
        while True:
            job = work_queue.get()
            if job is STOP_CAPTURE:
                break
            try:
                stepper.move_absolute(job.offset_mm)
                pump.run(job.duration_s)
            except Exception as exc:
                pot = config.pot_by_id(job.pot_id)
                label = pot_label(pot) if pot else job.pot_id
                message = f"Failed to water {label}: {exc}"
                history.append_error(message, source=job.source, pot_id=job.pot_id)
                status_queue.put(
                    StatusMessage(kind="error", text=message, pot_id=job.pot_id)
                )
                continue

            history.append_watering(
                pot_id=job.pot_id,
                duration_s=job.duration_s,
                source=job.source,
            )
            pot = config.pot_by_id(job.pot_id)
            label = pot_label(pot) if pot else job.pot_id
            status_queue.put(
                StatusMessage(
                    kind="success",
                    text=f"Watered {label} ({job.source})",
                    pot_id=job.pot_id,
                )
            )


def format_water_hours(water_hours: list[int]) -> str:
    return ", ".join(f"{hour:02d}:00" for hour in water_hours)


def watering_row(event: WateringEvent, config: Config) -> dict:
    pot = config.pot_by_id(event.pot_id)
    return {
        "timestamp": event.timestamp,
        "pot": pot_label(pot) if pot else event.pot_id,
        "pot_id": event.pot_id,
        "duration_s": event.duration_s,
        "source": event.source,
    }


def build_ui(state: AppState, stub: bool, camera: Webcam | None = None) -> None:
    pot_options = {pot.id: pot_label(pot) for pot in state.config.pots}

    def last_watered_text(pot_id: str) -> str:
        event = state.history.last_watering_for_pot(pot_id)
        return event.timestamp if event else "Never"

    def watering_count(pot_id: str) -> int:
        return len(state.history.waterings_for_pot(pot_id))

    with ui.header().classes("items-center gap-4"):
        ui.label("Watering system").classes("text-h5")
        if stub:
            ui.badge("STUB", color="orange").props("outline")
        dark = ui.dark_mode()
        ui.switch("Dark mode").bind_value(dark)

    overview_container: ui.column | None = None
    detail_labels: dict[str, ui.label] = {}
    history_table = {"widget": None}
    history_filter = {"pot_id": None}
    duration_input: dict[str, ui.number] = {}
    water_button: dict[str, ui.button] = {}

    def set_selected_pot(pot_id: str) -> None:
        state.selected_pot_id = pot_id
        refresh_overview()
        refresh_detail()

    def refresh_overview() -> None:
        if overview_container is None:
            return
        overview_container.clear()
        with overview_container:
            for pot in state.config.pots:
                selected = pot.id == state.selected_pot_id
                card_classes = "cursor-pointer w-full p-2 relative"
                if selected:
                    card_classes += " ring-2 ring-primary"

                with ui.card().classes(card_classes).on(
                    "click", lambda pot_id=pot.id: set_selected_pot(pot_id)
                ):
                    ui.label(pot_label(pot)).classes("text-subtitle2 leading-tight")
                    ui.label(
                        f"{format_water_hours(pot.water_hours)} · "
                        f"Last: {last_watered_text(pot.id)}"
                    ).classes("text-caption text-grey leading-tight")
                    if pot.id in state.pending_pot_ids:
                        ui.spinner(size="sm").classes("absolute top-2 right-2")

    def refresh_detail() -> None:
        pot_id = state.selected_pot_id
        if pot_id is None:
            return

        pot = state.config.pot_by_id(pot_id)
        if pot is None:
            return

        detail_labels["plants"].set_text(pot_label(pot))
        detail_labels["offset"].set_text(f"Offset: {pot.offset_cm} cm")
        detail_labels["schedule"].set_text(f"Schedule: {format_water_hours(pot.water_hours)}")
        detail_labels["last"].set_text(f"Last watered: {last_watered_text(pot_id)}")
        detail_labels["count"].set_text(f"Total waterings: {watering_count(pot_id)}")

        pending = pot_id in state.pending_pot_ids
        water_button["widget"].set_enabled(not pending)
        water_button["widget"].set_text(
            "Watering..." if pending else "Water now"
        )

    def refresh_history() -> None:
        events = state.history.load_waterings()
        filter_id = history_filter["pot_id"]
        if filter_id:
            events = [event for event in events if event.pot_id == filter_id]

        rows = [watering_row(event, state.config) for event in events]
        if history_table["widget"] is not None:
            history_table["widget"].rows = rows

    def refresh_all() -> None:
        refresh_overview()
        refresh_detail()
        refresh_history()

    def start_watering() -> None:
        pot_id = state.selected_pot_id
        if pot_id is None:
            ui.notify("Select a pot first", type="warning")
            return
        if pot_id in state.pending_pot_ids:
            return

        duration_s = float(duration_input["widget"].value)
        if duration_s <= 0:
            ui.notify("Duration must be greater than zero", type="warning")
            return

        state.enqueue_job(pot_id, duration_s, source="manual")
        refresh_detail()

    filter_options = {"": "All pots", **pot_options}

    with ui.column().classes("w-full items-stretch q-pa-md"):
        with ui.column().classes("w-full max-w-7xl mx-auto q-gutter-y-md"):
            if camera is not None:
                with ui.card().classes("w-full overflow-hidden"):
                    if camera.error:
                        ui.label(camera.error).classes("text-caption text-grey q-pa-md")
                    else:
                        ui.image(camera.stream_path).props("fit=contain").classes(
                            "w-full"
                        ).style("max-height: 32rem")

            with ui.element("div").style(
                "display: grid; grid-template-columns: minmax(220px, 1fr) minmax(0, 2fr); "
                "gap: 1rem; width: 100%; align-items: start;"
            ):
                with ui.column().classes("w-full q-gutter-y-xs"):
                    ui.label("Pots").classes("text-h6")
                    overview_container = ui.column().classes("w-full q-gutter-y-xs")

                with ui.column().classes("w-full q-gutter-y-md"):
                    with ui.column().classes("w-full q-gutter-y-sm"):
                        ui.label("Pot detail").classes("text-h6")
                        detail_labels["plants"] = ui.label().classes("text-subtitle1")
                        detail_labels["offset"] = ui.label()
                        detail_labels["schedule"] = ui.label()
                        detail_labels["last"] = ui.label()
                        detail_labels["count"] = ui.label()

                        with ui.row().classes("items-end q-gutter-sm"):
                            duration_input["widget"] = ui.number(
                                value=state.config.default_duration_s,
                                precision=1,
                                min=0.1,
                                step=0.5,
                                suffix="s",
                                label="Duration",
                            ).classes("w-40")
                            water_button["widget"] = ui.button(
                                "Water now", on_click=start_watering
                            )

                    with ui.column().classes("w-full q-gutter-y-sm"):
                        ui.label("Watering history").classes("text-h6")
                        ui.select(
                            filter_options,
                            value="",
                            label="Filter by pot",
                            on_change=lambda event: (
                                history_filter.update({"pot_id": event.value or None}),
                                refresh_history(),
                            ),
                        ).classes("w-64")

                        history_table["widget"] = ui.table(
                            columns=[
                                {
                                    "name": "timestamp",
                                    "label": "Time",
                                    "field": "timestamp",
                                    "align": "left",
                                },
                                {
                                    "name": "pot",
                                    "label": "Pot",
                                    "field": "pot",
                                    "align": "left",
                                },
                                {
                                    "name": "duration_s",
                                    "label": "Duration (s)",
                                    "field": "duration_s",
                                    "align": "right",
                                },
                                {
                                    "name": "source",
                                    "label": "Source",
                                    "field": "source",
                                    "align": "left",
                                },
                            ],
                            rows=[],
                            row_key="timestamp",
                        ).classes("w-full")

    state.register_refresh(refresh_all)
    refresh_all()

    def poll_status_queue() -> None:
        while True:
            try:
                message = state.status_queue.get_nowait()
            except queue.Empty:
                break

            if message.pot_id:
                state.pending_pot_ids.discard(message.pot_id)

            notify_type = "positive" if message.kind == "success" else "warning"
            ui.notify(message.text, type=notify_type)
            state.refresh()

    scheduler_state = {"last_checked_minute": None}

    def run_scheduler() -> None:
        now = datetime.now()
        minute_key = (now.date(), now.hour, now.minute)
        last_checked_minute = scheduler_state["last_checked_minute"]

        if now.minute == 0:
            scheduled_any = False
            for pot in state.config.pots:
                if now.hour not in pot.water_hours:
                    continue

                slot = (pot.id, now.date(), now.hour)
                if slot in state.watered_slots:
                    continue

                duration_s = state.config.duration_for_pot(pot)
                state.enqueue_job(pot.id, duration_s, source="scheduled")
                state.watered_slots.add(slot)
                scheduled_any = True

            if scheduled_any:
                state.refresh()

        if last_checked_minute and now.date() > last_checked_minute[0]:
            state.watered_slots = {
                slot for slot in state.watered_slots if slot[1] == now.date()
            }

        scheduler_state["last_checked_minute"] = minute_key

    ui.timer(0.2, poll_status_queue)
    ui.timer(30, run_scheduler)


def main(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    history = HistoryStore(args.history, args.errors)
    work_queue: queue.Queue = queue.Queue()
    status_queue: queue.Queue = queue.Queue()
    state = AppState(config, history, work_queue, status_queue)

    camera: Webcam | None = None
    if not args.no_camera:
        camera = Webcam(args.camera)
        camera.start()
        if camera.error is None:
            camera.register_stream(app)

    worker = Thread(
        target=water_worker,
        args=(work_queue, status_queue, history, config, args.stub),
        daemon=True,
    )
    worker.start()

    build_ui(state, stub=args.stub, camera=camera)

    shutdown_done = False

    def shutdown_services() -> None:
        nonlocal shutdown_done
        if shutdown_done:
            return
        shutdown_done = True

        if camera is not None:
            camera.stop()

        try:
            work_queue.put_nowait(STOP_CAPTURE)
        except queue.Full:
            pass

        worker.join(timeout=2)

    app.on_shutdown(shutdown_services)
    atexit.register(shutdown_services)

    @app.on_startup
    async def install_shutdown_hook() -> None:
        def wrap_handler(previous_handler):  # type: ignore[no-untyped-def]
            def handler(signum, frame):  # type: ignore[no-untyped-def]
                shutdown_services()
                if callable(previous_handler):
                    previous_handler(signum, frame)
                elif previous_handler == signal.SIG_DFL:
                    raise KeyboardInterrupt

            return handler

        signal.signal(signal.SIGINT, wrap_handler(signal.getsignal(signal.SIGINT)))
        signal.signal(signal.SIGTERM, wrap_handler(signal.getsignal(signal.SIGTERM)))

    try:
        ui.run(
            title="Watering system",
            host=args.host,
            port=args.port,
            reload=False,
            show=False,
            uvicorn_logging_level="warning",
            timeout_graceful_shutdown=0,
        )
    except KeyboardInterrupt:
        shutdown_services()
        os._exit(0)


def run_ui() -> None:
    parser = argparse.ArgumentParser(description="Plant watering system UI")
    parser.add_argument("config", help="Path to config.json")
    parser.add_argument("history", help="Path to watering history CSV")
    parser.add_argument("errors", help="Path to error log CSV")
    parser.add_argument(
        "--stub",
        action="store_true",
        help="Use hardware stubs instead of GPIO/USB (for dev machines)",
    )
    parser.add_argument(
        "--camera",
        default="0",
        help="Webcam device index or path (default: 0)",
    )
    parser.add_argument(
        "--no-camera",
        action="store_true",
        help="Disable the live webcam view",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Web server host")
    parser.add_argument("--port", type=int, default=8080, help="Web server port")
    args = parser.parse_args()
    try:
        main(args)
    except KeyboardInterrupt:
        sys.exit(0)
