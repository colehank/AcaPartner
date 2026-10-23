import {esc} from './ui.js';
import {colorControl,cmapControl} from './color-controls.js';
// API/store JSON may reorder object keys. Array order and value types matter.
export function figureValueKey(value){return JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.keys(item).sort().map(key=>[key,item[key]])):item);}
export function figureManifest(object,content){return object.metadata?.last_export?.manifest||content.manifest||content.object_manifest||content.objects||[];}
export function overlayLayers(content){return Array.isArray(content.overlays)?content.overlays:Object.entries(content.overlays||{}).map(([target,properties])=>({target,properties}));}
export function figurePropertyValue(item,layer,key){return (layer?.properties||layer||{})[key]??item[key]??(key==='alpha'?1:undefined);}
const definitions={text:['标签文字','string'],fontsize:['字号','number'],linewidth:['线宽','number'],linestyle:['线型（- / -- / : / -.）','string'],color:['颜色','string'],loc:['图例位置','string'],label:['图例标签','string'],tick_fontsize:['刻度字号','number'],rotation:['旋转角度（度）','number'],visible:['显示对象','boolean'],fontweight:['字重','string'],title:['图例标题','string'],frameon:['图例边框','boolean'],marker:['标记','string'],markersize:['标记尺寸','number'],alpha:['不透明度（0–1）','number']};
Object.assign(definitions,{facecolor:['填充颜色（颜色名或 RGB/RGBA 数组）','color_values'],edgecolor:['轮廓颜色（颜色名或 RGB/RGBA 数组）','color_values'],cmap:['色图名称','string'],interpolation:['像素插值方式','string'],fill:['填充区域','boolean'],hatch:['填充纹理','string']});
Object.assign(definitions,{figsize:['画布尺寸（英寸）','number_tuple'],subplot_left:['子图左边距','number'],subplot_right:['子图右边界','number'],subplot_bottom:['子图下边距','number'],subplot_top:['子图上边界','number'],subplot_wspace:['子图横向间距','number'],subplot_hspace:['子图纵向间距','number']});
export function propertyDefinition(item,key){return item.property_schema?.[key]||((key==='position'||key==='bbox_to_anchor')?null:definitions[key]?{type:definitions[key][1]}:null);}
export function parseFigureProperty(item,key,value){
  if(!item||!item.supported_properties?.includes(key))throw new Error('所选对象已消失或不支持此属性；原覆盖保留。');
  const schema=propertyDefinition(item,key);if(!schema)throw new Error('请先重绘取得此属性的确切类型和坐标定义。');
  if(schema.type==='number'){if(value===''||!Number.isFinite(Number(value)))throw new Error('请输入有限数值；原覆盖保留。');const n=Number(value);if(key==='alpha'&&(n<0||n>1))throw new Error('不透明度必须在 0–1 之间。');if(n<(schema.minimum??-Infinity)||n>(schema.maximum??Infinity))throw new Error('数值超出此对象支持的范围；原覆盖保留。');return n;}
  if(schema.type==='boolean'){if(value===true||value==='true')return true;if(value===false||value==='false')return false;throw new Error('请选择显示/开启或隐藏/关闭。');}
  if(schema.type==='number_list'){let numbers;try{numbers=typeof value==='string'?JSON.parse(value):value;}catch{throw new Error('请输入 JSON 数值数组。');}if(!Array.isArray(numbers)||!numbers.length||numbers.some(x=>typeof x!=='number'||!Number.isFinite(x)||x<(schema.minimum??-Infinity)))throw new Error('需要非空、有限且不小于属性下界的数值数组。');return numbers;}
  if(schema.type==='color_values'){if(typeof value==='string'&&!value.trim().startsWith('['))return value;let colors;try{colors=typeof value==='string'?JSON.parse(value):value;}catch{throw new Error('请输入颜色名、十六进制颜色或 JSON RGB/RGBA 数组。');}const rgba=a=>Array.isArray(a)&&[3,4].includes(a.length)&&a.every(x=>typeof x==='number'&&Number.isFinite(x)&&x>=0&&x<=1);if(!rgba(colors)&&!(Array.isArray(colors)&&colors.length&&colors.every(rgba)))throw new Error('RGB/RGBA 每个通道须为 0–1；可以填写多个颜色数组。');return colors;}
  if(schema.type==='number_tuple'){let numbers;try{numbers=typeof value==='string'?JSON.parse(value):value;}catch{throw new Error('请输入 JSON 数值数组。');}if(!Array.isArray(numbers)||!schema.lengths.includes(numbers.length)||numbers.some(x=>typeof x!=='number'||!Number.isFinite(x)))throw new Error(`需要 ${schema.lengths.join(' 或 ')} 个有限数值的数组；原覆盖保留。`);if(numbers.some(x=>x<(schema.minimum??-Infinity)||x>(schema.maximum??Infinity)))throw new Error('坐标或尺寸超出支持范围。');if(key==='position'&&['axes','colorbar'].includes(item.type)&&(numbers[2]<=0||numbers[3]<=0))throw new Error('宽度和高度必须大于零。');if(key==='figsize'&&numbers.some(x=>x<=0))throw new Error('画布宽度和高度必须大于零。');return numbers;}
  if(key==='loc'&&/^\d+$/.test(String(value))){const n=Number(value);if(n>10)throw new Error('图例位置编号须为 0–10，或填写 Matplotlib 位置名称。');return n;}
  return String(value);
}
export function updatedFigureOverlays(content,item,key,raw){
  const value=parseFigureProperty(item,key,raw),layers=structuredClone(overlayLayers(content));let layer=layers.find(x=>(x.target||x.object_id||x.id)===item.id);
  if(!layer){layer={target:item.id,properties:{}};layers.push(layer);}
  if(!layer.properties){layer.properties=Object.fromEntries(Object.entries(layer).filter(([k])=>!['target','object_id','id'].includes(k)));for(const k of Object.keys(layer))if(!['target','object_id','id','properties'].includes(k))delete layer[k];}
  layer.properties[key]=value;return layers;
}
export function figurePropertyGroup(item,key){
 const groups=item.property_groups;if(groups){if(groups.layout?.includes(key))return 'layout';if(groups.appearance?.includes(key)||groups.content?.includes(key))return 'visualization';}
 return key==='position'||key==='bbox_to_anchor'||key==='figsize'||key.startsWith('subplot_')||key==='rotation'||key==='loc'?'layout':'visualization';
}
function tupleKeyboardStep(item,key,schema){
  // Only the renderer's explicit Figure/SubFigure axis-bound coordinates use
  // this increment. A normalized hit box says nothing about setter units.
  return key==='position'&&['axes','colorbar'].includes(item.type)&&Array.isArray(schema.lengths)&&schema.lengths.includes(4)&&typeof schema.coordinates==='string'&&schema.coordinates.startsWith('所属 Figure/SubFigure 归一化坐标 ')?'0.01':'any';
}
export function figureControls(item,layer,{group=null,cmapScope='matching',cmapInfo=null}={}){
  return (item.supported_properties||[]).filter(key=>!group||figurePropertyGroup(item,key)===group).map(key=>{
    const schema=propertyDefinition(item,key),value=figurePropertyValue(item,layer,key),label=definitions[key]?.[0]||({position:item.type==='axes'?'轴位置 [左, 下, 宽, 高]':item.type==='colorbar'?'色条位置 [左, 下, 宽, 高]':'文字位置 [x, y]',bbox_to_anchor:'图例锚点 [x, y] 或 [x, y, 宽, 高]'}[key]||key);
    if(!schema)return `<p class="hint">${esc(label)}：请先重绘，读取坐标定义与当前值。</p>`;
    const type=schema.type;
    const structured=['number_tuple','number_list','color_values'].includes(type);
    let input;
    if(key==='cmap')input=`${cmapInfo?`<select data-edit="figure-cmap-scope" aria-label="色图作用范围"><option value="matching" ${cmapScope==='matching'?'selected':''}>相同显示标度的图层＋色条</option><option value="current" ${cmapScope==='current'?'selected':''}>仅当前对象及所属数据层</option></select><details class="cmap-targets" ${cmapScope==='current'?'open':''}><summary>${cmapInfo.layers.length} 个数据层 · ${cmapInfo.colorbars.length} 个色条</summary><p class="hint">${esc(cmapInfo.reason)}</p>${cmapInfo.targets.map(x=>`<code>${esc(x.id)}</code>`).join('<br>')}</details>${cmapScope==='current'?'<p class="notice warning cmap-current-warning">仅当前改动可能与其他同标度图层或共享色条失配。采用前核对整图和图注。</p>':''}`:''}${cmapControl(key,value)}`;
    else if(['color','facecolor','edgecolor'].includes(key))input=colorControl(key,value);
    else if(type==='number_tuple'&&Array.isArray(value))input=`<div class="tuple-controls" data-tuple="${esc(key)}">${value.map((n,i)=>`<label><small>${esc(key==='figsize'?['宽','高'][i]:key==='position'&&['axes','colorbar'].includes(item.type)?['左','下','宽','高'][i]:['x','y','宽','高'][i]||i+1)}</small><input type="number" step="${tupleKeyboardStep(item,key,schema)}" data-overlay-tuple="${esc(key)}" data-index="${i}" value="${esc(n)}" aria-label="${esc(label)} ${i+1}"></label>`).join('')}</div>`;
    else if(type==='number'){
     const presets={alpha:[0,1,.01],fontsize:[1,72,.5],tick_fontsize:[1,48,.5],linewidth:[0,12,.1],markersize:[0,40,.5],rotation:[-180,180,1]},r=presets[key]||(key.startsWith('subplot_')?[schema.minimum??0,schema.maximum??(key.endsWith('space')?2:1),.01]:null);
     input=`<div class="number-controls">${r?`<input type="range" data-edit="overlay-${esc(key)}" min="${schema.minimum??r[0]}" max="${schema.maximum??r[1]}" step="${r[2]}" value="${esc(value??r[0])}" aria-label="${esc(label)}滑块">`:''}<input data-edit="overlay-${esc(key)}" type="number" step="any" ${schema.minimum!=null?`min="${schema.minimum}"`:''} ${schema.maximum!=null?`max="${schema.maximum}"`:''} value="${esc(value??'')}" aria-label="${esc(label)}数值"></div>`;
    }else input=type==='boolean'?`<select data-edit="overlay-${key}">${value===undefined?'<option value="">读取值后选择</option>':''}<option value="true" ${value===true?'selected':''}>显示 / 开启</option><option value="false" ${value===false?'selected':''}>隐藏 / 关闭</option></select>`:`<input data-edit="overlay-${key}" type="text" value="${esc(value==null?'':structured&&Array.isArray(value)?JSON.stringify(value):value)}" ${structured?'spellcheck="false"':''}>`;
    return `<label class="field compact"><span>${esc(label)}</span>${input}${key==='cmap'?'<small class="hint cmap-scope">按上方作用范围更新显示编码；图注颜色描述需同步核对。</small>':''}${schema.coordinates?`<small class="hint">${esc(schema.coordinates)}</small>`:''}</label>`;
  }).join('');
}
export function orphanedFigureOverlays(manifest,content){return overlayLayers(content).filter(layer=>!manifest.some(m=>m.id===(layer.target||layer.object_id||layer.id)));}

