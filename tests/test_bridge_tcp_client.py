import json
import asyncio
import pathlib
import socket
import struct
import sys
import threading
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

import bridge_tcp_client  # noqa: E402
import ws_server  # noqa: E402


WAYPOINTS = [
    {'x': 0.0, 'y': 0.0, 'height': 20.0, 'speed': 2.0},
    {'x': 40.0, 'y': 0.0, 'height': 20.0, 'speed': 5.0},
]


def recv_json_line(sock):
    header = bytearray()
    while len(header) < 4:
        chunk = sock.recv(4 - len(header))
        if not chunk:
            raise EOFError('peer closed before frame header completed')
        header.extend(chunk)
    length = struct.unpack('>I', bytes(header))[0]
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise EOFError('peer closed before JSON frame completed')
        data.extend(chunk)
    return json.loads(bytes(data).decode('utf-8'))


def encode_frame(payload):
    if not isinstance(payload, bytes):
        payload = json.dumps(payload).encode('utf-8')
    return struct.pack('>I', len(payload)) + payload


def send_fragmented_ack(sock, message, accepted=True, ref_type=None,
                        ref_seq=None):
    ack = {
        'protocol_version': '2.0',
        'type': 'ack',
        'seq': message['seq'] + 100,
        'vehicle_id': 'Drone1',
        'data': {
            'ref_type': ref_type or message['type'],
            'ref_seq': message['seq'] if ref_seq is None else ref_seq,
            'accepted': accepted,
        },
    }
    wire = encode_frame(ack)
    for split in (wire[:3], wire[3:11], wire[11:]):
        sock.sendall(split)


