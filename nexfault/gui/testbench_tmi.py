import queue
import serial
import struct
import threading
import time
from dataclasses import dataclass
from typing import List, Optional, Set, Tuple

from nexfault.protobuf_msgs.proto_msgs import uart_data_pb2


DSI_PORT = "COM5"
DSI_BAUD = 9600
READ_TIMEOUT_SEC = 0.05
FRAME_MAX_LEN = 1024
REPORT_TIMEOUT_SEC = 20.0


@dataclass
class RxMessage:
    kind: str  # "report" | "unknown"
    envelope: uart_data_pb2.Envelope


class FramedSerialClient:
    def __init__(self, port: str, baud: int):
        self.ser = serial.Serial(port, baud, timeout=READ_TIMEOUT_SEC)
        self._stop_evt = threading.Event()
        self._reader_thread: Optional[threading.Thread] = None
        self._buf = bytearray()
        self._msg_q: "queue.Queue[RxMessage]" = queue.Queue()
        self._lock = threading.Lock()

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
        payload = cmd.SerializeToString()
        frame = struct.pack("<H", len(payload)) + payload

        with self._lock:
            self.ser.write(frame)
            self.ser.flush()

        print(
            f"[PYTHON] Sent DsiCommand: id={cmd.id}, transport={cmd.transport}, "
            f"inj_type={cmd.inj_type}, duration_ms={cmd.duration_ms}"
        )

    def wait_for_final_report(
        self,
        command_id: int,
        timeout_sec: float = REPORT_TIMEOUT_SEC,
    ) -> Optional[uart_data_pb2.TmiReport]:
        """
        Wait for the single consolidated final report for a command.
        The firmware now sends only ONE report with STATUS_DONE + verdict set.
        """
        deadline = time.time() + timeout_sec

        while time.time() < deadline:
            remaining = max(0.0, deadline - time.time())
            try:
                msg = self._msg_q.get(timeout=min(0.5, remaining))
            except queue.Empty:
                continue

            if msg.kind != "report":
                continue

            r = msg.envelope.report

            if r.id != command_id:
                continue

            # we expect exactly one report with DONE status and a verdict
            if self._is_done_status(r.status) and self._has_verdict(r):
                return r

        return None

    def _is_done_status(self, status_value: int) -> bool:
        done_value = getattr(uart_data_pb2, "STATUS_DONE", None)
        if done_value is not None and status_value == done_value:
            return True
        return str(status_value).endswith("DONE")

    def _has_verdict(self, report: uart_data_pb2.TmiReport) -> bool:
        unset_verdict = getattr(uart_data_pb2, "VERDICT_UNSET", None)
        if unset_verdict is not None:
            return report.verdict != unset_verdict
        return bool(str(report.verdict_message).strip())

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
        while True:
            if len(self._buf) < 2:
                return

            msg_len = struct.unpack_from("<H", self._buf, 0)[0]
            if msg_len == 0 or msg_len > FRAME_MAX_LEN:
                self._buf.pop(0)
                continue

            frame_total = 2 + msg_len
            if len(self._buf) < frame_total:
                return

            payload = bytes(self._buf[2:frame_total])
            del self._buf[:frame_total]

            env = uart_data_pb2.Envelope()
            try:
                env.ParseFromString(payload)
            except Exception:
                continue

            if env.HasField("report"):
                self._msg_q.put(RxMessage(kind="report", envelope=env))
            else:
                self._msg_q.put(RxMessage(kind="unknown", envelope=env))

    @staticmethod
    def enum_name(enum_cls, value):
        try:
            return enum_cls.Name(value)
        except Exception:
            return str(value)

    def print_report(self, report: uart_data_pb2.TmiReport):
        status_text = self.enum_name(uart_data_pb2.ExecStatus, report.status)
        frames = report.frames_sent if report.frames_sent > 0 else 1  # avoid div by zero

        print("\n" + "=" * 72)
        print(" " * 18 + "TMI FINAL REPORT")
        print("=" * 72)

        # --- Correlation ---
        print(f"Test ID:              {report.id}")
        print(f"Total Runs (frames):  {report.run_id}")
        print(f"Attempt No:           {report.attempt_no}")
        print(f"Status:               {status_text} ({report.status})")

        # --- Test Config ---
        print("-" * 72)
        print(f"Injection Type:       {self.enum_name(uart_data_pb2.InjectionType, report.injection_type)} ({report.injection_type})")
        print(f"Transport Type:       {self.enum_name(uart_data_pb2.TransportType, report.transport_type)} ({report.transport_type})")
        print(f"Duration (per inj):   {report.injection_duration_ms} ms")
        print(f"CRC Recalculated:     {report.crc_recalculated}")

        # --- Traffic Counters (totals + per-injection) ---
        print("-" * 72)
        print("TRAFFIC COUNTERS")
        print(f"  Bytes TX (per injection):       {report.bytes_transmitted}")
        print(f"  Bytes RX (per injection):       {report.bytes_received}")
        print(f"  Bytes Dropped (per injection):  {report.bytes_dropped}")
        print(f"  Bits Flipped (per injection):   {report.bits_flipped}")
        print(f"  Phantom Bytes (per injection):  {report.phantom_bytes_added}")

        # --- Frame Stats ---
        print("-" * 72)
        print("FRAME STATS")
        print(f"  Frames Sent:        {report.frames_sent}")
        print(f"  Responses OK:       {report.responses_ok}  ({report.responses_ok / frames * 100:.1f}%)")
        print(f"  Responses ERROR:    {report.responses_error}  ({report.responses_error / frames * 100:.1f}%)")
        print(f"  Timeouts:           {report.responses_timeout}  ({report.responses_timeout / frames * 100:.1f}%)")
        print(f"  Timeout Streak:     {report.consecutive_timeout_streak}")

        # --- Original Frames before Injection ---
        print("-" * 72)
        print("ORIGINAL RTU FRAMES (hex)")
        o_frame_str = report.original_frame if report.original_frame else "(none)"
        
        o_individual_frames = o_frame_str.split(" | ")
        
        for i, f in enumerate(o_individual_frames, 1):
            print(f"  [{i:>4}] {f}")
        
        print(f"  Total original frames in buffer: {len(o_individual_frames)}")
        
        if len(o_individual_frames) < report.frames_sent:
            print(f"  NOTE: buffer held {len(o_individual_frames)}/{report.frames_sent} frames (buffer limit reached)")

        # --- Transmitted Frames ---
        print("-" * 72)
        print("TRANSMITTED RTU FRAMES (hex)")
        frame_str = report.final_frame if report.final_frame else "(none)"
        
        individual_frames = frame_str.split(" | ")
        
        for i, f in enumerate(individual_frames, 1):
            print(f"  [{i:>4}] {f}")
        
        print(f"  Total frames in buffer: {len(individual_frames)}")
        
        if len(individual_frames) < report.frames_sent:
            print(f"  NOTE: buffer held {len(individual_frames)}/{report.frames_sent} frames (buffer limit reached)")

        # --- Crash Detection ---
        print("-" * 72)
        print("CRASH DETECTION")
        print(f"  Crash Suspected:    {report.uut_reset_suspected}")
        print(f"  Crash Timestamp:    {report.crash_timestamp_ms} ms")

        # --- Performance ---
        print("-" * 72)
        print("PERFORMANCE")
        print(f"  Avg Response Time:  {report.avg_response_time_ms} ms")
        print(f"  Max Response Time:  {report.max_response_time_ms} ms")
        if report.injection_duration_ms > 0:
            inj_rate = report.frames_sent / (report.injection_duration_ms*report.frames_sent / 1000.0)
            print(f"  Injection Rate:     {inj_rate:.1f} frames/sec")

        # --- Verdict ---
        print("-" * 72)
        print("VERDICT")
        print(f"  Verdict:            {self.enum_name(uart_data_pb2.TestVerdict, report.verdict)} ({report.verdict})")
        print(f"  Reason:             {self.enum_name(uart_data_pb2.FailureReason, report.reason)} ({report.reason})")
        print(f"  Message:            {report.verdict_message}")
        print("=" * 72 + "\n")


