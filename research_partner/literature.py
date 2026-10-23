"""Source-preserving literature acquisition; metadata is not claimed as full text."""
import json
import re
import time
import urllib.parse
import urllib.request
from .store import Problem, require, now, digest

CROSSREF_ENDPOINT = "https://api.crossref.org/works"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Problem("文献服务重定向被拒绝；只允许固定 Crossref 端点", "literature_redirect", 403)



def doi(value):
    value = str(value or "").strip().lower()
    return re.sub(r"^(https?://(dx\.)?doi\.org/|doi:\s*)", "", value)


def _name_parts(value, separator):
    """Split a BibTeX name only outside protected groups, without inferring order."""
    result, start, depth, index = [], 0, 0, 0
    while index < len(value):
        if value[index] == "\\": index += 2; continue
        if value[index] == "{": depth += 1
        elif value[index] == "}": depth -= 1
        require(depth >= 0, "作者姓名括号不平衡")
        if depth == 0 and value.startswith(separator, index):
            result.append(value[start:index].strip()); index += len(separator); start = index
        else: index += 1
    require(depth == 0, "作者姓名括号不平衡")
    result.append(value[start:].strip())
    return result


def _author_display(detail):
    if detail.get("literal") or detail.get("name"):
        return str(detail.get("literal") or detail["name"])
    if detail.get("unstructured") is not None: return str(detail["unstructured"])
    return " ".join(str(detail[k]) for k in ("given", "family", "suffix") if detail.get(k))


def author_names(record):
    """Keep declared family/given fields; unstructured names are never swapped."""
    details = record.get("author_details")
    if details is None:
        authors = record.get("authors")
        if authors is None:
            authors = _name_parts(str(record.get("author", "")), " and ")
            name_format = "bibtex"
        else: name_format = record.get("author_name_format")
        require(isinstance(authors, list), "作者应为有序列表")
        details = []
        for author in authors:
            if isinstance(author, dict): details.append(dict(author)); continue
            require(isinstance(author, str), "作者姓名应为文本或结构化姓名")
            if not author.strip(): continue
            author = author.strip()
            parts = _name_parts(author, ",") if name_format in {"bibtex", "ris"} else [author]
            if name_format == "bibtex" and author.startswith("{") and author.endswith("}"):
                detail = {"literal": author[1:-1]}
            elif len(parts) == 2: detail = {"family": parts[0], "given": parts[1]}
            elif len(parts) == 3: detail = {"family": parts[0], "suffix": parts[1], "given": parts[2]}
            else: detail = {"unstructured": author}
            details.append(detail)
    require(isinstance(details, list) and all(isinstance(d, dict) for d in details), "结构化作者应为有序对象列表")
    details = [{**detail, "display": _author_display(detail)} for detail in details]
    return [detail["display"] for detail in details], details


def crossref_record(item, query, receipt_sha, url):
    date = item.get("published", {}).get("date-parts", [[]])[0]
    # The retained response is authoritative for what Crossref actually supplied,
    # not evidence that an upstream deposit's personal-name fields are correct.
    authors, details = author_names({"author_details": item.get("author", [])})
    return {"title": (item.get("title") or [""])[0], "authors": authors,
            "author_details": details, "author_name_source": "crossref.author",
            "year": str(date[0]) if date else "", "journal": (item.get("container-title") or [""])[0],
            "doi": item.get("DOI", ""), "url": item.get("URL", ""), "abstract": item.get("abstract", ""),
            "query": query, "source_asset": receipt_sha, "source_url": url}


def parse_bibtex(text):
    records = []
    index = 0
    while True:
        match = re.search(r"@(\w+)\s*\{\s*([^,]+),", text[index:])
        if not match: break
        index += match.end()
        record = {"entry_type": match.group(1).lower(), "citation_key": match.group(2).strip()}
        while index < len(text):
            if text[index] in " ,\n\r\t": index += 1; continue
            if text[index] == "}": index += 1; break
            field = re.match(r"([\w-]+)\s*=\s*", text[index:])
            if not field: raise Problem("BibTeX字段无法解析；未静默丢弃")
            key = field.group(1).lower(); index += field.end()
            opener = text[index]; closer = "}" if opener == "{" else '"' if opener == '"' else None
            if closer:
                index += 1; start = index; depth = 1
                while index < len(text):
                    ch = text[index]
                    if ch == "\\": index += 2; continue
                    if opener == "{" and ch == "{": depth += 1
                    if ch == closer: depth -= 1
                    if depth == 0: break
                    index += 1
                require(index < len(text), "BibTeX括号未闭合")
                value = text[start:index]; index += 1
            else:
                end = re.search(r"[,}]", text[index:]); require(end, "BibTeX字段不完整")
                value = text[index:index+end.start()].strip(); index += end.start()
            record[key] = value
        record["author_name_format"] = "bibtex"
        records.append(record)
    require(records, "没有读到BibTeX条目")
    return records


