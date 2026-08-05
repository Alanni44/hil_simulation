"""Minimal MAVLink 2 HIL transport without a runtime pymavlink dependency.

Implemented messages are the PX4 HIL data path: HIL_SENSOR (107), HIL_GPS
(113), and inbound HIL_ACTUATOR_CONTROLS (93).  The adapter deliberately does
not own source arbitration: callers must submit returned controls to the C
core as ``source=px4_sitl``.
"""
from __future__ import print_function

import socket
import struct
import time

MAVLINK2_STX = 0xFD
MSG_HIL_ACTUATOR_CONTROLS = 93
MSG_HIL_SENSOR = 107
MSG_HIL_GPS = 113
CRC_EXTRA = {
    MSG_HIL_ACTUATOR_CONTROLS: 47,
    MSG_HIL_SENSOR: 108,
    MSG_HIL_GPS: 124,
}


def _x25_crc(data, initial=0xFFFF):
    crc = initial
    for byte in bytearray(data):
        byte ^= crc & 0xFF
        byte ^= (byte << 4) & 0xFF
        crc = ((crc >> 8) ^ (byte << 8) ^ (byte << 3) ^ (byte >> 4)) & 0xFFFF
    return crc


def _mavlink2_frame(message_id, payload, sequence, system_id=1, component_id=1):
    if message_id not in CRC_EXTRA:
        raise ValueError('unsupported MAVLink message {}'.format(message_id))
    header = struct.pack('<BBBBBB', len(payload), 0, 0, sequence & 0xFF,
                         system_id, component_id) + struct.pack('<I', message_id)[:3]
    checksum = _x25_crc(header + payload)
    checksum = _x25_crc(bytes(bytearray([CRC_EXTRA[message_id]])), checksum)
    return bytes(bytearray([MAVLINK2_STX])) + header + payload + struct.pack('<H', checksum)


def _decode_frame(packet):
    if len(packet) < 12 or bytearray(packet)[0] != MAVLINK2_STX:
        return None
    payload_length = bytearray(packet)[1]
    incompat_flags = bytearray(packet)[2]
    signature_length = 13 if incompat_flags & 0x01 else 0
    total = 10 + payload_length + 2 + signature_length
    if len(packet) != total:
        return None
    header = packet[1:10]
    payload = packet[10:10 + payload_length]
    checksum = struct.unpack('<H', packet[10 + payload_length:12 + payload_length])[0]
    message_id = struct.unpack('<I', header[6:9] + b'\0')[0]
    if message_id not in CRC_EXTRA:
        return None
    expected = _x25_crc(header + payload)
    expected = _x25_crc(bytes(bytearray([CRC_EXTRA[message_id]])), expected)
    if checksum != expected:
        return None
    return message_id, payload


class MavlinkHilAdapter(object):
    """UDP MAVLink HIL endpoint with explicit PX4 peer configuration."""

    def __init__(self, peer_host='127.0.0.1', peer_port=14560,
                 bind_host='127.0.0.1', bind_port=14580, system_id=1,
                 component_id=1):
        self._peer = (peer_host, int(peer_port))
        self._system_id = int(system_id)
        self._component_id = int(component_id)
        self._sequence = 0
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind((bind_host, int(bind_port)))
        self._socket.setblocking(False)

    def close(self):
        self._socket.close()

    def _send(self, message_id, payload):
        frame = _mavlink2_frame(message_id, payload, self._sequence,
                                self._system_id, self._component_id)
        self._sequence = (self._sequence + 1) & 0xFF
        self._socket.sendto(frame, self._peer)

    def send_sensor(self, sensor):
        """Send normalized IMU/barometer data as MAVLink HIL_SENSOR.

        ``sensor`` requires time_usec, accel_mps2[3], gyro_radps[3],
        mag_gauss[3], abs_pressure_hpa, diff_pressure_hpa, pressure_alt_m,
        temperature_c and fields_updated.
        """
        payload = struct.pack(
            '<Q13fI', int(sensor['time_usec']),
            sensor['accel_mps2'][0], sensor['accel_mps2'][1], sensor['accel_mps2'][2],
            sensor['gyro_radps'][0], sensor['gyro_radps'][1], sensor['gyro_radps'][2],
            sensor['mag_gauss'][0], sensor['mag_gauss'][1], sensor['mag_gauss'][2],
            sensor['abs_pressure_hpa'], sensor['diff_pressure_hpa'],
            sensor['pressure_alt_m'], sensor['temperature_c'],
            int(sensor['fields_updated']))
        self._send(MSG_HIL_SENSOR, payload)

    def send_gps(self, gps):
        """Send NED GPS data as MAVLink HIL_GPS (integer MAVLink units)."""
        payload = struct.pack(
            '<QiiiHHHhhhHBB', int(gps['time_usec']), int(gps['lat_e7']),
            int(gps['lon_e7']), int(gps['alt_mm']), int(gps['eph_cm']),
            int(gps['epv_cm']), int(gps['velocity_cmps']), int(gps['vn_cmps']),
            int(gps['ve_cmps']), int(gps['vd_cmps']), int(gps['cog_cdeg']),
            int(gps['fix_type']), int(gps['satellites_visible']))
        self._send(MSG_HIL_GPS, payload)

    def poll_actuators(self):
        """Return newest HIL_ACTUATOR_CONTROLS values, or None when absent."""
        newest = None
        while True:
            try:
                packet, _ = self._socket.recvfrom(512)
            except (socket.error, BlockingIOError):
                break
            decoded = _decode_frame(packet)
            if not decoded or decoded[0] != MSG_HIL_ACTUATOR_CONTROLS:
                continue
            payload = decoded[1]
            if len(payload) < 73:
                continue
            values = struct.unpack('<Q16fB', payload[:73])
            newest = {'time_usec': values[0], 'controls': list(values[1:17]),
                      'mode': values[17], 'received_monotonic_ns':
                      int(time.monotonic() * 1000000000)}
        return newest
