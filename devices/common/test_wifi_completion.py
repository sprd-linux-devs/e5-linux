#!/usr/bin/env python3
"""Execute actual SDIO completion dispatch with work-allocation failure."""
import json
from pathlib import Path
import runpy
import shutil
import subprocess
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
TOP = HERE.parents[1]
BASE = Path('drivers/unisoc_platform/sprd_wlan_combo/sc2355/sdio.c')
api = runpy.run_path(str(HERE / 'wifi-completion.py'))


def function(text):
    start = text.index('int sc2355_add_topop_list(')
    return text[start:text.index('\n}', start) + 2]


HARNESS = r'''
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <stdbool.h>
typedef unsigned char u8;
#define wl_err(...) ((void)0)
#define SPRD_POP_MBUF 12
struct mbuf_t {int finished,reclaimed;};
struct pop_work {int chn;void *head,*tail;int num;};
struct sprd_work {void *vif;int id;u8 data[sizeof(struct pop_work)];};
struct sprd_hif {void *priv;};
static struct sprd_hif hif;
static int allocation_fails,reclaimed;
static struct sprd_work *pending;
static struct sprd_hif *sc2355_get_hif(void){return &hif;}
static struct sprd_work *sprd_alloc_work(int n){assert(n==sizeof(struct pop_work));return allocation_fails?NULL:calloc(1,sizeof(struct sprd_work));}
static void sc2355_handle_pop_list(void *data){
    struct pop_work *pop=data;struct mbuf_t *m=pop->head;
    assert(pop->chn==9 && pop->head==pop->tail && pop->num==1);
    assert(m->finished && !m->reclaimed);m->reclaimed=1;reclaimed++;
}
static void sprd_queue_work(void *p,struct sprd_work *w){assert(!pending && !w->vif && w->id==SPRD_POP_MBUF);pending=w;}
/* COMPLETION */
int main(int argc,char **argv){
    struct mbuf_t first={1,0},second={1,0};
    allocation_fails=1;int rc=sc2355_add_topop_list(9,&first,&first,1);
    if(argc>1){assert(rc==-1 && !first.reclaimed && !pending);return 0;}
    assert(rc==0 && first.reclaimed && !pending && reclaimed==1);
    allocation_fails=0;
    assert(sc2355_add_topop_list(9,&second,&second,1)==0);
    assert(pending && !second.reclaimed);
    /* An OOM completion must not lose buffers while another pop is deferred. */
    struct mbuf_t third={1,0};allocation_fails=1;
    assert(sc2355_add_topop_list(9,&third,&third,1)==0 && third.reclaimed);
    sc2355_handle_pop_list(pending->data);free(pending);pending=NULL;
    assert(second.reclaimed && reclaimed==3);
    return 0;
}
'''


class Completion(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='e5-wifi-completion-')
        self.root = Path(self.temp.name)
        self.path = self.root / BASE
        self.path.parent.mkdir(parents=True)
        self.path.write_bytes((TOP / 'devices/fixtures/sc2355-pop-list.c').read_bytes())

    def tearDown(self):
        self.temp.cleanup()

    def execute(self, source, old=False):
        if not shutil.which('cc'):
            self.skipTest('host C compiler required')
        path = self.root / 'case.c'
        path.write_text(HARNESS.replace('/* COMPLETION */', function(source)))
        binary = self.root / 'case'
        subprocess.run(['cc', '-std=gnu11', '-Wall', '-Werror',
                        '-fsanitize=address,undefined', '-fno-pie', '-no-pie',
                        str(path), '-o', str(binary)], check=True, capture_output=True)
        subprocess.run([str(binary)] + (['old'] if old else []), check=True,
                       capture_output=True, timeout=10)

    def test_reproduces_lost_completion_and_preserves_normal_deferred_path(self):
        self.execute(self.path.read_text(), old=True)
        api['apply'](self.root)
        self.execute(self.path.read_text())
        before = self.path.read_bytes()
        api['apply'](self.root)
        self.assertEqual(before, self.path.read_bytes())

    def test_unknown_source_fails_without_partial_write(self):
        self.path.write_text(self.path.read_text().replace('return -1;', 'return -2;'))
        before = self.path.read_bytes()
        with self.assertRaises(ValueError):
            api['apply'](self.root)
        self.assertEqual(before, self.path.read_bytes())

    def test_all_registered_models_accept_the_completion_fix(self):
        workspace = Path('/home/kano/openwrt-build')
        config = json.loads((TOP / 'tools/build-layout.json').read_text())
        lower = workspace / 'sources/e5-kernel'
        if not lower.is_dir():
            self.skipTest('registered local source caches unavailable')
        for model in config['profiles']:
            with self.subTest(model=model):
                native = config.get('native_kernel_builds', {}).get(model)
                source = Path(native['source'].format(workspace=workspace)) if native else workspace / 'kernel-views' / model / 'upper'
                original = source / BASE
                if not original.is_file():
                    original = lower / BASE
                # Only the real production completion function is required by this shim.
                self.path.write_text(function(original.read_text()))
                api['apply'](self.root)
                self.execute(self.path.read_text())
        self.assertIn("common') / 'wifi-completion.py'", (TOP / 'devices/wifi-common.py').read_text())


if __name__ == '__main__':
    unittest.main()
