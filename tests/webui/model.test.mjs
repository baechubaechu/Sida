import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  escapeHtml, findProjects, relativeDate, projectSummary, chatItems, eventNotice, expertStatus,
  renderMarkdown, chatTitle, latestChat, chatLabel, keyChanges,
} from '../../webui/app/model.js';

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
