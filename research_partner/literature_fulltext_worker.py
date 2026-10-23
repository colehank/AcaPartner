"""Host-owned single-request OA reader. No Store, credentials, model or retry."""
import base64
import ctypes
import json
import os
import signal
import sys


def main():
    expected_parent = int(sys.argv[1])
    if ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != expected_parent:
        raise SystemExit('Cannot establish owning-host death signal')
    from .literature_fulltext_http import fetch
    from .literature_fulltext import parse_jats, JATSParseError
    try:
        job = json.loads(sys.stdin.read(4096))
        if set(job) != {'pmcid'}:
            raise ValueError('Unexpected request fields')
        value = fetch(job['pmcid'])
        raw = value.pop('raw')
        value['raw_base64'] = base64.b64encode(raw).decode('ascii')
        value['document'] = None
        value['parse_error'] = None
        if value['http_status'] == 200:
            try:
                value['document'] = parse_jats(raw, expected_pmcid=job['pmcid'],
                                              expected_raw_sha256=value['raw_sha256'])
            except JATSParseError as error:
                value['parse_error'] = {'code': error.code, 'message': str(error)[:500]}
        print(json.dumps({'response': value}, ensure_ascii=False), flush=True)
    except Exception as error:
        # No arbitrary URL, response body, exception repr, paths or secrets in a public error.
        print(json.dumps({'error': {'code': 'fulltext_transport_unknown',
                                   'message': '全文获取未确认完成；保留原请求，未自动重发',
                                   'exception_type': type(error).__name__}}), flush=True)
        raise SystemExit(2)


if __name__ == '__main__':
    main()
