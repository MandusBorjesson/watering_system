#!/usr/bin/env python3
import time
import asyncio
from threading import Thread
import queue
import datetime

from nicegui import Client, app, core, run, ui

from .cp210x import cp2104

water_systems = ["Chili/Tomatoes", "Tomato (large)", "Cucumber (large)"]

import sys

logfile_path = sys.argv[1]

def run_water():
    global water_queue, water_systems, system_selector, time_selector
    water_queue.put((water_systems.index(system_selector.value), time_selector.value))

    now = datetime.datetime.now()
    t = now.strftime('%Y-%m-%dT%H:%M:%S')
    with open(logfile_path, "a") as log:
        log.write(f"{t}, {system_selector.value}, {time_selector.value}\n")

dark = ui.dark_mode()
ui.switch('Dark mode').bind_value(dark)

with ui.row():
    system_selector = ui.select(water_systems)
    time_selector = ui.number(
                          value=1,
                          precision=1,
                          min=1,
                          suffix="s",
                       )
    ui.button("Water plants", on_click=run_water)

def water_worker(work_queue, fault_queue):
    pump_index = 3
    while True:
        index, watering_time = work_queue.get()
        try:
            relays = cp2104(invert=True)
            relays.set(index, 1)
            relays.set(pump_index, 1)
            time.sleep(watering_time)

            relays.set(pump_index, 0)
            time.sleep(0.5)
            relays.write([0,0,0,0])
        except Exception as e:
            fault_queue.put(f"Failed to water plants: {e}")

water_queue = queue.Queue(-1)
error_queue = queue.Queue(-1)
water_thread = Thread(target=water_worker, args=(water_queue, error_queue))
water_thread.start()

async def error_loop():
    while not app.is_stopped:
        if not error_queue.empty():
            ui.notify(error_queue.get(), type="warning")
        await asyncio.sleep(0.2)

app.on_startup(error_loop)

ui.run(title="Watering system", reload=False, show=False)

def run_ui():
    pass
