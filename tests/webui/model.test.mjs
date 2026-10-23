import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  escapeHtml, findProjects, relativeDate, projectSummary, chatItems, eventNotice, expertStatus,
  renderMarkdown, chatTitle, latestChat, chatLabel, keyChanges, parseRoute, expertPath, dateTime,
  documentSections, listItems, itemTag, handoffs, questionAnswer, arrangeDocument, EXPERT_LAYOUTS, SECTION_LABELS,
  stateChangeView,
} from '../../webui/app/model.js';
import { readFileSync, readdirSync } from 'node:fs';

const projects = [
  { name: 'museum', project_type: '미술관', updated_at: '2026-10-18T09:00:00+00:00', completed: ['site_reader'], expert_count: 10 },
  { name: 'housing', project_type: '단독주택', updated_at: '2026-10-20T09:00:00+00:00', completed: [], expert_count: 10 },
  { name: 'library', project_type: '', updated_at: '', completed: [], expert_count: 10 },
];

test('search matches name and type, ignoring case and spaces', () => {
  assert.deepEqual(findProjects(projects, '  미술관 ').map((p) => p.name), ['museum']);
  assert.deepEqual(findProjects(projects, 'HOUS').map((p) => p.name), ['housing']);
  assert.deepEqual(findProjects(projects, '없는 이름'), []);
});

test('recent sort puts the newest first and undated last, without changing the input', () => {
  const before = structuredClone(projects);
  assert.deepEqual(findProjects(projects).map((p) => p.name), ['housing', 'museum', 'library']);
  assert.deepEqual(findProjects(projects, '', 'name').map((p) => p.name), ['housing', 'library', 'museum']);
  assert.deepEqual(projects, before);
});

test('dates read as today, yesterday or a day of the month', () => {
  const now = new Date(2026, 9, 20, 15, 0);
  assert.equal(relativeDate(new Date(2026, 9, 20, 8, 0).toISOString(), now), '오늘 수정');
  assert.equal(relativeDate(new Date(2026, 9, 19, 23, 0).toISOString(), now), '어제 수정');
  assert.equal(relativeDate(new Date(2026, 9, 6, 12, 0).toISOString(), now), '10월 6일 수정');
  assert.equal(relativeDate('', now), '');
  assert.equal(relativeDate('not a date', now), '');
});

test('project summary counts finished experts', () => {
  assert.equal(projectSummary(projects[0]), '전문가 1/10 완료');
  assert.equal(projectSummary(projects[1]), '아직 실행한 전문가 없음');
});

test('stored chat becomes bubbles, analysis cards and notes', () => {
  const items = chatItems([
    { role: 'user', text: '안녕' },
    { role: 'conductor', text: '대지부터 보겠습니다.' },
    { role: 'system', event: 'module_completed', agent: 'site_reader', name: '대지 분석가', text: '[module completed] internal' },
    { role: 'system', event: 'run_requested', agent: 'site_reader', name: '대지 분석가', text: '/run site_reader' },
    { role: 'system', event: 'read', agent: 'site_reader', name: '대지 분석가', text: '[read] …' },
    { role: 'system', event: 'revised', text: '[revised] …' },
    { role: 'expert', text: '고쳤습니다.' },
    { role: 'system', event: 'something_new', text: 'ignored' },
  ]);
  assert.deepEqual(items.map((i) => i.kind), ['user', 'conductor', 'card', 'note', 'note', 'note', 'expert']);
  assert.deepEqual(items[2], { kind: 'card', agent: 'site_reader', name: '대지 분석가' });
  assert.ok(!JSON.stringify(items).includes('internal'), 'the model-facing note is not shown');
  assert.deepEqual(chatItems(undefined), []);
});

