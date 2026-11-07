"""Scientific support relations, distinct from integrity and run inventories."""
from research_partner.storage.store import require, digest, Problem
from research_partner.rendering.engine import ArtifactEngine


def _figure_outputs(app, engine, owner, source, scope, historical, missing):
    """Read verified outputs of the requested source revision; never render.

    content.preview can survive later script/overlay edits. It remains useful
    source evidence, but cannot stand in for an edited revision's render.
    """
    assets=[];selected=None;rendered=True
    try:
        selected,failures=engine._registered_component_export(source,'png')
        if selected is None and not failures:
            selected=engine._registered_static_component(source,'png')
            rendered=False
        if selected is None and (failures or source['content'].get('script_asset') or source['content'].get('overlays')):
            missing.append(f"{source['title']}：未找到修订 {source['revision']} 可验证的渲染结果；原始来源预览不能替代该修订的结果。")
        if selected:
            info=app.asset(selected['info']['sha'],scope,owner['project_id'])
            label=('历史修订' if historical else '采用修订')+f" {source['revision']}"
            description=label+('的渲染结果' if rendered else '的原始静态输出（未重绘）')
            assets.append({'role':'historical_result' if historical else 'result',
                           'name':description+' · '+info['filename'],'asset':info['sha'],
                           'url':'/api/assets/'+info['sha'],'relation':description,'available':True,
                           'source_revision':source['revision'],'source_sha256':digest(source),
                           'materialization':selected['materialization'],'rendered':rendered})
    except Problem as error:
        selected=None
        missing.append('采用图形结果无法核对：'+error.code)
    selected_sha=selected['info']['sha'] if selected else None
    for _,sha in engine._asset_refs({'preview':source['content'].get('preview')}):
        if sha==selected_sha:continue
        try:
            info=app.asset(sha,scope,owner['project_id'])
            assets.append({'role':'historical_result','name':'原始来源预览（历史） · '+info['filename'],
                           'asset':sha,'url':'/api/assets/'+sha,'available':True,
                           'relation':'content.preview：保留的原始来源输出，不代表所查修订的渲染结果。',
                           'materialization':'declared_source_preview','rendered':False})
        except Problem as error:
            missing.append('原始来源预览无法核对：'+error.code)
    return assets


def inspect(app,data,scope):
    require(set(data)<={'action','object_id','revision','block_id','component_id'},'溯源字段不支持')
    obj=app.get(data['object_id'],scope,data.get('revision'))
    content=obj['content'];block_id=data.get('block_id');component_id=data.get('component_id')
    require(not (block_id and component_id),'一次定位正文或图形')
    if block_id:require(any(b.get('id')==block_id for b in content.get('blocks',[])),'正文位置不存在','not_found',404)
    refs=[];relations=[];missing=[];adopted={}
    for component in content.get('components',[]):
        ident=component.get('id') or component.get('object_id');revision=component.get('revision')
        if ident and type(revision) is int:adopted.setdefault(ident,set()).add(revision)
    for entry in content.get('scientific_provenance',[]):
        require(isinstance(entry,dict),'科学来源登记无效','trace_invalid',409)
        target=entry.get('target',{})
        if block_id and target.get('block_id')!=block_id:continue
        if component_id and target.get('component_id')!=component_id:continue
        relations.append({k:entry.get(k) for k in ('statement','supports','limitations','computation','target')})
        refs.extend(entry.get('sources',[]))
    if component_id:
        selected=[r for r in content.get('components',[]) if (r.get('id') or r.get('object_id'))==component_id]
        require(len(selected)==1,'图形出现次数不唯一或已移除','trace_target',409)
        refs += [{'object_id':component_id,'revision':selected[0].get('revision'),'role':'figure','supports':'稿件采用的实际图形与图注；科学解释依据见下列关系'}]
    if obj['kind']=='figure':refs += [{'object_id':obj['id'],'revision':obj['revision'],'role':'figure','supports':'所查修订的绘图输入与生成来源'}]
    if not relations:missing.append('此阅读位置尚未登记从科学表述到具体结果的支持关系；不会由文件存在推断结论成立。')
    sources=[];engine=ArtifactEngine(app.store,app.config.get('rendering',{}))
    for ref in refs:
        ident=ref.get('object_id') or ref.get('id');revision=ref.get('revision')
        if not ident or type(revision) is not int:
            missing.append('来源缺少准确成果及采用修订');continue
        source=app.get(ident,scope,revision)
        with app.store.read_snapshot() as connection:app.store.assert_source_access(connection,obj['project_id'],ident)
        historical=bool(adopted.get(ident)) and revision not in adopted[ident]
        assets=[]
        fields=[('plot_code','script_asset'),('saved_data','input_assets')]
        if source['kind']!='figure':fields.append(('result','preview'))
        for role,field in fields:
            for label,sha in engine._asset_refs({field:source['content'].get(field)}):
                try:
                    asset=app.asset(sha,scope,obj['project_id'])
                    assets.append({'role':role,'name':asset['filename'],'asset':sha,'url':'/api/assets/'+sha,'relation':label,'available':True})
                except Problem as error:
                    missing.append(f'{role}来源无法核对：{getattr(error,"code",type(error).__name__)}')
        if source['kind']=='figure':
            assets.extend(_figure_outputs(app,engine,obj,source,scope,historical,missing))
        scientific=source['content'].get('scientific_provenance',[])
        for declaration in source['metadata'].get('source_assets',[]):
            if not isinstance(declaration,dict) or not declaration.get('sha'):continue
            try:
                asset=app.asset(declaration['sha'],scope,obj['project_id'])
                assets.append({'role':declaration.get('role','saved_source'),'name':asset['filename'],
                               'asset':asset['sha'],'url':'/api/assets/'+asset['sha'],
                               'relation':declaration.get('supports',''),'available':True})
            except Problem as error:missing.append('已登记科学材料无法访问：'+error.code)
        supports=ref.get('supports','')
        if historical:supports=f"历史科学来源（修订 {revision}；当前采用修订 {', '.join(str(r) for r in sorted(adopted[ident]))}）："+supports
        sources.append({'object_id':ident,'revision':revision,'title':source['title'],'kind':source['kind'],
                        'supports':supports,'role':ref.get('role','result'),'assets':assets,
                        'source_scope':'historical' if historical else 'adopted' if ident in adopted else 'referenced',
                        'scientific_relations':scientific,'computation':source['content'].get('computation_path'),
                        'parameters':source['content'].get('parameters',{}),'limitations':source['metadata'].get('reproducibility_limits',[])})
        if source['kind']=='figure' and not source['content'].get('script_asset'):missing.append(source['title']+'：尚无登记的生成对象/代码，只能核对静态来源。')
    return {'object_id':obj['id'],'revision':obj['revision'],'target':{'block_id':block_id,'component_id':component_id},
            'relations':relations,'sources':sources,'missing':missing,'scientific_approval':False}
