// The experts panel and an expert's page: result layout, analysis chat, earlier results, review.

import { phaseLabel, visibleExperts, STATUS_LABELS, escapeHtml as escape, chatItems, expertStatus, renderMarkdown, chatTitle, chatLabel, projectPath as projectUrl, expertPath, dateTime, arrangeDocument, itemTag, renderInline, parseRecommendation, stripRecommendation, expertPageTabs, MODEL_EXPERT, questionAnswer, stateChangeView, sitePath, siteHeadline } from './model.js';
import { expertUrl } from './api.js';
import { SITE_EXPERTS, activeChat, currentRoute, draftFor, expertById, jobRunning, ui } from './state.js';
import { bubble, composer, workingLine } from './view-conductor.js';

function chatAnswering(agent, chat) {
  return jobRunning() && ui.job.kind === 'expert_chat' && ui.job.agent === agent && ui.job.chat === chat;
}

function siteRow(name) {
  const looked = Boolean(ui.site?.available);
  return `<a class="site-row" href="${sitePath(name)}">
      <span class="dot ${looked ? 'done' : 'idle'}" aria-hidden="true"></span>
      <span class="expert-text"><span class="expert-name">대지 사실</span>
      <span class="expert-phase">${escape(siteHeadline(ui.site) || '주소로 필지를 찾아 저장합니다')} · ${looked ? '조회함' : '조회 전'}</span></span>
      <span class="row-open" aria-hidden="true">↗</span></a>`;
}

// What the experts are doing now, under the list.
function runsBlock() {
  const job = ui.job;
  const running = jobRunning() && job.running_agent ? expertById(job.running_agent) : null;
  if (running) {
    return `<p class="working" role="status"><span class="spinner" aria-hidden="true"></span><span><b>${escape(running.name)}</b> 실행 중입니다. 결과는 제도판의 AI 섹션에 놓입니다.</span></p>`;
  }
  return '';
}

// The 전문가 panel (view-dock.js): the site facts, the experts and a run going on.
export function expertsBody() {
  const experts = visibleExperts(ui.session?.experts);
  const busy = jobRunning();
  const picked = ui.selected.length;
  return `<div class="dock-body" role="tabpanel" aria-label="전문가"><div class="experts-scroll">
    <p class="side-note">${picked ? `고른 종이 ${picked}장과 함께 실행합니다.` : '브리프와 제도판을 보고 실행합니다. 보통은 Conductor가 필요할 때 부릅니다.'}</p>
    <h3 class="panel-label">대지</h3>${siteRow(currentRoute.name)}
    <h3 class="panel-label">전문가</h3>
    <ul class="expert-list">${experts.map((e) => {
    const status = expertStatus(e, ui.job);
    const id = escape(e.id);
    const threads = e.chat
      ? `<button class="thread-new" data-action="new-chat" data-agent="${id}">＋ 새 분석 채팅</button>
        ${(e.chats || []).map((c) => `<button data-action="open-chat" data-agent="${id}" data-chat="${escape(c.id)}">${escape(chatLabel(c))}${chatAnswering(e.id, c.id) ? ' · 답하는 중' : ''}</button>`).join('')}`
      : '<p class="muted small-text">채팅 없음. 결과 문서와 수정 요청만 있습니다.</p>';
    return `<li class="expert-item"><span class="dot ${status}" aria-hidden="true"></span>
      <details class="expert-row" data-agent="${id}" ${ui.openExperts.has(e.id) ? 'open' : ''}>
        <summary><span class="expert-name">${escape(e.name)}</span>
          <span class="expert-phase">${escape(phaseLabel(e))} · ${escape(STATUS_LABELS[status])}</span></summary>
        <div class="expert-threads"><button data-action="open-expert" data-agent="${id}">결과 문서 보기</button>${threads}</div></details>
      <button type="button" class="mini" data-action="run-expert" data-agent="${id}" ${busy ? 'disabled' : ''} title="${e.done ? '다시 실행' : '실행'}${picked ? ` (고른 종이 ${picked}장과 함께)` : ''}">${status === 'running' ? '실행 중' : e.done ? '다시' : '실행'}</button></li>`;
  }).join('')}</ul></div>
    ${runsBlock() ? `<section class="runs" aria-label="검토 진행"><h3>검토 진행</h3>${runsBlock()}</section>` : ''}</div>`;
}

