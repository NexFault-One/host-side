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
ser_dsi = None
ser_uut = None
running_dsi = False
running_uut = False

# -----------------
# Serial Reader Loops
# ----------------- 
def reader_loop_dsi(simulated=False):
    """Background loop for DSI (Control Device)"""
    global ser_dsi, running_dsi
    
    while running_dsi:
        if simulated:
            time.sleep(1)
            msg = f"[DSI Sim] Heartbeat {time.strftime('%H:%M:%S')}\n\n"
            dpg.add_text(msg, parent="log_window_dsi")
            dpg.set_y_scroll("log_window_dsi", -1)
        else: 
            try:
                if ser_dsi and ser_dsi.in_waiting:
                    line = ser_dsi.readline().decode(errors="ignore").strip()
                    if line:
                        dpg.add_text(f"[RX] {line}\n\n", parent="log_window_dsi")
                        dpg.set_y_scroll("log_window_dsi", -1)
                        if line.startswith("PROG:"):
                            try:
                                value = float(line.split(":")[1])
                                dpg.set_value("progress_bar", min(max(value, 0.0), 1.0))
                            except ValueError:
                                pass
            except Exception as e:
                dpg.add_text(f"[DSI Error] {e}\n\n", parent="log_window_dsi")
                break
        time.sleep(0.05)

def reader_loop_uut(simulated=False):
    """Background loop for UUT (Unit Under Test) - Monitor Only"""
    global ser_uut, running_uut
    
    while running_uut:
        if simulated:
            time.sleep(1.5)
            msg = f"[UUT Sim] Output {time.strftime('%H:%M:%S')}\n\n"
            dpg.add_text(msg, parent="log_window_uut")
            dpg.set_y_scroll("log_window_uut", -1)
        else:
            try:
                if ser_uut and ser_uut.in_waiting:
                    line = ser_uut.readline().decode(errors="ignore").strip()
                    if line:
                        # --- UPDATED: Added [RX] prefix and \n\n spacing to match DSI ---
                        dpg.add_text(f"[RX] {line}\n\n", parent="log_window_uut")
                        dpg.set_y_scroll("log_window_uut", -1)
            except Exception as e:
                dpg.add_text(f"[UUT Error] {e}\n\n", parent="log_window_uut")
                break
        time.sleep(0.05)

# -----------------
# Capture & Save Backend
# -----------------
def _make_row(chunk: bytes, ts: str):
    """Helper to format log rows"""
    return [ts, len(chunk), chunk.hex(" "), chunk.decode("utf-8", "ignore").strip(), chunk]

def _capture_backend(duration_s: int, run_name: str, target: str):
    """
    Generic capture backend.
    target: "DSI" or "UUT"
    """
    global ser_dsi, ser_uut, running_dsi, running_uut
    
    # Configuration Map
    if target == "DSI":
        ser_target = ser_dsi
        port_tag = "dsi_port"
        log_window = "log_window_dsi"
        sim_baud = 9600
        running_dsi = False
    else: # UUT
        ser_target = ser_uut
        port_tag = "uut_port"
        log_window = "log_window_uut"
        sim_baud = 115200
        running_uut = False

    time.sleep(0.2) # Allow thread to exit

    try:
        port = dpg.get_value(port_tag)
        simulated = str(port).strip().lower().startswith("simulated")

        dpg.add_text(f"[Capture] Starting {duration_s}s capture on {target}...\n\n", parent=log_window)
        dpg.set_y_scroll(log_window, -1)

        rows = []
        
        if simulated:
            dev = SerialDevice("FAKE", sim_baud)
            dev.connect()
            rows = dev.read_buffer(duration_s)
            dev.disconnect()
        else:
            if ser_target is None or not ser_target.is_open:
                dpg.add_text(f"[Capture] Error: {target} Port not open\n\n", parent=log_window)
                return

            end = time.time() + duration_s
            old_timeout = ser_target.timeout
            ser_target.timeout = 0.1
            
            try:
                while time.time() < end:
                    if ser_target.in_waiting:
                        chunk = ser_target.read(ser_target.in_waiting or 1)
                        if chunk:
                            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            rows.append(_make_row(chunk, ts))
            finally:
                ser_target.timeout = old_timeout

        if rows:
            full_name = f"{run_name}_{target}"
            lf = LogFile((full_name).strip())
            headers = ["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)"]
            
            csv_path = lf.log_csv(headers, rows)
            json_path = lf.log_json(headers, rows)

            dpg.add_text(f"[Capture] Saved CSV: {csv_path}\n", parent=log_window)
            dpg.add_text(f"[Capture] Saved JSON: {json_path}\n\n", parent=log_window)
        else:
            dpg.add_text(f"[Capture] No data received from {target}.\n\n", parent=log_window)

    except Exception as e:
        dpg.add_text(f"[Capture Error] {e}\n\n", parent=log_window)
    
    finally:
        sim_again = str(dpg.get_value(port_tag)).strip().lower().startswith("simulated")
        
        if target == "DSI":
            if (ser_dsi and ser_dsi.is_open) or sim_again:
                running_dsi = True
                threading.Thread(target=reader_loop_dsi, args=(sim_again,), daemon=True).start()
            dpg.set_y_scroll("log_window_dsi", -1)
        else:
            if (ser_uut and ser_uut.is_open) or sim_again:
                running_uut = True
                threading.Thread(target=reader_loop_uut, args=(sim_again,), daemon=True).start()
            dpg.set_y_scroll("log_window_uut", -1)

