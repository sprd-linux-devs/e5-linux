"""LK command-line compatibility, without SSH, storage writes or hardware."""
from pathlib import Path
import runpy
import struct
import unittest

TOP = Path(__file__).resolve().parents[2]
command = runpy.run_path(str(TOP/'tools/e5-update.py'))['partition_update_command']


class PartitionCommand(unittest.TestCase):
    def image(self, arguments):
        image = bytearray(4096); image[:8] = b'ANDROID!'
        struct.pack_into('<I', image, 40, 4)
        image[44:1580] = arguments.ljust(1536, b'\0')
        return image

    def test_existing_unpadded_images_keep_the_previous_update_command_exactly(self):
        self.assertEqual(command(self.image(b'e5.part_v=2')), b'e5.part_v=2 e5.root=part e5.part_update=1')

    def test_lym10k_and_existing_t512n_padding_survive_an_offline_update(self):
        prefix = b'e5.lkpad=0000000000 '
        original = self.image(prefix+b'e5.part_v=2')
        before = bytes(original)
        value = command(original)
        self.assertEqual(len(prefix), 20)
        self.assertEqual(value[20:], b'e5.part_v=2 e5.root=part e5.part_update=1')
        self.assertEqual(bytes(original), before)

    def test_invalid_boot_headers_are_refused(self):
        for value in (b'', b'ANDROID!', bytes(4096)):
            with self.assertRaisesRegex(ValueError, 'boot-v4'): command(value)


if __name__ == '__main__': unittest.main()