function proposalBlock(agent) {
  const proposal = ui.session?.proposal;
  if (!proposal || proposal.agent !== agent) return '';
  const names = Object.fromEntries((ui.session?.experts || []).map((e) => [e.id, e.name]));
  const sections = stateChangeView(proposal.changes, names);
  const raw = (proposal.diff || '').startsWith('---');
  let body;
  if (sections.length) {
    body = `<div class="state-changes">${sections.map((s) => `<div class="state-change">
      <h4>${escape(s.title)}${s.summary ? ` <span class="summary">${escape(s.summary)}</span>` : ''}</h4><ul>${s.rows.map(stateChangeRow).join('')}</ul></div>`).join('')}</div>`;
  } else if (!proposal.changes) {
    body = `<pre class="diff">${escape(proposal.diff)}</pre>`;
  } else {
    body = `<p class="state-note">${raw ? '바뀌는 내용은 마지막 갱신 날짜뿐입니다.' : escape(proposal.diff)}</p>`;
  }
  const rawDiff = proposal.changes && raw
    ? `<details class="raw-diff"><summary>원본 비교 보기</summary><pre class="diff">${escape(proposal.diff)}</pre></details>` : '';
  return `<section class="proposal" aria-label="설계 상태 반영안">
    <h3>설계 상태에 반영할까요?</h3>
    <p class="muted">반영하면 설계 상태(PROJECT STATE)가 이렇게 바뀝니다.</p>
    ${body}${rawDiff}
    <div class="form-actions"><button class="secondary" data-action="skip-proposal" data-id="${escape(proposal.id)}">건너뛰기</button>
      <button class="primary" data-action="apply-proposal" data-id="${escape(proposal.id)}">반영하기</button></div>
  </section>`;
}

function stateChangeRow(row) {
  if (row.kind === 'changed') {
    const value = row.before
      ? `<span class="before">${escape(row.before)}</span> → <strong>${escape(row.text)}</strong>`
      : `<strong>${escape(row.text)}</strong>`;
    return `<li class="changed"><span class="field">${escape(row.label)}</span><span>${value}</span>${row.note ? `<p class="note">${escape(row.note)}</p>` : ''}</li>`;
  }
  if (row.kind === 'removed') return `<li class="removed"><span class="sr-only">빠짐: </span><s>${escape(row.text)}</s></li>`;
  return `<li class="added">${escape(row.text)}</li>`;
}

// ------------------------------------------------------------------ expert page

function expertLink(name, id) {
  const other = expertById(id);
  return other && other.tier !== 'held' ? `<a class="expert-chip" href="${expertUrl(name, id)}">${escape(other.name)}</a>` : '';
}

function itemsHtml(items, draw = (item) => renderInline(item)) {
  return items.map((item) => `<li>${draw(item)}</li>`).join('');
}

function tagged(item, tags) {
  const tag = itemTag(item, tags);
  return `${tag ? `<span class="status-badge ${tag.tone}">${escape(tag.label)}</span> ` : ''}${renderInline(item)}`;
}

// One section of an expert document, drawn the way that expert's layout asks (model.js EXPERT_LAYOUTS).
function sectionBlock(block, row, agent, index) {
  const { label, body, items } = block;
  let inner;
  if (row.kind === 'lead') {
    const [first, ...others] = items;
    inner = `<p class="lead-text">${renderInline(first || '')}</p>${others.length ? `<ul class="lead-others">${itemsHtml(others)}</ul>` : ''}`;
  } else if (row.kind === 'cards' || (row.kind === 'tagged' && row.cards)) {
    const draw = row.kind === 'tagged' ? (item) => tagged(item, row.tags) : (item) => renderInline(item);
    inner = `<ul class="card-list">${itemsHtml(items, draw)}</ul>`;
  } else if (row.kind === 'tagged') {
    inner = `<ul class="tag-list">${itemsHtml(items, (item) => tagged(item, row.tags))}</ul>`;
  } else if (row.kind === 'checklist') {
    inner = `<ul class="check-list">${items.map((item, i) => {
      const key = `${currentRoute.name}:${agent}:${label}:${i}`;
      return `<li><label><input type="checkbox" data-check="${escape(key)}" ${ui.checks.has(key) ? 'checked' : ''}> <span>${renderInline(item)}</span></label></li>`;
    }).join('')}</ul>`;
  } else if (row.kind === 'steps') {
    inner = `<ol class="step-list">${itemsHtml(items)}</ol>`;
  } else if (row.kind === 'qa') {
    inner = `<div class="qa-list">${items.map((item) => {
      const { question, answer } = questionAnswer(item);
      return answer
        ? `<details><summary>${renderInline(question)}</summary><p>${renderInline(answer)}</p></details>`
        : `<p>${renderInline(question)}</p>`;
    }).join('')}</div>`;
  } else {
    inner = `<div class="markdown">${renderMarkdown(body)}</div>`;
  }
  return `<section class="doc-section kind-${row.kind}" aria-labelledby="sec-${index}"><h2 id="sec-${index}">${escape(label)}</h2>${inner}</section>`;
}

