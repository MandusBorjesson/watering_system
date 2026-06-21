from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from typing import Any

logger = logging.getLogger(__name__)

MJPEG_BOUNDARY = b"frame"
STREAM_INTERVAL_S = 1 / 15


class _StopCapture:
    pass


STOP_CAPTURE = _StopCapture()


class Webcam:
    def __init__(self, device: str | int) -> None:
        self._device = int(device) if isinstance(device, str) and device.isdigit() else device
        self._lock = threading.Lock()
        self._latest_jpeg: bytes | None = None
        self._error: str | None = None
        self._running = False
        self._capture: Any = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def error(self) -> str | None:
        return self._error

    @property
    def stream_path(self) -> str:
        return "/webcam/stream"

    def start(self) -> None:
        try:
            import cv2
        except ImportError:
            self._error = "Install opencv-python-headless to use the webcam"
            logger.warning(self._error)
            return

        self._capture = cv2.VideoCapture(self._device)
        if not self._capture.isOpened():
            self._error = f"Could not open camera {self._device!r}"
            self._capture.release()
            self._capture = None
            logger.warning(self._error)
            return

        self._running = True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._capture_loop, name="webcam", daemon=True)
        self._thread.start()
        logger.info("Webcam opened on %r", self._device)

    def _capture_loop(self) -> None:
        import cv2

        while self._running and self._capture is not None:
            ok, frame = self._capture.read()
            if not ok:
                continue

            ok, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not ok:
                continue

            with self._lock:
                self._latest_jpeg = jpeg.tobytes()

    def latest_jpeg(self) -> bytes | None:
        with self._lock:
            return self._latest_jpeg

    def _frame_bytes(self, jpeg: bytes) -> bytes:
        return (
            b"--" + MJPEG_BOUNDARY + b"\r\n"
            b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
        )

    def _wait_interruptible(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while self._running and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if self._stop_event.wait(min(0.05, max(remaining, 0))):
                return True
        return self._stop_event.is_set() or not self._running

    def mjpeg_frames(self) -> Iterator[bytes]:
        try:
            while self._running:
                jpeg = self.latest_jpeg()
                if jpeg is not None:
                    yield self._frame_bytes(jpeg)

                if self._wait_interruptible(STREAM_INTERVAL_S):
                    break
        except GeneratorExit:
            return

    def register_stream(self, nicegui_app: Any) -> None:
        from starlette.responses import StreamingResponse

        camera = self

        @nicegui_app.get(self.stream_path)
        def _webcam_stream() -> StreamingResponse:
            return StreamingResponse(
                camera.mjpeg_frames(),
                media_type=f"multipart/x-mixed-replace; boundary={MJPEG_BOUNDARY.decode()}",
            )

    def stop(self) -> None:
        if not self._running and self._capture is None:
            return

        self._running = False
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None
        if self._capture is not None:
            self._capture.release()
            self._capture = None
        logger.info("Webcam stopped")
