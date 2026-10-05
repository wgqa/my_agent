import { api, ApiError } from './api.js';

export function initProjectDialog({ getActiveProjectId, onCreate, isRunning }) {
  const dialog = document.getElementById('new-chat-dialog');
  const form = document.getElementById('new-chat-form');
  const select = document.getElementById('new-chat-project');
  const path = document.getElementById('new-chat-path');
  const feedback = document.getElementById('new-chat-feedback');
  const add = document.getElementById('new-chat-add-project');
  const cancel = document.getElementById('new-chat-cancel');
  const create = document.getElementById('new-chat-create');
  let busy = false;
  let projects = [];

  function notice(message, error = false) {
    feedback.textContent = message;
    feedback.hidden = !message;
    feedback.classList.toggle('is-error', error);
  }

  function setBusy(value) {
    busy = value;
    select.disabled = value;
    path.disabled = value;
    add.disabled = value;
    cancel.disabled = value;
    create.disabled = value || !projects.some(project => project.id === select.value && project.available);
  }

  function errorMessage(error) {
    if (error instanceof ApiError && error.status === 400) return error.detail;
    if (error instanceof ApiError && error.status === 409) return '这个项目目录已不可用，请选择其他项目。';
    if (error instanceof ApiError && error.status === 404) return '所选项目已不存在，请重新打开此窗口。';
    return '操作未完成，请检查后端连接后重试。';
  }

  function renderProjects(selectedId) {
    select.replaceChildren();
    for (const project of projects) {
      const option = document.createElement('option');
      option.value = project.id;
      const duplicate = projects.filter(item => item.project_name === project.project_name).length > 1;
      option.textContent = project.project_name + (duplicate ? ` · ${project.id.slice(0, 6)}` : '')
        + (project.is_default ? '（默认项目）' : '') + (!project.available ? '（目录不可用）' : '');
      option.disabled = !project.available;
      select.append(option);
    }
    const chosen = projects.find(project => project.id === selectedId && project.available)
      || projects.find(project => project.is_default && project.available)
      || projects.find(project => project.available);
    if (chosen) select.value = chosen.id;
    setBusy(busy);
  }

  async function addProject() {
    const localPath = path.value.trim();
    if (!localPath) throw new ApiError('input_error', '请输入项目目录。', { status: 400, detail: '请输入本机项目的完整目录路径。' });
    const project = await api.addLocalProject(localPath);
    projects = [project, ...projects.filter(item => item.id !== project.id)];
    renderProjects(project.id);
    path.value = '';
    notice(`已选择 ${project.project_name}。`);
    return project.id;
  }

  async function open() {
    if (isRunning() || dialog.open) return;
    path.value = '';
    projects = [];
    select.replaceChildren();
    notice('正在读取项目…');
    setBusy(true);
    dialog.showModal();
    try {
      const result = await api.listLocalProjects();
      projects = result.projects;
      renderProjects(getActiveProjectId());
      notice('');
    } catch (error) { notice(errorMessage(error), true); }
    finally { setBusy(false); }
  }

  cancel.addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  select.addEventListener('change', () => setBusy(busy));
  add.addEventListener('click', async () => {
    if (busy) return;
    setBusy(true);
    notice('正在检查项目目录…');
    try { await addProject(); }
    catch (error) { notice(errorMessage(error), true); }
    finally { setBusy(false); }
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || isRunning()) return;
    setBusy(true);
    notice('正在创建对话…');
    try {
      const projectId = path.value.trim() ? await addProject() : select.value;
      if (!projectId) return notice('请先添加或选择一个本地项目。', true);
      if (await onCreate(projectId)) dialog.close();
    } catch (error) { notice(errorMessage(error), true); }
    finally { setBusy(false); }
  });
  return { open };
}
