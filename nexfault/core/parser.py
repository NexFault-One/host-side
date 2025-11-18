import serial
import random
import time
import os
from datetime import datetime
from serial.tools import list_ports
from nexfault.protobuf_msgs.proto_msgs import uart_data_pb2
from google.protobuf.message import DecodeError
import struct

# serial device connection, data read and write logic
class SerialDevice:

    def __init__(self, port: str, baud: int):
        """
        Initializes serial device with given serial port and baud rate. Collects device description and information.
        """

        self.port = port
        self.baud = baud
        self.timeout = 0.1
        self.ser = None

        self._simulate = (str(port).upper() == "FAKE") # For hardwareless integration testing

        for port in list_ports.comports():
            if port.device == self.port:
                self.description = port.description
                self.hwid = port.hwid
        
        if self._simulate:
            self.description = "Fake Serial (simulated)"
            self.hwid = "SIM-FAKE-PORT"

    def connect(self):
        """
        Attempt connection to serial port.
        """

        try:
            print(f"Attempting connection to {self.port} with baud {self.baud}")
            if self._simulate:
                self.ser = object()
                print("Connection successful! (simulated)")
                return
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            print(f"Connection successful!")
        except (OSError, serial.SerialException) as e:
            print("Error opening serial port: ", e)
            self.ser = None

    def is_connected(self) -> bool:
        """
        Verify connection to serial port.
        """

        return (self._simulate and self.ser is not None) or (self.ser is not None and self.ser.is_open)
    
    def fw_ver(self):
        """
        Gets device firmware version.
        """

        # Must be implemented firmware side
        return "sim-0.1" if self._simulate else "None"
    
    def bus(self):
        """
        Returns device hardware ID information.
        """

        # May require firmware support. Currently not feasible with PySerial
        return self.hwid
    
    def features(self):
        """
        Checks features of serial device. Not yet implemented.
        """

        return 1
    
    def read_buffer(self, duration: float):
        """
        Collect data from the device's buffer and save to an array. Includes timestamp for logging purposes.
        """
        # must include interrupt / synchronization to prevent incomplete read.

        if not self.is_connected():
            print("Serial device is not connected.")
            return []
        
        if self._simulate:
            return self._fake_rows(duration)

        print (f"Reading data on {self.port} for {duration}s")
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
        Writes provided (assumed already serialized) protobuf message to buffer, returns write success (true/false)
        """

        if (not self.is_connected()):
            print ("Serial buffer not initialized.")
            return False
        
        if (self.try_parse_command(message) == None):
            print ("provided message is invalid, cannot be written.")
            return False

        self.ser.write(message)
        self.ser.flush()
        print(message)
        return True
   
    def disconnect(self):
        """
        Disconnects serial device.
        """
        # Simulated port
        if getattr(self, "_simulate", False):
            self.ser = None
            print("Disconnected (simulated)")
            return

        # Real port
        try:
            if self.ser and getattr(self.ser, "is_open", False):
                self.ser.close()
        finally:
            self.ser = None
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Serial connection closed.")

# ------------------------------------------- INJECTIONS ----------------------------------------------

    def byte_drop(self, seq_id = 1, start_offset = 0, length = 1, duration = 0):
        """
        Helper for byte drop injection
        """

        message = uart_data_pb2.DsiCommand()
        message.proto_version = 1
        message.id = seq_id
        message.cmd = uart_data_pb2.CommandType.CMD_INJECT
        message.inj_type = uart_data_pb2.InjectionType.INJ_BYTE_DROP
        message.byte_drop.start_offset = start_offset
        message.byte_drop.length = length

        data = message.SerializeToString()

        # if getattr(self, "_simulate", False): #simulate value
        #     print (f"[SIM TX] {frame.hex(' ')}")
        #     return 

        return data
    
    def bit_flip(self, seq_id = 1, start_offset = 0, length = 1, xor_mask = 0, duration = 0):
        """
        Helper for bit flip injection
        """

        message = uart_data_pb2.DsiCommand()
        message.proto_version = 1
        message.id = seq_id
        message.cmd = uart_data_pb2.CommandType.CMD_INJECT
        message.inj_type = uart_data_pb2.InjectionType.INJ_BYTE_DROP
        message.byte_drop.start_offset = start_offset
        message.byte_drop.length = length
        message.xor_mask = xor_mask

        data = message.SerializeToString()

        # if getattr(self, "_simulate", False): #simulate value
        #     print (f"[SIM TX] {frame.hex(' ')}")
        #     return 

        return data
            
# ---------------------------------------------- HELPERS ----------------------------------------------

    def log_entry(self, data):
        """
        creates formatted entry with given bytes that can be inserted into read arrays.
        """
        # must be updated along with read_buffer function
        data_type = self.serial_data_type(data)
        if data_type.__module__ == "uart_data_pb2":
            hex_data = hex(0)
            ascii_data = f"Protobuf Message: {data_type.__name__}"
        else:
            hex_data = data.hex(" ")
            ascii_data = data.decode("utf-8", "ignore").strip()
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        entry = [timestamp, len(data), hex_data, ascii_data, data, self.serial_data_type(data)]
        return entry
    
    def serial_data_type(self, bytes):
        """
        Checks if given data is a protobuf message. Takes bytes from serial, attempts parse and identification of data type. returns protobuf object type or bytes.
        """
        # strictly returns message type for debug / analysis. does not handle receiving live ack from firmware.
        for parsed in (self.try_parse_ack, self.try_parse_report, self.try_parse_command):
            msg = parsed(bytes)
            if msg is not None:
                return type(msg)
        return type(bytes)

    # need to ensure that each method is isolated to its targeted object type (DsiAck objects should not be able to parse as TmiReport or DsiCommand)
    def try_parse_ack(self, raw_bytes):
        """
        Attempts to parse given message as a DsiAck. Returns decoded message if successful, None if failure
        """
        msg = uart_data_pb2.DsiAck()
        try:
            msg.ParseFromString(raw_bytes)
            return msg
        except DecodeError:
            return None
    
    def try_parse_report(self, raw_bytes):
        """
        Attempts to parse given message as a TmiReport. Returns decoded message if successful, None if failure
        """
        msg = uart_data_pb2.TmiReport()
        try:
            msg.ParseFromString(raw_bytes)
            return msg
        except DecodeError:
            return None
    
    def try_parse_command(self, raw_bytes):
        """
        Attempts to parse given message as a DsiCommand. Returns decoded message if successful, None if failure
        """
        msg = uart_data_pb2.DsiCommand()
        try:
            msg.ParseFromString(raw_bytes)
            return msg
        except DecodeError:
            return None
    
    def _fake_rows(self, duration: float):
        import time
        from datetime import datetime
        data = []
        end_time = time.time() + duration
        t0 = time.time()
        while time.time() < end_time:
            prog = ((time.time() - t0) % 10) / 10.0
            line = f"PROG:{prog:.2f}\r\n".encode("ascii")
            # A small binary packet (Modbus-like)
            pkt = bytes([0x01, 0x03, 0x00, 0x10, 0x00, 0x02, 0xC4, 0x0B])

            for chunk in (line, pkt):
                hex_data = chunk.hex(" ")
                ascii_data = chunk.decode("utf-8", "ignore").strip()
                ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                data.append([ts, len(chunk), hex_data, ascii_data, chunk])

            time.sleep(0.25)
        print("Read complete! (simulated)")
        return data