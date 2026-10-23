// Pure helpers for the Sida screen: no DOM and no fetch, so `node --test` can check them.
// The data comes from the JSON API (docs/session-api.md, docs/settings-api.md).

export const PHASES = {
  analysis: '분석', concept: '개념', development: '발전', critique: '비평', communication: '전달',
};

export const STATUS_LABELS = {
  idle: '실행 전', running: '실행 중', review: '검토 필요', done: '완료',
};

export const PROVIDER_LABELS = {
  openrouter: 'OpenRouter (API 키)', ollama: 'Ollama (이 PC)', chatgpt: 'ChatGPT 구독',
};

export const MODE_LABELS = { cloud: '클라우드', local: '로컬', custom: '사용자 지정' };

export const STATE_UPDATE_LABELS = {
  ask: '승인 받고 반영', auto: '바로 반영', off: '반영 안 함',
};

// All text from the server or the designer passes through here before it becomes HTML.
export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c]);
}

function stamp(value) {
  const time = Date.parse(value || '');
  return Number.isFinite(time) ? time : 0;
}

export function findProjects(projects, query = '', sort = 'recent') {
  const term = query.trim().toLocaleLowerCase('ko');
  return projects
    .filter((p) => `${p.name} ${p.project_type || ''}`.toLocaleLowerCase('ko').includes(term))
    .sort((a, b) => (sort === 'name'
      ? a.name.localeCompare(b.name, 'ko')
      : stamp(b.updated_at) - stamp(a.updated_at)));
}

export function relativeDate(value, now = new Date()) {
  const time = stamp(value);
  if (!time) return '';
  const day = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const then = new Date(time);
  const days = Math.round((day(now) - day(then)) / 86400000);
  if (days === 0) return '오늘 수정';
  if (days === 1) return '어제 수정';
  return `${then.getMonth() + 1}월 ${then.getDate()}일 수정`;
}

export function projectSummary(project) {
  const done = (project.completed || []).length;
  if (!done) return '아직 실행한 전문가 없음';
  return `전문가 ${done}/${project.expert_count} 완료`;
}

// Stored chat entries (GET .../session or .../experts/{agent}/chat) → what the screen draws.
export function chatItems(messages) {
  const items = [];
  for (const m of messages || []) {
    if (m.role === 'user') items.push({ kind: 'user', text: m.text });
    else if (m.role === 'conductor' || m.role === 'expert') items.push({ kind: m.role, text: m.text });
    else if (m.role === 'system') {
      const name = m.name || m.agent || '전문가';
      if (m.event === 'module_completed') items.push({ kind: 'card', agent: m.agent, name });
      else if (m.event === 'run_requested') items.push({ kind: 'note', text: `${name} 실행을 요청했습니다.` });
      else if (m.event === 'read') items.push({ kind: 'note', text: `${name} 결과를 읽었습니다.` });
      else if (m.event === 'revised') items.push({ kind: 'note', text: '결과 문서를 고쳐 썼습니다.' });
    }
  }
  return items;
}

// A job event (GET .../session/jobs/{id}) → a progress line, and whether it also deserves a toast.
// conductor_reply and expert_reply are chat bubbles, not notices, so they return null.
export function eventNotice(event) {
  const data = event?.data || {};
  const name = data.agent?.name || data.agent?.id || '전문가';
  const notice = (text, tone = 'info', toast = false) => ({ text, tone, toast });
  switch (event?.kind) {
    case 'module_started': return notice(`${name} 실행을 시작합니다.`, 'info', true);
    case 'module_saved': return notice(`${name} 결과가 나왔습니다.`, 'success', true);
    case 'module_failed': return notice(`${name} 실행이 실패해 저장된 결과가 없습니다. ${data.reason || ''}`.trim(), 'error', true);
    case 'state_proposing': return notice(`${name} 결과에서 설계 상태에 반영할 내용을 정리하는 중입니다.`);
    case 'state_proposed': return notice(`${name} 결과를 설계 상태에 반영할지 검토해 주세요.`, 'warn', true);
    case 'state_applied': return notice(`${name} 결과를 설계 상태에 반영했습니다.`, 'success');
    case 'state_unchanged': return notice(`${name} 결과로 설계 상태에서 바뀔 내용은 없습니다.`);
    case 'state_failed': return notice(`설계 상태 반영안을 만들지 못했습니다. 결과 문서는 저장됐습니다. ${data.reason || ''}`.trim(), 'warn');
    case 'reading': return notice(`${data.file || '결과 문서'}를 읽는 중입니다.`);
    case 'read_failed': return notice(`결과 문서를 읽지 못했습니다. ${data.reason || ''}`.trim(), 'warn');
    case 'unknown_agent': return notice('Conductor가 없는 전문가를 불러서 실행하지 않았습니다.', 'warn');
    case 'action_recovered': return notice('Conductor 답에서 다음 동작을 다시 읽었습니다.');
    case 'conductor_error': return notice(`Conductor가 답하지 못했습니다. 이 메시지는 기록되지 않았으니 다시 보내 주세요. ${data.reason || ''}`.trim(), 'error', true);
    case 'notice': return notice(String(data.message || ''), 'warn');
    default: return null;
  }
}

