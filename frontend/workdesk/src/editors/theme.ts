import {useSyncExternalStore} from 'react';
import {githubLight,githubDark} from '@uiw/codemirror-theme-github';
export function editorTheme(dark:boolean){return dark?githubDark:githubLight;}
const listeners=new Set<()=>void>();let observer:MutationObserver|undefined;
const subscribe=(listener:()=>void)=>{listeners.add(listener);if(!observer){observer=new MutationObserver(()=>listeners.forEach(fn=>fn()));observer.observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});}return()=>{listeners.delete(listener);if(!listeners.size){observer?.disconnect();observer=undefined;}};};
export function useEditorDark(){return useSyncExternalStore(subscribe,()=>document.documentElement.dataset.theme==='dark',()=>false);}
