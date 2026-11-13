"""Client for the protected local HIL telemetry epoch handoff."""
import json
import socket


DEFAULT_SOCKET_PATH = '/run/hil/telemetry-control.sock'
MAX_MESSAGE_BYTES = 4096


class TelemetryEpochClient:
    def __init__(self, path=DEFAULT_SOCKET_PATH, timeout_s=1.0):
        self.path = path
        self.timeout_s = timeout_s

    def advance(self, reset_id, run_id):
        request = {'cmd': 'telemetry_epoch_advance', 'reset_id': reset_id, 'run_id': run_id,
                   'model_step': 0, 'sim_time_us': 0}
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(self.timeout_s)
            client.connect(self.path)
            client.sendall(json.dumps(request, separators=(',', ':')).encode('utf-8'))
            raw = client.recv(MAX_MESSAGE_BYTES)
        response = json.loads(raw.decode('utf-8'))
        if response.get('status') != 'SUCCESS' or type(response.get('epoch')) is not int:
            raise OSError('telemetry epoch handoff rejected: {}'.format(response.get('detail', 'unknown')))
        return response['epoch']
