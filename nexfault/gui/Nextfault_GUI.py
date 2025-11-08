import time
import threading
import serial
import serial.tools.list_ports
import dearpygui.dearpygui as dpg
import struct  
import uart_data_pb2  

from nexfault.core.parser import SerialDevice
from nexfault.core.logger import LogFile

ser = None   # global serial object
running = False  # background reader flag


# -----------------
# Serial Reader Loop
# -----------------
def reader_loop(simulated=False):
    global ser, running
    progress = 0.0

    while running:
        if simulated:
            time.sleep(1)
            # Fake messages
            msg = f"[Simulated] Heartbeat {time.strftime('%H:%M:%S')}"
            dpg.add_text(msg, parent="log_window")
            dpg.set_y_scroll("log_window", -1)

            # Fake progress
            progress = min(progress + 0.1, 1.0)
            dpg.set_value("progress_bar", progress)

            if progress >= 1.0:
                dpg.add_text("[Simulated] Task Complete!", parent="log_window")
                dpg.set_y_scroll("log_window", -1)
                running = False
        else:
            try:
                if ser and ser.in_waiting:
                    line = ser.readline().decode(errors="ignore").strip()
                    if line:
                        dpg.add_text(line, parent="log_window")
                        dpg.set_y_scroll("log_window", -1)

                        # Parse MCU progress messages (format: PROG:0.42)
                        if line.startswith("PROG:"):
                            try:
                                value = float(line.split(":")[1])
                                dpg.set_value("progress_bar", min(max(value, 0.0), 1.0))
                            except ValueError:
                                pass
            except Exception as e:
                dpg.add_text(f"[Error] {e}", parent="log_window")
                dpg.set_y_scroll("log_window", -1)
                break
        time.sleep(0.1)


# -----------------
# Serial Handshake
# -----------------
def run_handshake(simulated=False):
    global ser, running

    if simulated:
        time.sleep(0.5)
        dpg.set_value("info_text", "FW:Sim1.0 • BUS:Virtual • FC:99")
        dpg.set_value("status_text", "Connected (Simulated)")
        dpg.configure_item("status_text", color=(0, 200, 0))
        running = True
        threading.Thread(target=reader_loop, args=(True,), daemon=True).start()
        return

    if ser is None or not ser.is_open:
        dpg.set_value("status_text", "Disconnected")
        dpg.configure_item("status_text", color=(200, 0, 0))
        return

    try:
        ser.write(b"HELLO\n")
        time.sleep(0.5)
        if ser.in_waiting:
            response = ser.readline().decode(errors="ignore").strip()
            dpg.set_value("info_text", response)
            dpg.set_value("status_text", "Connected")
            dpg.configure_item("status_text", color=(0, 200, 0))
            running = True
            threading.Thread(target=reader_loop, daemon=True).start()
        else:
            dpg.set_value("info_text", "No response")
            dpg.set_value("status_text", "Disconnected")
            dpg.configure_item("status_text", color=(200, 0, 0))
    except Exception as e:
        dpg.set_value("info_text", f"Error: {e}")
        dpg.set_value("status_text", "Disconnected")
        dpg.configure_item("status_text", color=(200, 0, 0))


# -----------------
# Connect Function
# -----------------
def connect_callback():
    global ser, running

    running = False  # stop any previous reader loop

    port = dpg.get_value("port_dropdown")
    baud = int(dpg.get_value("baud_dropdown"))

    # clear log
    dpg.delete_item("log_window", children_only=True)

    # reset progress bar
    dpg.set_value("progress_bar", 0.0)

    if port == "Simulated Device":
        dpg.set_value("status_text", "Connecting...")
        dpg.configure_item("status_text", color=(200, 200, 0))
        threading.Thread(target=run_handshake, args=(True,), daemon=True).start()
        return

    try:
        ser = serial.Serial(port, baud, timeout=1)
        dpg.set_value("status_text", "Connecting...")
        dpg.configure_item("status_text", color=(200, 200, 0))
        threading.Thread(target=run_handshake, daemon=True).start()
    except Exception as e:
        dpg.set_value("info_text", f"Error: {e}")
        dpg.set_value("status_text", "Disconnected")
        dpg.configure_item("status_text", color=(200, 0, 0))

# -----------------
# Capture & Save
# -----------------
def _make_row(chunk: bytes, ts: str):
    return [ts, len(chunk), chunk.hex(" "), chunk.decode("utf-8", "ignore").strip(), chunk]

def _ui_get(tag, default):
    try:
        return dpg.get_value(tag)
    except Exception:
        return default

