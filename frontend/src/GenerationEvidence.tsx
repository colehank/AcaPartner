import {useState} from 'react';
import {datasetReference, fixedAssetUrl, inputReferences, logicalSources, nodeEvidence, readFixedAsset, GenerationMode} from './GenerationEvidenceModel';
import './GenerationEvidence.css';

function Json({value, label}: {value: any; label?: string}) {
  return <pre aria-label={label}>{JSON.stringify(value, null, 2)}</pre>;
}

function AssetReader({sha, label}: {sha?: string; label: string}) {
  const [reading, setReading] = useState(false), [value, setValue] = useState<{text: string; bytes: number} | null>(null), [error, setError] = useState('');
  const url = fixedAssetUrl(sha);
  const load = async () => {
    if (!sha) return;
    setReading(true); setError(''); setValue(null);
    try {setValue(await readFixedAsset(sha));} catch (e) {setError(e instanceof Error ? e.message : String(e));}
    finally {setReading(false);}
  };
  return <div className="generation-asset-reader">
    {url ? <><button type="button" disabled={reading} onClick={load}>{reading ? '读取中…' : '查看固定文件：' + label}</button>
      <a href={url} target="_blank" rel="noreferrer">打开完整文件：{label}</a></> : <p>固定素材引用缺失，不能打开文件。</p>}
    {error && <p role="alert">{error}</p>}
    {value && <><p role="status">当前读取 {value.bytes} 字节，SHA-256 与固定引用一致。查看没有启动计算。</p>
      <pre className="generation-file-preview" aria-label={'固定文件内容：' + label}>{value.text.slice(0, 64000)}</pre>
      {value.text.length > 64000 && <p>此处显示前 64,000 个字符；完整内容可从文件链接查看。</p>}</>}
  </div>;
}

function Snapshot({snapshot, contract}: {snapshot?: any; contract?: any}) {
  const [all, setAll] = useState(false);
  const members: any[] | undefined = Array.isArray(snapshot?.members) ? snapshot.members : undefined;
  return <div className="generation-snapshot">
    <dl><dt>行数</dt><dd>{snapshot?.row_count ?? '未提供固定快照'}</dd>
      <dt>身份顺序摘要</dt><dd>{snapshot?.ordered_members_sha256 || '未提供'}</dd></dl>
    <details><summary>字段、身份与单位合同</summary><Json value={contract || snapshot?.contract} label="固定字段身份单位合同"/></details>
    {members && <details><summary>固定成员及顺序 · {members.length} 项</summary>
      <Json value={all ? members : members.slice(0, 100)} label="固定成员顺序"/>
      {members.length > 100 && <button type="button" onClick={() => setAll(!all)}>{all ? '仅看前 100 项' : '展开全部固定成员'}</button>}
      {!all && members.length > 100 && <p>当前显示前 100 项，尚未展示的成员仍保留在固定快照中。</p>}
    </details>}
  </div>;
}

function Sources({step, plan}: {step: any; plan?: any}) {
  const sources = logicalSources(step, plan);
  return sources.length ? <details open><summary>此计算对应的成果步骤 · {sources.length} 项</summary>
    <table><thead><tr><th>成果配方修订</th><th>逻辑步骤及职责</th><th>物理计算节点</th></tr></thead><tbody>
      {sources.map((source, index) => <tr key={source.recipe_ref?.id + '/' + source.node_id + '/' + index}>
        <td>{source.recipe_ref?.id} · r{source.recipe_ref?.revision}<small>{source.recipe_sha256}</small></td>
        <td>{source.node_id}<small>{source.role}</small></td><td>{step.id}</td></tr>)}
    </tbody></table>
    {sources.length > 1 && <p>这些成果步骤引用同一个物理计算节点；各自的配方修订与逻辑身份仍保留。是否实际执行，以运行回执为准。</p>}
  </details> : null;
}

function InputEvidence({alias, input, step, mode, actual}: {alias: string; input: any; step: any; mode: GenerationMode; actual?: any}) {
  const dataset = datasetReference(input), result = nodeEvidence(step, mode, actual).result;
  const upstream = !dataset && actual ? (actual.run?.result?.nodes?.[input.node_id] || actual.checkpoint?.nodes?.[input.node_id])?.outputs?.[input.output] : undefined;
  const sha = input.asset_sha256 || result?.actual_inputs?.[alias] || upstream?.asset_sha256;
  const declared = step.io?.inputs?.[alias], snapshot = input.snapshot || upstream?.snapshot;
  return <details open className="generation-input-evidence"><summary>输入 {alias} · {dataset ? dataset.dataset_id + ' · r' + dataset.revision : input.node_id + ' / ' + input.output}</summary>
    <p>{dataset ? '固定数据修订' : '登记上游输出'}{sha ? ' · 素材 SHA-256：' + sha : ' · 尚无已登记实际素材'}</p>
    <Snapshot key={sha || alias} snapshot={snapshot} contract={input.contract || declared}/>
    {sha && <AssetReader key={sha} sha={sha} label={'输入 ' + alias}/>}
    <details><summary>准确输入引用与执行回执</summary><Json value={{fixed_reference: input, actual_asset_sha256: result?.actual_inputs?.[alias]}}/></details>
  </details>;
}

