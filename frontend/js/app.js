import { api, ApiError } from './api.js';

const EVIDENCE_ORDER = [
  'knowledge',
  'project_code',
  'project_doc',
  'project_change',
  'project_test',
];

const KIND_LABELS = {
  knowledge: 'KNOWLEDGE',
  project_code: 'CODE',
  project_doc: 'DOC',
  project_change: 'CHANGE',
  project_test: 'TEST',
};

const state = {
  conversations: [],
  activeConversationId: null,
  messages: [],
  evidence: [],
  activity: [],
  latestResult: null,
  running: false,
  toastTimer: null,
};

const elements = {
  apiStatus: document.querySelector('#api-status'),
  projectName: document.querySelector('#project-name'),
  conversationList: document.querySelector('#conversation-list'),
  newConversation: document.querySelector('#new-conversation'),
  refreshConversations: document.querySelector('#refresh-conversations'),
  conversationTitle: document.querySelector('#conversation-title'),
  conversationMeta: document.querySelector('#conversation-meta'),
  runState: document.querySelector('#run-state'),
  messages: document.querySelector('#messages'),
  composer: document.querySelector('#composer'),
  messageInput: document.querySelector('#message-input'),
  sendMessage: document.querySelector('#send-message'),
  evidenceCount: document.querySelector('#evidence-count'),
  evidenceList: document.querySelector('#evidence-list'),
  activityState: document.querySelector('#activity-state'),
  activityList: document.querySelector('#activity-list'),
  runSummary: document.querySelector('#run-summary'),
  runMetrics: document.querySelector('#run-metrics'),
  toast: document.querySelector('#toast'),
};

function text(value, fallback = '') {
  return typeof value === 'string' && value ? value : fallback;
}

