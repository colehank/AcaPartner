import {figureValueKey,figurePropertyValue,overlayLayers} from './figure-properties.js';

// Match the registered display encoding, never a brain area, label or data group.
export function cmapScopeTargets(manifest,selected,content={},scope='matching'){
 const supported=x=>x?.supported_properties?.includes('cmap');
 if(!supported(selected))return {targets:[],layers:[],colorbars:[],reason:'此对象不支持色图'};
 const current=x=>figurePropertyValue(x,overlayLayers(content).find(o=>(o.target||o.object_id||o.id)===x.id),'cmap');
 const owner=selected.type==='colorbar'?manifest.find(x=>x.id===selected.mappable_id):selected;
 const encoding=x=>{const s=x?.scalar_encoding;return s?.known_norm&&Array.isArray(s.clim)&&s.clim.every(Number.isFinite)?figureValueKey({norm_class:s.norm_class,clim:s.clim,parameters:s.parameters||{}}):null;};
 const signature=encoding(owner),palette=current(owner);
 let layers=scope==='current'?selected.type==='colorbar'?(owner&&supported(owner)?[owner]:[]):[selected]:signature?manifest.filter(x=>x.type!=='colorbar'&&supported(x)&&x.scalar_mapped!==false&&encoding(x)===signature&&current(x)===palette):owner&&supported(owner)?[owner]:[];
 let colorbars=scope==='current'?selected.type==='colorbar'?[selected]:[]:manifest.filter(x=>x.type==='colorbar'&&supported(x)&&layers.some(y=>y.id===x.mappable_id));
 const targets=[...new Map([...layers,...colorbars].map(x=>[x.id,x])).values()];
 if(!targets.length)targets.push(selected);
 return {targets,layers,colorbars,needsEncoding:scope==='matching'&&!signature,reason:scope==='current'?'仅当前对象；共用色条可能不再一致':signature?'按相同显示编码和当前色图匹配；不表示相同数据':'尚无可核验数值编码；等待当前来源预览，或明确选择仅当前'};
}
