// The Conductor panel: saved talks, one conversation, the message composer (HTML strings).

import { STATUS_LABELS, escapeHtml as escape, relativeDate, chatItems, expertStatus, renderMarkdown } from './model.js';
import { pickedNames } from './board-model.js';
import { MAIN_JOBS, currentRoute, draftFor, expertById, jobRunning, tableShown, talkViewById, ui } from './state.js';

// Papers picked on the drafting table go with the next message (and the next expert run).
// A chip's name opens the paper at reading size; × takes it out.
function pickedChips() {
  const withTable = tableShown();
  if (!ui.selected.length) {
    return withTable ? '<div class="picked" aria-label="질문에 함께 보낼 자료"><span class="picked-hint">제도판에서 종이를 고르면 이 질문에 자료로 붙습니다</span></div>' : '';
  }
  return `<div class="picked" aria-label="질문에 함께 보낼 자료"><span class="picked-label">함께 보낼 자료 ${ui.selected.length}개</span>
    <div class="picked-chips">${pickedNames(ui.selected, ui.board).map((p) => `<span class="attachment">${withTable
    ? `<button type="button" class="attachment-title" data-action="inspect-paper" data-id="${escape(p.id)}" title="상세 보기">${escape(p.name)}</button>`
    : `<span class="attachment-title">${escape(p.name)}</span>`}<button type="button" class="attachment-remove" data-action="unpick" data-id="${escape(p.id)}" aria-label="${escape(p.name)} 질문 자료에서 빼기">×</button></span>`).join('')}</div></div>`;
}


function contextChips(context) {
  if (!context?.length) return '';
  return `<div class="context-chips" aria-label="함께 보낸 제도판 종이">${context.map((c) => `<span class="paper-chip">${escape(c.name || c.id)}</span>`).join('')}</div>`;
}

export function composer(key, placeholder, label, disabled) {
  return `<form class="composer" data-composer="${escape(key)}" aria-label="${escape(label)} 입력">
    ${pickedChips()}
    <textarea data-focus="${escape(key)}" aria-label="${escape(label)}에게 메시지" placeholder="${escape(placeholder)}" maxlength="6000" rows="1">${escape(draftFor(key))}</textarea>
    <div class="composer-footer"><span class="composer-hint">${disabled ? '작업이 끝나면 보낼 수 있습니다.' : 'Enter로 보내기 · Shift+Enter로 줄 바꿈'}</span>
      <button class="send-button" type="submit" aria-label="${escape(label)}에게 보내기" ${disabled ? 'disabled' : ''}>↑</button></div>
  </form>`;
}

// A saved message can go onto the idea board (all of it, or the part selected in it).
function ideaButton(source) {
  if (!source || currentRoute.page !== 'project') return '';
  return `<button type="button" class="to-idea" data-action="idea-from-message" ${source.talk ? `data-talk="${escape(source.talk)}"` : ''} title="이 메시지(또는 드래그로 고른 부분)를 아이디어 보드에 넣기">＋ 아이디어로</button>`;
}

export function bubble(item, speaker, source = null) {
  if (item.kind === 'user') return `${contextChips(item.context)}<article class="message-user" aria-label="내 메시지">${escape(item.text)}${source && item.text ? ideaButton(source) : ''}</article>`;
  if (item.kind === 'note') return `<p class="event-note ${item.tone || ''}">${escape(item.text)}</p>`;
  if (item.kind === 'card') {
    const expert = expertById(item.agent);
    const status = expert ? STATUS_LABELS[expertStatus(expert, ui.job)] : '';
    return `<button class="analysis-card" data-action="open-expert" data-agent="${escape(item.agent)}">
      <h2>${escape(item.name)} 결과</h2>
      <p class="analysis-meta">${escape(item.name)}${status ? ` · ${escape(status)}` : ''}</p>
      <span class="analysis-link">분석 보기 ↗</span></button>`;
  }
  const [who, role] = Array.isArray(speaker) ? speaker : [speaker, ''];
  return `<article><h3 class="speaker">${escape(who)}${role ? ` <span>${escape(role)}</span>` : ''}</h3><div class="assistant-copy markdown">${renderMarkdown(item.text)}</div>${source && item.text ? ideaButton(source) : ''}</article>`;
}

