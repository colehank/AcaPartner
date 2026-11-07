import {useEffect,useId,useRef,useState,type KeyboardEvent,type PointerEvent} from 'react';

export type WorkspaceActions = {
  quickOpen:()=>void; search:()=>void; notes:()=>void; paper:()=>void; partner:()=>void;
  figure:()=>void; generation:()=>void; graph:()=>void; claims:()=>void; resetLayout:()=>void;
  retrySync?:()=>void;
  commission?:()=>void;
  researchCycle?:()=>void;
  tasks?:()=>void;
  guide?:()=>void;
};
export type WorkspaceChromeProps = {
  actions:WorkspaceActions;
  activeEditor?:string;
  activeTitle?:string;
  draftState:'synced'|'syncing'|'error';
  navigationOpen?:boolean;
  resettingLayout?:boolean;
  retryingSync?:boolean;
  hint?:string;
};
type Glyph='open'|'search'|'paper'|'note'|'partner'|'more'|'back'|'forward'|'save';
const paths:Record<Glyph,string>={
  open:'M3 5h6l2 2h10v12H3z M3 10h18',search:'M17 17l4 4 M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  paper:'M6 3h8l4 4v14H6z M14 3v5h4 M9 12h6 M9 16h6',note:'M5 3h14v18H5z M8 7h8 M8 11h8 M8 15h5',
  partner:'M3 4h18v13H9l-5 4v-4H3z M7 8h10 M7 12h7',more:'M5 12h.01 M12 12h.01 M19 12h.01',
  back:'M15 5l-7 7 7 7',forward:'M9 5l7 7-7 7',save:'M4 3h13l3 3v15H4z M8 3v6h8V3 M8 14h8v7H8z',
};
export function ChromeIcon({name}:{name:Glyph}){
  return <svg className="chrome-icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name]}/></svg>;
}

export type ChromeMenuItem={label:string;activate:()=>void;disabled?:boolean;pressed?:boolean;preserveEditorFocus?:boolean};
/** View-only menu. Opening tools never replaces the editor or its buffer. */
export function ChromeMenu({label,items,iconOnly=false,restoreEditorFocus=false}:{label:string;items:ChromeMenuItem[];iconOnly?:boolean;restoreEditorFocus?:boolean}){
  const [open,setOpen]=useState(false),id=useId(),button=useRef<HTMLButtonElement>(null),menu=useRef<HTMLDivElement>(null);
  const previousFocus=useRef<HTMLElement|null>(null);
  const remember=()=>{
    const current=document.activeElement;
    previousFocus.current=restoreEditorFocus&&current instanceof HTMLElement&&(current.isContentEditable||current instanceof HTMLInputElement||current instanceof HTMLTextAreaElement)?current:null;
  };
  const close=(restore=false)=>{
    setOpen(false);
    if(restore){const target=previousFocus.current?.isConnected?previousFocus.current:button.current;target?.focus({preventScroll:true});}
  };
  useEffect(()=>{
    if(!open)return;
    menu.current?.querySelector<HTMLButtonElement>('button:not(:disabled)')?.focus({preventScroll:true});
    const outside=(event:globalThis.PointerEvent)=>{
      if(!menu.current?.contains(event.target as Node)&&!button.current?.contains(event.target as Node))close();
    };
    document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);
  },[open]);
  const keys=(event:KeyboardEvent)=>{
    if(event.nativeEvent.isComposing||event.nativeEvent.keyCode===229)return;
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close(true);return;}
    if(event.key==='Tab'){button.current?.focus({preventScroll:true});close();return;}
    const controls=Array.from(menu.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)')||[]);
    if(!controls.length||!['ArrowDown','ArrowUp','Home','End'].includes(event.key))return;
    event.preventDefault();event.stopPropagation();const current=controls.indexOf(document.activeElement as HTMLButtonElement);
    const next=event.key==='Home'?0:event.key==='End'?controls.length-1:(current+(event.key==='ArrowUp'?-1:1)+controls.length)%controls.length;
    controls[next].focus();
  };
  return <div className="chrome-menu">
    <button ref={button} type="button" className={iconOnly?'chrome-icon-button':'chrome-tool'} aria-label={label} title={label} aria-haspopup="menu" aria-expanded={open} aria-controls={open?id:undefined}
      onPointerDown={remember} onClick={()=>setOpen(value=>!value)} onKeyDown={event=>{if(event.key==='ArrowDown'&&!event.nativeEvent.isComposing){event.preventDefault();remember();setOpen(true);}}}>
      <ChromeIcon name="more"/>{!iconOnly&&<span>{label}</span>}
    </button>
    {open&&<div ref={menu} id={id} className="chrome-menu-popup" role="menu" aria-label={label} onKeyDown={keys}>
      {items.map(item=><button type="button" key={item.label} role={item.pressed===undefined?'menuitem':'menuitemcheckbox'} aria-label={item.label}
        aria-checked={item.pressed} disabled={item.disabled} onClick={()=>{close(!!item.preserveEditorFocus);item.activate();}}>
        <span className="chrome-menu-check" aria-hidden="true">{item.pressed?'✓':''}</span><span>{item.label}</span>
      </button>)}
    </div>}
  </div>;
}
const editorNames:Record<string,string>={paper:'稿件',pdf:'排版稿',note:'项目笔记',review:'搭档',figure:'图画布',generation:'数据与生成',researchGraph:'问题与证据',claims:'稿件关系',navigation:'目录与检索',fixedSource:'固定来源',commission:'研究委托',researchCycle:'科研协作',projectTasks:'项目任务'};

