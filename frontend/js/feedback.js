// Presentation only: never fabricate an answer, infer missing facts or resend.
export function resultFeedback(result) {
  if (!['refused', 'failed'].includes(result?.status)) return null;
  const supplied = result.feedback;
  if (typeof supplied?.title === 'string' && typeof supplied.message === 'string'
      && Array.isArray(supplied.next_steps) && supplied.next_steps.every(step => typeof step === 'string')) {
    return { ...supplied, action: result.reason_code !== 'UNSAFE_REQUEST'
      && ['revise', 'retry'].includes(supplied.action) ? supplied.action : null };
  }
  return {
    title: result.status === 'refused' ? '暂时无法给出可靠结论' : '本次分析未完成',
    message: '系统未能完成这次请求。',
    next_steps: ['请确认项目与问题范围，补充更具体的背景或相关资料。'],
    action: result.reason_code === 'UNSAFE_REQUEST' ? null : 'revise',
  };
}

export function feedbackText(feedback) {
  return [feedback.title, feedback.message, ...feedback.next_steps.map(step => '建议：' + step)].join('\n');
}

export function requestFeedback(error) {
  const status = error?.status;
  const kind = error?.kind;
  if (status === 409) return {
    title: '绑定的项目目录不可用', message: '当前对话绑定的本地目录已无法访问。',
    next_steps: ['恢复原目录，或新建对话选择一个可用的本地项目。'], action: null,
  };
  if (status === 404) return {
    title: '会话或项目已不可用', message: '当前会话或其项目登记不存在。',
    next_steps: ['刷新会话列表；必要时新建对话并重新选择项目。'], action: null,
  };
  if (status === 503 && error.detail === 'Engineering run at capacity; retry shortly') return {
    title: '服务正在处理其他任务', message: '当前可同时处理的任务数量已满，本次请求未开始分析。',
    next_steps: ['等待正在运行的任务完成后，再手动发送问题。'], action: 'retry',
  };
  if (status === 503) return {
    title: '分析服务暂时不可用', message: '分析服务当前未能处理这次请求。',
    next_steps: ['检查后端是否完成启动，以及模型与知识库配置是否可用；恢复后再发送问题。'], action: 'retry',
  };
  if (status === 422 || status === 400) return {
    title: '输入需要调整', message: '这次提交的内容未通过请求校验。',
    next_steps: ['检查问题是否为空或过长，确认所选项目有效后再发送。'], action: 'revise',
  };
  if (kind === 'cancelled') return {
    title: '请求已停止', message: '页面停止了这次请求。',
    next_steps: ['重新发送前，先刷新会话确认是否已有保存的结果。'], action: 'retry',
  };
  if (kind === 'timeout' || status === 504) return {
    title: '等待结果超时', message: '页面未能及时收到完整结果。',
    next_steps: ['先刷新会话检查已保存的结果，再决定是否重新发送或缩小问题范围。'], action: 'retry',
  };
  if (kind === 'connection_error') return {
    title: '后端连接中断', message: '页面无法连接后端，暂时不能确认这次请求的结果。',
    next_steps: ['检查后端连接；恢复后刷新会话，确认是否已保存，再决定是否重新发送。'], action: 'retry',
  };
  return {
    title: '未能收到完整结果', message: '本次结果接收未完成，暂时不能确认是否已保存。',
    next_steps: ['先刷新会话检查历史；如果没有保存的结果，再手动重新发送。'], action: 'retry',
  };
}

export function requestDiagnostic(error) {
  // Raw HTTP detail and browser exception text may contain private paths.
  const parts = [];
  if (Number.isInteger(error?.status)) parts.push('HTTP ' + error.status);
  const knownKinds = ['connection_error', 'timeout', 'http_error', 'invalid_response', 'cancelled', 'stream_error'];
  if (knownKinds.includes(error?.kind)) parts.push(error.kind);
  return parts.join(' · ');
}
