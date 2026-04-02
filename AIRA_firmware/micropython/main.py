import bluetooth
import time
import sys
import select
from machine import Pin, PWM
from micropython import const
from ble_advertising import advertising_payload

# For Pico W: Wake up the CYW43 chip
try:
    import network
    net = network.WLAN(network.STA_IF)
    net.active(False)
except:
    pass

# BLE IRQ event constants
_IRQ_CENTRAL_CONNECT = const(1)
_IRQ_CENTRAL_DISCONNECT = const(2)
_IRQ_GATTS_WRITE = const(3)

# BLE Characteristic flags
_FLAG_WRITE = const(0x0008)
_FLAG_NOTIFY = const(0x0010)

# Gap appearance for generic computer
_ADV_APPEARANCE_GENERIC_COMPUTER = const(128)

# Nordic UART Service (NUS) UUIDs
_UART_UUID = bluetooth.UUID("6E400001-B5A3-F393-E0A9-E50E24DCCA9E")
_UART_TX = (bluetooth.UUID("6E400003-B5A3-F393-E0A9-E50E24DCCA9E"), _FLAG_NOTIFY,)
_UART_RX = (bluetooth.UUID("6E400002-B5A3-F393-E0A9-E50E24DCCA9E"), _FLAG_WRITE,)
_UART_SERVICE = (_UART_UUID, (_UART_TX, _UART_RX),)


class Motor:
    def __init__(self, in1_pin, in2_pin, pwm_pin):
        try:
            self.in1 = Pin(in1_pin, Pin.OUT, value=0)
            self.in2 = Pin(in2_pin, Pin.OUT, value=0)
            self.pwm = PWM(Pin(pwm_pin))
            self.pwm.freq(10000)  # 10kHz, same as C firmware
            self.pwm.duty_u16(0)
        except Exception as e:
            print(f"Motor init error on pins {in1_pin},{in2_pin},{pwm_pin}: {e}")
            self.in1 = None
            self.in2 = None
            self.pwm = None

    def forward(self):
        if self.in1 and self.in2:
            self.in1.value(1)
            self.in2.value(0)

    def backward(self):
        if self.in1 and self.in2:
            self.in1.value(0)
            self.in2.value(1)

    def idle(self):
        if self.in1 and self.in2:
            self.in1.value(0)
            self.in2.value(0)

    def set_speed(self, duty):
        if self.pwm:
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
print("Initializing motors...")
try:
    m_front_left  = Motor(Motor_Front_Left_IN1,  Motor_Front_Left_IN2,  Motor_Front_Left_PWM)
    m_front_right = Motor(Motor_Front_Right_IN1, Motor_Front_Right_IN2, Motor_Front_Right_PWM)
    m_rear_left   = Motor(Motor_Rear_Left_IN1,   Motor_Rear_Left_IN2,   Motor_Rear_Left_PWM)
    m_rear_right  = Motor(Motor_Rear_Right_IN1,  Motor_Rear_Right_IN2,  Motor_Rear_Right_PWM)
    motors = [m_front_left, m_front_right, m_rear_left, m_rear_right]
    print("Motors initialized successfully")
except Exception as e:
    print(f"ERROR initializing motors: {e}")
    motors = []


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
    if not cmd or not motors:
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
        if len(motors) >= 4:
            motors[1].forward()  # front right
            motors[3].forward()  # rear right
            motors[0].backward() # front left
            motors[2].backward() # rear left
        for m in motors:
            m.set_speed(1.0)
        return "Turn Left"

    elif c == 'd':
        # Turn right: left motors forward, right motors backward
        if len(motors) >= 4:
            motors[0].forward()  # front left
            motors[2].forward()  # rear left
            motors[1].backward() # front right
            motors[3].backward() # rear right
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


