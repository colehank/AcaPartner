"""Explicit, fresh-only Harness figure profile preparation; no agent or API call.

This private provider feature does not change the historical five-tool profile.
An inspectable profile is not account, disclosure, or spending authorization.
"""
from __future__ import annotations

from research_partner.resources import resource_path
import copy
import json
import math
import os
import stat
import shutil
import subprocess
import time
from pathlib import Path

from research_partner.integrations.mcp_workbench import TOOLS
from research_partner.storage.store import digest, encoded, require

FEATURE = "deepseek_task_figure_tools_v1"
TRANSPORT = "deepseek_harness_native"
AUTHORITY_CONTRACT = "task_lease_parent_budget_egress_v1"
LOCK_SHA256 = "a85eca55df1d7f4659acfec7c563c00c01c649f3ca1c2b76785de131acc1cdb2"
NATIVE = resource_path("agent_runtime")
DISABLED = ("llm-retry", "session-title-llm", "session-log-deepseek",
            "plugin-package-inventory-deepseek", "session-telemetry-otel",
            "llm-pi-ai", "web-search-deepseek")


def _number(value, cap):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value <= cap


def _reference(value):
    return (isinstance(value, str) and 0 < len(value.strip()) <= 4096
            and value.strip() != "User authorized provider in local config")


