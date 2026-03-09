from . import logger
from . import parser
from .logger import SessionLocal, User, verify_password, register_user

# main script intended to faciliate fast debug of backend code
# TODO: edit information as nescessary for your serial device.
SERIAL_PORT = "COM6" # check device manager / pio for com ports
BAUD_RATE = 9600
READ_DURATION = 3
LOG_FILE_NAME = "test"

# change for unique tests
USERNAME = "test2"
PASSWORD = "password"

def main():

    # ---------- login test ------------------------------
    db = SessionLocal()
    user = db.query(User).filter(User.username == USERNAME).first()
    
    if not user or not verify_password(PASSWORD, user.hashed_password):
        print("given credentials not registered. adding now.")
        register_user(USERNAME, PASSWORD, SessionLocal())
    
    owner_id = user.id
    db.close()
    print(f"Logged in as {USERNAME} (ID: {owner_id})")

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
    log = logger.LogFile(LOG_FILE_NAME, owner_id=owner_id)
    headers = ["Timestamp", "Length", "Data (Hex)", "Data (ASCII)", "Data (Raw)", "Data Type"]
    log.log_csv(headers, testdata)
    log.log_json(headers, testdata)
    log.log_db(headers, testdata)
    print(log.retrieve_tests())
    print(log.retrieve_logs("test"))
    print ("main complete!")

if __name__ == "__main__":
    main()