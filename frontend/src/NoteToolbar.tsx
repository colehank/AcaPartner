import {ChromeIcon,ChromeMenu,preserveEditorPointerFocus} from './WorkspaceChrome';

export type NoteToolbarProps={
  path:string; dirty:boolean; saving?:boolean; missingSource?:boolean; reading:boolean; favorite:boolean; pinned:boolean;
  reviewOpen?:boolean; managing?:boolean;
  onBack:()=>void; onForward:()=>void; onSave:()=>void; onToggleReading:()=>void;
  onToggleFavorite:()=>void; onTogglePinned:()=>void; onSplit:()=>void; onToggleReview:()=>void; onFileTools:()=>void;
};

/** Commands remain owned by NotePanel. This toolbar never mounts the editor. */
export function NoteToolbar(props:NoteToolbarProps){
  return <div className="panel-tools note-toolbar" role="toolbar" aria-label="笔记工具">
    <button type="button" className="chrome-icon-button" aria-label="返回上一文件和位置" title="返回上一文件和位置" onClick={props.onBack}><ChromeIcon name="back"/></button>
    <button type="button" className="chrome-icon-button" aria-label="前进" title="前进" onClick={props.onForward}><ChromeIcon name="forward"/></button>
    <span className="path note-location" title={props.path}><span aria-label={props.dirty?'笔记未保存到文件':'笔记已保存到文件'} className={'note-dirty-marker '+(props.dirty?'dirty':'')} aria-hidden={!props.dirty}>●</span>{props.path}</span>
    <button type="button" aria-pressed={props.reading} onClick={props.onToggleReading}>{props.reading?'编辑':'阅读'}</button>
    <button type="button" className="primary note-save" disabled={props.saving||!props.dirty||props.missingSource} onPointerDown={preserveEditorPointerFocus} onClick={props.onSave}>
      <ChromeIcon name="save"/>{props.saving?'保存中…':'保存'}
    </button>
    <ChromeMenu label="笔记更多工具" iconOnly restoreEditorFocus items={[
      {label:'收藏笔记',pressed:props.favorite,activate:props.onToggleFavorite,preserveEditorFocus:true},
      {label:'固定笔记',pressed:props.pinned,activate:props.onTogglePinned,preserveEditorFocus:true},
      {label:'分屏',activate:props.onSplit},
      {label:'笔记批注 / 历史',pressed:!!props.reviewOpen,activate:props.onToggleReview},
      {label:'文件操作',pressed:!!props.managing,activate:props.onFileTools},
    ]}/>
  </div>;
}
