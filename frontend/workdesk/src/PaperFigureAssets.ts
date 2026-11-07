import {useEffect,useState} from 'react';
import {command} from './api';
import {captionComponentIdentity} from './PaperFigureIdentity';

export type PaperFigureOccurrence={key:string,after_block_id:string,caption:string,previewUrl?:string,ref:{id:string,revision:number,sha256?:string},error?:string,componentIdentity:string};

// Saved occurrence -> exact registered figure -> matching saved render. Reading
// a manuscript does not authorize a redraw or substitute a current head.
export function usePaperFigures(projectId:string,paperId:string,components:any[]):PaperFigureOccurrence[]{
  const key=JSON.stringify([projectId,paperId,components]),[state,setState]=useState<{key:string,rows:PaperFigureOccurrence[]}>({key:'',rows:[]});
  useEffect(()=>{
    let live=true;
    const rows:PaperFigureOccurrence[]=components.map((component,index)=>({key:paperId+':'+index,
      after_block_id:component.after_block_id||'end',caption:component.caption||'',componentIdentity:captionComponentIdentity(component),
      ref:{id:component.id||component.object_id,revision:component.revision,...(component.sha256?{sha256:component.sha256}:{})},error:'读取此位置的保存版图…'}));
    setState({key,rows:structuredClone(rows)});
    let cursor=0;
    const next=async()=>{while(live&&cursor<rows.length){const index=cursor++,row=rows[index];
      try{
        if(typeof row.ref.id!=='string'||!Number.isSafeInteger(row.ref.revision)||row.ref.revision<1)throw Error('稿内对象缺少准确固定修订；未读取当前版本。');
        const view=await command('desk.figure.read',{project_id:projectId,id:row.ref.id,revision:row.ref.revision});
        if(!live)return;
        // Legacy saved occurrences may omit their optional hash. The actual
        // registered read must still identify the source before matching a
        // render; two absent hashes must never count as an identity match.
        if(view.figure?.id!==row.ref.id||view.figure?.revision!==row.ref.revision||view.figure?.kind!=='figure'||view.source_ref?.id!==row.ref.id||view.source_ref?.revision!==row.ref.revision||
           typeof view.source_ref?.sha256!=='string'||!/^[a-f0-9]{64}$/.test(view.source_ref.sha256)||
           (row.ref.sha256&&view.source_ref.sha256!==row.ref.sha256))throw Error('稿内图的保存身份不一致；未展示其他修订。');
        const render=view.render,assets=render?.assets;
        if(!render||render.provenance?.source_sha256!==view.source_ref.sha256)throw Error('此固定修订尚无匹配输出；可进入画布查看来源。');
        const image=assets?.['canvas.png']||assets?.['figure.png']||assets?.['canvas.svg']||assets?.['figure.svg'];
        if(!image||!/^[a-f0-9]{64}$/.test(image.sha))throw Error('此保存版没有可展示的图像输出。');
        rows[index]={...row,previewUrl:'/api/assets/'+image.sha,error:undefined};
      }catch(error){if(!live)return;rows[index]={...row,error:error instanceof Error?error.message:String(error)};}
      if(live)setState({key,rows:structuredClone(rows)});
    }};
    void next();void next();return()=>{live=false;};
  },[key]);
  return state.key===key?state.rows:[];
}
