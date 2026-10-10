// Presentation of the public v2 activity contract; no model reasoning or raw observations.
export const ACTIVITY_EVENT_TYPES = new Set(['run_started', 'activity', 'evidence_added', 'verification']);

const KINDS = {
  knowledge: '知识库资料', project_code: '项目源码', project_doc: '项目文档',
  project_change: '代码变更', project_test: '测试文件',
  tool_result: '工具查询结果',
};
const TOOLS = {
  knowledge_search: '搜索知识库', code_search: '搜索项目文件',
  read_project_context: '读取项目内容', changed_files: '查看变更文件',
  git_diff: '读取代码差异', find_tests: '查找相关测试', calculator: '计算',
  get_project_info: '查询项目绑定',
};
const STATES = { started: '进行中', completed: '已完成', error: '工具出错', blocked: '等待补充资料' };
const positive = value => Number.isInteger(value) && value > 0;
const nonnegative = value => Number.isInteger(value) && value >= 0;
const nonempty = value => typeof value === 'string' && Boolean(value.trim());
const object = value => Boolean(value) && typeof value === 'object' && !Array.isArray(value);
const evidenceId = value => typeof value === 'string' && /^E[1-9]\d*$/.test(value);

export function isActivityEvent(event) {
  if (!object(event)) return false;
  if (event.type === 'run_started') {
    return event.execution_model === 'single_agent' && nonnegative(event.available_tool_count);
  }
  if (event.type === 'activity') {
    return typeof event.activity_id === 'string' && /^A[1-9]\d*$/.test(event.activity_id)
      && positive(event.iteration) && nonempty(event.tool_name)
      && ['started', 'completed', 'error'].includes(event.state) && nonempty(event.purpose)
      && (event.target === undefined || object(event.target))
      && (event.result_summary === undefined || object(event.result_summary))
      && (event.evidence_ids_added === undefined
        || (Array.isArray(event.evidence_ids_added) && event.evidence_ids_added.every(evidenceId)));
  }
  if (event.type === 'evidence_added') {
    if (!evidenceId(event.evidence_id) || !Object.hasOwn(KINDS, event.kind)) return false;
    if (event.kind === 'tool_result') return event.schema_version === 'engineering_tool_result_evidence_v1'
      && Object.hasOwn(TOOLS, event.tool_name)
      && ['locator_set', 'change_list', 'test_candidates', 'calculation', 'project_binding', 'reader_locator'].includes(event.result_type);
    return event.kind === 'knowledge' ? nonempty(event.source_name)
      : nonempty(event.path) && positive(event.start_line) && positive(event.end_line)
        && event.end_line >= event.start_line;
  }
  return event.type === 'verification' && event.state === 'blocked' && positive(event.iteration)
    && Array.isArray(event.missing_evidence_kinds)
    && event.missing_evidence_kinds.every(kind => Object.hasOwn(KINDS, kind));
}

function targetDetails(target = {}) {
  const details = [];
  if (nonempty(target.query)) details.push('关键词：' + target.query);
  if (nonempty(target.path)) details.push('目标：' + target.path
    + (positive(target.line) ? ':' + target.line : ''));
  if (nonempty(target.scope)) details.push('搜索范围：' + target.scope);
  if (Object.hasOwn(KINDS, target.artifact_kind)) details.push('文件类型：' + KINDS[target.artifact_kind]);
  if (nonempty(target.mode)) details.push('变更范围：' + ({ working_tree: '工作区', commit_range: '提交范围' }[target.mode] || target.mode));
  if (nonempty(target.expression)) details.push('表达式：' + target.expression);
  return details;
}