def start_capture_dsi_callback():
    run_name = _ui_get("run_name_dsi", "dsi_run")
    dur_val = _ui_get("duration_dsi", 5)
    threading.Thread(target=_capture_backend, args=(dur_val, run_name, "DSI"), daemon=True).start()

def start_capture_uut_callback():
    run_name = _ui_get("run_name_uut", "uut_run")
    dur_val = _ui_get("duration_uut", 5)
    threading.Thread(target=_capture_backend, args=(dur_val, run_name, "UUT"), daemon=True).start()

# -----------------
# Toggle Connection Callbacks
# -----------------
def toggle_dsi_connection():
    global ser_dsi, running_dsi
    current_label = dpg.get_item_label("btn_connect_dsi")
    
    if current_label == "Connect DSI":
        port = dpg.get_value("dsi_port")
        baud = int(dpg.get_value("dsi_baud"))
        dpg.delete_item("log_window_dsi", children_only=True)

        if port == "Simulated Device":
            dpg.set_value("dsi_status", "Connected (Sim)")
            dpg.configure_item("dsi_status", color=(0, 200, 0))
            dpg.configure_item("btn_connect_dsi", label="Disconnect DSI")
            running_dsi = True
            threading.Thread(target=reader_loop_dsi, args=(True,), daemon=True).start()
            return

        try:
            ser_dsi = serial.Serial(port, baud, timeout=1)
            ser_dsi.dtr = False 
            ser_dsi.rts = False
            dpg.set_value("dsi_status", "Connected")
            dpg.configure_item("dsi_status", color=(0, 200, 0))
            dpg.configure_item("btn_connect_dsi", label="Disconnect DSI")
            running_dsi = True
            threading.Thread(target=reader_loop_dsi, daemon=True).start()
        except Exception as e:
            dpg.set_value("dsi_status", "Error")
            dpg.configure_item("dsi_status", color=(200, 0, 0))
            dpg.add_text(f"[Error] {e}\n\n", parent="log_window_dsi")

    else:
        running_dsi = False
        time.sleep(0.1)
        try:
            if ser_dsi and ser_dsi.is_open:
                ser_dsi.close()
        except:
            pass
        ser_dsi = None
        dpg.set_value("dsi_status", "Disconnected")
        dpg.configure_item("dsi_status", color=(200, 50, 50))
        dpg.configure_item("btn_connect_dsi", label="Connect DSI")
        dpg.add_text("[Info] Disconnected\n\n", parent="log_window_dsi")


