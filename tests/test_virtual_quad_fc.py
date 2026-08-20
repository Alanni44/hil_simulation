import os
import gzip
import socket
import struct
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'python_services'))

from hil_adapters.virtual_quad_fc import (VirtualQuadrotorClosedLoopController,
                                          VirtualQuadrotorFcService,
                                          VirtualQuadrotorUutAdapter, _RunRecorder)
from shared.flight_state import FLIGHT_STATE_FORMAT


def actuator_frame(sequence=1, timestamp_us=1, motors=None):
    return {'frame_type': 'actuator_command', 'hardware_id': 'virtual_quad_fc_01',
            'sequence': sequence, 'timestamp_us': timestamp_us, 'armed': True,
            'flight_mode': 'OFFBOARD', 'valid': True,
            'motor_command': motors or [0.5, 0.5, 0.5, 0.5]}


class VirtualAdapterTest(unittest.TestCase):
    def test_rejects_bad_motor_and_non_monotonic_sequence(self):
        adapter = VirtualQuadrotorUutAdapter('virtual_quad_fc_01')
        self.assertEqual(adapter.submit_actuator_frame(actuator_frame()), (True, None))
        self.assertFalse(adapter.submit_actuator_frame(actuator_frame(sequence=1, timestamp_us=2))[0])
        self.assertFalse(adapter.submit_actuator_frame(
            actuator_frame(sequence=2, timestamp_us=3, motors=[1.1, 0, 0, 0]))[0])
        self.assertEqual(adapter.stats['accepted_actuators'], 1)
        self.assertEqual(adapter.stats['rejected_actuators'], 2)


class VirtualRunRecorderTest(unittest.TestCase):
    def test_rotates_compresses_and_stops_at_run_limit(self):
        with tempfile.TemporaryDirectory() as root:
            recorder = _RunRecorder(root, max_file_bytes=300, max_run_bytes=900,
                                    retention_days=0)
            frame = {'payload': 'x' * 120}
            try:
                accepted = 0
                while recorder.record('sensor', frame):
                    accepted += 1
                self.assertGreater(accepted, 1)
            finally:
                recorder.close()
            compressed = os.path.join(recorder.directory, 'frames.0001.ndjson.gz')
            self.assertTrue(os.path.isfile(compressed))
            with gzip.open(compressed, 'rt') as source:
                self.assertIn('"kind":"sensor"', source.read())
            self.assertTrue(recorder.limited)

    def test_purges_only_expired_timestamped_run_directories(self):
        with tempfile.TemporaryDirectory() as root:
            old = os.path.join(root, '20000101T000000Z')
            unrelated = os.path.join(root, 'do-not-delete')
            os.makedirs(old); os.makedirs(unrelated)
            recorder = _RunRecorder(root, max_file_bytes=300, max_run_bytes=900,
                                    retention_days=14)
            recorder.close()
            self.assertFalse(os.path.exists(old))
            self.assertTrue(os.path.isdir(unrelated))