class BridgeTcpClientTests(unittest.TestCase):
    def setUp(self):
        self.original_running = bridge_tcp_client._running
        self.original_seq = bridge_tcp_client._seq
        bridge_tcp_client._running = True
        bridge_tcp_client._stop_event.clear()
        bridge_tcp_client._connected.clear()
        with bridge_tcp_client._queue_lock:
            bridge_tcp_client._current_mission_id = None
            bridge_tcp_client._pending_waypoints = None
            bridge_tcp_client._mission_queue[:] = []
            bridge_tcp_client._event_queue[:] = []
            bridge_tcp_client._event_reservations.clear()

    def tearDown(self):
        bridge_tcp_client._running = self.original_running
        bridge_tcp_client._seq = self.original_seq
        bridge_tcp_client._stop_event.clear()
        bridge_tcp_client._connected.clear()
        with bridge_tcp_client._queue_lock:
            bridge_tcp_client._current_mission_id = None
            bridge_tcp_client._pending_waypoints = None
            bridge_tcp_client._mission_queue[:] = []
            bridge_tcp_client._event_queue[:] = []
            bridge_tcp_client._event_reservations.clear()

    def test_start_bridge_accepts_explicit_debug_target_and_returns_worker(self):
        worker = mock.Mock()
        with mock.patch.object(bridge_tcp_client.threading, 'Thread',
                               return_value=worker) as thread_factory:
            result = bridge_tcp_client.start_bridge(
                '192.168.100.172', 5000)

        self.assertIs(worker, result)
        thread_factory.assert_called_once_with(
            target=bridge_tcp_client._run,
            args=('192.168.100.172', 5000),
            daemon=True,
            name='bridge_v2')
        worker.start.assert_called_once_with()

    def test_status_snapshot_exposes_operator_session_phase_and_error(self):
        bridge_tcp_client._set_session_status(
            'hello acknowledged', 'previous connection refused')

        status = bridge_tcp_client.get_status()

        self.assertEqual('hello acknowledged', status['phase'])
        self.assertEqual('previous connection refused', status['last_error'])
        self.assertFalse(status['connected'])

    def test_ws_mission_end_reserves_delivery_before_calling_core(self):
        bridge_tcp_client._connected.set()
        receipt = {
            'request_id': 'request-a',
            'accepted': True,
            'reason': 'mission ended',
        }

        def core_request(_command):
            with bridge_tcp_client._queue_lock:
                self.assertEqual(
                    [('mission_end', 'mission-a')],
                    list(bridge_tcp_client._event_reservations.values()))
                self.assertEqual([], bridge_tcp_client._event_queue)
            return receipt

        responses = []

        async def capture_response(_writer, payload):
            responses.append(json.loads(payload))

        with mock.patch.object(ws_server, '_core_request',
                               side_effect=core_request), \
                mock.patch.object(ws_server, 'ws_send',
                                  side_effect=capture_response):
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(ws_server._handle_core_command(
                    'mission_end',
                    {'request_id': 'request-a', 'mission_id': 'mission-a'},
                    object(), lifecycle_event='mission_end'))
            finally:
                loop.close()

        with bridge_tcp_client._queue_lock:
            self.assertEqual({}, bridge_tcp_client._event_reservations)
            self.assertEqual(
                [('mission_end', 'mission-a')],
                bridge_tcp_client._event_queue)
        self.assertEqual([receipt], responses)

    def test_queued_reset_is_mapped_to_wire_event_exactly_once(self):
        bridge_tcp_client.send_simulation_event('reset')

        missions, events = bridge_tcp_client._drain_queues()
        self.assertEqual([], missions)
        self.assertEqual([('reset', '')], events)
        message = bridge_tcp_client._simulation_event_message(*events[0])
        self.assertEqual('simulation_event', message['type'])
        self.assertEqual({'event': 'reset_scene'}, message['data'])

    def test_length_prefixed_fragment_survives_a_receive_timeout(self):
        client, peer = socket.socketpair()
        message = {
            'type': 'ack',
            'data': {'ref_type': 'hello', 'ref_seq': 1, 'accepted': True},
        }
        wire = encode_frame(message)
        try:
            peer.sendall(wire[:9])
            self.assertIsNone(bridge_tcp_client._frame_recv(client, 0.01))
            peer.sendall(wire[9:])
            self.assertEqual(message, bridge_tcp_client._frame_recv(client, 0.1))
        finally:
            client.close()
            peer.close()

    def test_oversized_length_prefixed_json_is_a_protocol_failure(self):
        client, peer = socket.socketpair()
        try:
            peer.sendall(encode_frame('x' * 40))
            with mock.patch.object(bridge_tcp_client, 'MAX_FRAME_BYTES', 32):
                with self.assertRaises(Exception) as caught:
                    bridge_tcp_client._frame_recv(client, 0.1)
            self.assertEqual('ProtocolFrameError',
                             type(caught.exception).__name__)
        finally:
            client.close()
            peer.close()

    def test_connected_session_rejects_malformed_ack_then_reconnects_from_hello(self):
        bridge_tcp_client.send_mission_plan('mission-a', WAYPOINTS)

        client, peer = socket.socketpair()
        first_outcome = []

        def first_session():
            try:
                first_outcome.append(
                    ('return', bridge_tcp_client._run_connected_session(client)))
            except Exception as exc:
                first_outcome.append(('error', exc))

        thread = threading.Thread(target=first_session)
        thread.start()
        try:
            hello = recv_json_line(peer)
            peer.sendall(encode_frame(b'{malformed-json}'))
            send_fragmented_ack(peer, hello)
            thread.join(0.5)
            self.assertFalse(thread.is_alive())
            self.assertEqual('error', first_outcome[0][0])
            self.assertEqual('ProtocolFrameError',
                             type(first_outcome[0][1]).__name__)
            peer.settimeout(0.03)
            with self.assertRaises(socket.timeout):
                peer.recv(1)
        finally:
            client.close()
            peer.close()
            thread.join(1.0)

        running_state = {'sequence': 1, 'lifecycle': 'RUNNING'}
        ended_state = {'sequence': 2, 'lifecycle': 'ENDED'}
        client, peer = socket.socketpair()
        second_outcome = []
        with mock.patch.object(
                bridge_tcp_client.state_cache, 'get_state_dict',
                side_effect=[running_state, ended_state]), \
                mock.patch.object(bridge_tcp_client.state_cache,
                                  'get_vehicle_state_v2', return_value=None), \
                mock.patch.object(bridge_tcp_client.state_cache,
                                  'state_age_s', return_value=None):
            thread = threading.Thread(target=lambda: second_outcome.append(
                bridge_tcp_client._run_connected_session(client)))
            thread.start()
            try:
                hello = recv_json_line(peer)
                self.assertEqual('hello', hello['type'])
                send_fragmented_ack(peer, hello)
                mission = recv_json_line(peer)
                self.assertEqual('mission_plan', mission['type'])
                self.assertEqual('mission-a', mission['data']['mission_id'])
                send_fragmented_ack(peer, mission)
                thread.join(1.0)
                self.assertEqual([True], second_outcome)
            finally:
                client.close()
                peer.close()
                thread.join(1.0)

    def test_actual_tcp_reconnect_starts_each_session_with_hello_sequence_one(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(('127.0.0.1', 0))
        listener.listen(2)
        host, port = listener.getsockname()
        hello_sequences = []
        server_errors = []

        def serve_two_failed_sessions():
            try:
                for _ in range(2):
                    connection, _address = listener.accept()
                    try:
                        hello_sequences.append(
                            recv_json_line(connection)['seq'])
                    finally:
                        connection.close()
                bridge_tcp_client._running = False
            except Exception as exc:
                server_errors.append(exc)

        bridge_tcp_client._seq = 41
        server = threading.Thread(target=serve_two_failed_sessions)
        server.start()
        try:
            with mock.patch.object(
                    bridge_tcp_client._stop_event, 'wait', return_value=False):
                bridge_tcp_client._run(host, port)
            server.join(1.0)
        finally:
            listener.close()
            bridge_tcp_client._running = False
            server.join(1.0)

        self.assertEqual([], server_errors)
        self.assertEqual([1, 1], hello_sequences)

    def test_successful_mission_end_ack_exits_run_without_second_connector(self):
        class FakeConnector(object):
            def __init__(self, connected_socket):
                self.connected_socket = connected_socket
                self.connect_calls = []

            def connect(self, target):
                self.connect_calls.append(target)

            def __getattr__(self, name):
                return getattr(self.connected_socket, name)

        bridge_tcp_client.send_mission_plan('mission-a', WAYPOINTS)
        bridge_tcp_client.send_simulation_event('mission_end', 'mission-a')
        client, peer = socket.socketpair()
        connector = FakeConnector(client)
        peer_errors = []

        def acknowledge_successful_session():
            try:
                hello = recv_json_line(peer)
                send_fragmented_ack(peer, hello)
                mission = recv_json_line(peer)
                send_fragmented_ack(peer, mission)
                event = recv_json_line(peer)
                self.assertEqual('simulation_event', event['type'])
                self.assertEqual('mission_end', event['data']['event'])
                send_fragmented_ack(peer, event)
            except Exception as exc:
                peer_errors.append(exc)

        peer_thread = threading.Thread(target=acknowledge_successful_session)
        peer_thread.start()
        socket_factory = mock.Mock(return_value=connector)
        running_state = {'sequence': 1, 'lifecycle': 'RUNNING'}
        try:
            with mock.patch.object(bridge_tcp_client.socket, 'socket',
                                   socket_factory), \
                    mock.patch.object(
                        bridge_tcp_client._stop_event, 'wait',
                        side_effect=AssertionError(
                            'successful mission scheduled a reconnect')), \
                    mock.patch.object(
                        bridge_tcp_client.state_cache, 'get_state_dict',
                        return_value=running_state), \
                    mock.patch.object(
                        bridge_tcp_client.state_cache, 'get_vehicle_state_v2',
                        return_value=None), \
                    mock.patch.object(
                        bridge_tcp_client.state_cache, 'state_age_s',
                        return_value=None):
                bridge_tcp_client._run('debug-host', 5000)
            peer_thread.join(1.0)
        finally:
            peer.close()
            client.close()
            peer_thread.join(1.0)

        self.assertEqual([], peer_errors)
        self.assertEqual([('debug-host', 5000)], connector.connect_calls)
        self.assertEqual(1, socket_factory.call_count)

    def test_pending_mission_snapshot_is_atomic_under_queue_lock(self):
        self.assertTrue(hasattr(bridge_tcp_client,
                                '_snapshot_pending_mission'))
        snapshot = []
        finished = threading.Event()

        def read_snapshot():
            snapshot.append(bridge_tcp_client._snapshot_pending_mission())
            finished.set()

        with bridge_tcp_client._queue_lock:
            bridge_tcp_client._current_mission_id = 'mission-old'
            bridge_tcp_client._pending_waypoints = WAYPOINTS
            thread = threading.Thread(target=read_snapshot)
            thread.start()
            self.assertFalse(finished.wait(0.03))
            replacement = [dict(waypoint, x=waypoint['x'] + 1.0)
                           for waypoint in WAYPOINTS]
            bridge_tcp_client._current_mission_id = 'mission-new'
            bridge_tcp_client._pending_waypoints = replacement

        thread.join(1.0)
        self.assertEqual([('mission-new', replacement)], snapshot)

    def test_hello_and_mission_acknowledgements_gate_state_publication(self):
        self.assertTrue(hasattr(bridge_tcp_client, '_perform_handshake'))
        client, peer = socket.socketpair()
        result = []
        state = {
            'sim_time_s': 1.25,
            'north_m': 10.0, 'east_m': 20.0, 'down_m': -30.0,
            'vn_mps': 1.0, 've_mps': 2.0, 'vd_mps': 3.0,
            'q_w': 1.0, 'q_x': 0.0, 'q_y': 0.0, 'q_z': 0.0,
            'p_radps': 0.1, 'q_radps': 0.2, 'r_radps': 0.3,
        }
        packet = bridge_tcp_client.state_cache.vehicle_state_v2_from_state(
            state, 'mission-a')

        def client_side():
            accepted = bridge_tcp_client._perform_handshake(
                client, 'mission-a', WAYPOINTS, ack_timeout=0.2)
            result.append(accepted)
            if accepted:
                bridge_tcp_client._vehicle_state_sender(
                    client, 'mission-a', threading.Event(), max_frames=1)

        with mock.patch.object(bridge_tcp_client.state_cache,
                               'get_vehicle_state_v2', return_value=packet):
            thread = threading.Thread(target=client_side)
            thread.start()
            try:
                hello = recv_json_line(peer)
                self.assertEqual('hello', hello['type'])
                peer.settimeout(0.03)
                with self.assertRaises(socket.timeout):
                    peer.recv(1)
                send_fragmented_ack(peer, hello)

                mission = recv_json_line(peer)
                self.assertEqual('mission_plan', mission['type'])
                send_fragmented_ack(peer, mission)
                state_message = recv_json_line(peer)
                self.assertEqual('vehicle_state', state_message['type'])
                thread.join(1.0)
                self.assertEqual([True], result)
            finally:
                client.close()
                peer.close()
                thread.join(1.0)

    def test_rejected_or_mismatched_ack_never_sends_mission(self):
        cases = (
            {'accepted': False},
            {'ref_type': 'mission_plan'},
            {'ref_seq': -1},
        )
        for changes in cases:
            with self.subTest(changes=changes):
                client, peer = socket.socketpair()
                result = []

                def client_side():
                    result.append(bridge_tcp_client._perform_handshake(
                        client, 'mission-a', WAYPOINTS, ack_timeout=0.1))

                thread = threading.Thread(target=client_side)
                thread.start()
                try:
                    hello = recv_json_line(peer)
                    send_fragmented_ack(peer, hello, **changes)
                    thread.join(1.0)
                    self.assertEqual([False], result)
                    peer.settimeout(0.03)
                    with self.assertRaises(socket.timeout):
                        peer.recv(1)
                finally:
                    client.close()
                    peer.close()
                    thread.join(1.0)

    def test_vehicle_state_uses_exact_twenty_ms_cadence_and_protocol_fields(self):
        self.assertTrue(hasattr(bridge_tcp_client, '_vehicle_state_sender'))

        class FakeClock(object):
            def __init__(self):
                self.now = 10.0

            def monotonic(self):
                return self.now

            def sleep(self, seconds):
                self.now += seconds

        class CaptureSocket(object):
            def __init__(self, clock):
                self.clock = clock
                self.messages = []

            def sendall(self, wire):
                length = struct.unpack('>I', wire[:4])[0]
                self.messages.append((self.clock.now,
                                      json.loads(wire[4:].decode('utf-8'))))
                if length != len(wire) - 4:
                    raise AssertionError('frame length does not match payload')

        state = {
            'sim_time_s': 1.25,
            'north_m': 10.0, 'east_m': 20.0, 'down_m': -30.0,
            'vn_mps': 1.0, 've_mps': 2.0, 'vd_mps': 3.0,
            'q_w': 1.0, 'q_x': 0.0, 'q_y': 0.0, 'q_z': 0.0,
            'p_radps': 0.1, 'q_radps': 0.2, 'r_radps': 0.3,
        }
        packet = bridge_tcp_client.state_cache.vehicle_state_v2_from_state(
            state, 'mission-a')
        clock = FakeClock()
        capture = CaptureSocket(clock)
        with mock.patch.object(bridge_tcp_client.state_cache,
                               'get_vehicle_state_v2', return_value=packet):
            bridge_tcp_client._vehicle_state_sender(
                capture, 'mission-a', threading.Event(), max_frames=3,
                monotonic_fn=clock.monotonic, sleep_fn=clock.sleep)

        self.assertEqual([10.0, 10.02, 10.04],
                         [round(item[0], 2) for item in capture.messages])
        for _, message in capture.messages:
            self.assertEqual(
                {'protocol_version', 'type', 'seq', 'vehicle_id', 'data'},
                set(message))
            self.assertEqual(
                {'mission_id', 'sim_time', 'position', 'attitude', 'velocity',
                 'angular_velocity'},
                set(message['data']))
            self.assertNotIn('acceleration', message['data'])
            self.assertNotIn('rate_hz', message['data'])
            self.assertNotIn('sequence', message['data'])

    def test_optional_mission_end_is_omitted_or_strictly_acknowledged(self):
        self.assertTrue(hasattr(bridge_tcp_client, '_send_mission_end'))
        client, peer = socket.socketpair()
        try:
            self.assertTrue(bridge_tcp_client._send_mission_end(
                client, 'mission-a', enabled=False, ack_timeout=0.1))
            peer.settimeout(0.03)
            with self.assertRaises(socket.timeout):
                peer.recv(1)

            result = []
            thread = threading.Thread(target=lambda: result.append(
                bridge_tcp_client._send_mission_end(
                    client, 'mission-a', enabled=True, ack_timeout=0.2)))
            thread.start()
            event = recv_json_line(peer)
            self.assertEqual('simulation_event', event['type'])
            self.assertEqual({'event': 'mission_end', 'mission_id': 'mission-a'},
                             event['data'])
            send_fragmented_ack(peer, event)
            thread.join(1.0)
            self.assertEqual([True], result)
        finally:
            client.close()
            peer.close()
            if 'thread' in locals():
                thread.join(1.0)

    def test_connected_session_sends_mission_end_queued_during_ended_check(self):
        bridge_tcp_client.send_mission_plan('mission-a', WAYPOINTS)
        running_state = {'sequence': 1, 'lifecycle': 'RUNNING'}
        ended_state = {'sequence': 2, 'lifecycle': 'ENDED'}
        state_reads = []

        def get_state():
            state_reads.append(True)
            if len(state_reads) == 1:
                return running_state
            if len(state_reads) == 2:
                bridge_tcp_client.send_simulation_event(
                    'mission_end', 'mission-a')
            return ended_state

        client, peer = socket.socketpair()
        outcome = []
        with mock.patch.object(bridge_tcp_client.state_cache,
                               'get_state_dict', side_effect=get_state), \
                mock.patch.object(bridge_tcp_client.state_cache,
                                  'get_vehicle_state_v2', return_value=None), \
                mock.patch.object(bridge_tcp_client.state_cache,
                                  'state_age_s', return_value=None):
            thread = threading.Thread(target=lambda: outcome.append(
                bridge_tcp_client._run_connected_session(client)))
            thread.start()
            try:
                hello = recv_json_line(peer)
                send_fragmented_ack(peer, hello)
                mission = recv_json_line(peer)
                send_fragmented_ack(peer, mission)

                peer.settimeout(1.0)
                event = recv_json_line(peer)
                self.assertEqual('simulation_event', event['type'])
                self.assertEqual(
                    {'event': 'mission_end', 'mission_id': 'mission-a'},
                    event['data'])
                send_fragmented_ack(peer, event)
                thread.join(1.0)
                self.assertEqual([True], outcome)
            finally:
                client.close()
                peer.close()
                thread.join(1.0)

    def test_connected_session_keeps_mission_for_reserved_late_mission_end(self):
        finish_checked = threading.Event()

        class ObservedReservations(dict):
            def values(self):
                # _finish_mission_if_no_queued_end reaches reservations only
                # after it has observed that the event queue has no matching
                # mission_end.  Resolution then blocks on _queue_lock until
                # the finish decision has retained the mission.
                finish_checked.set()
                return super().values()

        reservations = ObservedReservations()
        with mock.patch.object(bridge_tcp_client, '_event_reservations',
                               reservations):
            bridge_tcp_client.send_mission_plan('mission-a', WAYPOINTS)
            reservation = bridge_tcp_client.reserve_simulation_event(
                'mission_end', 'mission-a')
            running_state = {'sequence': 1, 'lifecycle': 'RUNNING'}
            ended_state = {'sequence': 2, 'lifecycle': 'ENDED'}

            client, peer = socket.socketpair()
            outcome = []
            with mock.patch.object(
                    bridge_tcp_client.state_cache, 'get_state_dict',
                    side_effect=[running_state, ended_state, ended_state]), \
                    mock.patch.object(bridge_tcp_client.state_cache,
                                      'get_vehicle_state_v2', return_value=None), \
                    mock.patch.object(bridge_tcp_client.state_cache,
                                      'state_age_s', return_value=None):
                thread = threading.Thread(target=lambda: outcome.append(
                    bridge_tcp_client._run_connected_session(client)))
                thread.start()
                try:
                    hello = recv_json_line(peer)
                    send_fragmented_ack(peer, hello)
                    mission = recv_json_line(peer)
                    send_fragmented_ack(peer, mission)

                    self.assertTrue(finish_checked.wait(1.0))
                    with bridge_tcp_client._queue_lock:
                        self.assertEqual([], bridge_tcp_client._event_queue)
                    bridge_tcp_client.resolve_simulation_event(
                        reservation, accepted=True)

                    peer.settimeout(1.0)
                    event = recv_json_line(peer)
                    self.assertEqual('simulation_event', event['type'])
                    self.assertEqual(
                        {'event': 'mission_end', 'mission_id': 'mission-a'},
                        event['data'])
                    send_fragmented_ack(peer, event)
                    thread.join(1.0)
                    self.assertEqual([True], outcome)
                finally:
                    client.close()
                    peer.close()
                    thread.join(1.0)


if __name__ == '__main__':
    unittest.main()
