import bluetooth
import time
import sys
import select
from machine import Pin, PWM
from micropython import const

# BLE IRQ event constants
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

# Nordic UART Service (NUS) UUIDs
_NUS_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_NUS_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_NOTIFY,)
_NUS_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), bluetooth.FLAG_WRITE,)
_NUS_SERVICE = (_NUS_UUID, (_NUS_TX, _NUS_RX),)

# BLE advertising payload types
_ADV_TYPE_FLAGS = const(0x01)
_ADV_TYPE_NAME = const(0x09)


class Motor:
    def __init__(self, in1_pin, in2_pin, pwm_pin):
        self.in1 = Pin(in1_pin, Pin.OUT, value=0)
        self.in2 = Pin(in2_pin, Pin.OUT, value=0)
        self.pwm = PWM(Pin(pwm_pin))
        self.pwm.freq(10000)  # 10kHz, same as C firmware
        self.pwm.duty_u16(0)

    def forward(self):
        self.in1.value(1)
        self.in2.value(0)

    def backward(self):
        self.in1.value(0)
        self.in2.value(1)

    def idle(self):
        self.in1.value(0)
        self.in2.value(0)

    def set_speed(self, duty):
        self.pwm.duty_u16(int(duty * 65535))


# Motor Configuration constants (from motor_config.h)
# These constants mirror the values defined in the C firmware's motor_config.h.
Motor_Front_Left_IN1  = 20
Motor_Front_Left_IN2  = 21
Motor_Front_Left_PWM  = 22

Motor_Front_Right_IN1 = 26
Motor_Front_Right_IN2 = 27
Motor_Front_Right_PWM = 28

Motor_Rear_Left_IN1   = 3
Motor_Rear_Left_IN2   = 4
Motor_Rear_Left_PWM   = 2

Motor_Rear_Right_IN1  = 6
Motor_Rear_Right_IN2  = 7
Motor_Rear_Right_PWM  = 5

# Motor pin mapping (matches motor_config.h)
m_front_left  = Motor(Motor_Front_Left_IN1,  Motor_Front_Left_IN2,  Motor_Front_Left_PWM)
m_front_right = Motor(Motor_Front_Right_IN1, Motor_Front_Right_IN2, Motor_Front_Right_PWM)
m_rear_left   = Motor(Motor_Rear_Left_IN1,   Motor_Rear_Left_IN2,   Motor_Rear_Left_PWM)
m_rear_right  = Motor(Motor_Rear_Right_IN1,  Motor_Rear_Right_IN2,  Motor_Rear_Right_PWM)
motors = [m_front_left, m_front_right, m_rear_left, m_rear_right]


def handle_command(cmd: str):
    """
    Handle a single-character motor command.

    Valid commands (case-insensitive):
    - 'z': move forward
    - 's': move backward
    - 'q': turn left
    - 'd': turn right
    - 'a': idle/stop

    Any whitespace (e.g. newlines, carriage returns, spaces, tabs) is ignored.
    Unrecognized commands are ignored and do not stop the robot. This prevents
    unintended "Idle" states from being triggered by line endings or noise on
    the serial/BLE connection.
    Returns a descriptive string when a command is executed, or None when
    the character is ignored.
    """
    if not cmd:
        return None

    # Ignore whitespace and control characters (common on serial/BLE)
    if cmd in ('\r', '\n', ' ', '\t'):
        return None

    c = cmd.lower()

    if c == 'z':
        # Forward: all motors forward at full speed
        for m in motors:
            m.forward()
            m.set_speed(1.0)
        return "Forward"

    elif c == 's':
        # Backward: all motors backward at full speed
        for m in motors:
            m.backward()
            m.set_speed(1.0)
        return "Backward"

    elif c == 'q':
        # Turn left: left motors backward, right motors forward
        m_front_right.forward()
        m_rear_right.forward()
        m_front_left.backward()
        m_rear_left.backward()
        for m in motors:
            m.set_speed(1.0)
        return "Turn Left"

    elif c == 'd':
        # Turn right: left motors forward, right motors backward
        m_front_left.forward()
        m_rear_left.forward()
        m_front_right.backward()
        m_rear_right.backward()
        for m in motors:
            m.set_speed(1.0)
        return "Turn Right"

    elif c == 'a':
        # Idle/stop: set all motors to idle and zero speed
        for m in motors:
            m.idle()
            m.set_speed(0)
        return "Idle"

    # Unknown command: do nothing
    return None


