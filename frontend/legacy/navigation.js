const outputKinds=new Set(['report','note','paper','figure','diagram','poster','slides','workshop','commission']);
export function projectArtifacts(objects,project){
  const visible=objects.filter(o=>!o.archived&&outputKinds.has(o.kind)&&(!project||o.project_id===project.id));
  const featured=project?.metadata?.featured_objects||[];
  return visible.sort((a,b)=>{
    const ai=featured.indexOf(a.id),bi=featured.indexOf(b.id);
    if(ai>=0||bi>=0)return ai<0?1:bi<0?-1:ai-bi;
    return String(b.updated_at).localeCompare(String(a.updated_at));
  });
}
export function entryNavigation(search,objects){
  const params=new URLSearchParams(search),id=params.get('object'),project=params.get('project');
  if(id){const o=objects.find(o=>o.id===id);if(o)return o.kind==='project'?{view:'projects',project:o.id}:{view:'workspace',project:o.project_id,object:o.id};return null;}
  return project&&objects.some(o=>o.id===project&&o.kind==='project')?{view:'projects',project}:null;
}
export function objectLink(origin,id){return new URL('/?object='+encodeURIComponent(id),origin).href;}
