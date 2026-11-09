// The idea board that floats over the drafting table (HTML strings).

import { escapeHtml as escape } from './model.js';
import { ideaPapers, pickedNotes, ideasInPlay, MAX_IDEA_TEXT, MAX_IDEA_PAPERS, ideaShape } from './board-model.js';
import { projectApi } from './api.js';
import { currentRoute, draftFor, ideaBoardOpen, ui } from './state.js';
import { talkSummary, talkTitle } from './view-conductor.js';

function ideaTalkChip(idea, editing) {
  if (!idea.talk) return '';
  const known = ui.session?.talks?.some((t) => t.id === idea.talk);
  const label = known ? `대화: ${talkTitle(talkSummary(idea.talk))}` : '지운 대화';
  return `<span class="attachment idea-talk">${known
    ? `<button type="button" class="attachment-title" data-action="talk-open" data-talk="${escape(idea.talk)}" title="이 대화 열기">${escape(label)}</button>`
    : `<span class="attachment-title">${escape(label)}</span>`}${editing ? `<button type="button" class="attachment-remove" data-action="idea-unlink-talk" data-idea="${escape(idea.id)}" aria-label="대화 연결 끊기">×</button>` : ''}</span>`;
}

// One idea as a circle: drag it to reorder, or out onto the table to take it out (2026-11-07 지훈).
function ideaDot(idea, index) {
  const shape = ideaShape(idea, index);
  const label = shape.name || shape.text;
  const inner = shape.photo
    ? `<img src="${escape(`${projectApi(currentRoute.name)}/board/photos/${encodeURIComponent(idea.paper.id)}`)}" alt="" draggable="false" decoding="async">`
    : `<span aria-hidden="true">${escape(shape.glyph)}</span>`;
  return `<button type="button" class="idea-dot kind-${shape.kind} ${idea.off ? 'is-off' : ''} ${ui.ideaDrag === idea.id ? 'is-dragging' : ''} ${ui.ideaNew?.has(idea.id) ? 'is-new' : ''}" data-idea-dot="${escape(idea.id)}"
    title="${escape(label.slice(0, 120))}${idea.off ? ' (잠시 뺌)' : ''} · 끌어서 순서 바꾸기, 제도판으로 끌어 꺼내기" aria-label="아이디어 ${index + 1}: ${escape(label.slice(0, 60))}">${inner}</button>`;
}

function ideaItem(idea, index, total) {
  const id = escape(idea.id);
  const editing = ui.ideaEdit === idea.id;
  const busy = ui.ideaBusy;
  const shape = ideaShape(idea, index);
  const papers = ideaPapers(idea, ui.board);
  const links = papers.map((p) => `<span class="attachment"><button type="button" class="attachment-title" data-action="inspect-paper" data-id="${escape(p.id)}" title="상세 보기">${escape(p.name)}</button>${editing ? `<button type="button" class="attachment-remove" data-action="idea-unlink" data-idea="${id}" data-id="${escape(p.id)}" aria-label="${escape(p.name)} 연결 끊기">×</button>` : ''}</span>`).join('') + ideaTalkChip(idea, editing);
  const more = ui.selected.filter((x) => !(idea.papers || []).includes(x));
  const key = `idea-edit:${idea.id}`;
  const held = idea.paper ? `<p class="idea-paper"><b>${escape(shape.name)}</b>${shape.text && shape.kind !== 'note' ? ` · ${escape(shape.text)}` : ''}</p>` : '';
  const words = idea.paper ? (idea.text ? `<p class="idea-text idea-caption">${escape(idea.text)}</p>` : '') : `<p class="idea-text">${escape(idea.text)}</p>`;
  const body = editing
    ? `${held}<form class="idea-edit" data-idea-form="${id}">
        <textarea data-focus="${escape(key)}" data-idea-draft="${escape(key)}" aria-label="아이디어 ${index + 1} ${idea.paper ? '설명' : '고치기'}" maxlength="${MAX_IDEA_TEXT}" rows="3" placeholder="${idea.paper ? '이 종이에 붙일 한마디 (비워도 됨)' : ''}">${escape(draftFor(key))}</textarea>
        <div class="idea-edit-actions"><span class="composer-hint">Enter 저장 · Esc 취소</span>
          <button type="button" class="secondary small" data-action="idea-cancel">취소</button><button type="submit" class="primary small" ${busy ? 'disabled' : ''}>저장</button></div></form>`
    : `${held}${words}`;
  const confirm = ui.ideaConfirm === idea.id;
  return `<li class="idea ${idea.off ? 'is-off' : ''} ${ui.ideaDrag === idea.id ? 'is-dragging' : ''} ${ui.ideaNew?.has(idea.id) ? 'is-new' : ''}" data-idea="${id}">
      ${ideaDot(idea, index)}
      <div class="idea-body">
        ${idea.off ? '<span class="idea-off-badge">잠시 뺌 · AI에게 안 감</span>' : ''}
        ${body}
        ${links ? `<div class="idea-links" aria-label="연결된 자료">${links}</div>` : ''}
        <div class="idea-actions" aria-label="아이디어 ${index + 1} 편집">
          <button type="button" data-action="idea-move" data-idea="${id}" data-step="-1" aria-label="위로" title="위로" ${index === 0 || busy ? 'disabled' : ''}>↑</button>
          <button type="button" data-action="idea-move" data-idea="${id}" data-step="1" aria-label="아래로" title="아래로" ${index === total - 1 || busy ? 'disabled' : ''}>↓</button>
          ${editing ? '' : `<button type="button" data-action="idea-edit" data-idea="${id}">${idea.paper ? '한마디' : '고치기'}</button>`}
          <button type="button" data-action="idea-off" data-idea="${id}" ${busy ? 'disabled' : ''} title="${idea.off ? 'AI가 다시 이 아이디어를 고려합니다' : '이 아이디어 없이 탐색해 보고 싶을 때: AI에게 보내지 않습니다'}">${idea.off ? '다시 넣기' : '잠시 빼기'}</button>
          <button type="button" data-action="idea-place" data-idea="${id}" ${busy ? 'disabled' : ''} title="제도판 가운데에 꺼내 놓기 (동그라미를 제도판으로 끌어도 됩니다)">${idea.paper ? '제도판에 꺼내기' : '메모로 꺼내기'}</button>
          ${more.length ? `<button type="button" data-action="idea-link" data-idea="${id}" ${busy || (idea.papers || []).length >= MAX_IDEA_PAPERS ? 'disabled' : ''}>＋ 고른 종이 ${more.length}개 연결</button>` : ''}
          <button type="button" class="idea-delete ${confirm ? 'confirm' : ''}" data-action="idea-delete" data-idea="${id}" ${busy ? 'disabled' : ''} title="${idea.paper ? '종이와 함께 지웁니다' : ''}">${confirm ? '정말 지우기' : '지우기'}</button>
        </div>
      </div>
    </li>`;
}

