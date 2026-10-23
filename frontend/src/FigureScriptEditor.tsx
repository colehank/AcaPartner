import {useEffect,useRef,useState} from 'react';
import {CodeEditor,type TextPosition} from './CodeEditor';
import {command,CommandError,requestId} from './api';
import type {Session} from './session';

type Intent={key:string,code:string,figure:any,figureCode:string,sha:string,version:number};
type Draft={editing:boolean,code:string,base:any,baseCode:string,sha:string,position:Partial<TextPosition>,version:number,phase:'idle'|'pending'|'unknown',intent?:Intent,receiptMissing?:boolean,error:string,notice:string};
// This memory belongs to the actual Session, not a project-global draft store.
// Closing the source tab cannot discard a dirty or uncertain save intent.
const drafts=new WeakMap<Session,Map<string,Draft>>();
const same=(a:any,b:any):boolean=>Object.is(a,b)||!!a&&!!b&&typeof a==='object'&&typeof b==='object'&&Array.isArray(a)===Array.isArray(b)&&Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>Object.hasOwn(b,k)&&same(a[k],b[k]));
const shaPattern=/^[a-f0-9]{64}$/;
const codeError=(code:string)=>!code.trim()?'源码不能为空。':code.includes('\0')?'源码不能包含空字符。':/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(code)?'源码包含无效 Unicode 字符。':new TextEncoder().encode(code).length>1024*1024?'源码超过 1 MiB 保存边界。':'';
const codeSha=async(code:string)=>Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(code)))).map(x=>x.toString(16).padStart(2,'0')).join('');
function assertReceipt(value:any,intent:Intent,expectedSha:string){
  const old=intent.figure,f=value?.figure,saved=value?.saved;
  if(typeof saved!=='boolean'||value.executed!==false||value.manuscript_updated!==false||typeof value.render_required!=='boolean'||typeof value.authorization_required!=='boolean'||saved&&(!value.render_required||!value.authorization_required)||value.replayed!==undefined&&value.replayed!==true)
    throw new Error('源码保存回执身份或执行边界不完整；结果尚未确认。');
  const scriptSha=saved?expectedSha:intent.sha;
  if(!f||f.id!==old.id||f.project_id!==old.project_id||f.kind!=='figure'||f.archived||f.revision!==old.revision+(saved?1:0)||f.content?.script_asset!==scriptSha||value.script?.sha!==scriptSha||saved&&value.script.size!==new TextEncoder().encode(intent.code).length||!saved&&intent.code!==intent.figureCode)
    throw new Error('源码保存回执的图、项目、修订或脚本身份不符；结果尚未确认。');
  const {revision:oldRevision,updated_at:oldTime,...oldFields}=old;
  const {revision:newRevision,updated_at:newTime,...newFields}=f;
  if(!same(newFields,{...oldFields,content:{...old.content,script_asset:scriptSha}})||typeof newTime!=='string')
    throw new Error('源码保存回执改变了其他保存字段；结果尚未确认。');
}

