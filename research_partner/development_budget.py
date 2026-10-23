"""Small persistent cap for this isolated development cycle, not a platform.

Reservations precede dispatch and are never refunded after an uncertain return.
Existing task/provider ledgers remain authoritative for actual usage. A stop
marker fences future reservations; the owning runner checks it during execution.
"""
import contextlib
import fcntl
import json
import math
import os
from datetime import datetime
from pathlib import Path
import time
from .store import require, encoded


class Budget:
    def __init__(self,path):
        self.path=Path(path)
        self.stop=self.path.with_suffix('.stop')

    @contextlib.contextmanager
    def locked(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        fd=os.open(str(self.path)+'.lock',os.O_CREAT|os.O_RDWR,0o600)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX)
            yield
        finally:os.close(fd)

    def write(self,value):
        temp=self.path.with_suffix('.tmp')
        fd=os.open(temp,os.O_CREAT|os.O_TRUNC|os.O_WRONLY,0o600)
        with os.fdopen(fd,'w') as f:
            f.write(encoded(value)+'\n');f.flush();os.fsync(f.fileno())
        temp.replace(self.path)

    def initialize(self,*,started_at,model_calls=6,model_seconds=1080,review_calls=6,wall_seconds=14400):
        with self.locked():
            if self.path.exists():return json.loads(self.path.read_text())
            state={'schema':'core-development-budget/v1','started_at':started_at,'deadline':started_at+wall_seconds,
                   'limits':{'model_calls':model_calls,'model_seconds':model_seconds,'review_calls':review_calls},
                   'reserved':{'model_calls':0,'model_seconds':0,'review_calls':0},'reservations':[],
                   'actual_bill_usd':None,'prior_workbench_budget':'preserved, no reset; prior usage not known here'}
            self.write(state);return state

    def check(self):
        require(self.path.exists(),'开发总额度未初始化','authorization_required',403)
        require(not self.stop.exists(),'开发停止标记已生效','development_stopped',409)
        state=json.loads(self.path.read_text())
        valid=isinstance(state,dict) and isinstance(state.get('limits'),dict) and isinstance(state.get('reserved'),dict)
        continuous=self.continuous(state)
        if valid:
            used=state['reserved'];caps=state['limits']
            for key in ('model_calls','review_calls','model_seconds'):
                value=used.get(key)
                valid=valid and type(value) in ((int,) if key!='model_seconds' else (int,float)) and math.isfinite(value) and value>=0
                cap=caps.get(key)
                valid=valid and ((continuous and key in caps and cap is None) or
                    type(cap) in ((int,) if key!='model_seconds' else (int,float)) and math.isfinite(cap) and cap>=0)
            deadline=state.get('deadline')
            valid=valid and ((continuous and 'deadline' in state and deadline is None) or
                type(deadline) in (int,float) and math.isfinite(deadline))
            single=caps.get('model_single_seconds',600)
            valid=valid and type(single) in (int,float) and math.isfinite(single) and single>0
            rounds=caps.get('review_roundtrips',20)
            valid=valid and ((continuous and rounds is None) or type(rounds) is int and rounds>=0)
        require(valid,'父资源账结构或计数无效；保留原字节，不推断剩余额度','integrity',409)
        require(time.time()<self.deadline(state),'本轮有界工作窗口已用尽；保留检查点，不重置','budget_exhausted',409)
        return state

    @staticmethod
    def continuous(state):
        authority=state.get('active_authorization',{})
        return (isinstance(authority,dict) and authority.get('mode')=='continuous_development'
                and authority.get('source')=='explicit_user'
                and isinstance(authority.get('record'),str) and bool(authority['record'])
                and authority.get('local_caps_removed') is True)

    @staticmethod
    def deadline(state):
        value=state['deadline']
        require(value is not None or Budget.continuous(state),'缺少持续开发明确授权','integrity',409)
        return float('inf') if value is None else value

    @staticmethod
    def remaining(state,key):
        value=state['limits'][key]
        require(value is not None or Budget.continuous(state),'缺少取消局部额度明确授权','integrity',409)
        return float('inf') if value is None else value-state['reserved'][key]

    @staticmethod
    def native_permission(state, frozen=None, amount=None, *, read_only=False):
        """Current grouped native fee planning; unknown bills are never refunds."""
        scope=state.get('native_figure_authorization')
        if scope is None:return None
        finite=lambda v:type(v) in (int,float) and (type(v) is int or math.isfinite(v)) and v>0
        require(isinstance(scope,dict) and scope.get('authorized') is True
                and type(scope.get('max_attempts')) is int and scope['max_attempts']>0
                and finite(scope.get('per_attempt_usd')) and finite(scope.get('total_planning_usd'))
                and scope['per_attempt_usd']<=scope['total_planning_usd']
                and all(isinstance(scope.get(k),str) and scope[k] for k in ('reference','model','runtime_lock_sha256')),
                '当前原生有限费用许可结构无效；不推断授权','authorization_required',403)
        if frozen is not None:
            require(scope['reference']==frozen['authorization_reference'] and scope['model']==frozen['model']
                    and scope['runtime_lock_sha256']==frozen['runtime_lock_sha256']
                    and frozen['deadline']<=Budget.deadline(state),
                    '此模型/费用/窗口不属于父任务当前许可','authorization_required',403)
            amount=frozen['budget_usd']
        if read_only:return scope
        existing=[r for r in state['reservations'] if r['kind']=='model' and r.get('request_cap') is not None]
        require(all(finite(r.get('native_fee_planning_reserved_usd')) for r in existing),
                '旧原生费用规划未知，不能当零消耗继续','authorization_required',403)
        require(len(existing)<scope['max_attempts'],'当前原生验证次数许可已到','budget_exhausted',409)
        require(finite(amount) and amount<=scope['per_attempt_usd']
                and sum(r['native_fee_planning_reserved_usd'] for r in existing)+amount<=scope['total_planning_usd'],
                '当前原生有限费用规划额度不足','budget_exhausted',409)
        return scope

    def reserve(self,kind,ident,seconds=0,*,review_id=None,request_cap=None,native_budget_usd=None):
        with self.locked():
            state=self.check()
            self._settle(state)
            require(not any(r['id']==ident for r in state['reservations']),'分派身份已有预留；不重复启动','idempotency_conflict',409)
            require(request_cap is None or (kind=='model' and type(request_cap) is int and 1<=request_cap<=4),
                    '仅显式原生主图路线可预留1至4个实际请求')
            native_scope=self.native_permission(state,amount=native_budget_usd) if request_cap is not None else None
            delta={'review_calls':1} if kind=='review' else {'model_calls':request_cap or 1,'model_seconds':seconds}
            require(kind in {'review','model'} and type(seconds) in (int,float) and math.isfinite(seconds)
                    and 0<=seconds<=state['limits'].get('model_single_seconds',600),'开发预留无效；超过当前单次命令保护')
            require(all(v<=self.remaining(state,k) for k,v in delta.items()),'本轮累计开发调用/时间额度耗尽，未分派','budget_exhausted',409)
            if kind=='review' and review_id:
                rounds={r['review_id'] for r in state['reservations'] if r.get('review_id')}
                round_cap=state['limits'].get('review_roundtrips',20)
                require(review_id in rounds or round_cap is None or len(rounds)<round_cap,'本轮复核往返额度耗尽，未投递','budget_exhausted',409)
            for k,v in delta.items():state['reserved'][k]+=v
            item={'id':ident,'kind':kind,'seconds':seconds,'at':time.time(),'state':'reserved_or_uncertain'}
            if request_cap is not None:
                item.update(request_cap=request_cap,accounting_unit='bounded_native_stream_requests; failed attempt at least one')
            if native_scope is not None:item.update(native_authorization_reference=native_scope['reference'],native_fee_planning_reserved_usd=native_budget_usd,native_actual_bill_usd=None)
            if review_id:item['review_id']=review_id
            state['reservations'].append(item)
            self.write(state)
            return state

    def complete(self,ident,evidence,*,only_unsettled=False):
        with self.locked():
            state=self.check() if only_unsettled else json.loads(self.path.read_text())
            if only_unsettled:
                rows=[r for r in state['reservations'] if r['id']==ident]
                require(len(rows)==1 and rows[0]['kind']=='model' and 'request_cap' not in rows[0],
                        '缺少唯一原 CLI 预留；未新增额度','integrity',409)
                row=rows[0]
                if row['state']=='returned':
                    require(row.get('evidence')==evidence,'原预留已有不同结算证据','integrity',409)
                    return
                require(row['state']=='reserved_or_uncertain' and not row.get('evidence'),
                        '原预留不能由此次补证改写','integrity',409)
            found=next(r for r in state['reservations'] if r['id']==ident)
            if evidence.get('transport') in {'app_server_dynamic','deepseek_harness_native'} and found.get('evidence')!=evidence:
                previous=found.get('evidence',{})
                if previous.get('native_terminal_confirmed') is True:
                    fields=('task_id','attempt_id','invocation','session_id','native_turn_id','started_at','finished_at','native_terminal_confirmed')
                    require(all(previous.get(k)==evidence.get(k) for k in fields),
                            '原生已知结算不能降级或改写调用身份/时间', 'integrity', 409)
                if self._no_dispatch(previous):
                    require(previous==evidence,'已核实派发前失败不能改成未知或另一调用', 'integrity', 409)
                if found.get('evidence'):
                    found.setdefault('settlement_history',[]).append({'state':found['state'],'evidence':found['evidence'],'observed_at':found.get('finished_at')})
            before_dispatch=self._no_dispatch(evidence)
            if before_dispatch:
                require(ident==evidence['task_id']+':'+str(evidence['invocation']),
                        '派发前结算不属于原预留调用', 'integrity', 409)
            if found.get('request_cap') is not None:
                require(evidence.get('task_id', '')+':'+str(evidence.get('invocation'))==ident,
                        '原生请求结算不属于原任务预留', 'integrity', 409)
                previous=found.get('evidence',{})
                if self._figure_calls(previous,found['request_cap']) is not None:
                    require(previous==evidence,'已核实原生请求结算不能改写', 'integrity', 409)
            unknown=(evidence.get('transport')=='app_server_dynamic' and evidence.get('native_terminal_confirmed') is not True and not before_dispatch
                     or found.get('request_cap') is not None and self._figure_calls(evidence,found['request_cap']) is None)
            found.update(state='failed_before_dispatch' if before_dispatch else 'result_unknown' if unknown else 'returned',evidence=evidence,finished_at=time.time())
            self._settle(state)
            self.write(state)

    @staticmethod
    def _no_dispatch(receipt):
        proof=receipt.get('dispatch_proof')
        return (receipt.get('route')=='codex' and receipt.get('transport')=='app_server_dynamic'
                and isinstance(receipt.get('task_id'),str) and receipt['task_id']
                and type(receipt.get('invocation')) is int and receipt['invocation']>0
                and isinstance(receipt.get('attempt_id'),str) and len(receipt['attempt_id'])==24
                and all(c in '0123456789abcdef' for c in receipt['attempt_id'])
                and receipt.get('native_terminal_confirmed') is False
                and receipt.get('dispatch_not_started') is True
                and all(receipt.get(k) is None for k in ('session_id','native_turn_id','started_at','finished_at'))
                and isinstance(proof,dict) and proof.get('session_run_entered') is False
                and proof.get('stage') in {'bridge_setup','client_initialization','session_constructor'}
                and proof.get('snapshot_sha256')==receipt.get('events_sha256')
                and isinstance(proof.get('snapshot_sha256'),str) and len(proof['snapshot_sha256'])==64
                and all(c in '0123456789abcdef' for c in proof['snapshot_sha256']))

    @staticmethod
    def _figure_calls(receipt,cap):
        """Unused reservations need a closed, exact native request ledger.

        This does not validate a candidate or convert token estimates to bills.
        The provider's independent checkpoint checks produce these fields. A
        missing/uncertain stream or terminal keeps the entire request cap.
        """
        ledger=receipt.get('native_request_accounting')
        if not (receipt.get('route')=='deepseek_harness'
                and receipt.get('transport')=='deepseek_harness_native'
                and receipt.get('feature')=='deepseek_task_figure_tools_v1'
                and receipt.get('native_terminal_confirmed') is True
                and isinstance(ledger,dict) and ledger.get('closed') is True
                and ledger.get('unknown_requests') is False
                and type(ledger.get('actual_requests')) is int
                and 0<=ledger['actual_requests']<=cap
                and ledger.get('request_cap')==cap and type(ledger.get('request_cap')) is int
                and isinstance(ledger.get('usage_sha256'),str) and len(ledger['usage_sha256'])==64
                and all(c in '0123456789abcdef' for c in ledger['usage_sha256'])):return None
        return max(1,ledger['actual_requests'])

    @staticmethod
    def _settle(state):
        """Keep all calls and original reservations; release only known unused time.

        A failed candidate still consumed its invocation. A missing or ambiguous
        provider return keeps its entire reservation. Outer setup/collection time
        is not the provider's execution time. Monetary/token caps are not changed.
        """
        used={'model_calls':0,'model_seconds':0.,'review_calls':0}
        for item in state['reservations']:
            if item['kind']=='review':
                used['review_calls']+=1
                continue
            receipt=item.get('evidence',{})
            cap=item.get('request_cap')
            if cap is None:used['model_calls']+=1
            else:
                actual=Budget._figure_calls(receipt,cap)
                accounted=actual if actual is not None else cap
                used['model_calls']+=accounted
                item['accounted_requests']=accounted
                item['released_unused_requests']=cap-accounted
            elapsed=None
            if item['state']=='failed_before_dispatch' and Budget._no_dispatch(receipt):
                item['accounted_seconds']=0.
                item['released_unused_seconds']=item['seconds']
                item['accounting_basis']='adapter-owned setup failure before session.run; failed attempt retained; no native terminal claimed'
            native_known=(receipt.get('transport') not in {'app_server_dynamic','deepseek_harness_native'} or receipt.get('native_terminal_confirmed') is True)
            if (item['state']=='returned' or cap is not None and native_known) and native_known and receipt.get('route') in {'codex','deepseek_harness'}:
                try:
                    start=datetime.fromisoformat(receipt['started_at']);end=datetime.fromisoformat(receipt['finished_at'])
                    value=(end-start).total_seconds()
                    if start.tzinfo is not None and end.tzinfo is not None and math.isfinite(value) and value>=0:
                        elapsed=value
                except (KeyError,ValueError,TypeError):pass
            if elapsed is not None:
                item['accounted_seconds']=elapsed
                item['released_unused_seconds']=max(0.,item['seconds']-elapsed)
                item['accounting_basis']='provider receipt started_at/finished_at; original reservation retained'
            used['model_seconds']+=item.get('accounted_seconds',item['seconds'])
        state['reserved']=used

    def reconcile(self):
        with self.locked():
            state=json.loads(self.path.read_text());self._settle(state);self.write(state);return state
