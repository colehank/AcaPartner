import {useEffect,useRef,useState,type KeyboardEvent} from 'react';
import {createPortal} from 'react-dom';
import './workspace-guide.css';

export type GuideModule='workspace'|'paper'|'review'|'figure'|'sources'|'generation'|'notes'|'commission'|'collaboration'|'tasks'|'graph'|'claims'|'pdf';
type Step={module:GuideModule,title:string,goal:string,entry:string,practice:string,boundary:string};
const steps:Step[]=[
  {module:'workspace',title:'项目与工作桌',goal:'在同一个项目中安排稿件、笔记、图和搭档面板。拖动标签可以停靠，面板也可并排或放大。',entry:'顶部“当前项目”切换项目；“新建项目”建立空项目。“项目工具”集中其他模块。',practice:'可选：先观察当前项目名称和面板标签；无需切换或重排。',boundary:'切换项目前先查看“草稿已同步”。“恢复默认布局”会重排面板，请仅在确实需要时使用；阅读本引导不会调整布局。'},
  {module:'paper',title:'连续稿件',goal:'直接在连续正文中阅读和编辑，保留段落、引用与稿内图的身份。阅读、审查和编辑是同一份稿件的不同操作模式。',entry:'“成果”打开连续稿件；顶部切换“阅读 / 审查 / 编辑”。文字直接修改用“保存文字”。',practice:'可选：切到阅读模式，找到一个已有段落，再返回编辑；不必输入新文字。',boundary:'“草稿已同步”表示工作桌草稿已保存，不代表正文已采用为新保存版。直接保存与建议修订分别处理。'},
  {module:'review',title:'选区批注与整轮意见',goal:'将意见定位到正文或图注选区，再集中整理同一回合的意见、搭档回应和候选修改。',entry:'在稿件选择原文后用“新建批注”；“搭档 / 整轮意见”打开回合面板。“上一项 / 下一项”定位审阅话题。',practice:'可选：选中一句已有文字，观察“新建批注”是否可用；无需提交意见。',boundary:'批注、搭档回复和候选修订不自动成为采用稿。接受或拒绝由你明确决定；调用搭档执行另需路线、权限与预算。'},
  {module:'figure',title:'科研图画布',goal:'在已有主图或叶图中选择实际元素，查看支持的视觉属性、缩放和布局；已有源图决定可编辑范围。',entry:'“项目工具 → 图 / 来源链”打开画布；先选择“当前图”。主图可以进入源子图查看元素。',practice:'可选：选择一个已有图或元素，观察属性栏；没有图时先了解空状态，无需登记脚本。',boundary:'修改某些视觉属性可能触发预览重绘，预览也可能执行代码。先核对脚本权限；“采用图形调整”才更新保存图。静态图不具备全部元素编辑能力。'},
  {module:'sources',title:'固定来源与当前来源',goal:'区分成果当时引用的固定修订与来源现在的保存版，避免把较新输入误当成历史结果的依据。',entry:'图中“数据 / 代码 / 结果链”查看当前图的实际输入与运行；问题关系的“读取固定来源”、Claim 的“查看 Claim 固定来源”打开对应历史修订。',practice:'可选：记录来源对象 ID 与固定修订，或输入文件的 SHA；有当前修订时，只比较同一个来源对象。没有来源时保留缺口。',boundary:'固定来源按指定修订只读，关闭后回到现稿。来源关系已登记，不等于证据已经支持结论；不要为练习改用最新修订。'},
  {module:'generation',title:'数据、代码与计算链',goal:'从数据身份、实际代码和生成配方追到真实运行；区分待执行计划、核验复用与已有结果。',entry:'“项目工具 → 数据 / 变化重做”；面板内有“数据身份”“实际代码”“生成配方”“计划 / 运行”。',practice:'可选：查看一个已有运行的输入或代码；没有运行时浏览各页签，不必登记数据。',boundary:'登记或保存定义不等于运行。“授权并启动此固定计划”会执行代码并使用资源；本地执行不是操作系统安全沙箱。本引导不授权或启动计算。'},
  {module:'notes',title:'原生笔记与检索',goal:'在项目的真实 Markdown 文件中记笔记，并用目录、最近记录、收藏或检索返回具体位置。',entry:'“笔记”打开已有笔记；“目录 / 搜索”展开导航。Ctrl/⌘+K 快速打开，Ctrl/⌘+Shift+F 打开检索入口。',practice:'可选：搜索一个已知词，观察命中路径与摘要；没有笔记时先看目录，不必新建。',boundary:'笔记的草稿同步与“保存”文件不同。冲突时先比较原文件和手改；不要为完成引导覆盖文件。检索范围可选当前项目或获授权项目。'},
  {module:'commission',title:'研究委托',goal:'把问题、允许的方法、保存来源和产出检查条件组织成一项可核对的委托。',entry:'“项目工具 → 发起研究委托”；先描述目标，再用“解析保存来源”核对采用的材料。',practice:'可选：阅读表单字段与执行器状态；无需填写、勾选确认或提交。',boundary:'执行器未运行（NoRunner）时不能提交执行；以模块显示的当前状态为准。执行仍须明确路线与预算；模型调用可能收费，次数和时限不代表金额上限。'},
  {module:'collaboration',title:'有限科研协作',goal:'围绕同一目标分配有限角色、步骤与返工额度，并查看规划、审查和交接状态。',entry:'“项目工具 → 发起有限科研协作”；查看来源、角色及合计调用和执行秒数上限。',practice:'可选：找到预算与“确认有限协作范围与预算”所在位置，保持确认框未勾选。',boundary:'执行器未运行（NoRunner）时不开放执行登记；以模块显示的当前状态为准。真实执行需要可用执行器和授权路线；额度不等于费用上限，形成候选或审查记录不代表科学或用户验收。'},
  {module:'tasks',title:'项目任务与回报',goal:'查看当前项目实际登记的任务、状态和回报，从任务返回候选、稿件或来源。',entry:'“项目工具 → 项目任务”；按状态查看并用“打开任务”进入具体回报。',practice:'可选：阅读一个已有任务的状态；空列表表示当前没有可见任务，无需创建演示。',boundary:'排队不代表已经执行；完成状态不等于候选已采用。暂停、取消、重试或恢复分别是明确操作，引导不会代你操作任务。'},
  {module:'graph',title:'问题与证据关系',goal:'查看科研问题、对象和有向关系，把候选解释与已经登记的关系分开阅读。',entry:'“项目工具 → 问题 / 证据关系”；从对象打开实际材料，或从关系读取固定来源。',practice:'可选：找到一条已有关系，查看它的方向和来源；没有关系时不必补造内容。',boundary:'图谱表达已保存的关系记录，不自动判定因果或科学支持。“候选”“登记”“科学确认”是不同状态。阅读不要求启动模型。'},
  {module:'claims',title:'稿件 Claim 与证据',goal:'将保存稿件中的准确选区与特定来源修订关联，查看来源更新或选区变化带来的缺口。',entry:'“项目工具 → 稿件 / Claim关系”；选择保存段落、准确引文与固定来源，先提出候选，再明确登记。',practice:'可选：查看已有 Claim 的引文和修订号；正文有未保存草稿时先保留草稿，不为练习清空。',boundary:'此模块依据保存稿件，草稿未保存时可能暂停读取。登记 Claim 不会修改正文，也不代表科学结论已确认；引导不提出或接受候选。'},
  {module:'pdf',title:'当前 PDF、保存与重开',goal:'比较编辑稿、保存稿和已编译 PDF，在退出或重开前确认哪些内容已经持久保存。',entry:'稿件“排版预览”打开 PDF；“编译保存版”针对保存稿重新编译。顶部“退出登录”先同步草稿。',practice:'可选：查看保存修订和 PDF 状态；无需为练习编译或退出。回到固定“使用引导”入口可重看任一步。',boundary:'PDF 可能落后于保存稿；本机未配置编译器时如实显示未生成。草稿同步、保存正文、编译和下载是不同步骤。退出失败保留当前工作桌与草稿。'},
];
const key='research-partner.workspace-guide.v1';
type Progress={version:1,status:'deferred'|'in_progress'|'completed',step:number};
let memory:Progress|null=null;
function readProgress():Progress|null{
  if(memory)return memory;
  try{
    const value=JSON.parse(localStorage.getItem(key)||'null');
    if(value?.version===1&&['deferred','in_progress','completed'].includes(value.status)&&Number.isInteger(value.step)&&value.step>=0&&value.step<steps.length)return value;
  }catch{/* Restricted storage must never block the workdesk. */}
  return memory;
}
function saveProgress(status:Progress['status'],step:number){
  memory={version:1,status,step};
  try{localStorage.setItem(key,JSON.stringify(memory));}catch{/* In-memory progress still allows reopening during this page session. */}
}

