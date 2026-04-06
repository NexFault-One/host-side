import time
import uuid
from datetime import datetime

import serial
from google.protobuf.message import DecodeError
from serial.tools import list_ports

from nexfault.protobuf_msgs.proto_msgs import uart_data_pb2


# serial device connection, data read and write logic
class SerialDevice:
    """Serial device connection, data read and write logic."""

    def __init__(self, port: str, baud: int):
        """
        Initialize serial device with given serial port and baud rate.
        Collects device description and information.
        """
        self.port = port
        self.baud = baud
        self.timeout = 0.1
        self.ser = None

        self._simulate = str(port).upper() == "FAKE"

        for port in list_ports.comports():
            if port.device == self.port:
                self.description = port.description
                self.hwid = port.hwid

        if self._simulate:
            self.description = "Fake Serial (simulated)"
            self.hwid = "SIM-FAKE-PORT"

    def connect(self, do_handshake: bool = False):
        """Attempt connection to serial port."""
        try:
            print(f"Attempting connection to {self.port} with baud {self.baud}")
            if self._simulate:
                self.ser = object()
                print("Connection successful! (simulated)")
                return
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            print("Connection successful!")
            self.handshake(5)
        except (OSError, serial.SerialException) as e:
            print("Error opening serial port: ", e)
            self.ser = None

    def is_connected(self) -> bool:
        """Verify connection to serial port."""
        return (self._simulate and self.ser is not None) or (
            self.ser is not None and self.ser.is_open
        )

    def fw_ver(self):
        """Get device firmware version."""
        # Must be implemented firmware side
        return "sim-0.1" if self._simulate else "None"

    def bus(self):
        """Return device hardware ID information."""
        # May require firmware support. Currently not feasible with PySerial
        return self.hwid

    def features(self):
        """Check features of serial device. Not yet implemented."""
        return 1

    def read_buffer(self, duration: float):
        """
        Collect data from the device's buffer and save to an array.
        Includes timestamp for logging purposes.
        """
        # Must include interrupt / synchronization to prevent incomplete read.
        if not self.is_connected():
            print("Serial device is not connected.")
            return []

        if self._simulate:
            return self._fake_rows(duration)

        print(f"Reading data on {self.port} for {duration}s")
        end_time = time.time() + duration
        data = []
        while time.time() < end_time:
            if self.ser.in_waiting > 0:
                read_data = self.ser.read(self.ser.in_waiting)
                read_log = self.log_entry(read_data)
                data.append(read_log)
        print("Read complete!")
        return data

    def write_buffer(self, message):
        """
        Write provided (assumed already serialized) protobuf message to buffer.
        Returns write success (True/False).
        """
        if not self.is_connected():
            print("Serial buffer not initialized.")
            return False

        if self.try_parse_command(message) is None:
            print("Provided message is invalid, cannot be written.")
            return False

        self.ser.write(message)
        self.ser.flush()
        print(message)
        return True
    
    def write_protobuf(self, message: bytes):
        if not self.is_connected():
            print("Serial buffer not initialized.")
            return False
        msg_len = len(message)
        prefix = msg_len.to_bytes(2, "little")
        self.ser.write(prefix + message)
        self.ser.flush()
        print(prefix + message)
        return True

    def write_raw(self, message):
        """Write message ignoring protobuf structure and safety checks."""
        if self._simulate:
            print(message)
            return True
        self.ser.write(message)
        self.ser.flush()
        print(message)
        return True

    def disconnect(self):
        """Disconnect serial device."""
        if getattr(self, "_simulate", False):
            self.ser = None
            print("Disconnected (simulated)")
            return

        try:
            if self.ser and getattr(self.ser, "is_open", False):
                self.ser.close()
        finally:
            self.ser = None
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Serial connection closed.")

    # INJECTIONS

    def byte_drop(
        self,
        seq_id=1,
        start_offset=0,
        length=1,
        payload="default",
        transport=uart_data_pb2.TransportType.TRANSPORT_UART,
        duration=0,
        burst_mode=False,
        burst_count=0,
        modbus_config=None,
    ):
        """Helper for byte drop injection."""
        message = uart_data_pb2.DsiCommand()
        message.proto_version = 1
        message.id = seq_id
        message.cmd = uart_data_pb2.CommandType.CMD_INJECT
        message.inj_type = uart_data_pb2.InjectionType.INJ_BYTE_DROP
        message.transport = transport
        message.duration_ms = duration
        message.burst_mode = burst_mode
        message.burst_count = burst_count
        message.byte_drop.start_offset = start_offset
        message.byte_drop.length = length
        message.byte_drop.payload = payload

        is_modbus = transport == uart_data_pb2.TransportType.TRANSPORT_MODBUS
        if is_modbus and modbus_config is not None:
            message.modbus_config.CopyFrom(modbus_config)

        return message.SerializeToString()

    def bit_flip(
        self,
        seq_id=1,
        every_n_p=2,
        bits_drop=1,
        payload="default",
        bit_flip_mode=uart_data_pb2.BitFlipMode.BITFLIP_RANDOM,
        transport=uart_data_pb2.TransportType.TRANSPORT_UART,
        duration=0,
        burst_mode=False,
        burst_count=0,
        modbus_config=None,
    ):
        """Helper for bit flip injection."""
        message = uart_data_pb2.DsiCommand()
        message.proto_version = 1
        message.id = seq_id
        message.cmd = uart_data_pb2.CommandType.CMD_INJECT
        message.inj_type = uart_data_pb2.InjectionType.INJ_BIT_FLIP
        message.transport = transport
        message.duration_ms = duration
        message.burst_mode = burst_mode
        message.burst_count = burst_count
        message.bit_flip.every_n_p = every_n_p
        message.bit_flip.bits_drop = bits_drop
        message.bit_flip.payload = payload
        message.bit_flip.mode = bit_flip_mode

        is_modbus = transport == uart_data_pb2.TransportType.TRANSPORT_MODBUS
        if is_modbus and modbus_config is not None:
            message.modbus_config.CopyFrom(modbus_config)

        return message.SerializeToString()

    def phantom_byte(
        self,
        seq_id=1,
        offset=0,
        byte_value=0,
        payload="default",
        phantom_byte_mode=uart_data_pb2.PhantomByteMode.PHANTOM_RANDOM,
        transport=uart_data_pb2.TransportType.TRANSPORT_UART,
        duration=0,
        burst_mode=False,
        burst_count=0,
        modbus_config=None,
    ):
        """Helper for phantom byte injection."""
        message = uart_data_pb2.DsiCommand()
        message.proto_version = 1
        message.id = seq_id
        message.cmd = uart_data_pb2.CommandType.CMD_INJECT
        message.inj_type = uart_data_pb2.InjectionType.INJ_PHANTOM_BYTE
        message.transport = transport
        message.duration_ms = duration
        message.burst_mode = burst_mode
        message.burst_count = burst_count
        message.phantom_byte.offset = offset
        message.phantom_byte.byte_value = byte_value
        message.phantom_byte.payload = payload
        message.phantom_byte.mode = phantom_byte_mode

        is_modbus = transport == uart_data_pb2.TransportType.TRANSPORT_MODBUS
        if is_modbus and modbus_config is not None:
            message.modbus_config.CopyFrom(modbus_config)

        return message.SerializeToString()

    def stop_injection(self, seq_id=1):
        """helper for command to stop injection"""
        message = uart_data_pb2.DsiCommand()
        message.proto_version = 1
        message.id = seq_id
        message.stop = True
        return message.SerializeToString()

    def _build_modbus_config(
        self, slave_id, func_code, address, value, recalculate_crc
    ):
        """Helper to build modbus config"""
        cfg = uart_data_pb2.ModbusConfig()
        cfg.slave_id = slave_id
        cfg.func_code = func_code
        cfg.address = address
        cfg.value_or_quantity = value
        cfg.recalculate_crc = recalculate_crc
        return cfg

    # HELPERS

    def log_entry(self, data):
        """
        Create a formatted entry with given bytes that can be inserted
        into read arrays.
        """
        parsed = self.parse_envelope(data)
        if parsed is not None:
            data_type = type(parsed)
            hex_data = hex(0)
            ascii_data = f"Protobuf Message: {data_type.__name__}"
        else:
            data_type = type(data)
            hex_data = data.hex(" ")
            ascii_data = data.decode("utf-8", "ignore").strip()
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        return [timestamp, len(data), hex_data, ascii_data, data, data_type]

    def parse_envelope(self, raw_bytes):
        """Parses protobuf envelope from firmware and returns the inside data"""
        env = uart_data_pb2.Envelope()

        try:
            env.ParseFromString(raw_bytes)
        except DecodeError:
            return None

        if env.HasField("report"):
            report = env.report
            # Host-assigned ID and completion timestamp (time envelope was received)
            # report.id = uuid.uuid4().int & 0xFFFFFFFF
            # report.timestamp_ms = int(datetime.now().timestamp())
            message = report
        elif env.HasField("dsi_ack"):
            message = env.dsi_ack
        elif env.HasField("dsi_command"):
            message = env.dsi_command
        else:
            return None

        return message

    def _fake_rows(self, duration: float):
        """Generate simulated log entries for hardwareless testing."""
        data = []
        end_time = time.time() + duration
        t0 = time.time()
        while time.time() < end_time:
            prog = ((time.time() - t0) % 10) / 10.0
            line = f"PROG:{prog:.2f}\r\n".encode("ascii")
            pkt = bytes([0x01, 0x03, 0x00, 0x10, 0x00, 0x02, 0xC4, 0x0B])

            for chunk in (line, pkt):
                hex_data = chunk.hex(" ")
                ascii_data = chunk.decode("utf-8", "ignore").strip()
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                data.append([ts, len(chunk), hex_data, ascii_data, chunk, type(chunk)])

            time.sleep(0.25)
        print("Read complete! (simulated)")
        return data

    def handshake(self, timeout):
        """Identify and acknowledge device type."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.ser.in_waiting > 0:
                message = self.ser.read(self.ser.in_waiting).decode("utf-8").strip()
                if "DSI" in message:
                    print("DSI found")
                    self.write_raw(b"<ACK:DSI>")
                    time.sleep(1)
                    return True
                elif "UUT" in message:
                    print("UUT found")
                    self.write_raw(b"<ACK:UUT>")
                    time.sleep(1)
                    return True
            time.sleep(0.1)
        raise TimeoutError("No device identification received.")
