import React,{useEffect,useRef,useState} from 'react';

type Registration={enabled:boolean,registration_open:boolean};
const message=(error:unknown)=>error instanceof Error?error.message:String(error);

/** Local workspace access only. No email, external account or role setup. */
export function LocalAccountAccess({onAuthenticated}:{onAuthenticated:()=>Promise<void>}){
  const [registration,setRegistration]=useState<Registration|null>(null),[checking,setChecking]=useState(true);
  const [mode,setMode]=useState<'login'|'register'>('login');
  const [username,setUsername]=useState(''),[password,setPassword]=useState(''),[confirmation,setConfirmation]=useState('');
  const [busy,setBusy]=useState(false),[error,setError]=useState('');
  const live=useRef(true),request=useRef(0),submitting=useRef(false);
  const readRegistration=async()=>{
    const sequence=++request.current,current=()=>live.current&&request.current===sequence;
    setChecking(true);setError('');
    try{
      const response=await fetch('/api/auth/registration',{credentials:'same-origin'}),body=await response.json();
      if(!current())return;
      if(!response.ok||body.ok!==true)throw new Error(body.error||'无法读取本地账号设置。');
      const value=body.result;
      if(typeof value?.enabled!=='boolean'||typeof value?.registration_open!=='boolean')throw new Error('本地账号设置不完整，请重试。');
      setRegistration(value);
    }catch(e){if(current())setError(message(e));}
    finally{if(current())setChecking(false);}
  };
  useEffect(()=>{live.current=true;void readRegistration();return()=>{live.current=false;++request.current;};},[]);
  const changeMode=(next:'login'|'register')=>{
    if(submitting.current)return;
    ++request.current;setMode(next);setPassword('');setConfirmation('');setError('');
  };
  const submit=async(e:React.FormEvent)=>{
    e.preventDefault();if(submitting.current||checking||!registration?.enabled)return;
    setError('');
    if(!/^[A-Za-z0-9_.-]{3,32}$/.test(username)){setError('用户名须为 3–32 个字母、数字、下划线、点或短横线。');return;}
    if(password.length<8||password.length>128){setError('密码须为 8–128 个字符。');return;}
    if(mode==='register'&&password!==confirmation){setError('两次输入的密码不一致。');return;}
    if(mode==='register'&&!registration.registration_open)return;
    const sequence=++request.current,current=()=>live.current&&request.current===sequence;
    submitting.current=true;setBusy(true);
    try{
      const response=await fetch('/api/auth/'+mode,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password})});
      const body=await response.json();if(!current())return;
      if(!response.ok){
        if(mode==='register'&&response.status===409){
          setRegistration({enabled:true,registration_open:false});setMode('login');setPassword('');setConfirmation('');
          throw new Error('本机工作空间已建立账号，请使用已有账号登录。');
        }
        throw new Error(body.error||'登录失败，请核对用户名和密码。');
      }
      if(body.ok!==true||body.result?.authenticated!==true||body.result?.session_active!==true)throw new Error('登录状态未确认，请重试。');
      setPassword('');setConfirmation('');await onAuthenticated();
    }catch(e){if(current())setError(message(e));}
    finally{if(current()){submitting.current=false;setBusy(false);}}
  };
  return <div className="modal-backdrop"><form className="dialog" role="dialog" aria-label="本地账号" aria-busy={busy||checking} onSubmit={submit}>
    <h2>{mode==='register'?'建立本地账号':'登录项目空间'}</h2>
    <p>这是本机工作空间的账号，用于打开这里的项目和草稿。</p>
    {checking?<p role="status">读取本地账号设置…</p>:registration?.enabled===false?<p role="status">此实例尚未启用账号密码登录，请联系本机工作空间的维护者启用。</p>:registration?.registration_open&&<p>{mode==='register'?'为这个工作空间建立首个账号；建立后关闭公开注册。':'首次使用这个工作空间？请先注册本地账号。'}</p>}
    <label>用户名<input name="username" autoComplete="username" autoCapitalize="none" spellCheck={false} value={username} onChange={e=>setUsername(e.target.value)} minLength={3} maxLength={32} pattern={'[A-Za-z0-9_.\\-]{3,32}'} title="3–32 个字母、数字、下划线、点或短横线" disabled={busy||checking||registration?.enabled===false} required autoFocus/></label>
    <label>密码<input name="password" type="password" autoComplete={mode==='register'?'new-password':'current-password'} value={password} onChange={e=>setPassword(e.target.value)} minLength={8} maxLength={128} disabled={busy||checking||registration?.enabled===false} required/></label>
    {mode==='register'&&<label>确认密码<input name="password_confirmation" type="password" autoComplete="new-password" value={confirmation} onChange={e=>setConfirmation(e.target.value)} minLength={8} maxLength={128} disabled={busy} required/></label>}
    {error&&<div className="error" role="alert">{error}</div>}
    <div className="dialog-actions">
      {!checking&&!registration&&<button type="button" onClick={()=>void readRegistration()}>重试账号设置</button>}
      {registration?.enabled&&registration.registration_open&&<button type="button" disabled={busy} onClick={()=>changeMode(mode==='login'?'register':'login')}>{mode==='login'?'注册本地账号':'返回登录'}</button>}
      <button className="primary" disabled={busy||checking||!registration?.enabled}>{busy?'正在打开工作桌…':mode==='register'?'注册并进入工作桌':'登录并进入工作桌'}</button>
    </div>
  </form></div>;
}
