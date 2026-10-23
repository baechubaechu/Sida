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

// Government data keys on the settings screen (ids of PUT /api/settings/keys/{key}).
// A secret key is never shown back, only whether it is set; the VWorld domain is shown in full.
export const DATA_KEYS = [
  { id: 'vworld', label: '브이월드 키', secret: true },
  { id: 'vworld_domain', label: '브이월드 등록 도메인', secret: false },
  { id: 'data_go_kr', label: '공공데이터포털 키', secret: true },
  { id: 'law', label: '법제처 인증값(OC)', secret: true },
];

// The keys to save: [id, value] for each one typed in (a shown value only when it changed).
export function keyChanges(draft, status = {}) {
  return DATA_KEYS
    .map(({ id, secret }) => [id, String(draft?.[id] ?? '').trim(), secret])
    .filter(([id, value, secret]) => value && (secret || value !== (status[id]?.value || '')))
    .map(([id, value]) => [id, value]);
}

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
    case 'run_skipped': return notice(data.reason === 'state_pending'
      ? `설계 상태 반영안을 먼저 검토해야 해서 ${name}은(는) 실행하지 않았습니다.`
      : `한 번에 실행하는 전문가 수(${data.limit || '?'}명)를 채워 ${name}은(는) 실행하지 않았습니다. 이어서 하려면 메시지를 보내 주세요.`, 'warn', true);
    case 'conductor_error': return data.after_run
      ? notice(`전문가 결과는 저장됐지만 Conductor가 이어서 답하지 못했습니다. ${data.reason || ''}`.trim(), 'warn', true)
      : notice(`Conductor가 답하지 못했습니다. 이 메시지는 기록되지 않았으니 다시 보내 주세요. ${data.reason || ''}`.trim(), 'error', true);
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

// Inline Markdown only (bold, code, links) for one line: a card or a list item.
export function renderInline(source) {
  return inline(escapeHtml(source));
}

// ------------------------------------------------------------------ addresses

export function projectPath(name) {
  return `#/project/${encodeURIComponent(name)}`;
}

// An expert page: tab 'doc' (result), 'chat' (an analysis chat) or 'versions' (earlier results).
export function expertPath(name, agent, tab = 'doc', id = '') {
  const rest = tab === 'doc' ? '' : `/${tab}${id ? `/${encodeURIComponent(id)}` : ''}`;
  return `${projectPath(name)}/expert/${encodeURIComponent(agent)}${rest}`;
}

const EXPERT_TABS = ['chat', 'versions'];

export function parseRoute(hash) {
  const parts = String(hash || '').replace(/^#\/?/, '').split('/').map((p) => {
    try { return decodeURIComponent(p); } catch { return ''; }
  });
  if (parts[0] === 'new') return { page: 'new' };
  if (parts[0] !== 'project' || !parts[1]) return { page: 'home' };
  const agent = parts[2] === 'expert' ? parts[3] || '' : '';
  const tab = agent && EXPERT_TABS.includes(parts[4]) ? parts[4] : 'doc';
  const id = tab === 'doc' ? '' : parts[5] || '';
  return {
    page: 'project', name: parts[1], agent, tab,
    chat: tab === 'chat' ? id : '', version: tab === 'versions' ? id : '',
  };
}

// "10월 1일 09:00", for result versions.
export function dateTime(value) {
  const time = stamp(value);
  if (!time) return '';
  const d = new Date(time);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getMonth() + 1}월 ${d.getDate()}일 ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

// ------------------------------------------------------------------ expert pages

