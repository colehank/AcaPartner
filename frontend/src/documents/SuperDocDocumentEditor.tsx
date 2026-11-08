import {useEffect,useImperativeHandle,useRef,useState} from 'react';
import {SuperDocEditor,type SuperDocRef,type DocumentMode} from '@superdoc/react';
import * as Menu from '@radix-ui/react-dropdown-menu';
import type {Config} from 'superdoc';
import {superdocToolbar} from './superdoc-toolbar';
import type {Capture,DocxEditorProps} from './DocxEditorAdapter';
import '@superdoc/react/style.css';
import './superdoc-workspace.css';

const exportOptions={triggerDownload:false,policies:{trackedChanges:'review-preserving',comments:'preserve',contentControls:'preserve'}} as const;
const localAuthor={name:'本机用户',email:'local-user@acapartner.invalid'};
const zoom={mode:'fit-width',fitWidth:{padding:40,max:200}} as const;
const message=(e:unknown)=>e instanceof Error?e.message:String(e);

function FileMenu({options:p,ready,openChanged}:{options:DocxEditorProps;ready:boolean;openChanged:(open:boolean)=>void}){
  return <Menu.Root onOpenChange={openChanged}><Menu.Trigger className="native-superdoc-file" aria-label="文件">文件</Menu.Trigger><Menu.Portal><Menu.Content className="native-document-menu" data-theme="light" sideOffset={5} align="start" collisionPadding={8}>
    <Menu.Label className="native-document-info">{p.title}</Menu.Label>
    {p.status&&<Menu.Label className="native-document-info"><span className="native-save-status" role="status">{p.status}</span></Menu.Label>}
    <Menu.Separator/>
    <Menu.Item disabled={p.busy} onSelect={p.onOpen}>打开…</Menu.Item>
    <Menu.Item disabled={!ready||p.busy} onSelect={p.onSave}>{p.local?'保存副本':'保存'}</Menu.Item>
    {p.onDownload&&<Menu.Item disabled={!ready||p.busy} onSelect={p.onDownload}>下载当前草稿</Menu.Item>}
    {p.onMakePrimary&&<Menu.Item disabled={p.busy||p.primary||!ready} onSelect={p.onMakePrimary}>{p.primary?'当前论文源稿':'设为论文源稿'}</Menu.Item>}
    {p.onReload&&<Menu.Item disabled={p.busy} onSelect={p.onReload}>保留草稿并载入项目保存版</Menu.Item>}
    <Menu.Separator/>
    <Menu.Item asChild><a href="/workdesk/licenses/superdoc/README.txt" target="_blank" rel="noreferrer">编辑器许可说明</a></Menu.Item>
  </Menu.Content></Menu.Portal></Menu.Root>;
}

