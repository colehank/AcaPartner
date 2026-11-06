"""One application service for GUI, CLI and bounded agents."""
from __future__ import annotations
import base64
import copy
import hashlib
import json
import mimetypes
import math
import contextlib
import os
import re
import shutil
import sqlite3
import stat
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from .store import Store, Problem, require, now, uid, digest, encoded
from .source_identity import IDENTITY_SCOPE, source_files
from .action_contract import validate_action_request


ROOT = Path(__file__).resolve().parent.parent
KINDS = {"report", "note", "paper", "figure", "diagram", "poster", "slides", "workshop", "workshop_note", "concept", "question", "literature", "commission", "growth", "dataset", "recipe"}


def implementation():
    files = source_files(ROOT)
    return {"digest": digest(files), "files": files, "version": "0.1.0.dev0",
            "identity_scope": IDENTITY_SCOPE}


def default_content(kind):
    if kind in {"report", "note", "paper", "commission"}:
        return {"blocks": [{"id": uid("BLOCK"), "kind": "paragraph", "text": ""}], "citations": []}
    if kind == "diagram": return {"nodes": [], "edges": []}
    if kind in {"poster", "slides"}:
        return {"units": "cm", "pages": [{"id": uid("PAGE"), "width": 80 if kind == "poster" else 33.867, "height": 120 if kind == "poster" else 19.05, "objects": [], "notes": ""}]}
    if kind == "figure": return {"input_assets": {}, "overlays": [], "spec": {"kind": "line", "x": [], "series": []}}
    return {}


