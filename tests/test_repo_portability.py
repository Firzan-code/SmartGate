"""Keep distributable tests independent of the developer's home directory."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepoPortabilityTests(unittest.TestCase):
    def test_camera_test_has_no_hardcoded_developer_scratch(self):
        source = (ROOT / 'tests/test_run_camera.py').read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'C:[/\\]Users[/\\][^\s\n]+', source),
                          'Camera test must use TMPDIR/default temp, not a developer home path')


if __name__ == '__main__':
    unittest.main()
