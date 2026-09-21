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
  drawerOpen: false,
  drawerTab: 'sources',
  drawerResult: null,
  drawerEvidenceId: null,
  drawerHighlightTimer: null,
  toastTimer: null,
};

const elements = {
  apiStatus: document.querySelector('#api-status'),
  apiStatusText: document.querySelector('#api-status-text'),
  sidebarFooter: document.querySelector('.sidebar-footer'),
  conversationTitle: document.querySelector('#conversation-title'),
  projectName: document.querySelector('#project-name'),
  runStatus: document.querySelector('#run-status'),
  conversationList: document.querySelector('#conversation-list'),
  newConversation: document.querySelector('#new-conversation'),
  refreshConversations: document.querySelector('#refresh-conversations'),
  messages: document.querySelector('#messages'),
  liveRun: document.querySelector('#live-run'),
  liveRunLabel: document.querySelector('#live-run-label'),
  liveActivityList: document.querySelector('#live-activity-list'),
  composer: document.querySelector('#composer'),
  messageInput: document.querySelector('#message-input'),
  sendMessage: document.querySelector('#send-message'),
  drawer: document.querySelector('#evidence-drawer'),
  drawerClose: document.querySelector('#drawer-close'),
  drawerTabs: document.querySelectorAll('[data-drawer-tab]'),
  drawerSourcesCount: document.querySelector('#drawer-sources-count'),
  drawerActivityCount: document.querySelector('#drawer-activity-count'),
  drawerSources: document.querySelector('#drawer-sources'),
  drawerActivity: document.querySelector('#drawer-activity'),
  drawerRun: document.querySelector('#drawer-run'),
  toast: document.querySelector('#toast'),
};

function text(value, fallback = '') {
  return typeof value === 'string' && value ? value : fallback;
}