def toggle_uut_connection():
    global ser_uut, running_uut
    current_label = dpg.get_item_label("btn_connect_uut")
    
    if current_label == "Connect UUT":
        port = dpg.get_value("uut_port")
        baud = 115200
        dpg.delete_item("log_window_uut", children_only=True)

        if port == "Simulated Device":
            dpg.set_value("uut_status", "Connected (Sim)")
            dpg.configure_item("uut_status", color=(0, 200, 0))
            dpg.configure_item("btn_connect_uut", label="Disconnect UUT")
            running_uut = True
            threading.Thread(target=reader_loop_uut, args=(True,), daemon=True).start()
            return

        try:
            ser_uut = serial.Serial(port, baud, timeout=1)
            ser_uut.dtr = False
            ser_uut.rts = False
            dpg.set_value("uut_status", "Connected")
            dpg.configure_item("uut_status", color=(0, 200, 0))
            dpg.configure_item("btn_connect_uut", label="Disconnect UUT")
            running_uut = True
            threading.Thread(target=reader_loop_uut, daemon=True).start()
        except Exception as e:
            dpg.set_value("uut_status", "Error")
            dpg.configure_item("uut_status", color=(200, 0, 0))
            dpg.add_text(f"[Error] {e}\n\n", parent="log_window_uut")

    else:
        running_uut = False
        time.sleep(0.1)
        try:
            if ser_uut and ser_uut.is_open:
                ser_uut.close()
        except:
            pass
        ser_uut = None
        dpg.set_value("uut_status", "Disconnected")
        dpg.configure_item("uut_status", color=(200, 50, 50))
        dpg.configure_item("btn_connect_uut", label="Connect UUT")
        dpg.add_text("[Info] Disconnected\n\n", parent="log_window_uut")


# -----------------
# Command & Injection Logic
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
    global ser_dsi
    if ser_dsi is None and not running_dsi:
        dpg.add_text("[Command] Error: DSI Not connected\n\n", parent="log_window_dsi")
        return

    try:
        main_command = _ui_get("main_command_dropdown", "Ping")
        seq_id = int(time.time() * 1000) % 65535 

        message = uart_data_pb2.DsiCommand()
        message.proto_version = 1
        message.id = seq_id

        if main_command == "Ping":
            message.cmd = uart_data_pb2.CommandType.CMD_PING
            dpg.add_text(f"[TX] Ping (id={seq_id})\n\n", parent="log_window_dsi")
        
        elif main_command == "Abort":
            message.cmd = uart_data_pb2.CommandType.CMD_ABORT
            dpg.add_text(f"[TX] Abort (id={seq_id})\n\n", parent="log_window_dsi")
            
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
                dpg.add_text(f"[TX] Inject ByteDrop (off={start_offset}, len={length}, pattern='{pattern_str}')\n\n", parent="log_window_dsi")

            elif inj_type == "Bit Flip":
                message.inj_type = uart_data_pb2.InjectionType.INJ_BIT_FLIP
                message.bit_flip.start_offset = start_offset
                message.bit_flip.length = length
                
                mask_str = _ui_get("inject_xor_mask", "FF")
                try:
                    clean_mask = mask_str.replace(" ", "").replace("0x", "")
                    message.bit_flip.xor_mask = bytes.fromhex(clean_mask)
                except ValueError:
                    dpg.add_text("[Error] Invalid XOR Mask Hex String\n\n", parent="log_window_dsi")
                    return

                dpg.add_text(f"[TX] Inject BitFlip (off={start_offset}, len={length}, mask={clean_mask})\n\n", parent="log_window_dsi")

        payload = message.SerializeToString()
        frame = struct.pack("<H", len(payload)) + payload

        if ser_dsi and ser_dsi.is_open:
            ser_dsi.write(frame)
            ser_dsi.flush()
        else:
            dpg.add_text(f"[Sim TX] {frame.hex(' ')}\n\n", parent="log_window_dsi")
            dpg.set_y_scroll("log_window_dsi", -1)

    except Exception as e:
        dpg.add_text(f"[Error] {e}\n\n", parent="log_window_dsi")

# -----------------
# Helpers
# -----------------
def get_ports():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return ports + ["Simulated Device"] if ports else ["Simulated Device"]

def _ui_get(tag, default):
    try: return dpg.get_value(tag)
    except: return default

# -----------------
# GUI Setup
# -----------------
dpg.create_context()
dpg.create_viewport(title="NextFault Dashboard", width=1100, height=700)

