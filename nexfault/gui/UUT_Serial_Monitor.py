import time
import threading
import serial
import serial.tools.list_ports
import dearpygui.dearpygui as dpg
import struct
from datetime import datetime

# Correct import based on your submodule structure
from nexfault.protobuf_msgs.proto_msgs import uart_data_pb2
from nexfault.core.parser import SerialDevice
from nexfault.core.logger import LogFile

# -----------------
# Global State
# -----------------
ser_main = None  # Single serial object for both DSI and UUT functions
running = False


# -----------------
# Serial Reader Loop (Combined)
# -----------------
def reader_loop_main(simulated=False):
    """Background loop: Handles UUT monitoring AND DSI progress updates"""
    global ser_main, running

    log_tag = "log_window_uut"  # Using the UUT window for everything

    while running:
        if simulated:
            time.sleep(1)
            msg = f"[Sim] Heartbeat {time.strftime('%H:%M:%S')}\n\n"
            dpg.add_text(msg, parent=log_tag)
            dpg.set_y_scroll(log_tag, -1)
        else:
            try:
                if ser_main and ser_main.in_waiting:
                    line = ser_main.readline().decode(errors="ignore").strip()
                    if line:
                        # 1. Log the line (UUT Function)
                        dpg.add_text(f"[RX] {line}\n\n", parent=log_tag)
                        dpg.set_y_scroll(log_tag, -1)

                        # 2. Check for DSI Progress Logic (DSI Function)
                        if line.startswith("PROG:"):
                            try:
                                value = float(line.split(":")[1])
                                dpg.set_value("progress_bar", min(max(value, 0.0), 1.0))
                            except ValueError:
                                pass
            except Exception as e:
                dpg.add_text(f"[Error] {e}\n\n", parent=log_tag)
                break
        time.sleep(0.05)


# -----------------
# Capture & Save Backend
# -----------------
def _make_row(chunk: bytes, ts: str):
    return [
        ts,
        len(chunk),
        chunk.hex(" "),
        chunk.decode("utf-8", "ignore").strip(),
        chunk,
    ]


def _capture_backend(duration_s: int, run_name: str):
    global ser_main, running

    port_tag = "main_port"
    log_window = "log_window_uut"

    # Pause the main reader loop
    running = False
    time.sleep(0.2)

    try:
        port = dpg.get_value(port_tag)
        simulated = str(port).strip().lower().startswith("simulated")

        dpg.add_text(
            f"[Capture] Starting {duration_s}s capture...\n\n", parent=log_window
        )
        dpg.set_y_scroll(log_window, -1)

        rows = []

        if simulated:
            dev = SerialDevice("FAKE", 115200)
            dev.connect()
            rows = dev.read_buffer(duration_s)
            dev.disconnect()
        else:
            if ser_main is None or not ser_main.is_open:
                dpg.add_text(f"[Capture] Error: Port not open\n\n", parent=log_window)
                return

            end = time.time() + duration_s
            old_timeout = ser_main.timeout
            ser_main.timeout = 0.1

            try:
                while time.time() < end:
                    if ser_main.in_waiting:
                        chunk = ser_main.read(ser_main.in_waiting or 1)
                        if chunk:
                            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            rows.append(_make_row(chunk, ts))
            finally:
                ser_main.timeout = old_timeout

        if rows:
            lf = LogFile((run_name).strip())
            headers = [
                "Timestamp",
                "Length",
                "Data (Hex)",
                "Data (ASCII)",
                "Data (Raw)",
            ]

            csv_path = lf.log_csv(headers, rows)
            json_path = lf.log_json(headers, rows)

            dpg.add_text(f"[Capture] Saved CSV: {csv_path}\n", parent=log_window)
            dpg.add_text(f"[Capture] Saved JSON: {json_path}\n\n", parent=log_window)
        else:
            dpg.add_text(f"[Capture] No data received.\n\n", parent=log_window)

    except Exception as e:
        dpg.add_text(f"[Capture Error] {e}\n\n", parent=log_window)

    finally:
        # Restart the main reader loop
        sim_again = str(dpg.get_value(port_tag)).strip().lower().startswith("simulated")
        if (ser_main and ser_main.is_open) or sim_again:
            running = True
            threading.Thread(
                target=reader_loop_main, args=(sim_again,), daemon=True
            ).start()


def start_capture_callback():
    run_name = _ui_get("run_name", "device_log")
    dur_val = _ui_get("duration", 5)
    threading.Thread(
        target=_capture_backend, args=(dur_val, run_name), daemon=True
    ).start()


