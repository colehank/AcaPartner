"""Native note move/trash/restore with stable identity and durable intent.

The Linux backend uses renameat2(NOREPLACE), so a competing destination is
never overwritten. Markdown is unchanged. Known relative links are reported,
not silently rewritten. Recovery reconciles only the recorded file operation;
it never launches research or guesses an external rename from identical text.
"""
import ctypes
import errno
import json
import os
import posixpath
import re
import uuid
from urllib.parse import unquote,urlsplit
from research_partner.storage.store import Problem,require,digest,encoded,now
from research_partner.domains.workspace.notebook import _components,_open_dir,_parent,_read_at,_replace_at,_decode

ACTIONS={'notes.move.inspect','notes.move','notes.trash','notes.trash.list','notes.restore','notes.resolve'}


def _rename(src,name,dst,target):
    libc=ctypes.CDLL(None,use_errno=True);fn=getattr(libc,'renameat2',None)
    require(fn is not None,'后端缺少无覆盖原子移动；未改动文件','runtime_unavailable',503)
    fn.argtypes=[ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint];fn.restype=ctypes.c_int
    if fn(src,os.fsencode(name),dst,os.fsencode(target),1):
        error=ctypes.get_errno()
        if error==errno.EEXIST:raise Problem('目标路径已存在；双方文件均保留','notes_conflict',409)
        raise OSError(error,os.strerror(error))
    os.fsync(src);os.fsync(dst)


def _revision(service,project,path):return service._key('revision',project)+':'+digest(path.encode())


def _resolve_links(markdown,path):
    result=[];fence=None
    for number,line in enumerate(markdown.splitlines(),1):
        marker=re.match(r'^ {0,3}(`{3,}|~{3,})',line)
        if marker:
            token=marker.group(1)
            if fence is None:fence=token[0]
            elif fence==token[0]:fence=None
            continue
        if fence:continue
        for match in re.finditer(r'!?\[[^\]]*\]\(([^\s)]+)(?:\s+"[^"\n]*")?\)',line):
            target=match.group(1).strip('<>');url=urlsplit(target)
            if url.scheme or url.netloc or not url.path:continue
            actual=posixpath.normpath(posixpath.join(posixpath.dirname(path),unquote(url.path)))
            result.append({'line':number,'literal_target':target,'resolved_path':actual})
    return result


def inspect(service,session,old,new):
    raw=service._read_file(session,old);documents,_=service._scan(session)
    outgoing=[];incoming=[]
    for link in _resolve_links(_decode(raw),old):
        moved=posixpath.normpath(posixpath.join(posixpath.dirname(new),unquote(urlsplit(link['literal_target']).path)))
        if moved!=link['resolved_path']:outgoing.append({**link,'after_move_path':moved})
    for d in documents:
        if d['relative_path']==old:continue
        for link in _resolve_links(d['markdown'],d['relative_path']):
            if link['resolved_path']==old:incoming.append({'source_path':d['relative_path'],**link})
    return {'incoming':incoming,'outgoing':outgoing,'rewritten':False,'syntax_scope':'inline Markdown links/images outside fenced code; other extensions require manual review'}