def _capture_backend(duration_s: int, run_name: str):
    """Pause reader, capture for N seconds, save CSV/JSON, resume reader."""
    global ser, running
    try:
        # stop background loop
        running = False
        time.sleep(0.2)

        ui_port = _ui_get("port_dropdown", "Simulated Device")
        simulated = str(ui_port).strip().lower().startswith("simulated")
        baud = int(_ui_get("baud_dropdown", "115200") or "115200")

        dpg.add_text(f"[Capture] {('Simulated' if simulated else 'Real')} • {duration_s}s • run={run_name}", parent="log_window")
        dpg.set_y_scroll("log_window", -1)

        rows = []

        if simulated:
            # use backend to generate fake rows (no hardware)
            dev = SerialDevice("FAKE", baud)
            dev.connect()
            if not dev.is_connected():
                dpg.add_text("[Capture] Simulated device failed to connect", parent="log_window")
                return
            rows = dev.read_buffer(duration_s)
            dev.disconnect()
        else:
            # read directly from the already-open 'ser' so we don't fight the port
            if ser is None or not ser.is_open:
                dpg.add_text("[Capture] Port not open", parent="log_window")
                return
            old_timeout = ser.timeout
            ser.timeout = 0.1
            end = time.time() + duration_s
            from datetime import datetime
            try:
                while time.time() < end:
                    chunk = ser.read(256)
                    if chunk:
                        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                        rows.append(_make_row(chunk, ts))
            finally:
                ser.timeout = old_timeout

        # save logs
        lf = LogFile((run_name or "run").strip() or "run")
        headers = ["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)"]
        csv_path = lf.log_csv(headers, rows)
        json_path = lf.log_json(headers, rows)

        dpg.add_text(f"[Capture] Saved CSV: {csv_path}", parent="log_window")
        dpg.add_text(f"[Capture] Saved JSON: {json_path}", parent="log_window")
        dpg.set_y_scroll("log_window", -1)

    except Exception as e:
        dpg.add_text(f"[Capture][Error] {e}", parent="log_window")
        dpg.set_y_scroll("log_window", -1)
    finally:
        # resume reader loop if connected
        sim_again = str(_ui_get("port_dropdown", "")).strip().lower().startswith("simulated")
        running = True
        threading.Thread(target=reader_loop, args=(sim_again,), daemon=True).start()

def start_capture_callback():
    # robust reads of UI fields
    run_name = (_ui_get("run_name_input", "run") or "run").strip()
    dur_val  = _ui_get("duration_input", 10)
    try:
        duration_s = int(str(dur_val)) if str(dur_val).strip() else 10
    except Exception:
        duration_s = 10

    dpg.add_text(f"[UI] Capture clicked (dur={duration_s}, run={run_name})", parent="log_window")
    dpg.set_y_scroll("log_window", -1)

    threading.Thread(target=_capture_backend, args=(duration_s, run_name), daemon=True).start()
            
# -----------------
# Command Callbacks  
# -----------------
def toggle_injection_fields(sender, app_data):
    """
    Shows or hides the injection parameter fields based
    on the main command dropdown selection.
    """
    if app_data == "Inject":
        dpg.configure_item("injection_params_group", show=True)
    else:
        dpg.configure_item("injection_params_group", show=False)

def send_command_callback():
    """
    Reads the selected command and parameters from the GUI,
    builds the appropriate Protobuf message, and sends it.
    """
    global ser

    if ser is None or not ser.is_open:
        dpg.add_text("[Command] Error: Not connected", parent="log_window")
        dpg.set_y_scroll("log_window", -1)
        return

    try:
        # Get values from GUI
        main_command = _ui_get("main_command_dropdown", "Ping")
        seq_id = int(time.time() * 1000) % 65535 # Use a simple unique-ish ID

        # 1. Create the base Protobuf message
        message = uart_data_pb2.DsiCommand()
        message.proto_version = 1
        message.id = seq_id

        # 2. Populate message based on the selected command
        if main_command == "Ping":
            message.cmd = uart_data_pb2.CommandType.CMD_PING
            dpg.add_text(f"[Command] Sending Ping (id={seq_id})", parent="log_window")
        
        elif main_command == "Abort":
            message.cmd = uart_data_pb2.CommandType.CMD_ABORT
            dpg.add_text(f"[Command] Sending Abort (id={seq_id})", parent="log_window")
            
        elif main_command == "Inject":
            message.cmd = uart_data_pb2.CommandType.CMD_INJECT
            
            # Get injection-specific parameters
            inj_type = _ui_get("injection_type_dropdown", "Byte Drop")
            
            if inj_type == "Byte Drop":
                start_offset = _ui_get("inject_offset", 0)
                length = _ui_get("inject_length", 1)
                duration = _ui_get("inject_duration", 0)

                message.inj_type = uart_data_pb2.InjectionType.INJ_BYTE_DROP
                message.duration_ms = duration
                message.byte_drop.start_offset = start_offset
                message.byte_drop.length = length
                
                dpg.add_text(f"[Command] Sending Inject (Byte Drop, id={seq_id}, offset={start_offset}, len={length}, dur={duration}ms)", parent="log_window")
            
            # Add 'elif inj_type == "Bit Flip":' here later
            
            else:
                dpg.add_text(f"[Command] Error: Unknown injection type '{inj_type}'", parent="log_window")
                return
        
        else:
            dpg.add_text(f"[Command] Error: Unknown command '{main_command}'", parent="log_window")
            return

        # 3. Serialize and frame the message
        payload = message.SerializeToString()
        frame = struct.pack("<H", len(payload)) + payload

        # 4. Send the message
        ser.write(frame)
        ser.flush()

        dpg.add_text(f"[Command] Sent {len(frame)} bytes: {frame.hex(' ')}", parent="log_window")
        dpg.set_y_scroll("log_window", -1)

    except Exception as e:
        dpg.add_text(f"[Command][Error] {e}", parent="log_window")
        dpg.set_y_scroll("log_window", -1)
            
