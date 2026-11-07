// Local view adapters only: the saved plan and run remain the source of truth.
export type GenerationMode = 'definition' | 'planned' | 'actual';

export function inputReferences(step: any, mode: GenerationMode): [string, any][] {
  return Object.entries(mode !== 'definition' && step.bound_inputs ? step.bound_inputs : step.inputs || {});
}

export function datasetReference(input: any): {dataset_id: string; revision: number} | undefined {
  const ref = input?.kind === 'dataset' ? input.ref : input;
  return typeof ref?.dataset_id === 'string' && Number.isInteger(ref.revision) ? ref : undefined;
}

export function nodeEvidence(step: any, mode: GenerationMode, actual?: any) {
  if (mode === 'definition') return {kind: 'definition', label: '待保存定义', result: undefined};
  if (mode === 'planned') return {kind: step.reuse ? 'planned-reuse' : 'pending',
    label: step.reuse ? '核验复用 · 本计划尚未执行' : '待执行 · 尚无本次输出', result: undefined};
  const result = actual?.run?.result?.nodes?.[step.id];
  if (result) return {kind: 'result', label: result.run_id === actual.run.id ? '已登记核验输出' : '复用输出 · 查看原运行', result};
  const checkpoint = actual?.checkpoint?.nodes?.[step.id];
  if (checkpoint) return {kind: 'checkpoint', label: '步骤已完成 · 整轮未完成', result: checkpoint};
  return {kind: 'unverified', label: '尚无核验输出', result: undefined};
}

export function logicalSources(step: any, plan?: any): any[] {
  if (Array.isArray(step.logical_sources)) return step.logical_sources;
  if (Array.isArray(plan?.target_mappings)) return plan.target_mappings.flatMap((target: any) =>
    Object.entries(target.nodes || {}).filter(([, physical]) => physical === step.id).map(([local]) => ({
      recipe_ref: target.recipe_ref, recipe_sha256: target.recipe_sha256, node_id: local, role: step.role,
    })));
  return plan?.recipe_ref ? [{recipe_ref: plan.recipe_ref, recipe_sha256: plan.recipe_sha256, node_id: step.id, role: step.role}] : [];
}

export function datasetSources(steps: any[], mode: GenerationMode, datasets: any[]) {
  const sources = new Map<string, any>();
  for (const step of steps) for (const [alias, input] of inputReferences(step, mode)) {
    const ref = datasetReference(input);
    if (!ref) continue;
    const id = ref.dataset_id + '@' + ref.revision;
    const existing = sources.get(id);
    if (existing) {existing.consumers.push({node_id: step.id, alias}); continue;}
    const catalog = datasets.find(d => d.id === ref.dataset_id && d.revision === ref.revision);
    // A current catalog revision never fills in a missing historical snapshot.
    const bound = mode !== 'definition' && input.kind === 'dataset' ? input : undefined;
    sources.set(id, {id, ref, title: catalog?.title || ref.dataset_id,
      snapshot: bound ? bound.snapshot : catalog?.content?.snapshot,
      asset_sha256: bound ? bound.asset_sha256 : catalog?.content?.asset_sha256,
      contract: bound ? bound.contract : catalog?.content?.snapshot?.contract,
      consumers: [{node_id: step.id, alias}], frozen: !!bound});
  }
  return [...sources.values()];
}

export function fixedAssetUrl(sha: unknown): string | undefined {
  return typeof sha === 'string' && /^[a-f0-9]{64}$/.test(sha) ? '/api/assets/' + sha : undefined;
}

export async function readFixedAsset(sha: string, fetcher: typeof fetch = fetch, subtle: SubtleCrypto = globalThis.crypto.subtle) {
  const url = fixedAssetUrl(sha);
  if (!url) throw new Error('缺少有效的固定素材 SHA-256，不能读取。');
  const response = await fetcher(url, {method: 'GET', credentials: 'same-origin'});
  if (!response.ok) throw new Error('固定素材不可访问（HTTP ' + response.status + '）。');
  const bytes = await response.arrayBuffer();
  if (bytes.byteLength > 16 * 1024 * 1024) throw new Error('素材超过当前 16 MiB 查看范围。');
  const hash = [...new Uint8Array(await subtle.digest('SHA-256', bytes))].map(x => x.toString(16).padStart(2, '0')).join('');
  if (hash !== sha) throw new Error('当前素材字节与固定 SHA-256 不一致，未显示为有效输出。');
  return {text: new TextDecoder('utf-8', {fatal: true}).decode(bytes), bytes: bytes.byteLength};
}