class App:
    def __init__(self, workspace, config=None):
        self.store = Store(workspace)
        self.config = config or {}
        from .notebook import NotebookService
        self.notebook = NotebookService(self.store)
        self.runner = None
        self.loaded_implementation = implementation()
        from .state_verification import Observation
        self._source_observation = Observation(self._verify_source)
        self._capability_observation = Observation(self.capabilities)
        self._development_observation = Observation(self._verify_development)
        self._development_source_observation = Observation(self._verify_development_source)

    def access(self, obj, scope=None, *, _receipt_seen=None):
        if scope is not None:
            project = obj["id"] if obj["kind"] == "project" else obj.get("project_id")
            require(project in scope or bool(set(obj["metadata"].get("shared_with", [])) & set(scope)), "此客户端没有该项目权限", "forbidden", 403)
        if obj['kind'] == 'feedback':
            from .feedback_external import require_read_access
            require_read_access(self, obj, scope, seen=_receipt_seen)
        return obj

    def get(self, ident, scope=None, revision=None):
        current = self.access(self.store.get(ident), scope)
        if revision is None:
            from .figure_definition import FigureDefinitions, is_definition
            if is_definition(current): current = FigureDefinitions(self.store).sync(ident)
        return self.store.get(ident, revision) if revision is not None else current

    def writable(self, ident, scope=None):
        obj = self.get(ident, scope)
        project = obj['id'] if obj['kind'] == 'project' else obj['project_id']
        require(scope is None or project in scope, '共享材料为只读；请在本项目创建衍生成果', 'forbidden', 403)
        return obj

    def asset(self, sha, scope=None, project_id=None):
        asset = self.store.asset(sha)
        projects = set(asset['metadata'].get('projects', [])) | {asset['metadata'].get('project_id')}
        allowed = scope is None if project_id is None else project_id in projects
        if scope is not None: allowed = bool(projects & set(scope)) and allowed if project_id else bool(projects & set(scope))
        if not allowed and scope is not None and project_id is None:
            from .artifacts import ArtifactEngine
            from .document_sources import asset_declarations
            for obj in self.store.objects():
                if obj.get('project_id') not in projects or not set(obj['metadata'].get('shared_with',[])) & set(scope):continue
                try:declared=self.render_view(self.access(obj, scope), scope)
                except Problem:continue
                refs=asset_declarations(obj['content'],strict=False)
                refs.update(ref for _,ref in ArtifactEngine._asset_refs({'metadata':declared['metadata']},strict=False))
                if sha in refs:
                    allowed=True;break
        require(allowed, '没有此资产权限', 'forbidden', 403)
        return asset

    def artifact(self, ident, scope=None, revision=None, consumer=None):
        obj = self.get(ident, scope, revision)
        if consumer:
            owner = self.get(consumer, scope)
            project = owner['id'] if owner['kind'] == 'project' else owner['project_id']
            with self.store.connect() as connection:
                self.store.assert_source_access(connection, project, ident)
        from .paper_sources import source_state
        paper_state = source_state(obj) if obj["kind"] == "paper" else None
        if paper_state and obj["revision"] > 1:
            previous = self.store.get(ident, obj["revision"] - 1)
            if previous.get("project_id") == obj.get("project_id"):
                old_state = source_state(previous)
                paper_state["previous_revision"] = {"revision": previous["revision"], "mode": old_state["mode"], "structured_sha256": old_state["structured_sha256"], "latex_sha256": old_state["latex_sha256"], "changed": [key for key in ("mode", "structured_sha256", "latex_sha256") if old_state[key] != paper_state[key]]}
        return {**self.render_view(obj, scope), **({"paper_source_state": paper_state} if paper_state else {}), "canonical_source_sha256": digest(obj), "revisions": self.store.revisions(ident), "annotations": self.store.annotations(ident), "dependencies": [r for r in self.store.relations(ident) if self._relation_allowed(r, scope)]}

    def render_view(self,obj,scope):
        if obj['kind']=='workshop':
            obj={**obj,'workshop_readiness':self.store.workshop_readiness(obj,self.store.get(obj['id']))}
        if obj['kind']=='growth':
            from .growth import view
            obj=view(self.store,obj)
        if obj['kind']=='feedback':obj=self.feedback_view(obj,scope)
        if obj['kind']=='question':obj=self.store.question_view(obj)
        records=self.store.export_records(obj['id'],obj['revision'])
        from .feedback_external import visible_review_records
        reviews=visible_review_records(self, self.store.review_records(obj['id'],obj['revision']), scope)
        if not records and obj['kind']=='figure':
            # Keep registered old pixels readable after source-only saves, never as a current render.
            for record in reversed(self.store.export_records(obj['id'])):
                result=record['result'];proof=result.get('provenance',{});image=result.get('assets',{}).get('figure.png')
                if record['revision']>=obj['revision'] or result.get('status')!='generated' or 'preview_identity' in result or result.get('replay',{}).get('failures') or not image:continue
                try:
                    prior=self.get(obj['id'],scope,record['revision'])
                    if proof.get('object_id')!=obj['id'] or proof.get('revision')!=prior['revision'] or proof.get('source_sha256')!=digest(prior):continue
                    asset=self.asset(image.get('sha') if isinstance(image,dict) else image,scope,obj['project_id'])
                    if asset['media_type']!='image/png':continue
                    with (self.store.blobs/asset['sha']).open('rb') as stream:
                        if stream.read(8)!=b'\x89PNG\r\n\x1a\n':continue
                except (Problem,OSError):continue
                return {**obj,'metadata':{**obj['metadata'],'last_export':result,'exported_revision':prior['revision'],'render_stale':True},'exports':[],'previous_render_record':record,'review_records':reviews,'canonical_source_sha256':digest(obj)}
        if not records:return {**obj,'review_records':reviews} if reviews else obj
        combined={};manifest=[];replay={}
        for record in records:
            result=record['result'];combined.update(result.get('assets',{}))
            if result.get('manifest'):manifest=result['manifest']
            if result.get('replay'):replay=result['replay']
        latest={**records[-1]['result'],'assets':combined,'manifest':manifest,'replay':replay}
        return {**obj,'metadata':{**obj['metadata'],'last_export':latest,'exported_revision':obj['revision']},'exports':records,'review_records':reviews,'canonical_source_sha256':digest(obj)}

    def _relation_allowed(self, relation, scope):
        try:
            self.get(relation["src"], scope)
            self.get(relation["dst"], scope)
            return True
        except Problem: return False

    def _verify_source(self):
        current = implementation()
        return {"implementation": current,
                "disk_implementation_changed": current["digest"] != self.loaded_implementation["digest"]}

    def _verify_development(self):
        from .devcontrol import DevelopmentControl
        return DevelopmentControl(Path(self.config.get('development_root', ROOT))).status()

    def _verify_development_source(self):
        from .devcontrol import DevelopmentControl
        return DevelopmentControl(Path(self.config.get('development_root', ROOT))).source_identity()

    def verify_state(self, scope=None):
        require(scope is None, "完整实现与开发门槛校验仅限所有者", "forbidden", 403)
        # This is a fresh observational check, never a mutation authorization.
        result = {"source": self._source_observation.verify_now(),
                  "capabilities": self._capability_observation.verify_now()}
        try:
            result["development"] = self._development_observation.verify_now()
        except Exception as error:
            result["development"] = {"status": "unavailable", "message": type(error).__name__, "verified_at": None}
        try:
            # Compare dated source observations of the same development root;
            # runtime source identity has a different scope and is not a proxy.
            result["development_source"] = self._development_source_observation.verify_now()
        except Exception as error:
            result["development_source"] = {"status": "unavailable", "message": type(error).__name__, "verified_at": None}
        return result

    def state(self, scope=None):
        # All Store projections, settings and access checks share one pinned,
        # query-only SQL transaction. No prefilled object cache is substituted.
        with self.store.read_snapshot():
            result = self._state_snapshot(scope)
        # Expensive filesystem/probe work is outside the request's SQL lifetime.
        source = self._source_observation.snapshot()
        capabilities = self._capability_observation.snapshot()
        result.update(implementation=self.loaded_implementation,
                      disk_implementation_changed=None, source_verification=source,
                      capabilities={**(capabilities['last_verification']['result'] if capabilities['last_verification'] else
                                       {"formats": {"status": "verification_pending"}, "agent": {"real_model_required": True, "template_fallback": False}, "client_verified": False}),
                                    "verification": capabilities})
        if scope is None:
            try:
                from .devcontrol import DevelopmentControl
                development = DevelopmentControl(Path(self.config.get('development_root', ROOT))).status(verify=False)
                development['verification'] = self._development_observation.snapshot()
                development['source_verification'] = self._development_source_observation.snapshot()
                development['can_verify'] = True
                result['development'] = development
            except Exception as error:
                result['development'] = {"status": "unavailable", "message": type(error).__name__, "can_verify": True}
        else:
            result['development'] = {"status": "owner_only"}
        return result

    def _state_snapshot(self, scope=None):
        from .conventions import visible
        objects = []
        for obj in self.store.objects():
            try: objects.append(self.render_view(self.access(obj, scope), scope))
            except Problem: pass
        ids = {o["id"] for o in objects}
        tasks = []
        with self.store.connect() as connection:
            for task in self.store.tasks():
                if task['payload'].get('kind')=='manuscript_revision':
                    from .manuscript_revision import task_access
                    try:task_access(self,task,scope,connection)
                    except Problem:continue
                    tasks.append(task)
                elif task['payload'].get('kind')=='project_management':
                    from .project_management import task_access
                    try:task_access(self,task,scope,connection)
                    except Problem:continue
                    tasks.append(task)
                elif scope is None or task.get('project_id') in scope:tasks.append(task)
        for t in tasks:
            # Provider config/credential references are deliberately absent from task responses.
            t["payload"] = {k: v for k, v in t["payload"].items() if k not in {"environment", "credentials", "config"}}
        return {"project_management": {"can_create":scope is None,"writable_project_ids":[o['id'] for o in objects if o['kind']=='project' and (scope is None or o['id'] in scope)]}, "projects": [o for o in objects if o["kind"] == "project"], "objects": [o for o in objects if o["kind"] != "project"], "relations": [r for r in self.store.relations() if r["src"] in ids and r["dst"] in ids], "tasks": tasks, "questions": [o for o in objects if o["kind"] == "question"], "feedback": [o for o in objects if o["kind"] == "feedback"], "growth": [o for o in objects if o["kind"] == "growth"], "providers": self.providers(), "extensions": self.store.setting("extensions", []), "workspace_id": self.store.setting("workspace_id"), "runtime": self.runner.status() if self.runner else {"running": False}, "preferences": visible(self.store.setting("preferences", {}), scope), "domain": visible(self.store.setting("domain", {}), scope)}

    def figure_provider_capability(self, pid, config, available):
        """Configured tool-route capability, never a connection or fee proof."""
        if not available or config.get('authorized') is not True:return False,None
        if config.get('route')=='codex':return True,{'max_model_calls':1,'timeout_seconds':180}
        if config.get('route')!='deepseek_harness' or config.get('transport')!='deepseek_harness_native':return False,None
        from .deepseek_figure_configuration import definition
        from .development_budget import Budget
        import time
        try:
            fingerprint=digest(config)
            cache=getattr(self,'_figure_provider_definitions',{})
            saved=cache.get(pid)
            if not saved or saved['config_sha256']!=fingerprint:
                saved={'config_sha256':fingerprint,'definition':definition(config)}
                cache[pid]=saved;self._figure_provider_definitions=cache
            frozen=saved['definition'];parent=Budget(self.config['development_budget']).check()
            if Budget.native_permission(parent,frozen) is None:return False,None
            remaining_calls=Budget.remaining(parent,'model_calls')
            remaining_seconds=Budget.remaining(parent,'model_seconds')
            if (time.time()>=frozen['deadline'] or remaining_calls<frozen['max_requests']
                    or remaining_seconds<frozen['timeout_seconds']
                    or Budget.deadline(parent)-time.time()<frozen['timeout_seconds']):return False,None
            return True,{'max_model_calls':frozen['max_requests'],'timeout_seconds':frozen['timeout_seconds']}
        except (Problem,OSError,ValueError,KeyError,TypeError,AttributeError):return False,None

    def providers(self):
        result = []
        for pid, p in self.config.get("providers", {}).items():
            p=p if isinstance(p,dict) else {}
            route = p.get("route")
            executable = p.get("executable")
            key = p.get("credential_file")
            available=False
            try:
                if route=='codex':available=isinstance(executable,str) and bool(shutil.which(executable))
                elif isinstance(p.get('runtime'),str) and isinstance(key,str) and key:
                    entry=Path(key).lstat()
                    available=(Path(p['runtime']).is_dir() and Path(key).is_absolute()
                               and stat.S_ISREG(entry.st_mode) and stat.S_IMODE(entry.st_mode)==0o600
                               and entry.st_uid==os.getuid() and 0<entry.st_size<=4096)
            except (OSError,ValueError,TypeError):pass
            note = "配置可探测；实际调用状态见任务记录" if available else "缺少可用执行入口或凭据"
            if p.get("transport") == "app_server_dynamic":
                from .provider_availability import codex_dynamic_availability
                availability = codex_dynamic_availability()
                available = availability["available"]
                note = availability["reason"]
            composition,composition_budget=self.figure_provider_capability(pid,p,available)
            result.append({"supports_figure_composition":composition,"figure_composition_budget":composition_budget,"id": pid, "route": route, "model": p.get("model"), "available": available, "connected": False, "note": note, "authorized": bool(p.get("authorized")), "supports_resume": route in {"codex", "deepseek_harness"} and p.get("transport") not in {"deepseek_harness_native", "app_server_dynamic"}})
        return result

    def capabilities(self):
        try:
            from .artifacts import ArtifactEngine
            formats = ArtifactEngine(self.store, self.config.get("rendering", {})).capabilities()
        except ImportError: formats = {"status": "implementation_in_progress"}
        return {"formats": formats, "agent": {"real_model_required": True, "template_fallback": False}, "client_verified": False}

    def dispatch(self, data, scope=None, *, principal=None):
        with self.store.capture_file_results() as files:
            result = self._dispatch(data, scope, principal=principal)
        repairs = {
            key: value for key, value in files.items()
            if value.get("status") == "repair_required"
        }
        if repairs and isinstance(result, dict):
            result = {**result, "project_files": repairs}
        return result

    def _dispatch(self, data, scope=None, *, principal=None):
        data = validate_action_request(data)
        action = data["action"]
        if isinstance(action, str) and action.startswith('claim.'):
            from .claims import dispatch
            return dispatch(self, data, scope, principal)
        if isinstance(action,str) and action.startswith(('dataset.','recipe.','build.')):
            from .generation import dispatch
            return dispatch(self,data,scope,principal)
        if isinstance(action, str) and action.startswith(('desk.', 'notes.')):
            from .desk_w1a import dispatch
            return dispatch(self, data, scope, principal)
        if action == "system.verify":
            return self.verify_state(scope)
        s = self.store
        if action in {'figure.visual.commit', 'figure.visual.receipt'}:
            from .figure_commit41 import dispatch
            return dispatch(self, data, scope, principal)
        if action == 'figure.preview':
            from .figure_preview40 import dispatch
            return dispatch(self, data, scope, principal)
        if action in {'manuscript.format.render', 'manuscript.format.source'}:
            from .manuscript_layout40 import dispatch
            return dispatch(self, data, scope, principal)
        if isinstance(action, str) and action.startswith(('manuscript.format.', 'manuscript.edit.')):
            from .manuscript_format40 import dispatch
            return dispatch(self, data, scope, principal)
        if action=='manuscript.render':
            from .manuscript_render import dispatch
            return dispatch(self,data,scope)
        if action=='trace.inspect':
            from .scientific_trace import inspect
            return inspect(self,data,scope)
        if isinstance(action,str) and action.startswith('article.'):
            from .article_workspace import dispatch
            return dispatch(self,data,scope,principal)
        if isinstance(action,str) and action.startswith('workbench.'):
            from .workbench import dispatch
            return dispatch(self,data,scope,principal)
        if action in {'manuscript.revision.recover_preview','manuscript.revision.recover'}:
            from .manuscript_recovery39 import dispatch
            return dispatch(self,data,scope,principal)
        if action in {'task.recover_cli_checkpoint_preview', 'task.recover_cli_checkpoint'}:
            from .codex_checkpoint_registration import dispatch
            return dispatch(self, data, scope, principal)
        if isinstance(action,str) and action.startswith('manuscript.revision.'):
            from .manuscript_revision import dispatch
            return dispatch(self,data,scope,principal)
        if isinstance(action,str) and action.startswith('project.management.'):
            from .project_management import dispatch
            return dispatch(self,data,scope,principal)
        if scope is not None and action not in {'project.create'} and not (isinstance(action,str) and action.startswith('graph.')):
            # Shared components grant evidence reading, never mutation rights.
            if data.get('project_id'):self.writable(data['project_id'],scope)
            if data.get('object_id'):self.writable(data['object_id'],scope)
            if data.get('src'):self.writable(data['src'],scope)
            if data.get('source_id'):self.writable(data['source_id'],scope)
            if data.get('target_id'):self.writable(data['target_id'],scope)
            if data.get('id') and action not in {'cycle.revise_failed_child_preview','cycle.revise_failed_child','task.control','task.guide','task.revise_candidate','task.extend_budget','task.recover_candidate','task.recover_candidate_preview','task.recover_stopped_candidate','task.recover_stopped_candidate_preview','cycle.view','cycle.control','cycle.stage_revision_preview','cycle.stage_revision','cycle.stage_final_revision_preview','cycle.stage_final_revision','annotation.update','dependency.accept','dependency.retain','question.candidate_preview'} and not action.startswith(('extension.','graph.')):
                self.writable(data['id'],scope)
        if action in {'cycle.revise_failed_child_preview', 'cycle.revise_failed_child'}:
            from .cycle_child_revision import dispatch
            return dispatch(self, data, scope)
        if action in {'cycle.stage_final_revision_preview','cycle.stage_final_revision'}:
            from .cycle_final_handoff import dispatch
            return dispatch(self,data,scope)
        if action in {'cycle.stage_revision_preview','cycle.stage_revision'}:
            from .cycle_handoff import dispatch
            return dispatch(self,data,scope)
        if action in {'task.recover_candidate','task.recover_candidate_preview'}:
            from .native_recovery import dispatch
            return dispatch(self,data,scope)
        if action == "project.create":
            require(scope is None, "受限客户端不能创建项目", "forbidden", 403)
            from .article_workspace import initialize_output
            with s.transaction() as connection:
                project=s.create("project", data["title"], content=data.get("content", {}), metadata=data.get("metadata", {}),connection=connection)
                result=initialize_output(s,connection,project)
            return {**result['project'],'primary_manuscript_id':result['manuscript']['id']}
        if action in {'cycle.submit', 'cycle.view', 'cycle.control'}:
            from . import cycle
            if action == 'cycle.submit': return cycle.create(self, data, scope)
            if action == 'cycle.view': return cycle.view(self, data['id'], scope)
            return cycle.control(self, data['id'], data['operation'], scope)
        if action == 'project.feature':
            project=self.writable(data['project_id'],scope)
            require(project['kind']=='project','需要所属项目')
            obj=self.get(data['object_id'],scope)
            require(obj['project_id']==project['id'] and obj['kind'] in {'report','note','paper','figure','diagram','poster','slides','workshop','commission'} and not obj['archived'],'请选择本项目未归档成果')
            require(type(data.get('featured')) is bool,'需要明确置顶或取消置顶')
            ids=list(dict.fromkeys(project['metadata'].get('featured_objects',[])))
            if data['featured'] and obj['id'] not in ids:ids.append(obj['id'])
            if not data['featured']:ids=[x for x in ids if x!=obj['id']]
            require(len(ids)<=12,'重点成果最多12项；其他成果仍可在工作台打开')
            return s.save(project['id'],data['expected_revision'],metadata={**project['metadata'],'featured_objects':ids},reason='explicit project highlight selection',merge=False)
        if action=='workshop.accept':
            obj=self.writable(data['id'],scope)
            require(obj['kind']=='workshop','需要工坊产物')
            records=obj['content'].get('acceptance',[])
            records=records if isinstance(records,list) else [records]
            content={**obj['content'],'acceptance':[*records,{k:data.get(k,'') for k in ('status','evidence','limitations')}]}
            return s.save(obj['id'],data['expected_revision'],content=content,reason='explicit technical acceptance; no scientific approval',merge=False)
        if action in {"project.update", "project.archive", "project.restore", "object.save", "object.rename", "object.archive"}:
            obj = self.writable(data["id"], scope)
            from .figure_definition import is_definition
            require(not is_definition(obj) or action == 'object.archive', '文件优先的主图必须通过组成文件服务修改', 'file_authority', 409)
            require(not isinstance(data.get('content'), dict) or not data['content'].get('definition_schema'), '主图文件身份只能由定义服务登记', 'file_authority', 409)
            archived = action.endswith("archive") if action in {"project.archive", "project.restore", "object.archive"} else data.get("archived")
            result=s.save(obj["id"], data["expected_revision"], content=data.get("content"), title=data.get("title"), metadata=data.get("metadata"), archived=archived)
            if self.runner:self.runner.stop_revoked()
            return result
        if action == "object.create":
            kind = data["kind"]
            require(kind in KINDS, "不支持的成果类型")
            require(not isinstance(data.get('content'), dict) or not data['content'].get('definition_schema'), '主图定义须经文件服务创建', 'file_authority', 409)
            self.writable(data["project_id"], scope)
            obj = s.create(kind, data["title"], data["project_id"], data.get("content", default_content(kind)), data.get("metadata", {}))
            s.relate(data["project_id"], obj["id"], "contains", "confirmed")
            return obj
        if action == "object.restore":
            obj = self.writable(data["id"], scope)
            from .figure_definition import is_definition
            require(not is_definition(obj), '主图历史仍保留；恢复须通过定义文件的明确新修订', 'file_authority', 409)
            result=s.restore(data["id"], data["revision"], data["expected_revision"])
            if self.runner:self.runner.stop_revoked()
            return result
        if action == "annotation.add":
            self.writable(data["object_id"], scope)
            return s.annotate(data["object_id"], data["revision"], data.get("anchor", {}), data["text"])
        if action == 'review.record':
            target=self.writable(data['object_id'],scope)
            reviewed=s.get(target['id'],data['revision'])
            report=self.get(data['review_object_id'],scope,data['review_revision'])
            require(report['kind'] in {'report','note'},'审阅依据需要可读报告或笔记')
            require(report['project_id']==target['project_id'] or target['project_id'] in report['metadata'].get('shared_with',[]),'审阅依据尚未授权给目标项目','forbidden',403)
            require(data.get('verdict') in {'needs_revision','usable_for_discussion','reviewed_with_limits'},'审阅判断不支持；此操作不授予科学批准或用户验收')
            require(data.get('scope','').strip() and data.get('summary','').strip() and data.get('reviewer_reference','').strip(),'需要审阅范围、具体判断与审阅者来源')
            return s.record_review(target['id'],reviewed['revision'],{**{k:data[k] for k in ('review_object_id','review_revision','verdict','scope','summary','reviewer_reference')},'review_source_sha256':digest(report)})
        if action == "annotation.update":
            self.writable(data["object_id"], scope)
            with s.transaction() as c:
                row = c.execute("SELECT * FROM annotations WHERE id=? AND object_id=?", (data["id"], data["object_id"])).fetchone()
                require(row, "批注不存在", "not_found", 404)
                status = data.get("status", row["status"])
                require(status in {"anchored", "orphaned", "text_changed", "resolved"}, "批注状态不支持")
                c.execute("UPDATE annotations SET text=?,status=? WHERE id=?", (data.get("text", row["text"]), status, data["id"]))
                s.event(c, "annotation.updated", data["object_id"], {"id": data["id"], "previous_text": row["text"]})
            return s.annotations(data["object_id"])
        if isinstance(action,str) and action.startswith("graph."):
            return self.graph(data, scope)
        if action in {"dependency.accept", "dependency.retain"}:
            rel = next((r for r in s.relations() if r["id"] == data["id"]), None)
            require(rel, "引用不存在", "not_found", 404)
            self.writable(rel["src"], scope); self.get(rel["dst"], scope)
            updated=s.accept_dependency(data["id"], data["target_revision"], action.endswith("accept"), expected_relation_revision=data.get("relation_revision"), expected_source_revision=data.get("expected_revision"))
            return [relation for relation in updated if self._relation_allowed(relation,scope)]
        if action == "asset.inspect":
            project=self.writable(data.get('project_id'),scope)
            require(project['kind']=='project','请选择资产所属项目')
            asset=self.asset(data.get('sha'),scope,project['id'])
            with (s.blobs/asset['sha']).open('rb') as source:header=source.read(24)
            detected='png' if header.startswith(b'\x89PNG\r\n\x1a\n') else 'jpeg' if header.startswith(b'\xff\xd8\xff') else None
            supported=bool(detected and asset['media_type']=={'png':'image/png','jpeg':'image/jpeg'}[detected])
            return {k:asset[k] for k in ['sha','url','filename','media_type']} | {'byte_size':asset['size'],'project_id':project['id'],
                'supported_image':supported,'detected_format':detected,'validation':'Stored SHA and PNG/JPEG signature plus registered MIME checked; full image decoding is not implied.'}
        if action == "asset.import": return self.import_asset(data, scope)
        if action == "object.import":
            self.writable(data["project_id"], scope)
            self.asset(data['asset_sha'], scope, data['project_id'])
            from .artifacts import ArtifactEngine
            return ArtifactEngine(s, self.config.get("rendering", {})).import_document(data["asset_sha"], kind=data.get("kind", "report"), title=data.get("title"), project_id=data["project_id"])
        if action == "object.authorize_code":
            require(scope is None, "仅所有者可授权运行导入脚本", "forbidden", 403)
            obj = self.get(data["id"])
            require(data.get("approved") is True and data.get("reason"), "需要明确授权及其范围")
            require(obj["revision"] == data["expected_revision"], "脚本对象已更新，需重新审查", "conflict",409)
            script = obj["content"].get("script_asset")
            require(script, "此对象没有待执行脚本")
            s.asset(script)
            s.set_setting("code_grant:"+obj["id"], {"script_sha":script,"reason":data["reason"],"at":now()})
            return {"authorized_script_sha":script}
        if action in {"object.export", "figure.render"}:
            obj = self.writable(data["id"], scope)
            from .figure_definition import is_definition
            require(action != 'figure.render' or not is_definition(obj), '主图使用组成渲染，不通过单脚本图的修改入口', 'file_authority', 409)
            from .artifacts import ArtifactEngine
            engine = ArtifactEngine(s, self.config.get("rendering", {}))
            require(obj["revision"] == data.get("expected_revision", obj["revision"]), "成果已更新", "conflict", 409)
            grant = s.setting("code_grant:"+obj["id"], {})
            allowed_code = bool(grant and grant.get("script_sha") == obj["content"].get("script_asset"))
            if action == "figure.render":
                content=copy.deepcopy(obj['content'])
                if data.get("overlays") is not None:content["overlays"] = data["overlays"]
                if data.get("input_assets") is not None:content["input_assets"] = data["input_assets"]
                if content!=obj['content']:obj=s.save(obj['id'],obj['revision'],content=content,reason='explicit figure source update',merge=False)
                result = engine.render_figure(obj, authorized_code=allowed_code)
            else:
                obj=self.get(obj['id'],scope,data.get('revision',obj['revision']))
                result = engine.export(obj, data["format"], authorized_code=allowed_code)
            s.record_export(obj['id'],obj['revision'],result)
            return {**result, "object": self.render_view(obj, scope)}
        if action == "feedback.record_external_action":
            from .feedback_external import record
            return record(self, data, scope, principal)
        if action.startswith("feedback."): return self.feedback(data, scope)
        if action == 'task.resolve':
            from .resolver import resolve
            return resolve(self,data,scope)
        if action in {"task.submit", "workshop.submit", "commission.submit"}: return self.submit(data, scope)
        if action in {'task.recover_stopped_candidate_preview', 'task.recover_stopped_candidate'}:
            from .stopped_candidate import dispatch
            return dispatch(self, data, scope, principal)
        if action in {"task.control","task.guide","task.extend_budget","task.revise_candidate"}:
            task = s.task(data["id"])
            if task['payload'].get('kind')=='manuscript_revision':
                from .manuscript_revision import task_access
                with s.connect() as connection:task_access(self,task,scope,connection)
            elif task['payload'].get('kind')=='project_management':
                from .project_management import task_access
                with s.connect() as connection:task_access(self,task,scope,connection)
            else:self.writable(task["project_id"], scope)
            if action=='task.revise_candidate':
                require(data.get('approved') is True,'需要明确选择按当前回答修订候选；此操作可能消耗既定剩余额度','authorization_required',403)
                require(task['payload']['kind']!='workshop','工具任务不使用模型候选修订')
                with s.transaction() as c:
                    current=s.unpack(c.execute('SELECT * FROM tasks WHERE id=?',(task['id'],)).fetchone())
                    if current['payload'].get('kind')=='manuscript_revision':
                        from .manuscript_revision import may_revise
                        may_revise(self,current,c)
                    require(current['status'] in {'waiting_input','paused','failed'},'请先停止执行并检查已保存候选','conflict',409)
                    require(current['attempts']<3,'有限尝试次数已耗尽；未扩额度或新建会话','budget_exhausted',409)
                    committed=c.execute('SELECT value FROM kv WHERE key=?',('commit:'+task['id'],)).fetchone()
                    produced=c.execute('SELECT id FROM objects WHERE id=?',('ART-'+task['id'].removeprefix('TASK-'),)).fetchone()
                    require(not current['result'].get('object_id') and not committed and not produced,
                            '此任务已有保存成果；请在成果旁发起修订以保留用户编辑和版本，未消耗模型额度','conflict',409)
                    snapshot=s.execution_inputs(c,task['id'])
                    require(not s.question_blockers(c,task['id']),'必要问题或来源尚待明确重新评估；未授权新的模型调用','conflict',409)
                    require(data.get('input_snapshot')==snapshot,'回答或指导已变化，请重新读取后选择','conflict',409)
                    grant={'input_snapshot':snapshot,'state':'authorized','at':now(),'permissions_changed':False,'budget_extended':False}
                    c.execute('INSERT INTO kv VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('candidate_revision_authorized:'+task['id'],json.dumps(grant)))
                    lease_row=c.execute('SELECT value FROM kv WHERE key=?',('execution:'+task['id'],)).fetchone()
                    if lease_row:
                        lease=json.loads(lease_row[0]);lease.update(state='revoked',reason='explicit candidate revision',revoked_at=now())
                        c.execute('UPDATE kv SET value=? WHERE key=?',(json.dumps(lease),'execution:'+task['id']))
                    c.execute("UPDATE tasks SET status='queued',error=NULL,updated_at=? WHERE id=?",(now(),task['id']))
                    s.event(c,'task.candidate_revision_authorized',task['id'],grant,'user')
                if self.runner:self.runner.wake()
                return {'task':s.task(task['id']),'revision_authorized':True,'budget_extended':False,'permissions_changed':False}
            if action=='task.extend_budget':
                require(scope is None and data.get('approved') is True and data.get('reason'),'增加额度需要空间所有者明确确认范围与理由','authorization_required',403)
                require(task['status'] in {'failed','waiting_resource','waiting_authorization','paused'},'仅可在执行停止后调整额度','conflict',409)
                route=self.config.get('providers',{}).get(task['payload'].get('provider_id'),{}).get('route')
                require(route=='codex','原生Harness额度须核对其独立授权账本，不能从此入口绕过','authorization_required',403)
                calls=data.get('additional_invocations',0);seconds=data.get('additional_seconds',0)
                require(type(calls)==int and 0<=calls<=5 and isinstance(seconds,(int,float)) and 0<=seconds<=900 and calls+seconds>0,'需要有限新增额度')
                previous=s.setting('budget_extension:'+task['id'],{'invocations':0,'seconds':0})
                value={'invocations':previous['invocations']+calls,'seconds':previous['seconds']+seconds,'reason':data['reason'],'at':now()}
                s.set_setting('budget_extension:'+task['id'],value)
                with s.transaction() as c:s.event(c,'budget.explicit_extension',task['id'],{'previous':previous,'current':value},'owner')
                return {'task_id':task['id'],'extension':value,'consumption_preserved':True,'automatically_resumed':False}
            if action=='task.guide':
                require(data.get('text','').strip(),'指导不能为空')
                require(task['status'] not in {'cancelled','deliverable'},'已结束任务不能接收新指导','conflict',409)
                author=data.get('source','user')
                require(author in {'user','coordinator','independent_review'},'指导来源不支持')
                with s.transaction() as c:
                    s.event(c,'task.guidance',task['id'],{'text':data['text'],'source':author,'source_reference':data.get('source_reference'),'scope':'next execution handoff; cannot grant permissions'},author)
                return {'task_id':task['id'],'guidance_saved':True,'takes_effect':'next execution handoff'}
            require(self.runner, "执行服务没有启动", "runtime_unavailable", 503)
            if 'expected_status' in data:
                require(data['expected_status'] in ('queued','running') and data.get('operation')=='pause',
                        '暂停需要明确的执行中状态','conflict',409)
                return self.runner.control(task["id"], data["operation"], expected_status=data['expected_status'])
            return self.runner.control(task["id"], data["operation"])
        if action == "decision.answer": return self.answer(data, scope)
        if action in {'question.materialize','question.bind','question.candidate_preview','question.reassess'}:return self.question_action(data,scope)
        if action in {'literature.fulltext.fetch', 'literature.fulltext.status'}:
            from .literature_fulltext_service import dispatch
            return dispatch(self, data, scope, principal)
        if action.startswith("literature."):
            from .literature import Literature
            self.get(data["project_id"], scope)
            return Literature(s, self.config.get("network", {})).dispatch(data)
        if action.startswith("growth."): return self.growth(data, scope)
        if action.startswith("extension."):
            require(scope is None, "仅空间所有者可管理扩展", "forbidden", 403)
            from .extensions import Extensions
            return Extensions(self).dispatch(data)
        if action in {"settings.layer_preview", "settings.layer_update"}:
            from .conventions import layer_action
            return layer_action(s, data, scope)
        if action == "settings.update":
            require(scope is None, "仅空间所有者可管理设置", "forbidden", 403)
            require(data["key"] in {"domain", "preferences"}, "此配置需通过本机授权文件修改", "forbidden", 403)
            from .conventions import validate
            s.set_setting(data["key"], validate(data["value"]))
            return {"saved": True}
        if action == "workspace.backup":
            require(scope is None, "受限客户端不能导出整个空间", "forbidden", 403)
            return self.backup()
        raise Problem("未实现的操作：" + str(action), "not_implemented", 501)

    def graph(self, data, scope):
        if data["action"] == "graph.move":
            obj = self.writable(data["id"], scope)
            position = data.get("position", {"x": data.get("x", 0), "y": data.get("y", 0)})
            require(isinstance(position,dict) and set(position)=={'x','y'} and all(type(position[k]) in (int,float) and 0<=position[k]<=100000 for k in ('x','y')),'节点位置需要有限、非负的数值坐标')
            return self.store.save(obj["id"], data.get("expected_revision", obj["revision"]), metadata={**obj["metadata"], "position": position})
        from .graph_growth import dispatch
        return dispatch(self,data["action"],data,scope)

    def import_asset(self, data, scope):
        self.get(data["project_id"], scope)
        filename = data.get("filename", "asset")
        if "path" in data:
            require(scope is None, "受限客户端只能上传文件内容", "forbidden", 403)
            path = Path(data["path"]).expanduser().resolve()
            roots = [Path(p).resolve() for p in self.config.get("import_roots", [])]
            require(any(path.is_relative_to(p) for p in roots), "此读取路径不在授权导入范围", "forbidden", 403)
            require(not any(x.startswith(".") for x in path.parts[1:]) and not re.search(r"(api.?key|credential|auth\.json|id_rsa|id_ed25519|\.env)", path.name, re.I), "不导入凭据或隐藏配置", "forbidden", 403)
            require(path.is_file() and path.stat().st_size <= 128 * 1024 * 1024, "文件不存在或超出128MB单文件限制")
            content = path.read_bytes(); filename = path.name
        else:
            try: content = base64.b64decode(data["base64"], validate=True)
            except Exception: raise Problem("文件编码无效")
            require(len(content) <= 128 * 1024 * 1024, "单文件超出限制")
        provenance=data.get('provenance','unverified_import')
        require(provenance in {'unverified_import','public_real','authorized_real','synthetic'},'来源类别不支持')
        if provenance in {'public_real','authorized_real'}:
            require(scope is None and data.get('source') and data.get('authorization_reference'), '真实输入登记需所有者提供可核对来源与授权依据','authorization_required',403)
        return self.store.add_asset(content, filename, mimetypes.guess_type(filename)[0] or "application/octet-stream", {"project_id": data["project_id"], "source": data.get("source", "user import"), "immutable_input": True,'provenance':provenance,'synthetic':provenance=='synthetic','authorization_reference':data.get('authorization_reference'),'source_identity':data.get('source_identity')})

    def submit(self, data, scope=None, register_feedback_action=True, *, connection=None, request_prefix="", domain_context=None):
        s = self.store
        from .resolver import prepare_submission
        project, materials, material_resolution = prepare_submission(self,data,scope,connection)
        kind = data.get("kind", "workshop" if data["action"] == "workshop.submit" else "research")
        require(kind != 'figure_composition' or isinstance(domain_context, dict), '领域工具任务只能通过固定组成委托入口创建', 'forbidden', 403)
        require(kind not in {"literature_acquisition","growth_assessment","project_management","manuscript_revision"}, "此任务类型只能通过对应的有限委托入口创建", "forbidden", 403)
        request = data.get("request", data.get("prompt", ""))
        from .acquisition import plan as acquisition_plan
        literature_plan = acquisition_plan(data) if kind != "workshop" else None
        require(kind == "workshop" or isinstance(request, str) and request.strip(), "请描述研究目的或修订意见")
        def writable(ident):
            obj=self.access(s.get(ident,connection=connection),scope)
            require(scope is None or (obj['id'] if obj['kind']=='project' else obj['project_id']) in scope,'共享材料为只读','forbidden',403)
            return obj
        target = writable(data["object_id"]) if data.get("object_id") else None
        if target:
            require(target["project_id"] == project["id"], "任务和成果的项目不一致")
            require(data.get('expected_revision',target['revision'])==target['revision'],'成果已更新，请核对当前版本后提交修订','conflict',409)
        fb = None
        if data.get('feedback_id'):
            fb = writable(data['feedback_id'])
            require(fb['kind']=='feedback' and fb['project_id']==project['id'], '反馈不属于此任务项目', 'forbidden', 403)
            require(fb['content'].get('lifecycle')!='withdrawn','反馈已撤回','cancelled',409)
            require(self.feedback_disposition(fb)!='defer','反馈已暂缓，请先明确重新安排','feedback_deferred',409)
            require(data.get('expected_feedback_revision',fb['revision'])==fb['revision'],'反馈已变化，请重新读取','conflict',409)
        for dep_id in data.get('depends_on', []):
            dep = s.task(dep_id,connection)
            require(dep['project_id']==project['id'], '任务依赖不属于此项目', 'forbidden',403)
        budget = data.get('budget', {'max_model_calls':4,'timeout_seconds':300})
        require(isinstance(budget,dict) and type(budget.get('max_model_calls')) is int and 0 <= budget['max_model_calls'] <= 100 and type(budget.get('timeout_seconds')) in (int,float) and math.isfinite(budget['timeout_seconds']) and 0 < budget['timeout_seconds'] <= 900, '任务需要有限请求次数和时限')
        request = request_prefix + request
        from .commission import infer_output
        output=data.get('output_kind') or (target['kind'] if target else infer_output(request))
        require(kind=='workshop' or output in {'report','note','paper','diagram','poster','slides'},'此委托不支持该自动产出类型；统计图与准备任务请使用对应工作区')
        if target:require(output==target['kind'],'修订任务不能静默改变成果类型')
        context = {"background": project["content"], 'additional_background':data.get('background',''), "question": request, "materials": materials, "constraints": data.get("constraints", "不改原始数据；不启动未经授权拟合；结论绑定可访问证据"), "output": output, "acceptance": data.get("acceptance", "保存实际产物、来源和限制，进入审查；不把模型回复视为交付通过"), "unresolved": data.get("unresolved", [])}
        if fb:
            context['feedback']={k:fb['content'].get(k) for k in ('original','interpretation')} | {'id':fb['id'],'revision':fb['revision']}
        if material_resolution:
            context['material_resolution']=material_resolution
            context['background']={'title':project['title'],'description':project['content'].get('description','')}
        from .conventions import snapshot
        context['working_conventions'] = snapshot(s, project['id'])
        from .growth import active
        context['working_strategies']=active(s,project['id'],{'kind':kind,'output':output,'cycle_role':None},connection)
        local_strategies = context['working_strategies']
        if domain_context is not None:
            # A figure-only egress grant is not permission to disclose project
            # background, notebook conventions or unrelated growth records.
            context.update(background={}, working_conventions={}, working_strategies=[], figure_composition=copy.deepcopy(domain_context))
        payload = {"project_id": project["id"], "kind": kind, "request": request, "context": context, "target_id": target["id"] if target else None, "base_revision": target["revision"] if target else None, "provider_id": data.get("provider_id", self.config.get("default_provider")), "depends_on": data.get("depends_on", []), "budget": data.get("budget", {"max_model_calls": 4, "timeout_seconds": 300}), "authorization": data.get("authorization", {}), "priority": int(data.get("priority", 0)), "feedback_id": data.get("feedback_id"), "workshop": {k: data[k] for k in ["category", "inputs", "config", "code", "expected_output"] if k in data}}
        if literature_plan:payload["literature_plan"] = literature_plan
        if material_resolution:require(len(encoded(context).encode())<=14000,'委托上下文超过 14000 字节；请收窄补充背景或采用材料数量，不会截断科学正文','context_limit',409)
        def preflight(connection):
            current_project,current_materials,current_resolution=prepare_submission(self,data,scope,connection)
            require(current_project==project and current_materials==materials and current_resolution==material_resolution,'提交前项目或材料已变化，请重新预览','conflict',409)
            require(active(s,project['id'],{'kind':kind,'output':output,'cycle_role':None},connection)==local_strategies,'工作策略在提交期间改变，请重新预览','conflict',409)
            if target:require(s.get(target['id'],connection=connection)==target,'提交前成果已变化，请重新预览','conflict',409)
            if fb:require(s.get(fb['id'],connection=connection)==fb,'提交前反馈已变化，请重新读取','conflict',409)
            s.assert_material_readiness(connection,payload,mark_requirement=True)
            if kind != 'workshop':
                from .compatibility import require_features
                require_features(connection, ['bounded_growth_evidence_v1','reviewed_growth_comparison_v2','scientific_evidence_projection_v1'] + (['literature_acquisition_v1'] if literature_plan else []))
                if domain_context and domain_context.get('native_transport')=='app_server_dynamic':
                    require_features(connection, ['native_codex_dynamic_tools_v1'])
        if fb is None and connection is None:
            task=s.submit(payload,data.get('request_key') or uid('REQUEST'),preflight=preflight)
        else:
            with (s.transaction() if connection is None else contextlib.nullcontext(connection)) as tx:
                task = s.submit(payload, data.get("request_key") or uid("REQUEST"), preflight=preflight, connection=tx)
                if fb and register_feedback_action:
                    current=s.get(fb['id'],connection=tx)
                    if not any(a.get('task_id')==task['id'] for a in current['content'].get('actions',[])):
                        action={'id':uid('ACTION'),'scope':'method' if kind=='strategy_review' else 'result','timing':'after_task' if data.get('depends_on') else 'immediate','task_id':task['id'],'owner':'research_agent','provider_id':payload['provider_id'],'status':task['status'],'working_strategies':[g['id'] for g in context['working_strategies']]}
                        s.save(current['id'],current['revision'],content={**current['content'],'actions':current['content'].get('actions',[])+[action]},reason='task linked to feedback',merge=False,connection=tx)
        if self.runner and connection is None: self.runner.wake()
        return task

    @staticmethod
    def feedback_disposition(obj):
        return Store.feedback_disposition(obj)

    @staticmethod
    def feedback_options(data, defaults=None):
        defaults=defaults or {}
        scope=data.get('scope',defaults.get('scope','result'))
        scope={'workstyle':'method','result_and_method':'both'}.get(scope,scope)
        timing=data.get('timing',defaults.get('timing','immediate'))
        disposition=data.get('disposition',defaults.get('disposition','ready'))
        require(scope in {'result','method','both'},'反馈范围不支持')
        require(timing in {'immediate','after_task','after_user_trial'},'反馈处理时机不支持')
        require(timing!='after_user_trial' or disposition=='defer','试用后反馈仍应保留；发起行动前请明确选择新的处理时机','feedback_deferred',409)
        require(disposition in {'ready','defer'},'反馈安排不支持')
        return scope,timing,disposition

    def feedback(self, data, scope):
        s = self.store
        if data["action"] == "feedback.add":
            with s.transaction() as tx:
                ident=data.get('object_id') or data['project_id']
                target=self.access(s.get(ident,connection=tx),scope)
                project=target['project_id'] or target['id']
                require(scope is None or project in scope,'共享材料为只读；请在本项目创建衍生成果','forbidden',403)
                require(data.get('project_id') in (None,project),'反馈与目标项目不一致','forbidden',403)
                if 'expected_target_revision' in data:
                    expected=data['expected_target_revision']
                    require(type(expected) is int and expected==target['revision'],'留言目标已变化，草稿应保留；请重读或明确采用所见历史修订','conflict',409,{'current':target})
                revision=data.get('object_revision',target['revision'])
                require(type(revision) is int and revision>0,'留言需要准确目标修订','version_required',409)
                # Historical comments bind the actual displayed version; current
                # access was checked above, independently of historical metadata.
                source=s.get(ident,revision,connection=tx)
                text=data.get('text','')
                require(isinstance(text,str) and text.strip(),'意见不能为空')
                requested_scope,timing,disposition=self.feedback_options(data)
                interpretation=data.get('interpretation') or None
                require(interpretation is None or isinstance(interpretation,str),'意见理解应为文字')
                return s.create('feedback',text[:70],project,{'original':text,'source':data.get('source','user'),'source_reference':data.get('source_reference'),'object_id':ident,'object_revision':source['revision'],'interpretation':interpretation,'actions':[],'lifecycle':'active','disposition':disposition,'disposition_reason':data.get('reason','')},{'scope':requested_scope,'timing':timing},connection=tx)
        if data['action']=='feedback.inspect':
            obj=self.get(data['id'],scope)
            require(obj['kind']=='feedback','对象不是反馈')
            return self.feedback_view(obj,scope)
        result=None
        with s.transaction() as tx:
            fb=self.access(s.get(data['id'],connection=tx),scope)
            require(scope is None or fb['project_id'] in scope,'共享反馈为只读','forbidden',403)
            require(fb['kind']=='feedback','对象不是反馈')
            if data['action']=='feedback.withdraw':
                # Withdrawal is also safe for a legacy client without a revision:
                # it can only revoke authority, never schedule or overwrite text.
                require(data.get('expected_revision',fb['revision'])==fb['revision'],'反馈已变化，请重读后撤回','conflict',409)
                result=s.save(fb['id'],fb['revision'],content={**fb['content'],'lifecycle':'withdrawn'},merge=False,connection=tx)
            elif data['action']=='feedback.review':
                require(data.get('expected_revision')==fb['revision'],'反馈已变化，请重新读取','conflict',409,{'current':fb})
                require(fb['content'].get('lifecycle')!='withdrawn','已撤回反馈不能重新安排','cancelled',409)
                oldscope={'artifact':'result','project':'result','work_method':'method'}.get(fb['metadata'].get('scope'),fb['metadata'].get('scope','result'))
                oldtiming=fb['metadata'].get('timing') if fb['metadata'].get('timing') in {'after_task','after_user_trial'} else 'immediate'
                requested_scope,timing,disposition=self.feedback_options(data,{'scope':oldscope,'timing':oldtiming,'disposition':self.feedback_disposition(fb)})
                interpretation=data.get('interpretation',fb['content'].get('interpretation'))
                require(interpretation is None or isinstance(interpretation,str),'意见理解应为文字')
                result=s.save(fb['id'],fb['revision'],content={**fb['content'],'interpretation':interpretation,'disposition':disposition,'disposition_reason':data.get('reason',fb['content'].get('disposition_reason',''))},metadata={**fb['metadata'],'scope':requested_scope,'timing':timing},merge=False,reason='feedback interpretation and schedule saved; no execution requested',connection=tx)
                if interpretation!=fb['content'].get('interpretation'):
                    for row in tx.execute("SELECT * FROM tasks WHERE project_id=? AND status IN ('queued','running','paused','waiting_input','waiting_resource','waiting_authorization','failed')",(fb['project_id'],)).fetchall():
                        task=s.unpack(row)
                        if task['payload'].get('feedback_id')!=fb['id']:continue
                        s.event(tx,'task.guidance',task['id'],{'text':'用户已更新反馈理解；原话：'+fb['content']['original']+'\n当前理解：'+(interpretation or '尚未给出；不可替用户补造理解'),'source':'user','source_reference':{'feedback_id':fb['id'],'revision':result['revision']},'scope':'next execution handoff; cannot grant permissions'},'user')
            elif data['action']=='feedback.request':
                require(fb['content'].get('lifecycle')!='withdrawn','反馈已撤回','cancelled',409)
                require(self.feedback_disposition(fb)!='defer','反馈已暂缓，请先明确重新安排','feedback_deferred',409)
                requested_scope,timing,_=self.feedback_options(data)
                revision=data.get('expected_revision')
                require(type(revision) is int and revision>0,'安排执行需要已读反馈版本','version_required',409)
                key=data.get('request_key') or 'feedback:'+fb['id']+':'+str(revision)
                require(isinstance(key,str) and key.strip(),'任务需要稳定请求标识')
                fingerprint=digest({**data,'scope':requested_scope,'timing':timing,'request_key':key})
                receiptkey='feedback_request:'+key
                previous=tx.execute('SELECT value FROM kv WHERE key=?',(receiptkey,)).fetchone()
                if previous:
                    receipt=json.loads(previous[0])
                    require(receipt['fingerprint']==fingerprint,'同一反馈请求标识的内容不同','idempotency_conflict',409)
                    result={**s.task(receipt['task_ids'][0],tx),'feedback_id':fb['id'],'feedback_revision':receipt['feedback_revision'],'action_task_ids':receipt['task_ids']}
                else:
                    require(revision==fb['revision'],'反馈已变化，请重新读取','conflict',409,{'current':fb})
                    require(not tx.execute('SELECT 1 FROM tasks WHERE request_key IN (?,?)',(key,key+':method')).fetchone(),'请求标识已用于其他任务','idempotency_conflict',409)
                    target=self.access(s.get(fb['content']['object_id'],connection=tx),scope)
                    method_only=requested_scope=='method'
                    target_id=target['id'] if target['kind']!='project' and not method_only else None
                    if target_id:
                        require(type(data.get('expected_target_revision')) is int,'修订成果需要已读目标版本','version_required',409)
                        require(data['expected_target_revision']==target['revision'],'成果已变化，请重新预览','conflict',409,{'current':target})
                    dependencies=list(data.get('depends_on',[]))
                    if timing=='after_task':
                        dependencies=list(dict.fromkeys(dependencies+[row['id'] for row in tx.execute("SELECT id FROM tasks WHERE project_id=? AND status IN ('queued','running','paused','waiting_input','waiting_resource','waiting_authorization')",(fb['project_id'],))]))
                    payload={**data,'action':'task.submit','project_id':fb['project_id'],'request':fb['content']['original'],'object_id':target_id,'expected_revision':target['revision'] if target_id else None,'expected_feedback_revision':fb['revision'],'feedback_id':fb['id'],'kind':'strategy_review' if method_only else 'revision','depends_on':dependencies,'request_key':key}
                    prefix='分析以下工作方式意见，输出原因假设、最小策略改动、预期观察和比较办法。只提出候选，不自行改变工作策略或权限。\n' if method_only else ''
                    if method_only:payload['output_kind']='note'
                    task=self.submit(payload,scope,register_feedback_action=False,connection=tx,request_prefix=prefix)
                    def action_for(task,action_scope,action_timing):
                        return {'id':uid('ACTION'),'intent':fingerprint,'scope':action_scope,'timing':action_timing,'task_id':task['id'],'owner':'research_agent','provider_id':task['payload']['provider_id'],'status':task['status'],'depends_on':task['payload']['depends_on'],'feedback_revision':fb['revision']}
                    actions=[action_for(task,'method' if method_only else 'result',timing)]
                    tasks=[task]
                    if requested_scope=='both':
                        method_payload={k:v for k,v in payload.items() if k not in {'material_mode','resolution_pin','selected_materials','selected_project_id','additional_materials','literature_plan'}}
                        method_payload.update(object_id=None,expected_revision=None,kind='strategy_review',output_kind='note',depends_on=[task['id']],request_key=key+':method',materials=task['payload']['context']['materials'],literature_plan={'enabled':False})
                        method=self.submit(method_payload,scope,register_feedback_action=False,connection=tx,request_prefix='在成果修订形成候选后，分析同一意见涉及的工作方式，提出原因假设、最小策略改动及比较办法；不宣称已采用或普遍有效。\n')
                        tasks.append(method);actions.append(action_for(method,'method','after_task'))
                    updated=s.save(fb['id'],fb['revision'],content={**fb['content'],'actions':fb['content'].get('actions',[])+actions},merge=False,reason='explicit feedback action request',connection=tx)
                    receipt={'fingerprint':fingerprint,'feedback_id':fb['id'],'feedback_revision':updated['revision'],'task_ids':[item['id'] for item in tasks]}
                    tx.execute('INSERT INTO kv VALUES(?,?)',(receiptkey,encoded(receipt)))
                    result={**task,'feedback_id':fb['id'],'feedback_revision':updated['revision'],'action_task_ids':receipt['task_ids']}
            else:raise Problem('反馈操作不支持')
        # Work becomes visible only after every task and feedback link commits.
        if self.runner:
            if data['action']=='feedback.withdraw' or (data['action']=='feedback.review' and self.feedback_disposition(result)=='defer'):self.runner.stop_revoked()
            elif data['action']=='feedback.request':self.runner.wake()
        return result

    def feedback_view(self, obj, scope=None):
        """Read-only task projection; saved action labels are never execution truth."""
        from .feedback_external import require_read_access
        require_read_access(self, obj, scope)
        s=self.store;actions=[]
        for saved in obj['content'].get('actions',[]):
            action=copy.deepcopy(saved);action.update(task=None,output=None,changes=None,validation=None,live_status=saved.get('status','unassigned'))
            if not saved.get('task_id'):
                from .feedback_external import project_action
                try:
                    registered = project_action(self, obj, saved, scope)
                except Problem as error:
                    registered = None
                    action['unavailable_reason'] = str(error)
                # Never trust a verification marker supplied through object.save.
                action['registration_verified'] = False
                actions.append(registered or action);continue
            try:
                task=s.task(saved['task_id'])
                require(task['project_id']==obj['project_id'] and (scope is None or task['project_id'] in scope),'行动任务不可读','forbidden',403)
                payload=task['payload'];result=task['result']
                action.update(live_status=task['status'],task={k:copy.deepcopy(task[k]) for k in ('id','status','error','attempts','created_at','updated_at')})
                action['task']['payload']={k:copy.deepcopy(payload.get(k)) for k in ('kind','provider_id','depends_on','budget','target_id','base_revision')}
                action['provider_id']=payload.get('provider_id')
                action['validation']={'independent_review':result.get('independent_review','not_recorded'),'user_acceptance':result.get('user_acceptance','not_recorded'),'records':[]}
                output_id=result.get('object_id') or saved.get('object_id')
                revision=result.get('revision') or saved.get('revision')
                if output_id and type(revision) is int:
                    output=self.get(output_id,scope,revision)
                    require(output['project_id']==obj['project_id'],'行动成果归属不符','forbidden',403)
                    action['output']={k:output[k] for k in ('id','title','kind','revision')}
                    from .feedback_external import visible_review_records
                    action['validation']['records']=visible_review_records(self, s.review_records(output_id,revision), scope)
                    base={'id':payload.get('target_id'),'revision':payload.get('base_revision')} if payload.get('target_id') else None
                    paths=[]
                    if base:
                        before=self.get(base['id'],scope,base['revision'])
                        def compare(a,b,path='content'):
                            if a==b:return
                            if isinstance(a,dict) and isinstance(b,dict):
                                for key in sorted(a.keys()|b.keys()):compare(a.get(key),b.get(key),path+'.'+key)
                            else:paths.append(path)
                        compare(before['content'],output['content'])
                        if before['title']!=output['title']:paths.append('title')
                    action['changes']={'base':base,'result':{'id':output_id,'revision':revision},'changed_paths':paths,'kind':'revision' if base else 'new_candidate'}
            except Problem as error:
                action['unavailable_reason']=str(error)
                if action['task'] is None:action['live_status']='unavailable'
            actions.append(action)
        rawscope=obj['metadata'].get('scope','result')
        canonical={'artifact':'result','project':'result','work_method':'method','workstyle':'method','result_and_method':'both'}.get(rawscope,rawscope)
        view={'scope':canonical,'timing':obj['metadata'].get('timing','immediate'),'disposition':self.feedback_disposition(obj),'actions':actions,'read_only_projection':True}
        return {**obj,'feedback_view':view}

    def answer(self, data, scope):
        obj = self.writable(data["id"], scope)
        require(obj["kind"] == "question", "对象不是决策")
        require(data.get("expected_revision") == obj["revision"], "问题已变化，需重新读取", "conflict", 409)
        choice = data.get("answer")
        require(isinstance(choice,str) and choice.strip(), "需要具体回答；空文字不能放行任务")
        disposition=data.get('disposition','defer')
        require(disposition in {'continue','deny','defer'},'请选择在既有范围接续、拒绝或暂缓；回答不增加权限')
        if disposition=='continue' and obj['content'].get('blocking'):
            require(self.store.question_view(obj)['question_view']['source_valid'],'来源已经更新；请先从当前候选或成果重新评估此问题，保留旧回答','conflict',409)
        result = self.store.save(obj["id"], obj["revision"], content={**obj["content"], "answer": choice.strip(), "answered_at": now(), "status": "deferred" if disposition=='defer' else "denied" if disposition=='deny' else "answered",'disposition':disposition,'grants_permissions':False})
        self.after_question_answer(result,disposition)
        return result

    def after_question_answer(self,obj,disposition):
        if self.runner:self.runner.stop_revoked()
        for task in self.store.tasks():
            relevant=task['project_id']==obj['project_id'] and (not obj['content'].get('task_id') or obj['content']['task_id']==task['id'])
            if not relevant or not obj['content'].get('blocking'):continue
            if disposition=='deny' and task['status'] in {'queued','running','paused','waiting_input','waiting_resource','waiting_authorization','failed'}:
                if self.runner:self.runner.control(task['id'],'cancel')
                else:self.store.task_update(task['id'],'cancelled',error='必要裁决拒绝该动作')
            elif disposition=='continue' and task['status']=='waiting_input' and (task.get('error') or '').startswith('必要裁决') and task['attempts']<3:
                if self.runner:self.runner.control(task['id'],'resume')
                else:self.store.task_update(task['id'],'queued',error=None)
        if self.runner:self.runner.wake()

    def question_action(self,data,scope):
        from .questions import model_questions
        s=self.store;obj=self.get(data['id'],scope) if data['action']=='question.candidate_preview' else self.writable(data['id'],scope)
        require(obj['kind']=='question','对象不是研究问题')
        if data['action']=='question.candidate_preview':
            from .providers import _controlled_file
            from .questions import scientific_candidate
            ref=obj['content'].get('source_candidate',{})
            require(isinstance(ref.get('sha256'),str) and re.fullmatch(r'[0-9a-f]{64}',ref['sha256']),'此问题没有可核验的候选来源','not_found',404)
            task=s.task(ref.get('task_id'));require(task['project_id']==obj['project_id'],'问题候选归属不符','forbidden',403)
            require(scope is None or task['project_id'] in scope,'共享问题不授予原任务候选访问权限','forbidden',403)
            base=Path(self.config.get('control_root',str(Path.home()/'.local/share/research-partner/control'))).expanduser()
            directory=base/digest(str(s.workspace))[:20]/task['id']
            candidates=[directory/'candidate.json',directory/('candidate.preserved-'+ref['sha256']+'.json')]
            raw=None
            for path in candidates:
                if path.exists():
                    value=_controlled_file(directory,path,131072)
                    if digest(value)==ref['sha256']:raw=value;break
            if raw is None:
                from .native_recovery import stored_candidate
                raw=stored_candidate(self,task,ref['sha256'],scope)
            require(raw is not None,'此候选检查点在当前实例不可用；未重新调用模型','candidate_checkpoint_unavailable',503)
            candidate=scientific_candidate(json.loads(raw),task['payload'].get('context',{}).get('output','report'))
            return {'task_id':task['id'],'sha256':ref['sha256'],'candidate':candidate,'read_only':True}
        require(data.get('expected_revision')==obj['revision'],'问题已变化，请重读','conflict',409)
        view=s.question_view(obj)['question_view']
        if data['action']=='question.reassess':
            require(data.get('approved') is True,'需要明确重新评估；回答不授予新科学或费用权限','authorization_required',403)
            require(view['source_stale'] and view['source_bound'] and all(not ref.get('unavailable') for ref in view['sources']),'需要可读取的已更新来源','conflict',409)
            require(isinstance(data.get('source_snapshot'),list) and data['source_snapshot']==view['sources'],'来源已变化，请重新读取','conflict',409)
            reason=data.get('reason');answer=data.get('answer');disposition=data.get('disposition')
            require(isinstance(reason,str) and reason.strip() and isinstance(answer,str) and answer.strip(),'请记录看到的来源变化、保留原采用版本的理由和具体回答')
            require(disposition in {'continue','deny','defer'},'请选择继续、拒绝或暂缓；不会新增权限')
            reassessment={'source_snapshot':copy.deepcopy(data['source_snapshot']),'reason':reason.strip(),'at':now(),
                'previous_question_revision':obj['revision'],'adopted_sources_changed':False,'grants_permissions':False}
            content={**obj['content'],'source_reassessment':reassessment,'answer':answer.strip(),'answered_at':now(),
                'status':'deferred' if disposition=='defer' else 'denied' if disposition=='deny' else 'answered','disposition':disposition,'grants_permissions':False}
            result=s.save(obj['id'],obj['revision'],content=content,reason='explicit question source reassessment',merge=False,question_source_snapshot=data['source_snapshot'])
            self.after_question_answer(result,disposition)
            return s.question_view(result)
        if data['action']=='question.bind':
            require(obj['content'].get('scope') in {'followup','optional','historical'},'此问题已有当前任务作用域','conflict',409)
            require(data.get('approved') is True,'绑定后续动作需要明确选择；不会授权新科学计算','authorization_required',403)
            require(view['source_bound'] and view['source_valid'],'来源已更新或尚未绑定；请从当前成果提出新问题或明确重新评估，保留历史题','conflict',409)
            task=s.task(data['task_id']);self.writable(task['project_id'],scope)
            require(task['project_id']==obj['project_id'],'问题和未来任务必须属于同一项目','forbidden',403)
            require(task['status'] in {'queued','paused','waiting_input','waiting_resource','waiting_authorization','failed'},'请先停止目标任务再绑定问题','conflict',409)
            require(type(data.get('blocking')) is bool,'必须明确该问题是否阻断所绑定动作')
            content={**obj['content'],'bound_task_id':task['id'],'task_id':task['id'],'blocking':data['blocking'],
                'binding':{'task_id':task['id'],'question_revision':obj['revision'],'at':now(),'permissions_changed':False}}
            result=s.save(obj['id'],obj['revision'],content=content,reason='explicit question binding')
            if self.runner:self.runner.stop_revoked()
            return s.question_view(result)
        existing=obj['content'].get('question_ids')
        if existing:return {'questions':[s.question_view(self.get(ident,scope)) for ident in existing],'created':[],'original_parent':{'id':obj['id'],'revision':obj['revision']}}
        raw=obj['content'].get('model_questions',[])
        require(isinstance(raw,list) and raw,'此父问题没有待展开的原始模型问题')
        require(all(isinstance(question,dict) for question in raw),'原始模型问题结构无法展开；原字段已保留','invalid_model_output',422)
        # Legacy embedded questions had no enforced scope contract. Preserve
        # their raw assertions, but never retroactively grant blocking force.
        normalized=model_questions([{**question,'scope':'historical'} for question in raw])
        for item,original in zip(normalized,raw):item['raw']=copy.deepcopy(original)
        refs=[ref for ref in view['sources'] if ref['kind']=='artifact' and not ref.get('unavailable')]
        source_ref={'id':refs[0]['id'],'revision':refs[0]['revision']} if refs else None
        result=s.register_questions(obj['project_id'],normalized,{'parent_question_id':obj['id']},source_ref=source_ref,parent=obj)
        return {**result,'original_parent':{'id':obj['id'],'revision':obj['revision']},'legacy_scope':'historical','permissions_changed':False}

    def growth(self, data, scope):
        from .growth import dispatch
        return dispatch(self,data,scope)

    def link_growth_feedback(self, growth):
        fb=self.store.get(growth['content']['feedback'])
        actions=fb['content'].get('actions',[])
        previous=next((a for a in actions if a.get('growth_id')==growth['id'] and a.get('scope')=='method'),None)
        action={**(previous or {'id':uid('ACTION')}),'scope':'method','timing':'after_task','owner':'coordinator','growth_id':growth['id'],'revision':growth['revision'],'status':growth['content']['status'],'verification':growth['content'].get('decision_reason','candidate; not yet adopted')}
        self.store.save(fb['id'],fb['revision'],content={**fb['content'],'actions':[a for a in actions if not (a.get('growth_id')==growth['id'] and a.get('scope')=='method')]+[action]},reason='linked growth disposition')

    def backup(self):
        s = self.store
        with tempfile.TemporaryDirectory(prefix="rp-backup-") as directory:
            root = Path(directory)
            target = sqlite3.connect(root / "research.sqlite3")
            with s.connect() as c: c.backup(target)
            target.close()
            with sqlite3.connect(root/'research.sqlite3') as snapshot:
                old_backups={r[0] for r in snapshot.execute('SELECT sha,metadata FROM assets') if json.loads(r[1]).get('kind')=='backup'}
                snapshot.executemany('DELETE FROM assets WHERE sha=?',[(sha,) for sha in old_backups])
                registered = snapshot.execute('SELECT sha,size FROM assets ORDER BY sha').fetchall()
            # Product config, tokens and provider credentials are never stored in SQLite or copied.
            package = root / "workspace.zip"
            records = []
            with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as z:
                z.write(root / "research.sqlite3", "research.sqlite3")
                # Only this frozen database snapshot authorizes export. Never scan
                # the blob directory: it can contain crash residue or later writes.
                for sha, size in registered:
                    require(isinstance(sha,str) and len(sha)==64 and all(ch in '0123456789abcdef' for ch in sha), "迁移资产标识不合法", "integrity", 409)
                    p = s.blobs / sha
                    require(p.is_file(), "迁移资产文件缺失", "missing_asset", 409, {"sha": sha})
                    try:
                        content = p.read_bytes()
                    except FileNotFoundError as error:
                        raise Problem("迁移资产文件缺失", "missing_asset", 409, {"sha": sha}) from error
                    require(hashlib.sha256(content).hexdigest() == sha and len(content) == size, "迁移前资产校验失败", "integrity", 409, {"sha": sha})
                    z.writestr("assets/" + sha, content)
                    records.append({"sha256": sha, "bytes": len(content)})
                from .compatibility import workspace_requirements
                manifest = {"format": "research-partner-workspace", "schema_version": 1, "created_at": now(), "database_sha256": hashlib.sha256((root / "research.sqlite3").read_bytes()).hexdigest(), "assets": records, "credentials_included": False, "provider_rebinding_required": True, "implementation": self.loaded_implementation["digest"], "minimum_runtime_features":workspace_requirements(root)['minimum_runtime_features']}
                z.writestr("manifest.json", encoded(manifest))
            return s.add_asset(package.read_bytes(), "research-space.zip", "application/zip", {"kind": "backup", "manifest": manifest})


def restore_workspace(archive, destination):
    destination = Path(destination).resolve()
    require(not destination.exists() or not any(destination.iterdir()), "恢复目标必须为空；原空间不会覆盖", "conflict", 409)
    destination.mkdir(parents=True, exist_ok=True, mode=0o700)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("manifest.json"))
        require(manifest.get("format") == "research-partner-workspace" and manifest.get("schema_version") == 1, "迁移格式不支持")
        from .compatibility import feature_list, check_workspace
        declared_floor=feature_list(manifest.get('minimum_runtime_features',[]))
        files = {"research.sqlite3": manifest["database_sha256"], **{"assets/" + a["sha256"]: a["sha256"] for a in manifest["assets"]}}
        require(set(z.namelist()) == set(files) | {"manifest.json"}, "迁移包含未登记路径")
        require(sum(i.file_size for i in z.infolist()) < 2 * 1024**3, "迁移包超过本机2GB边界")
        for name, sha in files.items():
            content = z.read(name)
            require(hashlib.sha256(content).hexdigest() == sha, "迁移校验失败：" + name, "integrity", 409)
        for name in files:
            path = destination / name
            require(path.resolve().is_relative_to(destination), "迁移路径越界", "forbidden", 403)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(z.read(name)); os.chmod(path, 0o600)
    actual_floor=check_workspace(destination)['minimum_runtime_features']
    require(actual_floor==declared_floor,'迁移manifest与数据库能力门槛不一致；未启动研究空间','compatibility_invalid',409)
    store = Store(destination)
    with store.transaction() as c:
        # Restored history is readable, but execution and candidate authority
        # must be issued again on this instance. Match literal prefixes.
        for (key,) in c.execute("SELECT key FROM kv").fetchall():
            if key.startswith(("execution:", "code_grant:", "extension_grant:", "project_management:grant:",
                               "generation_grant:", "manuscript_revision:grant:")):
                c.execute("DELETE FROM kv WHERE key=?", (key,))
        registry=store.setting('extension_registry',{})
        for entry in registry.values():
            if isinstance(entry,dict):entry['grants']=[];entry['enabled']=False
        c.execute("UPDATE kv SET value=? WHERE key='extension_registry'",(encoded(registry),))
    # Running work is never silently relaunched on a different host.
    for task in store.tasks():
        if task["status"] in {"running", "queued"}: store.task_update(task["id"], "waiting_authorization", error="迁入新实例：需重绑提供者并确认接续权限")
    return {"restored": True, "workspace": str(destination), "objects": len(store.objects()), "assets": len(manifest["assets"]), "credentials_required": True, "minimum_runtime_features":actual_floor}
