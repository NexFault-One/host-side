import serial
import time

# --- Configuration ---
# TODO: Change this to your serial port name
# On Windows, it will be something like 'COM3'
# On Linux or macOS, it will be like '/dev/ttyUSB0' or '/dev/tty.usbmodem1234'
SERIAL_PORT = 'COM4' 
BAUD_RATE = 115200

def main():
    """
    Main function to connect to the serial port and print all incoming data.
    """
    print("--- Simple Serial Monitor ---")
    
    try:
        # Initialize the serial port connection.
        # A short timeout is used so the read operation doesn't block forever.
        ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
        print(f"Successfully opened port {SERIAL_PORT} at {BAUD_RATE} bps.")
    except serial.SerialException as e:
        print(f"Fatal Error: Could not open serial port {SERIAL_PORT}.")
        print(f"Details: {e}")
        print("Please check the port name and ensure the device is connected.")
        return # Exit the script

    print("Listening for incoming data... Press Ctrl+C to exit.")
    
    try:
        while True:
            # Check if there is data waiting in the serial buffer
            if ser.in_waiting > 0:
                # Read all available bytes from the buffer
                data_bytes = ser.read(ser.in_waiting)
                
                # Decode the bytes into a string for printing.
                # 'ignore' will prevent errors if non-textual binary data is received.
                data_str = data_bytes.decode('utf-8', 'ignore')
                
                # Print the received data. The `end=''` prevents adding extra newlines.
                print(data_str, end='')

            # A small delay to prevent the loop from running too fast and using 100% CPU
            time.sleep(0.01)

    except KeyboardInterrupt:
        # Allow the user to exit gracefully with Ctrl+C
        print("\nExiting program.")
    except Exception as e:
        # Catch any other unexpected errors
        print(f"\nAn unexpected error occurred: {e}")
    finally:
        # Cleanly close the serial port when the program ends
        if ser.is_open:
            ser.close()
            print("Serial port closed.")


if __name__ == "__main__":
    main()