function resultDetails(summary = {}) {
  const details = [];
  if (nonnegative(summary.match_count)) details.push('找到 ' + summary.match_count + ' 处匹配');
  if (nonnegative(summary.file_count)) details.push('发现 ' + summary.file_count + ' 个变更文件');
  if (nonnegative(summary.test_file_count)) details.push('找到 ' + summary.test_file_count + ' 个测试文件');
  if (nonempty(summary.path) && positive(summary.start_line) && positive(summary.end_line)) {
    details.push('已读取：' + summary.path + ':' + summary.start_line + '–' + summary.end_line);
  }
  for (const key of ['top_paths', 'top_sources']) {
    if (Array.isArray(summary[key])) details.push(...summary[key].filter(nonempty));
  }
  if (typeof summary.result_preview === 'number' && Number.isFinite(summary.result_preview)) {
    details.push('结果：' + summary.result_preview);
  }
  if (summary.truncated === true) details.push('结果已截断，仅展示本次取得的范围');
  if (nonnegative(summary.document_entrypoint_count)) details.push('常见文档入口：' + summary.document_entrypoint_count + ' 个');
  if (typeof summary.available === 'boolean') details.push(summary.available ? '绑定目录可用' : '绑定目录当前不可用');
  return details;
}

export function activityItem(event) {
  if (!isActivityEvent(event)) return null;
  if (event.type === 'run_started') return {
    key: 'run', name: '开始分析', state: 'completed', stateLabel: '已开始',
    details: ['可用工具：' + event.available_tool_count], evidenceIds: [],
  };
  if (event.type === 'activity') return {
    key: event.activity_id, name: TOOLS[event.tool_name] || event.tool_name,
    state: event.state, stateLabel: STATES[event.state],
    details: [event.purpose, ...targetDetails(event.target), ...resultDetails(event.result_summary),
      ...(event.state === 'error' && nonempty(event.error_code) ? ['错误码：' + event.error_code] : [])],
    evidenceIds: event.evidence_ids_added || [],
  };
  if (event.type === 'evidence_added') return {
    key: event.evidence_id, name: '已取得资料 ' + event.evidence_id,
    state: 'completed', stateLabel: KINDS[event.kind],
    details: [event.kind === 'tool_result' ? TOOLS[event.tool_name] : event.kind === 'knowledge' ? event.source_name
      : event.path + ':' + event.start_line + '–' + event.end_line], evidenceIds: [event.evidence_id],
  };
  return {
    key: 'verification:' + event.iteration, name: '资料校验',
    state: 'blocked', stateLabel: STATES.blocked,
    details: event.missing_evidence_kinds.length
      ? ['仍需补充：' + event.missing_evidence_kinds.map(kind => KINDS[kind]).join('、')]
      : ['本轮结论暂未通过资料校验'], evidenceIds: [],
  };
}

export function updateActivity(items, event) {
  const item = activityItem(event);
  if (!item) return items;
  const index = items.findIndex(existing => existing.key === item.key);
  return index < 0 ? [...items, item] : items.map((existing, i) => i === index ? item : existing);
}

export function activityFromResult(result) {
  if (Array.isArray(result?.activity)) return result.activity.reduce(updateActivity, []);
  // Historic v1 chats retain only the reduced public trace. Do not invent details.
  if (!Array.isArray(result?.trace)) return [];
  return result.trace.map((event, index) => {
    if (event.event_type === 'tool_call_created' && nonempty(event.tool_name)) return {
      key: 'legacy:' + index, name: TOOLS[event.tool_name] || event.tool_name,
      state: 'started', stateLabel: STATES.started, details: [], evidenceIds: [],
    };
    if (event.event_type === 'tool_observation' && nonempty(event.tool_name)) {
      const state = event.tool_status === 'ok' ? 'completed' : 'error';
      return { key: 'legacy:' + index, name: TOOLS[event.tool_name] || event.tool_name,
        state, stateLabel: STATES[state], details: [], evidenceIds: [] };
    }
    if (event.event_type === 'finalization_guard_blocked') return {
      key: 'legacy:' + index, name: '资料校验', state: 'blocked',
      stateLabel: STATES.blocked, details: [], evidenceIds: [],
    };
    return null;
  }).filter(Boolean);
}
