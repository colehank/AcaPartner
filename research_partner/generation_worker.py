"""One explicit registered-script invocation; executed only by the task adapter.

This is process separation, not an OS security sandbox. The script was granted
current-account local execution for its exact plan. Inputs/outputs are checked
against the immutable job; the parent verifies again before publication.
"""
import csv
import hashlib
import json
from pathlib import Path
import runpy
import stat
import sys


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    job=json.loads(Path(sys.argv[1]).read_text());root=Path(job['output_dir'])
    if sha(job['script'])!=job['script_sha256']:raise ValueError('Frozen script digest changed')
    before={name:sha(path) for name,path in job['inputs'].items()}
    namespace=runpy.run_path(job['script'],run_name='research_partner_registered_step')
    function=namespace.get('build_step')
    if not callable(function):raise ValueError('Registered script must expose build_step(inputs, parameters, output_dir)')
    function(dict(job['inputs']),job['parameters'],str(root))
    if before!={name:sha(path) for name,path in job['inputs'].items()}:raise ValueError('Script changed frozen input bytes')
    outputs={}
    for name,contract in job['contracts']['outputs'].items():
        path=root/name;info=path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>16*1024*1024:raise ValueError('Output not a bounded ordinary file')
        with path.open(encoding='utf-8-sig',newline='') as handle:
            reader=csv.DictReader(handle)
            if reader.fieldnames!=contract['columns']:raise ValueError('Output columns differ from I/O contract')
            rows=list(reader)
        if any(None in row or any(v is None for v in row.values()) for row in rows):raise ValueError('Incomplete output row')
        members=[tuple(row[k] for k in contract['identity_fields']) for row in rows]
        if any(any(v=='' for v in member) for member in members) or len(set(members))!=len(members):raise ValueError('Output identities missing or duplicated')
        outputs[name]={'sha256':sha(path),'rows':len(rows),'contract':contract}
        path.chmod(0o400)
    record={'node_key':job['node_key'],'plan_hash':job['plan_hash'],'inputs':before,'outputs':outputs,'script_sha256':job['script_sha256']}
    temporary=root/'.outputs.json.pending';temporary.write_text(json.dumps(record,ensure_ascii=False,sort_keys=True)+'\n');temporary.replace(root/'outputs.json')


if __name__=='__main__':main()