test('the three expert-run notices raise a toast; replies are not notices', () => {
  const agent = { id: 'site_reader', name: '대지 분석가' };
  const toasts = ['module_started', 'module_saved', 'state_proposed']
    .map((kind) => eventNotice({ kind, data: { agent } }));
  for (const notice of toasts) {
    assert.equal(notice.toast, true);
    assert.match(notice.text, /대지 분석가/);
  }
  assert.equal(eventNotice({ kind: 'state_proposing', data: { agent } }).toast, false);
  assert.equal(eventNotice({ kind: 'conductor_reply', data: { text: '…' } }), null);
  assert.equal(eventNotice({ kind: 'expert_reply', data: { agent, text: '…' } }), null);
  const failed = eventNotice({ kind: 'conductor_error', data: { reason: '한도 초과' } });
  assert.equal(failed.tone, 'error');
  assert.match(failed.text, /다시 보내/);
  assert.match(failed.text, /한도 초과/);
  const afterRun = eventNotice({ kind: 'conductor_error', data: { reason: '한도 초과', after_run: true } });
  assert.equal(afterRun.tone, 'warn');
  assert.match(afterRun.text, /결과는 저장됐/);
  assert.doesNotMatch(afterRun.text, /다시 보내/);
});

test('a run the Conductor asked for but Sida held back says why', () => {
  const agent = { id: 'program_analyst', name: '프로그램 분석가' };
  const limit = eventNotice({ kind: 'run_skipped', data: { agent, reason: 'limit', limit: 3 } });
  assert.equal(limit.toast, true);
  assert.match(limit.text, /3명/);
  assert.match(limit.text, /프로그램 분석가/);
  const pending = eventNotice({ kind: 'run_skipped', data: { agent, reason: 'state_pending' } });
  assert.match(pending.text, /반영안을 먼저 검토/);
});

test('a running job marks its expert as running', () => {
  const expert = { id: 'site_reader', status: 'idle', done: false };
  assert.equal(expertStatus(expert, null), 'idle');
  assert.equal(expertStatus(expert, { running_agent: 'site_reader' }), 'running');
  assert.equal(expertStatus({ id: 'x', done: true }, { running_agent: 'y' }), 'done');
});

test('markdown escapes HTML before formatting', () => {
  const html = renderMarkdown('<script>alert(1)</script> **굵게** [링크](javascript:alert(1))');
  assert.ok(!html.includes('<script>'));
  assert.ok(html.includes('&lt;script&gt;'));
  assert.ok(html.includes('<strong>굵게</strong>'));
  assert.ok(!html.includes('href="javascript'));
  assert.equal(escapeHtml('"\'&'), '&quot;&#39;&amp;');
});

test('markdown renders the blocks expert documents use', () => {
  const html = renderMarkdown([
    '## 대지 사실',
    '',
    '- 용도지역: 제2종일반주거지역',
    '- 면적: `512㎡`',
    '',
    '1. 첫째',
    '2. 둘째',
    '',
    '| 항목 | 값 |',
    '|---|---|',
    '| 건폐율 | 60% |',
    '',
    '> 미확인 항목이 있습니다.',
    '',
    '```',
    '<b>그대로</b>',
    '```',
    '---',
    '[출처](https://www.law.go.kr/x?a=1&b=2) 문단',
  ].join('\n'));
  assert.ok(html.includes('<h3>대지 사실</h3>'));
  assert.ok(html.includes('<ul><li>용도지역: 제2종일반주거지역</li><li>면적: <code>512㎡</code></li></ul>'));
  assert.ok(html.includes('<ol><li>첫째</li><li>둘째</li></ol>'));
  assert.ok(html.includes('<th>항목</th>') && html.includes('<td>60%</td>'));
  assert.ok(html.includes('<blockquote>미확인 항목이 있습니다.</blockquote>'));
  assert.ok(html.includes('<pre><code>&lt;b&gt;그대로&lt;/b&gt;</code></pre>'));
  assert.ok(html.includes('<hr>'));
  assert.ok(html.includes('<a href="https://www.law.go.kr/x?a=1&amp;b=2" target="_blank" rel="noopener noreferrer">출처</a>'));
});

