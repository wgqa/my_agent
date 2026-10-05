import { api, ApiError } from './api.js';

const MAX_FILE_BYTES = 20 * 1024 * 1024;
const EXTENSIONS = new Set(['txt', 'md', 'pdf', 'py', 'js', 'java']);

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function formatSize(bytes) {
  return bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KB` : `${(bytes / 1048576).toFixed(1)} MB`;
}

function formatDate(value) {
  return new Date(value).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}

function errorMessage(error) {
  if (error instanceof ApiError) {
    if (error.status === 409) return '当前操作存在冲突：' + error.detail;
    if (error.status === 400 || error.status === 413 || error.status === 422) return '文件未能导入：' + error.detail;
    if (error.status === 404) return '这篇文档已不存在，请刷新知识库。';
    if (error.status === 503) return '知识库暂时不可用，请检查后端服务。';
  }
  return '操作未完成，请检查服务连接后重试。';
}

export function initKnowledgeBase({ onOpen, isRunning }) {
  const find = (id) => document.getElementById(id);
  const view = find('knowledge-view');
  const chat = document.querySelector('.chat-column');
  const navigation = find('open-knowledge');
  const list = find('knowledge-documents');
  const preview = find('knowledge-preview');
  const feedback = find('knowledge-feedback');
  const upload = find('knowledge-upload');
  const refresh = find('knowledge-refresh');
  const search = find('knowledge-search');
  const dialog = find('knowledge-delete-dialog');
  const previous = find('knowledge-previous');
  const next = find('knowledge-next');
  let documents = [];
  let selected = null;
  let offset = 0;
  let total = 0;
  let query = '';
  let busy = false;
  let loadSequence = 0;
  let previewSequence = 0;
  let searchTimer;
  let pendingDelete = null;

  const notify = (message, error = false) => {
    feedback.textContent = message;
    feedback.hidden = false;
    feedback.classList.toggle('is-error', error);
  };

  const controls = () => {
    upload.disabled = busy;
    refresh.disabled = busy;
    search.disabled = busy;
    previous.disabled = busy || offset === 0;
    next.disabled = busy || offset + 50 >= total;
    for (const button of preview.querySelectorAll('button')) button.disabled = busy;
  };

  const setBusy = (value) => { busy = value; controls(); };

  function emptyPreview() {
    preview.replaceChildren();
    const empty = node('div', 'knowledge-preview-empty');
    empty.append(node('span', '', '▤'), node('h2', '', '选择一篇文档'), node('p', '', '在这里查看正文、替换文件或删除文档。'));
    preview.append(empty);
  }

  function renderList() {
    list.replaceChildren();
    if (!documents.length) {
      const empty = node('div', 'knowledge-list-empty');
      empty.append(node('h2', '', query ? '没有匹配的文档' : '知识库还是空的'),
                   node('p', '', query ? '换个文档名试试，问答仍会检索整个知识库。' : '上传第一篇文档，导入后即可用于问答。'));
      list.append(empty);
    }
    for (const document of documents) {
      const button = node('button', 'knowledge-document');
      button.type = 'button';
      button.classList.toggle('is-selected', document.id === selected?.id);
      button.setAttribute('aria-pressed', String(document.id === selected?.id));
      const badge = node('span', 'knowledge-file-badge', document.file_type.toUpperCase());
      const description = node('span', 'knowledge-document-description');
      description.append(node('strong', '', document.name), node('span', '', `${formatSize(document.size_bytes)} · ${document.chunk_count} 个分块 · 已可检索`));
      button.append(badge, description, node('time', 'knowledge-document-date', formatDate(document.updated_at)));
      button.addEventListener('click', () => selectDocument(document.id));
      list.append(button);
    }
    find('knowledge-page-label').textContent = total ? `${offset + 1}–${Math.min(offset + 50, total)} / ${total} 篇` : '0 篇文档';
    controls();
  }

  async function loadDocuments({ preserveFeedback = false } = {}) {
    const sequence = ++loadSequence;
    if (!preserveFeedback) feedback.hidden = true;
    try {
      const result = await api.listKnowledgeDocuments({ query, offset });
      if (sequence !== loadSequence) return;
      if (offset && !result.items.length) { offset = Math.max(0, offset - 50); return loadDocuments({ preserveFeedback }); }
      documents = result.items;
      total = result.total;
      find('knowledge-counts').textContent = `${result.file_count} 篇文档 · ${result.chunk_count} 个分块 · 全库检索`;
      renderList();
    } catch (error) {
      if (sequence !== loadSequence) return;
      notify(errorMessage(error), true);
      list.replaceChildren(node('div', 'knowledge-list-empty', '无法读取文档列表。可以点击刷新重试。'));
      find('knowledge-counts').textContent = '知识库未连接';
    }
  }

  function renderPreview() {
    preview.replaceChildren();
    if (!selected) return emptyPreview();
    const heading = node('div', 'knowledge-preview-heading');
    const title = node('div');
    title.append(node('span', 'knowledge-eyebrow', 'DOCUMENT'), node('h2', '', selected.name),
                 node('p', '', `${formatSize(selected.size_bytes)} · ${selected.chunk_count} 个分块 · 更新于 ${formatDate(selected.updated_at)}`));
    const actions = node('div', 'knowledge-preview-actions');
    const replace = node('button', 'library-button', '替换文件');
    replace.type = 'button';
    replace.addEventListener('click', () => find('knowledge-replace-file').click());
    const remove = node('button', 'library-button library-button-danger-outline', '删除');
    remove.type = 'button';
    remove.addEventListener('click', () => {
      if (busy) return;
      pendingDelete = { id: selected.id, name: selected.name };
      find('knowledge-delete-description').textContent = `即将删除「${selected.name}」。`;
      dialog.returnValue = '';
      dialog.showModal();
    });
    actions.append(replace, remove);
    heading.append(title, actions);
    const label = node('div', 'knowledge-preview-label', `文本预览 · 已显示 ${selected.offset + selected.content.length} / ${selected.content_length} 字符`);
    const content = node('pre', 'knowledge-content', selected.content);
    preview.append(heading, label, content);
    if (selected.next_offset !== null) {
      const more = node('button', 'library-button knowledge-load-more', '加载更多正文');
      more.type = 'button';
      more.addEventListener('click', async () => {
        const id = selected.id;
        const sequence = previewSequence;
        more.disabled = true;
        try {
          const result = await api.getKnowledgeDocument(id, selected.next_offset);
          if (sequence !== previewSequence || selected?.id !== id) return;
          if (result.updated_at !== selected.updated_at) {
            notify('文档已更新，正在重新加载最新正文。');
            await selectDocument(id);
            return;
          }
          selected.content += result.content;
          selected.next_offset = result.next_offset;
          renderPreview();
        } catch (error) { notify(errorMessage(error), true); more.disabled = false; }
      });
      preview.append(more);
    }
    controls();
  }

  async function selectDocument(id) {
    if (busy) return;
    const sequence = ++previewSequence;
    preview.replaceChildren(node('div', 'knowledge-preview-empty', '正在读取正文…'));
    try {
      const document = await api.getKnowledgeDocument(id);
      if (sequence !== previewSequence) return;
      selected = document;
      renderPreview();
      renderList();
    } catch (error) {
      if (sequence !== previewSequence) return;
      selected = null;
      emptyPreview();
      notify(errorMessage(error), true);
    }
  }

  async function uploadFiles(files, documentId = null) {
    if (busy || !files.length) return;
    if (isRunning()) return notify('请等待当前问答结束后再更新知识库。', true);
    const errors = [];
    const completed = [];
    ++previewSequence;
    setBusy(true);
    for (const file of files) {
      if (!EXTENSIONS.has(file.name.split('.').pop().toLowerCase())) { errors.push(`${file.name}：不支持的文件类型`); continue; }
      if (!file.size || file.size > MAX_FILE_BYTES) { errors.push(`${file.name}：文件为空或超过 20 MiB`); continue; }
      notify(`正在导入 ${file.name}…`);
      try {
        const result = await api.uploadKnowledgeDocument(file, documentId);
        completed.push(result);
      } catch (error) { errors.push(`${file.name}：${errorMessage(error)}`); }
    }
    query = '';
    search.value = '';
    offset = 0;
    await loadDocuments({ preserveFeedback: true });
    setBusy(false);
    if (completed.length) await selectDocument(completed.at(-1).document.id);
    const statuses = { create: '已上传并可检索', update: '已更新并可检索', no_change: '内容未变化，无需更新' };
    const message = completed.map((result) => `${result.document.name}：${statuses[result.status]}`).concat(errors).join('；');
    notify(message, errors.length > 0);
  }

  function close() {
    if (busy) return;
    view.hidden = true;
    chat.hidden = false;
    navigation.classList.remove('is-active');
    navigation.setAttribute('aria-expanded', 'false');
    if (window.location.hash === '#knowledge') window.history.replaceState(null, '', window.location.pathname + window.location.search);
  }

  async function open() {
    if (isRunning()) return;
    onOpen();
    chat.hidden = true;
    view.hidden = false;
    navigation.classList.add('is-active');
    navigation.setAttribute('aria-expanded', 'true');
    window.history.replaceState(null, '', window.location.pathname + window.location.search + '#knowledge');
    await loadDocuments();
  }

  navigation.addEventListener('click', open);
  find('knowledge-back').addEventListener('click', close);
  find('new-conversation').addEventListener('click', close, { capture: true });
  find('conversation-list').addEventListener('click', close, { capture: true });
  upload.addEventListener('click', () => find('knowledge-file').click());
  find('knowledge-file').addEventListener('change', (event) => {
    const files = Array.from(event.target.files);
    event.target.value = '';
    uploadFiles(files);
  });
  find('knowledge-replace-file').addEventListener('change', (event) => {
    const files = Array.from(event.target.files);
    event.target.value = '';
    if (selected) uploadFiles(files, selected.id);
  });
  dialog.addEventListener('close', async () => {
    const document = pendingDelete;
    pendingDelete = null;
    if (dialog.returnValue !== 'delete' || !document || busy) return;
    if (isRunning()) return notify('请等待当前问答结束后再删除文档。', true);
    ++previewSequence;
    setBusy(true);
    try {
      await api.deleteKnowledgeDocument(document.id);
      if (selected?.id === document.id) { selected = null; emptyPreview(); }
      await loadDocuments({ preserveFeedback: true });
      notify(`已删除 ${document.name}，后续问答不再检索这篇文档。`);
    } catch (error) { notify(errorMessage(error), true); }
    finally { setBusy(false); }
  });
  refresh.addEventListener('click', async () => {
    await loadDocuments();
    if (selected) await selectDocument(selected.id);
  });
  search.addEventListener('input', () => {
    window.clearTimeout(searchTimer);
    searchTimer = window.setTimeout(() => { query = search.value.trim(); offset = 0; loadDocuments(); }, 220);
  });
  previous.addEventListener('click', () => { offset = Math.max(0, offset - 50); loadDocuments(); });
  next.addEventListener('click', () => { offset += 50; loadDocuments(); });
  if (window.location.hash === '#knowledge') open();
  return { open, close };
}
