// Optional real-browser regression suite. Uses a local static server and mocked
// conversation APIs; never starts the backend, writes its DBs or calls an LLM.
import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const frontend = join(repo, 'frontend');
const browserRequire = process.env.ENGINEERING_BROWSER_NODE_MODULES
  ? createRequire(join(resolve(process.env.ENGINEERING_BROWSER_NODE_MODULES), '_test.cjs'))
  : createRequire(import.meta.url);
const { chromium } = browserRequire('playwright');
let server, browser, origin;

before(async () => {
  server = createServer(async (request, response) => {
    const relative = decodeURIComponent(new URL(request.url, 'http://local.test').pathname);
    const path = resolve(frontend, relative === '/' ? 'index.html' : '.' + relative);
    if (!path.startsWith(frontend + sep)) return response.writeHead(404).end();
    try {
      const mime = path.endsWith('.js') ? 'text/javascript' : path.endsWith('.css') ? 'text/css' : 'text/html';
      response.writeHead(200, { 'Content-Type': mime });
      response.end(await readFile(path));
    } catch { response.writeHead(404).end(); }
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  origin = 'http://127.0.0.1:' + server.address().port;
  browser = await chromium.launch({ headless: true,
    ...(process.env.ENGINEERING_BROWSER_EXECUTABLE ? { executablePath: process.env.ENGINEERING_BROWSER_EXECUTABLE } : {}) });
});
after(async () => {
  await browser?.close();
  if (server) await new Promise(resolve => server.close(resolve));
});

const evidence = name => ({ evidence_id: 'E1', kind: 'project_doc', path: name,
  start_line: 1, end_line: 2, snippet: name + ' document body' });
const activity = name => [
  { type: 'run_started', execution_model: 'single_agent', available_tool_count: 7 },
  { type: 'activity', activity_id: 'A1', iteration: 1, tool_name: 'read_project_context',
    state: 'completed', purpose: 'Read this message document', target: { path: name }, evidence_ids_added: ['E1'] },
];
const completed = name => ({ status: 'completed', answer: name + ' [E1]',
  evidence: [evidence(name)], activity: activity(name), trace: [], iterations_used: 2, tool_calls_used: 1 });
const refused = { status: 'refused', reason_code: 'INSUFFICIENT_INFORMATION', answer: null, evidence: [], activity: [], trace: [] };
const rounds = results => results.flatMap((result, index) => [
  { id: 'u' + index, role: 'user', content: 'Question ' + index },
  { id: 'a' + index, role: 'assistant', content: result?.answer || '', result },
]);

async function app(t, results, { viewport = { width: 1100, height: 800 }, secondResults } = {}) {
  const page = await browser.newPage({ viewport });
  t.after(() => page.close());
  const messages = rounds(results);
  const detail = { id: 'fixture-chat', title: 'Message ownership fixture', project_id: 'fixture-project',
    project_name: 'Fixture', messages };
  const details = [detail];
  if (secondResults) details.push({ ...detail, id: 'other-chat', title: 'Other fixture conversation',
    project_id: 'other-project', project_name: 'Other fixture', messages: rounds(secondResults) });
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.origin !== origin) return route.abort();
    if (url.pathname === '/js/app.js') {
      const source = await readFile(join(frontend, 'js/app.js'), 'utf8');
      return route.fulfill({ contentType: 'text/javascript', body: source
        + '\nwindow.__frontendTest = {state, api, openDrawer};\n' });
    }
    if (url.pathname.startsWith('/engineering/')) {
      const payload = url.pathname === '/engineering/conversations'
        ? { conversations: details.map(item => ({ ...item, messages: undefined })) }
        : details.find(item => url.pathname.endsWith('/' + item.id));
      if (!payload) return route.fulfill({ status: 404, json: { detail: 'Fixture endpoint not found' } });
      return route.fulfill({ json: payload });
    }
    return route.continue();
  });
  await page.goto(origin);
  await page.waitForFunction(count => window.__frontendTest?.state.messages.length === count, messages.length);
  return page;
}