test('expert chats are numbered and the newest opens first', () => {
  assert.equal(chatTitle('02'), '분석 02');
  assert.equal(chatTitle(''), '분석 01');
  assert.equal(latestChat({ chats: [{ id: '01' }, { id: '02' }] }), '02');
  assert.equal(latestChat({ chats: [] }), '01');
  assert.equal(latestChat(null), '01');
  assert.equal(chatLabel({ id: '01', preview: '주차 대수는?' }), '분석 01 · 주차 대수는?');
  assert.equal(chatLabel({ id: '03', preview: '' }), '분석 03 · 빈 대화');
});

test('only typed keys are saved, and the shown VWorld domain only when it changed', () => {
  const status = { vworld: { set: true, hint: '…abcd' }, vworld_domain: { set: true, value: 'localhost' } };
  assert.deepEqual(keyChanges({ vworld: '', vworld_domain: 'localhost', data_go_kr: '', law: '' }, status), []);
  assert.deepEqual(
    keyChanges({ vworld: ' new-key ', vworld_domain: '127.0.0.1', data_go_kr: '', law: 'oc' }, status),
    [['vworld', 'new-key'], ['vworld_domain', '127.0.0.1'], ['law', 'oc']],
  );
  assert.deepEqual(keyChanges({ vworld_domain: '  ' }, status), []);
});

test('addresses open an expert on its result, analysis chat or earlier result', () => {
  assert.deepEqual(parseRoute('#/project/my%20museum/expert/site_reader'), {
    page: 'project', name: 'my museum', agent: 'site_reader', tab: 'doc', chat: '', version: '',
  });
  assert.equal(parseRoute('#/project/a/expert/program_analyst/chat/02').chat, '02');
  assert.equal(parseRoute('#/project/a/expert/program_analyst/chat').tab, 'chat');
  assert.equal(parseRoute('#/project/a/expert/x/versions/20261001-090000').version, '20261001-090000');
  assert.equal(parseRoute('#/project/a/expert/x/nonsense').tab, 'doc');
  assert.equal(parseRoute('#/project/a').agent, '');
  assert.deepEqual(parseRoute('#/new'), { page: 'new' });
  assert.deepEqual(parseRoute(''), { page: 'home' });
  for (const [tab, id] of [['doc', ''], ['chat', '01'], ['chat', ''], ['versions', '20261001-090000-1']]) {
    const route = parseRoute(expertPath('뮤지엄 #1', 'site_reader', tab, id));
    assert.equal(route.name, '뮤지엄 #1');
    assert.equal(route.tab, tab);
    assert.equal(tab === 'chat' ? route.chat : route.version, id);
  }
  assert.equal(dateTime('2026-10-01T09:05:00'), '10월 1일 09:05');
  assert.equal(dateTime(''), '');
});

