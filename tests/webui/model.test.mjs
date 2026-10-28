import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  escapeHtml, findProjects, relativeDate, projectSummary, chatItems, eventNotice, expertStatus,
  renderMarkdown, chatTitle, latestChat, chatLabel, keyChanges, parseRoute, expertPath, dateTime,
  documentSections, listItems, itemTag, handoffs, questionAnswer, arrangeDocument, EXPERT_LAYOUTS, SECTION_LABELS,
  stateChangeView, phaseLabel, sitePath, sitePageFor, needsSiteFirst, areaText, zoneScope, siteHeadline, missingText, restrictionGroups,
  ordinanceFigure, ordinanceApplies, ordinanceSends, useResult, useError, useDefinitions,
  buildingLine, chosenDong, lotQuery, lookupBody, briefSite,
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

test('drafting table notices: AI papers land in the AI section and board reads are named', () => {
  const added = eventNotice({ kind: 'tray_added', data: { paper: { kind: 'mass', title: '안 C' } } });
  assert.equal(added.text, '안 C을(를) 제도판의 AI 섹션에 놓았습니다.');
  assert.equal(added.toast, true);
  assert.match(eventNotice({ kind: 'tray_failed', data: { reason: 'limit' } }).text, /넘어/);
  assert.match(eventNotice({ kind: 'tray_failed', data: { reason: 'bad block' } }).text, /bad block/);
  assert.equal(eventNotice({ kind: 'reading', data: { file: 'board/mass-a' } }).text, '제도판 종이 mass-a를 읽는 중입니다.');
  assert.equal(eventNotice({ kind: 'reading', data: { file: 'site_reader.md' } }).text, 'site_reader.md를 읽는 중입니다.');
});

test('a message keeps the papers sent with it as chips', () => {
  const [sent, plain] = chatItems([
    { role: 'user', text: '이 안 어때?', context: [{ id: 'mass-a', name: '안 A' }] },
    { role: 'user', text: '안녕' },
  ]);
  assert.deepEqual(sent.context, [{ id: 'mass-a', name: '안 A' }]);
  assert.deepEqual(plain.context, []);
});

test('a run the Conductor asked for but Sida held back says why', () => {
  const agent = { id: 'program_analyst', name: '프로그램 분석가' };
  const limit = eventNotice({ kind: 'run_skipped', data: { agent, reason: 'limit', limit: 3 } });
  assert.equal(limit.toast, true);
  assert.match(limit.text, /3명/);
  assert.match(limit.text, /프로그램 분석가/);
  const pending = eventNotice({ kind: 'run_skipped', data: { agent, reason: 'state_pending' } });
  assert.match(pending.text, /반영안을 먼저 검토/);
  const held = eventNotice({ kind: 'run_skipped', data: { agent, reason: 'held' } });
  assert.match(held.text, /보류 중인 전문가/);
});

