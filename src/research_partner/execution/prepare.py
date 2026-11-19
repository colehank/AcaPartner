#!/usr/bin/env python3
"""Create an isolated native DSH profile and a bounded public/synthetic task.

This writes inspectable configuration only: no install, network or model call.
The target is a new private instance directory; the runtime is separately pinned.
"""
from __future__ import annotations
from research_partner.resources import resource_path
import argparse
import hashlib
import json
from pathlib import Path
import shutil


def prepare(instance: Path, capsule: Path, runtime: Path) -> dict:
    if instance.exists() or instance.is_symlink():
        raise FileExistsError(instance)
    contract = capsule / "task.json"
    data = json.loads(contract.read_text())
    if not isinstance(data.get("evidence"), list):
        raise ValueError("Capsule task.json must list evidence")
    instance.mkdir(parents=True, mode=0o700)
    instance.chmod(0o700)
    if instance.stat().st_mode & 0o077:
        raise PermissionError("The chosen filesystem does not enforce private directories")
    source = resource_path("agent_runtime")
    plugin = instance / "plugin"
    shutil.copytree(source, plugin)
    # Native ESM dependencies resolve through the pinned runtime, not global npm.
    (instance / "node_modules").symlink_to(runtime / "app/node_modules", target_is_directory=True)
    home = instance / "home"
    profile = home / "profiles/acaworker"
    preset = instance / "presets/acaworker"
    control = instance / "control"
    for p in [profile, preset, control]:
        p.mkdir(parents=True, mode=0o700)
    q = json.dumps
    for name, bundles in [
        ("acaworker", ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"]),
        ("acaworker-headless", ["@deepseek-ai/dsh-base"]),
    ]:
        target = home / "profiles" / name
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
        (target / "package.json").write_text(q({"name": name, "private": True, "dsh": {"profile": {"bundles": bundles, "patchReload": "startup"}}}, indent=2) + "\n")
    disabled = ["llm-retry", "session-title-llm", "session-log-deepseek", "plugin-package-inventory-deepseek", "session-telemetry-otel", "llm-pi-ai", "web-search-deepseek"]
    patch = "\n".join(f"- id: {name}\n  disabled: true" for name in disabled)
    patch += f"""
- id: tools
  config:
    mode: native
    maxParallelSubCalls: 1
- id: system-prompt
  config:
    includeHarnessIdentity: true
    includeRuntimeContext: false
    personaPrefix: You are AcaWorker, a critical research collaborator.
- id: agent-default-model
  config:
    provider: deepseek-official
    model: deepseek-flash
- id: llm-deepseek
  config:
    apiKeyEnv: DEEPSEEK_API_KEY
    baseURL: https://api.deepseek.com
    thinking: disabled
    reasoningEffort: off
    maxTokens: 8192
    defaultContextWindow: 65536
    streamIdleTimeoutMs: 120000
    retryPolicy:
      mode: normal
      maxRetries: 0
    models:
      - id: deepseek-flash
        name: DeepSeek Flash (provider alias; backend version not pinned)
        contextWindow: 65536
        maxTokens: 8192
- id: agent-presets
  config:
    default: acaworker
    includeShippedRoot: false
    includeUserRoot: false
    roots:
      - path: {q(str(instance / 'presets'))}
        trust: system
- insert:
    - id: acaworker-research
      name: {q(str(plugin / 'acaworker-plugin.mjs'))}
      config:
        capsuleRoot: {q(str(capsule))}
        controlRoot: {q(str(control))}
        restrictToolCatalog: true
"""
    (profile / "cordis.patch.yml").write_text(patch)
    (control / "profile-base.yml").write_text(patch)
    (home / "profiles/acaworker-headless/cordis.patch.yml").write_text(patch)
    (preset / "preset.yml").write_text("name: AcaWorker 科研协作\ndescription: 从限定证据制作可审阅候选，记录反馈与真实资源使用。\norder: 1\n")
    (preset / "agent.cordis.yml").write_text("- id: persona\n  name: '@deepseek-ai/dsh-persona'\n  config:\n    prefix: You are AcaWorker, a critical research collaborator.\n")
    authorization = {
        "approved": False, "authorization_reference": None,
        "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
        "expires_at": None, "no_expiry_authorized": False,
        "model": "deepseek-flash", "budget_mode": "capped",
        "budget_usd": 0, "uncapped_spending_authorized": False,
        "max_requests": 12, "max_output_tokens": 8192,
        "max_request_bytes": 262144, "disclosure_classes": [],
        "rates_usd_per_million": {"input_miss": 0.30, "output": 1.20},
        "pricing_source": "https://api-docs.deepseek.com/quick_start/pricing/",
        "pricing_verified_date": "2026-09-14",
        "limit": "Planning reservations; provider billing remains unverified. No automatic retries or wallet-cap guarantee."
    }
    (control / "authorization.json").write_text(q(authorization, indent=2) + "\n")
    launch = instance / "launch.py"
    shutil.copyfile(source / "native-launch.py", launch)
    record = {"instance": str(instance), "runtime": str(runtime), "capsule": str(capsule), "profile": str(profile), "headless_profile": str(home / "profiles/acaworker-headless"), "launch": str(launch), "credential_file": str(control / "api-key.txt"), "authorization": str(control / "authorization.json"), "requested_model": "deepseek-flash", "effective_backend_version": None, "native_runtime_tested": False, "live_model_calls": 0}
    (instance / "preparation.json").write_text(q(record, indent=2) + "\n")
    return record


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--instance", type=Path, required=True)
    p.add_argument("--capsule", type=Path, required=True)
    p.add_argument("--runtime", type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(prepare(a.instance.expanduser().absolute(), a.capsule.resolve(), a.runtime.expanduser().absolute()), indent=2))
