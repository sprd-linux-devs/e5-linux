#!/usr/bin/env python3
"""Read-only proof of Y60's DVFS payload identity with the audited K1 SML.

No execution, SMC calls, device access or firmware writes. Both complete Y60
images stay identified separately; payload equality never bypasses runtime
verification of the two complete SML partitions.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

REFERENCE='efc2e6cf3a83a1dbbedecbea12673a7320520632b7b3f59c9072276f9b24d5eb'
IMAGES={
    '7755b6ae0282e308eab179710401bfc2a16f86e3658936cdf79ee581fda0a3a9': 'CP21.20240108.0S.GCY',
    '355cf12fa6fa336c013ac94ace426bceb094ed5c27b95995e7ba1628c6d0348b': 'CP21.20240304.1S.GCY',
}


def payload(data):
    if len(data)!=1048576 or data[:8]!=b'DHTB\x01\0\0\0':
        raise ValueError('Expected the original complete 1 MiB SML partition')
    size=struct.unpack_from('<I',data,0x30)[0]
    if size!=0x224f0:raise ValueError('Unexpected Y60/K1 SML payload size')
    blob=data[512:512+size]
    if hashlib.sha256(blob).digest()!=data[8:40]:
        raise ValueError('DHTB payload hash mismatch')
    return blob


def verify(reference,images):
    if hashlib.sha256(reference).hexdigest()!=REFERENCE:
        raise ValueError('Reference is not the previously audited original K1 B SML')
    expected=payload(reference)
    rows=[]
    for data in images:
        digest=hashlib.sha256(data).hexdigest()
        if digest not in IMAGES:raise ValueError('Not an audited complete Y60 stock SML')
        if payload(data)!=expected:raise ValueError('Y60 DVFS executable/data payload differs from K1')
        rows.append(dict(build=IMAGES[digest],sha256=digest,payload_equal=True))
    return dict(reference_sha256=REFERENCE,payload_bytes=len(expected),
                payload_sha256=hashlib.sha256(expected).hexdigest(),
                images=rows,hardware_validated=False)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--images',type=Path,nargs='+',required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    for path in [args.reference,*args.images]:
        if args.output.resolve().is_relative_to(path.parent.resolve()):
            p.error('Do not write a report inside the firmware backup')
    report=verify(args.reference.read_bytes(),[path.read_bytes() for path in args.images])
    args.output.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print('Y60 complete image identities, DHTB checksum and entire K1 executable/data payload match: PASS')
