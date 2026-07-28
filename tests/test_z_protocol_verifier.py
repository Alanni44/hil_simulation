import unittest

from scripts.z_protocol import ProtocolSequenceValidator, ProtocolViolation


def message(message_type, seq, data):
    return {
        'protocol_version': '2.0',
        'type': message_type,
        'seq': seq,
        'vehicle_id': 'Drone1',
        'data': data,
    }


def hello(seq=1):
    return message('hello', seq, {
        'role': 'simulink_state_source',
        'state_rate_hz': 50,
        'coordinate_convention': 'x_forward_y_right_height_up',
        'angle_unit': 'rad',
    })


def mission(seq=2):
    return message('mission_plan', seq, {
        'mission_id': 'z_mission_001',
        'replace_previous': True,
        'waypoints': [
            {'id': 'P1', 'x': 0.0, 'y': 0.0, 'height': 20.0,
             'target_speed': 2.0},
            {'id': 'P2', 'x': 40.0, 'y': 0.0, 'height': 20.0,
             'target_speed': 5.0},
        ],
    })


def state(seq, sim_time):
    return message('vehicle_state', seq, {
        'mission_id': 'z_mission_001',
        'sim_time': sim_time,
        'position': {'x': 0.0, 'y': 0.0, 'height': 20.0},
        'attitude': {'roll': 0.0, 'pitch': 0.0, 'yaw': 0.0},
        'velocity': {'vx': 0.0, 'vy': 0.0, 'vz': 0.0},
        'angular_velocity': {'p': 0.0, 'q': 0.0, 'r': 0.0},
    })


def mission_end(seq=6):
    return message('simulation_event', seq, {
        'event': 'mission_end',
        'mission_id': 'z_mission_001',
    })


class ProtocolSequenceValidatorTests(unittest.TestCase):
    def test_records_exact_sequence_and_matching_accepted_acks(self):
        validator = ProtocolSequenceValidator()

        hello_ack = validator.observe(hello(), 10.00)
        mission_ack = validator.observe(mission(), 10.01)
        validator.observe(state(3, 0.00), 10.02)
        validator.observe(state(4, 0.02), 10.04)
        validator.observe(state(5, 0.04), 10.06)
        event_ack = validator.observe(mission_end(), 10.07)
        summary = validator.finish()

        self.assertEqual(
            [('hello', 1), ('mission_plan', 2),
             ('vehicle_state', 3), ('vehicle_state', 4),
             ('vehicle_state', 5), ('simulation_event', 6)],
            [(entry['message']['type'], entry['message']['seq'])
             for entry in validator.transcript
             if entry['direction'] == 'received'])
        for ack, ref_type, ref_seq in (
                (hello_ack, 'hello', 1),
                (mission_ack, 'mission_plan', 2),
                (event_ack, 'simulation_event', 6)):
            self.assertEqual('ack', ack['type'])
            self.assertEqual(
                {'ref_type': ref_type, 'ref_seq': ref_seq, 'accepted': True},
                ack['data'])
        self.assertEqual(3, summary['vehicle_state_count'])
        self.assertEqual(50.0, summary['average_state_rate_hz'])
        self.assertTrue(summary['mission_end_acknowledged'])

    def test_rejects_state_before_mission_handshake(self):
        validator = ProtocolSequenceValidator()
        validator.observe(hello(), 1.0)

        with self.assertRaisesRegex(ProtocolViolation, 'mission_plan'):
            validator.observe(state(2, 0.0), 1.02)

    def test_rejects_extra_vehicle_state_fields(self):
        validator = ProtocolSequenceValidator()
        validator.observe(hello(), 1.0)
        validator.observe(mission(), 1.01)
        invalid = state(3, 0.0)
        invalid['data']['acceleration'] = {'x': 0.0, 'y': 0.0, 'z': 0.0}

        with self.assertRaisesRegex(ProtocolViolation, 'vehicle_state.data'):
            validator.observe(invalid, 1.02)

    def test_rejects_non_50_hz_recorded_state_stream(self):
        validator = ProtocolSequenceValidator()
        validator.observe(hello(), 1.0)
        validator.observe(mission(), 1.01)
        validator.observe(state(3, 0.0), 1.02)
        validator.observe(state(4, 0.03), 1.05)
        validator.observe(state(5, 0.06), 1.08)

        with self.assertRaisesRegex(ProtocolViolation, '50 Hz'):
            validator.finish()

    def test_mission_end_is_optional_but_state_is_required(self):
        validator = ProtocolSequenceValidator()
        validator.observe(hello(), 2.0)
        validator.observe(mission(), 2.01)
        validator.observe(state(3, 0.0), 2.02)
        validator.observe(state(4, 0.02), 2.04)

        summary = validator.finish()

        self.assertFalse(summary['mission_end_acknowledged'])


if __name__ == '__main__':
    unittest.main()