def _finalize(service,session,record,actual):
    project=session['project_id'];old=record['old_path'];new=record.get('new_path');entry=record['entry'];op=record['op']
    with service.store.transaction() as c:
        receipt=c.execute('SELECT value FROM kv WHERE key=?',(record['receipt_key'],)).fetchone()
        if receipt:
            saved=json.loads(receipt[0]);require(saved['input']==record['input'],'文件恢复请求身份不符','notes_integrity',409);return saved['result']
        if op in {'move','trash'}:c.execute('DELETE FROM kv WHERE key=?',(_revision(service,project,old),))
        if op in {'move','restore'}:
            key=_revision(service,project,new);existing=c.execute('SELECT value FROM kv WHERE key=?',(key,)).fetchone()
            if existing and json.loads(existing[0]).get('note_id')!=entry['note_id']:
                previous=json.loads(existing[0])
                # The recorded no-overwrite rename proved the destination was
                # absent. A stale path registry is historical data, not a live
                # file to merge with the explicitly moved note.
                c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('notebook:retired:'+project+':'+previous['note_id'],encoded(previous)))
            entry={**entry,'relative_path':new,'path_history':entry.get('path_history',[])+[{'op':op,'from':old,'to':new,'at':record['at']}]}
            c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(key,encoded(entry)))
        if op=='trash':
            c.execute('INSERT INTO kv VALUES(?,?)',('notebook:trash:'+project+':'+record['trash_id'],encoded({**record,'deleted':True})))
        if op=='restore':c.execute('UPDATE kv SET value=? WHERE key=?',(encoded({**record,'deleted':False}),'notebook:trash:'+project+':'+record['trash_id']))
        nav_key=service._key('navigation',project);row=c.execute('SELECT value FROM kv WHERE key=?',(nav_key,)).fetchone()
        if row and op in {'move','trash'}:
            nav=json.loads(row[0]);index=nav['history_index'];prior=nav['history'][:index+1]
            for name in ['history','recent']:
                nav[name]=[{**r,'relative_path':new} if r['relative_path']==old else r for r in nav[name] if op!='trash' or r['relative_path']!=old]
            nav['favorites']=[new if p==old else p for p in nav['favorites'] if op!='trash' or p!=old]
            if op=='trash':nav['history_index']=sum(r['relative_path']!=old for r in prior)-1
            c.execute('UPDATE kv SET value=? WHERE key=?',(encoded(nav),nav_key))
        revisions={}
        if op in {'move','trash'}:
            for namespace in ['drafts','layout']:
                cache_key='desk_w1a:'+namespace+':'+project;row=c.execute('SELECT value FROM kv WHERE key=?',(cache_key,)).fetchone()
                if not row:continue
                state=json.loads(row[0]);value=state['value']
                if namespace=='drafts' and old in value.get('buffers',{}):
                    buffer=value['buffers'].pop(old)
                    if op=='move':value['buffers'][new]={**buffer,'path':new}
                if namespace=='layout':
                    for panel in (value.get('layout') or {}).get('panels',{}).values():
                        if panel.get('params',{}).get('path')==old:
                            if op=='move':panel['params']['path']=new
                            else:panel['params']['trashed']=True
                    for ident,view in list(value.get('views',{}).items()):
                        if view.get('path')==old:
                            if op=='move':view['path']=new
                            else:del value['views'][ident]
                    locations=value.get('locations',{})
                    if old in locations:
                        prior=locations.pop(old)
                        if op=='move':locations[new]={**prior,'path':new}
                    for locations in value.get('view_locations',{}).values():
                        if old in locations:
                            prior=locations.pop(old)
                            if op=='move':locations[new]={**prior,'path':new}
                    if value.get('active_path')==old:value['active_path']=new or ''
                state.update(revision=state['revision']+1,updated_at=now());revisions[namespace]=state['revision']
                c.execute('UPDATE kv SET value=? WHERE key=?',(encoded(state),cache_key))
        result={'op':op,'note_id':entry['note_id'],'old_path':old,'relative_path':new,'trash_id':record.get('trash_id'),'content_sha256':digest(actual),'file_changed_during_operation':digest(actual)!=record['content_sha256'],'links':record.get('links'),'bytes_preserved':True}
        result['desk_revisions']=revisions
        c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',(record['receipt_key'],encoded({'input':record['input'],'result':result})))
        service.store.event(c,'notes.file.'+op,project,result,'file_service')
    if op!='trash':service._document(session,new,actual,'file_'+op,record['request_id'])
    return result


def recover(service,session):
    fd=session['file_ops']
    for filename in sorted(os.listdir(fd)):
        require(re.fullmatch(r'[a-f0-9]{32}\.json',filename),'文件操作日志名无效','notes_integrity',409)
        record=json.loads(_read_at(fd,filename));require(record['project_id']==session['project_id'],'文件操作项目不符','notes_integrity',409)
        source_tree=session['trash'] if record['op']=='restore' else session['notes']
        source_parts=[record['trash_id']+'.md'] if record['op']=='restore' else _components(record['old_path'])[1:]
        target_tree=session['trash'] if record['op']=='trash' else session['notes']
        target_parts=[record['trash_id']+'.md'] if record['op']=='trash' else _components(record['new_path'])[1:]
        with _parent(source_tree,source_parts) as (src,name),_parent(target_tree,target_parts,create=True) as (dst,target):
            before=_read_at(src,name,absent=True);actual=_read_at(dst,target,absent=True)
            if actual is not None:
                info=os.stat(target,dir_fd=dst,follow_symlinks=False)
                moved=(info.st_dev,info.st_ino)==tuple(record['source_inode']) or (before is None and digest(actual)==record['content_sha256'])
                require(moved,'恢复不能确认移动身份；保留双方路径，不按同名或同内容合并','notes_integrity',409)
                if before is not None:
                    original=os.stat(name,dir_fd=src,follow_symlinks=False)
                    require((original.st_dev,original.st_ino)!=tuple(record['source_inode']),'源文件仍在，目标身份有歧义','notes_integrity',409)
                _finalize(service,session,record,actual)
                os.unlink(filename,dir_fd=fd);os.fsync(fd)
            elif before is not None:
                # The durable intent predates the filesystem mutation. Reading
                # reconciles metadata only, never silently replays a move.
                record['phase']='not_applied';_replace_at(fd,filename,(encoded(record)+'\n').encode())
                _rename(fd,filename,session['recovery'],filename)
            else:raise Problem('文件操作的两个路径均缺失；历史快照保留','notes_integrity',409)


