"""Explicit paper editing/export origins; no automatic prose/LaTeX translation."""
import hashlib
from .store import digest, require


def source_state(obj):
    content = obj['content']
    latex = content.get('latex') or ''
    require(isinstance(latex, str), '手写 LaTeX 必须是文本', 'invalid_paper_source', 422)
    selected = content.get('paper_source_mode')
    require(selected in (None, '', 'structured', 'latex', 'univer', 'docx'), '论文来源模式不支持', 'invalid_paper_source', 422)
    has_structured = bool(content.get('blocks') or content.get('components'))
    mode = selected or ('unselected' if latex.strip() and has_structured else 'latex' if latex.strip() else 'structured')
    structured = {'title': obj['title'], 'content': {key: value for key, value in content.items() if key not in {'latex', 'paper_source_mode', 'univer_snapshot', 'docx_asset'}}}
    return {'object_id': obj['id'], 'revision': obj['revision'], 'mode': mode,
            'selection_explicit': bool(selected), 'structured_sha256': digest(structured),
            'latex_sha256': hashlib.sha256(latex.encode()).hexdigest(), 'latex_characters': len(latex),
            'independent_sources': bool(latex.strip() and has_structured),
            'semantic_equivalence': 'not_assessed', 'docx_source': mode if mode in {'docx', 'univer'} else 'structured',
            **({'docx_sha256': content['docx_asset']} if content.get('docx_asset') else {}),
            **({'univer_sha256': digest(content['univer_snapshot'])} if content.get('univer_snapshot') else {})}


def selected_latex(obj):
    state = source_state(obj)
    require(state['mode'] != 'docx', '当前源为 DOCX；请下载原文件或在原生论文编辑器中编辑。', 'document_adapter_required', 409)
    require(state['mode'] != 'univer', '当前源为 Univer 文稿，请使用已配置的文档转换器导出。', 'document_adapter_required', 409)
    require(state['mode'] != 'unselected', '结构稿与手写 LaTeX 同时存在：请在论文编辑区明确选择并保存 TEX/PDF 来源；不会自动覆盖手写稿。',
            'paper_source_required', 409, state)
    if state['mode'] == 'latex':
        require(bool(obj['content'].get('latex', '').strip()), '所选手写 LaTeX 来源为空；请编辑它或选择结构稿。', 'paper_source_empty', 409, state)
        return obj['content']['latex'], state
    return None, state


def export_origin(obj, source):
    state = source_state(obj)
    return {**state, 'export_source': source,
            'export_source_sha256': state['latex_sha256'] if source == 'latex' else state['structured_sha256'] if source == 'structured' else None}
