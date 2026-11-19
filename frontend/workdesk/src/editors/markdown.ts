import {useEffect,useState} from 'react';
import MarkdownIt from 'markdown-it';
import type {HighlighterCore} from 'shiki/core';
import {fromHighlighter,type MarkdownItShikiSetupOptions} from '@shikijs/markdown-it/core';

// Local imports only. Scientific languages are kept explicit to bound the browser bundle.
let highlighter:HighlighterCore|undefined,pending:Promise<void>|undefined;
const listeners=new Set<()=>void>();let version=0;
function prepare(){return pending??=(async()=>{
 const [{createHighlighterCore},{createJavaScriptRegexEngine},light,dark,...langs]=await Promise.all([
  import('shiki/core'),import('shiki/engine/javascript'),
  import('@shikijs/themes/github-light-default'),import('@shikijs/themes/github-dark-default'),
  import('@shikijs/langs/python'),import('@shikijs/langs/r'),import('@shikijs/langs/latex'),
  import('@shikijs/langs/json'),import('@shikijs/langs/yaml'),import('@shikijs/langs/toml'),
  import('@shikijs/langs/bash'),import('@shikijs/langs/javascript'),import('@shikijs/langs/typescript'),
  import('@shikijs/langs/julia'),import('@shikijs/langs/sql'),
 ]);
 highlighter=await createHighlighterCore({themes:[light.default,dark.default],langs:langs.map(v=>v.default),engine:createJavaScriptRegexEngine()});
 version++;listeners.forEach(fn=>fn());
})().catch(error=>{console.warn('代码高亮加载失败，保持纯文本。',error);});}
export function useMarkdownHighlight(){const [value,setValue]=useState(version);useEffect(()=>{const update=()=>setValue(version);listeners.add(update);void prepare().then(update);return()=>{listeners.delete(update);};},[]);return value;}
export function markdownParser(options:{html?:boolean;linkify?:boolean}={}){
 const parser=new MarkdownIt({html:false,...options});
 if(highlighter)parser.use(fromHighlighter(highlighter,{themes:{light:'github-light-default',dark:'github-dark-default'},fallbackLanguage:'text' as MarkdownItShikiSetupOptions['fallbackLanguage']}));
 const highlight=parser.options.highlight;if(highlight)parser.options.highlight=(code,lang,attrs)=>new TextEncoder().encode(code).length>65536?parser.utils.escapeHtml(code):highlight(code,lang,attrs);
 return parser;
}
