import serial
import struct
import time
import threading
import queue
from dataclasses import dataclass
from typing import Optional, List

from nexfault.protobuf_msgs.proto_msgs import uart_data_pb2


# =========================
# CONFIG
# =========================
DSI_PORT = "COM3"
DSI_BAUD = 9600

READ_TIMEOUT_SEC = 0.05
FRAME_MAX_LEN = 1024
REPORT_TIMEOUT_SEC = 20.0


@dataclass
class RxMessage:
    kind: str  # "report" | "unknown"
    envelope: uart_data_pb2.Envelope


class FramedSerialClient:
    """
    Single-reader framed serial client:
      - Reads bytes in one thread
      - Parses little-endian 2-byte length + protobuf payload
      - Parses payload as Envelope only for TmiReport
    """

    def __init__(self, port: str, baud: int):
        self.ser = serial.Serial(port, baud, timeout=READ_TIMEOUT_SEC)
        self._stop_evt = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._buf = bytearray()
        self._msg_q: "queue.Queue[RxMessage]" = queue.Queue()
        self._lock = threading.Lock()  # serialize writes

    def start(self):
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def close(self):
        self._stop_evt.set()
        if self._reader_thread and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=1.0)
        if self.ser and self.ser.is_open:
            self.ser.close()

    def send_dsi_command(self, cmd: uart_data_pb2.DsiCommand):
        """
        IMPORTANT: send raw DsiCommand (NOT Envelope).
        """
        payload = cmd.SerializeToString()
        frame = struct.pack("<H", len(payload)) + payload

        with self._lock:
            self.ser.write(frame)
            self.ser.flush()

        print(
            f"[PYTHON] Sent DsiCommand: id={cmd.id}, transport={cmd.transport}, "
            f"inj_type={cmd.inj_type}, duration_ms={cmd.duration_ms}"
        )

    def wait_for_report(self, timeout_sec: float = REPORT_TIMEOUT_SEC) -> Optional[uart_data_pb2.TmiReport]:
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            try:
                msg = self._msg_q.get(timeout=min(0.25, remaining))
            except queue.Empty:
                continue

            if msg.kind == "report":
                return msg.envelope.report
            else:
                print("[PYTHON] Envelope received (non-report / unknown)")
        return None

    def _reader_loop(self):
        print("[PYTHON] Reader thread started")
        while not self._stop_evt.is_set():
            try:
                chunk = self.ser.read(self.ser.in_waiting or 1)
                if chunk:
                    self._buf.extend(chunk)
                    self._parse_frames()
                else:
                    time.sleep(0.01)
            except serial.SerialException as e:
                print(f"[PYTHON] Serial error: {e}")
                break
            except Exception as e:
                print(f"[PYTHON] Reader exception: {e}")
                time.sleep(0.05)

        print("[PYTHON] Reader thread stopped")

    def _parse_frames(self):
        # Parse as many complete frames as possible
        while True:
            if len(self._buf) < 2:
                return

            msg_len = struct.unpack_from("<H", self._buf, 0)[0]

            # Sanity checks + re-sync
            if msg_len == 0 or msg_len > FRAME_MAX_LEN:
                self._buf.pop(0)
                continue

            frame_total = 2 + msg_len
            if len(self._buf) < frame_total:
                return  # need more bytes

            payload = bytes(self._buf[2:frame_total])
            del self._buf[:frame_total]

            # Parse only as Envelope for TmiReport output path
            env = uart_data_pb2.Envelope()
            try:
                env.ParseFromString(payload)
            except Exception:
                # Could be text/log noise or future message type
                continue

            if env.HasField("report"):
                self._msg_q.put(RxMessage(kind="report", envelope=env))
            else:
                self._msg_q.put(RxMessage(kind="unknown", envelope=env))


def safe_pct(num: int, den: int) -> float:
    return (num / den * 100.0) if den else 0.0


def enum_name(enum_cls, value):
    # Works with generated protobuf enums
    try:
        return enum_cls.Name(value)
    except Exception:
        return str(value)

