"""Downloader checks use in-memory fixtures, never a camera or model service."""
import hashlib
import importlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ModelDownloadTests(unittest.TestCase):
    def module(self):
        self.assertTrue((ROOT / 'scripts/download_models.py').is_file(),
                        'Missing reproducible official-model downloader')
        return importlib.import_module('scripts.download_models')

    def test_downloads_verified_model_to_destination(self):
        module = self.module()
        content = b'verified test fixture, not a real model'
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'models/face_landmarker.task'
            with patch.object(module, 'EXPECTED_SHA256', hashlib.sha256(content).hexdigest()), \
                 patch.object(module, 'EXPECTED_SIZE', len(content)), \
                 patch.object(module, 'urlopen', return_value=io.BytesIO(content)) as request:
                result = module.fetch_model(destination)
            self.assertEqual(result, destination)
            self.assertEqual(destination.read_bytes(), content)
            self.assertEqual(request.call_count, 1)
            self.assertGreater(request.call_args.kwargs['timeout'], 0)

    def test_oversize_response_is_rejected_without_writing(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'face_landmarker.task'
            with patch.object(module, 'urlopen', return_value=io.BytesIO(b'wrong model')):
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    module.fetch_model(destination)
            self.assertFalse(destination.exists())

    def test_existing_valid_model_needs_no_network(self):
        module = self.module()
        content = b'already verified fixture'
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'face_landmarker.task'
            destination.write_bytes(content)
            with patch.object(module, 'EXPECTED_SHA256', hashlib.sha256(content).hexdigest()), \
                 patch.object(module, 'EXPECTED_SIZE', len(content)), \
                 patch.object(module, 'urlopen') as request:
                self.assertEqual(module.fetch_model(destination), destination)
                request.assert_not_called()

    def test_existing_invalid_model_is_not_overwritten(self):
        module = self.module()
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / 'face_landmarker.task'
            destination.write_bytes(b'user file')
            with patch.object(module, 'urlopen') as request:
                with self.assertRaisesRegex(ValueError, 'berbeda checksum'):
                    module.fetch_model(destination)
                request.assert_not_called()
            self.assertEqual(destination.read_bytes(), b'user file')


if __name__ == '__main__':
    unittest.main()
