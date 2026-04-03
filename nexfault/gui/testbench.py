import serial
import struct
import time
import threading
from nexfault.protobuf_msgs.proto_msgs import uart_data_pb2

DSI_PORT = "COM3"
DSI_BAUD = 9600

# Default Modbus config used for all tests
MODBUS_SLAVE_ID = 1
MODBUS_FUNC_CODE = 0x06
MODBUS_ADDRESS = 100
MODBUS_VALUE_OR_QUANTITY = 55
MODBUS_RECALCULATE_CRC = False


def monitor_dsi(ser, stop_event):
    while not stop_event.is_set():
        try:
            if ser.in_waiting:
                line = ser.readline().decode("utf-8", errors="ignore").strip()
                if line:
                    print(f"[DSI] {line}")
        except Exception:
            # keep monitor thread alive
            pass


def send(ser, cmd):
    payload = cmd.SerializeToString()  # raw DsiCommand payload
    ser.write(struct.pack("<H", len(payload)) + payload)
    ser.flush()


def apply_modbus_config(cmd):
    cmd.modbus_config.slave_id = MODBUS_SLAVE_ID
    cmd.modbus_config.func_code = MODBUS_FUNC_CODE
    cmd.modbus_config.address = MODBUS_ADDRESS
    cmd.modbus_config.value_or_quantity = MODBUS_VALUE_OR_QUANTITY
    cmd.modbus_config.recalculate_crc = MODBUS_RECALCULATE_CRC


def run():
    time.sleep(5)
    ser = serial.Serial(DSI_PORT, DSI_BAUD, timeout=0.1)

    stop_event = threading.Event()
    thread = threading.Thread(target=monitor_dsi, args=(ser, stop_event), daemon=True)
    thread.start()

    time.sleep(5)

    # === TEST 1: No injection ===
    print("\n=== TEST 1: No injection ===")
    cmd = uart_data_pb2.DsiCommand()
    cmd.id = 1
    cmd.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd.inj_type = uart_data_pb2.INJ_UNSPECIFIED
    cmd.duration_ms = 500
    apply_modbus_config(cmd)
    send(ser, cmd)
    time.sleep(5)

    # === TEST 2: BitFlip random, 5 bits, 10s ===
    print("\n=== TEST 2: BitFlip randomly changes 5 bits during 10s ===")
    cmd = uart_data_pb2.DsiCommand()
    cmd.id = 2
    cmd.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd.inj_type = uart_data_pb2.INJ_BIT_FLIP
    cmd.duration_ms = 10000
    cmd.bit_flip.mode = uart_data_pb2.BITFLIP_RANDOM
    cmd.bit_flip.bits_drop = 5
    apply_modbus_config(cmd)
    send(ser, cmd)
    time.sleep(cmd.duration_ms * 2 / 1000)

    # === TEST 3: ByteDrop ===
    print("\n=== TEST 3: ByteDrop 1 byte ===")
    cmd = uart_data_pb2.DsiCommand()
    cmd.id = 3
    cmd.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd.inj_type = uart_data_pb2.INJ_BYTE_DROP
    cmd.duration_ms = 500
    cmd.byte_drop.length = 1
    cmd.byte_drop.start_offset = 2
    apply_modbus_config(cmd)
    send(ser, cmd)
    time.sleep(5)

    # === TEST 4: BitFlip periodic ===
    print("\n=== TEST 4: BitFlip every 3 bits ===")
    cmd = uart_data_pb2.DsiCommand()
    cmd.id = 4
    cmd.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd.inj_type = uart_data_pb2.INJ_BIT_FLIP
    cmd.duration_ms = 500
    cmd.bit_flip.mode = uart_data_pb2.BITFLIP_PERIODIC
    cmd.bit_flip.every_n_p = 3
    apply_modbus_config(cmd)
    send(ser, cmd)
    time.sleep(5)

    # === TEST 5: Phantom Byte manual ===
    print("\n=== TEST 5: Phantom Byte Injection (Manual Offset) ===")
    cmd = uart_data_pb2.DsiCommand()
    cmd.id = 5
    cmd.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd.inj_type = uart_data_pb2.INJ_PHANTOM_BYTE
    cmd.duration_ms = 500
    cmd.phantom_byte.mode = uart_data_pb2.PHANTOM_MANUAL
    cmd.phantom_byte.byte_value = 0xAB
    cmd.phantom_byte.offset = 1
    apply_modbus_config(cmd)
    send(ser, cmd)
    time.sleep(5)

    print("\n=== DONE ===")
    stop_event.set()
    ser.close()


if __name__ == "__main__":
    run()