/** SuperDoc owns OOXML/layout/review; the workbench owns storage and revisions. */
export default function SuperDocDocumentEditor(props:DocxEditorProps){
  const editor=useRef<SuperDocRef>(null),frame=useRef<HTMLDivElement>(null),callbacks=useRef(props),alive=useRef(true),readyRef=useRef(false),generation=useRef(0),menuOpen=useRef(false);
  const timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),queue=useRef<Promise<unknown>>(Promise.resolve());
  callbacks.current=props;
  const [ready,setReady]=useState(false),[error,setError]=useState(''),[mode,setMode]=useState<DocumentMode>('editing');
  const [toolbarId]=useState(()=> 'superdoc-toolbar-'+crypto.randomUUID());
  const stageId=toolbarId+'-stage';
  // Freeze the source for this lifecycle. A title/status change after saving must
  // never recreate the upstream document from its old input bytes.
  const [file]=useState(()=>props.initial?new File([new Uint8Array(props.initial).buffer],props.title,{type:'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}):undefined);
  const [ui]=useState<Config['ui']>(()=>({toolbar:{...superdocToolbar,container:'#'+toolbarId,responsiveTo:'container',overflow:'menu',excludeItems:['document-mode','measurement-unit','ruler']},comments:{layout:'auto',responsive:{target:'#'+stageId,breakpoint:900}}}));
  function openFailed(){
    readyRef.current=false;setReady(false);
    setError('文稿无法打开。原文件和已保留的草稿未改动，请从“文件 → 打开…”选择有效的 DOCX。');
  }
  function capture():Promise<Capture>{
    clearTimeout(timer.current);
    const job=queue.current.catch(()=>{}).then(async()=>{
      const instance=editor.current?.getInstance(),version=generation.current;
      if(!alive.current||!readyRef.current||!instance)throw new Error('DOCX 编辑器尚未准备好，请稍后重试。');
      const blob=await instance.export(exportOptions),bytes=new Uint8Array(await blob.arrayBuffer());
      if(!alive.current||instance!==editor.current?.getInstance())throw new Error('文稿已切换，请在当前文稿中重试。');
      return {bytes,generation:version};
    });
    queue.current=job.catch(()=>{});return job;
  }
  useImperativeHandle(props.ref,()=>({capture}),[]);
  function changed(){
    if(!alive.current||!readyRef.current)return;
    callbacks.current.onChange(++generation.current);clearTimeout(timer.current);
    timer.current=setTimeout(()=>{void capture().then(value=>{if(alive.current)callbacks.current.onSnapshot(value);}).catch(e=>{if(alive.current)callbacks.current.onError(e);});},650);
  }
  useEffect(()=>{
    const shortcuts=(e:KeyboardEvent)=>{
      if(!frame.current?.getClientRects().length||(!frame.current.contains(document.activeElement)&&!menuOpen.current))return;
      if((e.metaKey||e.ctrlKey)&&['s','o'].includes(e.key.toLowerCase())){
        e.preventDefault();if(callbacks.current.busy)return;
        if(e.key.toLowerCase()==='s'){if(readyRef.current)callbacks.current.onSave();}else callbacks.current.onOpen();
      }
    };
    window.addEventListener('keydown',shortcuts);
    return()=>{alive.current=false;readyRef.current=false;clearTimeout(timer.current);window.removeEventListener('keydown',shortcuts);};
  },[]);
  return <div ref={frame} className="docx-editor-frame native-superdoc-frame" role="region" aria-label="DOCX 论文编辑器">
    <div className="native-docx-editor native-superdoc-editor" data-theme="light">
      <div className="native-docx-commandbar native-superdoc-commandbar" aria-label="文档操作">
        <FileMenu options={props} ready={ready} openChanged={value=>{menuOpen.current=value;}}/>
        <div id={toolbarId} className="native-superdoc-formatting"/>
        <select className="native-superdoc-mode" aria-label="文稿模式" value={mode} disabled={!ready||props.busy} onChange={e=>setMode(e.target.value as DocumentMode)}><option value="editing">编辑</option><option value="suggesting">修订</option><option value="viewing">阅读</option></select>
      </div>
      {error&&<div className="native-superdoc-error" role="alert"><span>{error}</span>{!ready&&<button onClick={props.onOpen}>打开其他 DOCX</button>}<button onClick={()=>setError('')}>关闭提示</button></div>}
      <div id={stageId} className="native-superdoc-stage" inert={props.busy}>
        <SuperDocEditor ref={editor} document={file} contained documentMode={mode} viewing={{trackedChanges:'markup'}} allowSelectionInViewMode user={localAuthor} telemetry={{enabled:false}} ui={ui} zoom={zoom} rulers={false}
          onReady={()=>{if(!alive.current)return;readyRef.current=true;setReady(true);callbacks.current.onReady();}}
          onEditorUpdate={changed} onCommentsUpdate={changed}
          onContentError={()=>{if(alive.current)openFailed();}}
          onException={value=>{if(!alive.current)return;if(!readyRef.current)openFailed();else setError('文稿操作未完成，请重试或下载当前草稿。'+message('error' in value?value.error:value));}}/>
      </div>
    </div>
  </div>;
}