async function startRun(page) {
  await page.evaluate(() => {
    const { api, state } = window.__frontendTest;
    api.streamConversation = async (_id, _query, emit) => {
      window.__emitFixture = emit;
      await new Promise(resolve => { window.__finishFixture = resolve; });
    };
    api.getConversation = async () => ({ id: 'fixture-chat', title: 'Message ownership fixture',
      project_id: 'fixture-project', project_name: 'Fixture', messages: state.messages });
  });
  await page.locator('#message-input').fill('这次读取项目说明，介绍一下当前项目');
  await page.locator('#send-message').click();
  await page.waitForFunction(() => typeof window.__emitFixture === 'function');
}
async function emit(page, event) { await page.evaluate(event => window.__emitFixture(event), event); }
async function finishRun(page, result) {
  await emit(page, { type: 'final', result });
  await page.evaluate(() => window.__finishFixture());
  await page.waitForFunction(() => !window.__frontendTest.state.running);
}

test('legacy refusal with missing fields never borrows latest evidence in feedback or drawer', async t => {
  const legacy = { status: 'refused', reason_code: 'INSUFFICIENT_INFORMATION', answer: null, trace: [] };
  const page = await app(t, [legacy, completed('latest.md')]);
  const row = page.locator('.message-row--assistant').nth(0);
  assert.equal(await row.getByRole('button', { name: '查看已找到的资料' }).count(), 0);
  await row.getByRole('button', { name: 'Activity 0', exact: true }).click();
  assert.equal(await page.locator('#drawer-sources-count').textContent(), '0');
  assert.equal(await page.locator('#drawer-activity-count').textContent(), '0');
  assert.equal(await page.locator('#drawer-sources').getByText('latest.md', { exact: true }).count(), 0);
});

test('legacy text citation without its own evidence stays text, even when latest also has E1', async t => {
  const page = await app(t, [{ status: 'completed', answer: 'Unrecorded source [E1]', trace: [] }, completed('latest.md')]);
  const row = page.locator('.message-row--assistant').nth(0);
  assert.equal(await row.locator('.citation').count(), 0);
  assert.match(await row.textContent(), /\[E1\]/);
});

test('historic citations and activity evidence links retain message ownership across refresh', async t => {
  const page = await app(t, [completed('older.md'), completed('latest.md')]);
  for (const refresh of [false, true]) {
    if (refresh) { await page.reload(); await page.waitForFunction(() => window.__frontendTest?.state.messages.length === 4); }
    const older = page.locator('.message-row--assistant').nth(0);
    await older.locator('.citation').click();
    assert.match(await page.locator('#drawer-sources').textContent(), /older\.md/);
    assert.doesNotMatch(await page.locator('#drawer-sources').textContent(), /latest\.md/);
    await older.getByRole('button', { name: 'Activity 2', exact: true }).click();
    await page.locator('#drawer-activity .activity-evidence').click();
    assert.match(await page.locator('#drawer-sources').textContent(), /older\.md/);
  }
});

test('explicit empty refusal retains empty details and refused run status', async t => {
  const page = await app(t, [refused, completed('latest.md')]);
  const row = page.locator('.message-row--assistant').nth(0);
  assert.equal(await row.getByRole('button', { name: 'Sources 0', exact: true }).isDisabled(), true);
  await row.getByRole('button', { name: 'Run', exact: true }).click();
  assert.equal(await page.locator('#drawer-sources-count').textContent(), '0');
  assert.match(await page.locator('#drawer-run').textContent(), /refused/);
});

test('live activity belongs below the current question and survives answer rerenders on desktop and mobile', async t => {
  for (const viewport of [{ width: 1100, height: 800 }, { width: 390, height: 844 }]) {
    const page = await app(t, Array.from({ length: 12 }, (_, i) => completed('history-' + i + '.md')), { viewport });
    await startRun(page);
    const live = page.locator('.message-row--assistant').last().locator('#live-run');
    assert.equal(await live.count(), 1);
    assert.equal(await live.isVisible(), true);
    const question = await page.locator('.message-row--user').last().boundingBox();
    const panel = await live.boundingBox();
    assert.ok(panel.y >= question.y + question.height);
    await emit(page, activity('current.md')[0]);
    await emit(page, activity('current.md')[1]);
    await emit(page, { type: 'answer_delta', delta: 'Current answer' });
    assert.equal(await live.count(), 1);
    assert.equal(await page.locator('#live-run').count(), 1);
    assert.match(await live.textContent(), /current\.md/);
    if (viewport.width > 800 && process.env.ENGINEERING_FRONTEND_SCREENSHOT) {
      await page.screenshot({ path: process.env.ENGINEERING_FRONTEND_SCREENSHOT });
    }
    await finishRun(page, completed('current.md'));
    assert.equal(await page.locator('#live-run:visible').count(), 0);
  }
});