with dpg.window(label="Dashboard", width=1920, height=1080, pos=(0, 0)):
    
    # --- TOP ROW: CONNECTIONS ---
    with dpg.group(horizontal=True):
        with dpg.group():
            dpg.add_text("DSI Connection (Control)", color=(100, 255, 100))
            with dpg.group(horizontal=True):
                dpg.add_combo(get_ports(), tag="dsi_port", width=150, default_value="Select Port")
                dpg.add_text("Baud:")
                dpg.add_combo(("9600", "57600", "115200"), tag="dsi_baud", width=80, default_value="9600")
                dpg.add_button(label="Connect DSI", tag="btn_connect_dsi", callback=toggle_dsi_connection)
            dpg.add_text("Disconnected", tag="dsi_status", color=(200, 50, 50))
        dpg.add_spacer(width=50)
        with dpg.group():
            dpg.add_text("UUT Connection (Monitor)", color=(100, 100, 255))
            with dpg.group(horizontal=True):
                dpg.add_combo(get_ports(), tag="uut_port", width=150, default_value="Select Port")
                dpg.add_button(label="Connect UUT", tag="btn_connect_uut", callback=toggle_uut_connection)
            dpg.add_text("Disconnected", tag="uut_status", color=(200, 50, 50))

    dpg.add_separator()
    dpg.add_spacer(height=5)

    # --- COMMAND & INJECTION ---
    dpg.add_text("Injection Control", color=(255, 200, 80))
    with dpg.group(horizontal=True):
        dpg.add_text("Command:")
        dpg.add_combo(items=["Ping", "Abort", "Inject"], tag="main_command_dropdown", default_value="Ping", width=120, callback=toggle_injection_fields)
        dpg.add_button(label="SEND", width=100, callback=send_command_callback)
        dpg.add_spacer(width=20)
        dpg.add_progress_bar(tag="progress_bar", default_value=0.0, width=300, overlay="Device Progress")

    with dpg.group(tag="injection_params_group", show=False):
        dpg.add_spacer(height=5)
        with dpg.group(horizontal=True):
            dpg.add_text("Type:")
            dpg.add_combo(items=["Byte Drop", "Bit Flip"], tag="injection_type_dropdown", default_value="Byte Drop", width=120, callback=update_dynamic_fields)
            dpg.add_text("Offset:")
            dpg.add_input_int(tag="inject_offset", width=80, min_value=0, default_value=0)
            dpg.add_text("Length:")
            dpg.add_input_int(tag="inject_length", width=80, min_value=1, default_value=1)
            dpg.add_text("Duration(ms):")
            dpg.add_input_int(tag="inject_duration", width=80, min_value=0, default_value=0)
            
            with dpg.group(tag="byte_drop_group", show=True, horizontal=True):
                dpg.add_text("Pattern (String):", color=(255, 200, 100))
                dpg.add_input_text(tag="inject_drop_pattern", width=120, default_value="", hint="Target String")

            with dpg.group(tag="xor_mask_group", show=False, horizontal=True):
                dpg.add_text("XOR Mask (Hex):", color=(255, 100, 100))
                dpg.add_input_text(tag="inject_xor_mask", width=100, default_value="FF", hint="e.g. FF AA")

    dpg.add_separator()
    dpg.add_spacer(height=5)

    # --- DATA CAPTURE SECTIONS ---
    with dpg.group(horizontal=True):
        # DSI Capture Group
        with dpg.group():
            dpg.add_text("Data Capture (DSI)", color=(100, 255, 100))
            with dpg.group(horizontal=True):
                dpg.add_text("Name:")
                dpg.add_input_text(tag="run_name_dsi", width=120, default_value="dsi_log", hint="Filename")
                dpg.add_text("Time(s):")
                dpg.add_input_int(tag="duration_dsi", width=80, default_value=5, min_value=1)
                dpg.add_button(label="Capture DSI", callback=start_capture_dsi_callback)

        dpg.add_spacer(width=50)

        # UUT Capture Group
        with dpg.group():
            dpg.add_text("Data Capture (UUT)", color=(100, 100, 255))
            with dpg.group(horizontal=True):
                dpg.add_text("Name:")
                dpg.add_input_text(tag="run_name_uut", width=120, default_value="uut_log", hint="Filename")
                dpg.add_text("Time(s):")
                dpg.add_input_int(tag="duration_uut", width=80, default_value=5, min_value=1)
                dpg.add_button(label="Capture UUT", callback=start_capture_uut_callback)

    dpg.add_separator()
    dpg.add_spacer(height=5)

    # --- SPLIT LOG MONITORS ---
    with dpg.group(horizontal=True):
        # Left: DSI Log (width=520)
        with dpg.child_window(width=520, height=-1, border=True):
            dpg.add_text("--- DSI Serial Log ---", color=(100, 255, 100))
            dpg.add_child_window(tag="log_window_dsi", autosize_x=True, autosize_y=True)

        # Right: UUT Log (width=520, matching DSI)
        with dpg.child_window(width=520, height=-1, border=True):
            dpg.add_text("--- UUT Serial Log ---", color=(100, 100, 255))
            dpg.add_child_window(tag="log_window_uut", autosize_x=True, autosize_y=True)

dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()