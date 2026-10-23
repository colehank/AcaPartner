"""One explicit byte deletion, never a scientific/text rewrite or JSON reformatter."""
import json
import math
from .store import Problem, require, digest

KIND='delete_unmatched_closing_delimiter'
FEATURE='native_json_syntax_recovery_v1'


def strict_loads(raw):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate object key: '+key)
            result[key]=value
        return result
    def constant(value):raise ValueError('non-finite JSON number: '+value)
    def decimal(value):
        number=float(value)
        if not math.isfinite(number):raise ValueError('JSON number exceeds finite parser range')
        return number
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=constant,parse_float=decimal)


def fault(raw,error):
    text=raw.decode('utf-8')
    result={'code':'invalid_model_output','message':'已登记候选 JSON 无效：'+str(error),'details':{'parser':'strict_json'}}
    if isinstance(error,json.JSONDecodeError):
        result['details'].update(byte_offset=len(text[:error.pos].encode('utf-8')),line=error.lineno,column=error.colno)
    return result


def unmatched(raw):
    """Return the first closing delimiter mismatching the lexical stack.

    Quotes and escapes are scanned as bytes; ASCII delimiters cannot be inside a
    UTF-8 continuation byte. A strict reparse after deletion is mandatory.
    """
    stack=[];quoted=False;escaped=False
    for offset,byte in enumerate(raw):
        if quoted:
            if escaped:escaped=False
            elif byte==92:escaped=True
            elif byte==34:quoted=False
        elif byte==34:quoted=True
        elif byte in (123,91):stack.append(byte)
        elif byte in (125,93):
            if not stack or stack[-1]!={125:123,93:91}[byte]:return offset
            stack.pop()
    return None


def inspect_syntax(raw,revision):
    original_error=None
    try:source=strict_loads(raw)
    except ValueError as error:source=None;original_error=fault(raw,error)
    if not original_error:
        require(revision['kind']!=KIND,'原候选 JSON 已有效；不能删除结构字符')
        return source,raw,[],None,None
    offset=unmatched(raw);suggestion=None
    if offset is not None:
        repaired=raw[:offset]+raw[offset+1:]
        try:parsed=strict_loads(repaired)
        except ValueError:parsed=None
        if isinstance(parsed,dict):
            suggestion={'kind':KIND,'native_candidate_sha256':digest(raw),'byte_offset':offset,'expected':chr(raw[offset])}
    if revision['kind']!=KIND:return None,raw,[],original_error,suggestion
    require(suggestion is not None,'无法通过删除一个未匹配的右分隔符得到严格 JSON 对象；不提供任意文本修补')
    require(type(revision.get('byte_offset')) is int and all(revision.get(key)==value for key,value in suggestion.items()),
            '修复偏移、原始摘要或字符与已登记字节不一致','conflict',409)
    require(set(revision)==set(suggestion)|{'reason'},'语法修复仅允许明确的单字节删除')
    require(isinstance(revision['reason'],str) and revision['reason'].strip(),'语法修复需要具体理由')
    before=raw[:offset].decode('utf-8')
    change={'operation':'delete_unmatched_closing_delimiter','byte_offset':offset,'byte_length':1,
            'line':before.count('\n')+1,'column':len(before.rsplit('\n',1)[-1])+1,
            'before':chr(raw[offset]),'after':'','origin':'coordinator_technical_syntax_repair',
            'native_candidate_sha256':digest(raw),'candidate_sha256':digest(repaired),
            'preservation':'all other UTF-8 bytes unchanged; scientific claims and model authorship retained'}
    return parsed,repaired,[change],original_error,None
