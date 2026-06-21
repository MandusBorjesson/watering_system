from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

PIPE_FILL_S = 2
RELAY_CHANNEL = 3
STEPPER_PINS = (19, 12, 13, 14)
TRACK_SIZE_MM = 1900


class StubStepper:
    def __init__(self) -> None:
        self._position_mm: float | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def home(self) -> None:
        self.move_relative(-TRACK_SIZE_MM)

    def move_relative(self, distance_mm: float) -> None:
        if self._position_mm is not None:
            new_position = self._position_mm + distance_mm
        else:
            new_position = 0.0 if distance_mm < 0 else None

        steps = int(abs(distance_mm) * 400 / 80)
        time.sleep(min(steps * 0.0008, 0.5))

        if distance_mm < 0:
            new_position = 0.0

        self._position_mm = new_position
        logger.info("StubStepper moved %.1f mm to position %s", distance_mm, self._position_mm)

    def move_absolute(self, target_mm: float) -> None:
        if self._position_mm is None:
            self.home()
        assert self._position_mm is not None
        self.move_relative(target_mm - self._position_mm)


class StubPump:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def run(self, duration: float) -> None:
        total = duration + PIPE_FILL_S
        logger.info("StubPump running for %.1f s (includes pipe fill)", total)
        time.sleep(total)


class Pump:
    def __init__(self, controller, channel: int):
        self._controller = controller
        self._channel = channel
        self._controller.set(self._channel, True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._controller.set(self._channel, True)
        return False

    def run(self, duration: float) -> None:
        self._controller.set(self._channel, False)
        time.sleep(duration + PIPE_FILL_S)
        self._controller.set(self._channel, True)


class Stepper:
    def __init__(self, step, enable, direction, home_sensor, size_mm: float):
        from gpiozero import Button, LED

        self.step = LED(step)
        self.enable = LED(enable)
        self.direction = LED(direction)
        self.home_sensor = Button(home_sensor, pull_up=True)
        self._step_duration = 0.0004
        self._size_mm = size_mm
        self._position_mm: float | None = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.enable.off()
        return False

    def home(self) -> None:
        self.move_relative(-self._size_mm)

    def move_relative(self, distance_mm: float) -> None:
        if self._position_mm is not None:
            new_position = self._position_mm + distance_mm
        else:
            new_position = None

        self._position_mm = None

        steps = int(distance_mm * 400 / 80)

        self.enable.on()
        if steps > 0:
            self.direction.on()
        else:
            self.direction.off()

        for _ in range(abs(steps)):
            if steps < 0 and self.home_sensor.is_pressed:
                new_position = 0.0
                break

            self.step.on()
            time.sleep(self._step_duration)
            self.step.off()
            time.sleep(self._step_duration)

        self.enable.off()
        self._position_mm = new_position

    def move_absolute(self, target_mm: float) -> None:
        if self._position_mm is None:
            self.home()
        assert self._position_mm is not None
        self.move_relative(target_mm - self._position_mm)


def create_hardware(stub: bool = False):
    if stub:
        return StubStepper(), StubPump()

    from .cp210x import cp2104

    step_pin, enable_pin, direction_pin, home_sensor = STEPPER_PINS
    relay_board = cp2104()
    stepper = Stepper(step_pin, enable_pin, direction_pin, home_sensor, TRACK_SIZE_MM)
    pump = Pump(relay_board, RELAY_CHANNEL)
    return stepper, pump
