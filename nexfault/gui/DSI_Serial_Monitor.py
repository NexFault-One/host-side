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
running_dsi = False

# -----------------
# Serial Reader Loop
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

# -----------------
# Capture & Save Backend
# -----------------
def _make_row(chunk: bytes, ts: str):
    """Helper to format log rows"""
    return [ts, len(chunk), chunk.hex(" "), chunk.decode("utf-8", "ignore").strip(), chunk]

def _capture_backend(duration_s: int, run_name: str):
    """Pauses the live monitor to perform a high-speed capture on DSI"""
    global ser_dsi, running_dsi
    
    running_dsi = False
    time.sleep(0.2) 

    try:
        port = dpg.get_value("dsi_port")
        baud = int(dpg.get_value("dsi_baud"))
        simulated = str(port).strip().lower().startswith("simulated")

        dpg.add_text(f"[Capture] Starting {duration_s}s capture on DSI...\n\n", parent="log_window_dsi")
        dpg.set_y_scroll("log_window_dsi", -1)

        rows = []
        if simulated:
            dev = SerialDevice("FAKE", baud)
            dev.connect()
            rows = dev.read_buffer(duration_s)
            dev.disconnect()
        else:
            if ser_dsi is None or not ser_dsi.is_open:
                dpg.add_text(f"[Capture] Error: DSI Port not open\n\n", parent="log_window_dsi")
                return

            end = time.time() + duration_s
            old_timeout = ser_dsi.timeout
            ser_dsi.timeout = 0.1
            
            try:
                while time.time() < end:
                    if ser_dsi.in_waiting:
                        chunk = ser_dsi.read(ser_dsi.in_waiting or 1)
                        if chunk:
                            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            rows.append(_make_row(chunk, ts))
            finally:
                ser_dsi.timeout = old_timeout

        if rows:
            full_name = f"{run_name}_DSI"
            lf = LogFile((full_name).strip())
            headers = ["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)"]
            csv_path = lf.log_csv(headers, rows)
            json_path = lf.log_json(headers, rows)
            dpg.add_text(f"[Capture] Saved CSV: {csv_path}\n", parent="log_window_dsi")
            dpg.add_text(f"[Capture] Saved JSON: {json_path}\n\n", parent="log_window_dsi")
        else:
            dpg.add_text(f"[Capture] No data received from DSI.\n\n", parent="log_window_dsi")

    except Exception as e:
        dpg.add_text(f"[Capture Error] {e}\n\n", parent="log_window_dsi")
    finally:
        sim_again = str(dpg.get_value("dsi_port")).strip().lower().startswith("simulated")
        if (ser_dsi and ser_dsi.is_open) or sim_again:
            running_dsi = True
            threading.Thread(target=reader_loop_dsi, args=(sim_again,), daemon=True).start()
        dpg.set_y_scroll("log_window_dsi", -1)

def start_capture_dsi_callback():
    run_name = dpg.get_value("run_name_dsi")
    dur_val = dpg.get_value("duration_dsi")
    threading.Thread(target=_capture_backend, args=(dur_val, run_name), daemon=True).start()

# -----------------
# Callbacks
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
        except: pass
        ser_dsi = None
        dpg.set_value("dsi_status", "Disconnected")
        dpg.configure_item("dsi_status", color=(200, 50, 50))
        dpg.configure_item("btn_connect_dsi", label="Connect DSI")
        dpg.add_text("[Info] Disconnected\n\n", parent="log_window_dsi")

def toggle_injection_fields(sender, app_data):
    if app_data == "Inject":
        dpg.configure_item("injection_params_group", show=True)
    else:
        dpg.configure_item("injection_params_group", show=False)

def update_dynamic_fields(sender, app_data):
    dpg.configure_item("byte_drop_group", show=False)
    dpg.configure_item("xor_mask_group", show=False)
    dpg.configure_item("phantom_byte_group", show=False)

    if app_data == "Byte Drop":
        dpg.configure_item("byte_drop_group", show=True)
    elif app_data == "Bit Flip":
        dpg.configure_item("xor_mask_group", show=True)
    elif app_data == "Phantom Byte":
        dpg.configure_item("phantom_byte_group", show=True)

