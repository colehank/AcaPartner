export type NativeTextSelection={start_offset:number,end_offset:number,text:string};

// DOM endpoints count UTF-16 code units. The file contract counts Unicode
// code points and hashes the original UTF-8, including BOM and CRLF.
export function nativeTextSelection(element:HTMLElement,markdown:string,selection:Selection|null):NativeTextSelection|null{
  if(!selection||selection.rangeCount!==1||selection.isCollapsed||element.textContent!==markdown)return null;
  const range=selection.getRangeAt(0);
  if(!element.contains(range.startContainer)||!element.contains(range.endContainer))return null;
  const prefix=range.cloneRange();prefix.selectNodeContents(element);prefix.setEnd(range.startContainer,range.startOffset);
  const start=prefix.toString().length;prefix.setEnd(range.endContainer,range.endOffset);const end=prefix.toString().length;
  const boundary=(at:number)=>at===0||at===markdown.length||!(markdown.charCodeAt(at)>=0xdc00&&markdown.charCodeAt(at)<=0xdfff&&markdown.charCodeAt(at-1)>=0xd800&&markdown.charCodeAt(at-1)<=0xdbff);
  if(start<0||end<=start||end>markdown.length||!boundary(start)||!boundary(end))return null;
  const text=markdown.slice(start,end);
  if(range.toString()!==text)return null;
  return {start_offset:Array.from(markdown.slice(0,start)).length,end_offset:Array.from(markdown.slice(0,end)).length,text};
}