def dispatch(service,command):
    require(set(command)=={'action','project_id','request_id','payload'},'文件操作需要统一笔记命令形状')
    action=command['action'];p=command['payload'];require(isinstance(p,dict),'payload需要对象')
    require(isinstance(command['request_id'],str) and 0<len(command['request_id'])<=200,'文件操作需要稳定请求身份')
    with service._locked(command['project_id']) as session:
        project=session['project_id']
        if action=='notes.trash.list':
            require(not p,'回收列表不接路径')
            with service.store.connect() as c:items=[json.loads(r[0]) for r in c.execute('SELECT value FROM kv WHERE key LIKE ?',('notebook:trash:'+project+':%',))]
            return {'items':[{'trash_id':r['trash_id'],'note_id':r['entry']['note_id'],'relative_path':r['old_path'],'content_sha256':r['content_sha256'],'deleted_at':r['at']} for r in items if r['deleted']]}
        if action=='notes.resolve':
            require(set(p)=={'note_id'},'解析需要稳定笔记身份')
            with service.store.connect() as c:entries=[json.loads(r[0]) for r in c.execute('SELECT value FROM kv WHERE key LIKE ?',(service._key('revision',project)+':%',))]
            matches=[e for e in entries if e.get('note_id')==p['note_id'] and service._read_file(session,e['relative_path'],absent=True) is not None]
            require(len(matches)==1,'当前路径不可唯一解析；历史身份保留，不猜测外部移动','notes_identity_unbound',409)
            return {'note_id':p['note_id'],'relative_path':matches[0]['relative_path']}
        allowed={'relative_path','new_path','expected_content_sha256','links_reviewed'} if action in {'notes.move.inspect','notes.move'} else {'relative_path','expected_content_sha256'} if action=='notes.trash' else {'trash_id','new_path'}
        require(set(p)<=allowed and action in ACTIONS,'文件操作字段不支持')
        key='notebook:fileop_request:'+project+':'+digest(command['request_id'].encode());fingerprint=digest(command)
        previous=service.store.setting(key)
        if previous:require(previous['input']==fingerprint,'同一文件操作请求不同','idempotency_conflict',409);return previous['result']
        if action=='notes.restore':
            trash_id=p.get('trash_id');require(isinstance(trash_id,str) and re.fullmatch('[a-f0-9]{32}',trash_id),'回收身份无效')
            old_record=service.store.setting('notebook:trash:'+project+':'+trash_id);require(old_record and old_record['deleted'],'回收文件不存在','not_found',404)
            old=old_record['old_path'];new=p.get('new_path') or old;_components(new)
            entry=old_record['entry'];raw=_read_at(session['trash'],trash_id+'.md');require(digest(raw)==old_record['content_sha256'],'回收字节已改变，未覆盖当前文件','notes_integrity',409)
            source_tree=session['trash'];source_parts=[trash_id+'.md'];op='restore';links=None
        else:
            old=p.get('relative_path');_components(old);raw=service._read_file(session,old)
            require(digest(raw)==p.get('expected_content_sha256'),'文件已外部改变，未移动或删除','notes_conflict',409)
            service._document(session,old,raw);entry=service.store.setting(_revision(service,project,old));op='move' if action.startswith('notes.move') else 'trash'
            new=p.get('new_path') if op=='move' else None
            if op=='move':
                _components(new);require(new!=old,'目标与来源相同');links=inspect(service,session,old,new)
                if action=='notes.move.inspect':return {'note_id':entry['note_id'],'content_sha256':digest(raw),'links':links,'executed':False}
                require(not (links['incoming'] or links['outgoing']) or p.get('links_reviewed') is True,'受影响相对链接已列出，请明确检查后移动；正文不自动重写','notes_links_review_required',409,links)
            else:links=None
            source_tree=session['notes'];source_parts=_components(old)[1:];trash_id=uuid.uuid4().hex
        target_tree=session['trash'] if op=='trash' else session['notes'];target_parts=[trash_id+'.md'] if op=='trash' else _components(new)[1:]
        draft=service.store.setting('desk_w1a:drafts:'+project,{}).get('value',{}).get('buffers',{})
        affected=[new] if op=='restore' else [old,new]
        require(not any(draft.get(path,{}).get('dirty') for path in affected if path),'相关笔记有未保存手改，请先保存或保留双方草稿；文件未移动或回收','notes_draft_conflict',409)
        from research_partner.packaging.compatibility import require_features
        with service.store.transaction() as c:require_features(c,['native_note_file_operations_v1'])
        with _parent(source_tree,source_parts) as (src,name),_parent(target_tree,target_parts,create=True) as (dst,target):
            require(_read_at(src,name)==raw,'源文件在操作准备期间已改变','notes_conflict',409)
            info=os.stat(name,dir_fd=src,follow_symlinks=False);filename=uuid.uuid4().hex+'.json'
            record={'project_id':project,'op':op,'old_path':old,'new_path':new,'trash_id':trash_id if op in {'trash','restore'} else None,'entry':entry,'source_inode':[info.st_dev,info.st_ino],'content_sha256':digest(raw),'request_id':command['request_id'],'receipt_key':key,'input':fingerprint,'at':now(),'links':links,'phase':'prepared'}
            _replace_at(session['file_ops'],filename,(encoded(record)+'\n').encode())
            try:_rename(src,name,dst,target)
            except Exception:
                os.unlink(filename,dir_fd=session['file_ops']);os.fsync(session['file_ops']);raise
            actual=_read_at(dst,target);result=_finalize(service,session,record,actual)
            os.unlink(filename,dir_fd=session['file_ops']);os.fsync(session['file_ops']);return result
