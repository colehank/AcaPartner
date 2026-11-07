"""Actual bounded math rendering; no user code, TeX shell or model execution."""
from research_partner.resources import module_file
import base64
import json
import re
import tempfile
from pathlib import Path
from research_partner.storage.store import require, digest
from research_partner.rendering.engine import ArtifactEngine, run_process

MATH = re.compile(r'(?<!\\)\$\$([\s\S]+?)\$\$|(?<![\\$])\$(?!\$)([^\n$]+)\$(?!\$)|\\\[([\s\S]+?)\\\]|\\\(([^\n]+?)\\\)')

def dispatch(app, data, scope):
    require(set(data) <= {'action','object_id','expected_revision'}, '渲染字段不支持')
    obj=app.get(data['object_id'],scope)
    require(obj['kind'] in {'paper','report','note','workshop_note'}, '需要文稿')
    require(obj['revision']==data['expected_revision'],'稿件已变化，请重新渲染','conflict',409)
    values=[]
    for block in obj['content'].get('blocks',[]):
        # Ignore code, which must remain literal source rather than mathematics.
        text=re.sub(r'```[\s\S]*?```|`[^`]*`','',str(block.get('text','')))
        values += [next(x for x in m.groups() if x is not None) for m in MATH.finditer(text)]
    values=list(dict.fromkeys(values))
    require(len(values)<=64 and all(len(x)<=4096 for x in values),'公式超出本次渲染上限','render_limit',413)
    result={'object_id':obj['id'],'revision':obj['revision'],'source_sha256':digest(obj),'math':{},'failures':[]}
    if not values:return result
    engine=ArtifactEngine(app.store,app.config.get('rendering',{}))
    with tempfile.TemporaryDirectory(prefix='manuscript-math-',dir=app.store.workspace) as name:
        work=Path(name);(work/'input.json').write_text(json.dumps(values))
        script=module_file('research_partner.rendering.math_worker')
        record=run_process([engine.config['scientific_python'],str(script),str(work)],cwd=work,timeout=30)
        payload=json.loads((work/'result.json').read_text())
        for item in payload:
            if item.get('error'):result['failures'].append(item)
            else:result['math'][item['formula']]='data:image/svg+xml;base64,'+base64.b64encode((work/item['file']).read_bytes()).decode()
        result['renderer']={'kind':'matplotlib.mathtext','execution':record,'scope':'mathematical glyph rendering only'}
    return result
