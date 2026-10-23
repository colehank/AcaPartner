"""Image references in the workbench's supported document-token grammar.

Matches web/document-markdown.js documentTokens: escaped syntax, fenced code
and variable-length inline code are literal, not registered image references.
No network or filesystem interpretation is performed here.
"""
import re


def image_references(value):
    text=str(value);i=0
    while i<len(text):
        if i==0 or text[i-1]=='\n':
            end=text.find('\n',i);end=len(text) if end<0 else end
            fence=re.match(r'^[ \t]*(`{3,}|~{3,})',text[i:end])
            if fence:
                stop=min(end+1,len(text))
                while stop<len(text):
                    until=text.find('\n',stop);until=len(text) if until<0 else until
                    close=re.fullmatch(r'[ \t]*(`{3,}|~{3,})[ \t]*',text[stop:until])
                    stop=min(until+1,len(text))
                    if close and close[1][0]==fence[1][0] and len(close[1])>=len(fence[1]):break
                i=stop;continue
        if text[i]=='\\' and i+1<len(text):i+=2;continue
        if text[i]=='`':
            n=1
            while i+n<len(text) and text[i+n]=='`':n+=1
            j=i+n;found=-1
            while j<len(text):
                if text[j]!='`':j+=1;continue
                count=1
                while j+count<len(text) and text[j+count]=='`':count+=1
                if count==n:found=j;break
                j+=count
            if found>=0:i=found+n;continue
            i+=n;continue
        match=re.match(r'(!?)\[((?:\\.|[^\]\\\n])*)\]\(((?:\\.|[^)\\\n])+)\)',text[i:])
        if match:
            if match[1]:yield match[3].strip()
            i+=match.end();continue
        i+=1


def asset_declarations(content,*,strict=True):
    """Collect declared identities without reading bytes or granting access.

    Handoff content must resolve every image. An adopted source may contain
    unrelated placeholders; those cannot erase its valid target declarations.
    """
    from .store import require
    from .artifacts import ArtifactEngine
    refs={sha for _,sha in ArtifactEngine._asset_refs(content,strict=strict)}
    resources=content.get('resources',{})
    if strict:require(isinstance(resources,dict),'文稿图片资源必须是映射')
    if not isinstance(resources,dict):resources={}
    resolved=set()
    for alias,value in resources.items():
        if strict:require(isinstance(alias,str) and alias,'文稿图片别名无效')
        if isinstance(value,dict):value=value.get('sha') or value.get('asset') or value.get('url')
        if strict:require(isinstance(value,str),'图片资源缺少登记资产','missing_asset',409)
        if not isinstance(value,str):continue
        sha=value.removeprefix('/api/assets/')
        if strict:require(re.fullmatch(r'[a-f0-9]{64}',sha),'图片资源不是已登记资产','unregistered_dependency',422)
        if re.fullmatch(r'[a-f0-9]{64}',sha):refs.add(sha);resolved.add(alias)
    blocks=content.get('blocks',[])
    bodies=[b.get('text','') for b in blocks if isinstance(b,dict)] if isinstance(blocks,list) else []
    for body in bodies+[content.get('markdown','')]:
        if not isinstance(body,str):continue
        for target in image_references(body):
            direct=re.fullmatch(r'/api/assets/([a-f0-9]{64})',target)
            if direct:refs.add(direct[1])
            elif strict:require(target in resolved,'修订文稿图片未绑定已登记资源','missing_asset',409,{'target':target})
    return refs

