import type {Ref} from 'react';
export type Capture={bytes:Uint8Array;generation:number};
export type DocxHandle={capture:()=>Promise<Capture>};
export type DocxEditorProps={
  ref:Ref<DocxHandle>;initial:Uint8Array|null;title:string;theme:'light'|'dark';
  onReady:()=>void;onChange:(generation:number)=>void;
  onSnapshot:(capture:Capture)=>void;onError:(error:unknown)=>void;onSave:()=>void;onOpen:()=>void;
  status?:string;local?:boolean;ready?:boolean;onDownload?:()=>void;
  primary?:boolean;onMakePrimary?:()=>void;onReload?:()=>void;busy?:boolean;
};