test('held experts say so next to their phase', () => {
  assert.equal(phaseLabel({ phase: 'concept', tier: 'held' }), '개념 · 보류');
  assert.equal(phaseLabel({ phase: 'analysis', tier: 'core' }), '분석');
  assert.equal(phaseLabel({ phase: 'other' }), 'other');
  assert.equal(phaseLabel({ tier: 'held' }), '보류');
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
    page: 'project', name: 'my museum', agent: 'site_reader', site: false, tab: 'doc', chat: '', version: '',
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

const SITE = `# Site Reader

## Facts
- 대지 면적 1,234㎡, 지목 대 — source: site facts
- 남쪽으로 철도와 접함 — source: brief
- 정부 자료로 확인한 진입 도로 폭 8m — 출처: 대지 사실

## Interpretations
- 철도가 남북 보행을 끊는다 — rests on: 철도 접함 (brief)

## Unconfirmed
- 대지 고저차 — 현장 측량 필요

## Site Conditions
- 예전 형식의 결과
`;

test('site reader page puts sourced facts first, then interpretations, then what is unconfirmed', () => {
  const doc = arrangeDocument('site_reader', SITE);
  assert.deepEqual(doc.rows.map((r) => r.blocks.map((b) => b.label)), [['사실'], ['해석'], ['미확인'], ['대지 조건']]);
  assert.equal(doc.rows[0].top, true);
  const tags = doc.rows[0].blocks[0].items.map((item) => itemTag(item, doc.rows[0].tags)?.label ?? null);
  assert.deepEqual(tags, ['정부 자료', '브리프', '정부 자료']);
  assert.equal(doc.rows[2].kind, 'checklist');
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

test('the site page opens on its facts or on finding parcels, beside the Conductor conversation', () => {
  assert.deepEqual(parseRoute(sitePath('뮤지엄 #1')), {
    page: 'project', name: '뮤지엄 #1', agent: '', site: true, tab: 'facts', chat: '', version: '',
  });
  assert.equal(parseRoute(sitePath('a', 'find')).tab, 'find');
  assert.equal(parseRoute('#/project/a/site/nonsense').tab, 'facts');
  assert.equal(parseRoute(sitePath('a', 'ordinance')).tab, 'ordinance');
  assert.equal(parseRoute(sitePath('a', 'uses')).tab, 'uses');
  assert.equal(parseRoute('#/project/a').site, false);
});

const site = {
  available: true,
  query: '경기도 군포시 금정동 689',
  summary: {
    parcel_count: 2, total_area_m2: 2028.6, area_complete: true, municipality: '경기도 군포시',
    zoning: [
      { zone: '일반공업지역', pnus: ['1', '2'], area_m2: 2028.6, partial: false },
      { zone: '자연녹지지역', pnus: ['2'], area_m2: 1014.3, partial: false },
    ],
  },
};

test('site facts read as given: areas, where a zone lies, and 미확인 instead of a guess', () => {
  assert.equal(areaText(1014.3), '1,014.3㎡');
  assert.equal(areaText(null), '미확인');
  assert.equal(zoneScope(site.summary.zoning[0], 2), '전 필지');
  assert.equal(zoneScope(site.summary.zoning[1], 2), '필지 1개, 1,014.3㎡');
  assert.equal(zoneScope({ partial: true, pnus: ['1'] }, 1), '필지 일부에 걸침, 면적 비율 미확인');
  assert.equal(siteHeadline(site), '경기도 군포시 금정동 689 · 일반공업지역, 자연녹지지역');
  assert.equal(siteHeadline({ ...site, summary: { ...site.summary, zoning: [] } }), '경기도 군포시 금정동 689 · 용도지역 미확인');
  assert.equal(siteHeadline({ available: false }), '');
  assert.equal(siteHeadline(null), '');
  assert.equal(missingText({ pnu: '1', address: '금정동 689-14', what: 'buildings' }), '금정동 689-14의 건축물대장');
  assert.equal(missingText({ pnu: '41410', address: '', what: 'new_kind' }), '41410의 new_kind');
});

test('restriction articles split into national laws and ordinances, and a failed lookup says why', () => {
  const groups = restrictionGroups({
    laws: [{ text: '제71조(용도지역안에서의 건축제한)', local: false }, { text: '제30조', local: true }], error: null,
  });
  assert.deepEqual(groups.national.map((l) => l.text), ['제71조(용도지역안에서의 건축제한)']);
  assert.deepEqual(groups.local.map((l) => l.text), ['제30조']);
  assert.equal(groups.error, '');
  assert.equal(restrictionGroups({ laws: [], error: 'network' }).error, '연결 실패');
});

test('a registered building reads as one line with only what the register holds', () => {
  assert.equal(
    buildingLine({ name: '(주)혜창', dong: '', purpose: '공장', structure: '철골구조', floors_above: 4, floors_below: 1, total_floor_area_m2: 3210, approved: '19980512' }),
    '(주)혜창 · 공장 · 철골구조 · 지상 4층/지하 1층 · 연면적 3,210㎡ · 사용승인 1998.05.12',
  );
  assert.equal(buildingLine({ name: '', purpose: '주택', floors_above: null, total_floor_area_m2: null, approved: '' }), '이름 없는 건물 · 주택');
});

test('a 지번 is looked up in the chosen 리, or in a 동 that has none', () => {
  const emd = { code: '41410105', dong_code: '4141010500', has_ri: false };
  const town = { code: '41830250', dong_code: '4183025000', has_ri: true };
  assert.equal(chosenDong({ emd }), '4141010500');
  assert.equal(chosenDong({ emd: town }), '');
  assert.equal(chosenDong({ emd: town, ri: { dong_code: '4183025021' } }), '4183025021');
  assert.equal(chosenDong({}), '');

  assert.equal(lotQuery('4141010500', ' 689 ', '14').query, 'dong_code=4141010500&main=689&sub=14');
  assert.equal(lotQuery('4141010500', '689', '', true).query, 'dong_code=4141010500&main=689&mountain=true');
  assert.equal(lotQuery('4141010500', '689', '0').query, 'dong_code=4141010500&main=689&sub=0');
  assert.match(lotQuery('', '689').error, /읍·면·동/);
  for (const main of ['', '0', '10000', '68a', '6.5']) assert.match(lotQuery('4141010500', main).error, /본번/);
  assert.match(lotQuery('4141010500', '689', '-1').error, /부번/);
});

test('parcels from the last address search go with that search; others go by number alone', () => {
  const search = { query: '금정동 689', pnus: ['a', 'b'] };
  assert.deepEqual(lookupBody([{ pnu: 'b' }, { pnu: 'a' }], search), { query: '금정동 689', pnus: ['b', 'a'] });
  assert.deepEqual(lookupBody([{ pnu: 'a' }, { pnu: 'c' }], search), { pnus: ['a', 'c'] });
  assert.deepEqual(lookupBody([{ pnu: 'a' }], null), { pnus: ['a'] });
});

test('the find tab starts from the address the brief was made with', () => {
  const brief = '# Project Brief\n\n## Project Type\n미술관\n\n## Site\n경기도 군포시 금정동 689\n\n## Core Problem\n-\n';
  assert.equal(briefSite(brief), '경기도 군포시 금정동 689');
  assert.equal(briefSite(brief.replace('경기도 군포시 금정동 689', '-')), '');
  assert.equal(briefSite(''), '');
});

test('the site page opens when the site reader starts, on find while no site is saved', () => {
  const started = (id) => ({ kind: 'module_started', data: { agent: { id, name: '대지 분석가' } } });
  assert.equal(sitePageFor(started('site_reader'), 'museum', { available: true }), sitePath('museum'));
  assert.equal(sitePageFor(started('site_reader'), 'museum', { available: false }), sitePath('museum', 'find'));
  assert.equal(sitePageFor(started('site_reader'), 'museum', null), sitePath('museum', 'find'));
  assert.equal(sitePageFor(started('design_critic'), 'museum', { available: true }), null);
  assert.equal(sitePageFor({ kind: 'module_saved', data: { agent: { id: 'site_reader' } } }, 'museum', null), null);
  assert.equal(sitePageFor(null, 'museum', null), null);
});

test('the site reader waits for a saved site, unless the site is unknown', () => {
  assert.equal(needsSiteFirst('site_reader', { available: false }), true);
  assert.equal(needsSiteFirst('site_reader', { available: true }), false);
  assert.equal(needsSiteFirst('site_reader', null), false); // not loaded or no key: run as before
  assert.equal(needsSiteFirst('regulation_checker', { available: false }), false);
});

test('ordinance figures are the number read by rule with its line, or 미확인 and why', () => {
  const line = { value: 70, quote: '일반공업지역 : 100분의 70 이하', conditional: false, label: '제49조' };
  assert.deepEqual(ordinanceFigure(line), { text: '70%', note: '', quote: line.quote, label: '제49조' });
  assert.equal(ordinanceFigure({ ...line, conditional: true }).note, '단서·예외 있음, 원문 확인');
  const unread = ordinanceFigure({ ...line, value: null });
  assert.equal(unread.text, '미확인');
  assert.equal(unread.quote, line.quote);
  assert.equal(ordinanceFigure({ ...line, value: null, out_of_range: true }).note, '법정 범위를 벗어나 수치를 내지 않음');
  assert.deepEqual(ordinanceFigure(null), { text: '미확인', note: '조문에 이 용도지역이 없음', quote: '', label: '' });
});

test('related articles say whether they concern the site and what the experts receive', () => {
  const article = { id: '제34조', applies: true, matched: ['자연경관지구'], dismissed: false, detailed: false };
  assert.deepEqual(ordinanceApplies(article), { tone: 'done', text: '해당: 자연경관지구' });
  assert.equal(ordinanceApplies({ ...article, applies: false, matched: [] }).text, '대지의 지구·구역 아님');
  assert.equal(ordinanceApplies({ ...article, applies: null }), null);
  assert.equal(ordinanceSends('site', article), '건폐율·용적률 항을 전문가에게 보냄');
  assert.equal(ordinanceSends('site', { ...article, applies: false, detailed: true }), '전문가에게 보내지 않음');
  assert.equal(ordinanceSends('design', { ...article, applies: null }), '제목만 전문가에게 보냄');
  assert.equal(ordinanceSends('admin', { ...article, applies: null, detailed: true }), '원문을 전문가에게 보냄');
  assert.equal(ordinanceSends('design', { ...article, applies: null, detailed: true, dismissed: true }), '숨김 · 전문가에게 보내지 않음');
});

test('planned uses show the government answer as given, and 미확인 when it is missing', () => {
  assert.deepEqual(useResult('가능'), { text: '가능', tone: 'done' });
  assert.deepEqual(useResult('금지'), { text: '금지', tone: 'blocked' });
  assert.deepEqual(useResult('조건부 가능'), { text: '조건부 가능', tone: 'review' });
  assert.deepEqual(useResult(''), { text: '미확인', tone: 'idle' });
  assert.equal(useError('network'), '가져오지 못했습니다(연결 실패). 미확인');
  assert.equal(useError(null), '');
  const def = { name: '공장', law: '건축법 시행령', definition: '물품의 제조·가공 시설' };
  const use = { zones: [
    { acts: [{ act: '건축', uses: [def] }, { act: '신설·증설·이전', uses: [def] }] },
    { acts: [{ act: '건축', uses: [def, { name: '', law: '', definition: '' }] }] },
  ] };
  assert.deepEqual(useDefinitions(use), [def]);
  assert.deepEqual(useDefinitions({ zones: [] }), []);
});
