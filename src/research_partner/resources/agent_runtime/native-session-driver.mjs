// Drive the installed native Agent registry; no model loop or API client.
import fs from 'node:fs';
import path from 'node:path';
import { randomUUID } from 'node:crypto';
import { installModelSelection } from '@deepseek-ai/dsh-agent';
import { createUserMessage } from '@deepseek-ai/dsh-llm';

export const name = 'acaworker-native-session-driver';
export const inject = ['agentDefaultModel', 'agents', 'sessions'];
const FIGURE_FEATURE = 'deepseek_task_figure_tools_v1';

function save(filename, value) {
  fs.mkdirSync(path.dirname(filename), { recursive: true });
  const temporary = `${filename}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, JSON.stringify(value, null, 2) + '\n');
  fs.renameSync(temporary, filename);
}

export function apply(ctx, config) {
  const exit = ctx.get('appExit');
  if (!exit) throw new Error('Native session driver requires launcher appExit');
  async function run() {
    await ctx.get('loader')?.await();
    const figureProfile = config.feature === FIGURE_FEATURE;
    const figureTools = figureProfile ? ctx.get('figureTaskTools') : null;
    if (figureProfile) {
      if (config.resumeSessionId !== undefined && config.resumeSessionId !== null) throw new Error('Figure task driver requires a fresh agents.create; resume is disabled');
      if (typeof figureTools?.bindAgent !== 'function' || typeof figureTools?.snapshot !== 'function') throw new Error('Figure task driver requires figureTaskTools bindAgent and snapshot');
    }
    const task = fs.readFileSync(config.promptPath, 'utf8');
    if (!task.trim()) throw new Error('A nonempty task is required');
    const selection = ctx.get('agentDefaultModel').currentSelection();
    const options = {
      agentOptions: { provider: selection.provider, model: selection.model },
      setup: agentCtx => { installModelSelection(agentCtx, { current: selection, assembled: undefined }); },
    };
    const handle = config.resumeSessionId
      ? await ctx.get('agents').resume({ ...options, resumeSessionId: config.resumeSessionId })
      : await ctx.get('agents').create({ ...options, sessionId: `session-${randomUUID()}`, meta: { cwd: process.cwd() } });
    const { agent } = handle;
    const figureSnapshot = () => {
      if (ctx.get('figureTaskTools') !== figureTools) throw new Error('Figure task binding service changed');
      const snapshot = figureTools.snapshot();
      if (snapshot?.feature !== FIGURE_FEATURE || snapshot.session_id !== agent.id
          || snapshot.binding_proof?.native_api !== 'agents.create' || snapshot.binding_proof.resumed_from !== null) throw new Error('Figure task snapshot does not bind the authoritative fresh Agent return');
      return snapshot;
    };
    let binding = null;
    if (figureProfile) {
      if (!agent || typeof agent.id !== 'string' || !agent.id || !agent.session
          || typeof agent.whenIdle !== 'function' || typeof agent.followup !== 'function') throw new Error('Figure task agents.create returned an invalid Agent');
      if (ctx.get('figureTaskTools') !== figureTools) throw new Error('Figure task binding service changed during agents.create');
      await figureTools.bindAgent(agent, { native_api: 'agents.create', resumed_from: null });
      binding = figureSnapshot();
    }
    const receipt = {
      native_api: config.resumeSessionId ? 'agents.resume' : 'agents.create',
      session_id: agent.id, resumed_from: config.resumeSessionId ?? null,
      loaded_seq: agent.session.seq, started_at: new Date().toISOString(),
      provider: selection.provider, model: selection.model, phase: 'loaded',
      ...(figureProfile ? { feature: FIGURE_FEATURE, identity_source: 'authoritative_agents_create_return', figure_task_binding: binding } : {}),
    };
    save(config.receiptPath, receipt);
    await agent.whenIdle();
    const firstSeq = agent.session.seq;
    let checkpoint = null;
    const calls = new Map();
    const stopObserve = config.checkpointAfterTool ? ctx.on('session/event', (session, event) => {
      if (session !== agent.session || checkpoint) return;
      if (event.type === 'tool/call') calls.set(event.data.callId, event.data.name);
      if (event.type !== 'tool/result') return;
      const blocks = event.data.message.content.filter(b => b.type === 'tool-result');
      const completed = blocks.find(b => !b.isError && calls.get(b.toolCallId) === config.checkpointAfterTool);
      if (!completed) return;
      checkpoint = { after_tool: config.checkpointAfterTool, tool_call_id: completed.toolCallId, result_seq: event.seq };
      agent.cancel({ kind: 'hook', reason: 'Authorized native-session interruption test after a completed tool result' });
    }) : () => {};
    agent.followup(createUserMessage({ content: [{ type: 'text', text: task }], source: { kind: 'user' } }));
    await agent.whenIdle();
    stopObserve();
    await ctx.get('sessions').flush(agent.session);
    let reason = null, text = '';
    for (let seq = firstSeq; seq < agent.session.seq; seq++) {
      const event = agent.session.eventAt(seq);
      if (!event) throw new Error(`Cannot read durable event ${seq}`);
      if (event.type === 'turn/end') reason = event.data.reason;
      if (event.type === 'assistant/message') {
        const latest = event.data.message.content.filter(b => b.type === 'text').map(b => b.text).join('');
        if (latest) text = latest;
      }
    }
    Object.assign(receipt, { phase: checkpoint ? 'checkpoint_flushed' : 'flushed', first_seq: firstSeq, final_seq: agent.session.seq, reason, checkpoint, finished_at: new Date().toISOString() });
    if (figureProfile) receipt.figure_task_binding = figureSnapshot();
    save(config.receiptPath, receipt);
    // The owning test runner terminates this process, then starts a separate
    // native resume process. This tests a durable application checkpoint, not a
    // power loss during an in-flight provider request or tool write.
    if (checkpoint) {
      const timer = setInterval(() => {}, 30000);
      ctx.on('dispose', () => clearInterval(timer));
      await new Promise(() => {});
    }
    process.stdout.write(text + '\n');
    if (reason?.kind !== 'completed') process.stderr.write(JSON.stringify(reason) + '\n');
    exit(reason?.kind === 'completed' ? 0 : 1);
  }
  run().catch(error => { process.stderr.write(`Native session driver: ${error.message}\n`); exit(1); });
}
