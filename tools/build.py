#!/usr/bin/env python3
"""Create a deterministic source distribution, excluding runtime and research assets."""
import argparse
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path


# Product sources are public; author-machine control and historical case records
# are not part of an installation. This same allowlist is used for Git export.
DISTRIBUTION_FOLDERS = ('research_partner', 'frontend/src', 'extensions', 'plugins')
DISTRIBUTION_FILES = (
    'README.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md', 'pyproject.toml', 'config.example.json',
    'docs/user-guide.md', 'docs/quickstart.md', 'docs/RELEASE.md', 'docs/screenshots/workspace-guide.png',
    'docs/product/current-20261010/Research_Partner_产品书.md',
    'docs/product/04_全量功能清单.json', 'docs/product/09_验收场景.md',
    'frontend/package.json', 'frontend/package-lock.json', 'frontend/index.html',
    'frontend/vite.config.ts', 'frontend/tsconfig.json', 'frontend/playwright.config.ts',
    'frontend/tests/local-account-login.spec.ts', 'frontend/tests/workspace-guide.spec.ts',
    'tools/start_local.py', 'tools/build.py', 'tools/install.py',
    'tests/__init__.py', 'tests/test_start_local.py', 'tests/test_http_auth.py',
    'tests/test_local_accounts_http.py', 'tests/test_package_freeze31.py',
    'tests/test_public_distribution.py', 'tests/http_fixture.py',
    'tests/test_action_contract.py', 'tests/test_store_results.py',
    'tests/test_render_output.py', 'tests/test_provider_availability.py',
    'tests/test_command_routing.py', 'tests/test_object_policies.py',
    'tests/test_http_boundary.py', 'tests/test_render_contract.py',
    'tests/test_contracts.py', 'tools/check_backend.py',
    'docs/backend-development.md', '.github/workflows/backend.yml',
    'development/core-generation-runtime.in', 'development/core-generation-runtime.lock',
    'development/core-generation-build.lock',
)


def distributed_source(name):
    path = Path(name)
    if (set(path.parts) & {'.git', '.private', '.runtime', '.venv', 'node_modules'}
            or path.name.startswith('.env')
            or path.suffix.lower() in {'.sqlite', '.sqlite3', '.db', '.pem', '.key', '.token', '.log'}
            or path.name in {'credentials.json', 'account.json', 'accounts.json', 'config.local.json'}):
        return False
    return ('__pycache__' not in path.parts and path.suffix not in {'.pyc', '.pyo'}
            and not name.startswith('research_partner/web/tests/')
            and (name in DISTRIBUTION_FILES or any(name.startswith(folder + '/') for folder in DISTRIBUTION_FOLDERS)))


def build(root, output, frozen_manifest=None):
    root=Path(root).resolve();output=Path(output).resolve()
    paths=[]
    for name in DISTRIBUTION_FOLDERS:
        paths.extend(p for p in (root/name).rglob('*') if p.is_file() and distributed_source(p.relative_to(root).as_posix()))
    paths += [root/n for n in DISTRIBUTION_FILES if (root/n).is_file()]
    backups=[str(p.relative_to(root)) for p in paths if p.name.endswith(('~','.orig','.rej','.bak','.swp','.swo'))]
    if backups:raise ValueError('Patch/editor backup in source distribution: '+', '.join(sorted(backups)))
    records={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}
    for p in paths:
        if p.is_symlink():raise ValueError('Source distribution cannot contain symlinks: '+str(p))
        if any(part in {'.private','.runtime','.env','node_modules'} for part in p.relative_to(root).parts):raise ValueError('Private file in build')
    if frozen_manifest is not None:
        frozen=json.loads(Path(frozen_manifest).read_text())
        declared=frozen.get('files')
        if not isinstance(declared,dict) or not declared:raise ValueError('Invalid frozen source manifest')
        if any(not isinstance(name,str) or Path(name).is_absolute() or '..' in Path(name).parts or Path(name).as_posix()!=name for name in declared):raise ValueError('Invalid frozen source path')
        expected={name for name in declared if distributed_source(name)}
        if set(records)!=expected:
            raise ValueError('Distribution member set differs from frozen source: missing='+repr(sorted(expected-set(records)))+', extra='+repr(sorted(set(records)-expected)))
        for name,sha in records.items():
            if declared.get(name)!=sha:raise ValueError('Distribution input not bound to frozen source: '+name)
    declaration=json.loads((root/'research_partner/runtime-features.json').read_text())
    features=declaration.get('runtime_features')
    if declaration.get('schema_version')!=1 or not isinstance(features,list) or not all(isinstance(v,str) for v in features) or len(features)!=len(set(features)):
        raise ValueError('Invalid runtime feature declaration')
    manifest={'format':'research-partner-source','files':records,'runtime_features':sorted(features),'core_requires':'Python >=3.12 standard library','optional_runtime_dependencies':'Configured separately; no credentials/runtime/research data included','private_materials_included':False}
    stream=io.BytesIO()
    with tarfile.open(fileobj=stream,mode='w',format=tarfile.PAX_FORMAT) as tar:
        for name,sha in records.items():
            data=(root/name).read_bytes()
            if hashlib.sha256(data).hexdigest()!=sha:raise ValueError('Source changed during freeze: '+name)
            info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.mtime=0;tar.addfile(info,io.BytesIO(data))
        data=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode();info=tarfile.TarInfo('distribution-manifest.json');info.size=len(data);info.mtime=0;tar.addfile(info,io.BytesIO(data))
    output.mkdir(parents=True,exist_ok=True)
    dest=output/'research-partner.tar.gz'
    with dest.open('wb') as f:
        with gzip.GzipFile(fileobj=f,mode='wb',mtime=0,filename='') as gz:gz.write(stream.getvalue())
    result={'path':str(dest),'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'files':len(records),'publicly_published':False}
    (output/'build.json').write_text(json.dumps(result,indent=2)+'\n');return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default=str(Path(__file__).resolve().parents[1]));p.add_argument('--output',default='dist');p.add_argument('--frozen-manifest',type=Path,help='Require every distribution member to match the explicitly frozen source files');a=p.parse_args();print(json.dumps(build(a.root,a.output,a.frozen_manifest),indent=2))
