"""Fail-closed runtime capabilities and task-write fencing, without opening a Store."""
from __future__ import annotations
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from .store import Problem, require, encoded
from .source_identity import source_files

FLOOR_KEY = 'minimum_runtime_features'
WORKSHOP_ACCEPTANCE_FEATURE = 'workshop_acceptance_guard_v1'
FEATURE_FILE = 'research_partner/runtime-features.json'
LEGACY_EMPTY_MANIFESTS = {
    '27df5664e7441581652bc75e4800d5f3fc00b00f8ab9870d0004f65112a87129',
    '63436d2830e95f110c5077e25913a297cde932293a033e6026aad74a77999e66',
    '5ea9e353423d67c4a6efd9ccd13d2a99ab6afd4ac52e20ef131727c962949648',
}


def feature_list(value):
    require(isinstance(value,list) and all(isinstance(v,str) and re.fullmatch(r'[a-z][a-z0-9_]{0,95}',v) for v in value),
            '运行能力声明格式无效','compatibility_invalid',409)
    require(len(value)==len(set(value)),'运行能力声明重复','compatibility_invalid',409)
    return sorted(value)


def declared_features(path):
    try:value=json.loads(Path(path).read_text())
    except (OSError,ValueError) as error:raise Problem('运行能力声明不可读取','compatibility_invalid',409) from error
    require(isinstance(value,dict) and value.get('schema_version')==1,'运行能力声明版本不支持','compatibility_invalid',409)
    return feature_list(value.get('runtime_features'))


SUPPORTED_FEATURES = frozenset(declared_features(Path(__file__).with_name('runtime-features.json')))


def configure_connection(connection):
    """New connections attest only this installed code's static feature set."""
    def supported(raw):
        try:return int(set(feature_list(json.loads(raw) if raw else []))<=SUPPORTED_FEATURES)
        except (Problem,ValueError,TypeError):return 0
    connection.create_function('rp_runtime_supports',1,supported,deterministic=True)


