from nexfault.protobuf_msgs.proto_msgs import uart_data_pb2

from . import logger, parser
from .logger import SessionLocal, User, hash_password_bcrypt, verify_password

# main script intended to faciliate fast debug of backend code
SERIAL_PORT = "FAKE"  # set to "FAKE" to run without hardware, or "COMx" for real device
BAUD_RATE = 9600
READ_DURATION = 3
LOG_FILE_NAME = "test"

# change for unique tests
USERNAME = "test2"
EMAIL = "test2@gmail.com"
PASSWORD = "password"
FIRST_NAME = "Test"
LAST_NAME = "User"


def main():

    # ---------- login test ------------------------------
    db = SessionLocal()
    user = db.query(User).filter(User.username == USERNAME).first()

    if not user:
        print("given credentials not registered. adding now.")
        new_user = User(
            username=USERNAME,
            email=EMAIL,
            first_name=FIRST_NAME,
            last_name=LAST_NAME,
            hashed_password=hash_password_bcrypt(PASSWORD),
        )
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        user = new_user
    elif not verify_password(PASSWORD, user.hashed_password):
        print("incorrect password for existing user.")
        db.close()
        return

    owner_id = user.id
    db.close()
    print(f"Logged in as {USERNAME} (ID: {owner_id})")

    # ---------- create and initiate connection ----------
    testdevice = parser.SerialDevice(SERIAL_PORT, BAUD_RATE)
    testdevice.connect()
    print("Device connection:", testdevice.is_connected())
    print("Device Information:", testdevice.bus())
    print("Device Firmware Information:", testdevice.fw_ver())

    # ---------- TmiReport round-trip test ----------
    print("attempting TmiReport serialize → parse_envelope round-trip")
    tmi = uart_data_pb2.TmiReport()
    tmi.run_id                = 42
    tmi.attempt_no            = 1
    tmi.injection_type        = uart_data_pb2.InjectionType.INJ_BYTE_DROP
    tmi.transport_type        = uart_data_pb2.TransportType.TRANSPORT_MODBUS
    tmi.injection_duration_ms = 5000
    tmi.bytes_transmitted     = 128
    tmi.bytes_received        = 120
    tmi.bytes_dropped         = 8
    tmi.frames_sent           = 10
    tmi.responses_ok          = 2
    tmi.responses_error       = 8
    tmi.status                = uart_data_pb2.ExecStatus.STATUS_DONE
    tmi.verdict               = uart_data_pb2.TestVerdict.VERDICT_PASS
    tmi.reason                = uart_data_pb2.FailureReason.FAIL_NONE
    tmi.verdict_message       = "UUT rejected all corrupted frames correctly."

    env = uart_data_pb2.Envelope()
    env.report.CopyFrom(tmi)
    raw = env.SerializeToString()
    print("Serialized bytes:", raw.hex(" "))

    result = testdevice.parse_envelope(raw)
    if result is not None:
        print("  id (host-assigned):       ", result.id)
        print("  timestamp_ms (host):      ", result.timestamp_ms)
        print("  run_id:                   ", result.run_id)
        print("  attempt_no:               ", result.attempt_no)
        print("  injection_type:           ", result.injection_type)
        print("  transport_type:           ", result.transport_type)
        print("  injection_duration_ms:    ", result.injection_duration_ms)
        print("  bytes_transmitted:        ", result.bytes_transmitted)
        print("  bytes_received:           ", result.bytes_received)
        print("  bytes_dropped:            ", result.bytes_dropped)
        print("  frames_sent:              ", result.frames_sent)
        print("  responses_ok:             ", result.responses_ok)
        print("  responses_error:          ", result.responses_error)
        print("  responses_timeout:        ", result.responses_timeout)
        print("  uut_reset_suspected:      ", result.uut_reset_suspected)
        print("  status:                   ", result.status)
        print("  verdict:                  ", result.verdict)
        print("  reason:                   ", result.reason)
        print("  verdict_message:          ", result.verdict_message)
    else:
        print("parse_envelope returned None")

    # ---------- read and return data ----------
    print("attempting read test")
    testdata = testdevice.read_buffer(READ_DURATION)
    testdata.append(testdevice.log_entry(raw))
    testdevice.disconnect()

    # ---------- logging test ----------
    print("attempting log test")
    log = logger.LogFile(LOG_FILE_NAME, username=USERNAME)
    headers = [
        "Timestamp",
        "Length",
        "Data (Hex)",
        "Data (ASCII)",
        "Data (Raw)",
        "Data Type",
    ]
    log.log_csv(headers, testdata)
    log.log_json(headers, testdata)
    log.log_db(headers, testdata)
    print(log.retrieve_tests())
    print(log.retrieve_logs("test"))
    print("main complete!")


if __name__ == "__main__":
    main()
