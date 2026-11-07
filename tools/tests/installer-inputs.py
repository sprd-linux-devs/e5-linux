"""Pinned installer downloads never replace a modified cache or trust bad bytes."""
import hashlib
import io
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

TOP = Path(__file__).resolve().parents[2]
api = runpy.run_path(str(TOP/'tools/prepare-installer-inputs.py'))
fetch = api['fetch']


class InstallerDownloads(unittest.TestCase):
    def record(self, content):
        return {'url': 'https://example.test/installer.tar.gz', 'sha256': hashlib.sha256(content).hexdigest()}

    def test_verified_download_reuses_exact_cache_without_network(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)/'download'
            with patch('urllib.request.urlopen', return_value=io.BytesIO(b'correct')) as request:
                self.assertEqual(fetch(self.record(b'correct'), destination), destination)
                fetch(self.record(b'correct'), destination)
                self.assertEqual(request.call_count, 1)

    def test_changed_cache_is_preserved_and_never_redownloaded(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)/'download'; destination.write_bytes(b'local changes')
            with patch('urllib.request.urlopen') as request:
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'): fetch(self.record(b'correct'), destination)
                request.assert_not_called()
            self.assertEqual(destination.read_bytes(), b'local changes')

    def test_bad_download_is_retained_as_partial_and_http_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            destination = Path(temp)/'download'
            with patch('urllib.request.urlopen', return_value=io.BytesIO(b'wrong')):
                with self.assertRaisesRegex(ValueError, 'checksum mismatch'): fetch(self.record(b'correct'), destination)
            self.assertFalse(destination.exists())
            self.assertEqual(destination.with_name('download.partial').read_bytes(), b'wrong')
            with self.assertRaisesRegex(ValueError, 'HTTPS'):
                fetch(dict(self.record(b'correct'), url='http://example.test/insecure'), destination)


if __name__ == '__main__': unittest.main()
