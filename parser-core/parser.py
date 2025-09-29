import serial
import time
from datetime import datetime
from serial.tools import list_ports

class SerialDevice:
    def __init__(self, port: str, baud: int):
        """
        Initialize serial connection parameters.
        """
        self.port = port
        self.baud = baud
        self.timeout = 0.1
        self.ser = None

        for port in list_ports.comports():
            if port.device == self.port:
                self.description = port.description
                self.hwid = port.hwid

    def connect(self):
        """
        Attempt connection to serial port.
        """
        try:
            print(f"Attempting connection to {self.port} with baud {self.baud}")
            self.ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            print(f"Connection successful!")
        except (OSError, serial.SerialException) as e:
            print("Error opening serial port: ", e)
            self.ser = None

    def is_connected(self) -> bool:
        """
        Verify connection to serial port.
        """
        return self.ser is not None and self.ser.is_open
    
    def fw_ver(self):
        """
        Gets device firmware version. Not yet implemented.
        """
        return "None"
    
    def bus(self):
        """
        Returns device hwid for the time being.
        """
        return self.hwid
    
    def features(self):
        """
        Checks features of serial device. Not yet implemented.
        """
        return "None"
    
    def read_buffer(self, duration: float):
        """
        Collect data from the device's buffer and save to an array. Includes timestamp for logging purposes.
        """
        if not self.is_connected():
            print("Serial device is not connected.")
            return []
        
        print (f"Reading data on {self.port} for {duration}s")
        print (self.ser)
        end_time = time.time() + duration
        data = []

        while time.time() < end_time:
            if self.ser.in_waiting > 0:
                read_data = self.ser.read(self.ser.in_waiting)
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                data.append([read_data, timestamp])
            time.sleep(0.01)
        
        print("Read complete")
        return data
    
    def disconnect(self):
        """
        Disconnects serial device.
        """
        if self.ser and self.ser.is_open:
            self.ser.close()
            print("Serial connection closed.")
               

# testing
def main():
    testdevice = SerialDevice('COM3', 115200)
    testdevice.connect()
    print ("Device connection:", testdevice.is_connected())
    print ("Device Information:", testdevice.bus())
    print ("Device Firmware Information:", testdevice.fw_ver())
    testdata = testdevice.read_buffer(duration=5)
    for i in testdata:
        print (i)
    testdevice.disconnect()

if __name__ == "__main__":
    main()