function arrangedDoc(name, agent, content) {
  const ids = visibleExperts(ui.session?.experts).map((e) => e.id);
  const arranged = arrangeDocument(agent, content, ids);
  const raw = `<div class="markdown doc">${renderMarkdown(content)}</div>`;
  if (!arranged) return raw;
  let index = 0;
  const rows = arranged.rows.map((row) => `<div class="doc-row ${row.top ? 'top' : ''} cols-${row.blocks.length}">
      ${row.blocks.map((block) => sectionBlock(block, row, agent, index++)).join('')}</div>`).join('');
  const next = arranged.handoffs.length
    ? `<section class="doc-section handoff"><h2>다음 전문가</h2><ul>${arranged.handoffs.map((h) => `<li>${expertLink(name, h.agent)} ${renderInline(h.text)}</li>`).join('')}</ul></section>`
    : '';
  return `${arranged.intro ? `<div class="markdown">${renderMarkdown(arranged.intro)}</div>` : ''}${rows}${next}
    <details class="raw-doc" ${ui.showRaw ? 'open' : ''}><summary>원문 보기</summary>${raw}</details>`;
}

// Site reader and regulation checker work from the saved site facts: say which site, or that there is none.
function siteNote(name, agent) {
  if (!SITE_EXPERTS.has(agent) || !ui.site) return '';
  if (!ui.site.available) {
    return `<p class="site-note warn">아직 대지를 조회하지 않아 정부 데이터 없이 브리프만으로 실행됩니다. <a href="${sitePath(name, 'find')}">대지 찾기</a></p>`;
  }
  return `<p class="site-note">대지 · ${escape(siteHeadline(ui.site))} <a href="${sitePath(name)}">대지 보기</a></p>`;
}

function docTab(name, agent, expert) {
  const loading = !ui.module && !ui.moduleMissing && expert.done;
  if (!ui.module) {
    return `${siteNote(name, agent)}<div class="expert-note">${loading ? '불러오는 중입니다.' : '아직 실행 전입니다. 오른쪽에서 실행하면 결과가 여기에 나옵니다.'}</div>`;
  }
  const reads = expert.inputs?.length
    ? `<p class="reads">읽은 전문가 ${expert.inputs.map((id) => expertLink(name, id)).join('')}</p>` : '';
  const content = agent === MODEL_EXPERT ? stripRecommendation(ui.module.content) : ui.module.content;
  return `${proposalBlock(agent)}${siteNote(name, agent)}${reads}${arrangedDoc(name, agent, content)}`;
}

// The representation planner's 모형 tab: the model board panel (placeModelMaker), with
// 추천대로 놓기 when the latest result recommends a board.
function modelTab() {
  const rec = parseRecommendation(ui.module?.content);
  const label = rec ? `추천대로 놓기 (${rec.board.replace(/^W/, '우드락 ')} · 1:${rec.scale} · ${rec.thickness} mm)` : '';
  const note = rec ? '' : '<p class="muted">표현 계획자를 실행하면 결과의 모형 추천을 여기서 바로 놓을 수 있습니다.</p>';
  return `<section class="doc-section model-maker-section" aria-label="모형 판">
    ${rec ? `<button class="primary-small" data-action="model-apply">${escape(label)}</button>` : note}
    <div id="model-maker-slot" class="model-maker-slot"><p class="muted">모형 판을 여는 중입니다.</p></div></section>`;
}

