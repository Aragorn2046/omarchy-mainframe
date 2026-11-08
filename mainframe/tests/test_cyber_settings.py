import importlib.util
from pathlib import Path
import unittest
import tempfile
from unittest.mock import patch
import json


spec = importlib.util.spec_from_file_location('config_manager_cyber', Path(__file__).resolve().parents[1] / 'config_manager.py')
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class CyberSettingsTest(unittest.TestCase):
    def test_old_and_new_settings(self):
        for settings in ({}, {'overviewView': 'agents', 'showUnavailable': False},
                         {'style': 'cyberpunk', 'cyber': {'hudFrames': True, 'neonGlow': False}}):
            self.assertEqual(manager.validate('settings', settings), settings)

    def test_invalid_style_and_switches(self):
        for settings in ({'style': None}, {'style': 'other'}, {'style': True},
                         {'cyber': None}, {'cyber': []}, {'cyber': {'hudFrames': 1}},
                         {'cyber': {'neonGlow': 'true'}}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                manager.validate('settings', settings)

    def test_write_rejects_non_objects_before_merging(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(manager, 'CONFIG', Path(directory)):
            for data in (None, [], 'invalid', 3, {'cyber': None}, {'cyber': []}, {'cyber': 'invalid'}):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    manager.write('settings', data)
            self.assertFalse((Path(directory) / 'settings.json').exists())

    def test_write_preserves_existing_settings(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(manager, 'CONFIG', Path(directory)):
            path = Path(directory) / 'settings.json'
            path.write_text(json.dumps({'future': 42, 'style': 'cyberpunk', 'cyber': {'hudFrames': False}}))
            manager.write('settings', {'showUnavailable': True})
            self.assertEqual(json.loads(path.read_text()), {'future': 42, 'style': 'cyberpunk',
                                                            'cyber': {'hudFrames': False}, 'showUnavailable': True})
            manager.write('settings', {'cyber': {'neonGlow': True}})
            self.assertEqual(json.loads(path.read_text())['cyber'], {'hudFrames': False, 'neonGlow': True})


if __name__ == '__main__':
    unittest.main()