// Panel status of one expert, with the running job taken into account.
export function expertStatus(expert, job) {
  if (job && job.running_agent === expert.id) return 'running';
  return expert.status || (expert.done ? 'done' : 'idle');
}

// ------------------------------------------------------------------ expert chats

// An expert has several chats ("01", "02", ...; expert.chats from GET .../session).
export const FIRST_CHAT = '01';

export function chatTitle(id) {
  return `분석 ${id || FIRST_CHAT}`;
}

// The chat an expert screen opens on when the address names none: the newest one.
export function latestChat(expert) {
  const chats = expert?.chats || [];
  return chats.length ? chats[chats.length - 1].id : FIRST_CHAT;
}

// One line in a chat list: "분석 02 · 첫 질문" or "분석 02 · 빈 대화".
export function chatLabel(chat) {
  return `${chatTitle(chat.id)} · ${chat.preview || '빈 대화'}`;
}

// ------------------------------------------------------------------ Markdown

function inline(text) {
  // `text` is already escaped; only these patterns turn back into tags.
  return text
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
}

function tableCells(line) {
  return line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => inline(c.trim()));
}

// A small Markdown subset for expert documents and Conductor replies: headings, paragraphs,
// lists, tables, quotes, code, rules, bold/italic/code/links. Everything is escaped first.
export function renderMarkdown(source) {
  const lines = escapeHtml(source).replace(/\r\n?/g, '\n').split('\n');
  const out = [];
  let paragraph = [];
  let list = null;
  const flush = () => {
    if (paragraph.length) out.push(`<p>${paragraph.map(inline).join('<br>')}</p>`);
    paragraph = [];
    if (list) out.push(`<${list.tag}>${list.items.map((i) => `<li>${inline(i)}</li>`).join('')}</${list.tag}>`);
    list = null;
  };
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flush();
      const code = [];
      for (i += 1; i < lines.length && !/^\s*```/.test(lines[i]); i += 1) code.push(lines[i]);
      out.push(`<pre><code>${code.join('\n')}</code></pre>`);
      continue;
    }
    const heading = line.match(/^(#{1,6})\s+(.*)$/);
    if (heading) {
      flush();
      const level = Math.min(heading[1].length + 1, 6);
      out.push(`<h${level}>${inline(heading[2])}</h${level}>`);
      continue;
    }
    if (/^\s*\|.*\|\s*$/.test(line) && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1] || '')) {
      flush();
      const head = tableCells(line);
      const rows = [];
      for (i += 2; i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i]); i += 1) rows.push(tableCells(lines[i]));
      i -= 1;
      out.push(`<div class="table-wrap"><table><thead><tr>${head.map((c) => `<th>${c}</th>`).join('')}</tr></thead>`
        + `<tbody>${rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`);
      continue;
    }
    if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push('<hr>'); continue; }
    const quote = line.match(/^\s*&gt;\s?(.*)$/);
    if (quote) { flush(); out.push(`<blockquote>${inline(quote[1])}</blockquote>`); continue; }
    const bullet = line.match(/^\s*[-*+]\s+(.*)$/);
    const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
    if (bullet || numbered) {
      const tag = bullet ? 'ul' : 'ol';
      if (paragraph.length || (list && list.tag !== tag)) flush();
      if (!list) list = { tag, items: [] };
      list.items.push((bullet || numbered)[1]);
      continue;
    }
    if (!line.trim()) { flush(); continue; }
    if (list) flush();
    paragraph.push(line.trim());
  }
  flush();
  return out.join('');
}
