"""One bounded public OA XML request; never accept a user supplied URL."""
import hashlib
import re
import time
import urllib.error
import urllib.request

ENDPOINT = 'https://www.ebi.ac.uk/europepmc/webservices/rest/'
MAX_BYTES = 4 * 1024 * 1024
TIMEOUT = 30


def pmcid(value):
    if not isinstance(value, str) or not re.fullmatch(r'PMC[1-9][0-9]{0,11}', value):
        raise ValueError('需要明确的 PMC 正整数编号，不接受 URL 或其他查询内容')
    return value


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError('全文获取不跟随重定向')


def fetch(ident):
    ident = pmcid(ident)
    url = ENDPOINT + ident + '/fullTextXML'
    start = time.monotonic()
    request = urllib.request.Request(url, headers={
        'Accept': 'application/xml', 'Accept-Encoding': 'identity',
        'User-Agent': 'ResearchPartner/0.1 (explicit public fulltext reading)'})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        response = opener.open(request, timeout=TIMEOUT)
    except urllib.error.HTTPError as error:
        # These are observations of access, not a guess that an article is paywalled.
        if error.code not in {401, 403, 404, 410}:
            error.close()
            raise
        response = error
    raw = bytearray()
    with response:
        if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
            raise ValueError('不接受未预算的压缩全文响应')
        length = response.headers.get('Content-Length')
        if length is not None:
            if not re.fullmatch(r'[0-9]+', length) or int(length) > MAX_BYTES:
                raise ValueError('全文声明长度无效或超过读取上限')
            length = int(length)
        while True:
            remaining = TIMEOUT - (time.monotonic() - start)
            if remaining <= 0:
                raise TimeoutError('全文响应超过总时限')
            try:
                response.fp.raw._sock.settimeout(remaining)
            except AttributeError:
                pass
            chunk = response.read1(min(65536, MAX_BYTES + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise ValueError('全文响应超过 4 MiB；没有截断后冒称全文')
        if time.monotonic() - start > TIMEOUT:
            raise TimeoutError('全文结束响应超过总时限')
        if length is not None and len(raw) != length:
            raise ValueError('全文实际字节数与声明长度不符，未作为完整响应')
        return {'pmcid': ident, 'source_url': url, 'http_status': response.code,
                'media_type': response.headers.get_content_type(), 'raw': bytes(raw),
                'raw_sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw),
                'elapsed_seconds': time.monotonic() - start}