class VirtualFcServiceTest(unittest.TestCase):
    @staticmethod
    def _state_datagram(sequence, sim_time_s, north=0.0, east=0.0, down=0.0):
        return struct.pack(FLIGHT_STATE_FORMAT, 2, sequence, sim_time_s, north, east, down,
                           0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
                           0.0, 0.0, -9.81, 0, 0, 0)

    def test_closed_loop_uses_sensor_estimate_and_fails_safe_when_stale(self):
        controller = VirtualQuadrotorClosedLoopController({
            'origin_lat_deg': 31.2304, 'origin_lon_deg': 121.4737, 'origin_alt_m': 10.0})
        self.assertTrue(controller.ingest({
            'frame_type': 'imu', 'timestamp_us': 1000000, 'valid': True,
            'gyro_radps': [0.0, 0.0, 0.0], 'accel_mps2': [0.0, 0.0, -9.81]}, 1.0))
        self.assertTrue(controller.ingest({
            'frame_type': 'gps', 'timestamp_us': 1000000, 'valid': True,
            'latitude_deg': 31.2304, 'longitude_deg': 121.4737, 'altitude_m': 10.0,
            'velocity_ned_mps': [0.0, 0.0, 0.0], 'heading_deg': 0.0, 'fix_type': 3}, 1.0))
        self.assertTrue(controller.ingest({
            'frame_type': 'barometer', 'timestamp_us': 1000000, 'valid': True,
            'altitude_m': 10.0}, 1.0))
        controller.set_target(5.0, 0.0, 0.0, 0.0)
        motors, armed, mode = controller.command(1.01)
        self.assertTrue(armed); self.assertEqual(mode, 'OFFBOARD')
        self.assertGreater(max(motors) - min(motors), 0.01)
        motors, armed, mode = controller.command(1.25)
        self.assertEqual(motors, [0.0] * 4)
        self.assertFalse(armed); self.assertEqual(mode, 'FAILSAFE')

    def test_route_advances_only_after_estimated_arrival(self):
        controller = VirtualQuadrotorClosedLoopController({})
        for frame in (
                {'frame_type': 'imu', 'timestamp_us': 1, 'valid': True,
                 'gyro_radps': [0.0, 0.0, 0.0], 'accel_mps2': [0.0, 0.0, -9.81]},
                {'frame_type': 'gps', 'timestamp_us': 1, 'valid': True,
                 'latitude_deg': 31.2304, 'longitude_deg': 121.4737, 'altitude_m': 10.0,
                 'velocity_ned_mps': [0.0, 0.0, 0.0], 'heading_deg': 0.0, 'fix_type': 3},
                {'frame_type': 'barometer', 'timestamp_us': 1, 'valid': True, 'altitude_m': 10.0}):
            controller.ingest(frame, 1.0)
        controller.load_route([{'north_m': 0.0, 'east_m': 0.0, 'down_m': 0.0},
                               {'north_m': 4.0, 'east_m': 0.0, 'down_m': 0.0}])
        controller.command(1.01)
        self.assertEqual(controller.route_index, 1)
        self.assertEqual(controller.target['north_m'], 4.0)

    def test_service_generates_sensor_frames_then_closed_loop_command(self):
        sent = []
        with tempfile.TemporaryDirectory() as root:
            service = VirtualQuadrotorFcService(
                {'hardware_id': 'virtual_quad_fc_01', 'command_rate_hz': 250,
                 'imu_rate_hz': 250, 'barometer_rate_hz': 50, 'gps_rate_hz': 20,
                 'health_rate_hz': 10}, command_send=sent.append, recorder_root=root)
            state = {'sequence': 12, 'sim_time_s': 4.0, 'north_m': 10.0, 'east_m': 20.0,
                     'down_m': -3.0, 'vn_mps': 1.0, 've_mps': 2.0, 'vd_mps': 0.0,
                     'q_w': 1.0, 'q_x': 0.0, 'q_y': 0.0, 'q_z': 0.0,
                     'p_radps': 0.1, 'q_radps': 0.2, 'r_radps': 0.3,
                     'ax_mps2': 0.0, 'ay_mps2': 0.0, 'az_mps2': -9.81}
            self.assertEqual(service._imu_from_state(state)['frame_type'], 'imu')
            self.assertEqual(service._gps_from_state(state)['fix_type'], 3)
            self.assertEqual(service._barometer_from_state(state)['valid'], True)
            service._publish(service._imu_from_state(state))
            service._publish(service._barometer_from_state(state))
            service._publish(service._gps_from_state(state))
            self.assertTrue(service.start_scenario('forward')['accepted'])
            frame = service._command_frame(service.clock())
            self.assertTrue(frame['armed'])
            self.assertEqual(frame['flight_mode'], 'OFFBOARD')
            self.assertNotEqual(frame['motor_command'][0], frame['motor_command'][1])
            service._send_frame(frame)
            self.assertEqual(sent[-1]['params']['source'], 'physical_uut')
            self.assertTrue(os.path.isfile(service.recorder.path))
            self.assertFalse(service.status()['recording']['limited'])
            self.assertEqual(512 * 1024 * 1024,
                             service.status()['recording']['max_run_bytes'])
            service.stop()

    def test_udp_snapshot_to_closed_loop_command_path(self):
        sent = []
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        probe.bind(('127.0.0.1', 0)); sensor_port = probe.getsockname()[1]; probe.close()
        with tempfile.TemporaryDirectory() as root:
            service = VirtualQuadrotorFcService(
                {'hardware_id': 'virtual_quad_fc_01', 'sensor_port': sensor_port,
                 'command_rate_hz': 250, 'imu_rate_hz': 250, 'barometer_rate_hz': 50,
                 'gps_rate_hz': 20, 'health_rate_hz': 10},
                command_send=sent.append, recorder_root=root)
            service.start()
            sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                time.sleep(0.01)
                sender.sendto(self._state_datagram(4, 0.004), ('127.0.0.1', sensor_port))
                time.sleep(0.03)
                self.assertTrue(service.start_scenario('forward')['accepted'])
                sender.sendto(self._state_datagram(8, 0.008), ('127.0.0.1', sensor_port))
                time.sleep(0.04)
                active = [item for item in sent if max(item['params']['values']) > 0.0]
                self.assertTrue(active)
                self.assertEqual(active[-1]['params']['source'], 'physical_uut')
            finally:
                sender.close(); service.stop()

    def test_fault_rejects_before_core_dispatch(self):
        sent = []
        with tempfile.TemporaryDirectory() as root:
            service = VirtualQuadrotorFcService({'hardware_id': 'virtual_quad_fc_01'},
                                                command_send=sent.append, recorder_root=root)
            service._faults['invalid_frame_next'] = True
            service._dispatch(service._command_frame(3.0), 3.0)
            self.assertEqual(sent, [])
            self.assertEqual(service.adapter.stats['rejected_actuators'], 1)
            service.stop()


if __name__ == '__main__':
    unittest.main()
