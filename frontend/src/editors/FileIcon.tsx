import type {CSSProperties} from 'react';
import {codeLanguage} from './languages';
import theme from './assets/seti-theme.json';
import './file-icons.css';
const t=theme as any;
function iconId(path:string,light=false){
 const name=path.split('/').at(-1)||'',layer=light?t.light:t;
 let id=layer?.fileNames?.[name]||t.fileNames?.[name];
 const parts=name.split('.');
 for(let i=1;!id&&i<parts.length;i++){const suffix=parts.slice(i).join('.');id=layer?.fileExtensions?.[suffix]||t.fileExtensions?.[suffix];}
 const language=codeLanguage(undefined,path);
 const languageId=language&&(language.alias.find(alias=>layer?.languageIds?.[alias]||t.languageIds?.[alias])||language.name.toLowerCase());
 return id||(languageId&&(layer?.languageIds?.[languageId]||t.languageIds?.[languageId]))||(light?t.light?.file:undefined)||t.file;
}
export function FileIcon({path}:{path:string}){
 const id=iconId(path),dark=t.iconDefinitions[id],light=t.iconDefinitions[iconId(path,true)]||dark;
 return <span className="wb-file-icon" aria-hidden="true" data-icon-id={id} data-file-icon={path.split('/').at(-1)} style={{'--file-ink':light.fontColor,'--file-ink-dark':dark.fontColor} as CSSProperties}>{String.fromCodePoint(parseInt(dark.fontCharacter.replace('\\',''),16))}</span>;
}
