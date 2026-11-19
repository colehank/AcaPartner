import {LanguageDescription} from '@codemirror/language';
import {languages} from '@codemirror/language-data';

/** Upstream filename/alias matching, with the app's LaTeX name mapped to TeX. */
export function codeLanguage(language?:string,filename?:string){
  if(filename){const found=LanguageDescription.matchFilename(languages,filename.split('/').at(-1)!);if(found)return found;}
  if(!language||language==='plain'||language==='text')return null;
  return LanguageDescription.matchLanguageName(languages,language==='latex'?'stex':language,true)
    ||(language==='latex'?LanguageDescription.matchLanguageName(languages,'TeX',true):null);
}