def print_report(report):
    print("\n" + "=" * 72)
    print(" " * 24 + "TMI FINAL REPORT")
    print("=" * 72)
    print(f"Test ID:            {report.id}")
    # todo: fix run id & attempt no
    print(f"Run ID:             {report.run_id}")
    print(f"Attempt No:         {report.attempt_no}")
    #print(f"Timestamp (ms):     {report.timestamp_ms}")
    print(f"Duration:           {report.injection_duration_ms} ms")
    print(f"Injection Type:     {enum_name(uart_data_pb2.InjectionType, report.injection_type)} ({report.injection_type})")
    print(f"Transport Type:     {enum_name(uart_data_pb2.TransportType, report.transport_type)} ({report.transport_type})")
    print(f"CRC Recalculated:   {report.crc_recalculated}")
    print("-" * 72)
    print(f"Bytes TX:           {report.bytes_transmitted}")
    print(f"Bytes RX:           {report.bytes_received}")
    print(f"Bytes Dropped:      {report.bytes_dropped}")
    print(f"Bits Flipped:       {report.bits_flipped}")
    print(f"Phantom Bytes:      {report.phantom_bytes_added}")
    print("-" * 72)
    print(f"Frames Sent:        {report.frames_sent}")
    print(f"Responses OK:       {report.responses_ok}")
    print(f"Responses ERROR:    {report.responses_error}")
    print(f"Timeouts:           {report.responses_timeout}")
    print(f"Timeout Streak:     {report.consecutive_timeout_streak}")
    print("-" * 72)
    print(f"Crash Suspected:    {report.uut_reset_suspected}")
    print(f"Crash Timestamp:    {report.crash_timestamp_ms} ms")
    print(f"Avg Response Time:  {report.avg_response_time_ms} ms")
    print(f"Max Response Time:  {report.max_response_time_ms} ms")
    print("-" * 72)
    print(f"Verdict:            {enum_name(uart_data_pb2.TestVerdict, report.verdict)} ({report.verdict})")
    print(f"Reason:             {enum_name(uart_data_pb2.FailureReason, report.reason)} ({report.reason})")
    print(f"Message:            {report.verdict_message}")
    print("=" * 72 + "\n")


def build_test_commands(start_id: int = 1) -> List[uart_data_pb2.DsiCommand]:
    cmds: List[uart_data_pb2.DsiCommand] = []

    # TEST 1: BitFlip Random
    cmd1 = uart_data_pb2.DsiCommand()
    cmd1.id = start_id
    cmd1.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd1.inj_type = uart_data_pb2.INJ_BIT_FLIP
    cmd1.duration_ms = 5000
    cmd1.modbus_config.slave_id = 1
    cmd1.modbus_config.func_code = 0x06
    cmd1.modbus_config.address = 100
    cmd1.modbus_config.value_or_quantity = 50
    cmd1.modbus_config.recalculate_crc = True
    cmd1.bit_flip.mode = uart_data_pb2.BITFLIP_RANDOM
    cmd1.bit_flip.bits_drop = 5
    cmds.append(cmd1)

    # TEST 2: ByteDrop
    cmd2 = uart_data_pb2.DsiCommand()
    cmd2.id = start_id + 1
    cmd2.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd2.inj_type = uart_data_pb2.INJ_BYTE_DROP
    cmd2.duration_ms = 5000
    cmd2.modbus_config.slave_id = 1
    cmd2.modbus_config.func_code = 0x06
    cmd2.modbus_config.address = 100
    cmd2.modbus_config.value_or_quantity = 50
    cmd2.modbus_config.recalculate_crc = True
    cmd2.byte_drop.length = 1
    cmd2.byte_drop.start_offset = 2
    cmds.append(cmd2)

    # TEST 3: PhantomByte
    cmd3 = uart_data_pb2.DsiCommand()
    cmd3.id = start_id + 2
    cmd3.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd3.inj_type = uart_data_pb2.INJ_PHANTOM_BYTE
    cmd3.duration_ms = 5000
    cmd3.modbus_config.slave_id = 1
    cmd3.modbus_config.func_code = 0x06
    cmd3.modbus_config.address = 100
    cmd3.modbus_config.value_or_quantity = 50
    cmd3.modbus_config.recalculate_crc = False
    cmd3.phantom_byte.mode = uart_data_pb2.PHANTOM_MANUAL
    cmd3.phantom_byte.byte_value = 0xAB
    cmd3.phantom_byte.offset = 1
    cmds.append(cmd3)

    return cmds


def run():
    client = FramedSerialClient(DSI_PORT, DSI_BAUD)
    try:
        print(f"[PYTHON] Opening {DSI_PORT} @ {DSI_BAUD}")
        time.sleep(1.0)  # serial settle
        client.start()
        time.sleep(0.5)

        tests = build_test_commands(start_id=1)

        for i, cmd in enumerate(tests, start=1):
            print("\n" + "=" * 72)
            print(f"TEST {i} / {len(tests)}  | id={cmd.id} inj={cmd.inj_type} dur={cmd.duration_ms}ms")
            print("=" * 72)

            client.send_dsi_command(cmd)

            # Slightly above duration to allow reporter task to fire
            timeout = max(REPORT_TIMEOUT_SEC, (cmd.duration_ms / 1000.0) + 8.0)
            report = client.wait_for_report(timeout_sec=timeout)
            if report is None:
                print(f"[PYTHON] Timeout waiting for report for test id={cmd.id}")
            else:
                print_report(report)

            time.sleep(1.5)

        print("[PYTHON] All tests complete")

    finally:
        client.close()
        print("[PYTHON] Serial closed")


if __name__ == "__main__":
    run()