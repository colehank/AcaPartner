import {reviewAuthorDisplay,type ReviewAuthorContext} from './ReviewAuthorIdentity';

/** Read-only label; full saved audit identity remains available on request. */
export function ReviewAuthor({identity,kind,route,prefix=''}:ReviewAuthorContext&{identity:unknown,prefix?:string}){
  const display=reviewAuthorDisplay(identity,{kind,route});
  return <div className="review-author" data-author-kind={display.kind}>
    <small>{prefix}<span aria-label="记录的作者">{display.label}</span></small>
    {(display.identity||display.route)&&<details><summary>查看作者身份</summary>
      <p>{display.kind==='agent'?'此标识来自本轮已保存的 Agent 路线与会话。':'此标识来自已保存审计记录；未核对姓名或当前登录人。'}</p>
      {display.identity&&<code>{display.identity}</code>}
      {display.route&&<p>记录的路线：<code>{display.route}</code></p>}
    </details>}
  </div>;
}