function formatDate(value) {
  if (!value) {
    return '';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return '';
  }
  return new Intl.DateTimeFormat(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

function setApiStatus(status, label) {
  elements.apiStatus.classList.remove('status-online', 'status-error', 'status-unknown');
  elements.apiStatus.classList.add(
    status === 'online'
      ? 'status-online'
      : status === 'error'
        ? 'status-error'
        : 'status-unknown',
  );
  const light = elements.apiStatus.querySelector('.status-dot__light');
  elements.apiStatus.replaceChildren(light, document.createTextNode(' ' + label));
}

function showToast(message, { error = false } = {}) {
  window.clearTimeout(state.toastTimer);
  elements.toast.textContent = message;
  elements.toast.hidden = false;
  elements.toast.classList.toggle('toast-error', error);
  state.toastTimer = window.setTimeout(() => {
    elements.toast.hidden = true;
  }, 4200);
}

function userFacingError(error) {
  if (error instanceof ApiError) {
    return error.message || 'Unable to complete this request.';
  }
  return 'Unable to complete this request.';
}

function errorDetails(error) {
  if (!(error instanceof ApiError)) {
    return '';
  }
  const parts = [];
  if (error.status) {
    parts.push('HTTP ' + error.status);
  }
  if (error.detail) {
    parts.push(error.detail);
  }
  return parts.join(' · ');
}

function setRunning(running) {
  state.running = running;
  elements.newConversation.disabled = running;
  elements.refreshConversations.disabled = running;
  elements.messageInput.disabled = running;
  elements.sendMessage.disabled = running;
  elements.sendMessage.querySelector('span').textContent = running ? 'Running' : 'Send';
  elements.runState.className = running
    ? 'run-state run-state-running'
    : 'run-state run-state-idle';
  elements.runState.textContent = running ? 'Running' : 'Ready';
}

function setTerminalRunState(result) {
  if (result?.status === 'completed') {
    elements.runState.className = 'run-state run-state-complete';
    elements.runState.textContent = 'Complete';
  } else if (result?.status === 'refused') {
    elements.runState.className = 'run-state run-state-error';
    elements.runState.textContent = 'Refused';
  } else if (result?.status === 'failed') {
    elements.runState.className = 'run-state run-state-error';
    elements.runState.textContent = 'Failed';
  } else {
    elements.runState.className = 'run-state run-state-idle';
    elements.runState.textContent = 'Ready';
  }
}

function renderConversationList() {
  elements.conversationList.replaceChildren();
  if (!state.conversations.length) {
    const empty = document.createElement('div');
    empty.className = 'list-placeholder';
    empty.textContent = 'No conversations yet.';
    elements.conversationList.append(empty);
    return;
  }

  for (const conversation of state.conversations) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'conversation-item';
    button.classList.toggle(
      'is-active',
      conversation.id === state.activeConversationId,
    );
    button.disabled = state.running;
    button.addEventListener('click', () => selectConversation(conversation.id));

    const title = document.createElement('span');
    title.className = 'conversation-item__title';
    title.textContent = text(conversation.title, 'New conversation');
    const meta = document.createElement('span');
    meta.className = 'conversation-item__meta';
    meta.textContent = formatDate(conversation.updated_at) || 'Server conversation';
    button.append(title, meta);
    elements.conversationList.append(button);
  }
}

function resultForMessage(message) {
  return message && message.role === 'assistant' && message.result
    ? message.result
    : null;
}

function statusMessage(result) {
  if (!result) {
    return '';
  }
  if (result.status === 'refused') {
    if (result.reason_code === 'INSUFFICIENT_EVIDENCE_TO_FINALIZE') {
      return 'Insufficient evidence was found.';
    }
    return 'Unable to complete this request.';
  }
  if (result.status === 'failed') {
    if (result.failure_code === 'REQUEST_TIMEOUT') {
      return 'The request timed out.';
    }
    return 'Unable to complete this request.';
  }
  return text(result.answer);
}

function renderMessageContent(container, message) {
  const result = resultForMessage(message);
  const content = result ? statusMessage(result) : text(message.content);
  if (message.pending) {
    const pending = document.createElement('span');
    pending.className = 'message-placeholder';
    pending.textContent = 'Waiting for the Engineering Agent…';
    container.append(pending);
    return;
  }
  if (message.error) {
    const error = document.createElement('span');
    error.className = 'message-error';
    error.textContent = message.error;
    container.append(error);
    if (message.errorDetail) {
      const details = document.createElement('details');
      details.className = 'message-details';
      const summary = document.createElement('summary');
      summary.textContent = 'Details';
      const detail = document.createElement('div');
      detail.textContent = message.errorDetail;
      details.append(summary, detail);
      container.append(details);
    }
    return;
  }
  if (!content) {
    const empty = document.createElement('span');
    empty.className = 'message-placeholder';
    empty.textContent = 'No public answer was returned.';
    container.append(empty);
    return;
  }

  const paragraphs = String(content).split(/\n{2,}/);
  for (const paragraphText of paragraphs) {
    const paragraph = document.createElement('p');
    paragraph.textContent = paragraphText;
    container.append(paragraph);
  }
}

function renderMessages() {
  elements.messages.replaceChildren();
  if (!state.messages.length) {
    const empty = document.createElement('div');
    empty.className = 'empty-chat';
    const mark = document.createElement('div');
    mark.className = 'empty-chat__mark';
    mark.setAttribute('aria-hidden', 'true');
    mark.textContent = '↗';
    const heading = document.createElement('h3');
    heading.textContent = 'Ask about the bound project';
    const copy = document.createElement('p');
    copy.textContent =
      'Explore implementation details, repository behavior, or evidence from the Engineering Agent.';
    empty.append(mark, heading, copy);
    elements.messages.append(empty);
    return;
  }

  for (const message of state.messages) {
    const row = document.createElement('article');
    row.className = 'message-row message-row--' + (message.role === 'user' ? 'user' : 'assistant');
    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = message.role === 'user' ? 'You' : 'E';
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';
    const meta = document.createElement('div');
    meta.className = 'message-meta';
    const author = document.createElement('span');
    author.textContent = message.role === 'user' ? 'You' : 'Engineering Agent';
    const time = document.createElement('span');
    time.textContent = formatDate(message.created_at);
    meta.append(author, time);
    const content = document.createElement('div');
    content.className = 'message-content';
    renderMessageContent(content, message);
    bubble.append(meta, content);

    const result = resultForMessage(message);
    if (result) {
      const metaLine = document.createElement('div');
      metaLine.className = 'message-result-meta';
      if (result.status) {
        metaLine.append(document.createTextNode(result.status));
      }
      if (result.tool_calls_used !== undefined) {
        metaLine.append(document.createTextNode(' · ' + result.tool_calls_used + ' tool calls'));
      }
      if (result.iterations_used !== undefined) {
        metaLine.append(document.createTextNode(' · ' + result.iterations_used + ' iterations'));
      }
      bubble.append(metaLine);
    }
    row.append(avatar, bubble);
    elements.messages.append(row);
  }
  elements.messages.scrollTop = elements.messages.scrollHeight;
}

function kindLabel(kind) {
  return KIND_LABELS[kind] || 'EVIDENCE';
}

function kindClass(kind) {
  return kind ? 'kind-badge--' + kind.replaceAll('_', '-') : '';
}

function renderEvidence() {
  elements.evidenceCount.textContent = String(state.evidence.length);
  elements.evidenceList.replaceChildren();
  if (!state.evidence.length) {
    const empty = document.createElement('div');
    empty.className = 'section-empty';
    empty.textContent = 'Evidence from the active run will appear here.';
    elements.evidenceList.append(empty);
    return;
  }

  const evidence = [...state.evidence].sort((left, right) => {
    const leftOrder = EVIDENCE_ORDER.indexOf(left.kind);
    const rightOrder = EVIDENCE_ORDER.indexOf(right.kind);
    return (leftOrder < 0 ? 99 : leftOrder) - (rightOrder < 0 ? 99 : rightOrder);
  });

  for (const item of evidence) {
    const card = document.createElement('article');
    card.className = 'evidence-card';
    const heading = document.createElement('div');
    heading.className = 'evidence-card__heading';
    const id = document.createElement('span');
    id.className = 'evidence-card__id';
    id.textContent = '[' + text(item.evidence_id, 'E?') + ']';
    const kind = document.createElement('span');
    kind.className = 'kind-badge ' + kindClass(item.kind);
    kind.textContent = kindLabel(item.kind);
    heading.append(id, kind);

    const location = document.createElement('div');
    location.className = 'evidence-card__location';
    if (item.kind === 'knowledge') {
      location.textContent = text(item.source_name, 'Knowledge source');
    } else {
      const lineStart = item.start_line || '?';
      const lineEnd = item.end_line || lineStart;
      location.textContent =
        text(item.path, 'Project path') + ' · lines ' + lineStart + '–' + lineEnd;
    }
    const snippet = document.createElement('p');
    snippet.className = 'evidence-card__snippet';
    snippet.textContent = text(item.snippet, 'No public snippet');
    card.append(heading, location, snippet);
    elements.evidenceList.append(card);
  }
}

function activityLabel(event) {
  if (event.kind === 'status') {
    if (event.stage === 'analysis') {
      return 'Analysis started';
    }
    if (event.stage === 'verification') {
      return event.state === 'blocked'
        ? 'Evidence verification blocked'
        : 'Evidence verification';
    }
    if (event.stage === 'tool') {
      return text(event.tool_name, 'Tool') + ' ' + text(event.state, 'updated');
    }
  }
  return 'Runtime activity';
}

function addActivity(event) {
  if (!event || typeof event.type !== 'string') {
    return;
  }
  if (event.type === 'status') {
    state.activity.push({
      label: activityLabel(event),
      state: text(event.state, 'started'),
      timestamp: new Date(),
    });
  }
  renderActivity();
}

function activityFromResult(result) {
  if (!result || !Array.isArray(result.trace)) {
    return [];
  }
  return result.trace
    .map((event) => {
      if (event.event_type === 'tool_call_created') {
        return {
          label: text(event.tool_name, 'Tool') + ' started',
          state: 'started',
          timestamp: null,
        };
      }
      if (event.event_type === 'tool_observation') {
        return {
          label: text(event.tool_name, 'Tool') + ' '
            + (event.tool_status === 'ok' ? 'completed' : 'error'),
          state: event.tool_status === 'ok' ? 'completed' : 'error',
          timestamp: null,
        };
      }
      if (event.event_type === 'finalization_guard_blocked') {
        return {
          label: 'Evidence verification blocked',
          state: 'blocked',
          timestamp: null,
        };
      }
      return null;
    })
    .filter(Boolean);
}

function renderActivity() {
  elements.activityList.replaceChildren();
  if (!state.activity.length) {
    const empty = document.createElement('li');
    empty.className = 'section-empty';
    empty.textContent = 'Activity from the active run will appear here.';
    elements.activityList.append(empty);
    elements.activityState.textContent = 'Live run events';
    return;
  }
  elements.activityState.textContent = state.running ? 'Receiving events' : 'Run complete';
  for (const item of state.activity) {
    const row = document.createElement('li');
    row.className = 'activity-item';
    const marker = document.createElement('span');
    marker.className = 'activity-marker activity-marker--' + item.state;
    marker.setAttribute('aria-hidden', 'true');
    const copy = document.createElement('div');
    copy.className = 'activity-item__copy';
    const label = document.createElement('span');
    label.className = 'activity-item__label';
    label.textContent = item.label;
    const timestamp = document.createElement('span');
    timestamp.className = 'activity-item__time';
    timestamp.textContent = item.timestamp
      ? item.timestamp.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      : 'history';
    copy.append(label, timestamp);
    row.append(marker, copy);
    elements.activityList.append(row);
  }
}

function renderRunSummary(result) {
  if (!result) {
    elements.runSummary.hidden = true;
    elements.runMetrics.replaceChildren();
    return;
  }
  elements.runSummary.hidden = false;
  elements.runMetrics.replaceChildren();
  const metrics = [
    ['Status', text(result.status, 'unknown')],
    ['Iterations', result.iterations_used],
    ['Tool calls', result.tool_calls_used],
    ['Tool errors', result.tool_errors_used],
  ];
  if (result.execution) {
    metrics.push(['Elapsed', String(result.execution.elapsed_ms) + ' ms']);
    metrics.push(['Decision calls', result.execution.decision_llm_calls]);
  }
  if (result.reason_code) {
    metrics.push(['Reason', result.reason_code]);
  }
  if (result.failure_code) {
    metrics.push(['Failure', result.failure_code]);
  }
  for (const [labelText, value] of metrics) {
    const label = document.createElement('dt');
    label.textContent = labelText;
    const valueNode = document.createElement('dd');
    valueNode.textContent = String(value ?? '—');
    elements.runMetrics.append(label, valueNode);
  }
}

function applyConversationDetail(detail, { keepRunPanels = false } = {}) {
  state.messages = Array.isArray(detail.messages) ? detail.messages : [];
  const assistant = [...state.messages]
    .reverse()
    .find((message) => message.role === 'assistant' && message.result);
  if (!keepRunPanels) {
    state.latestResult = assistant ? assistant.result : null;
    state.evidence = state.latestResult?.evidence || [];
    state.activity = activityFromResult(state.latestResult);
  }
  elements.conversationTitle.textContent = text(detail.title, 'New conversation');
  elements.projectName.textContent = text(detail.project_name, 'Project');
  elements.conversationMeta.textContent =
    text(detail.project_name, 'Bound project')
      + ' · '
      + (formatDate(detail.updated_at) || 'Server conversation');
  renderMessages();
  renderEvidence();
  renderActivity();
  renderRunSummary(state.latestResult);
  if (!state.running) {
    setTerminalRunState(state.latestResult);
  }
}

async function loadConversation(conversationId, options = {}) {
  const detail = await api.getConversation(conversationId);
  state.activeConversationId = conversationId;
  applyConversationDetail(detail, options);
  renderConversationList();
}

async function refreshConversations() {
  const payload = await api.listConversations();
  state.conversations = Array.isArray(payload.conversations)
    ? payload.conversations
    : [];
  renderConversationList();
  if (!state.conversations.length) {
    const created = await api.createConversation();
    state.conversations = [created];
    state.activeConversationId = created.id;
    renderConversationList();
    applyConversationDetail(created);
    return;
  }
  const selected = state.conversations.some(
    (conversation) => conversation.id === state.activeConversationId,
  )
    ? state.activeConversationId
    : state.conversations[0].id;
  await loadConversation(selected);
}

async function selectConversation(conversationId) {
  if (state.running || conversationId === state.activeConversationId) {
    return;
  }
  try {
    await loadConversation(conversationId);
  } catch (error) {
    showToast(userFacingError(error), { error: true });
  }
}

async function createConversation() {
  if (state.running) {
    return;
  }
  try {
    const created = await api.createConversation();
    state.conversations = [created, ...state.conversations];
    state.activeConversationId = created.id;
    state.latestResult = null;
    state.evidence = [];
    state.activity = [];
    applyConversationDetail(created);
    renderConversationList();
    elements.messageInput.focus();
  } catch (error) {
    showToast(userFacingError(error), { error: true });
  }
}

function updatePendingAssistant(content, result = null) {
  const index = state.messages.findIndex((message) => message.pending);
  if (index < 0) {
    return;
  }
  state.messages[index] = {
    ...state.messages[index],
    content,
    pending: false,
    result,
  };
}

async function sendMessage(event) {
  event.preventDefault();
  if (state.running) {
    return;
  }
  const message = elements.messageInput.value.trim();
  if (!message || !state.activeConversationId) {
    return;
  }

  state.messages.push({
    role: 'user',
    content: message,
    created_at: new Date().toISOString(),
  });
  state.messages.push({
    role: 'assistant',
    content: '',
    pending: true,
    created_at: new Date().toISOString(),
  });
  state.evidence = [];
  state.activity = [];
  state.latestResult = null;
  elements.messageInput.value = '';
  setRunning(true);
  renderMessages();
  renderEvidence();
  renderActivity();
  renderRunSummary(null);

  let finalResult = null;
  try {
    await api.streamConversation(state.activeConversationId, message, async (eventPayload) => {
      if (eventPayload.type === 'status') {
        addActivity(eventPayload);
        return;
      }
      if (eventPayload.type === 'evidence') {
        if (eventPayload.evidence) {
          state.evidence.push(eventPayload.evidence);
          renderEvidence();
        }
        return;
      }
      if (eventPayload.type === 'answer_delta') {
        const pending = state.messages.find((item) => item.pending);
        if (pending) {
          pending.content = (pending.content || '') + text(eventPayload.delta);
          renderMessages();
        }
        return;
      }
      if (eventPayload.type === 'final') {
        finalResult = eventPayload.result || null;
        state.latestResult = finalResult;
        state.evidence = Array.isArray(finalResult?.evidence)
          ? finalResult.evidence
          : state.evidence;
        updatePendingAssistant(statusMessage(finalResult), finalResult);
        renderMessages();
        renderEvidence();
        renderRunSummary(finalResult);
        return;
      }
      if (eventPayload.type === 'error') {
        updatePendingAssistant('');
        const pending = state.messages[state.messages.length - 1];
        if (pending && pending.role === 'assistant') {
          pending.error = 'Unable to complete this request.';
          pending.errorDetail = text(eventPayload.code);
        }
        renderMessages();
      }
    });

    if (finalResult && state.activeConversationId) {
      await loadConversation(state.activeConversationId, { keepRunPanels: true });
    }
    setRunning(false);
    renderActivity();
    setTerminalRunState(finalResult);
  } catch (error) {
    updatePendingAssistant('');
    const pending = state.messages[state.messages.length - 1];
    if (pending && pending.role === 'assistant') {
      pending.error = userFacingError(error);
      pending.errorDetail = errorDetails(error);
    }
    setRunning(false);
    elements.runState.className = 'run-state run-state-error';
    elements.runState.textContent = 'Unavailable';
    renderMessages();
    showToast(userFacingError(error), { error: true });
  }
}

async function boot() {
  elements.composer.addEventListener('submit', sendMessage);
  elements.newConversation.addEventListener('click', createConversation);
  elements.refreshConversations.addEventListener('click', async () => {
    try {
      await refreshConversations();
    } catch (error) {
      setApiStatus('error', 'API unavailable');
      showToast(userFacingError(error), { error: true });
    }
  });
  elements.messageInput.addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      elements.composer.requestSubmit();
    }
  });

  try {
    await refreshConversations();
    setApiStatus('online', 'API connected');
  } catch (error) {
    setApiStatus('error', 'API unavailable');
    elements.conversationList.replaceChildren();
    const empty = document.createElement('div');
    empty.className = 'list-placeholder';
    empty.textContent = 'Start the API, then refresh this page.';
    elements.conversationList.append(empty);
    showToast(userFacingError(error), { error: true });
  }
}

boot();