test('live evidence drawer uses current data and updates start/completion as one activity', async t => {
  const page = await app(t, [completed('older.md')]);
  await startRun(page);
  const step = activity('current.md')[1];
  await emit(page, { ...step, state: 'started', evidence_ids_added: undefined });
  await emit(page, { type: 'evidence_added', ...evidence('current.md') });
  await emit(page, step);
  await page.locator('#live-activity-list .activity-evidence').first().click();
  assert.match(await page.locator('#drawer-sources').textContent(), /current\.md/);
  assert.doesNotMatch(await page.locator('#drawer-sources').textContent(), /older\.md/);
  assert.equal(await page.locator('#drawer-activity-count').textContent(), '2');
  await finishRun(page, completed('current.md'));
  assert.match(await page.locator('#drawer-sources').textContent(), /current\.md/);
});

test('a historic drawer opened during a run stays pinned when that run finishes', async t => {
  const page = await app(t, [completed('older.md')]);
  await startRun(page);
  await page.locator('.message-row--assistant').nth(0).getByRole('button', { name: 'Activity 2', exact: true }).click();
  await emit(page, { type: 'evidence_added', ...evidence('current.md') });
  await finishRun(page, completed('current.md'));
  assert.match(await page.locator('#drawer-activity').textContent(), /older\.md/);
  assert.doesNotMatch(await page.locator('#drawer-activity').textContent(), /current\.md/);
  assert.match(await page.locator('#drawer-sources').textContent(), /older\.md/);
});

test('request error removes the live panel and leaves historic details intact', async t => {
  const page = await app(t, [completed('older.md')]);
  await startRun(page);
  await emit(page, { type: 'error', code: 'INTERNAL_ENGINEERING_STREAM_ERROR' });
  await page.evaluate(() => window.__finishFixture());
  await page.waitForFunction(() => !window.__frontendTest.state.running);
  assert.equal(await page.locator('#live-run:visible').count(), 0);
  assert.equal(await page.locator('.message-row--assistant').last().locator('.outcome-feedback').count(), 1);
  await page.locator('.message-row--assistant').nth(0).locator('.citation').click();
  assert.match(await page.locator('#drawer-sources').textContent(), /older\.md/);
});

test('streaming answer citations explicitly target the live run before its final result', async t => {
  const page = await app(t, [completed('older.md')]);
  await startRun(page);
  await emit(page, { type: 'evidence_added', ...evidence('current.md') });
  await emit(page, { type: 'answer_delta', delta: '**Current answer [E1]**\n\n> Quoted source [E1]' });
  const citations = page.locator('.message-row--assistant').last().locator('.citation');
  assert.equal(await citations.count(), 2);
  for (const index of [0, 1]) {
    await citations.nth(index).click();
    assert.match(await page.locator('#drawer-sources').textContent(), /current\.md/);
    assert.doesNotMatch(await page.locator('#drawer-sources').textContent(), /older\.md/);
  }
  await finishRun(page, completed('current.md'));
});

test('conversation switching clears the selected historic drawer and keeps same-ID evidence isolated', async t => {
  const page = await app(t, [completed('chat-A.md')], { secondResults: [completed('chat-B.md')] });
  await page.locator('.citation').click();
  assert.match(await page.locator('#drawer-sources').textContent(), /chat-A\.md/);
  await page.locator('.conversation-item').nth(1).click();
  await page.waitForFunction(() => window.__frontendTest.state.activeConversationId === 'other-chat');
  assert.equal(await page.locator('#evidence-drawer').getAttribute('aria-hidden'), 'true');
  await page.locator('.citation').click();
  assert.match(await page.locator('#drawer-sources').textContent(), /chat-B\.md/);
  assert.doesNotMatch(await page.locator('#drawer-sources').textContent(), /chat-A\.md/);
});
