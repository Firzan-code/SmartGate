"""User-facing Arduino layout contract. No hardware or credentials are read."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
SKETCH = ROOT / 'smart_gate_full/firmware/tes_dua_model_esp32s3'
INO = SKETCH / 'tes_dua_model_esp32s3.ino'


class SingleFileFirmwareTests(unittest.TestCase):
    def test_arduino_folder_has_only_one_ino(self):
        entries = sorted(p.name for p in SKETCH.iterdir() if p.is_file())
        self.assertEqual(entries, [INO.name],
                         'Sketch kuliah harus satu .ino; backup/panduan di luar folder')

    def test_user_configuration_is_at_the_top(self):
        # Never read a secrets file. The only source under test is the new .ino.
        top = '\n'.join(INO.read_text(encoding='utf-8').splitlines()[:35])
        for name in ('WIFI_SSID', 'WIFI_PASSWORD', 'SERVER_IP'):
            self.assertRegex(top, rf'(?m)^#define {name} "[^"\n]*"\s*$', name)
        self.assertIn('Jangan bagikan', top)

    def test_source_is_standalone_without_project_headers(self):
        text = INO.read_text(encoding='utf-8')
        self.assertNotRegex(text, r'(?m)^\s*#\s*include\s*"')
        self.assertNotIn('secrets.h', text)
        self.assertIn('class Packetizer', text)
        self.assertIn('void setup()', text)
        self.assertIn('void loop()', text)
        self.assertIn('adc_continuous_read', text)


if __name__ == '__main__':
    unittest.main()
