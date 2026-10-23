// Local value identity, not the service's SHA encoding. Preserve negative zero
// and distinguish structured user metadata from primitive values.
export function captionComponentIdentity(component:unknown):string{
  function encoded(value:any):any{
    if(Array.isArray(value))return ['array',value.map(encoded)];
    if(value===null)return ['null'];
    if(typeof value==='object')return ['object',Object.keys(value).sort().map(key=>[key,encoded(value[key])])];
    if(typeof value==='number')return ['number',Object.is(value,-0)?'-0':String(value)];
    return [typeof value,value];
  }
  return JSON.stringify(encoded(component));
}
