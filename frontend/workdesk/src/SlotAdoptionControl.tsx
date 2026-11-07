export type SlotAdoption={main_opinion_id:string,slot_id:string,leaf_opinion_id:string};
export type SlotAdoptionGroup={id:string,opinion_ids:string[]};
export type SlotAdoptionControlProps={opinions:any[],groups:SlotAdoptionGroup[],value:SlotAdoption[],disabled:boolean,onChange:(value:SlotAdoption[])=>void};

const nonempty=(value:unknown):value is string=>typeof value==='string'&&value.length>0;
const ids=(value:unknown):value is string[]=>Array.isArray(value)&&value.length>0&&value.every(nonempty)&&new Set(value).size===value.length;
function opinion(opinions:any[],id:string){const rows=opinions.filter(row=>row?.id===id);return rows.length===1&&!rows[0].deleted?rows[0]:undefined;}
function mainOpinion(opinions:any[],id:string){const row=opinion(opinions,id);return row?.field==='slot_layout'&&ids(row.slot_ids)?row:undefined;}
function leafOpinion(opinions:any[],id:string){const row=opinion(opinions,id);return row?.field==='visual_overlays'?row:undefined;}
function grouped(opinions:any[],groups:SlotAdoptionGroup[],main:string,leaf:string){
  return groups.some(group=>nonempty(group?.id)&&ids(group.opinion_ids)&&group.opinion_ids.length>=2
    &&group.opinion_ids.includes(main)&&group.opinion_ids.includes(leaf)
    &&group.opinion_ids.every(id=>!!opinion(opinions,id)));
}
function problem(opinions:any[],groups:SlotAdoptionGroup[],edge:SlotAdoption){
  if(!edge||!nonempty(edge.main_opinion_id)||!nonempty(edge.slot_id)||!nonempty(edge.leaf_opinion_id))return '来源关系身份不完整';
  const main=mainOpinion(opinions,edge.main_opinion_id);
  if(!main)return '主图意见已删除、缺失或身份不明确';
  if(!main.slot_ids.includes(edge.slot_id))return '图位已不在此主图意见的选择中';
  if(!leafOpinion(opinions,edge.leaf_opinion_id))return '叶图意见已删除、缺失或不是图元素意见';
  if(!grouped(opinions,groups,edge.main_opinion_id,edge.leaf_opinion_id))return '两条意见不在同一有效的明确关联组';
}
const key=(edge:SlotAdoption)=>JSON.stringify([edge?.main_opinion_id,edge?.slot_id]);

// This validates the user's explicit relation only. The server must separately
// check the saved source/pin, selected Artist and atomic adoption authority.
export function slotAdoptionProblem(opinions:any[],groups:SlotAdoptionGroup[],value:SlotAdoption[]):boolean{
  if(!Array.isArray(value))return true;
  if(!value.length)return false;
  if(!Array.isArray(opinions)||!Array.isArray(groups))return true;
  const seen=new Set<string>();
  return value.some(edge=>{const duplicate=seen.has(key(edge));seen.add(key(edge));return duplicate||!!problem(opinions,groups,edge);});
}

export function SlotAdoptionControl({opinions,groups,value,disabled,onChange}:SlotAdoptionControlProps){
  const rows=Array.isArray(opinions)?opinions:[],links=Array.isArray(value)?value:[],groupRows=Array.isArray(groups)?groups:[];
  const mains=rows.filter(row=>nonempty(row?.id)&&mainOpinion(rows,row.id)===row);
  const invalid=links.map((edge,index)=>({edge,index,reason:links.filter(other=>key(other)===key(edge)).length>1?'同一图位有多条来源关系':problem(rows,groupRows,edge)})).filter(row=>!!row.reason);
  const label=(row:any)=>{
    const text=typeof row.text==='string'&&row.text?row.text:'意见 '+(rows.indexOf(row)+1);
    return rows.filter(other=>other?.text===text).length>1?text+'（意见'+(rows.indexOf(row)+1)+'）':text;
  };
  const describe=(id:string)=>{const row=rows.find(row=>row?.id===id);return row?label(row):id;};
  return <section role="group" aria-label="本轮图位叶图来源">
    <p>只更新明确选定的图位；其他使用位置保持原版。来源变化时整组采用会停止并保留当前成果。</p>
    {!mains.length&&<p>本轮没有可指定叶图来源的主图图位意见。</p>}
    {mains.map(main=><fieldset key={main.id}>
      <legend>{label(main)}</legend>
      {main.slot_ids.map((slot:string)=>{
        const choices=rows.filter(row=>nonempty(row?.id)&&leafOpinion(rows,row.id)===row&&grouped(rows,groupRows,main.id,row.id));
        const existing=links.filter(edge=>edge?.main_opinion_id===main.id&&edge?.slot_id===slot),chosen=existing.length===1?existing[0]:undefined;
        const available=chosen&&choices.some(row=>row.id===chosen.leaf_opinion_id);
        const selected=chosen?chosen.leaf_opinion_id:'';
        return <label key={slot}>本轮更新图位 {slot} 的叶图来源<select aria-label={'本轮更新图位 '+slot+' 的叶图来源'} disabled={disabled} value={selected} onChange={event=>{
          if(disabled)return;
          const selected=event.target.value,leaf=choices.find(row=>row.id===selected);
          if(selected!==''&&!leaf)return;
          const next=links.filter(edge=>edge?.main_opinion_id!==main.id||edge?.slot_id!==slot);
          onChange(leaf?[...next,{main_opinion_id:main.id,slot_id:slot,leaf_opinion_id:leaf.id}]:next);
        }}>
          <option value="" disabled={existing.length>1}>{existing.length>1?'来源关系冲突，请明确移除或重新选择':'保持现有固定来源'}</option>
          {chosen&&!available&&<option value={chosen.leaf_opinion_id} disabled>已失效：{describe(chosen.leaf_opinion_id)}</option>}
          {choices.map(row=><option key={row.id} value={row.id}>{label(row)}</option>)}
        </select></label>;
      })}
    </fieldset>)}
    {invalid.length>0&&<div role="alert"><p>以下来源关系已失效；原输入保留，请明确移除或重新选择后提交。</p><ul>{invalid.map(({edge,index,reason})=><li key={index}>
      <span>{describe(edge?.main_opinion_id)} · 图位 {edge?.slot_id} → {describe(edge?.leaf_opinion_id)}：{reason}</span>
      <button type="button" disabled={disabled} aria-label={'移除失效图位来源关系 '+(index+1)} onClick={()=>{if(!disabled)onChange(links.filter((_,row)=>row!==index));}}>移除此来源关系</button>
    </li>)}</ul></div>}
  </section>;
}