def send_command_callback():
    global ser_dsi
    if ser_dsi is None and not running_dsi:
        dpg.add_text("[Command] Error: DSI Not connected\n\n", parent="log_window_dsi")
        return

    try:
        main_command = dpg.get_value("main_command_dropdown")
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
            inj_type = dpg.get_value("injection_type_dropdown")
            start_offset = dpg.get_value("inject_offset")
            length = dpg.get_value("inject_length")
            duration = dpg.get_value("inject_duration")
            message.duration_ms = duration

            if inj_type == "Byte Drop":
                message.inj_type = uart_data_pb2.InjectionType.INJ_BYTE_DROP
                message.byte_drop.start_offset = start_offset
                message.byte_drop.length = length
                pattern_str = dpg.get_value("inject_drop_pattern")
                dpg.add_text(f"[TX] Inject ByteDrop (off={start_offset}, len={length})\n\n", parent="log_window_dsi")

            elif inj_type == "Bit Flip":
                message.inj_type = uart_data_pb2.InjectionType.INJ_BIT_FLIP
                message.bit_flip.start_offset = start_offset
                message.bit_flip.length = length
                mask_str = dpg.get_value("inject_xor_mask")
                try:
                    clean_mask = mask_str.replace(" ", "").replace("0x", "")
                    message.bit_flip.xor_mask = bytes.fromhex(clean_mask)
                except ValueError:
                    dpg.add_text("[Error] Invalid XOR Mask\n\n", parent="log_window_dsi")
                    return
                dpg.add_text(f"[TX] Inject BitFlip (off={start_offset}, len={length}, mask={clean_mask})\n\n", parent="log_window_dsi")

            elif inj_type == "Phantom Byte":
                message.inj_type = uart_data_pb2.InjectionType.INJ_PHANTOM_BYTE
                mode = dpg.get_value("phantom_mode")
                
                if mode == "MANUAL":
                    hex_val = dpg.get_value("phantom_val").replace("0x", "")
                    try:
                        val_int = int(hex_val, 16)
                        if not (0 <= val_int <= 255): raise ValueError
                        message.phantom.byte_val = val_int
                        message.phantom.random = False
                    except ValueError:
                        dpg.add_text("[Error] Phantom Byte must be 00-FF\n\n", parent="log_window_dsi")
                        return
                    message.phantom.offset = start_offset
                else:
                    message.phantom.random = True
                
                dpg.add_text(f"[TX] Inject Phantom ({mode}, offset={start_offset})\n\n", parent="log_window_dsi")

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

def get_ports():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return ports + ["Simulated Device"] if ports else ["Simulated Device"]

# -----------------
# GUI Setup
# -----------------
dpg.create_context()
dpg.create_viewport(title="DSI Controller", width=800, height=800)

with dpg.window(label="DSI Monitor", width=1900, height=980, pos=(0, 0)):
    dpg.add_text("DSI Connection", color=(100, 255, 100))
    with dpg.group(horizontal=True):
        dpg.add_combo(get_ports(), tag="dsi_port", width=150, default_value="Select Port")
        dpg.add_combo(("9600", "57600", "115200"), tag="dsi_baud", width=80, default_value="115200")
        dpg.add_button(label="Connect DSI", tag="btn_connect_dsi", callback=toggle_dsi_connection)
        dpg.add_text("Disconnected", tag="dsi_status", color=(200, 50, 50))

    dpg.add_separator()
    dpg.add_text("Injection Control", color=(255, 200, 80))
    with dpg.group(horizontal=True):
        dpg.add_combo(items=["Ping", "Abort", "Inject"], tag="main_command_dropdown", default_value="Ping", width=120, callback=toggle_injection_fields)
        dpg.add_button(label="SEND", width=100, callback=send_command_callback)
        dpg.add_progress_bar(tag="progress_bar", default_value=0.0, width=200, overlay="Progress")

    with dpg.group(tag="injection_params_group", show=False):
        with dpg.group(horizontal=True):
            dpg.add_text("Type:")
            dpg.add_combo(items=["Byte Drop", "Bit Flip", "Phantom Byte"], tag="injection_type_dropdown", default_value="Byte Drop", width=120, callback=update_dynamic_fields)
            dpg.add_text("Offset:")
            dpg.add_input_int(tag="inject_offset", width=70, min_value=0, default_value=0)
            dpg.add_text("Length:")
            dpg.add_input_int(tag="inject_length", width=70, min_value=1, default_value=1)
            dpg.add_text("Duration(ms):")
            dpg.add_input_int(tag="inject_duration", width=70, min_value=0, default_value=0)
            
        with dpg.group(tag="byte_drop_group", show=True, horizontal=True):
            dpg.add_text("Pattern:", color=(255, 200, 100))
            dpg.add_input_text(tag="inject_drop_pattern", width=100)

        with dpg.group(tag="xor_mask_group", show=False, horizontal=True):
            dpg.add_text("Mask(Hex):", color=(255, 100, 100))
            dpg.add_input_text(tag="inject_xor_mask", width=100, default_value="FF")

        with dpg.group(tag="phantom_byte_group", show=False, horizontal=True):
            dpg.add_text("Mode:")
            dpg.add_combo(items=["RANDOM", "MANUAL"], tag="phantom_mode", default_value="MANUAL", width=90)
            dpg.add_text("Byte(Hex):", color=(0, 255, 255))
            dpg.add_input_text(tag="phantom_val", width=60, default_value="00")

    dpg.add_separator()
    dpg.add_text("Data Capture", color=(100, 255, 100))
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag="run_name_dsi", width=150, default_value="dsi_log")
        dpg.add_input_int(tag="duration_dsi", width=80, default_value=5)
        dpg.add_button(label="Capture & Save", callback=start_capture_dsi_callback)

    dpg.add_child_window(tag="log_window_dsi", width=-1, height=-1, border=True)

dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()