export function workingLine(forMain) {
  if (!jobRunning()) return '';
  const job = ui.job;
  if (forMain !== MAIN_JOBS.has(job.kind)) return '';
  const running = job.running_agent ? expertById(job.running_agent) : null;
  const text = running ? `${running.name} 실행 중입니다…` : forMain ? 'Conductor가 답을 쓰는 중입니다…' : '전문가가 답을 쓰는 중입니다…';
  return `<p class="working" role="status"><span class="spinner" aria-hidden="true"></span>${escape(text)}</p>`;
}

// ------------------------------------------------------------------ talks and the command line
// The same saved talks back the left panel and questions entered on the command line.

export function talkTitle(talk) {
  if (talk?.title) return talk.title;
  return talk?.id === '01' ? '첫 대화' : '새 대화';
}

export function talkSummary(id) {
  return ui.session?.talks?.find((t) => t.id === id) || { id, title: '', messages: 0, updated_at: '' };
}

// Saved conversations, newest first, inside the Conductor panel.
function talkActions(id) {
  return `<details class="talk-more" ${ui.talkMenu === id ? 'open' : ''}>
    <summary data-action="talk-menu" data-talk="${escape(id)}" data-focus="talk-menu-${escape(id)}" aria-label="${escape(talkTitle(talkSummary(id)))} 대화 메뉴" title="대화 메뉴">⋯</summary>
    <div class="talk-more-options"><button type="button" class="talk-delete" data-action="talk-delete" data-talk="${escape(id)}" ${jobRunning() ? 'disabled' : ''}>대화 삭제</button></div>
  </details>`;
}

function talksCard() {
  const session = ui.session;
  const talks = [...(session?.talks || [])].reverse();
  const body = !session
    ? `<p class="${ui.sessionError ? 'error-text' : 'muted'}">${escape(ui.sessionError || '대화를 불러오는 중입니다.')}</p>`
    : !talks.length ? '<p class="muted">저장된 대화가 없습니다. 새 대화를 시작해 보세요.</p>'
    : `<ul class="talk-list" aria-label="Conductor 대화 목록">${talks.map((t) => `<li>
        <button type="button" class="talk-row" data-action="talk-open" data-talk="${escape(t.id)}" aria-pressed="${ui.conductor.active === t.id}">
          <span class="talk-row-title">${escape(talkTitle(t))}</span>
          <span class="talk-row-meta">${t.messages ? `메시지 ${t.messages}개` : '아직 비어 있음'}${t.updated_at ? ` · ${escape(relativeDate(t.updated_at))}` : ''}${jobRunning() && ui.job.talk === t.id ? ' · 답하는 중' : ''}</span>
        </button>${talkActions(t.id)}</li>`).join('')}</ul>`;
  return `<section class="conductor-history" aria-label="대화 목록">
      <div class="talk-list-scroll" data-scroll="talks" data-scroll-from="top">${body}</div></section>`;
}

export function conductorPanel() {
  const id = ui.conductor.active;
  const view = talkViewById(id);
  return `<aside class="conductor-panel panel" id="conductor-panel" aria-label="Conductor 대화" ${ui.conductor.open ? '' : 'hidden'}>
      <header class="pane-head"><div><span class="eyebrow">설계 대화</span><h2>Conductor</h2></div>
        <button type="button" class="ghost" data-action="conductor-close" aria-label="Conductor 대화 닫기" title="대화 패널 접기">‹</button></header>
      <div class="conductor-toolbar"><button type="button" data-action="talk-new">＋ 새 대화</button>
        <button type="button" data-action="talks-toggle" aria-expanded="${ui.conductor.list}">${ui.conductor.list ? '대화로 돌아가기' : '이전 대화'}</button></div>
      ${ui.sessionError ? `<p class="error-text conductor-error">${escape(ui.sessionError)}</p>` : ''}
      ${ui.conductor.list ? talksCard() : view ? talkConversation(view) : `<div class="conductor-welcome"><span class="conductor-mark" aria-hidden="true">S</span><h3>설계 이야기를 시작해 보세요</h3><p>아이디어를 나누거나 제도판에서 고른 자료를 함께 검토할 수 있습니다.</p></div>
        ${composer('conductor-new', 'Conductor에게 질문하세요…', 'Conductor', jobRunning() || ui.creatingTalk || !ui.session)}`}
    </aside>`;
}

