import time
import argparse
from water_ui import cp210x
from gpiozero import LED

pins = {
    'm1_step': 19,
    'm1_enable': 12,
    'm1_direction': 13,
    'm2_step': 18,
    'm2_enable': 4,
    'm2_direction': 24,
        }

class Pump:
    def __init__(self, controller, channel):
        self._controller = controller
        self._channel = channel
        self._controller.set(self._channel, True)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._controller.set(self._channel, True)
        return False

    def run(self, duration):
        self._controller.set(self._channel, False)
        time.sleep(duration)
        self._controller.set(self._channel, True)

class Motor:
    def __init__(self, step, enable, direction):
        self.step = LED(step)
        self.enable = LED(enable)
        self.direction = LED(direction)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.enable.off()
        return False

    def move(self, distance_mm, step_duration = 0.0004):
        # 400 steps = 80mm
        steps = int(distance_mm * 400/80)

        self.enable.on()
        if steps > 0:
            self.direction.on()
        else:
            self.direction.off()
        
        for i in range(abs(steps)):
            self.step.on()
            time.sleep(step_duration)
            self.step.off()
            time.sleep(step_duration)

        self.enable.off()


if __name__ == "__main__":
    import argparse
    # Create the parser
    parser = argparse.ArgumentParser(description="Demo watering system")
    parser.add_argument("--move", type=int, help="Perform a move operation, in mm")
    parser.add_argument("--pump", type=int, help="Perform a pump operation, in seconds")
    args = parser.parse_args()

    # GPIO.setmode(GPIO.BCM)
    # GPIO.setwarnings(True)
    relay_board = cp210x.cp2104()
    relay_channel = 3

    with Motor(19, 12, 13) as stepper, Pump(relay_board, relay_channel) as pump:
        if args.move:
            stepper.move(int(args.move))
        if args.pump:
            pump.run(int(args.pump))
