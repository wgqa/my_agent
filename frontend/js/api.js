const DEFAULT_API_BASE = 'http://localhost:8000';
const STREAM_SCHEMA = 'engineering_query_stream_v1';

export class ApiError extends Error {
  constructor(kind, message, { status = null, detail = '' } = {}) {
    super(message);
    this.name = 'ApiError';
    this.kind = kind;
    this.status = status;
    this.detail = detail;
  }
}

function resolveApiBase() {
  const configured = window.ENGINEERING_API_BASE_URL;
  const queryValue = new URLSearchParams(window.location.search).get('api');
  const sameOrigin = ['http:', 'https:'].includes(window.location.protocol) ? window.location.origin : DEFAULT_API_BASE;
  return String(configured || queryValue || sameOrigin).replace(/\/+$/, '');
}

export const API_BASE_URL = resolveApiBase();

function projectQuery(projectId) {
  return projectId ? '?project_id=' + encodeURIComponent(projectId) : '';
}

async function parseResponseError(response) {
  let detail = '';
  try {
    const payload = await response.json();
    if (payload && typeof payload.detail !== 'undefined') {
      detail = String(payload.detail);
    }
  } catch (_error) {
    // The status itself is enough for the user-facing error.
  }

  if (response.status === 503) {
    return new ApiError(
      'http_error',
      'The service is temporarily busy.',
      { status: response.status, detail },
    );
  }
  if (response.status === 504) {
    return new ApiError(
      'timeout',
      'The request timed out.',
      { status: response.status, detail },
    );
  }
  return new ApiError(
    'http_error',
    'Unable to complete this request.',
    { status: response.status, detail },
  );
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(API_BASE_URL + path, {
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.body && !(options.body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
        ...(options.headers || {}),
      },
    });
  } catch (error) {
    if (error && error.name === 'AbortError') {
      throw new ApiError('cancelled', 'The request was cancelled.');
    }
    throw new ApiError(
      'connection_error',
      'Unable to reach the Engineering API.',
      { detail: error instanceof Error ? error.message : '' },
    );
  }

  if (!response.ok) {
    throw await parseResponseError(response);
  }
  if (response.status === 204) {
    return {};
  }
  try {
    return await response.json();
  } catch (_error) {
    throw new ApiError('invalid_response', 'The API returned an invalid response.');
  }
}