# -----------------
# Connection Callback (Unified)
# -----------------
def toggle_connection():
    global ser_main, running
    current_label = dpg.get_item_label("btn_connect")

    if current_label == "Connect Device":
        port = dpg.get_value("main_port")
        baud = int(dpg.get_value("main_baud"))
        dpg.delete_item("log_window_uut", children_only=True)

        if port == "Simulated Device":
            dpg.set_value("conn_status", "Connected (Sim)")
            dpg.configure_item("conn_status", color=(0, 200, 0))
            dpg.configure_item("btn_connect", label="Disconnect")
            running = True
            threading.Thread(target=reader_loop_main, args=(True,), daemon=True).start()
            return

        try:
            ser_main = serial.Serial(port, baud, timeout=1)
            ser_main.dtr = False
            ser_main.rts = False
            dpg.set_value("conn_status", "Connected")
            dpg.configure_item("conn_status", color=(0, 200, 0))
            dpg.configure_item("btn_connect", label="Disconnect")
            running = True
            threading.Thread(target=reader_loop_main, daemon=True).start()
        except Exception as e:
            dpg.set_value("conn_status", "Error")
            dpg.configure_item("conn_status", color=(200, 0, 0))
            dpg.add_text(f"[Error] {e}\n\n", parent="log_window_uut")

    else:
        running = False
        time.sleep(0.1)
        try:
            if ser_main and ser_main.is_open:
                ser_main.close()
        except:
            pass
        ser_main = None
        dpg.set_value("conn_status", "Disconnected")
        dpg.configure_item("conn_status", color=(200, 50, 50))
        dpg.configure_item("btn_connect", label="Connect Device")
        dpg.add_text("[Info] Disconnected\n\n", parent="log_window_uut")


# -----------------
# Command & Injection Logic (Sends to ser_main)
# -----------------
def toggle_injection_fields(sender, app_data):
    if app_data == "Inject":
        dpg.configure_item("injection_params_group", show=True)
    else:
        dpg.configure_item("injection_params_group", show=False)


def update_dynamic_fields(sender, app_data):
    if app_data == "Byte Drop":
        dpg.configure_item("byte_drop_group", show=True)
        dpg.configure_item("xor_mask_group", show=False)
    elif app_data == "Bit Flip":
        dpg.configure_item("byte_drop_group", show=False)
        dpg.configure_item("xor_mask_group", show=True)


def send_command_callback():
    global ser_main

    # Log to UUT window
    log_tag = "log_window_uut"

    if ser_main is None and not running:
        dpg.add_text("[Command] Error: Device Not connected\n\n", parent=log_tag)
        return

    try:
        main_command = _ui_get("main_command_dropdown", "Ping")
        seq_id = int(time.time() * 1000) % 65535

        message = uart_data_pb2.DsiCommand()
        message.proto_version = 1
        message.id = seq_id

        if main_command == "Ping":
            message.cmd = uart_data_pb2.CommandType.CMD_PING
            dpg.add_text(f"[TX] Ping (id={seq_id})\n\n", parent=log_tag)

        elif main_command == "Abort":
            message.cmd = uart_data_pb2.CommandType.CMD_ABORT
            dpg.add_text(f"[TX] Abort (id={seq_id})\n\n", parent=log_tag)

        elif main_command == "Inject":
            message.cmd = uart_data_pb2.CommandType.CMD_INJECT
            inj_type = _ui_get("injection_type_dropdown", "Byte Drop")

            start_offset = _ui_get("inject_offset", 0)
            length = _ui_get("inject_length", 1)
            duration = _ui_get("inject_duration", 0)
            message.duration_ms = duration

            if inj_type == "Byte Drop":
                message.inj_type = uart_data_pb2.InjectionType.INJ_BYTE_DROP
                message.byte_drop.start_offset = start_offset
                message.byte_drop.length = length
                pattern_str = _ui_get("inject_drop_pattern", "")

                if not pattern_str:
                    dpg.add_text("[Error] Pattern cannot be empty\n\n", parent=log_tag)
                    return

                message.byte_drop.payload = pattern_str
                dpg.add_text(
                    f"[TX] Inject ByteDrop (off={start_offset}, len={length}, pattern='{pattern_str}')\n\n",
                    parent=log_tag,
                )

            elif inj_type == "Bit Flip":
                message.inj_type = uart_data_pb2.InjectionType.INJ_BIT_FLIP
                message.bit_flip.every_n_p = start_offset
                message.bit_flip.bits_drop = length
                mode = dpg.get_value("bitflip_mode_dropdown")

                if mode == "RANDOM":
                    message.bit_flip.mode = uart_data_pb2.BitFlipMode.RANDOM
                else:
                    message.bit_flip.mode = uart_data_pb2.BitFlipMode.PERIODIC

                pattern_str = dpg.get_value("inject_xor_mask")
                if not pattern_str:
                    dpg.add_text(
                        "[Error] Bit Flip Pattern cannot be empty\n\n", parent=log_tag
                    )
                    return

                message.bit_flip.payload = pattern_str
                dpg.add_text(
                    f"[TX] Inject BitFlip (every_n={start_offset}, random_n={length}, mode={mode}, pattern='{pattern_str}')\n\n",
                    parent=log_tag,
                )

        payload = message.SerializeToString()
        frame = struct.pack("<H", len(payload)) + payload

        if ser_main and ser_main.is_open:
            ser_main.write(frame)
            time.sleep(0.05)
            ser_main.flush()
        else:
            dpg.add_text(f"[Sim TX] {frame.hex(' ')}\n\n", parent=log_tag)
            dpg.set_y_scroll(log_tag, -1)

    except Exception as e:
        dpg.add_text(f"[Error] {e}\n\n", parent=log_tag)


