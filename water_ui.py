#!/usr/bin/env python3
import base64
import signal
import time
import asyncio
from threading import Thread
import queue
import datetime

import cv2
import numpy as np
from fastapi import Response

from nicegui import Client, app, core, run, ui

from BirdsNest.cp210x import cp2104

# In case you don't have a webcam, this will provide a black placeholder image.
black_1px = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAAXNSR0IArs4c6QAAAA1JREFUGFdjYGBg+A8AAQQBAHAgZQsAAAAASUVORK5CYII='
placeholder = Response(content=base64.b64decode(black_1px.encode('ascii')), media_type='image/png')
webcam = None

def get_webcams():
    # checks the first 10 indexes.
    arr = []
    for i in range(10):
        cap = cv2.VideoCapture(i)
        if cap.read()[0]:
            arr.append(i)
            cap.release()
    return arr

def convert(frame: np.ndarray) -> bytes:
    """Converts a frame from OpenCV to a JPEG image.

    This is a free function (not in a class or inner-function),
    to allow run.cpu_bound to pickle it and send it to a separate process.
    """
    _, imencode_image = cv2.imencode('.jpg', frame)
    return imencode_image.tobytes()


def setup() -> None:
    # OpenCV is used to access the webcam.

    @app.get('/video/frame')
    # Thanks to FastAPI's `app.get` it is easy to create a web route which always provides the latest image from OpenCV.
    async def grab_video_frame() -> Response:
        global webcam
        if webcam is None or not webcam.isOpened():
            return placeholder
        # The `webcam.read` call is a blocking function.
        # So we run it in a separate thread (default executor) to avoid blocking the event loop.
        _, frame = await run.io_bound(webcam.read)
        if frame is None:
            return placeholder
        # `convert` is a CPU-intensive function, so we run it in a separate process to avoid blocking the event loop and GIL.
        jpeg = await run.cpu_bound(convert, frame)
        return Response(content=jpeg, media_type='image/jpeg')

    # For non-flickering image updates and automatic bandwidth adaptation an interactive image is much better than `ui.image()`.
    video_image = ui.interactive_image().classes('w-full h-full')
    # A timer constantly updates the source of the image.
    # Because data from same paths is cached by the browser,
    # we must force an update by adding the current timestamp to the source.
    ui.timer(interval=0.1, callback=lambda: video_image.set_source(f'/video/frame?{time.time()}'))

    async def disconnect() -> None:
        """Disconnect all clients from current running server."""
        for client_id in Client.instances:
            await core.sio.disconnect(client_id)

    def handle_sigint(signum, frame) -> None:
        # `disconnect` is async, so it must be called from the event loop; we use `ui.timer` to do so.
        # ui.timer(0.1, disconnect, once=True)
        # Delay the default handler to allow the disconnect to complete.
        # ui.timer(1, lambda: signal.default_int_handler(signum, frame), once=True)
        pass

    async def cleanup() -> None:
        global webcam
        # This prevents ugly stack traces when auto-reloading on code change,
        # because otherwise disconnected clients try to reconnect to the newly started server.
        await disconnect()
        # Release the webcam hardware so it can be used by other applications again.
        if webcam is not None:
            webcam.release()

    app.on_shutdown(cleanup)
    # We also need to disconnect clients when the app is stopped with Ctrl+C,
    # because otherwise they will keep requesting images which lead to unfinished subprocesses blocking the shutdown.
    signal.signal(signal.SIGINT, handle_sigint)

water_systems = ["Chili/Tomatoes", "Tomato (large)", "Cucumber (large)"]

def run_water():
    global water_queue, water_systems, system_selector, time_selector
    water_queue.put((water_systems.index(system_selector.value), time_selector.value))

    now = datetime.datetime.now()
    t = now.strftime('%Y-%m-%dT%H:%M:%S')
    with open("water_log.csv", "a") as log:
        log.write(f"{t}, {system_selector.value}, {time_selector.value}\n")

def update_webcam(data):
    global webcam
    webcam = cv2.VideoCapture(data.value)

def probe_webcams():
    webcam_selector.set_options(get_webcams())

dark = ui.dark_mode()
ui.switch('Dark mode').bind_value(dark)

with ui.expansion("Webcam selection"):
    with ui.row():
        webcam_selector = ui.select(get_webcams(), on_change=update_webcam)
        ui.button(icon="refresh", on_click=probe_webcams)

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

# All the setup is only done when the server starts. This avoids the webcam being accessed
# by the auto-reload main process (see https://github.com/zauberzeug/nicegui/discussions/2321).
app.on_startup(setup)
app.on_startup(error_loop)

ui.run(title="Watering system")
