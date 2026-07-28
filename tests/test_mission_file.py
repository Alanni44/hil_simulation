import json
import pathlib
import sys
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'python_services'))

from mission_file import load_mission, to_ue4_waypoints  # noqa


class MissionFileTests(unittest.TestCase):
    def test_default_mission_is_takeoff_z_and_landing(self):
        mission = load_mission(str(ROOT / 'missions' / 'z_mission.json'))
        self.assertEqual(-20.0, mission['waypoints'][0]['down_m'])
        self.assertEqual([40.0, 0.0, 40.0],
                         [item['north_m'] for item in mission['waypoints'][1:]])
        self.assertEqual(0.0, mission['landing']['down_m'])
        self.assertEqual({'id', 'x', 'y', 'height', 'target_speed'},
                         set(to_ue4_waypoints(mission)[0]))

    def test_load_mission_rejects_missing_mission_id(self):
        with self.assertRaises(ValueError):
            self._load_json(self._valid_mission(mission_id=None))

    def test_load_mission_rejects_non_finite_number(self):
        mission = self._valid_mission()
        mission['waypoints'][0]['north_m'] = float('nan')
        with self.assertRaises(ValueError):
            self._load_json(mission)

    def test_load_mission_rejects_fewer_than_two_waypoints(self):
        mission = self._valid_mission()
        mission['waypoints'] = mission['waypoints'][:1]
        with self.assertRaises(ValueError):
            self._load_json(mission)

    def test_load_mission_rejects_non_positive_speed(self):
        mission = self._valid_mission()
        mission['waypoints'][0]['speed_mps'] = 0.0
        with self.assertRaises(ValueError):
            self._load_json(mission)

    @staticmethod
    def _valid_mission(mission_id='mission-a'):
        return {
            'mission_id': mission_id,
            'completion_radius_m': 1.0,
            'waypoints': [
                {'id': 'TAKEOFF', 'north_m': 0.0, 'east_m': 0.0,
                 'down_m': -20.0, 'speed_mps': 2.0},
                {'id': 'Z1', 'north_m': 40.0, 'east_m': 0.0,
                 'down_m': -20.0, 'speed_mps': 5.0},
            ],
            'landing': {'id': 'LAND', 'north_m': 40.0, 'east_m': 0.0,
                        'down_m': 0.0, 'speed_mps': 1.5},
        }

    def _load_json(self, value):
        handle = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
        try:
            json.dump(value, handle)
            handle.close()
            return load_mission(handle.name)
        finally:
            path = pathlib.Path(handle.name)
            if path.exists():
                path.unlink()


if __name__ == '__main__':
    unittest.main()