// The idea board floats over the drafting table in a corner, always there (2026-11-07 지훈):
// a row of circles, opening into the ideas with a little of each while the pointer is over it.
export function ideaFloatView() {
  const ideas = ui.board?.ideas || [];
  const busy = ui.ideaBusy || !ui.board;
  const picked = ui.selected.length;
  const notes = pickedNotes(ui.selected, ui.board);
  const inPlay = ideasInPlay(ui.board);
  const open = ideaBoardOpen();
  const list = !ui.board ? '<p class="muted">제도판을 불러오는 중입니다.</p>'
    : ideas.length ? `<ol class="idea-list" aria-label="아이디어 목록 (순서대로)">${ideas.map((idea, i) => ideaItem(idea, i, ideas.length)).join('')}</ol>`
    : `<div class="idea-empty"><p><b>설계를 이끌 메인 아이디어를 모아 두세요.</b></p>
        <p>제도판의 종이를 끌어 이 보드에 놓으면 동그라미로 들어옵니다. 동그라미를 제도판으로 끌어내면 다시 꺼내집니다. 아래에 직접 적거나 대화의 <b>＋ 아이디어로</b>도 됩니다. 순서가 곧 중요도입니다.</p></div>`;
  const pin = ui.ideaFloat.pinned;
  return `<section class="idea-float ${open ? 'is-open' : ''} at-${ui.ideaFloat.corner}" id="idea-float" aria-label="아이디어 보드">
    <div class="idea-dock" data-float-drag="move" title="아이디어 보드 · 마우스를 올리면 펼쳐집니다 · 빈 곳을 끌어 옮기기">
      <span class="idea-dock-label">아이디어</span>
      ${ideas.length ? `<div class="idea-dots" aria-label="아이디어 ${ideas.length}개">${ideas.map((idea, i) => ideaDot(idea, i)).join('')}</div>` : '<span class="idea-dock-empty">종이를 여기로 끌어 넣기</span>'}
      <button type="button" class="idea-dock-open" data-action="idea-float-pin" aria-label="아이디어 보드 펼쳐 두기" aria-expanded="false">⌄</button>
    </div>
    <div class="idea-panel">
      <header class="idea-float-head" data-float-drag="move" title="끌어서 옮기기 · 가까운 구석에 붙습니다">
        <div><h2>아이디어 보드${ideas.length ? ` <span class="expert-count">${ideas.length}</span>` : ''}</h2>
        <p>${ideas.length ? `AI가 읽는 아이디어 ${inPlay}개 · AI는 읽기만 합니다` : 'AI는 읽기만 하고 바꾸지 않습니다'}</p></div>
        <button type="button" class="ghost idea-float-pin ${pin ? 'is-on' : ''}" data-action="idea-float-pin" aria-pressed="${Boolean(pin)}" title="${pin ? '마우스를 떼면 다시 동그라미로 접히게' : '마우스를 떼도 펼쳐 두기'}" aria-label="펼쳐 두기">${pin ? '접기' : '고정'}</button></header>
      <div class="ideas-scroll" data-scroll="ideas" data-scroll-from="top">${list}</div>
      <form class="idea-new" id="idea-new-form" aria-label="새 아이디어">
        ${notes.length ? `<button type="button" class="idea-from-notes" data-action="idea-notes" ${busy ? 'disabled' : ''}>고른 메모 ${notes.length}장을 아이디어로</button>` : ''}
        <textarea data-focus="idea-new" data-idea-draft="idea-new" aria-label="새 아이디어" placeholder="새 아이디어 적기 (예: 길에서 마당이 보이게)" maxlength="${MAX_IDEA_TEXT}" rows="2">${escape(draftFor('idea-new'))}</textarea>
        <div class="idea-new-footer">
          ${picked ? `<label class="idea-link-picked"><input type="checkbox" id="idea-new-link" ${ui.ideaLinkNew ? 'checked' : ''}> 고른 종이 ${Math.min(picked, MAX_IDEA_PAPERS)}장 연결</label>` : '<span class="composer-hint">Enter 추가 · Shift+Enter 줄 바꿈</span>'}
          <button type="submit" class="primary small" ${busy ? 'disabled' : ''}>추가</button></div>
      </form>
      <div class="idea-float-size" data-float-drag="size" title="끌어서 크기 조절" aria-hidden="true"></div>
    </div>
  </section>`;
}