export const api = {
  knowledgeStatus() {
    return request('/engineering/knowledge');
  },

  listKnowledgeDocuments({ query = '', offset = 0, limit = 50 } = {}) {
    const params = new URLSearchParams({ q: query, offset: String(offset), limit: String(limit) });
    return request('/engineering/knowledge/documents?' + params);
  },

  getKnowledgeDocument(documentId, offset = 0) {
    return request('/engineering/knowledge/documents/' + encodeURIComponent(documentId) + '?offset=' + offset);
  },

  uploadKnowledgeDocument(file, documentId = null) {
    const body = new FormData();
    body.append('file', file);
    const suffix = documentId ? '/' + encodeURIComponent(documentId) : '';
    return request('/engineering/knowledge/documents' + suffix, { method: documentId ? 'PUT' : 'POST', body });
  },

  deleteKnowledgeDocument(documentId) {
    return request('/engineering/knowledge/documents/' + encodeURIComponent(documentId), { method: 'DELETE' });
  },

  listConversations() {
    return request('/engineering/conversations?scope=all');
  },

  listLocalProjects() {
    return request('/engineering/projects');
  },

  addLocalProject(path) {
    return request('/engineering/projects', { method: 'POST', body: JSON.stringify({ path }) });
  },

  createConversation(projectId = null) {
    return request('/engineering/conversations', {
      method: 'POST', ...(projectId ? { body: JSON.stringify({ project_id: projectId }) } : {}),
    });
  },

  getConversation(conversationId, projectId = null) {
    return request(
      '/engineering/conversations/' + encodeURIComponent(conversationId) + projectQuery(projectId),
    );
  },

  deleteConversation(conversationId, projectId = null) {
    return request(
      '/engineering/conversations/' + encodeURIComponent(conversationId) + projectQuery(projectId),
      { method: 'DELETE' },
    );
  },

  async streamConversation(conversationId, message, onEvent, projectId = null) {
    let response;
    try {
      response = await fetch(
        API_BASE_URL
          + '/engineering/conversations/'
          + encodeURIComponent(conversationId)
          + '/messages/stream/v1' + projectQuery(projectId),
        {
          method: 'POST',
          headers: {
            Accept: 'text/event-stream',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ message }),
        },
      );
    } catch (error) {
      throw new ApiError(
        'connection_error',
        'Unable to reach the Engineering API.',
        { detail: error instanceof Error ? error.message : '' },
      );
    }

    if (!response.ok) {
      throw await parseResponseError(response);
    }

    const contentType = response.headers.get('content-type') || '';
    const schema = response.headers.get('x-engineering-stream-schema') || '';
    if (!contentType.toLowerCase().startsWith('text/event-stream')) {
      throw new ApiError(
        'invalid_response',
        'The API returned an invalid stream.',
        { status: response.status },
      );
    }
    // Custom response headers are not readable from a cross-origin static
    // page unless the API exposes them. Content-Type plus the validated
    // event shape remains the public fallback; an explicitly visible,
    // incompatible schema still fails closed.
    if (schema && schema !== STREAM_SCHEMA) {
      throw new ApiError(
        'invalid_response',
        'The API returned an unknown stream protocol.',
        { status: response.status, detail: schema },
      );
    }
    if (!response.body) {
      throw new ApiError('invalid_response', 'The API returned an empty stream.');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let frame = [];
    let sawDone = false;
    let terminalEvent = null;
    let answerStarted = false;
    let answerBuffer = '';

    const dispatchFrame = async () => {
      if (!frame.length) {
        return;
      }
      const data = frame
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).replace(/^ /, ''))
        .join('\n');
      frame = [];
      if (!data) {
        return;
      }
      let event;
      try {
        event = JSON.parse(data);
      } catch (_error) {
        throw new ApiError('invalid_response', 'The API returned invalid stream data.');
      }
      if (!event || typeof event.type !== 'string') {
        throw new ApiError('invalid_response', 'The API returned an invalid stream event.');
      }
      if (sawDone) {
        throw new ApiError('invalid_response', 'The stream continued after completion.');
      }
      const invalid = () => new ApiError('invalid_response', 'The API returned an incomplete or inconsistent result.');
      if (!['status', 'evidence', 'answer_start', 'answer_delta', 'final', 'error', 'done'].includes(event.type)
          || (terminalEvent && event.type !== 'done')) throw invalid();
      if (event.type === 'answer_start') {
        if (answerStarted) throw invalid();
        answerStarted = true;
      }
      if (event.type === 'answer_delta') {
        if (!answerStarted || typeof event.delta !== 'string' || !event.delta) throw invalid();
        answerBuffer += event.delta;
      }
      if (event.type === 'final') {
        const result = event.result;
        if (!['completed', 'refused', 'failed'].includes(result?.status)) throw invalid();
        if (result.status === 'completed') {
          if (!answerStarted || typeof result.answer !== 'string' || result.answer !== answerBuffer) throw invalid();
        } else if (answerStarted || (result.answer !== null && result.answer !== undefined)) throw invalid();
        terminalEvent = 'final';
      }
      if (event.type === 'error') {
        if (answerStarted || typeof event.code !== 'string' || !event.code) throw invalid();
        terminalEvent = 'error';
      }
      if (event.type === 'done') {
        if (!terminalEvent) throw invalid();
        sawDone = true;
      }
      await onEvent(event);
    };

    const consumeLines = async (text) => {
      buffer += text;
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (line === '') {
          await dispatchFrame();
        } else if (!line.startsWith(':')) {
          frame.push(line);
        }
      }
    };

    try {
      while (true) {
        const { value, done } = await reader.read();
        if (done) {
          break;
        }
        await consumeLines(decoder.decode(value, { stream: true }));
      }
      await consumeLines(decoder.decode());
      if (buffer) {
        frame.push(buffer);
      }
      await dispatchFrame();
    } catch (error) {
      if (error instanceof ApiError) {
        throw error;
      }
      throw new ApiError(
        'invalid_response',
        'The Engineering stream ended unexpectedly.',
        { detail: error instanceof Error ? error.message : '' },
      );
    } finally {
      reader.releaseLock();
    }

    if (!sawDone) {
      throw new ApiError(
        'invalid_response',
        'The Engineering stream did not finish normally.',
      );
    }
  },
};
