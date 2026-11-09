// The idea board's behaviour: opening on hover, moving and resizing the window, circles dragged
// between the table and the board, and every change through the ideas API.

import { escapeHtml as escape } from './model.js';
import { ideaText, moveIdea, dropIdea, sameOrder, linkPapers, pickedNotes, floatAnchor, floatPlace, ideaShape } from './board-model.js';
import { api, projectApi } from './api.js';
import { boardCall, loadBoard, table } from './board.js';
import { render } from './render.js';
import { announce, app, currentRoute, deferred, draftFor, drafts, ideaBoardOpen, toast, ui } from './state.js';

let floatDrag = null; // moving or resizing the idea window
// ------------------------------------------------------------------ the idea board

// Open or close the board in place (no redraw: the page under it keeps its state).
function showIdeaBoard() {
  const el = app.querySelector('#idea-float');
  if (!el) return;
  el.classList.toggle('is-open', ideaBoardOpen());
  placeIdeaFloat();
}

let ideaHoverTimer = 0;
function hoverIdeas(on) {
  clearTimeout(ideaHoverTimer);
  ideaHoverTimer = setTimeout(() => {
    const el = app.querySelector('#idea-float');
    if (!on && (floatDrag || dotDrag || el?.contains(document.activeElement) || el?.matches(':hover'))) return;
    if (on && (floatDrag || dotDrag?.moved || table?.carrying)) return;
    ui.ideaHover = on;
    showIdeaBoard();
  }, on ? 120 : 350);
}
app.addEventListener('pointerenter', (event) => {
  if (event.target.id === 'idea-float' && event.pointerType !== 'touch') hoverIdeas(true);
}, true);
app.addEventListener('pointerleave', (event) => {
  if (event.target.id === 'idea-float' && event.pointerType !== 'touch') hoverIdeas(false);
}, true);
app.addEventListener('focusout', (event) => {
  if (event.target.closest?.('#idea-float')) hoverIdeas(false);
});

// Open the idea board and keep it open (the `idea` command; on a phone the table pane comes up).
export function openIdeas() {
  ui.ideaFloat = { ...ui.ideaFloat, pinned: true };
  if (ui.pane === 'conductor' || ui.pane === 'side') ui.pane = 'board';
}

function pinIdeas() {
  ui.ideaFloat = { ...ui.ideaFloat, pinned: !ideaBoardOpen() || !ui.ideaFloat.pinned };
  if (!ui.ideaFloat.pinned) ui.ideaHover = false;
  render(false);
}

// Lay the idea board over the table area: held to its corner, sized to fit, never past the edges.
export function placeIdeaFloat() {
  const el = app.querySelector('#idea-float');
  const box = el?.parentElement;
  if (!el || !box || !box.clientWidth) return;
  const area = { width: box.clientWidth, height: box.clientHeight };
  const open = el.classList.contains('is-open');
  if (!open) { el.style.width = ''; el.style.height = ''; }
  const size = open ? ui.ideaFloat : { width: el.offsetWidth, height: el.offsetHeight };
  const at = floatPlace(ui.ideaFloat, size, area);
  el.style.left = `${at.left}px`;
  el.style.top = `${at.top}px`;
  if (open) { el.style.width = `${at.width}px`; el.style.height = `${at.height}px`; }
  else { el.style.maxWidth = `${area.width - 12}px`; }
}

// Dragging the board's head (or an empty part of its row of circles) moves it; its corner grip
// resizes it. On release it holds to the nearest corner.
function startFloatDrag(event) {
  const grip = event.target.closest('[data-float-drag]');
  if (!grip || event.button !== 0 || event.target.closest('button, a, input, textarea, label')) return false;
  const el = grip.closest('#idea-float');
  floatDrag = {
    mode: grip.dataset.floatDrag, el, grip, pointer: event.pointerId, x: event.clientX, y: event.clientY,
    left: el.offsetLeft, top: el.offsetTop, width: el.offsetWidth, height: el.offsetHeight, moved: false,
  };
  grip.setPointerCapture(event.pointerId);
  event.preventDefault(); // no text selection while dragging the head
  return true;
}