/** A local guide. Only the explicit module button calls existing navigation. */
export function WorkspaceGuide({openRequest,onOpenModule}:{openRequest:number,onOpenModule:(module:GuideModule)=>void|Promise<void>}){
  const [initial]=useState(readProgress),[view,setView]=useState<'welcome'|'steps'|null>(()=>readProgress()?null:'welcome');
  const [index,setIndex]=useState(initial?.step||0),[contents,setContents]=useState(false),[busy,setBusy]=useState(false),[error,setError]=useState('');
  const heading=useRef<HTMLHeadingElement>(null),dialog=useRef<HTMLDivElement>(null),returnFocus=useRef<HTMLElement|null>(null),live=useRef(true);
  const seenRequest=useRef(openRequest),opening=useRef(false);
  const restore=()=>{const target=returnFocus.current?.isConnected&&returnFocus.current!==document.body?returnFocus.current:document.querySelector<HTMLElement>('[aria-label="使用引导"]');target?.focus({preventScroll:true});};
  useEffect(()=>{live.current=true;return()=>{live.current=false;};},[]);
  useEffect(()=>{
    if(openRequest===seenRequest.current)return;
    seenRequest.current=openRequest;setView('steps');setContents(false);setError('');
  },[openRequest]);
  useEffect(()=>{
    if(!view)return;
    returnFocus.current=document.activeElement instanceof HTMLElement?document.activeElement:null;
  },[!!view]);
  useEffect(()=>{if(view)heading.current?.focus({preventScroll:true});},[view,index,contents]);
  const close=(status:Progress['status']='deferred')=>{
    if(opening.current)return;
    saveProgress(status,index);setView(null);setContents(false);restore();
  };
  const change=(next:number)=>{if(opening.current)return;setIndex(next);setContents(false);setError('');saveProgress('in_progress',next);};
  const keyboard=(event:KeyboardEvent)=>{
    if(event.nativeEvent.isComposing||event.nativeEvent.keyCode===229)return;
    if(event.key==='Escape'){event.preventDefault();event.stopPropagation();close();return;}
    if(event.key==='Tab'){
      const controls=Array.from(dialog.current?.querySelectorAll<HTMLElement>('button:not(:disabled),a[href],[tabindex="0"]')||[]),at=controls.indexOf(document.activeElement as HTMLElement);
      if(event.shiftKey&&at<=0){event.preventDefault();controls.at(-1)?.focus();}
      else if(!event.shiftKey&&at===controls.length-1){event.preventDefault();controls[0]?.focus();}
    }
    if(view==='steps'&&!contents&&(event.key==='ArrowRight'||event.key==='ArrowLeft')){event.preventDefault();change(Math.max(0,Math.min(steps.length-1,index+(event.key==='ArrowRight'?1:-1))));}
  };
  const openModule=async()=>{
    if(opening.current)return;
    opening.current=true;setBusy(true);setError('');
    try{await onOpenModule(steps[index].module);if(live.current){
      const target=document.activeElement,focusMoved=target instanceof HTMLElement&&target!==document.body&&!dialog.current?.contains(target);
      saveProgress('in_progress',index);setView(null);setContents(false);if(!focusMoved)restore();
    }}
    catch(e){if(live.current)setError(e instanceof Error?e.message:String(e));}
    finally{opening.current=false;if(live.current)setBusy(false);}
  };
  if(!view)return null;
  const step=steps[index];
  return createPortal(<div className="workspace-guide-backdrop" data-workspace-guide onKeyDown={keyboard}>
    <div className="workspace-guide" ref={dialog} role="dialog" aria-modal="true" aria-labelledby="workspace-guide-title" aria-describedby="workspace-guide-summary" aria-busy={busy}>
      <div className="workspace-guide-top"><span>Research Partner · 使用引导</span><button type="button" onClick={()=>close()} disabled={busy} aria-label="关闭引导">关闭</button></div>
      <div className="workspace-guide-body">
        {view==='welcome'?<>
          <p className="workspace-guide-kicker">从一个项目开始</p><h2 id="workspace-guide-title" ref={heading} tabIndex={-1}>认识你的研究工作桌</h2>
          <p id="workspace-guide-summary">用 {steps.length} 个简短主题，找到稿件、意见、图、笔记和任务的真实入口。每一步都有可选练习，可以只读、跳过或随时结束。</p>
          <p>引导不要求填写材料，也不会代你保存正文、运行代码、调用模型或授权费用。执行器未运行（NoRunner）时，研究任务不能提交执行；实际执行能力以模块显示的当前状态为准。</p>
          <p>以后从工具栏的“使用引导”重新打开。引导进度只保存在此浏览器，不会写入项目。</p>
        </>:contents?<>
          <h2 id="workspace-guide-title" ref={heading} tabIndex={-1}>引导目录</h2><p id="workspace-guide-summary">按当前需要选择主题；切换主题不会打开模块或修改项目。</p>
          <ol className="workspace-guide-contents">{steps.map((row,i)=><li key={row.module}><button type="button" aria-current={i===index?'step':undefined} onClick={()=>change(i)}>{row.title}</button></li>)}</ol>
        </>:<>
          <p className="workspace-guide-kicker">{index+1} / {steps.length}</p><h2 id="workspace-guide-title" ref={heading} tabIndex={-1}>{step.title}</h2>
          <p id="workspace-guide-summary">{step.goal}</p>
          <dl><dt>从哪里进入</dt><dd>{step.entry}</dd><dt>试一试</dt><dd>{step.practice}</dd><dt>保存与执行边界</dt><dd>{step.boundary}</dd></dl>
          <button className="workspace-guide-open" type="button" disabled={busy} onClick={()=>void openModule()}>{busy?'正在打开…':'打开此模块'}</button>
          <p className="workspace-guide-open-hint">打开后收起引导；再次点击“使用引导”会回到这一步。只有这个按钮会打开模块；上一 / 下一步只切换说明。</p>
          {error&&<p className="workspace-guide-error" role="alert">{error}</p>}
        </>}
      </div>
      <div className="workspace-guide-footer">
        {view==='welcome'?<><button type="button" onClick={()=>close()}>稍后再看</button><button type="button" className="workspace-guide-start" onClick={()=>{saveProgress('in_progress',index);setView('steps');}}>开始引导</button></>:<>
          <button type="button" disabled={busy} onClick={()=>close(index===steps.length-1?'completed':'deferred')}>{index===steps.length-1?'完成引导':'结束引导'}</button>
          <button type="button" disabled={busy} aria-pressed={contents} onClick={()=>setContents(!contents)}>目录</button>
          <span className="workspace-guide-spacer"/>
          <button type="button" disabled={busy||index===0} onClick={()=>change(index-1)}>上一步</button>
          <button type="button" disabled={busy||index===steps.length-1} onClick={()=>change(index+1)}>下一步</button>
        </>}
      </div>
    </div>
  </div>,document.body);
}
