import time
import usb.core
import usb.util

class cp210x:
    # Config request types
    REQTYPE_HOST_TO_INTERFACE = 0x41
    REQTYPE_DEVICE_TO_HOST = 0xc0
    
    # CP210X_VENDOR_SPECIFIC values
    CP210X_VENDOR_SPECIFIC = 0xFF
    CP210X_READ_LATCH = 0x00C2
    CP210X_WRITE_LATCH = 0x37E1
    PID = 0xea60
    VID = 0x10c4
    N_GPIO = 0

    def __init__(self, invert = False):
        self.dev = usb.core.find(
            idVendor=self.__class__.VID,
            idProduct=self.__class__.PID)
        self.invert = invert
        assert self.dev, "No device found, aborting..."

    def _get(self) -> list:
        ret = self.dev.ctrl_transfer(
            self.__class__.REQTYPE_DEVICE_TO_HOST,
            self.__class__.CP210X_VENDOR_SPECIFIC,
            self.__class__.CP210X_READ_LATCH,
            0,
            1)

        values = []
        for i in range(self.__class__.N_GPIO):
            if self.invert:
                values.append( False if ( ret[0] & (1<<i) ) else True)
            else:
                values.append( True if ( ret[0] & (1<<i) ) else False)
        return values

    def write(self, values: list):
        assert len(values) == self.__class__.N_GPIO
        val = 0x00
        for i in range(self.__class__.N_GPIO):
            if self.invert:
                enable = 0 if values[i] else 1
            else:
                enable = 1 if values[i] else 0
            val = val + (enable << i)
        val = (val << 8) | 0xFF
        self.dev.ctrl_transfer(
            self.__class__.REQTYPE_HOST_TO_INTERFACE,
            self.__class__.CP210X_VENDOR_SPECIFIC,
            self.__class__.CP210X_WRITE_LATCH,
            val,
            [])

    def set(self, pin: int, value: bool):
        assert pin in range(self.__class__.N_GPIO), "Pin index out of range"
        pins = self._get()
        pins[pin] = value
        self.write(pins)

class cp2104(cp210x):
    N_GPIO = 4

import time

if __name__ == "__main__":
    a = cp2104()
    while True:
        a.write([1,0,0,0])
        time.sleep(0.5)
        a.write([0,1,0,0])
        time.sleep(0.5)
        a.write([0,0,1,0])
        time.sleep(0.5)
        a.write([0,0,0,1])
        time.sleep(0.5)