export function WorkspaceChrome({actions,activeEditor,activeTitle,draftState,navigationOpen,resettingLayout,retryingSync,hint}:WorkspaceChromeProps){
  const editor=activeEditor?editorNames[activeEditor]||activeEditor:'';
  const tool=(label:string,text:string,icon:Glyph,activate:()=>void,pressed?:boolean)=><button type="button" className="chrome-tool" aria-label={label} title={label} aria-pressed={pressed} onClick={activate}><ChromeIcon name={icon}/><span>{text}</span></button>;
  return <div className="desk-toolbar workspace-chrome">
    <nav className="workspace-primary-tools" aria-label="工作桌工具">
      {tool('快速打开','快速打开','open',actions.quickOpen)}
      {tool('目录 / 搜索','目录 / 搜索','search',actions.search,navigationOpen)}
      <span className="chrome-divider" aria-hidden="true"/>
      {tool('打开论文','成果','paper',actions.paper,activeEditor==='paper'||activeEditor==='pdf')}
      {tool('随手记','笔记','note',actions.notes,activeEditor==='note')}
      {tool('搭档 / 整轮意见','搭档','partner',actions.partner,activeEditor==='review')}
    </nav>
    <output className="workspace-context" aria-label="当前工作区" title={activeTitle||editor}>{editor&&<span>{editor}</span>}{activeTitle&&<strong>{activeTitle}</strong>}</output>
    <span className={'workspace-draft-state '+draftState} role="status"><i aria-hidden="true"/>{draftState==='synced'?'草稿已同步':draftState==='error'?'草稿同步失败':'草稿待同步'}</span>
    {draftState==='error'&&actions.retrySync&&<button type="button" className="chrome-tool" disabled={retryingSync}
      onMouseDown={event=>event.preventDefault()} onClick={actions.retrySync}>{retryingSync?'正在重试同步…':'重试同步'}</button>}
    <ChromeMenu label="项目工具" items={[
      ...(actions.commission?[{label:'发起研究委托',activate:actions.commission}]:[]),
      ...(actions.researchCycle?[{label:'发起有限科研协作',activate:actions.researchCycle}]:[]),
      ...(actions.tasks?[{label:'项目任务',activate:actions.tasks}]:[]),
      {label:'图 / 来源链',activate:actions.figure},
      {label:'数据 / 变化重做',activate:actions.generation},
      {label:'问题 / 证据关系',activate:actions.graph},
      {label:'稿件 / Claim关系',activate:actions.claims},
      {label:'恢复默认布局',activate:actions.resetLayout,disabled:resettingLayout},
    ]}/>
    {actions.guide&&<button type="button" className="chrome-tool workspace-guide-entry" aria-label="使用引导" onClick={actions.guide}>使用引导</button>}
    {hint&&<span className="workspace-hint" role="status">{hint}</span>}
  </div>;
}

export const preserveEditorPointerFocus=(event:PointerEvent<HTMLButtonElement>)=>{if(event.button===0)event.preventDefault();};