function moveFloatDrag(event) {
  const drag = floatDrag;
  if (!drag || event.pointerId !== drag.pointer) return;
  const dx = event.clientX - drag.x;
  const dy = event.clientY - drag.y;
  if (!drag.moved && Math.hypot(dx, dy) < 4) return;
  drag.moved = true;
  document.body.classList.add('moving-float');
  const box = drag.el.parentElement;
  if (drag.mode === 'size') {
    drag.el.style.width = `${Math.max(240, Math.min(drag.width + dx, box.clientWidth - drag.left - 6))}px`;
    drag.el.style.height = `${Math.max(180, Math.min(drag.height + dy, box.clientHeight - drag.top - 6))}px`;
  } else {
    drag.el.style.left = `${Math.max(0, Math.min(drag.left + dx, box.clientWidth - drag.width))}px`;
    drag.el.style.top = `${Math.max(0, Math.min(drag.top + dy, box.clientHeight - drag.height))}px`;
  }
}

function finishFloatDrag(event) {
  const drag = floatDrag;
  if (!drag || event.pointerId !== drag.pointer) return;
  floatDrag = null;
  document.body.classList.remove('moving-float');
  if (drag.grip.hasPointerCapture?.(drag.pointer)) drag.grip.releasePointerCapture(drag.pointer);
  if (drag.moved) {
    const el = drag.el;
    const box = el.parentElement;
    const rect = { left: el.offsetLeft, top: el.offsetTop, width: el.offsetWidth, height: el.offsetHeight };
    ui.ideaFloat = {
      ...ui.ideaFloat, ...floatAnchor(rect, { width: box.clientWidth, height: box.clientHeight }),
      ...(drag.mode === 'size' ? { width: rect.width, height: rect.height } : {}),
    };
  }
  if (deferred.render) { deferred.render = false; render(false); } else showIdeaBoard();
}

// ---- circles carried between the table and the idea board (2026-11-07 지훈)

const ideaGhost = document.createElement('div');
ideaGhost.className = 'idea-ghost';
ideaGhost.hidden = true;
ideaGhost.setAttribute('aria-hidden', 'true');
document.body.append(ideaGhost);

function showGhost(at, html, tone) {
  if (!at) { ideaGhost.hidden = true; return; }
  ideaGhost.hidden = false;
  ideaGhost.innerHTML = html;
  ideaGhost.className = `idea-ghost ${tone}`;
  ideaGhost.style.transform = `translate(${at.x}px, ${at.y}px)`;
}

const overIdeaBoard = (x, y) => {
  const r = app.querySelector('#idea-float')?.getBoundingClientRect();
  return Boolean(r && x >= r.left && x <= r.right && y >= r.top && y <= r.bottom);
};

// A paper moving on the table: its circle follows the pointer; over the idea board it can go in.
// Answers the table: 'over', 'carry', or '' (nothing the board takes, such as the site alone).
export function carryPapers(at) {
  const board = app.querySelector('#idea-float');
  const papers = at ? at.ids.map((id) => (ui.board?.papers || []).find((p) => p.id === id)).filter((p) => p && p.kind !== 'site') : [];
  if (!papers.length) { showGhost(null); board?.classList.remove('is-target'); return ''; }
  const over = overIdeaBoard(at.x, at.y);
  board?.classList.toggle('is-target', over);
  const shape = ideaShape({ paper: papers[0] });
  showGhost(at, `<span>${escape(shape.glyph)}</span>${papers.length > 1 ? `<b>${papers.length}</b>` : ''}`, `kind-${shape.kind} ${over ? 'is-over' : ''}`);
  return over ? 'over' : 'carry';
}