// The "## " sections experts write (agents/*.md, Output Format), in Korean on screen.
export const SECTION_LABELS = {
  'Site Conditions': '대지 조건', 'Spatial Conflicts': '공간 충돌', Opportunities: '기회',
  'Missing Information': '부족한 정보', 'Design Implications': '설계 시사점', Handoff: '다음 전문가',
  'Users and Rhythms': '사용자와 리듬', 'Program Components': '프로그램 구성요소',
  'Adjacency and Separation': '인접과 분리', 'Public–Private Gradient': '공공–사적 단계', 'Area Logic': '면적 논리',
  'Governing Frameworks': '적용 법규', 'Items to Verify': '확인할 항목', 'Likely Binding Constraints': '구속할 제약',
  'Regulatory Opportunities': '법규상 기회', 'Design Consequences': '설계에 미치는 영향', 'Sources Used': '근거 출처',
  'Search Frame': '검색 틀', Precedents: '선례', 'Typological Patterns': '유형 패턴', 'What to Study Next': '다음에 볼 것',
  'Problem Restated': '문제 다시 쓰기', 'Concept Statement': '개념 문장', 'Operative Strategy': '작동 전략',
  'What the Concept Must Prove': '증명할 것', 'Risks of Cliché': '상투 위험', 'Alternative Framings': '대안 프레임',
  'Organization as Described': '설명된 조직', 'Circulation Logic': '동선', 'Sectional Logic': '단면',
  'Thresholds and Edges': '경계와 문턱', 'Program Fit': '프로그램 적합', 'Weak Points to Test': '시험할 약점',
  'Structural Questions': '구조', 'Envelope and Environment': '외피와 환경', 'Services and Egress': '설비와 피난',
  'Options and Trade-offs': '선택지 비교', 'Early Decisions That Lock Later Options': '지금 정해야 할 결정',
  'Strong Points': '강점', 'Unresolved Problems': '미해결 문제', Contradictions: '모순', Risks: '위험',
  'Next Actions': '다음 행동',
  'Essential Diagrams': '핵심 다이어그램', Drawings: '도면', 'Renders / Visuals': '렌더·이미지',
  'Model / Prototype': '모형', 'Presentation Hierarchy': '발표 위계',
  'One-line Summary': '한 줄 요약', 'Problem Statement': '문제', 'System Summary': '시스템 요약',
  'Key Outputs': '핵심 자료', 'Portfolio Section Structure': '포트폴리오 구성', 'Anticipated Questions': '예상 질문',
};

// Words the prompts ask experts to tag items with, shown as badges (tone = status-badge class).
const CERTAINTY_TAGS = [
  { word: /\bcertainly\b/i, ko: /확실/, label: '확실히 적용', tone: 'done' },
  { word: /\bprobably\b/i, ko: /아마|가능성/, label: '아마 적용', tone: 'review' },
  { word: /\bcheck\b/i, ko: /확인/, label: '적용 여부 확인', tone: 'idle' },
];
const SOURCE_TAGS = [
  { word: /\bbrief\b/i, ko: /브리프/, label: '브리프', tone: 'done' },
  { word: /\bcandidate\b/i, ko: /후보/, label: '후보', tone: 'review' },
  { word: /\bassumption\b/i, ko: /가정/, label: '가정', tone: 'idle' },
];
const FIT_TAGS = [
  { word: /\bunaddressed\b/i, ko: /다루지 않/, label: '다루지 않음', tone: 'idle' },
  { word: /\bviolated\b/i, ko: /어긋|위반/, label: '어긋남', tone: 'review' },
  { word: /\bhonored\b/i, ko: /충족|맞음/, label: '맞음', tone: 'done' },
];
const FRAMING_TAGS = [
  { word: /\badopt\b/i, ko: /채택/, label: '채택', tone: 'done' },
  { word: /\breject\b/i, ko: /버림|기각/, label: '버림', tone: 'idle' },
];
const VERIFY_TAGS = [{ word: /[\s\S]/, label: '사실 확인 필요', tone: 'review' }];

