import time
import threading
import serial
import serial.tools.list_ports
import dearpygui.dearpygui as dpg
from datetime import datetime

# Imports from your core modules
from nexfault.core.parser import SerialDevice
from nexfault.core.logger import LogFile

# -----------------
# Global State
# -----------------
ser = None
running = False

# -----------------
# Serial Reader Loop
# ----------------- 
def reader_loop(simulated=False):
    """Background loop for monitoring UUT traffic"""
    global ser, running
    
    while running:
        if simulated:
            time.sleep(1.5)
            msg = f"[Sim] UUT Output {time.strftime('%H:%M:%S')}\n\n"
            dpg.add_text(msg, parent="log_window")
            dpg.set_y_scroll("log_window", -1)
        else:
            try:
                if ser and ser.in_waiting:
                    # Read line-by-line for the GUI log
                    line = ser.readline().decode(errors="ignore").strip()
                    if line:
                        dpg.add_text(f"[RX] {line}\n\n", parent="log_window")
                        dpg.set_y_scroll("log_window", -1)
            except Exception as e:
                dpg.add_text(f"[Error] {e}\n\n", parent="log_window")
                break
        time.sleep(0.05)

# -----------------
# Capture & Save Backend
# -----------------
def _make_row(chunk: bytes, ts: str):
    return [ts, len(chunk), chunk.hex(" "), chunk.decode("utf-8", "ignore").strip(), chunk]

def _capture_backend(duration_s: int, run_name: str):
    """Pauses the live monitor to perform a high-speed capture to file"""
    global ser, running
    
    # 1. Pause background reader
    running = False
    time.sleep(0.2) 

    try:
        port = dpg.get_value("port_select")
        baud = int(dpg.get_value("baud_select"))
        simulated = str(port).strip().lower().startswith("simulated")

        dpg.add_text(f"[Capture] Recording {duration_s}s of data...\n\n", parent="log_window")
        dpg.set_y_scroll("log_window", -1)

        rows = []
        
        # 2. Capture Data
        if simulated:
            dev = SerialDevice("FAKE", baud)
            dev.connect()
            rows = dev.read_buffer(duration_s)
            dev.disconnect()
        else:
            if ser is None or not ser.is_open:
                dpg.add_text("[Capture] Error: Port not open\n\n", parent="log_window")
                return

            end = time.time() + duration_s
            old_timeout = ser.timeout
            ser.timeout = 0.1
            
            try:
                while time.time() < end:
                    if ser.in_waiting:
                        chunk = ser.read(ser.in_waiting or 1)
                        if chunk:
                            ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                            rows.append(_make_row(chunk, ts))
            finally:
                ser.timeout = old_timeout

        # 3. Save Logs
        if rows:
            lf = LogFile(run_name.strip() or "uut_log")
            headers = ["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)"]
            
            csv_path = lf.log_csv(headers, rows)
            json_path = lf.log_json(headers, rows)

            dpg.add_text(f"[Capture] Saved CSV: {csv_path}\n", parent="log_window")
            dpg.add_text(f"[Capture] Saved JSON: {json_path}\n\n", parent="log_window")
        else:
            dpg.add_text("[Capture] No data received.\n\n", parent="log_window")

    except Exception as e:
        dpg.add_text(f"[Capture Error] {e}\n\n", parent="log_window")
    
    finally:
        # 4. Resume background reader
        sim_again = str(dpg.get_value("port_select")).strip().lower().startswith("simulated")
        if (ser and ser.is_open) or sim_again:
            running = True
            threading.Thread(target=reader_loop, args=(sim_again,), daemon=True).start()
        dpg.set_y_scroll("log_window", -1)

def start_capture_callback():
    run_name = dpg.get_value("run_name")
    dur_val = dpg.get_value("duration")
    threading.Thread(target=_capture_backend, args=(dur_val, run_name), daemon=True).start()

# -----------------
# Connection Logic
# -----------------
def toggle_connection():
    global ser, running
    current_label = dpg.get_item_label("btn_connect")
    
    # --- CONNECT ---
    if current_label == "Connect":
        port = dpg.get_value("port_select")
        baud = int(dpg.get_value("baud_select"))
        dpg.delete_item("log_window", children_only=True)

        if port == "Simulated Device":
            dpg.set_value("status_text", "Connected (Sim)")
            dpg.configure_item("status_text", color=(0, 200, 0))
            dpg.configure_item("btn_connect", label="Disconnect")
            running = True
            threading.Thread(target=reader_loop, args=(True,), daemon=True).start()
            return

        try:
            ser = serial.Serial(port, baud, timeout=1)
            # Prevent ESP32 Reset
            ser.dtr = False 
            ser.rts = False
            
            dpg.set_value("status_text", "Connected")
            dpg.configure_item("status_text", color=(0, 200, 0))
            dpg.configure_item("btn_connect", label="Disconnect")
            running = True
            threading.Thread(target=reader_loop, daemon=True).start()
        except Exception as e:
            dpg.set_value("status_text", "Error")
            dpg.configure_item("status_text", color=(200, 0, 0))
            dpg.add_text(f"[Error] {e}\n\n", parent="log_window")

    # --- DISCONNECT ---
    else:
        running = False
        time.sleep(0.1)
        try:
            if ser and ser.is_open:
                ser.close()
        except:
            pass
        ser = None
        dpg.set_value("status_text", "Disconnected")
        dpg.configure_item("status_text", color=(200, 50, 50))
        dpg.configure_item("btn_connect", label="Connect")
        dpg.add_text("[Info] Disconnected\n\n", parent="log_window")

def get_ports():
    ports = [p.device for p in serial.tools.list_ports.comports()]
    return ports + ["Simulated Device"] if ports else ["Simulated Device"]

# -----------------
# GUI Setup
# -----------------
dpg.create_context()
dpg.create_viewport(title="UUT Serial Monitor", width=700, height=600)

with dpg.window(label="UUT Monitor", width=1910, height=980, pos=(0, 0)):
    
    dpg.add_text("UUT Connection", color=(100, 255, 100))
    with dpg.group(horizontal=True):
        dpg.add_text("Port:")
        dpg.add_combo(get_ports(), tag="port_select", width=150, default_value="Select Port")
        dpg.add_text("Baud:")
        dpg.add_combo(("9600", "57600", "115200"), tag="baud_select", width=100, default_value="115200")
        dpg.add_button(label="Connect", tag="btn_connect", callback=toggle_connection, width=100)
        dpg.add_text("Disconnected", tag="status_text", color=(200, 50, 50))

    dpg.add_separator()
    dpg.add_spacer(height=5)

    dpg.add_text("Data Capture", color=(100, 100, 255))
    with dpg.group(horizontal=True):
        dpg.add_text("Filename:")
        dpg.add_input_text(tag="run_name", width=150, default_value="uut_log", hint="File prefix")
        dpg.add_text("Time(s):")
        dpg.add_input_int(tag="duration", width=80, default_value=5, min_value=1)
        dpg.add_button(label="Capture & Save", callback=start_capture_callback)

    dpg.add_separator()
    dpg.add_spacer(height=5)

    dpg.add_text("Serial Output:", color=(200, 200, 200))
    dpg.add_child_window(tag="log_window", width=-1, height=-1, border=True)

dpg.setup_dearpygui()
dpg.show_viewport()
dpg.start_dearpygui()
dpg.destroy_context()