# -----------------
# Helpers
# -----------------
def get_ports():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return ports + ["Simulated Device"] if ports else ["Simulated Device"]


def _ui_get(tag, default):
    try:
        return dpg.get_value(tag)
    except:
        return default


# -----------------
# GUI Setup
# -----------------
dpg.create_context()
dpg.create_viewport(title="NextFault Dashboard", width=1100, height=700)

with dpg.window(label="Dashboard", width=1920, height=1080, pos=(0, 0)):

    # --- SINGLE CONNECTION ROW ---
    with dpg.group(horizontal=True):
        dpg.add_text("Device Connection (UUT)", color=(100, 200, 255))
        with dpg.group(horizontal=True):
            dpg.add_combo(
                get_ports(), tag="main_port", width=150, default_value="Select Port"
            )
            dpg.add_text("Baud:")
            dpg.add_combo(
                ("9600", "57600", "115200"),
                tag="main_baud",
                width=80,
                default_value="9600",
            )
            dpg.add_button(
                label="Connect Device", tag="btn_connect", callback=toggle_connection
            )
        dpg.add_text("Disconnected", tag="conn_status", color=(200, 50, 50))

    dpg.add_separator()
    dpg.add_spacer(height=5)

    # --- COMMAND & INJECTION ---
    dpg.add_text("Injection Control", color=(255, 200, 80))
    with dpg.group(horizontal=True):
        dpg.add_text("Command:")
        dpg.add_combo(
            items=["Ping", "Abort", "Inject"],
            tag="main_command_dropdown",
            default_value="Ping",
            width=120,
            callback=toggle_injection_fields,
        )
        dpg.add_button(label="SEND", width=100, callback=send_command_callback)
        dpg.add_spacer(width=20)
        dpg.add_progress_bar(
            tag="progress_bar", default_value=0.0, width=300, overlay="Device Progress"
        )

    with dpg.group(tag="injection_params_group", show=False):
        dpg.add_spacer(height=5)
        with dpg.group(horizontal=True):
            dpg.add_text("Type:")
            dpg.add_combo(
                items=["Byte Drop", "Bit Flip"],
                tag="injection_type_dropdown",
                default_value="Byte Drop",
                width=120,
                callback=update_dynamic_fields,
            )
            dpg.add_text("Offset:")
            dpg.add_input_int(
                tag="inject_offset", width=80, min_value=0, default_value=0
            )
            dpg.add_text("Length:")
            dpg.add_input_int(
                tag="inject_length", width=80, min_value=1, default_value=1
            )
            dpg.add_text("Duration(ms):")
            dpg.add_input_int(
                tag="inject_duration", width=80, min_value=0, default_value=0
            )

            with dpg.group(tag="byte_drop_group", show=True, horizontal=True):
                dpg.add_text("Pattern:", color=(255, 200, 100))
                dpg.add_input_text(
                    tag="inject_drop_pattern",
                    width=120,
                    default_value="",
                    hint="Target String",
                )

            with dpg.group(tag="xor_mask_group", show=False, horizontal=True):
                dpg.add_text("Pattern:", color=(255, 100, 100))
                dpg.add_input_text(
                    tag="inject_xor_mask", width=100, default_value="", hint="String"
                )
                dpg.add_spacer(width=10)
                dpg.add_combo(
                    items=["RANDOM", "PERIODIC"],
                    default_value="RANDOM",
                    tag="bitflip_mode_dropdown",
                    width=100,
                )

    dpg.add_separator()
    dpg.add_spacer(height=5)

    # --- DATA CAPTURE (SINGLE) ---
    with dpg.group(horizontal=True):
        dpg.add_text("Data Capture", color=(100, 100, 255))
        dpg.add_text("Name:")
        dpg.add_input_text(
            tag="run_name", width=120, default_value="uut_log", hint="Filename"
        )
        dpg.add_text("Time(s):")
        dpg.add_input_int(tag="duration", width=80, default_value=5, min_value=1)
        dpg.add_button(label="Start Capture", callback=start_capture_callback)

    dpg.add_separator()
    dpg.add_spacer(height=5)

    # --- SINGLE MONITOR ON RIGHT ---
    with dpg.group(horizontal=True):
        # We push it to the right by using a spacer or just letting it fill
        # If you want it specifically "on the right" visually but taking up space:

        with dpg.child_window(width=520, height=-1, border=True):
            dpg.add_text("--- UUT Serial Log ---", color=(100, 255, 100))
            dpg.add_child_window(tag="log_window_uut", autosize_x=True, autosize_y=True)

dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()