export async function stowPapers(name, ids) {
  ui.ideaBusy = true;
  let count = 0;
  for (const id of ids) {
    const done = await boardCall(name, () => api(`${projectApi(name)}/board/ideas/stow`, { method: 'POST', body: { paper: id } }));
    if (!done) break;
    count += 1;
  }
  ui.ideaBusy = false;
  await loadBoard(name);
  render(false);
  if (count) { toast(`아이디어 보드에 넣었습니다${count > 1 ? ` (${count}장)` : ''}. 동그라미를 제도판으로 끌면 다시 꺼내집니다.`); announce('아이디어 보드에 넣었습니다.'); }
}

// An idea onto the table where it is dropped (the middle of the view without a point).
async function placeIdea(name, id, x, y) {
  const g = (x !== undefined && table?.ground(x, y)) || table?.view;
  const spot = g ? { x: g.x, y: g.y } : {};
  const idea = ideaById(id);
  const result = await ideaCall(name, `${ideaUrl(id)}/place`, 'POST', spot);
  if (result) announce(idea?.paper ? '제도판에 꺼냈습니다.' : '메모로 꺼냈습니다.');
}

let dotDrag = null;
function startDotDrag(event) {
  const dot = event.target.closest('[data-idea-dot]');
  if (!dot || event.button !== 0 || ui.ideaBusy) return false;
  dotDrag = { id: dot.dataset.ideaDot, dot, pointer: event.pointerId, x: event.clientX, y: event.clientY, moved: false, target: null };
  dot.setPointerCapture(event.pointerId);
  return true;
}

function clearDropMarks() {
  for (const el of app.querySelectorAll('.drop-before, .drop-after')) el.classList.remove('drop-before', 'drop-after');
}

function moveDotDrag(event) {
  const drag = dotDrag;
  if (!drag || event.pointerId !== drag.pointer) return;
  if (!drag.moved && Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 4) return;
  drag.moved = true;
  ui.ideaDrag = drag.id;
  drag.dot.classList.add('is-dragging');
  document.body.classList.add('moving-float');
  const over = overIdeaBoard(event.clientX, event.clientY);
  clearDropMarks();
  drag.target = null;
  if (over) {
    // Over another idea: before it, or after it past its middle (across in the row, down in the list).
    const under = document.elementFromPoint(event.clientX, event.clientY)?.closest('[data-idea], [data-idea-dot]');
    const id = under?.dataset.idea || under?.dataset.ideaDot;
    if (under && id && id !== drag.id) {
      const r = under.getBoundingClientRect();
      const after = under.matches('.idea-dots > *') ? event.clientX > r.left + r.width / 2 : event.clientY > r.top + r.height / 2;
      under.classList.add(after ? 'drop-after' : 'drop-before');
      drag.target = { id, after };
    }
  }
  const idea = ideaById(drag.id);
  const shape = ideaShape(idea, (ui.board?.ideas || []).indexOf(idea));
  showGhost({ x: event.clientX, y: event.clientY }, `<span>${escape(shape.glyph)}</span>`, `kind-${shape.kind} ${over ? '' : 'is-out'}`);
}

function finishDotDrag(event, cancel = false) {
  const drag = dotDrag;
  if (!drag || event.pointerId !== drag.pointer) return;
  dotDrag = null;
  ui.ideaDrag = '';
  showGhost(null);
  clearDropMarks();
  document.body.classList.remove('moving-float');
  if (drag.dot.hasPointerCapture?.(drag.pointer)) drag.dot.releasePointerCapture(drag.pointer);
  drag.dot.classList.remove('is-dragging');
  const name = currentRoute.name;
  const pending = deferred.render;
  deferred.render = false;
  if (!drag.moved || cancel) {
    if (!drag.moved && !cancel && !ideaBoardOpen()) { ui.ideaHover = true; showIdeaBoard(); }
    if (pending) render(false);
    return;
  }
  const canvas = app.querySelector('.board-canvas')?.getBoundingClientRect();
  const inBoard = overIdeaBoard(event.clientX, event.clientY);
  const onTable = canvas && event.clientX >= canvas.left && event.clientX <= canvas.right && event.clientY >= canvas.top && event.clientY <= canvas.bottom;
  if (inBoard && drag.target) {
    orderIdeas(name, dropIdea((ui.board?.ideas || []).map((i) => i.id), drag.id, drag.target.id, drag.target.after));
  } else if (!inBoard && onTable) {
    placeIdea(name, drag.id, event.clientX, event.clientY);
  } else if (pending) {
    render(false);
  }
}

