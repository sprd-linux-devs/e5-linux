#!/usr/bin/env python3
"""Compile the Y60 PA callback with a fake profile API; no hardware access."""
from pathlib import Path
import argparse
import os
import runpy
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
AUDIO = runpy.run_path(str(HERE/'audio.py'))
SOURCE = None


class Speaker(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        global SOURCE
        if SOURCE is None:
            kernel = os.environ.get('Y60_TEST_KERNEL')
            if not kernel:
                raise unittest.SkipTest('Set Y60_TEST_KERNEL to the prepared Y60 source')
            SOURCE = (Path(kernel)/AUDIO['RELATIVE']).read_text()

    def test_only_the_y60_callback_changes(self):
        changed = AUDIO['transform'](SOURCE)
        self.assertEqual(AUDIO['transform'](changed), changed)
        self.assertIn('{"general_speaker", hook_general_spk, EN_LEVEL}', changed)
        self.assertNotIn('hook_gpio_pulse_control(', changed)
        # The original DT GPIO lifecycle, other hook, table, and register
        # interfaces must remain byte-identical, including the initial level.
        start = SOURCE.index('extern int gPA_type;')
        declaration = 'extern int aw87xxx_set_profile(int dev_index, char *profile);\n'
        expected = SOURCE[start:].replace(declaration, '', 1)
        self.assertEqual(changed[changed.index('extern int gPA_type;'):], expected)

    def test_unknown_table_is_rejected(self):
        if AUDIO['MARKER'] in SOURCE:
            self.skipTest('already prepared Y60 source')
        with self.assertRaises(ValueError):
            AUDIO['transform'](SOURCE.replace('"general_speaker"', '"unknown_speaker"'))

    def test_real_callback_uses_stock_music_off_and_reports_failure(self):
        changed = AUDIO['transform'](SOURCE)
        start = changed.index('static int hook_general_spk(')
        callback = changed[start:changed.index('\n}\n', start)+3]
        with tempfile.TemporaryDirectory(prefix='y60-pa-test-') as temporary:
            root = Path(temporary)
            program = root/'pa.c'
            program.write_text(r'''
#include <assert.h>
#include <string.h>
#include <errno.h>
#define HOOK_OK 1
#define pr_err(...) ((void)0)
static int result,calls;
static const char *profile;
static int aw87xxx_set_profile(int index,char *name) {
 assert(index==0);profile=name;calls++;return result;
}
''' + callback + r'''
int main(void) {
 assert(hook_general_spk(0,1)==HOOK_OK&&calls==1&&!strcmp(profile,"Music"));
 assert(hook_general_spk(0,0)==HOOK_OK&&calls==2&&!strcmp(profile,"Off"));
 result=-EIO;
 assert(hook_general_spk(0,1)==-EIO&&calls==3);
 result=-EAGAIN;
 assert(hook_general_spk(0,0)==-EAGAIN&&calls==4);
 result=1;
 assert(hook_general_spk(0,1)==HOOK_OK);
 return 0;
}
''')
            binary = root/'pa'
            subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',
                            '-Wno-unused-parameter','-fsanitize=undefined',
                            str(program),'-o',str(binary)], check=True)
            subprocess.run([str(binary)], check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--kernel', type=Path, required=True)
    args, remaining = parser.parse_known_args()
    SOURCE = (args.kernel/AUDIO['RELATIVE']).read_text()
    unittest.main(argv=[__file__,*remaining])
