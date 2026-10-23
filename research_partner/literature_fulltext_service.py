"""Explicit public-source input with durable once-only request identity.

This creates a separate literature object, never edits an imported citation,
submits a model task, grants execution, or treats an HTTP response as scientific review.
"""
import base64
import copy
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from .store import Problem, require, digest, encoded, now
from .project_management import authority_scope
from .literature_fulltext_http import pmcid, ENDPOINT, MAX_BYTES, TIMEOUT

SCHEMA = 'literature-fulltext-receipt-v1'
FIELDS = {'action', 'project_id', 'pmcid', 'request_key'}


def _get(c, key):
    row = c.execute('SELECT value FROM kv WHERE key=?', (key,)).fetchone()
    return json.loads(row[0]) if row else None


def _put(c, key, value):
    c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, encoded(value)))


def _authority(app, project, scope, principal, *, network=False):
    require(principal.get('kind') != 'agent' and principal.get('actor_kind') != 'agent',
            '全文输入需操作者明确请求，不能由 Agent 私自获取', 'forbidden', 403)
    obj = app.writable(project, scope)
    app.writable(project, authority_scope(app, principal))
    require(obj['kind'] == 'project' and not obj['archived'], '需要当前可写的活动项目', 'forbidden', 403)
    if network:
        require(app.config.get('network', {}).get('literature_enabled', True), '文献联网未启用', 'network_disabled', 403)
    return obj