function chatTab(name, agent, expert) {
  const busy = jobRunning();
  const chat = activeChat();
  const chatOn = (ui.chat ? ui.chat.chat : expert.chat) && !ui.chatMissing;
  const items = chatItems(ui.chat?.messages);
  const live = ui.job?.kind === 'expert_chat' && ui.job.agent === agent && ui.job.chat === chat ? ui.live : [];
  const pending = ui.pending?.target === `${agent}/${chat}` ? [{ kind: 'user', text: ui.pending.text, context: ui.pending.context }] : [];
  const chats = expert.chats?.length ? expert.chats : [{ id: chat }];
  const list = `<nav class="chat-pills" aria-label="분석 채팅">
      ${chats.map((c) => `<a class="chat-pill ${c.id === chat ? 'active' : ''}" href="${expertUrl(name, agent, c.id)}" ${c.id === chat ? 'aria-current="page"' : ''}>${escape(chatTitle(c.id))}${chatAnswering(agent, c.id) ? ' · 답하는 중' : ''}</a>`).join('')}
      <button class="chat-pill new" data-action="new-chat" data-agent="${escape(agent)}">＋ 새 분석 채팅</button></nav>`;
  return `${list}
    <div class="chat-scroll" data-scroll="expert:${escape(agent)}:${escape(chat)}">
      ${ui.chatMissing ? `<p class="expert-note error-text">${escape(chatTitle(chat))} 대화를 찾을 수 없습니다. 다른 대화를 고르거나 새 분석 채팅을 시작해 주세요.</p>` : ''}
      ${!ui.chatMissing && !items.length && !pending.length && !live.length ? `<p class="muted">${escape(expert.name)}에게 결과에 대해 묻거나 더 파고들 점을 적어 보세요.</p>` : ''}
      <div class="message-list" role="log" aria-label="${escape(expert.name)} 대화">
        ${items.map((item) => bubble(item, expert.name, {})).join('')}
        ${[...pending, ...live].map((item) => bubble(item, expert.name)).join('')}
        ${workingLine(false)}
      </div>
    </div>
    ${chatOn ? composer(`expert:${agent}:${chat}`, `${expert.name}에게 메시지...`, expert.name, busy) : ''}`;
}

function versionsTab(name, agent) {
  const versions = ui.versions || [];
  const { version } = currentRoute;
  if (ui.versions === null) return '<p class="muted">불러오는 중입니다.</p>';
  if (!versions.length) {
    return '<div class="expert-note">이전 버전이 없습니다. 다시 실행하거나 수정 요청을 보내면 그 전 결과가 여기에 남습니다.</div>';
  }
  const current = ui.module
    ? `<li><a class="${version ? '' : 'active'}" href="${expertPath(name, agent, 'versions')}" ${version ? '' : 'aria-current="page"'}>지금 결과 · ${escape(dateTime(ui.module.updated_at))}</a></li>` : '';
  const list = `<ul class="version-list">${current}${versions.map((v) => `<li><a class="${v.id === version ? 'active' : ''}" href="${expertPath(name, agent, 'versions', v.id)}" ${v.id === version ? 'aria-current="page"' : ''}>${escape(dateTime(v.saved_at))}</a></li>`).join('')}</ul>`;
  let doc;
  if (version && ui.versionMissing) doc = '<p class="error-text">이 버전을 찾을 수 없습니다.</p>';
  else if (version && !ui.version) doc = '<p class="muted">불러오는 중입니다.</p>';
  else if (version) doc = `<p class="muted small-text">${escape(dateTime(ui.version.saved_at))}에 저장된 결과입니다. 지금 결과와 다를 수 있습니다.</p><div class="markdown doc">${renderMarkdown(ui.version.content)}</div>`;
  else doc = ui.module ? `<div class="markdown doc">${renderMarkdown(ui.module.content)}</div>` : '<p class="muted">지금 결과가 없습니다.</p>';
  return `<div class="versions">${list}<div class="version-doc">${doc}</div></div>`;
}

function runLine(agent) {
  if (!jobRunning()) return '';
  const job = ui.job;
  const mine = job.running_agent === agent || (job.agent === agent && job.kind === 'expert_chat');
  const text = mine ? (job.kind === 'expert_chat' ? '분석 채팅에 답하는 중입니다…' : '실행 중입니다…') : '다른 작업이 실행 중입니다. 끝나면 실행할 수 있습니다.';
  return `<p class="working" role="status">${mine ? '<span class="spinner" aria-hidden="true"></span>' : ''}${escape(text)}</p>`;
}

