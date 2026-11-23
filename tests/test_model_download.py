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

    def test_ast_files_are_downloaded_and_verified(self):
        module = self.module()
        files = {'model.onnx': b'onnx fixture', 'labels.json': b'{"id2label": {}}'}
        pinned = {name: (len(data), hashlib.sha256(data).hexdigest()) for name, data in files.items()}

        def serve(url, timeout):
            self.assertTrue(url.startswith(module.AST_RELEASE_URL))
            self.assertGreater(timeout, 0)
            return io.BytesIO(files[url.rsplit('/', 1)[1]])

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'siren_ast_v2'
            with patch.object(module, 'AST_FILES', pinned), \
                 patch.object(module, 'urlopen', side_effect=serve) as request:
                self.assertEqual(module.fetch_ast_model(directory), directory)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(sorted(p.name for p in directory.iterdir()), sorted(files))
            for name, data in files.items():
                self.assertEqual((directory / name).read_bytes(), data)

    def test_oversized_ast_download_is_bounded_and_leaves_no_partial_file(self):
        module = self.module()

        class Response(io.BytesIO):
            consumed = 0

            def read(self, size=-1):
                data = super().read(size)
                self.consumed += len(data)
                return data

        response = Response(b'right, plus trailing bytes')
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'siren_ast_v2'
            with patch.object(module, 'AST_FILES', {'model.onnx': (5, hashlib.sha256(b'right').hexdigest())}), \
                 patch.object(module, 'urlopen', return_value=response):
                with self.assertRaisesRegex(ValueError, 'checksum'):
                    module.fetch_ast_model(directory)
            self.assertEqual(list(directory.iterdir()), [])
            self.assertEqual(response.consumed, 6)

    def test_lfs_pointer_gets_actionable_message_and_is_kept(self):
        module = self.module()
        pointer = b'version https://git-lfs.github.com/spec/v1\noid sha256:abc\nsize 171407125\n'
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / 'siren_ast_v2'
            directory.mkdir()
            (directory / 'model.onnx').write_bytes(pointer)
            with patch.object(module, 'AST_FILES', {'model.onnx': (5, hashlib.sha256(b'right').hexdigest())}), \
                 patch.object(module, 'urlopen') as request:
                with self.assertRaisesRegex(ValueError, 'git lfs pull'):
                    module.fetch_ast_model(directory)
                request.assert_not_called()
            self.assertEqual((directory / 'model.onnx').read_bytes(), pointer)

    def test_ast_model_is_tracked_with_lfs_not_ignored(self):
        attributes = (ROOT / '.gitattributes').read_text(encoding='utf-8')
        self.assertIn('ml_engine/models/siren_ast_v2/*.onnx filter=lfs diff=lfs merge=lfs -text', attributes)
        ignored = [line.strip() for line in (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()]
        self.assertNotIn('ml_engine/models/siren_ast_v2/', ignored)

    def test_pinned_ast_files_cover_runtime_requirements(self):
        module = self.module()
        self.assertTrue({'siren_ast_fp16.onnx', 'labels.json', 'preprocessor_config.json'} <= set(module.AST_FILES))
        self.assertTrue(module.AST_RELEASE_URL.startswith(
            'https://github.com/Firzan-code/SmartGate/releases/download/'))
        self.assertEqual(module.DEFAULT_AST_DIR, ROOT / 'ml_engine/models/siren_ast_v2')


if __name__ == '__main__':
    unittest.main()
