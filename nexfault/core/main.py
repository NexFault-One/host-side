import logger
import parser

# TODO: edit information as nescessary for your serial device.
SERIAL_PORT = "COM3"
BAUD_RATE = 115200
READ_DURATION = 3
LOG_FILE_NAME = "testing"

# script to test functionality of parser-core
def main():
    testdevice = parser.SerialDevice(SERIAL_PORT, BAUD_RATE)

    testdevice.connect()
    print ("Device connection:", testdevice.is_connected())
    print ("Device Information:", testdevice.bus())
    print ("Device Firmware Information:", testdevice.fw_ver())
    testdata = testdevice.read_buffer(READ_DURATION)
    print (testdata)
    testdevice.disconnect()

    log = logger.LogFile(LOG_FILE_NAME)
    log.log_csv(["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)"], testdata)
    log.log_json(["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)"], testdata)

if __name__ == "__main__":
    main()