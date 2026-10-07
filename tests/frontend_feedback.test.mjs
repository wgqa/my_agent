import test from 'node:test';
import assert from 'node:assert/strict';
import { resultFeedback, requestFeedback, requestDiagnostic, feedbackText } from '../frontend/js/feedback.js';

globalThis.window = { location: { protocol: 'http:', origin: 'http://offline.local', search: '' } };
const { api, ApiError } = await import('../frontend/js/api.js');

function installStream(events) {
  const body = events.map(event => 'data: ' + JSON.stringify(event) + '\n\n').join('');
  globalThis.fetch = async () => new Response(body, {
    headers: { 'Content-Type': 'text/event-stream', 'X-Engineering-Stream-Schema': 'engineering_query_stream_v1' },
  });
}

test('non-completed feedback never uses an unverified answer; completed is unchanged', () => {
  const result = { status: 'refused', answer: 'unverified answer' };
  assert.ok(!feedbackText(resultFeedback(result)).includes(result.answer));
  assert.equal(resultFeedback({ status: 'completed', answer: 'valid answer' }), null);
  assert.equal(resultFeedback({ status: 'refused', reason_code: 'UNSAFE_REQUEST' }).action, null);
  assert.equal(resultFeedback({ status: 'refused', reason_code: 'UNSAFE_REQUEST',
    feedback: { title: 'test', message: 'test', next_steps: [], action: 'retry' } }).action, null);
});

test('old or malformed feedback has usable guidance', () => {
  assert.ok(resultFeedback({ status: 'failed', feedback: { next_steps: 'invalid' } }).next_steps.length);
  assert.ok(resultFeedback({ status: 'refused' }).message);
});

test('busy, unavailable and missing-project errors have different recovery', () => {
  const busy = requestFeedback(new ApiError('http_error', '', { status: 503, detail: 'Engineering run at capacity; retry shortly' }));
  const unavailable = requestFeedback(new ApiError('http_error', '', { status: 503, detail: 'runtime not initialized' }));
  const missing = requestFeedback(new ApiError('http_error', '', { status: 409 }));
  assert.notEqual(busy.title, unavailable.title);
  assert.match(busy.message, /未开始/);
  assert.equal(missing.action, null);
  assert.match(missing.next_steps.join(''), /新建对话/);
});

test('transport failures ask to check saved history and never echo raw details', () => {
  for (const kind of ['connection_error', 'invalid_response', 'timeout', 'stream_error']) {
    const error = new ApiError(kind, 'SECRET_EXCEPTION', { detail: 'SECRET_PATH_AND_KEY' });
    const feedback = feedbackText(requestFeedback(error));
    assert.match(feedback, /保存|历史/);
    assert.ok(!feedback.includes('SECRET'));
    assert.ok(!requestDiagnostic(error).includes('SECRET'));
  }
});

for (const status of ['refused', 'failed']) test(status + ' is a final outcome with no answer stream', async () => {
  installStream([{ type: 'final', result: { status, answer: null } }, { type: 'done' }]);
  const received = [];
  await api.streamConversation('offline', 'question', event => received.push(event));
  assert.deepEqual(received.map(event => event.type), ['final', 'done']);
});

test('completed answer and public status survive the stream unchanged', async () => {
  installStream([{ type: 'answer_start' }, { type: 'answer_delta', delta: 'verified' },
    { type: 'final', result: { status: 'completed', answer: 'verified' } }, { type: 'done' }]);
  const received = [];
  await api.streamConversation('offline', 'question', event => received.push(event));
  assert.equal(received.find(event => event.type === 'final').result.answer, 'verified');
});

const invalidStreams = [
  [{ type: 'done' }],
  [{ type: 'status', stage: 'analysis' }],
  [{ type: 'final', result: null }, { type: 'done' }],
  [{ type: 'final', result: { status: 'refused', answer: 'unverified' } }, { type: 'done' }],
  [{ type: 'answer_start' }, { type: 'final', result: { status: 'failed', answer: null } }, { type: 'done' }],
  [{ type: 'final', result: { status: 'completed', answer: 'missing stream' } }, { type: 'done' }],
  [{ type: 'answer_start' }, { type: 'answer_delta', delta: 'first' },
    { type: 'final', result: { status: 'completed', answer: 'different' } }, { type: 'done' }],
  [{ type: 'error', code: 'INTERNAL_ENGINEERING_STREAM_ERROR' }, { type: 'final', result: { status: 'refused' } }, { type: 'done' }],
];
for (const [index, events] of invalidStreams.entries()) test('incomplete or inconsistent stream ' + index + ' fails closed', async () => {
  installStream(events);
  await assert.rejects(api.streamConversation('offline', 'question', () => {}),
    error => error instanceof ApiError && error.kind === 'invalid_response');
});

test('SSE service error completes as an error and does not create a final answer', async () => {
  installStream([{ type: 'error', code: 'INTERNAL_ENGINEERING_STREAM_ERROR' }, { type: 'done' }]);
  const received = [];
  await api.streamConversation('offline', 'question', event => received.push(event));
  assert.deepEqual(received.map(event => event.type), ['error', 'done']);
});
