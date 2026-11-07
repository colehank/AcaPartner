/** Reading location belongs to content, not the temporary height of unloaded images. */
export function readingKey41(workspace, objectId, region) {
  return 'research-partner:reading41:'+JSON.stringify([workspace,objectId,region]);
}

export function captureReading41(root, objectId) {
  const page=root.querySelector('.manuscript-page'),frame=root.querySelector('.manuscript-surface');
  if(!page||!frame||page.dataset.manuscriptObject!==objectId)return null;
  const area=frame.getBoundingClientRect();
  const candidates=[...page.querySelectorAll('[data-block],.manuscript-component')]
    .map(el=>({el,rect:el.getBoundingClientRect()}))
    .filter(({rect})=>rect.bottom>area.top&&rect.top<area.bottom)
    .sort((a,b)=>Math.abs(a.rect.top-area.top)-Math.abs(b.rect.top-area.top));
  const first=candidates[0];if(!first)return null;
  return {objectId,block:first.el.dataset.block||null,component:first.el.dataset.componentId||null,
    index:first.el.dataset.componentIndex==null?null:Number(first.el.dataset.componentIndex),offset:first.rect.top-area.top};
}

export function restoreReading41(root, position) {
  if(!position||!Number.isFinite(position.offset))return false;
  const page=root.querySelector('.manuscript-page'),frame=root.querySelector('.manuscript-surface');
  if(!page||!frame||page.dataset.manuscriptObject!==position.objectId)return false;
  const element=[...page.querySelectorAll('[data-block],.manuscript-component')].find(el=>
    position.block?el.dataset.block===position.block:
    el.dataset.componentId===position.component&&Number(el.dataset.componentIndex)===position.index);
  if(!element)return false;
  frame.scrollTop+=element.getBoundingClientRect().top-frame.getBoundingClientRect().top-position.offset;
  return true;
}