def _fetch(ident, check):
    """A hard host deadline covers DNS/TLS/XML parsing, including a silent peer."""
    from .providers import restricted_environment
    from .runtime import confirm_process_identity, cleanup_unregistered, terminate_owned
    process = None
    record = None
    registration = {}
    start = time.monotonic()
    try:
        check()
        process = subprocess.Popen([sys.executable, '-m', 'research_partner.literature_fulltext_worker', str(os.getpid())],
            cwd=Path(__file__).resolve().parent.parent, env=restricted_environment(),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
        record = confirm_process_identity(process, start + TIMEOUT, registration, timeout_code='fulltext_timeout')
        check()
        pending_input = encoded({'pmcid': ident}).encode()
        while True:
            remaining = TIMEOUT - (time.monotonic()-start)
            if remaining <= 0:
                raise subprocess.TimeoutExpired(process.args, TIMEOUT)
            try:
                raw, errors = process.communicate(pending_input, timeout=min(.1, remaining))
                break
            except subprocess.TimeoutExpired:
                # communicate() preserves the same stdin/output after a wait timeout.
                # This is waiting for one child, never sending a second HTTP request.
                pending_input = None
                check()
        require(len(raw) <= MAX_BYTES*3 and len(errors) <= 65536, '全文工具输出超限', 'fulltext_output_limit', 503)
        value = json.loads(raw)
        require(process.returncode == 0 and 'response' in value, '全文请求结果未确认；未重发', 'fulltext_unknown', 503)
        result = value['response']
        body = base64.b64decode(result.pop('raw_base64'), validate=True)
        require(len(body) <= MAX_BYTES and len(body) == result['bytes'] and digest(body) == result['raw_sha256']
                and result['pmcid'] == ident and result['source_url'] == ENDPOINT+ident+'/fullTextXML',
                '全文工具回包身份不符', 'fulltext_integrity', 409)
        result['raw'] = body
        result['host_elapsed_seconds'] = time.monotonic()-start
        return result
    except subprocess.TimeoutExpired as error:
        raise Problem('全文工具达到 30 秒时限；原请求状态未知，不自动重发', 'fulltext_unknown', 503) from error
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise Problem('全文工具没有完整有效回执；原请求未重发', 'fulltext_unknown', 503) from error
    finally:
        record = record or registration.get('confirmed')
        if record:
            terminate_owned(record, hard=True)
        elif process:
            cleanup_unregistered(process, registration)
        if process:
            process.wait(timeout=5)
            for stream in (process.stdin, process.stdout, process.stderr):
                if stream and not stream.closed:
                    stream.close()


def dispatch(app, data, scope=None, principal=None):
    require(set(data) == FIELDS, '全文请求字段必须明确，不接受额外 URL 或执行参数')
    action = data['action']
    require(action in {'literature.fulltext.fetch', 'literature.fulltext.status'}, '全文动作不支持')
    try:
        ident = pmcid(data['pmcid'])
    except ValueError as error:
        raise Problem(str(error)) from error
    request_key = data['request_key']
    require(isinstance(request_key, str) and re.fullmatch(r'[A-Za-z0-9_-]{8,128}', request_key), '全文请求身份无效')
    project = data['project_id']
    principal = principal or {'kind': 'local_operator'}
    _authority(app, project, scope, principal)
    key = 'literature_fulltext:'+project+':'+request_key
    fingerprint = digest({'project': project, 'pmcid': ident, 'principal': principal})
    public = {'schema': SCHEMA, 'project_id': project, 'pmcid': ident, 'request_key': request_key,
        'state': 'not_found', 'status': 'not_found', 'reference': None, 'title': None,
        'paragraph_count': 0, 'read_scope': 'none', 'license_status': 'unknown',
        'limitations': [], 'source': None, 'error': None,
        'source_url': ENDPOINT+ident+'/fullTextXML', 'request_limit': 1,
        'timeout_seconds': TIMEOUT, 'max_bytes': MAX_BYTES}
    network_pin = digest(app.config.get('network', {}))
    with app.store.transaction() as c:
        previous = _get(c, key)
        if previous:
            require(previous['fingerprint'] == fingerprint, '原请求属于其他文章或操作者', 'conflict', 409)
            return copy.deepcopy(previous['receipt'])
        if action.endswith('.status'):
            return public
        # A browser reload/new request key is not evidence that an earlier HTTP
        # request failed. Keep uncertainty attached to the source and issuer.
        for row in c.execute('SELECT value FROM kv WHERE key LIKE ?', ('literature_fulltext:'+project+':%',)):
            old = json.loads(row[0])
            if old.get('fingerprint') == fingerprint and old['receipt']['state'] in {'dispatched', 'uncertain'}:
                raise Problem('这篇文章已有未确认请求；先查原状态，不能换身份重发',
                              'fulltext_prior_unknown', 409, {'receipt': old['receipt']})
        _authority(app, project, scope, principal, network=True)
        # An already active STOP is a known pre-dispatch refusal. Do not turn
        # zero requests into an uncertain operation that fences this article.
        if app.config.get('development_budget'):
            from .development_budget import Budget
            Budget(app.config['development_budget']).check()
        public.update(state='dispatched', status='pending', started_at=now(),
                      requests_reserved=1, confirmed_http_responses=0)
        operation = {'fingerprint': fingerprint, 'network_sha256': network_pin, 'receipt': public}
        _put(c, key, operation)
        app.store.event(c, 'literature.fulltext.dispatched', project,
                        {'request_key': request_key, 'pmcid': ident, 'requests_reserved': 1, 'model_calls': 0})

    def check():
        _authority(app, project, scope, principal, network=True)
        require(digest(app.config.get('network', {})) == network_pin, '全文获取配置已改变', 'forbidden', 403)
        with app.store.connect() as c:
            require(_get(c, key) == operation, '原全文请求状态已变化', 'conflict', 409)
        if app.config.get('development_budget'):
            from .development_budget import Budget
            Budget(app.config['development_budget']).check()

    start = time.monotonic()
    try:
        fetched = _fetch(ident, check)
        check()
        with app.store.transaction() as c:
            _authority(app, project, scope, principal, network=True)
            require(_get(c, key) == operation and digest(app.config.get('network', {})) == network_pin,
                    '全文返回时权限或请求已变化，未登记旧回包', 'forbidden', 403)
            asset = app.store.add_asset(fetched['raw'], ident+'.xml', fetched['media_type'],
                {'project_id': project, 'source_url': public['source_url'], 'request_key': request_key,
                 'http_status': fetched['http_status'], 'source': 'Europe PMC Open Access XML'}, connection=c)
            receipt = copy.deepcopy(public)
            receipt.update(state='received', finished_at=now(), host_elapsed_seconds=time.monotonic()-start,
                confirmed_http_responses=1,
                source={'sha256': asset['sha'], 'bytes': fetched['bytes'], 'media_type': fetched['media_type']})
            code = fetched['http_status']
            doc = fetched['document']
            if code in {401, 403, 404, 410}:
                receipt.update(status='forbidden' if code in {401,403} else 'unavailable',
                               limitations=['HTTP access result only; paywall or reuse permission is not inferred.'])
            elif fetched['parse_error']:
                receipt.update(state='failed', status='invalid', error=fetched['parse_error'])
            else:
                require(code == 200 and doc and doc['pmcid'] == ident and doc['raw_sha256'] == asset['sha'],
                        '全文结构身份不符', 'fulltext_integrity', 409)
                blocks = doc['paragraphs']
                body = doc['read_scope'] == 'fulltext'
                # Abstract-only responses stay separately labelled, never upgraded to full text.
                status = 'body_paragraphs' if body else 'abstract_only' if doc['read_scope'] == 'abstract' else 'metadata_only'
                content = {'title': doc['title'], 'pmcid': ident, 'blocks': blocks,
                    'abstracts': doc['abstracts'], 'read_scope': status, 'claims': [],
                    'full_text': {'source_asset': asset['sha'], 'source_url': public['source_url'],
                                  'raw_bytes': fetched['bytes'], 'status': status, 'parser': doc['parser']},
                    'license_status': doc['license_status'], 'license_observations': doc['license_observations'],
                    'redistribution_permission': 'unknown', 'limitations': doc['limitations'],
                    'article_ids': doc['article_ids'], 'unparsed_elements': doc['unparsed_elements'],
                    'scientific_content_complete': False}
                require(len(encoded(content).encode()) <= 768*1024, '派生文献超过完整阅读上限，未截断', 'fulltext_content_limit', 413)
                existing = [app.store.unpack(row) for row in c.execute(
                    "SELECT * FROM objects WHERE project_id=? AND kind='literature' AND archived=0", (project,))]
                # Preserve edited/imported records. Only an exactly identical derived
                # source may be reused; a changed response creates its own identity.
                obj = next((item for item in existing if item['content'] == content), None)
                if obj is None:
                    obj = app.store.create('literature', doc['title'] or ident, project, content,
                        {'citation_key': 'pmc_'+ident[3:]+'_'+asset['sha'][:12], 'source_url': public['source_url'],
                         'scientific_approval': False, 'acquisition_request': request_key}, connection=c)
                receipt.update(status=status, title=obj['title'], paragraph_count=len(blocks), read_scope=status,
                    license_status=doc['license_status'], limitations=doc['limitations'],
                    reference={'id': obj['id'], 'revision': obj['revision'], 'sha256': digest(obj), 'consumer_id': project})
            _put(c, key, {**operation, 'receipt': receipt})
            app.store.event(c, 'literature.fulltext.received', project,
                {'request_key': request_key, 'pmcid': ident, 'status': receipt['status'],
                 'source_sha256': asset['sha'], 'reference': receipt['reference'], 'model_calls': 0})
        return receipt
    except Exception as error:
        with app.store.transaction() as c:
            if _get(c, key) == operation:
                failed = {**public, 'state': 'uncertain', 'status': 'unknown', 'finished_at': now(),
                          'host_elapsed_seconds': time.monotonic()-start,
                          'error': {'code': getattr(error, 'code', 'fulltext_unknown'),
                                    'message': '原全文请求没有可采用回执；仅可查原请求状态，不自动重发'}}
                _put(c, key, {**operation, 'receipt': failed})
                app.store.event(c, 'literature.fulltext.unconfirmed', project,
                    {'request_key': request_key, 'pmcid': ident, 'code': failed['error']['code'], 'model_calls': 0})
        raise
