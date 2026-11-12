import tempfile
import unittest
from pathlib import Path

from app.recording_registry import RecordingRegistry


class RecordingRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = RecordingRegistry(self.root)
        self.prefix = 'mentalab_Explore_AABH_20261110_120000_aabbccdd'
        self.exg = self.root / f'{self.prefix}_ExG.csv'
        self.exg.write_text('timestamp,CH1\n0,1.0\n', encoding='utf-8')

    def tearDown(self):
        self.temp.cleanup()

    def test_legacy_discovery_and_restart(self):
        row = self.registry.list_recordings()[0]
        self.assertTrue(row['legacy'])
        self.assertFalse(row['patientLinked'])
        self.assertEqual(self.registry.resolve_file(row['recordingId'], self.exg.name).resolve(),self.exg.resolve(),)
        restarted = RecordingRegistry(self.root)
        self.assertEqual(restarted.list_recordings()[0]['recordingId'], row['recordingId'])

    def test_manifest_persists_full_id_after_restart(self):
        rid = '12345678-1234-1234-1234-123456789abc'
        self.registry.register(rid, self.root / self.prefix, '2026-11-10T12:00:00Z')
        self.registry.finalize(rid, self.root / self.prefix, '2026-11-10T12:01:00Z')
        restarted = RecordingRegistry(self.root)
        row = restarted.list_recordings()[0]
        self.assertEqual(row['recordingId'], rid)
        self.assertFalse(row['legacy'])
        self.assertEqual(restarted.resolve_file(rid, self.exg.name).resolve(),self.exg.resolve(),)

    def test_bad_name_and_id_rejected(self):
        rid = self.registry.list_recordings()[0]['recordingId']
        for name in ('../secret.csv', 'oops.txt', '/tmp/secret.csv', 'other_ExG.csv'):
            with self.assertRaises(ValueError):
                self.registry.resolve_file(rid, name)
        with self.assertRaises(FileNotFoundError):
            self.registry.resolve_file('wrong-id', self.exg.name)

    def test_symlink_not_exposed(self):
        self.exg.unlink()
        other = self.root / 'external.txt'
        other.write_text('secret')
        self.exg.symlink_to(other)
        self.assertEqual(self.registry.list_recordings(), [])


if __name__ == '__main__':
    unittest.main()
