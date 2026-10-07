import test from 'node:test';
import assert from 'node:assert/strict';
import { activityFromResult, activityItem, updateActivity } from '../frontend/js/activity.js';

globalThis.window = { location: { protocol: 'http:', origin: 'http://offline.local', search: '' } };
const { api, ApiError } = await import('../frontend/js/api.js');

const rich = [
  { type: 'run_started', execution_model: 'single_agent', available_tool_count: 7 },
  { type: 'activity', activity_id: 'A1', iteration: 1, tool_name: 'code_search', state: 'started',
    purpose: 'Locate source', target: { query: '配置', artifact_kind: 'project_code' } },
  { type: 'evidence_added', evidence_id: 'E1', kind: 'project_code', path: 'src/service.py', start_line: 2, end_line: 8 },
  { type: 'activity', activity_id: 'A1', iteration: 1, tool_name: 'code_search', state: 'completed',
    purpose: 'Locate source', target: { query: '配置' },
    result_summary: { match_count: 1, top_paths: ['src/service.py'], truncated: false }, evidence_ids_added: ['E1'] },
  { type: 'verification', state: 'blocked', iteration: 2, missing_evidence_kinds: ['project_test'] },
];

function install(events, { schema = 'engineering_query_stream_v2', chunked = false, onFetch = () => {} } = {}) {
  const body = ': keep-alive\r\n\r\n' + events.map(event => 'data: ' + JSON.stringify(event) + '\r\n\r\n').join('');
  const bytes = new TextEncoder().encode(body);
  let offset = 0;
  globalThis.fetch = async (url, options) => {
    onFetch(url, options);
    const stream = new ReadableStream({ pull(controller) {
      if (offset === bytes.length) return controller.close();
      const end = chunked ? Math.min(offset + 7, bytes.length) : bytes.length;
      controller.enqueue(bytes.slice(offset, end));
      offset = end;
    } });
    return new Response(stream, { headers: { 'Content-Type': 'text/event-stream',
      ...(schema ? { 'X-Engineering-Stream-Schema': schema } : {}) } });
  };
}

test('HTML calls the project-bound v2 conversation endpoint and decodes all rich events', async () => {
  const all = [...rich, { type: 'answer_start' }, { type: 'answer_delta', delta: '结论 [E1]' },
    { type: 'final', result: { status: 'completed', answer: '结论 [E1]', activity: rich } }, { type: 'done' }];
  let calls = 0;
  install(all, { chunked: true, onFetch(url, options) {
    calls++;
    assert.equal(url, 'http://offline.local/engineering/conversations/chat%20id/messages/stream/v2?project_id=project-B');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body), { message: '问题' });
  } });
  const received = [];
  await api.streamConversation('chat id', '问题', event => received.push(event), 'project-B');
  assert.deepEqual(received, all);
  assert.equal(calls, 1);
});

test('tool start/completion update one step; live and reopened activity have the same details', () => {
  const live = rich.reduce(updateActivity, []);
  const reopened = activityFromResult({ activity: JSON.parse(JSON.stringify(rich)), trace: [] });
  assert.deepEqual(live, reopened);
  assert.equal(live.length, 4);
  const tool = live.find(item => item.key === 'A1');
  assert.equal(tool.state, 'completed');
  assert.ok(tool.details.includes('关键词：配置'));
  assert.ok(tool.details.includes('找到 1 处匹配'));
  assert.deepEqual(tool.evidenceIds, ['E1']);
  assert.match(live.at(-1).details.join(''), /测试文件/);
});

test('read range, tool error and knowledge source are presented from public fields', () => {
  const read = activityItem({ type: 'activity', activity_id: 'A2', iteration: 2, tool_name: 'read_project_context',
    state: 'completed', purpose: 'Read source', target: { path: 'src/service.py', line: 2 },
    result_summary: { path: 'src/service.py', start_line: 2, end_line: 8 } });
  assert.ok(read.details.includes('已读取：src/service.py:2–8'));
  const failed = activityItem({ type: 'activity', activity_id: 'A3', iteration: 3, tool_name: 'find_tests',
    state: 'error', purpose: 'Find tests', error_code: 'PROJECT_CONTEXT_PATH_NOT_ALLOWED' });
  assert.equal(failed.state, 'error');
  assert.match(failed.details.join(''), /PROJECT_CONTEXT_PATH_NOT_ALLOWED/);
  const evidence = activityItem({ type: 'evidence_added', evidence_id: 'E2', kind: 'knowledge', source_name: 'rag/检索.md' });
  assert.deepEqual(evidence.details, ['rag/检索.md']);
});

test('old v1 history falls back to its recorded trace and cannot acquire invented v2 details', () => {
  assert.equal(activityFromResult({ trace: [] }).length, 0);
  const rows = activityFromResult({ trace: [{ event_type: 'tool_observation', tool_name: 'code_search', tool_status: 'ok' }] });
  assert.equal(rows[0].state, 'completed');
  assert.deepEqual(rows[0].details, []);
});

test('extra raw activity fields are omitted from the presentation', () => {
  const row = activityItem({ ...rich[3], raw_observation: 'DO_NOT_DISPLAY',
    target: { ...rich[3].target, raw_argument: 'DO_NOT_DISPLAY' },
    result_summary: { ...rich[3].result_summary, hidden_rationale: 'DO_NOT_DISPLAY' } });
  assert.ok(!JSON.stringify(row).includes('DO_NOT_DISPLAY'));
});

test('visible v1 schema is rejected and never silently retried through an old endpoint', async () => {
  let calls = 0;
  install([{ type: 'done' }], { schema: 'engineering_query_stream_v1', onFetch() { calls++; } });
  await assert.rejects(api.streamConversation('id', 'question', () => {}), error => error instanceof ApiError && error.kind === 'invalid_response');
  assert.equal(calls, 1);
});

for (const [index, event] of [
  { type: 'status', stage: 'analysis', state: 'started' },
  { type: 'evidence', evidence: {} },
  { type: 'run_started', execution_model: 'multi_agent', available_tool_count: 7 },
  { ...rich[1], activity_id: 'invalid' },
  { ...rich[1], state: 'unexpected' },
  { ...rich[2], end_line: 1 },
  { ...rich[4], missing_evidence_kinds: ['internal_reason'] },
].entries()) test('v1 or malformed rich event ' + index + ' fails closed even without a schema header', async () => {
  install([event], { schema: '' });
  await assert.rejects(api.streamConversation('id', 'question', () => {}), error => error instanceof ApiError && error.kind === 'invalid_response');
});
