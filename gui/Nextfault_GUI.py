import time
import threading
import serial
import serial.tools.list_ports
import dearpygui.dearpygui as dpg

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

with dpg.window(label="Serial Monitor", width=580, height=430, pos=(10, 10)):
    dpg.add_text("Connection Settings", color=(150, 200, 255))
    dpg.add_separator()

    with dpg.group(horizontal=True):
        dpg.add_text("Port:")
        dpg.add_combo(get_ports(), tag="port_dropdown", width=150)

        dpg.add_text("Baud:")
        dpg.add_combo(("9600", "57600", "115200"), default_value="9600", tag="baud_dropdown", width=100)

        dpg.add_button(label="Connect", callback=connect_callback)

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