export function GenerationEvidence({mode, plan, actual, selectedStep: requestedStep, selectedDataset, onSelectNode}: {
  mode: GenerationMode; plan?: any; actual?: any; selectedStep?: any; selectedDataset?: any; onSelectNode?: (id: string) => void;
}) {
  const frozen = mode === 'actual' ? actual?.run?.payload?.generation_plan || plan : plan;
  const selectedStep = mode !== 'definition' && Array.isArray(frozen?.nodes)
    ? frozen.nodes.find((node: any) => node.id === requestedStep?.id) : requestedStep;
  const evidence = selectedStep && nodeEvidence(selectedStep, mode, actual);
  const result = evidence?.result;
  const mappings: any[] = Array.isArray(frozen?.target_mappings) ? frozen.target_mappings : [];
  const describe = (ids: string[] = []) => ids.map(id => {
    const step = frozen?.nodes?.find((n: any) => n.id === id), sources = step ? logicalSources(step, frozen) : [];
    return <li key={id}>{onSelectNode ? <button type="button" onClick={() => onSelectNode(id)}>{id}</button> : id}
      {sources.length > 0 && <span> — {sources.map((s: any) => s.recipe_ref.id + ' r' + s.recipe_ref.revision + ' / ' + s.node_id).join('；')}</span>}</li>;
  });
  return <section className="generation-evidence" aria-label={mode === 'actual' ? '固定运行来源与输出证据' : '固定生成来源证据'}>
    {frozen && <details className="generation-plan-evidence"><summary>{mode === 'actual' ? '该历史运行的固定计划' : '待执行固定计划'} · 来源与变化集合</summary>
      <dl><dt>计划 SHA-256</dt><dd>{frozen.plan_hash}</dd>
        {actual && mode === 'actual' && <><dt>所选历史运行</dt><dd>{actual.run.id} · {actual.run.status}</dd></>}
        <dt>配方修订</dt><dd>{(frozen.recipe_refs || [frozen.recipe_ref]).filter(Boolean).map((r: any) => r.id + ' · r' + r.revision).join('；')}</dd></dl>
      <h4>计划登记的变化节点</h4>{frozen.changed?.length ? <ul>{describe(frozen.changed)}</ul> : <p>此计划未登记变化节点。</p>}
      <h4>计划待执行集合</h4>{frozen.pending?.length ? <ul>{describe(frozen.pending)}</ul> : <p>无待执行步骤。</p>}
      <h4>计划核验复用集合</h4>{frozen.reused?.length ? <ul>{describe(frozen.reused)}</ul> : <p>无复用步骤。</p>}
      {mode === 'actual' && <><h4>实际执行集合回执</h4>{Array.isArray(actual?.run?.result?.actual_dry_run_jobs)
        ? <Json value={{planned_jobs: actual.run.result.planned_jobs, actual_dry_run_jobs: actual.run.result.actual_dry_run_jobs, reused_nodes: actual.run.result.reused_nodes, output_checks: actual.run.result.output_checks}}/>
        : <p>尚无整轮执行集合回执；计划集合不表示已经运行。</p>}</>}
      {frozen.resume_from && <details><summary>从原运行接续的固定来源</summary><Json value={frozen.resume_from}/></details>}
      <details><summary>固定执行环境与锁引用</summary><Json value={frozen.environment}/></details>
    </details>}
    {mappings.length > 0 && <details className="generation-target-mappings"><summary>成果与共享计算对应 · {mappings.length} 个配方</summary>
      <table><thead><tr><th>成果配方</th><th>逻辑步骤</th><th>物理计算节点</th><th>输出来源运行</th></tr></thead><tbody>
        {mappings.flatMap(target => Object.entries(target.nodes || {}).map(([local, physical]: any) => {
          const targetResult = actual?.run?.result?.target_results?.find((t: any) => t.recipe_ref.id === target.recipe_ref.id && t.recipe_ref.revision === target.recipe_ref.revision)?.nodes?.[local];
          const physicalResult = actual?.run?.result?.nodes?.[physical];
          return <tr key={target.recipe_ref.id + '/' + local}><td>{target.title || target.recipe_ref.id}<small>{target.recipe_ref.id} · r{target.recipe_ref.revision}</small></td>
            <td>{local}</td><td>{onSelectNode ? <button type="button" onClick={() => onSelectNode(physical)}>{physical}</button> : physical}</td>
            <td>{mode === 'actual' ? targetResult?.run_id || physicalResult?.run_id || '尚无整轮输出' : '尚未执行本计划'}</td></tr>;
        }))}
      </tbody></table>
    </details>}
    {selectedDataset && <article aria-label="所选固定数据来源"><h3>{selectedDataset.title} · r{selectedDataset.ref.revision}</h3>
      <p>{selectedDataset.frozen ? '来自此计划的固定输入绑定。' : '待执行定义引用的数据修订。'}数据身份：{selectedDataset.ref.dataset_id}</p>
      <p>素材 SHA-256：{selectedDataset.asset_sha256 || '此修订的固定素材尚未提供'}</p>
      <Snapshot key={selectedDataset.id + selectedDataset.asset_sha256} snapshot={selectedDataset.snapshot} contract={selectedDataset.contract}/>
      {selectedDataset.asset_sha256 && <AssetReader key={selectedDataset.asset_sha256} sha={selectedDataset.asset_sha256} label={selectedDataset.title}/>}
      <p>使用此数据的步骤：{selectedDataset.consumers.map((c: any) => c.node_id + ' / ' + c.alias).join('；')}</p>
    </article>}
    {selectedStep && <article aria-label="所选计算来源与实际输出"><h3>{selectedStep.id} · {selectedStep.role}</h3>
      <p role="status">{evidence?.label}{result?.run_id && ' · 输出来源运行：' + result.run_id}</p>
      <Sources step={selectedStep} plan={frozen}/>
      <h4>固定输入</h4>{inputReferences(selectedStep, mode).map(([alias, input]) => <InputEvidence key={selectedStep.id + '/' + alias + '/' + frozen?.plan_hash} alias={alias} input={input} step={selectedStep} mode={mode} actual={actual}/>)}
      <details open><summary>产生结果的代码与参数</summary><p>{selectedStep.script_snapshot?.relative_path || selectedStep.script}</p>
        {selectedStep.script_snapshot ? <><p>固定脚本 SHA-256：{selectedStep.script_snapshot.sha256}</p><pre className="generation-code-preview" aria-label="固定运行脚本源码">{selectedStep.script_snapshot.code}</pre></>
          : <p>此处是待保存定义；代码字节尚未由固定计划提供。</p>}
        <h4>实际配置键与参数</h4><Json value={{config_keys: selectedStep.config_keys, parameters: selectedStep.parameters}} label="固定运行参数"/>
        {result && <details><summary>输出回执绑定的脚本与参数</summary><Json value={{source_script_sha256: result.source_script_sha256, parameters: result.parameters, node_key: result.node_key, verified_at: result.verified_at}}/></details>}
      </details>
      <details><summary>声明的完整 I/O 合同</summary><Json value={selectedStep.io} label="完整输入输出合同"/></details>
      <h4>{evidence?.kind === 'checkpoint' ? '步骤检查点输出 · 整轮尚未完成' : '实际登记输出'}</h4>
      {result?.outputs ? Object.entries(result.outputs).map(([name, output]: any) => <details open key={name + output.asset_sha256}><summary>{name} · {output.snapshot?.row_count ?? '未知'} 行</summary>
        <p>输出来源运行：{result.run_id} · 素材 SHA-256：{output.asset_sha256}</p>
        <Snapshot snapshot={output.snapshot} contract={result.io?.outputs?.[name] || selectedStep.io?.outputs?.[name]}/>
        <AssetReader sha={output.asset_sha256} label={'输出 ' + name}/>
      </details>) : <p>尚无此节点的实际登记输出。声明的输出文件和计划复用不会替代本次运行回执。</p>}
      {mode === 'actual' && result && <p>{evidence?.kind === 'checkpoint' ? '此输出属于已核验步骤检查点。' : '此输出保留其来源运行身份。'}执行核验与科学批准、成果采用分别记录；当前来源查看不采用成果。</p>}
    </article>}
    {!selectedStep && !selectedDataset && <p>选择图中的数据或计算节点，查看固定修订、代码、参数、I/O 和实际文件。</p>}
  </section>;
}
