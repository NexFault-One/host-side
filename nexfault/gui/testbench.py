import serial
import struct
import time
import threading
from nexfault.protobuf_msgs.proto_msgs import uart_data_pb2

DSI_PORT = "COM3"
DSI_BAUD = 9600

def monitor_dsi(ser, stop_event):
    while not stop_event.is_set():
        if ser.in_waiting:
            line = ser.readline().decode('utf-8', errors='ignore').strip()
            if line:
                print(f"[DSI] {line}")

def send(ser, cmd):
    payload = cmd.SerializeToString()
    ser.write(struct.pack('<H', len(payload)) + payload)

def run():
    time.sleep(5)
    ser = serial.Serial(DSI_PORT, DSI_BAUD, timeout=0.1)
    stop_event = threading.Event()
    thread = threading.Thread(target=monitor_dsi, args=(ser, stop_event), daemon=True)
    thread.start()

    time.sleep(5)

    sensor_value = 50

    print("\n=== TEST 1: No injection ===")
    cmd = uart_data_pb2.DsiCommand()
    cmd.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd.inj_type = uart_data_pb2.INJ_UNSPECIFIED
    cmd.sensor_value = sensor_value
    cmd.duration_ms = 0;
    send(ser, cmd)
    time.sleep(5)

    print("\n=== TEST 2: BitFlip randomly changes 5 bits during 10s ===")
    cmd = uart_data_pb2.DsiCommand()
    cmd.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd.inj_type = uart_data_pb2.INJ_BIT_FLIP
    cmd.sensor_value = sensor_value
    cmd.bit_flip.mode = uart_data_pb2.BITFLIP_RANDOM
    cmd.bit_flip.bits_drop = 5
    #cmd.bit_flip.every_n_p = 2
    cmd.duration_ms = 10000
    send(ser, cmd)
    time.sleep(cmd.duration_ms*2/1000)

    print("\n=== TEST 3: ByteDrop 1 byte ===")
    cmd = uart_data_pb2.DsiCommand()
    cmd.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd.inj_type = uart_data_pb2.INJ_BYTE_DROP
    cmd.sensor_value = sensor_value
    cmd.byte_drop.length = 1
    cmd.byte_drop.start_offset = 2
    cmd.duration_ms = 0
    send(ser, cmd)
    time.sleep(5)

    print("\n=== TEST 4: BitFlip every 3 bits ===")
    cmd = uart_data_pb2.DsiCommand()
    cmd.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd.inj_type = uart_data_pb2.INJ_BIT_FLIP
    cmd.sensor_value = sensor_value
    cmd.duration_ms = 0
    cmd.bit_flip.mode = uart_data_pb2.BITFLIP_PERIODIC
    cmd.bit_flip.every_n_p = 3
    send(ser, cmd)
    time.sleep(5)

    print("\n=== TEST 5: Phantom Byte Injection (Manual Offset) ===")
    cmd = uart_data_pb2.DsiCommand()
    cmd.transport = uart_data_pb2.TRANSPORT_MODBUS
    cmd.inj_type = uart_data_pb2.INJ_PHANTOM_BYTE
    cmd.sensor_value = sensor_value
    cmd.duration_ms = 0 # Single shot
    # We insert 0xAB after the 1st byte of the 'Value' field
    cmd.phantom_byte.mode = uart_data_pb2.PHANTOM_MANUAL
    cmd.phantom_byte.byte_value = 0xAB 
    cmd.phantom_byte.offset = 1 
    send(ser, cmd)
    time.sleep(5)

    print("\n=== DONE ===")
    stop_event.set()
    ser.close()

if __name__ == "__main__":
    run()