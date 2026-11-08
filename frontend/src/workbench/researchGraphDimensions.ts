/** Fixed view bounds; zoom changes disclosure, never the research layout. */
export function researchNodeDimensions(node:{kind:string}){
 return {width:256,height:node.kind==='E'?212:180};
}