// Each expert's page: rows of sections, top first. `columns` sets sections side by side.
// kind: lead (large first line), cards, list, checklist, tagged (badge per item), table,
// steps (numbered order), qa (question that unfolds its answer). `top` marks the row shown first and large.
// Sections an expert wrote that are not listed here follow at the end as plain lists.
export const EXPERT_LAYOUTS = {
  site_reader: [
    { columns: ['Site Conditions', 'Spatial Conflicts', 'Opportunities'], kind: 'cards' },
    { section: 'Missing Information', kind: 'checklist' },
    { section: 'Design Implications', kind: 'list' },
  ],
  program_analyst: [
    { section: 'Users and Rhythms', kind: 'cards', top: true },
    { section: 'Program Components', kind: 'tagged', tags: SOURCE_TAGS },
    { columns: ['Adjacency and Separation', 'Public–Private Gradient'], kind: 'list' },
    { section: 'Area Logic', kind: 'list' },
    { section: 'Missing Information', kind: 'checklist' },
  ],
  regulation_checker: [
    { section: 'Items to Verify', kind: 'table', top: true },
    { section: 'Governing Frameworks', kind: 'tagged', tags: CERTAINTY_TAGS },
    { columns: ['Likely Binding Constraints', 'Regulatory Opportunities'], kind: 'cards' },
    { section: 'Design Consequences', kind: 'list' },
    { section: 'Sources Used', kind: 'list' },
  ],
  precedent_scout: [
    { section: 'Search Frame', kind: 'lead' },
    { section: 'Precedents', kind: 'tagged', tags: VERIFY_TAGS, cards: true },
    { section: 'Typological Patterns', kind: 'list' },
    { section: 'What to Study Next', kind: 'checklist' },
  ],
  concept_framer: [
    { section: 'Concept Statement', kind: 'lead' },
    { section: 'Problem Restated', kind: 'list' },
    { section: 'Operative Strategy', kind: 'cards' },
    { section: 'What the Concept Must Prove', kind: 'checklist' },
    { section: 'Risks of Cliché', kind: 'cards' },
    { section: 'Alternative Framings', kind: 'tagged', tags: FRAMING_TAGS },
  ],
  spatial_reviewer: [
    { section: 'Organization as Described', kind: 'lead' },
    { columns: ['Circulation Logic', 'Sectional Logic', 'Thresholds and Edges'], kind: 'cards' },
    { section: 'Program Fit', kind: 'tagged', tags: FIT_TAGS },
    { section: 'Weak Points to Test', kind: 'checklist' },
  ],
  systems_advisor: [
    { section: 'Early Decisions That Lock Later Options', kind: 'cards', top: true },
    { columns: ['Structural Questions', 'Envelope and Environment', 'Services and Egress'], kind: 'cards' },
    { section: 'Options and Trade-offs', kind: 'table' },
  ],
  design_critic: [
    { section: 'Next Actions', kind: 'checklist', top: true },
    { columns: ['Strong Points', 'Unresolved Problems'], kind: 'cards' },
    { columns: ['Contradictions', 'Risks'], kind: 'cards' },
  ],
  representation_planner: [
    { section: 'Presentation Hierarchy', kind: 'steps', top: true },
    { columns: ['Essential Diagrams', 'Drawings'], kind: 'cards' },
    { columns: ['Renders / Visuals', 'Model / Prototype'], kind: 'cards' },
  ],
  presentation_editor: [
    { section: 'One-line Summary', kind: 'lead' },
    { columns: ['Problem Statement', 'System Summary'], kind: 'list' },
    { section: 'Key Outputs', kind: 'cards' },
    { section: 'Portfolio Section Structure', kind: 'steps' },
    { section: 'Anticipated Questions', kind: 'qa' },
  ],
};

const headingKey = (text) => text.toLowerCase().replace(/[–—-]/g, '-').replace(/[^a-z0-9/ -]/g, '').replace(/\s+/g, ' ').trim();
const LABEL_BY_KEY = new Map(Object.entries(SECTION_LABELS).map(([heading, label]) => [headingKey(heading), label]));

