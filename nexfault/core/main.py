import uuid
from datetime import datetime

from nexfault.protobuf_msgs.proto_msgs import uart_data_pb2

from . import logger, parser
from .logger import (
    Profile,
    SessionLocal,
    User,
    hash_password_bcrypt,
    verify_password,
    _build_command_from_profile,
    _report_to_dict,
)

# main script intended to faciliate fast debug of backend code
SERIAL_PORT = "FAKE"  # set to "FAKE" to run without hardware, or "COMx" for real device
BAUD_RATE = 9600
READ_DURATION = 3
LOG_FILE_NAME = "test_run"

# change for unique tests
USERNAME = "nexfault_tester"
EMAIL = "nexfault@gmail.com"
PASSWORD = "password"
FIRST_NAME = "Test"
LAST_NAME = "User"
PROFILE_NAME = "bd_uart_1"


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

    # ---------- create profile ----------
    db = SessionLocal()
    profile = db.query(Profile).filter(
        Profile.owner_id == owner_id, Profile.name == PROFILE_NAME
    ).first()
    if not profile:
        print(f"Profile '{PROFILE_NAME}' not found. Creating now.")
        # EDIT FOR UNIQUE PROFILES
        profile = Profile(
            id=str(uuid.uuid4()),
            owner_id=owner_id,
            name=PROFILE_NAME,
            description="Byte drop injection over UART",
            injection_type="INJ_BYTE_DROP",
            transport="TRANSPORT_UART",
            payload="default",
            duration_ms=5000,
            duration_str="5000",
            injection_params_str='{"start_offset": 0, "length": 1}',
        )
        db.add(profile)
        db.commit()
        db.refresh(profile)
    profile_id = profile.id
    db.close()
    print(f"Using profile '{PROFILE_NAME}' (ID: {profile_id})")

    # ---------- create and initiate connection ----------
    testdevice = parser.SerialDevice(SERIAL_PORT, BAUD_RATE)
    testdevice.connect()
    print("Device connection:", testdevice.is_connected())
    print("Device Information:", testdevice.bus())
    print("Device Firmware Information:", testdevice.fw_ver())

    # ---------- build injection command from profile ----------
    cmd = _build_command_from_profile(profile)
    print(f"Built DsiCommand: id={cmd.id}, inj_type={cmd.inj_type}, "
          f"transport={cmd.transport}, duration_ms={cmd.duration_ms}")

    # ---------- send command + read response ----------
    # CHANGE THESE VALUES FOR FAKE TMI REPORTS
    if testdevice._simulate:
        # Simulated mode: fake a TmiReport since there's no real device
        tmi = uart_data_pb2.TmiReport()
        tmi.run_id                = cmd.id
        tmi.attempt_no            = 1
        tmi.injection_type        = cmd.inj_type
        tmi.transport_type        = uart_data_pb2.TransportType.Value(profile.transport)
        tmi.injection_duration_ms = cmd.duration_ms
        tmi.bytes_transmitted     = 256
        tmi.bytes_received        = 248
        tmi.bytes_dropped         = 8
        tmi.frames_sent           = 20
        tmi.responses_ok          = 12
        tmi.responses_error       = 8
        tmi.avg_response_time_ms  = 15
        tmi.max_response_time_ms  = 42
        tmi.status                = uart_data_pb2.ExecStatus.STATUS_DONE
        tmi.verdict               = uart_data_pb2.TestVerdict.VERDICT_PASS
        tmi.reason                = uart_data_pb2.FailureReason.FAIL_NONE
        tmi.verdict_message       = "Simulated: UUT rejected all corrupted frames."

        env = uart_data_pb2.Envelope()
        env.report.CopyFrom(tmi)
        tmi_raw = env.SerializeToString()

        # Verify parse_envelope round-trip
        parsed = testdevice.parse_envelope(tmi_raw)
        if parsed is None:
            print("ERROR: parse_envelope returned None for TmiReport")
            return
        print("TmiReport round-trip OK")

        testdata = testdevice.read_buffer(READ_DURATION)
        testdata.append(testdevice.log_entry(tmi_raw))
    else:
        # Real hardware: send command and read all responses
        testdevice.write_raw(cmd.SerializeToString())
        read_duration = (cmd.duration_ms / 1000.0) + 8.0
        testdata = testdevice.read_buffer(read_duration)

    testdevice.disconnect()

    # ---------- save all data (telemetry + report) ----------
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    test_name = f"{PROFILE_NAME}_{timestamp}"
    headers = [
        "Timestamp", "Length", "Data (Hex)",
        "Data (ASCII)", "Data (Raw)", "Data Type",
    ]
    log = logger.LogFile(test_name, USERNAME, profile_id)
    log.log_csv(headers, testdata)
    log.log_json(headers, testdata)
    log.log_db(headers, testdata)

    # ---------- extract report and print (same as endpoint) ----------
    report = None
    for row in testdata:
        raw = row[4]  # Data (Raw)
        msg = testdevice.parse_envelope(raw)
        if isinstance(msg, uart_data_pb2.TmiReport):
            report = msg

    if report:
        result = _report_to_dict(report, test_name, PROFILE_NAME)
        print(f"Saved test '{test_name}' with {len(testdata)} log entries")
        for k, v in result.items():
            print(f"  {k}: {v}")
    else:
        print("WARNING: No TmiReport found in logged data")

    print("Tests in DB:", log.retrieve_tests())
    db.close()
    print("main complete!")


if __name__ == "__main__":
    main()