test('every expert in config.yaml has a page layout made of sections its prompt asks for', () => {
  const config = readFileSync(new URL('../../config.yaml', import.meta.url), 'utf8');
  const ids = [...config.matchAll(/^\s*- id: (\w+)/gm)].map((m) => m[1]);
  assert.deepEqual(Object.keys(EXPERT_LAYOUTS).sort(), ids.sort());
  const prompts = readdirSync(new URL('../../agents/', import.meta.url))
    .map((f) => readFileSync(new URL(`../../agents/${f}`, import.meta.url), 'utf8')).join('\n');
  const asked = new Set([...prompts.matchAll(/^## (.+)$/gm)].map((m) => m[1].trim()));
  for (const [id, rows] of Object.entries(EXPERT_LAYOUTS)) {
    for (const heading of rows.flatMap((row) => row.columns || [row.section])) {
      assert.ok(asked.has(heading), `${id}: ${heading}`);
      assert.ok(SECTION_LABELS[heading], `${id}: ${heading} has no Korean label`);
    }
  }
});

const REGULATION = `# Regulation Checker

## Governing Frameworks
- **건축법** — certainly / 기본 요건이라 적용됨. 확인 필요 없음
- **하천법** — probably / 하천이 인접함
- 지구단위계획 — check / 수립 여부
- 주차장법 — 주차 대수를 확인해야 함

## Items to Verify

| Item | Why | Where |
|---|---|---|
| 용도지역 | 상한 결정 | 조례 |

## Odd Extra Section
- 형식 밖 내용

## Handoff
→ expert_site_reader: 이격 거리 확인.
- (→ program_analyst: 주차 대수)
→ nobody: 모르는 전문가
`;

test('an expert document is split into its sections and arranged by that expert\'s layout', () => {
  const { sections } = documentSections(REGULATION);
  assert.deepEqual(sections.map((s) => s.label), ['적용 법규', '확인할 항목', 'Odd Extra Section', '다음 전문가']);

  const doc = arrangeDocument('regulation_checker', REGULATION, ['site_reader', 'program_analyst']);
  assert.deepEqual(doc.rows.map((r) => [r.kind, r.top, r.blocks.map((b) => b.label)]), [
    ['table', true, ['확인할 항목']],
    ['tagged', false, ['적용 법규']],
    ['list', false, ['Odd Extra Section']], // sections outside the layout are kept, at the end
  ]);
  const tags = doc.rows[1].blocks[0].items.map((item) => itemTag(item, doc.rows[1].tags)?.label ?? null);
  // The English word the prompt asks for wins over Korean words elsewhere in the line.
  assert.deepEqual(tags, ['확실히 적용', '아마 적용', '적용 여부 확인', '적용 여부 확인']);
  assert.deepEqual(doc.handoffs, [
    { agent: 'site_reader', text: '이격 거리 확인.' },
    { agent: 'program_analyst', text: '주차 대수' },
  ]);

  // A document in none of the expected sections is shown as written.
  assert.equal(arrangeDocument('regulation_checker', '그냥 글입니다.'), null);
  assert.equal(arrangeDocument('unknown_expert', REGULATION), null);
});

test('list items keep their following lines and drop template placeholders', () => {
  assert.deepEqual(listItems('- 첫째\n  이어지는 줄\n- 둘째\n1. 셋째\n- (component — source — role)\n-'), [
    '첫째\n이어지는 줄', '둘째', '셋째',
  ]);
  assert.deepEqual(listItems('목록 없이 한 문단'), ['목록 없이 한 문단']);
  assert.deepEqual(handoffs('→ **concept_framer**: 개념 확인'), [{ agent: 'concept_framer', text: '개념 확인' }]);
  assert.deepEqual(questionAnswer('왜 보이드인가? — 단면도 2'), { question: '왜 보이드인가?', answer: '단면도 2' });
  assert.deepEqual(questionAnswer('답 없는 질문'), { question: '답 없는 질문', answer: '' });
});

test('state proposal changes read as Korean sections, not a diff', () => {
  const view = stateChangeView([
    { section: 'Meta', fields: [{ name: 'Phase', before: '', after: 'analysis' }, { name: 'Active focus', before: '대지', after: '보행' }] },
    { section: 'Open Questions', added: ['질문 1', '질문 2'], removed: ['옛 질문'] },
    { section: 'Module Status', fields: [{ name: 'site_reader', before: 'pending', after: 'done', takeaway: '역은 접점' }] },
    { section: 'Custom', added: [], removed: [] },
  ], { site_reader: '대지 분석가' });
  assert.deepEqual(view.map((s) => [s.title, s.summary]), [
    ['프로젝트 개요', ''], ['열린 질문', '2개 추가 · 1개 빠짐'], ['전문가 진행 상황', ''],
  ]);
  assert.deepEqual(view[0].rows, [
    { kind: 'changed', label: '단계', before: '', text: '분석', note: '' },
    { kind: 'changed', label: '이번 초점', before: '대지', text: '보행', note: '' },
  ]);
  assert.deepEqual(view[1].rows.map((r) => r.kind), ['added', 'added', 'removed']);
  assert.deepEqual(view[2].rows, [{ kind: 'changed', label: '대지 분석가', before: '대기', text: '완료', note: '역은 접점' }]);
  assert.deepEqual(stateChangeView(undefined), []);
});
