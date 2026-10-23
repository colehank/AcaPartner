#!/usr/bin/env python3
"""Offline isolated install from a verified Research Partner source distribution."""
import argparse
import hashlib
import json
import os
import tarfile
from pathlib import Path


def install(archive,target):
    archive,target=Path(archive),Path(target).expanduser().resolve()
    if target.exists() and any(target.iterdir()):raise ValueError('Install into an empty version directory; do not overwrite an existing running version')
    with tarfile.open(archive,'r:gz') as tar:
        manifest=json.load(tar.extractfile('distribution-manifest.json'))
        if manifest['format']!='research-partner-source':raise ValueError('Unknown distribution')
        members=tar.getmembers();names=[m.name for m in members]
        if len(names)!=len(set(names)) or set(names)!=set(manifest['files'])|{'distribution-manifest.json'}:raise ValueError('Unexpected distribution contents')
        if sum(m.size for m in members)>64*1024*1024:raise ValueError('Distribution too large')
        for member in members:
            path=target/member.name
            if not member.isfile() or not path.resolve().is_relative_to(target):raise ValueError('Unsafe distribution member')
            if member.name in manifest['files']:
                data=tar.extractfile(member).read()
                if hashlib.sha256(data).hexdigest()!=manifest['files'][member.name]:raise ValueError('Distribution hash mismatch')
        target.mkdir(parents=True,exist_ok=True)
        for member in members:
            path=target/member.name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(tar.extractfile(member).read());path.chmod(0o644)
    # Launcher resolves this installation independently of current working directory.
    launcher=target/'research-partner'
    launcher.write_text('#!/usr/bin/env python3\nimport sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parent))\nfrom research_partner.__main__ import main\nraise SystemExit(main())\n');launcher.chmod(0o755)
    return {'installed':True,'target':str(target),'entry':str(launcher),'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'global_environment_modified':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('--target',required=True);a=p.parse_args();print(json.dumps(install(a.archive,a.target),indent=2))