def require_features(connection,features):
    """Monotonic floor plus task guards; caller's enqueue transaction is atomic."""
    require(connection.in_transaction,'能力门槛必须与任务写入处于同一事务','compatibility_invalid',409)
    needed=set(feature_list(list(features)))
    require(needed<=SUPPORTED_FEATURES,'当前代码不支持待写入任务能力','runtime_incompatible',409)
    row=connection.execute('SELECT value FROM kv WHERE key=?',(FLOOR_KEY,)).fetchone()
    try:old=feature_list(json.loads(row[0])) if row else []
    except (ValueError,TypeError) as error:raise Problem('现有运行能力门槛损坏','compatibility_invalid',409) from error
    floor=sorted(set(old)|needed)
    require(set(floor)<=SUPPORTED_FEATURES,'研究空间需要较新运行能力','runtime_incompatible',409)
    connection.execute('INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(FLOOR_KEY,encoded(floor)))
    # Do not use executescript: its implicit commit would break enqueue atomicity.
    for operation in ('INSERT','UPDATE'):
        connection.execute(f'''CREATE TRIGGER IF NOT EXISTS rp_runtime_task_{operation.lower()}
            BEFORE {operation} ON tasks BEGIN
            SELECT CASE WHEN rp_runtime_supports((SELECT value FROM kv WHERE key='minimum_runtime_features'))!=1
            THEN RAISE(ABORT,'Research Partner runtime features are incompatible') END;
            END''')
    return floor


def workspace_requirements(workspace):
    """Read-only floor; infer pre-marker v14 task requirements conservatively."""
    path=Path(workspace).expanduser().resolve()/'research.sqlite3'
    if not path.exists():return {'minimum_runtime_features':[],'declared':[],'inferred':[],'database_present':False}
    require(path.is_file(),'研究空间数据库路径无效','compatibility_invalid',409)
    connection=None
    try:
        connection=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)
        connection.execute('PRAGMA query_only=ON')
        tables={row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        require({'kv','tasks'}<=tables,'研究空间数据库格式无法核对','compatibility_invalid',409)
        row=connection.execute('SELECT value FROM kv WHERE key=?',(FLOOR_KEY,)).fetchone()
        declared=feature_list(json.loads(row[0])) if row else [];inferred=set()
        for (raw,) in connection.execute('SELECT payload FROM tasks'):
            payload=json.loads(raw)
            require(isinstance(payload,dict),'任务数据无法核对','compatibility_invalid',409)
            if payload.get('kind')=='generation':
                inferred.add('content_generation_plans_v1')
                if payload.get('generation_plan',{}).get('shared_generation'):inferred.add('shared_generation_plans_v1')
            if payload.get('kind')=='project_management':inferred.add('reviewed_project_management_v1')
            if payload.get('kind')=='manuscript_revision':
                inferred.add('reviewed_manuscript_revision_v1')
                if any(t.get('target', {}).get('field') == 'slot_layout' for t in payload.get('context', {}).get('manuscript_revision', {}).get('targets', [])):
                    inferred.add('reviewed_main_layout_round_v1')
                if payload.get('context', {}).get('manuscript_revision', {}).get('slot_adoptions'):
                    inferred.add('reviewed_main_leaf_adoption_v1')
                native_context=payload.get('context',{}).get('manuscript_revision',{}).get('native_note_context',{})
                if any('fragment' in note for note in native_context.get('notes',[])):
                    inferred.add('native_review_fragment_context_v1')
            if payload.get('literature_plan') or payload.get('kind')=='literature_acquisition':inferred.add('literature_acquisition_v1')
            if payload.get('kind')=='research_cycle' or payload.get('cycle_parent'):inferred.add('research_cycle_v1')
            if payload.get('context',{}).get('figure_composition',{}).get('native_transport')=='app_server_dynamic':inferred.add('native_codex_dynamic_tools_v1')
            if payload.get('context',{}).get('material_resolution',{}).get('version')==1:inferred.add('scientific_evidence_projection_v1')
        return {'minimum_runtime_features':sorted(set(declared)|inferred),'declared':declared,'inferred':sorted(inferred),'database_present':True}
    except (sqlite3.Error,ValueError,TypeError,AttributeError) as error:
        raise Problem('研究空间能力门槛无法只读核对','compatibility_invalid',409) from error
    finally:
        if connection is not None:connection.close()


def check_workspace(workspace,supported=None):
    result=workspace_requirements(workspace);available=set(SUPPORTED_FEATURES if supported is None else feature_list(list(supported)))
    missing=sorted(set(result['minimum_runtime_features'])-available)
    require(not missing,'目标发行不支持研究空间已有任务；请使用兼容发行，或在独立目录恢复升级前快照','runtime_incompatible',409,{'required':result['minimum_runtime_features'],'supported':sorted(available),'missing':missing})
    return {**result,'supported_runtime_features':sorted(available),'compatible':True}


def verify_release(release):
    """Verify manifest and declared source bytes without importing target code."""
    root=Path(release).expanduser().resolve();path=root/'distribution-manifest.json'
    require(path.is_file() and not path.is_symlink(),'发行缺少可核验manifest','release_integrity',409)
    try:raw=path.read_bytes();manifest=json.loads(raw)
    except (OSError,ValueError) as error:raise Problem('发行manifest不可读取','release_integrity',409) from error
    require(manifest.get('format')=='research-partner-source' and isinstance(manifest.get('files'),dict),'发行manifest格式无效','release_integrity',409)
    records=manifest['files'];require(0<len(records)<=10000,'发行文件清单无效','release_integrity',409)
    for name,sha in records.items():
        require(isinstance(name,str) and not Path(name).is_absolute() and '..' not in Path(name).parts and '\\' not in name,'发行路径不安全','release_integrity',409)
        file=root/name
        require(isinstance(sha,str) and re.fullmatch(r'[a-f0-9]{64}',sha),'发行摘要无效','release_integrity',409)
        require(file.is_file() and file.resolve().is_relative_to(root),'发行文件缺失或越界','release_integrity',409)
        require(not any(p.is_symlink() for p in [file,*file.parents] if p!=root and p.is_relative_to(root)),'发行不得通过符号链接替换文件','release_integrity',409)
        require(hashlib.sha256(file.read_bytes()).hexdigest()==sha,'发行文件与冻结摘要不符：'+name,'release_integrity',409)
    require({'research_partner/__init__.py','research_partner/__main__.py','research_partner/app.py','research_partner/store.py','research_partner/runtime.py'}<=set(records),'发行缺少关键入口','release_integrity',409)
    # Runtime data (notably native strategy text) must be frozen alongside code.
    # Use the manager's selector; target modules are never imported for preflight.
    require(set(source_files(root, development=True))<=set(records),'发行存在未登记运行输入','release_integrity',409)
    if 'research_partner/native/acaworker-plugin.mjs' in records:
        require('research_partner/native/research-strategy.md' in records,'发行缺少已冻结原生策略','release_integrity',409)
    # Ignore runtime bytecode, but never permit unmanifested source/modules that
    # could shadow a checked import. The managed launcher disables cache reads.
    for folder in ('research_partner','tools'):
        for file in (root/folder).rglob('*'):
            if file.is_file() and file.suffix in {'.py','.so','.pyd','.dll','.zip'}:
                require(str(file.relative_to(root)) in records,'发行存在未登记可执行模块','release_integrity',409)
    manifest_sha=hashlib.sha256(raw).hexdigest()
    if 'runtime_features' in manifest:
        require(FEATURE_FILE in records and 'research_partner/compatibility.py' in records,'发行能力声明缺少已冻结实现入口','release_integrity',409)
        features=feature_list(manifest['runtime_features'])
        require(features==declared_features(root/FEATURE_FILE),'manifest与冻结能力声明不一致','release_integrity',409)
        legacy=False
    else:
        require(manifest_sha in LEGACY_EMPTY_MANIFESTS,'未知旧发行没有已知能力声明；未加载目标代码','release_unknown',409)
        features=[];legacy=True
    return {'release':str(root),'manifest_sha256':manifest_sha,'verified_files':len(records),'runtime_features':features,'known_legacy_empty_features':legacy}


def preflight_release(release,workspace):
    verified=verify_release(release)
    checked=check_workspace(workspace,verified['runtime_features'])
    return {'ok':True,'operation':'preflight','release':verified,'workspace':str(Path(workspace).expanduser().resolve()),'compatibility':checked,'target_code_loaded':False,'runtime_started':False}