def parse_ris(text):
    records, record = [], {}
    keys = {"TI":"title", "T1":"title", "DO":"doi", "PY":"year", "Y1":"year", "JO":"journal", "JF":"journal", "AB":"abstract", "UR":"url"}
    for line in text.splitlines():
        m = re.match(r"([A-Z0-9]{2})\s+-\s?(.*)", line)
        if not m: continue
        key, value = m.groups()
        if key == "TY": record = {"entry_type": value, "author_name_format": "ris"}
        elif key in {"AU", "A1"}: record.setdefault("authors", []).append(value)
        elif key in keys: record[keys[key]] = value
        elif key == "ER": records.append(record); record = {}
    if record: records.append(record)
    require(records, "没有读到RIS条目")
    return records


class Literature:
    def __init__(self, store, config=None):
        self.store, self.config = store, config or {}

    def fetch(self, query, limit=10, *, max_bytes=4*1024*1024, timeout=20):
        """Pure bounded HTTP: no assets or objects are committed here."""
        require(self.config.get("literature_enabled", True), "文献联网未启用", "network_disabled", 403)
        require(isinstance(query, str) and query.strip(), "请输入文献查询范围")
        limit = max(1, min(20, int(limit)))
        url = CROSSREF_ENDPOINT + "?" + urllib.parse.urlencode({"query.bibliographic": query, "rows": limit})
        request = urllib.request.Request(url, headers={"User-Agent": "ResearchPartner/0.1 (self-hosted literature lookup)", "Accept": "application/json"})
        start = time.monotonic(); deadline = start + timeout; raw = bytearray(); response_complete = False
        try:
            # No proxy-configured alternate destination, redirects, retry or second request.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=timeout) as response:
                raw = bytearray()
                while True:
                    remaining = deadline-time.monotonic()
                    require(remaining > 0, "文献响应超出总时限", "literature_timeout", 503)
                    try: response.fp.raw._sock.settimeout(remaining)
                    except AttributeError: pass
                    chunk = response.read1(min(65536, max_bytes-len(raw)))
                    if not chunk: break
                    raw.extend(chunk)
                    require(len(raw) < max_bytes, "文献响应达到读取上限，未继续读取", "literature_response_limit", 413)
                raw = bytes(raw); response_complete = True
                require(time.monotonic() <= deadline, "文献响应超出总时限", "literature_timeout", 503)
                payload = json.loads(raw)
                items = payload.get("message", {}).get("items")
                require(isinstance(items, list) and all(isinstance(x,dict) for x in items), "文献响应结构无效", "literature_unavailable", 503)
        except Problem as e:
            e.details.update(bytes_read=len(raw),received_sha256=digest(bytes(raw)),response_complete=response_complete)
            raise
        except (OSError, ValueError) as e:
            raise Problem("文献服务不可用；请求是否完整执行无法确认：" + type(e).__name__, "literature_unavailable", 503,
                {'bytes_read':len(raw),'received_sha256':digest(bytes(raw)),'response_complete':response_complete}) from e
        return {"raw": raw, "items": items[:limit], "query": query, "source_url": url,
                "elapsed_seconds": time.monotonic()-start, "bytes_read": len(raw), "full_text_read": False}

    def persist_response(self, fetched, project_id, *, connection=None, task_id=None, execution_token=None):
        receipt = self.store.add_asset(fetched['raw'], "crossref-query.json", "application/json",
            {"project_id":project_id,"source_url":fetched['source_url'],"query":fetched['query'],
             "read_scope":"metadata/available abstracts","queried_at":now()},
            connection=connection,task_id=task_id,execution_token=execution_token)
        records = [crossref_record(item, fetched['query'], receipt['sha'], fetched['source_url']) for item in fetched['items']]
        return {"records":records,"query":fetched['query'],"source":receipt,"elapsed_seconds":fetched['elapsed_seconds'],
                "bytes_read":fetched['bytes_read'],"full_text_read":False}

    def query(self, query, limit=10, project_id=None):
        return self.persist_response(self.fetch(query,limit),project_id)

    def import_records(self, records, project_id, raw_source=None, *, connection=None, task_id=None, execution_token=None):
        require(isinstance(records, list) and len(records) <= 500, "引用条目应为最多500项的列表")
        existing = self.store.objects(project_id, ["literature"]) if connection is None else [self.store.unpack(r) for r in connection.execute("SELECT * FROM objects WHERE project_id=? AND kind='literature' ORDER BY id",(project_id,))]
        created, duplicates, warnings = [], [], []
        for record in records:
            title = str(record.get("title") or "").strip()
            identifier = doi(record.get("doi"))
            normalized_title = re.sub(r"\W+", "", title.casefold())
            matched = next((o for o in existing if (identifier and doi(o["content"].get("doi")) == identifier) or (not (identifier and doi(o['content'].get('doi'))) and normalized_title and re.sub(r"\W+", "", o["content"].get("title", "").casefold()) == normalized_title)), None)
            if matched:
                duplicates.append({"existing_id": matched["id"], "existing_revision": matched["revision"], "incoming": record, "conflicting_fields": [k for k in ("title","authors","year","abstract","doi") if record.get(k) and record.get(k)!=matched["content"].get(k)], "action": "retained_original_no_silent_overwrite"}); continue
            authors, author_details = author_names(record)
            missing = [k for k in ["title", "year"] if not record.get(k)]
            if not authors: missing.append("authors")
            content = {**record, "doi": identifier, "title": title, "authors": authors, "author_details": author_details, "read_scope": "abstract" if record.get("abstract") else "metadata", "full_text": None, "missing_fields": missing, "import_source": raw_source, "claims": []}
            obj = self.store.create("literature", title or "待补题名的引用条目", project_id, content, {"citation_key": record.get("citation_key") or "ref_"+digest(record)[:10]},connection=connection,task_id=task_id,execution_token=execution_token)
            created.append(obj); existing.append(obj)
            if missing: warnings.append({"id": obj["id"], "missing": missing})
        return {"created": created, "duplicates": duplicates, "warnings": warnings}

    def bibtex(self, records):
        output = []
        for obj in records:
            r = obj["content"]
            entry_type = r.get('entry_type', 'article')
            require(isinstance(entry_type, str), '文献条目类型无效', 'bibliography_type', 422)
            # Preserve declared BibTeX types. RIS uses its own explicit codes;
            # unsupported types stay visible rather than becoming articles.
            if r.get('author_name_format') == 'ris':
                entry_type = {'JOUR':'article','BOOK':'book','CHAP':'incollection',
                              'CONF':'proceedings','CPAPER':'inproceedings',
                              'RPRT':'techreport','THES':'phdthesis','ELEC':'misc',
                              'GEN':'misc'}.get(entry_type.upper(), entry_type)
            entry_type = entry_type.lower()
            require(entry_type in {'article','book','booklet','inbook','incollection',
                                  'inproceedings','conference','manual','mastersthesis',
                                  'misc','phdthesis','proceedings','techreport','unpublished'},
                    '当前 BibTeX 出口不支持原条目类型：'+entry_type, 'bibliography_type', 422)
            fields = {k:r.get(k) for k in ["title","year","doi","journal","url",
                       'booktitle','publisher','edition','pages','volume','number',
                       'howpublished','note','institution','school','address','series',
                       'month','type','organization']}
            def escaped(value): return str(value).replace("\\", "\\textbackslash{} ").replace("{", "\\{").replace("}", "\\}")
            authors, details = author_names(r)
            require(not r.get("author_details") or authors == r.get("authors", authors),
                    "作者显示名与结构化姓名不一致；请核对来源后同时更新", "author_structure_mismatch", 409)
            formatted = []
            for detail in details:
                if detail.get("literal") or detail.get("name"):
                    formatted.append("{" + escaped(detail.get("literal") or detail["name"]) + "}")
                elif detail.get("family"):
                    formatted.append(", ".join(escaped(detail[k]) for k in ("family", "suffix", "given") if detail.get(k)))
                else: formatted.append(escaped(_author_display(detail)))
            lines = ["  "+k+" = {"+escaped(v)+"}" for k,v in fields.items() if v]
            if formatted: lines.append("  author = {"+" and ".join(formatted)+"}")
            key = obj["metadata"].get("citation_key", obj["id"])
            require(isinstance(key,str) and re.fullmatch(r'[A-Za-z0-9_.:-]+',key),
                    '引用 key 无效；未导出损坏的 BibTeX', 'citation_key', 422)
            warnings = []
            for conflict in r.get("metadata_conflicts", []):
                if isinstance(conflict, dict):
                    status = conflict.get("status", "unresolved")
                    message = conflict.get("message", "Bibliographic source metadata disagree")
                else: status, message = "unresolved", str(conflict)
                warnings.append("% METADATA WARNING ["+key+"; "+str(status)+"] "+" ".join(str(message).split()))
            output.append("\n".join(warnings+["@"+entry_type+"{"+key+",\n"+",\n".join(lines)+"\n}"]))
        return "\n\n".join(output)+"\n"

    def dispatch(self, data):
        action = data["action"]
        if action == "literature.search": return self.query(data["query"], data.get("limit",10),data['project_id'])
        if action == "literature.import":
            text, fmt = data.get("text", ""), data.get("format", "json")
            raw = self.store.add_asset(text.encode(), "references."+fmt, "text/plain", {"project_id": data["project_id"], "source": "user import"}) if text else None
            records = data.get("records")
            if records is None:
                records = parse_bibtex(text) if fmt == "bibtex" else parse_ris(text) if fmt == "ris" else json.loads(text)
            if isinstance(records, dict): records = [records]
            return self.import_records(records, data["project_id"], raw["sha"] if raw else None)
        if action == "literature.export":
            objects = self.store.objects(data["project_id"], ["literature"],include_archived=False)
            return self.store.add_asset(self.bibtex(objects).encode(), "references.bib", "application/x-bibtex", {"project_id": data["project_id"], "sources": [{"id":o["id"],"revision":o["revision"]} for o in objects]})
        raise Problem("文献操作不支持")