class BLEUART:
    """BLE UART Peripheral following MicroPython official example."""
    
    def __init__(self, ble, name="mpy-uart", rxbuf=100):
        print(f"  [BLEUART] Init with name='{name}'")
        self._ble = ble
        
        print("  [BLEUART] Activating BLE...")
        self._ble.active(True)
        print("  [BLEUART] BLE activated")
        
        print("  [BLEUART] Registering IRQ handler...")
        self._ble.irq(self._irq)
        print("  [BLEUART] IRQ registered")
        
        # Register BLE GATT services
        print("  [BLEUART] Registering GATT services...")
        ((self._tx_handle, self._rx_handle),) = self._ble.gatts_register_services((_UART_SERVICE,))
        print(f"  [BLEUART] Services registered: TX={self._tx_handle}, RX={self._rx_handle}")
        
        # Set up RX buffer: increase size and enable append mode
        print("  [BLEUART] Setting RX buffer...")
        self._ble.gatts_set_buffer(self._rx_handle, rxbuf, True)
        print("  [BLEUART] RX buffer set")
        
        # Track active connections
        self._connections = set()
        self._last_activity = {}  # Track last activity per connection
        
        # RX buffer for accumulated data
        self._rx_buffer = bytearray()
        
        # Optional handler callback
        self._handler = None
        
        # Build advertising payload with appearance
        # Note: services can make payload too large, so we use appearance instead
        print("  [BLEUART] Building advertising payload...")
        self._payload = advertising_payload(
            name=name,
            appearance=_ADV_APPEARANCE_GENERIC_COMPUTER
        )
        print(f"  [BLEUART] Payload built: {len(self._payload)} bytes")
        
        # Start advertising
        print("  [BLEUART] Starting advertising...")
        self._advertise()
        print(f"[BLEUART] Ready! '{name}' advertising - Multiple connections allowed")

    def _irq(self, event, data):
        """Handle BLE events."""
        if event == _IRQ_CENTRAL_CONNECT:
            conn_handle, _, _ = data
            self._connections.add(conn_handle)
            self._last_activity[conn_handle] = time.ticks_ms()
            print(f"BLE connected: {conn_handle} (Total: {len(self._connections)})")
            
        elif event == _IRQ_CENTRAL_DISCONNECT:
            conn_handle, _, _ = data
            if conn_handle in self._connections:
                self._connections.remove(conn_handle)
            if conn_handle in self._last_activity:
                del self._last_activity[conn_handle]
            print(f"BLE disconnected: {conn_handle} (Total: {len(self._connections)})")
            # Start advertising again to allow new connections
            self._advertise()
            
        elif event == _IRQ_GATTS_WRITE:
            conn_handle, value_handle = data
            if conn_handle in self._connections and value_handle == self._rx_handle:
                # Update activity timestamp
                self._last_activity[conn_handle] = time.ticks_ms()
                # Append received data to buffer
                self._rx_buffer += self._ble.gatts_read(self._rx_handle)
                # Call handler if registered
                if self._handler:
                    self._handler()

    def irq(self, handler):
        """Register a callback to be called when data is received."""
        self._handler = handler

    def any(self):
        """Return the number of bytes in the RX buffer."""
        return len(self._rx_buffer)

    def read(self, sz=None):
        """Read and remove bytes from the RX buffer."""
        if not sz:
            sz = len(self._rx_buffer)
        result = self._rx_buffer[0:sz]
        self._rx_buffer = self._rx_buffer[sz:]
        return result

    def write(self, data):
        """Send data to all connected centrals."""
        for conn_handle in self._connections:
            self._ble.gatts_notify(conn_handle, self._tx_handle, data)

    def close(self):
        """Disconnect all centrals."""
        for conn_handle in self._connections:
            self._ble.gap_disconnect(conn_handle)
        self._connections.clear()

    def _advertise(self, interval_us=500000):
        """Start BLE advertising."""
        self._ble.gap_advertise(interval_us, adv_data=self._payload)


def main():
    print("AIRA Motor Controller - MicroPython (Pico W)")
    print("Commands: z=forward, s=backward, q=left, d=right, a=idle")

    # Initialize BLE
    print("\n[BLE] Initializing...")
    try:
        print("[BLE] Soft reset of BLE controller...")
        # Soft reset - create and deactivate BLE
        try:
            ble_test = bluetooth.BLE()
            ble_test.active(False)
            time.sleep_ms(500)
        except:
            pass
        
        print("[BLE] Creating BLE object...")
        ble = bluetooth.BLE()
        print("[BLE] BLE object created")
        
        print("[BLE] Creating BLEUART...")
        uart = BLEUART(ble, name="AIRA Motor", rxbuf=100)
        print("[BLE] BLEUART created successfully")
    except Exception as e:
        print(f"[BLE] ERROR during initialization: {e}")
        print("[BLE] BLE not available - continuing without BLE")
        uart = None

    # Set up non-blocking serial input
    poll = select.poll()
    poll.register(sys.stdin, select.POLLIN)

    print("Ready. Accepting commands via serial and BLE.")

    # Define callback for BLE data reception
    if uart:
        def on_ble_rx():
            while uart.any():
                try:
                    cmd = uart.read(1).decode().strip()
                except:
                    continue
                if cmd:
                    result = handle_command(cmd)
                    if result:
                        print("BLE cmd:", repr(cmd), "->", result)
                        uart.write(result.encode() + b'\n')

        uart.irq(on_ble_rx)

    try:
        while True:
            # Check for serial input
            if poll.poll(0):
                cmd = sys.stdin.read(1)
                if cmd:
                    result = handle_command(cmd)
                    if result:
                        print("Serial cmd:", repr(cmd), "->", result)

            time.sleep_ms(10)
    except KeyboardInterrupt:
        print("Exiting...")
        if uart:
            uart.close()


main()
