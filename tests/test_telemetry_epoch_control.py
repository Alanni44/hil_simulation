import pathlib
import struct
import sys
import tempfile
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))
# This focused socket/cache test does not exercise YAML configuration loading.
# Keep it runnable in the hermetic runtime interpreter used by CI.
sys.modules.setdefault('config_loader', types.SimpleNamespace(CONFIG={'logging': {}}))

from shared import state_cache  # noqa: E402
from shared.flight_state import FLIGHT_STATE_FIELDS, FLIGHT_STATE_V2_FORMAT  # noqa: E402
from telemetry_epoch_control import TelemetryEpochServer  # noqa: E402
from icd_gateway.telemetry_epoch_client import TelemetryEpochClient  # noqa: E402


def packet(sequence, sim_time_s, lifecycle):
    state = {
        'version': 2, 'sequence': sequence, 'sim_time_s': sim_time_s,
        'north_m': 0.0, 'east_m': 0.0, 'down_m': 0.0,
        'vn_mps': 0.0, 've_mps': 0.0, 'vd_mps': 0.0,
        'q_w': 1.0, 'q_x': 0.0, 'q_y': 0.0, 'q_z': 0.0,
        'p_radps': 0.0, 'q_radps': 0.0, 'r_radps': 0.0,
        'ax_mps2': 0.0, 'ay_mps2': 0.0, 'az_mps2': 0.0,
        'airborne': 0, 'lifecycle': lifecycle, 'reserved': 0,
    }
    return struct.pack(FLIGHT_STATE_V2_FORMAT, *(state[name] for name in FLIGHT_STATE_FIELDS))


class TelemetryEpochControlTests(unittest.TestCase):
    def test_verified_reset_opens_new_epoch_and_requires_zero_baseline(self):
        # Start with an old run's high watermark.
        state_cache.advance_epoch_after_verified_reset()
        state_cache.update(packet(0, 0.0, 5))
        state_cache.update(packet(206736, 206.736, 0))
        with tempfile.TemporaryDirectory() as directory:
            path = str(pathlib.Path(directory) / 'telemetry.sock')
            server = TelemetryEpochServer(path).start()
            try:
                epoch = TelemetryEpochClient(path).advance('reset-1', 'run-2')
                self.assertGreaterEqual(epoch, 1)
                with self.assertRaisesRegex(ValueError, 'awaiting reset baseline'):
                    state_cache.update(packet(206737, 206.737, 0))
                # The C-core sender is periodic, so an immediate PREPARE and
                # START may make the first observed new-epoch sample nonzero.
                state_cache.update(packet(20, 0.020, 0))
                current = state_cache.get_normalized_state()
                self.assertEqual(20, current['sequence'])
                self.assertEqual(0.020, current['sim_time_s'])
                self.assertFalse(state_cache.telemetry_epoch_status()['awaiting_reset_baseline'])
                # Replaying the same reset is idempotent and must not create another epoch.
                self.assertEqual(epoch, TelemetryEpochClient(path).advance('reset-1', 'run-2'))
            finally:
                server.close()


if __name__ == '__main__':
    unittest.main()