def build_test_commands(start_id: int = 1) -> List[uart_data_pb2.DsiCommand]:
    cmds: List[uart_data_pb2.DsiCommand] = []

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
    cmd1.bit_flip.bits_drop = 9
    #cmd1.bit_flip.every_n_p = 1;
    cmds.append(cmd1)

    cmd2 = uart_data_pb2.DsiCommand()
    cmd2.id = start_id + 1
    cmd2.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd2.inj_type = uart_data_pb2.INJ_BYTE_DROP
    cmd2.duration_ms = 2500
    cmd2.modbus_config.slave_id = 1
    cmd2.modbus_config.func_code = 0x06
    cmd2.modbus_config.address = 100
    cmd2.modbus_config.value_or_quantity = 50
    cmd2.modbus_config.recalculate_crc = False
    cmd2.byte_drop.length = 2
    cmd2.byte_drop.start_offset = 2
    cmds.append(cmd2)

    cmd3 = uart_data_pb2.DsiCommand()
    cmd3.id = start_id + 2
    cmd3.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd3.inj_type = uart_data_pb2.INJ_PHANTOM_BYTE
    cmd3.duration_ms = 5000
    cmd3.modbus_config.slave_id = 1
    cmd3.modbus_config.func_code = 0x06
    cmd3.modbus_config.address = 100
    cmd3.modbus_config.value_or_quantity = 50
    cmd3.modbus_config.recalculate_crc = True
    cmd3.phantom_byte.mode = uart_data_pb2.PHANTOM_MANUAL
    cmd3.phantom_byte.byte_value = 0x01
    cmd3.phantom_byte.offset = 1
    cmds.append(cmd3)

    return cmds


def run():
    client = FramedSerialClient(DSI_PORT, DSI_BAUD)
    try:
        print(f"[PYTHON] Opening {DSI_PORT} @ {DSI_BAUD}")
        time.sleep(1.0)
        client.start()
        time.sleep(0.5)

        tests = build_test_commands(start_id=1)

        for i, cmd in enumerate(tests, start=1):
            print("\n" + "=" * 72)
            print(f"TEST {i} / {len(tests)}  | id={cmd.id} inj={cmd.inj_type} dur={cmd.duration_ms}ms")
            print("=" * 72)

            client.send_dsi_command(cmd)

            timeout = max(REPORT_TIMEOUT_SEC, (cmd.duration_ms / 1000.0) + 10.0)
            report = client.wait_for_final_report(command_id=cmd.id, timeout_sec=timeout)
            if report is None:
                print(f"[PYTHON] Timeout waiting for final report for test id={cmd.id}")
            else:
                client.print_report(report)

            time.sleep(1.5)

        print("[PYTHON] All tests complete")
    finally:
        client.close()
        print("[PYTHON] Serial closed")


if __name__ == "__main__":
    run()