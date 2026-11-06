#!/usr/bin/env python3
"""Execute each generated recipient's silicon gate; no hardware access."""
import argparse
from pathlib import Path
import subprocess
import tempfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel',type=Path)
    parser.add_argument('--profile',choices=('t512n','lym10k'),required=True)
    args=parser.parse_args()
    source=(args.kernel/'drivers/power/supply/bq2560x-charger.c').read_text()
    assert 't551m_charger_supported' not in source, 'T551M silicon gate leaked into recipient'
    label='T512N' if args.profile=='t512n' else 'LYM-10K'
    lines=source.splitlines()
    gates=[lines[i-1].strip() for i,line in enumerate(lines)
           if 'unsupported '+label+' charger ID' in line]
    assert len(gates)==1 and gates[0].startswith('if (') and gates[0].endswith(') {'), gates
    expression=gates[0][4:-3]
    expected='id == 0x11' if args.profile=='t512n' else '(id == 0x11 || id == 0x12)'
    harness='''#include <assert.h>
struct client { unsigned addr; };
static int accepted(unsigned addr, unsigned val) {
 struct client storage={addr}; struct client *client=&storage;
 return !(EXPRESSION);
}
int main(void) {
 for (unsigned addr=0;addr<128;addr++)
  for (unsigned id=0;id<256;id++)
   assert(accepted(addr,id)==(addr==0x6b && EXPECTED));
}
'''.replace('EXPRESSION',expression).replace('EXPECTED',expected)
    with tempfile.TemporaryDirectory(prefix='bq-profile-') as directory:
        root=Path(directory);path=root/'test.c';path.write_text(harness)
        subprocess.run(['cc','-Wall','-Wextra','-Werror',str(path),'-o',str(root/'test')],check=True)
        subprocess.run([str(root/'test')],check=True)
    print('PASS:',args.profile,'generated silicon gate: all 32768 address/ID combinations')


if __name__=='__main__':main()