function setApiStatus(status, label) {
  elements.apiStatus.hidden = status === 'online';
  elements.apiStatusText.textContent = label;
  elements.refreshConversations.hidden = status === 'online';
  elements.sidebarFooter.hidden = status === 'online';
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

function setRunError(label = 'Unavailable') {
  elements.runStatus.hidden = false;
  elements.runStatus.textContent = label;
}

function clearRunError() {
  elements.runStatus.hidden = true;
  elements.runStatus.textContent = '';
}

function resizeComposer() {
  elements.messageInput.style.height = 'auto';
  elements.messageInput.style.height = Math.min(elements.messageInput.scrollHeight, 180) + 'px';
}

function updateComposerState() {
  elements.sendMessage.disabled = state.running || !elements.messageInput.value.trim();
}

function setRunning(running) {
  state.running = running;
  elements.newConversation.disabled = running;
  elements.refreshConversations.disabled = running;
  elements.messageInput.disabled = running;
  elements.liveRun.hidden = !running;
  if (running) {
    clearRunError();
    elements.liveRunLabel.textContent = 'Analyzing…';
  }
  updateComposerState();
  renderConversationList();
  renderLiveActivity();
}

function setTerminalRunState(result) {
  if (result?.status === 'failed') {
    setRunError('Error');
  } else {
    clearRunError();
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
    button.textContent = text(conversation.title, 'New conversation');
    button.addEventListener('click', () => selectConversation(conversation.id));
    elements.conversationList.append(button);
  }
}

function resultForMessage(message) {
  return message && message.role === 'assistant' && message.result
    ? message.result
    : null;
}

function evidenceId(value) {
  if (value === null || value === undefined) {
    return '';
  }
  const raw = String(value).trim().toUpperCase();
  if (!raw) {
    return '';
  }
  return raw.startsWith('E') ? raw : 'E' + raw;
}

function evidenceForResult(result) {
  return Array.isArray(result?.evidence) ? result.evidence : state.evidence;
}

function findEvidence(evidence, id) {
  const wanted = evidenceId(id);
  return evidence.find((item) => evidenceId(item?.evidence_id) === wanted) || null;
}

function appendTextWithCitations(container, value, evidence, result = null) {
  const source = String(value ?? '');
  const pattern = /\[E\d+\]/g;
  let lastIndex = 0;
  let match;
  while ((match = pattern.exec(source)) !== null) {
    if (match.index > lastIndex) {
      container.append(document.createTextNode(source.slice(lastIndex, match.index)));
    }
    const citationId = evidenceId(match[0].slice(1, -1));
    if (!findEvidence(evidence, citationId)) {
      container.append(document.createTextNode(match[0]));
    } else {
      const citation = document.createElement('button');
      citation.type = 'button';
      citation.className = 'citation';
      citation.textContent = match[0];
      citation.dataset.evidenceId = citationId;
      citation.setAttribute('aria-label', 'Open evidence ' + citationId);
      citation.addEventListener('click', () => openDrawer('sources', result, citationId));
      container.append(citation);
    }
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < source.length) {
    container.append(document.createTextNode(source.slice(lastIndex)));
  }
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

  const result = resultForMessage(message);
  const content = result ? statusMessage(result) : text(message.content);
  if (message.pending && !content) {
    const pending = document.createElement('span');
    pending.className = 'message-placeholder';
    pending.textContent = 'Waiting for the Engineering Agent…';
    container.append(pending);
    return;
  }
  if (!content) {
    const empty = document.createElement('span');
    empty.className = 'message-placeholder';
    empty.textContent = 'No public answer was returned.';
    container.append(empty);
    return;
  }

  const resultEvidence = evidenceForResult(result);
  const paragraphs = String(content).split(/\n{2,}/);
  for (const paragraphText of paragraphs) {
    const paragraph = document.createElement('p');
    appendTextWithCitations(paragraph, paragraphText, resultEvidence, result);
    container.append(paragraph);
  }
  if (message.pending && content) {
    const cursor = document.createElement('span');
    cursor.className = 'streaming-cursor';
    cursor.setAttribute('aria-hidden', 'true');
    container.append(cursor);
  }
}

function kindLabel(kind) {
  return KIND_LABELS[kind] || 'EVIDENCE';
}

function kindClass(kind) {
  return kind ? 'kind-badge--' + kind.replaceAll('_', '-') : '';
}

function buildEvidenceCard(item, { selected = false } = {}) {
  const card = document.createElement('article');
  card.className = 'evidence-card';
  card.classList.toggle('is-selected', selected);
  const itemId = evidenceId(item?.evidence_id);
  if (itemId) {
    card.id = 'evidence-' + itemId;
    card.dataset.evidenceId = itemId;
  }

  const heading = document.createElement('div');
  heading.className = 'evidence-card__heading';
  const id = document.createElement('span');
  id.className = 'evidence-card__id';
  id.textContent = '[' + (itemId || 'E?') + ']';
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
  return card;
}

function appendEvidence(container, evidence, selectedId = '') {
  const stack = document.createElement('div');
  stack.className = 'evidence-stack';
  const ordered = [...(Array.isArray(evidence) ? evidence : [])].sort((left, right) => {
    const leftOrder = EVIDENCE_ORDER.indexOf(left.kind);
    const rightOrder = EVIDENCE_ORDER.indexOf(right.kind);
    return (leftOrder < 0 ? 99 : leftOrder) - (rightOrder < 0 ? 99 : rightOrder);
  });
  if (!ordered.length) {
    const empty = document.createElement('div');
    empty.className = 'section-empty';
    empty.textContent = 'No public evidence was returned.';
    stack.append(empty);
  } else {
    ordered.forEach((item) => {
      stack.append(
        buildEvidenceCard(item, {
          selected: evidenceId(item?.evidence_id) === evidenceId(selectedId),
        }),
      );
    });
  }
  container.append(stack);
}

function activityLabel(event) {
  if (event?.type !== 'status') {
    return null;
  }
  if (event.stage === 'analysis') {
    if (event.state === 'started') {
      return 'Analyzing';
    }
    if (event.state === 'completed') {
      return 'Analysis complete';
    }
    return null;
  }
  if (event.stage === 'tool' && event.tool_name) {
    if (event.state === 'started') {
      return event.tool_name + ' started';
    }
    if (event.state === 'completed') {
      return event.tool_name + ' completed';
    }
    if (event.state === 'error') {
      return event.tool_name + ' error';
    }
    return null;
  }
  if (event.stage === 'verification' && event.state === 'blocked') {
    return 'Evidence verification blocked';
  }
  return null;
}

function activityFromResult(result) {
  if (!result || !Array.isArray(result.trace)) {
    return [];
  }
  return result.trace
    .map((event) => {
      if (event.event_type === 'tool_call_created' && event.tool_name) {
        return {
          label: event.tool_name + ' started',
          state: 'started',
          timestamp: null,
        };
      }
      if (event.event_type === 'tool_observation' && event.tool_name) {
        return {
          label: event.tool_name
            + (event.tool_status === 'ok' ? ' completed' : ' error'),
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

function renderActivityItems(container, activity, emptyText) {
  container.replaceChildren();
  if (!activity.length) {
    const empty = document.createElement('li');
    empty.className = 'section-empty';
    empty.textContent = emptyText;
    container.append(empty);
    return;
  }
  for (const item of activity) {
    const row = document.createElement('li');
    row.className = 'activity-item';
    const marker = document.createElement('span');
    marker.className = 'activity-marker activity-marker--' + item.state;
    marker.setAttribute('aria-hidden', 'true');
    const label = document.createElement('span');
    label.className = 'activity-item__label';
    label.textContent = item.label;
    row.append(marker, label);
    if (item.timestamp) {
      const timestamp = document.createElement('span');
      timestamp.className = 'activity-item__time';
      timestamp.textContent = item.timestamp.toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
      });
      row.append(timestamp);
    }
    container.append(row);
  }
}

function renderLiveActivity() {
  if (!elements.liveActivityList) {
    return;
  }
  renderActivityItems(
    elements.liveActivityList,
    state.activity,
    'Waiting for runtime activity…',
  );
  elements.liveRunLabel.textContent = 'Analyzing';
}

function addActivity(event) {
  const label = activityLabel(event);
  if (!label) {
    return;
  }
  state.activity.push({
    label,
    state: text(event.state, 'started'),
    timestamp: new Date(),
  });
  renderLiveActivity();
}

function drawerData() {
  const result = state.drawerResult || state.latestResult;
  const evidence = evidenceForResult(result);
  const activity = result ? activityFromResult(result) : state.activity;
  return { result, evidence, activity };
}

function renderDrawerRun(result) {
  elements.drawerRun.replaceChildren();
  const heading = document.createElement('div');
  heading.className = 'drawer-section-heading';
  heading.textContent = 'Execution summary';
  elements.drawerRun.append(heading);

  const metrics = document.createElement('dl');
  metrics.className = 'run-metrics';
  const execution = result?.execution || {};
  const values = [
    ['Status', text(result?.status, state.running ? 'running' : '—')],
    ['Iterations', result?.iterations_used],
    ['Tool calls', result?.tool_calls_used],
    ['Tool errors', result?.tool_errors_used],
    ['Elapsed', execution.elapsed_ms === undefined ? null : execution.elapsed_ms + ' ms'],
    ['Decision calls', execution.decision_llm_calls],
  ];
  for (const [label, value] of values) {
    const term = document.createElement('dt');
    term.textContent = label;
    const detail = document.createElement('dd');
    detail.textContent = value === null || value === undefined ? '—' : String(value);
    metrics.append(term, detail);
  }
  elements.drawerRun.append(metrics);

  if (result?.reason_code || result?.failure_code) {
    const details = document.createElement('div');
    details.className = 'drawer-run-details';
    if (result.reason_code) {
      details.append('Reason: ' + result.reason_code);
    }
    if (result.failure_code) {
      if (details.childNodes.length) {
        details.append(document.createTextNode(' · '));
      }
      details.append('Failure: ' + result.failure_code);
    }
    elements.drawerRun.append(details);
  }
}

function renderDrawer() {
  const { result, evidence, activity } = drawerData();
  elements.drawerSourcesCount.textContent = String(evidence.length);
  elements.drawerActivityCount.textContent = String(activity.length);
  elements.drawerSources.replaceChildren();
  elements.drawerActivity.replaceChildren();

  const sourcesHeading = document.createElement('div');
  sourcesHeading.className = 'drawer-section-heading';
  sourcesHeading.textContent = evidence.length
    ? 'Public evidence'
    : 'No public evidence';
  elements.drawerSources.append(sourcesHeading);
  appendEvidence(elements.drawerSources, evidence, state.drawerEvidenceId);

  const activityHeading = document.createElement('div');
  activityHeading.className = 'drawer-section-heading';
  activityHeading.textContent = 'Execution trace';
  const activityList = document.createElement('ol');
  activityList.className = 'activity-list activity-list--drawer';
  elements.drawerActivity.append(activityHeading, activityList);
  renderActivityItems(activityList, activity, 'No activity recorded.');

  renderDrawerRun(result);
  for (const button of elements.drawerTabs) {
    const selected = button.dataset.drawerTab === state.drawerTab;
    button.classList.toggle('is-active', selected);
    button.setAttribute('aria-selected', String(selected));
  }
  elements.drawerSources.hidden = state.drawerTab !== 'sources';
  elements.drawerActivity.hidden = state.drawerTab !== 'activity';
  elements.drawerRun.hidden = state.drawerTab !== 'run';

  if (state.drawerOpen && state.drawerTab === 'sources' && state.drawerEvidenceId) {
    window.requestAnimationFrame(() => {
      const selected = document.querySelector(
        '#evidence-' + evidenceId(state.drawerEvidenceId),
      );
      selected?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    });
  }
}

function openDrawer(tab = 'sources', result = null, selectedEvidenceId = '') {
  window.clearTimeout(state.drawerHighlightTimer);
  state.drawerOpen = true;
  state.drawerTab = tab;
  state.drawerResult = result || state.latestResult || null;
  state.drawerEvidenceId = selectedEvidenceId || '';
  document.querySelector('.app-shell').classList.add('drawer-open');
  elements.drawer.setAttribute('aria-hidden', 'false');
  renderDrawer();
  if (selectedEvidenceId) {
    state.drawerHighlightTimer = window.setTimeout(() => {
      state.drawerEvidenceId = '';
      renderDrawer();
    }, 850);
  }
}

function closeDrawer() {
  window.clearTimeout(state.drawerHighlightTimer);
  state.drawerOpen = false;
  state.drawerEvidenceId = '';
  document.querySelector('.app-shell').classList.remove('drawer-open');
  elements.drawer.setAttribute('aria-hidden', 'true');
}

function buildAssistantActions(result) {
  const evidence = Array.isArray(result?.evidence) ? result.evidence : [];
  const activity = activityFromResult(result);
  const actions = document.createElement('nav');
  actions.className = 'assistant-actions';
  actions.setAttribute('aria-label', 'Answer details');

  const makeAction = (label, value, tab, disabled = false) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'assistant-action';
    button.disabled = disabled;
    button.append(label + (value === null ? '' : ' ' + value));
    button.addEventListener('click', () => openDrawer(tab, result));
    return button;
  };

  actions.append(
    makeAction('Sources', evidence.length, 'sources', evidence.length === 0),
    makeAction('Activity', activity.length, 'activity'),
    makeAction('Run', null, 'run'),
  );
  return actions;
}

function renderEmptyState() {
  const empty = document.createElement('div');
  empty.className = 'empty-chat';
  const mark = document.createElement('div');
  mark.className = 'empty-chat__mark';
  mark.setAttribute('aria-hidden', 'true');
  mark.textContent = '↗';
  const heading = document.createElement('h2');
  heading.textContent = 'Ask about this project';
  const copy = document.createElement('p');
  copy.textContent = 'Explore the repository with evidence-grounded answers.';
  empty.append(mark, heading, copy);
  return empty;
}

function renderMessages() {
  elements.messages.replaceChildren();
  if (!state.messages.length) {
    elements.messages.append(renderEmptyState());
    return;
  }

  for (const message of state.messages) {
    const row = document.createElement('article');
    row.className =
      'message-row message-row--'
      + (message.role === 'user' ? 'user' : 'assistant');
    const bubble = document.createElement('div');
    bubble.className = 'message-bubble';

    if (message.role === 'assistant') {
      const author = document.createElement('div');
      author.className = 'message-author';
      author.textContent = 'Engineering Agent';
      bubble.append(author);
    }

    const content = document.createElement('div');
    content.className = 'message-content';
    renderMessageContent(content, message);
    bubble.append(content);

    const result = resultForMessage(message);
    if (result && !message.pending) {
      bubble.append(buildAssistantActions(result));
    }
    row.append(bubble);
    elements.messages.append(row);
  }
  elements.messages.scrollTop = elements.messages.scrollHeight;
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
    state.drawerResult = state.latestResult;
    state.drawerEvidenceId = '';
  }
  const title = text(detail.title, '');
  elements.conversationTitle.textContent =
    title && title !== 'New conversation' ? title : 'Engineering Agent';
  elements.projectName.textContent = text(detail.project_name, 'Project');
  renderMessages();
  renderLiveActivity();
  renderDrawer();
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
    closeDrawer();
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
    state.drawerResult = null;
    closeDrawer();
    clearRunError();
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

function markPendingError(message, detail) {
  const pending = state.messages[state.messages.length - 1];
  if (pending && pending.role === 'assistant') {
    pending.error = message;
    pending.errorDetail = detail;
    pending.pending = false;
  }
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
  state.drawerResult = null;
  closeDrawer();
  elements.messageInput.value = '';
  setRunning(true);
  renderMessages();
  renderLiveActivity();

  let finalResult = null;
  let streamError = null;
  try {
    await api.streamConversation(
      state.activeConversationId,
      message,
      async (eventPayload) => {
        if (eventPayload.type === 'status') {
          addActivity(eventPayload);
          return;
        }
        if (eventPayload.type === 'evidence') {
          if (eventPayload.evidence) {
            state.evidence.push(eventPayload.evidence);
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
          state.drawerResult = finalResult;
          state.evidence = Array.isArray(finalResult?.evidence)
            ? finalResult.evidence
            : state.evidence;
          updatePendingAssistant(statusMessage(finalResult), finalResult);
          renderMessages();
          renderDrawer();
          return;
        }
        if (eventPayload.type === 'error') {
          streamError = {
            message: 'Unable to complete this request.',
            detail: text(eventPayload.code),
          };
          updatePendingAssistant('');
          markPendingError(streamError.message, streamError.detail);
          renderMessages();
        }
      },
    );

    if (finalResult && state.activeConversationId) {
      await loadConversation(state.activeConversationId, { keepRunPanels: true });
    }
    setRunning(false);
    if (streamError && !finalResult) {
      setRunError('Error');
      renderMessages();
      renderDrawer();
      return;
    }
    setTerminalRunState(finalResult);
  } catch (error) {
    setRunning(false);
    if (finalResult) {
      setTerminalRunState(finalResult);
      showToast('The answer arrived, but history could not be refreshed.', {
        error: true,
      });
      return;
    }
    markPendingError(userFacingError(error), errorDetails(error));
    setRunError('Unavailable');
    renderMessages();
    renderDrawer();
    showToast(userFacingError(error), { error: true });
  }
}

async function boot() {
  elements.composer.addEventListener('submit', sendMessage);
  elements.newConversation.addEventListener('click', createConversation);
  elements.drawerClose.addEventListener('click', closeDrawer);
  for (const button of elements.drawerTabs) {
    button.addEventListener('click', () => {
      state.drawerTab = button.dataset.drawerTab;
      state.drawerOpen = true;
      renderDrawer();
    });
  }
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
  elements.messageInput.addEventListener('input', () => {
    resizeComposer();
    updateComposerState();
  });
  elements.messageInput.addEventListener('focus', resizeComposer);
  updateComposerState();
  renderDrawer();

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