function reviewCard(name, agent, expert) {
  const busy = jobRunning();
  const revision = ui.revisionOpen
    ? `<form class="revision-form" id="revision-form"><label for="revision-text">무엇을 고칠지 적어 주세요</label>
        <textarea id="revision-text" data-focus="revision" maxlength="4000" rows="4">${escape(draftFor(`revision:${agent}`))}</textarea>
        <div class="form-actions"><button class="secondary" type="button" data-action="close-revision">취소</button>
        <button class="primary" type="submit" ${busy ? 'disabled' : ''}>보내기</button></div></form>`
    : '';
  const sent = ui.feedback[agent];
  const feedback = expert.done
    ? `<section class="feedback" aria-label="결과 평가"><h3>이 결과가 도움이 됐나요?</h3>
        ${sent ? `<p class="muted small-text">${sent.recorded ? '평가를 보냈습니다. 고맙습니다.' : '이 PC는 "사용 기록 보내기"가 꺼져 있어 평가가 전달되지 않았습니다. 설정에서 켤 수 있습니다.'}</p>` : `
        <label class="sr-only" for="feedback-text">한 줄 의견</label>
        <input id="feedback-text" data-focus="feedback" maxlength="500" placeholder="한 줄 의견 (선택)" value="${escape(draftFor(`feedback:${agent}`))}">
        <div class="feedback-buttons"><button class="secondary small" data-action="feedback" data-rating="up">도움 됨</button>
          <button class="secondary small" data-action="feedback" data-rating="down">아쉬움</button></div>`}
      </section>`
    : '';
  const proposalWaiting = ui.session?.proposal?.agent === agent && currentRoute.tab !== 'doc';
  return `<aside class="review-card" aria-label="검토">
    <h2>검토</h2>
    <p class="muted">결과를 확인하고 다음 작업을 고릅니다.</p>
    ${runLine(agent)}
    ${proposalWaiting ? `<p class="review-note">설계 상태 반영안이 기다리고 있습니다. <a href="${expertUrl(name, agent)}">결과 탭에서 보기</a></p>` : ''}
    <div class="review-actions">
      <button class="primary" data-action="run-expert" data-agent="${escape(agent)}" ${busy ? 'disabled' : ''}>${expert.done ? '다시 실행' : '실행'}</button>
      ${expert.done ? `<button class="secondary" data-action="open-revision" ${busy ? 'disabled' : ''}>수정 요청</button>` : ''}
    </div>
    ${revision}
    ${expert.chat ? '' : `<p class="muted small-text">${escape(expert.name)}는 정부 데이터에서 온 사실을 다루기 때문에 채팅이 없습니다. 바꿀 내용은 수정 요청으로 보내 주세요.</p>`}
    ${feedback}
  </aside>`;
}

export function expertPage(name, agent) {
  if (!ui.session) {
    return `<section class="expert-page"><p class="${ui.sessionError ? 'error-text' : 'muted'}">${escape(ui.sessionError || '불러오는 중입니다.')}</p></section>`;
  }
  const expert = expertById(agent);
  if (!expert) {
    return `<section class="expert-page"><header class="expert-head"><div><h1>전문가를 찾을 수 없습니다</h1></div>
      <a class="icon-button" href="${projectUrl(name)}" aria-label="전문가 화면 닫기">×</a></header></section>`;
  }
  const extra = expertPageTabs(agent);
  const known = currentRoute.tab !== 'model' || extra.some((t) => t.id === 'model');
  const tab = (currentRoute.tab === 'chat' && !expert.chat) || !known ? 'doc' : currentRoute.tab;
  const status = expertStatus(expert, ui.job);
  const tabs = [
    ['doc', '결과', expertUrl(name, agent)],
    ...(expert.chat ? [['chat', `분석 채팅${expert.chats?.length ? ` ${expert.chats.length}` : ''}`, expertPath(name, agent, 'chat')]] : []),
    ['versions', `이전 버전${ui.versions?.length ? ` ${ui.versions.length}` : ''}`, expertPath(name, agent, 'versions')],
    ...extra.map((t) => [t.id, t.label, expertPath(name, agent, t.id)]),
  ];
  const body = tab === 'chat' ? chatTab(name, agent, expert) : tab === 'versions' ? versionsTab(name, agent)
    : tab === 'model' ? modelTab() : docTab(name, agent, expert);
  return `<section class="expert-page" aria-label="${escape(expert.name)}">
    <header class="expert-head"><div>
      <h1>${escape(expert.name)}</h1>
      <p class="expert-meta">${escape(phaseLabel(expert))} · <span class="status-badge ${status}">${escape(STATUS_LABELS[status])}</span>${expert.updated_at ? ` · 마지막 실행 ${escape(dateTime(expert.updated_at))}` : ''}</p></div>
      <a class="icon-button" href="${projectUrl(name)}" aria-label="전문가 화면 닫기">×</a>
    </header>
    <nav class="expert-tabs" aria-label="${escape(expert.name)} 화면">
      ${tabs.map(([id, label, href]) => `<a class="tab ${id === tab ? 'active' : ''}" href="${href}" ${id === tab ? 'aria-current="page"' : ''}>${escape(label)}</a>`).join('')}
    </nav>
    <div class="expert-body">
      <section class="expert-content ${tab === 'chat' ? 'is-chat' : ''}" aria-label="${escape(tabs.find((t) => t[0] === tab)[1])}">
        ${tab === 'chat' ? body : `<div class="content-scroll" data-scroll="page:${escape(agent)}:${tab}" data-scroll-from="top">${body}</div>`}
      </section>
      ${reviewCard(name, agent, expert)}
    </div>
  </section>`;
}