// One idea-board change through the API; the board is read again either way.
async function ideaCall(name, path, method, body) {
  ui.ideaBusy = true;
  render(false);
  const result = await boardCall(name, () => api(`${projectApi(name)}/board/ideas${path}`, { method, body }), true);
  ui.ideaBusy = false;
  render(false);
  return result;
}

const ideaById = (id) => (ui.board?.ideas || []).find((i) => i.id === id);
const ideaUrl = (id) => `/${encodeURIComponent(id)}`;

// `done`: the toast to show, false for none.
async function addIdea(name, data, done) {
  const text = ideaText(data.text);
  if (!text) { toast('아이디어로 넣을 글이 없습니다.', 'warn'); return null; }
  const result = await ideaCall(name, '', 'POST', { ...data, text });
  if (result && done !== false) { toast(done || `아이디어 보드 ${(ui.board?.ideas || []).length}번에 넣었습니다.`); announce('아이디어를 넣었습니다.'); }
  return result;
}

export async function addTypedIdea(name) {
  const text = draftFor('idea-new').trim();
  if (!text || ui.ideaBusy) return;
  const link = app.querySelector('#idea-new-link');
  const papers = link?.checked ? linkPapers([], ui.selected) : [];
  if (await addIdea(name, { text, papers }, '아이디어를 넣었습니다.')) {
    drafts.delete('idea-new');
    render(false);
    app.querySelector('[data-focus="idea-new"]')?.focus({ preventScroll: true });
  }
}

// The text selected inside a message. Kept as the selection changes, in case pressing the
// button clears the selection before the click arrives (a few seconds at most).
let messagePick = { article: null, text: '', at: 0 };
const selectedIn = (article) => {
  const sel = document.getSelection();
  if (!sel || sel.isCollapsed || !article.contains(sel.anchorNode)) return '';
  return sel.toString().trim();
};
document.addEventListener('selectionchange', () => {
  const sel = document.getSelection();
  const node = sel?.anchorNode;
  const article = (node?.nodeType === 1 ? node : node?.parentElement)?.closest?.('.message-list article');
  const text = article ? selectedIn(article) : '';
  if (text) messagePick = { article, text, at: Date.now() };
});

// The message as read on screen: the answer's rendered text, or the designer's own words.
function messageText(article) {
  const copy = article.querySelector('.assistant-copy');
  if (copy) return copy.innerText || copy.textContent || '';
  return [...article.childNodes].filter((n) => n.nodeType === Node.TEXT_NODE).map((n) => n.textContent).join('');
}

function ideaFromMessage(name, button) {
  const article = button.closest('article');
  if (!article) return;
  const recent = messagePick.article === article && Date.now() - messagePick.at < 8000 && document.getSelection()?.isCollapsed;
  const picked = selectedIn(article) || (recent ? messagePick.text : '');
  const text = picked || messageText(article);
  messagePick = { article: null, text: '', at: 0 };
  const talk = button.dataset.talk || null;
  addIdea(name, { text, talk }, picked ? '고른 부분을 아이디어 보드에 넣었습니다.' : '메시지를 아이디어 보드에 넣었습니다.').then((result) => {
    // Shown open for a moment, so the designer sees where it went.
    if (result && !ideaBoardOpen()) { ui.ideaHover = true; showIdeaBoard(); setTimeout(() => hoverIdeas(false), 2500); }
  });
}