# -----------------
# Populate Ports
# -----------------
def get_ports():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return ports + ["Simulated Device"] if ports else ["Simulated Device"]


# -----------------
# GUI Setup
# -----------------
dpg.create_context()
dpg.create_viewport(title="Serial Monitor", width=600, height=450)

with dpg.window(label="Serial Monitor", width=1920, height=1080, pos=(10, 10)):
    dpg.add_text("Connection Settings", color=(150, 200, 255))
    dpg.add_separator()

    with dpg.group(horizontal=True):
        dpg.add_text("Port:")
        dpg.add_combo(get_ports(), tag="port_dropdown", width=150)

        dpg.add_text("Baud:")
        dpg.add_combo(("9600", "57600", "115200"), default_value="9600", tag="baud_dropdown", width=100)

        dpg.add_button(label="Connect", callback=connect_callback)
        dpg.add_spacer(width=12)
        dpg.add_text("Run:")
        dpg.add_input_text(hint="run name", tag="run_name_input", width=150, default_value="run")
        dpg.add_text("Duration:")
        dpg.add_input_int(tag="duration_input", width=70, min_value=1, default_value=10)
        dpg.add_button(label="Capture & Save", width=140, callback=start_capture_callback)

    # --- MODIFIED: ADDED NEW COMMAND SECTION ---
    dpg.add_spacer(height=5)
    dpg.add_text("Command Control", color=(150, 200, 255))
    dpg.add_separator()
    
    with dpg.group(horizontal=True):
        dpg.add_text("Command:")
        dpg.add_combo(
            items=["Ping", "Abort", "Inject"],
            tag="main_command_dropdown",
            default_value="Ping",
            width=150,
            callback=toggle_injection_fields  # This callback shows/hides the section below
        )
        dpg.add_button(label="Send Command", width=140, callback=send_command_callback)

    # This group is hidden by default and shown by the callback
    with dpg.group(horizontal=True, tag="injection_params_group", show=False):
        dpg.add_text("Inject Type:")
        dpg.add_combo(
            items=["Byte Drop"], # Add "Bit Flip" here when ready
            tag="injection_type_dropdown",
            default_value="Byte Drop",
            width=150
        )
        dpg.add_text("Offset:")
        dpg.add_input_int(tag="inject_offset", width=70, min_value=0, default_value=0)
        dpg.add_text("Length:")
        dpg.add_input_int(tag="inject_length", width=70, min_value=1, default_value=1)
        dpg.add_text("Duration (ms):")
        dpg.add_input_int(tag="inject_duration", width=70, min_value=0, default_value=0,
                          tooltip="0 = until next command")
    # --- END OF MODIFIED SECTION ---

    dpg.add_spacer(height=10)
    dpg.add_separator()

    dpg.add_text("fw_ver • bus • features_count", tag="info_text")
    dpg.add_text("Disconnected", tag="status_text", color=(200, 0, 0))

    dpg.add_spacer(height=10)
    dpg.add_separator()
    dpg.add_text("Progress", color=(150, 200, 255))
    dpg.add_progress_bar(tag="progress_bar", default_value=0.0, width=-1)

    dpg.add_spacer(height=10)
    dpg.add_separator()
    dpg.add_text("Serial Log", color=(150, 200, 255))
    dpg.add_child_window(tag="log_window", autosize_x=True, autosize_y=True, border=True)

dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()