function talkWorking(id) {
  if (!jobRunning() || ui.job.talk !== id) return '';
  const running = ui.job.running_agent ? expertById(ui.job.running_agent) : null;
  const text = running ? `${running.name} 실행 중입니다…` : 'Conductor가 답을 쓰는 중입니다…';
  return `<p class="working" role="status"><span class="spinner" aria-hidden="true"></span>${escape(text)}</p>`;
}

// The papers a view's next question carries: × takes one out, and what is picked on the table
// now can be added.
function talkContext(view) {
  const names = pickedNames(view.context, ui.board);
  const more = ui.selected.filter((id) => !view.context.includes(id));
  if (!names.length && !more.length) return '';
  return `<div class="talk-context" aria-label="이번 질문에 함께 보낼 자료">
      ${names.map((p) => `<span class="attachment"><button type="button" class="attachment-title" data-action="inspect-paper" data-id="${escape(p.id)}" title="상세 보기">${escape(p.name)}</button><button type="button" class="attachment-remove" data-action="talk-unpick" data-talk="${escape(view.id)}" data-id="${escape(p.id)}" aria-label="${escape(p.name)} 빼기">×</button></span>`).join('')}
      ${more.length ? `<button type="button" class="talk-add-picked" data-action="talk-add-picked" data-talk="${escape(view.id)}">＋ 고른 종이 ${more.length}개 넣기</button>` : ''}
    </div>`;
}

function talkConversation(view) {
  const { id } = view;
  const loaded = ui.talks.get(id);
  const items = chatItems(loaded?.messages || []);
  const key = `talk:${id}`;
  const pending = ui.pending?.target === key ? [{ kind: 'user', text: ui.pending.text, context: ui.pending.context }] : [];
  const live = ui.job?.talk === id ? ui.live : [];
  const busy = jobRunning();
  const empty = !items.length && !pending.length && !live.length && !talkWorking(id);
  return `<section class="talk-conversation" data-talk="${escape(id)}" aria-label="대화: ${escape(talkTitle(talkSummary(id)))}">
      <header class="talk-head"><strong>${escape(talkTitle(talkSummary(id)))}</strong>${talkActions(id)}</header>
      <div class="talk-scroll" data-scroll="${escape(key)}">
        ${loaded?.error ? `<p class="error-text">${escape(loaded.error)}</p>` : ''}
        ${empty && !loaded?.error ? `<p class="muted">${loaded ? '아직 대화가 없습니다.' : '대화를 불러오는 중입니다.'}</p>` : ''}
        <div class="message-list" role="log" aria-label="대화 메시지">
          ${items.map((item) => bubble(item, ['Sida', 'Conductor'], { talk: id })).join('')}
          ${[...pending, ...live].map((item) => bubble(item, ['Sida', 'Conductor'])).join('')}
          ${talkWorking(id)}
        </div>
      </div>
      <form class="composer talk-composer" data-composer="${escape(key)}" aria-label="이 대화에 이어서 묻기">
        ${talkContext(view)}
        <textarea data-focus="${escape(key)}" aria-label="이 대화에 이어서 묻기" placeholder="이어서 묻기" maxlength="6000" rows="1">${escape(draftFor(key))}</textarea>
        <div class="composer-footer"><span class="composer-hint">${busy ? '작업이 끝나면 보낼 수 있습니다.' : 'Enter로 보내기 · Shift+Enter로 줄 바꿈'}</span>
          <button class="send-button" type="submit" aria-label="이 대화에 보내기" ${busy ? 'disabled' : ''}>↑</button></div>
      </form>
    </section>`;
}