// "## Heading" sections of an expert document, in order. Text before the first one (the "# Title"
// line aside) comes back as `intro`.
export function documentSections(markdown) {
  const sections = [];
  const intro = [];
  let current = null;
  let fence = false;
  for (const line of String(markdown || '').replace(/\r\n?/g, '\n').split('\n')) {
    if (/^\s*```/.test(line)) fence = !fence;
    const heading = !fence && line.match(/^##\s+(.+?)\s*#*\s*$/);
    if (heading) {
      current = { heading: heading[1], key: headingKey(heading[1]), lines: [] };
      sections.push(current);
    } else if (current) current.lines.push(line);
    else if (!/^#\s/.test(line)) intro.push(line);
  }
  return {
    intro: intro.join('\n').trim(),
    sections: sections.map(({ heading, key, lines }) => ({
      heading, key, label: LABEL_BY_KEY.get(key) || heading, body: lines.join('\n').trim(),
    })),
  };
}

// Top-level list items of a section ("- ", "* ", "1. "); lines under an item stay with it.
// A section without a list is one item. Placeholders like "-" or "(...)" are dropped.
export function listItems(body) {
  const items = [];
  for (const line of String(body || '').split('\n')) {
    const start = line.match(/^(?:[-*+]|\d+[.)])\s+(.*)$/) || line.match(/^(?:[-*+])$/);
    if (start) items.push(start[1] || '');
    else if (items.length && line.trim()) items[items.length - 1] += `\n${line.trim()}`;
    else if (!items.length && line.trim()) items.push(line.trim());
  }
  return items.map((i) => i.trim()).filter((i) => i && !/^\(.*\)$/.test(i));
}

// The English tag word the prompt asks for wins; a Korean word counts only when none is there.
export function itemTag(text, tags) {
  const list = tags || [];
  return list.find((t) => t.word.test(text)) || list.find((t) => t.ko?.test(text)) || null;
}

// "→ concept_framer: ..." lines (with or without "- ", "(" or an "expert_" prefix).
export function handoffs(body, knownIds = []) {
  const found = [];
  for (const line of String(body || '').split('\n')) {
    const match = line.match(/→\s*\**(?:expert_)?([a-z0-9_]+)\**\s*[:：]\s*(.*?)\)?\s*$/i);
    if (match && (!knownIds.length || knownIds.includes(match[1]))) found.push({ agent: match[1], text: match[2] });
  }
  return found;
}

// One question item "question — where the answer lives" split at its first dash.
export function questionAnswer(text) {
  const [question, ...rest] = text.split(/\s+[—–-]\s+/);
  return { question: question.trim(), answer: rest.join(' — ').trim() };
}

// An expert's document arranged by its layout: rows of {kind, top, blocks: [{label, body, items}]}.
// Returns null when the document has none of the layout's sections, so the page shows it as written.
export function arrangeDocument(agentId, markdown, knownIds = []) {
  const layout = EXPERT_LAYOUTS[agentId];
  const { intro, sections } = documentSections(markdown);
  const byKey = new Map(sections.map((s) => [s.key, s]));
  const used = new Set();
  const take = (heading) => {
    const section = byKey.get(headingKey(heading));
    if (!section || !section.body) return null;
    used.add(section.key);
    return { label: section.label, body: section.body, items: listItems(section.body) };
  };
  const rows = [];
  for (const row of layout || []) {
    const blocks = (row.columns || [row.section]).map(take).filter(Boolean);
    if (blocks.length) rows.push({ kind: row.kind, top: Boolean(row.top), tags: row.tags || null, cards: Boolean(row.cards), blocks });
  }
  if (!rows.length) return null;
  const handoff = sections.find((s) => s.key === 'handoff');
  if (handoff) used.add(handoff.key);
  const rest = sections.filter((s) => !used.has(s.key) && s.body)
    .map((s) => ({ label: s.label, body: s.body, items: listItems(s.body) }));
  if (rest.length) rows.push({ kind: 'list', top: false, tags: null, cards: false, blocks: rest });
  return { intro, rows, handoffs: handoff ? handoffs(handoff.body, knownIds) : [] };
}

// ------------------------------------------------------------------ state proposal

// project_state.md headings and fields (data/project_state_template.md), in Korean on screen.
export const STATE_SECTION_LABELS = {
  Meta: '프로젝트 개요', 'Core Problem': '핵심 문제', 'Current Direction': '현재 방향',
  'Confirmed Decisions': '확정한 결정', 'Open Questions': '열린 질문', Tensions: '부딪히는 조건',
  'Module Status': '전문가 진행 상황', 'Missing Information': '부족한 정보', 'Recent Notes': '최근 메모',
  'Next Focus': '다음에 볼 것',
};
const STATE_FIELD_LABELS = {
  Project: '프로젝트', Phase: '단계', 'Primary driver': '주된 출발점', 'Studio week': '스튜디오 주차',
  'Last updated': '마지막 갱신', 'Active focus': '이번 초점',
};
const STATE_VALUE_LABELS = {
  Phase: {
    analysis: '분석', concept: '개념', schematic: '계획 설계', development: '설계 발전',
    representation: '표현', presentation: '발표', review: '검토',
  },
  'Primary driver': { site: '대지', idea: '아이디어', program: '프로그램', regulation: '법규', competition: '공모' },
};
const MODULE_STATUS_LABELS = { pending: '대기', in_progress: '진행 중', done: '완료', stale: '다시 볼 필요' };

// The proposal's `changes` (GET .../session, docs/state-editing.md) as sections of readable rows:
// [{title, summary, rows: [{kind: 'added' | 'removed', text} | {kind: 'changed', label, before, text, note}]}].
// `names` maps expert ids to their names for the Module Status rows.
export function stateChangeView(changes, names = {}) {
  return (changes || []).map((change) => {
    const title = STATE_SECTION_LABELS[change.section] || change.section;
    if (change.fields) {
      const modules = change.section === 'Module Status';
      const value = (name, v) => (modules ? MODULE_STATUS_LABELS[v] : STATE_VALUE_LABELS[name]?.[v]) || v;
      const rows = change.fields.map((f) => ({
        kind: 'changed',
        label: modules ? names[f.name] || f.name : STATE_FIELD_LABELS[f.name] || f.name,
        before: f.before ? value(f.name, f.before) : '',
        text: f.after ? value(f.name, f.after) : '(비움)',
        note: f.takeaway || '',
      }));
      return { title, summary: '', rows };
    }
    const added = change.added || [];
    const removed = change.removed || [];
    const summary = [added.length && `${added.length}개 추가`, removed.length && `${removed.length}개 빠짐`]
      .filter(Boolean).join(' · ');
    const rows = [
      ...added.map((text) => ({ kind: 'added', text })),
      ...removed.map((text) => ({ kind: 'removed', text })),
    ];
    return { title, summary, rows };
  }).filter((section) => section.rows.length);
}