export function figureDragCapability(item,content={},object=null){
  const drag=item?.interaction?.drag;
  const deny=reason=>({enabled:false,reason});
  if(!drag?.enabled)return deny(drag?.reason||'此渲染尚无确切拖动坐标，请先重绘；仍可选中和编辑属性。');
  if(item.interaction.version!==1||drag.screen_coordinates!=='whole_figure_normalized_top_left')return deny('无法识别此渲染的坐标约定。');
  const matrix=drag.delta_matrix;
  if(!Array.isArray(matrix)||matrix.length!==2||matrix.some(row=>!Array.isArray(row)||row.length!==2||row.some(x=>!Number.isFinite(x)))||matrix[0][0]*matrix[1][1]===matrix[0][1]*matrix[1][0])return deny('拖动坐标无效；请重新渲染。');
  if(!item.supported_properties?.includes(drag.property)||!propertyDefinition(item,drag.property))return deny('此属性没有可重放的坐标定义。');
  if(object){
    const provenance=object.metadata?.last_export?.provenance;
    if(!provenance||provenance.object_id!==object.id||provenance.revision!==object.revision)return deny('预览属于其他或较早修订；请先重绘当前保存版本。');
    for(const key of ['script_asset','script','spec','parameters','input_assets'])if(figureValueKey(content[key])!==figureValueKey(object.content?.[key]))return deny('绘图来源已改动；保存、必要时授权并重绘后再拖动。');
  }
  const manifest=object?figureManifest(object,content):[];
  if(overlayLayers(content).some(layer=>{
    const target=manifest.find(x=>x.id===(layer.target||layer.object_id||layer.id));
    return target?.type==='axes'&&target.id!==item.id&&(layer.properties||layer).position&&figureValueKey((layer.properties||layer).position)!==figureValueKey(target.position);
  }))return deny('轴位置已有未渲染改动；先重绘更新关联 Artist 的坐标。');
  const layer=overlayLayers(content).find(x=>(x.target||x.object_id||x.id)===item.id);
  try{return {...drag,value:parseFigureProperty(item,drag.property,figurePropertyValue(item,layer,drag.property))};}catch(error){return deny(error.message);}
}

export function figurePreviewState(object,content,{dirty=false}={}){
  const output=object.metadata?.last_export,provenance=output?.provenance;
  const bound=!!provenance&&provenance.object_id===object.id&&Number.isInteger(provenance.revision)&&!!provenance.source_sha256;
  const mismatch=!bound||provenance.revision!==object.revision;
  const changes=overlayLayers(content).flatMap(layer=>{
    const id=layer.target||layer.object_id||layer.id,item=figureManifest(object,content).find(x=>x.id===id);
    return Object.entries(layer.properties||layer).filter(([key,value])=>!['target','object_id','id'].includes(key)&&(!item||figureValueKey(item[key])!==figureValueKey(value))).map(([property,value])=>({id,property,value}));
  });
  const pending=dirty||mismatch||changes.length>0||figureValueKey(content)!==figureValueKey(object.content);
  return {bound,pending,changes,provenance,message:bound?`图像来源：${object.id} @${provenance.revision} · ${provenance.source_sha256.slice(0,12)}。${pending?'当前修改尚未渲染；虚线框仅预览位置。请保存后显式重绘。':'当前保存版本已有渲染输出。'}`:'此预览没有可验证的完整渲染身份；请显式重绘当前保存版本。'};
}