async function ideasFromNotes(name) {
  const notes = pickedNotes(ui.selected, ui.board);
  let added = 0;
  for (const note of notes) {
    if (!(await addIdea(name, { text: note.text, papers: [note.id] }, false))) break;
    added += 1;
  }
  if (added) toast(`메모 ${added}장을 아이디어로 넣었습니다.`);
}

export async function saveIdea(name, id) {
  const key = `idea-edit:${id}`;
  const text = draftFor(key).trim();
  if (!text) { toast('아이디어 내용을 적어 주세요. 지우려면 지우기를 누르세요.', 'warn'); return; }
  if (await ideaCall(name, ideaUrl(id), 'PATCH', { text })) { ui.ideaEdit = ''; drafts.delete(key); render(false); }
}

function orderIdeas(name, ids) {
  const now = (ui.board?.ideas || []).map((i) => i.id);
  if (sameOrder(now, ids)) return;
  const by = new Map((ui.board?.ideas || []).map((i) => [i.id, i]));
  ui.board.ideas = ids.map((id) => by.get(id)); // drawn at once; the server's answer follows
  ideaCall(name, '/order', 'PUT', { ids });
}

export function ideaAction(name, action, button) {
  const id = button.dataset.idea;
  const idea = id ? ideaById(id) : null;
  if (action !== 'idea-delete') ui.ideaConfirm = '';
  if (action === 'idea-float-pin') { pinIdeas(); return; }
  if (action === 'idea-from-message') { ideaFromMessage(name, button); return; }
  if (action === 'idea-notes') { ideasFromNotes(name); return; }
  if (action === 'idea-cancel') { drafts.delete(`idea-edit:${ui.ideaEdit}`); ui.ideaEdit = ''; render(false); return; }
  if (!idea || ui.ideaBusy) return;
  if (action === 'idea-move') orderIdeas(name, moveIdea(ui.board.ideas.map((i) => i.id), id, Number(button.dataset.step)));
  if (action === 'idea-edit') {
    ui.ideaEdit = id;
    drafts.set(`idea-edit:${id}`, idea.text);
    render(false);
    const box = app.querySelector(`[data-focus="idea-edit:${CSS.escape(id)}"]`);
    box?.focus({ preventScroll: true });
    box?.setSelectionRange(box.value.length, box.value.length);
  }
  if (action === 'idea-place') placeIdea(name, id);
  if (action === 'idea-off') ideaCall(name, ideaUrl(id), 'PATCH', { off: !idea.off });
  if (action === 'idea-link') ideaCall(name, ideaUrl(id), 'PATCH', { papers: linkPapers(idea.papers, ui.selected) });
  if (action === 'idea-unlink') ideaCall(name, ideaUrl(id), 'PATCH', { papers: (idea.papers || []).filter((x) => x !== button.dataset.id) });
  if (action === 'idea-unlink-talk') ideaCall(name, ideaUrl(id), 'PATCH', { talk: null });
  if (action === 'idea-delete') {
    if (ui.ideaConfirm !== id) { ui.ideaConfirm = id; render(false); return; }
    ui.ideaConfirm = '';
    if (ui.ideaEdit === id) ui.ideaEdit = '';
    ideaCall(name, ideaUrl(id), 'DELETE');
  }
}

export function ideaDragging() { return Boolean(floatDrag || dotDrag); }

app.addEventListener('pointerdown', (event) => { if (!startDotDrag(event)) startFloatDrag(event); });
window.addEventListener('pointermove', (event) => { moveFloatDrag(event); moveDotDrag(event); });
window.addEventListener('pointerup', (event) => { finishFloatDrag(event); finishDotDrag(event); });
window.addEventListener('pointercancel', (event) => { finishFloatDrag(event); finishDotDrag(event, true); });