def build_advertising_payload(name):
    """Build BLE advertising payload with flags, name, and service UUID."""
    payload = bytearray()
    # Flags: LE General Discoverable + BR/EDR Not Supported
    payload += bytearray([2, _ADV_TYPE_FLAGS, 0x06])
    # Complete Local Name
    name_bytes = name.encode()
    payload += bytearray([len(name_bytes) + 1, _ADV_TYPE_NAME]) + name_bytes
    return payload


class BLEUART:
    def __init__(self, name="AIRA Motor"):
        self._ble = bluetooth.BLE()
        self._ble.active(True)
        self._tx_handle = None
        self._rx_handle = None
        self._conn_handle = None
        self._name = name
        
        # Register services with retry
        for attempt in range(3):
            try:
                ((self._tx_handle, self._rx_handle),) = self._ble.gatts_register_services((_NUS_SERVICE,))
                print("BLE services registered")
                break
            except Exception as e:
                print(f"Service registration failed (attempt {attempt + 1}):", e)
                if attempt < 2:
                    time.sleep_ms(200)
        
        if self._tx_handle is None or self._rx_handle is None:
            raise Exception("Failed to register BLE services")
        
        self._ble.irq(self._irq)
        self._advertise()

    def _irq(self, event, data):
        if event == _IRQ_CENTRAL_CONNECT:
            self._conn_handle, _, _ = data
            print("BLE connected")
        elif event == _IRQ_CENTRAL_DISCONNECT:
            self._conn_handle = None
            print("BLE disconnected - preparing for reconnection")
            time.sleep_ms(200)
            self._advertise()
        elif event == _IRQ_GATTS_WRITE:
            conn_handle, attr_handle = data
            if attr_handle == self._rx_handle:
                # Verify handles are valid before reading
                if self._rx_handle is not None:
                    data_received = self._ble.gatts_read(self._rx_handle)
                    if data_received is not None:
                        cmd = data_received.decode().strip()
                        response = handle_command(cmd)
                        if response:
                            self._send(response)

    def _send(self, text):
        if self._conn_handle is not None and self._tx_handle is not None:
            try:
                # gatts_notify takes: value_handle, data (no conn_handle needed)
                self._ble.gatts_notify(self._tx_handle, text.encode())
            except Exception as e:
                print("Error sending BLE notification:", e)

    def _advertise(self):
        """Start BLE advertising with retry logic."""
        # Start advertising with retries
        for attempt in range(3):
            try:
                payload = build_advertising_payload(self._name)
                # Simply start/restart advertising - no need for explicit stop
                self._ble.gap_advertise(100000, payload)
                print(f"BLE advertising started: {self._name} (payload: {len(payload)} bytes)")
                return
            except Exception as e:
                print(f"Advertising failed (attempt {attempt + 1}):", e)
                if attempt < 2:
                    time.sleep_ms(100)
        
        print("ERROR: Failed to start advertising after retries")


def main():
    print("AIRA Motor Controller - MicroPython")
    print("Commands: z=forward, s=backward, q=left, d=right, a=idle")

    # Initialize BLE GATT server
    uart = BLEUART("AIRA Motor")

    # Set up non-blocking serial input
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)

    print("Ready. Accepting commands via BLE and serial.")

    while True:
        if poll.poll(0):
            cmd = sys.stdin.read(1)
            if cmd:
                result = handle_command(cmd)
                # Only print when a valid command is processed
                if result:
                    print("Serial cmd:", repr(cmd), "->", result)
        time.sleep_ms(10)


main()
