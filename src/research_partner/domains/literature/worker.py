"""One host-owned HTTP request. No Store, model, arbitrary URL or retry."""
import base64
import ctypes
import json
import os
import signal
import sys
from research_partner.domains.literature.literature import Literature
from research_partner.storage.store import Problem


def main():
    # This runtime already relies on Linux /proc process identity. The worker
    # must die if its host disappears, even while libc DNS is blocked.
    expected_parent=int(sys.argv[1])
    if ctypes.CDLL(None,use_errno=True).prctl(1,signal.SIGKILL,0,0,0)!=0 or os.getppid()!=expected_parent:
        raise SystemExit('Cannot establish owning-host death signal')
    try:
        job=json.loads(sys.stdin.read(8192))
        fetched=Literature(None).fetch(job['query'],job['limit'],max_bytes=job['max_bytes'],timeout=job['timeout_seconds'])
        result={k:v for k,v in fetched.items() if k not in {'raw','items'}}
        result['raw_base64']=base64.b64encode(fetched['raw']).decode('ascii')
        print(json.dumps({'response':result}),flush=True)
    except Problem as error:
        print(json.dumps({'error':{'message':str(error),'code':error.code,'status':error.status,'details':error.details}}),flush=True)
        raise SystemExit(2)


if __name__=='__main__':main()