export function FigureScriptEditor({session:s,view,readOnly,busy,visualDirty,onSavingChange,onSaved}:{session:Session,view:any,readOnly:boolean,busy:boolean,visualDirty:boolean,onSavingChange:(value:boolean,owner:string)=>void,onSaved:(result:any)=>Promise<void>}){
  const project=s.project.id,id=view.figure.id,key=project+'\0'+id,sourceCode=view.source.code,sourceSha=view.source.script?.sha;
  const valid=typeof sourceCode==='string'&&typeof sourceSha==='string'&&shaPattern.test(sourceSha)&&view.figure.project_id===project&&view.figure.kind==='figure'&&!view.figure.archived&&!view.definition&&!view.figure.content.composition&&view.figure.content.script_asset===sourceSha&&view.source_ref?.id===id&&view.source_ref.revision===view.figure.revision&&shaPattern.test(view.source_ref.sha256||'');
  let memory=drafts.get(s);if(!memory){memory=new Map();drafts.set(s,memory);}
  let entry=memory.get(key);
  if(!entry&&valid){entry={editing:false,code:sourceCode,base:structuredClone(view.figure),baseCode:sourceCode,sha:sourceSha,position:{cursor:0},version:0,phase:'idle',error:'',notice:''};memory.set(key,entry);}
  const [,render]=useState(0),alive=useRef(false),scope=useRef({s,project,id,entry});scope.current={s,project,id,entry};
  useEffect(()=>{alive.current=true;return()=>{alive.current=false;if(entry?.phase==='pending'){entry.phase='unknown';entry.error='原保存结果尚未确认；保留原请求与草稿，不自动重发。';}};},[s,project,id,entry]);
  const changed=()=>render(x=>x+1);
  const stale=!!entry&&(entry.base.revision!==view.figure.revision||entry.sha!==sourceSha||!same(entry.base,view.figure));
  const dirty=!!entry&&entry.code!==entry.baseCode;
  const validation=entry?codeError(entry.code):'';
  const perform=async(mode:'save'|'receipt'|'retry'='save')=>{
    const original=mode!=='save';
    if(!entry||!valid||readOnly||busy||visualDirty||entry.phase==='pending'||!original&&(stale||validation||entry.phase==='unknown')||mode==='retry'&&!entry.receiptMissing)return;
    const draft=entry,context={s,project,id,entry},current=()=>alive.current&&scope.current.s===context.s&&scope.current.project===context.project&&scope.current.id===context.id&&scope.current.entry===context.entry&&s.project.id===project;
    const intent=original?draft.intent:{key:requestId(),code:draft.code,figure:structuredClone(draft.base),sha:draft.sha,version:draft.version,figureCode:draft.baseCode};
    if(!intent)return;
    const owner=requestId();
    draft.intent=intent;draft.receiptMissing=false;draft.phase='pending';draft.error='';draft.notice='';changed();onSavingChange(true,owner);
    let confirmed=false;
    try{
      const expected=await codeSha(intent.code);if(!current())return;
      const result=await command(mode==='receipt'?'desk.figure.script.receipt':'desk.figure.script.save',{project_id:project,id,expected_revision:intent.figure.revision,expected_script_sha256:intent.sha,code:intent.code,request_key:intent.key});
      if(!current())return;
      if(mode==='receipt'){
        if(result?.found===false&&result.executed===false&&Object.keys(result).length===2){draft.phase='unknown';draft.receiptMissing=true;draft.error='原保存尚未登记；草稿与原请求保留。可另行明确重试原保存，不会保存后手改动。';changed();return;}
        if(result?.found!==true||result.replayed!==true)throw new Error('原保存回执核对结果身份不完整；结果尚未确认。');
      }
      assertReceipt(result,intent,expected);confirmed=true;
      draft.base=structuredClone(result.figure);draft.baseCode=intent.code;draft.sha=result.script.sha;draft.phase='idle';draft.intent=undefined;
      draft.notice=(result.saved?'源码已保存为同一叶图 r'+result.figure.revision+'。需要另行明确授权并重绘；稿内固定引用未更新。':'源码未变化；保存版与原授权保持。')+(draft.code!==intent.code?' 后续输入仍未保存。':'');
      changed();onSavingChange(false,owner);await onSaved(result);
    }catch(error){
      if(!current())return;
      const definite=error instanceof CommandError&&['csrf','unauthorized','forbidden','conflict','idempotency_conflict','context_limit','invalid_figure','validation_error'].includes(error.code);
      // A fresh read with equal text cannot confirm an uncertain POST. Only the
      // original key's explicit idempotency receipt can close that intent.
      if(!confirmed){draft.phase=definite&&!original?'idle':'unknown';draft.error=(error instanceof Error?error.message:String(error))+(draft.phase==='unknown'?' 原保存结果尚未确认；保留原请求与草稿，不自动重发。':' 草稿保留；请核对当前权限与保存基线。');}
      else draft.error='源码保存已经确认，但重新读取失败：'+(error instanceof Error?error.message:String(error));
      changed();
    }finally{onSavingChange(false,owner);}
  };
  return <section aria-label="绘图源码修订" role="region">
    <h3>此叶图绘图源码</h3><p>保存只修订当前叶图的脚本资产，不执行代码；授权、重绘和稿内采用分别操作。</p>
    {!valid?<p role="alert">没有身份完整的可读 UTF-8 脚本；不能编辑此来源。</p>:readOnly?<><p>固定历史源码 · 只读</p><pre>{sourceCode}</pre></>:entry&&<>
      {!entry.editing?<><pre>{sourceCode}</pre><button disabled={busy||visualDirty} onClick={()=>{entry!.editing=true;changed();}}>编辑绘图源码</button>{dirty&&<p role="status">有未保存源码草稿；再次编辑可继续。</p>}</>:<>
        <div style={{height:320,minHeight:180,display:'flex',flexDirection:'column',border:'1px solid var(--border,#667)'}}><CodeEditor language="plain" ariaLabel="绘图源码编辑器" text={entry.code} initial={entry.position} viewId={'figure-script:'+project+':'+id} onPosition={value=>{entry!.position=value;}} onChange={value=>{entry!.code=value;entry!.version++;changed();}}/></div>
        <p role="status">{dirty?'未保存源码草稿':'源码与已确认保存版一致'} · 基线 r{entry.base.revision}</p>
        {stale&&<p role="alert">当前保存版已有变化；原源码草稿保留，不能以旧基线保存。</p>}
        {validation&&<p role="alert">{validation}</p>}
        <button disabled={busy||visualDirty||stale||!!validation||entry.phase!=='idle'} onClick={()=>{void perform();}}>保存此叶图源码</button>
        {entry.phase==='unknown'&&<button disabled={busy||visualDirty} onClick={()=>{void perform('receipt');}}>核对原保存回执</button>}
        {entry.phase==='unknown'&&entry.receiptMissing&&<button disabled={busy||visualDirty} onClick={()=>{void perform('retry');}}>重试原保存</button>}
        {stale&&entry.phase==='idle'&&<button disabled={busy||visualDirty} onClick={()=>{entry!.base=structuredClone(view.figure);entry!.baseCode=sourceCode;entry!.sha=sourceSha;entry!.error='';entry!.notice='已明确选择当前保存版为基线；保留源码草稿，请先比较后保存。';changed();}}>基于当前保存版继续编辑</button>}
      </>}
      {entry.notice&&<p role="status">{entry.notice}</p>}{entry.error&&<p role="alert">{entry.error}</p>}
    </>}
  </section>;
}
