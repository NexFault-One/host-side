from . import logger
from . import parser

# main script intended to faciliate fast debug of backend code
# TODO: edit information as nescessary for your serial device.
SERIAL_PORT = "COM6" # check device manager / pio for com ports
BAUD_RATE = 9600
READ_DURATION = 3
LOG_FILE_NAME = "test"

def main():

    # ---------- create and initiate connection ----------
    testdevice = parser.SerialDevice(SERIAL_PORT, BAUD_RATE)
    testdevice.connect()
    print ("Device connection:", testdevice.is_connected())
    print ("Device Information:", testdevice.bus())
    print ("Device Firmware Information:", testdevice.fw_ver())

    # ---------- writetest ----------
    print ("attempting write test")
    env = testdevice.byte_drop()
    if (testdevice.try_parse_command(env) != None):
        print ("valid data provided.")
        print (env, type(env))
    else:
        print ("invalid data provided.")
        print (env)
    testdevice.write_buffer(env)

    # ---------- read and return data ----------
    print ("attempting read test")
    testdata = testdevice.read_buffer(READ_DURATION)
    testdata.append(testdevice.log_entry(env))
    testdevice.disconnect()

    # ---------- logging test ----------
    print ("attempting log test")
    log = logger.LogFile(LOG_FILE_NAME)
    log.log_csv(["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)", "Data Type"], testdata)
    log.log_json(["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)", "Data Type"], testdata)
    log.log_db(["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)", "Data Type"], testdata)
    print ("main complete!")

if __name__ == "__main__":
    main()