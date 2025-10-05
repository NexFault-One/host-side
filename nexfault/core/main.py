import logger
import parser

# main script intended to faciliate fast debug of backend code
# TODO: edit information as nescessary for your serial device.
SERIAL_PORT = "COM6" # COM6 = receiver, COM3 = transmitter on Siva PC and esp32 hardware loop
BAUD_RATE = 9600
READ_DURATION = 4
LOG_FILE_NAME = "serial_receiver_oct5"

# script to test functionality of parser-core
def main():

    # creates and connects to device
    testdevice = parser.SerialDevice(SERIAL_PORT, BAUD_RATE)
    testdevice.connect()
    print ("Device connection:", testdevice.is_connected())
    print ("Device Information:", testdevice.bus())
    print ("Device Firmware Information:", testdevice.fw_ver())

    # writetest
    # testdevice.write_buffer()
    testdata = testdevice.read_buffer(READ_DURATION)
    
    for values in testdata:
        print(values[3])
        
    testdevice.disconnect()

    log = logger.LogFile(LOG_FILE_NAME)
    log.log_csv(["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)"], testdata)
    log.log_json(["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)"], testdata)

if __name__ == "__main__":
    main()