def _sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _identity(value):
    return isinstance(value, str) and 0 < len(value) <= 200 and all(c in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.:-" for c in value)


def catalogs(runtime, task=None):
    """Use the original catalog and its JS mechanical projection, not a new schema.

    The subprocess performs only local JSON projection. It imports no Harness
    agent, provider or credentials and cannot dispatch a model request.
    """
    raw = encoded([t for t in TOOLS if t["name"] in {"read_figure_context", "create_main_figure"}])
    script = """import fs from 'node:fs'; import {createHash} from 'node:crypto';
import {projectNativeCatalog,createFigureTools} from %s;
const canonical=v=>Array.isArray(v)?'['+v.map(canonical).join(',')+']':v&&typeof v==='object'?'{'+Object.keys(v).sort().map(k=>JSON.stringify(k)+':'+canonical(v[k])).join(',')+'}':JSON.stringify(v);
const input=JSON.parse(fs.readFileSync(0,'utf8')), projected=projectNativeCatalog(JSON.parse(input.catalogJson));
if(input.task){const task=input.task,plan=task.payload.context.figure_composition;
createFigureTools({taskId:task.id,projectId:task.project_id,planSha256:plan.sha256,fixedSources:plan.fixed_sources,request:plan.request,catalogJson:input.catalogJson,
client:{call:()=>{throw new Error('preflight cannot call service')}},checkAuthority:()=>{throw new Error('preflight cannot authorize')}});}
process.stdout.write(JSON.stringify({declarations:projected,sha256:createHash('sha256').update(canonical(projected)).digest('hex')}));
""" % json.dumps((NATIVE / "figure-tools.mjs").as_uri())
    run = subprocess.run([str(runtime / "node-v24.21.0-linux-x64/bin/node"), "--input-type=module", "-e", script], input=encoded({"catalogJson": raw, **({"task": task} if task else {})}), capture_output=True, text=True, timeout=10)
    require(run.returncode == 0, "原生工具声明投影不能加载；未派发", "provider_missing", 503)
    projection = json.loads(run.stdout)
    return {"raw_json": raw, "sha256": digest(raw.encode()),
            "native_declarations": projection["declarations"],
            "native_declarations_sha256": projection["sha256"],
            "native_schema_is_projection": True}


def definition(config):
    """Pure local preflight, suitable before any parent/provider reservation."""
    require(config.get("route") == "deepseek_harness" and config.get("transport") == TRANSPORT
            and config.get("figure_profile") == FEATURE,
            "需要显式两工具Harness主图profile；不回退旧科研profile", "provider_missing", 503)
    require(_reference(config.get("authorization_reference")),
            "缺少本任务当前账号/费用授权引用；不能回退旧授权文本", "authorization_required", 403)
    model = config.get("model")
    require(_identity(model), "需要明确模型身份，不能自动改模型", "provider_missing", 503)
    require(type(config.get("max_requests")) is int and 1 <= config["max_requests"] <= 4
            and type(config.get("max_output_tokens")) is int and 1 <= config["max_output_tokens"] <= 8192
            and type(config.get("max_request_bytes")) is int and 1 <= config["max_request_bytes"] <= 262144
            and _number(config.get("timeout_seconds"), 600), "主图请求/输出/上下文/时间必须在有界范围")
    require(config.get("budget_mode") == "capped" and config.get("uncapped_spending_authorized", False) is False
            and _number(config.get("budget_usd"), float("inf")), "需要明确有限USD上限；不能沿用旧uncapped科研授权", "authorization_required", 403)
    rates = config.get("rates_usd_per_million")
    require(isinstance(rates, dict) and set(rates) == {"input_miss", "output"}
            and all(_number(v, float("inf")) for v in rates.values())
            and _reference(config.get("pricing_reference")), "需要显式规划费率与来源；不是已核实账单", "authorization_required", 403)
    require(_number(config.get("deadline"), float("inf")) and config["deadline"] > time.time(), "原窗口已截止；不重置", "budget_exhausted", 409)
    require(config.get("authority_contract") == AUTHORITY_CONTRACT, "当前Task/父额度/外发许可probe尚未接通", "provider_missing", 503)
    require(config.get("fresh_only") is True and not any(config.get(k) for k in ("resume_session_id", "resumeSessionId", "checkpoint", "resumed_from")), "此profile不允许隐式恢复或重开未知任务", "provider_checkpoint_missing", 503)
    runtime = Path(config.get("runtime", ""))
    require(runtime.is_absolute() and runtime.is_dir() and config.get("expected_lock_sha256") == LOCK_SHA256,
            "需要明确锁定的既有Harness运行时", "provider_missing", 503)
    lock = runtime / "app/package-lock.json"
    require(lock.is_file() and digest(lock.read_bytes()) == LOCK_SHA256, "Harness依赖锁身份已改变", "provider_missing", 503)
    receipt = json.loads((runtime / "install-receipt.json").read_text())
    require(receipt.get("status") == "installed_version_probe_passed" and receipt.get("package_lock_sha256") == LOCK_SHA256,
            "锁环境缺少版本证据", "provider_missing", 503)
    catalog = catalogs(runtime)
    modules = {name: digest((NATIVE / name).read_bytes()) for name in
               ("figure-plugin.mjs", "figure-tools.mjs", "figure-host.mjs", "figure-host-plugin.mjs",
                "figure-launch.py", "acaworker-core.mjs", "native-session-driver.mjs")}
    result = {"feature": FEATURE, "transport": TRANSPORT, "route": "deepseek_harness",
              "provider": "deepseek-official", "model": model, "effective_backend_version": None,
              "runtime": str(runtime.resolve()), "runtime_lock_sha256": LOCK_SHA256,
              "catalog_sha256": catalog["sha256"], "native_declarations_sha256": catalog["native_declarations_sha256"],
              "native_schema_is_projection": True, "modules": modules,
              **{k: copy.deepcopy(config[k]) for k in ("authorization_reference", "max_requests", "max_output_tokens", "max_request_bytes", "timeout_seconds", "deadline", "budget_mode", "budget_usd", "rates_usd_per_million", "pricing_reference", "authority_contract", "fresh_only")},
              "max_tool_calls": 8, "retry_max": 0, "native_context_window": 262144,
              "accounting_units": {"parent": "reserved_native_stream_requests_and_actual_execution_seconds; failed_zero_stream_attempt_counts_once; unknown_requests_remain_reserved",
                                   "native": "each_llm_stream_request_with_monotonic_reservations"}}
    def wire(v):
        if type(v) is float and v.is_integer(): return int(v)
        if isinstance(v, dict): return {k: wire(x) for k, x in v.items()}
        if isinstance(v, list): return [wire(x) for x in v]
        return v
    result = wire(result)
    return {**result, "sha256": digest(result)}


def _plan(task, frozen, *, fresh=True):
    # Existing public Task/checkpoint fields, not a second resume protocol.
    # A fresh directory alone cannot turn an old unknown attempt into a new one.
    if fresh:
        result = task.get("result") or {}
        require(not result.get("provider") and not result.get("details", {}).get("provider_checkpoint")
                and not any(step.get("step_key") == "model" and
                            (step.get("data", {}).get("provider") or
                             step.get("data", {}).get("dispatch_continuity", {}).get("requires_checkpoint"))
                            for step in task.get("steps", [])),
                "已有提供者/未知checkpoint仅可零调用核对；不能换新目录隐式重开", "provider_checkpoint_missing", 503)
    plan = task.get("payload", {}).get("context", {}).get("figure_composition")
    require(task.get("payload", {}).get("kind") == "figure_composition" and isinstance(plan, dict)
            and plan.get("native_transport") == TRANSPORT and plan.get("native_definition") == frozen,
            "Task未固定此模型/profile；不能切换旧任务", "provider_checkpoint_missing", 503)
    require(plan.get("sha256") == digest({k: v for k, v in plan.items() if k != "sha256"}), "固定计划SHA不符", "integrity", 409)
    require(_identity(task.get("id")) and _identity(task.get("project_id")) and plan.get("request", {}).get("project_id") == task["project_id"], "需要准确Task与project身份", "integrity", 409)
    require(plan.get("max_tool_calls") == 8 and _sha(plan.get("egress_sha256")), "固定外发/工具权限不完整", "integrity", 409)
    refs = plan.get("fixed_sources")
    require(isinstance(refs, list) and 1 <= len(refs) <= 24 and all(isinstance(r, dict) and _identity(r.get("id")) and type(r.get("revision")) is int and r["revision"] > 0 and _sha(r.get("sha256")) for r in refs), "需要真实保存版来源pin", "integrity", 409)
    keys = [(r["id"], r["revision"]) for r in refs]
    require(len(keys) == len(set(keys)), "来源pin不能重复", "integrity", 409)
    budget = task["payload"].get("budget", {})
    require(type(budget.get("max_model_calls")) is int and frozen["max_requests"] <= budget["max_model_calls"]
            and _number(budget.get("timeout_seconds"), 600) and frozen["timeout_seconds"] <= budget["timeout_seconds"], "原Task不能扩请求/执行额度", "budget_exhausted", 409)
    return copy.deepcopy(plan)


def guard(task, config):
    frozen = definition(config)
    require(config.get("authorized") is True, "此账号/外发/费用路线尚未获当前明确许可；未派发", "authorization_required", 403)
    plan = _plan(task, frozen)
    catalogs(Path(frozen["runtime"]), task)
    return plan


def guard_saved(task, config):
    """Same frozen protocol for zero-call reads; never a dispatch permission."""
    frozen=definition(config)
    require(config.get('authorized') is True,'当前模型/外发授权已撤回','authorization_required',403)
    plan=_plan(task,frozen,fresh=False)
    catalogs(Path(frozen['runtime']),task)
    return plan


def prepare(instance, task, config):
    """Write an inspectable new private instance; never reads credentials.

    approved remains false unless root provides current explicit authorization.
    The supplied fresh launcher is not invoked here. Inspection is possible
    without credentials or approval; actual provider/Store checks remain root
    integration responsibilities.
    """
    instance = Path(instance).absolute()
    require(not instance.exists() and not instance.is_symlink(), "必须使用全新隔离实例；未知结果不能重开", "provider_checkpoint_missing", 503)
    frozen = definition(config); plan = _plan(task, frozen)
    catalog = catalogs(Path(frozen["runtime"]), task)
    now = time.time()
    remaining = min(frozen["timeout_seconds"], frozen["deadline"] - now)
    require(remaining > 0, "原父窗口已截止", "budget_exhausted", 409)
    scope = {"version": 1, "task_id": task["id"], "project_id": task["project_id"],
             "plan_sha256": plan["sha256"], "egress_sha256": plan["egress_sha256"],
             "fixed_sources": plan["fixed_sources"], "request": plan["request"], "definition": frozen}
    contract_raw = encoded(scope).encode(); contract_sha = digest(contract_raw)
    instance.mkdir(parents=True, mode=0o700); instance.chmod(0o700)
    require(not instance.stat().st_mode & 0o077, "文件系统必须支持private实例", "forbidden", 403)
    for dirname in ("plugin", "control", "capsule", "home/profiles/acaworker-headless", "presets/figure-task"):
        (instance / dirname).mkdir(parents=True, mode=0o700)
    (instance / "node_modules").symlink_to(Path(frozen["runtime"]) / "app/node_modules", target_is_directory=True)
    for filename in frozen["modules"]:
        shutil.copyfile(NATIVE / filename, instance / "plugin" / filename)
    shutil.copyfile(NATIVE / "figure-launch.py", instance / "launch.py")
    def write(relative, value):
        p = instance / relative; p.write_text(value, encoding="utf-8"); p.chmod(0o600)
    write("control/scope.json", contract_raw.decode())
    authorization = {"approved": config.get("authorized") is True, "authorization_reference": frozen["authorization_reference"],
                     "contract_sha256": contract_sha, "expires_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(min(frozen["deadline"], now + remaining))), "no_expiry_authorized": False,
                     "model": frozen["model"], "budget_mode": "capped", "budget_usd": frozen["budget_usd"], "uncapped_spending_authorized": False,
                     "max_requests": frozen["max_requests"], "max_output_tokens": frozen["max_output_tokens"], "max_request_bytes": frozen["max_request_bytes"],
                     "rates_usd_per_million": frozen["rates_usd_per_million"], "pricing_reference": frozen["pricing_reference"],
                     "disclosure_classes": ["fixed_figure_context"], "task_id": task["id"], "project_id": task["project_id"], "plan_sha256": plan["sha256"], "egress_sha256": plan["egress_sha256"]}
    write("control/authorization.json", encoded(authorization) + "\n")
    plugin_config = {"feature": FEATURE, "transport": TRANSPORT, "definition": frozen,
                     "taskId": task["id"], "projectId": task["project_id"], "planSha256": plan["sha256"], "egressSha256": plan["egress_sha256"],
                     "fixedSources": plan["fixed_sources"], "request": plan["request"], "catalogJson": catalog["raw_json"],
                     "controlRoot": str(instance / "control"), "contractSha256": contract_sha,
                     "deadlineMs": min(frozen["deadline"], now + remaining) * 1000}
    write("control/figure-plugin.json", encoded(plugin_config) + "\n")
    patch = [{"id": n, "disabled": True} for n in DISABLED] + [
        {"id": "tools", "config": {"mode": "native", "maxParallelSubCalls": 1}},
        {"id": "system-prompt", "config": {"includeHarnessIdentity": True, "includeRuntimeContext": False}},
        {"id": "agent-default-model", "config": {"provider": "deepseek-official", "model": frozen["model"]}},
        {"id": "llm-deepseek", "config": {"apiKeyEnv": "DEEPSEEK_API_KEY", "baseURL": "https://api.deepseek.com", "thinking": "disabled", "reasoningEffort": "off", "maxTokens": frozen["max_output_tokens"], "defaultContextWindow": 262144, "streamIdleTimeoutMs": min(120000, int(remaining * 1000)), "retryPolicy": {"mode": "normal", "maxRetries": 0}, "models": [{"id": frozen["model"], "name": frozen["model"] + " (requested identity; backend version requires actual observation)", "contextWindow": 262144, "maxTokens": frozen["max_output_tokens"]}]}},
        {"id": "agent-presets", "config": {"default": "figure-task", "roots": [{"path": str(instance / "presets"), "trust": "system"}], "includeShippedRoot": False, "includeUserRoot": False}},
        {"insert": [{"id": "acaworker-figure-task", "name": str(instance / "plugin/figure-plugin.mjs"), "config": plugin_config}]}]
    # JSON is valid YAML and retains exact finite values without another loader.
    patch_raw = encoded(patch) + "\n"
    write("home/profiles/acaworker-headless/cordis.patch.yml", patch_raw)
    write("control/profile-base.yml", patch_raw)
    write("home/profiles/acaworker-headless/package.json", encoded({"name": "acaworker-headless", "private": True, "dsh": {"profile": {"bundles": ["@deepseek-ai/dsh-base"], "patchReload": "startup"}}}) + "\n")
    write("presets/figure-task/preset.yml", encoded({"name": "Fixed figure Task", "description": "Two typed tools, saved fixed sources and an unadopted composition candidate only.", "order": 1}) + "\n")
    write("presets/figure-task/agent.cordis.yml", encoded([{"id": "persona", "name": "@deepseek-ai/dsh-persona", "config": {"prefix": "AcaWorker figure Task: use only the two scoped domain tools. Preserve scientific uncertainty."}}]) + "\n")
    from research_partner.domains.collaboration.commission import candidate_schema
    prompt = "Use only the two native typed tools. First read EVERY fixed saved figure context with its exact id and revision; then create the exact unadopted composition candidate ONCE. No scientific confirmation, computations, shell, adoption or permission grants. Return only a compact authored note JSON referring to the actual saved candidate ID and limits after the tools succeed.\n" + encoded({"task_id": task["id"], "project_id": task["project_id"], "request": {**plan["request"], "request_key": task["id"] + ":composition"}, "source_pins": plan["fixed_sources"]}) + "\nREQUIRED NOTE OUTPUT SCHEMA:\n" + candidate_schema('note', task)
    write("control/prompt.txt", prompt + "\n")
    record = {"feature": FEATURE, "transport": TRANSPORT, "instance": str(instance), "runtime": frozen["runtime"], "profile": str(instance / "home/profiles/acaworker-headless"), "definition": frozen,
              "contract_sha256": contract_sha, "profile_sha256": digest(patch_raw.encode()), "plugin_config": str(instance / "control/figure-plugin.json"),
              "authorization": str(instance / "control/authorization.json"), "prompt_path": str(instance / "control/prompt.txt"), "remaining_seconds": remaining,
              "fresh_only": True, "native_execution_verified": False, "native_runtime_tested": False,
              "launch_path": str(instance / "launch.py"), "capsule": str(instance / "capsule"),
              "missing_root_hooks": ["provider_parent_accounting", "independent_Store_verifier", "current_account_API_finite_fee_permission"],
              "actual_provider_bill_usd": None}
    write("preparation.json", encoded(record) + "\n")
    return record


def load_current_provider(filename, budget):
    """Read one explicit private current config; never read an account key."""
    from research_partner.providers.registry import _controlled_file
    path=Path(filename)
    require(path.is_absolute(),'需要明确当前private提供者文件','authorization_required',403)
    stamp=path.lstat()
    require(stat.S_ISREG(stamp.st_mode) and stamp.st_uid==os.getuid()
            and stat.S_IMODE(stamp.st_mode)==0o600 and 0<stamp.st_size<=131072,
            '提供者配置需要private regular0600文件','authorization_required',403)
    config=json.loads(_controlled_file(path.parent,path,131072))
    require(isinstance(config,dict) and config.get('authorized') is True,'缺少当前明确账号费用授权','authorization_required',403)
    frozen=definition(config);parent=budget.check();scope=budget.native_permission(parent,frozen)
    require(scope is not None,'缺少同父任务当前明确API/有限费用许可','authorization_required',403)
    require(frozen['max_requests']<=budget.remaining(parent,'model_calls')
            and frozen['timeout_seconds']<=budget.remaining(parent,'model_seconds'),
            '现有父调用/时间额度不足','budget_exhausted',409)
    return config
