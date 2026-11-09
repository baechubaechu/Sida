// Docking the panels beside the drafting table (dock-model.js, view-dock.js): dragging a tab to
// another group, above or below one, to an empty side, or over the table to float it; moving and
// sizing a floating window; dragging the line between two groups; folding and unfolding a side; and keeping the layout on this PC's server (GET/PUT
// /api/panel-layout), read once when the first project opens.

import { api } from './api.js';
import {
  DEFAULT_PANEL_RATIOS, FLOAT_SIZE, activate, defaultDock, dockFloat, dockForSaving, dropTarget, moveFloat, movePanel, normalizeDock, resizeGroups,
  setSideOpen, sideShown, swapActive,
} from './dock-model.js';
import { placeTable } from './board.js';
import { render } from './render.js';
import { app, currentRoute, deferred, toast, ui } from './state.js';

const narrow = () => matchMedia('(max-width: 900px)').matches;
const EDGE = 72; // px: the strip along an empty or folded side where a tab can be dropped

// ------------------------------------------------------------------ keeping the layout

let loading = null;
export function loadDock() {
  loading ||= api('/api/panel-layout').then((data) => {
    if (data?.layout) {
      ui.dock = normalizeDock(data.layout);
      ui.panelRatios = { ...ui.panelRatios, ...(data.layout.ratios || {}) };
    }
    return true;
  }).catch(() => false);
  return loading;
}

let saveTimer = 0;
export function saveDock() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => {
    api('/api/panel-layout', { method: 'PUT', body: { ...dockForSaving(ui.dock), ratios: ui.panelRatios } })
      .catch(() => toast('패널 배치를 저장하지 못했습니다. 이번 화면에서만 유지됩니다.', 'warn'));
  }, 400);
}

export function resetDock() {
  ui.dock = defaultDock();
  ui.panelRatios = { ...DEFAULT_PANEL_RATIOS };
  saveDock();
}

// Selecting a paper turns 레이어 to 속성 where they share a group; clearing turns it back.
export function followSelection(selected) {
  const [from, to] = selected ? ['layers', 'props'] : ['props', 'layers'];
  ui.dock = swapActive(ui.dock, from, to);
  if (ui.narrowSide === from) ui.narrowSide = to;
}

// The buttons of the docked panels (app.js passes them on).
export function dockAction(action, button) {
  if (action === 'dock-tab') {
    const id = button.dataset.panel;
    ui.dock = activate(ui.dock, id);
    if (id !== 'conductor') ui.narrowSide = id;
  } else if (action === 'dock-fold') {
    ui.dock = setSideOpen(ui.dock, button.dataset.side, false);
    if (ui.pane !== 'board') ui.pane = 'board';
  } else if (action === 'dock-open') {
    ui.dock = setSideOpen(ui.dock, button.dataset.side, true);
  } else if (action === 'dock-float-back') {
    ui.dock = dockFloat(ui.dock, Number(button.dataset.index), 'right');
  } else {
    return false;
  }
  saveDock();
  render(false);
  if (action === 'dock-fold') app.querySelector(`[data-action="dock-open"][data-side="${button.dataset.side}"]`)?.focus({ preventScroll: true });
  return true;
}

// ------------------------------------------------------------------ dragging a tab

let drag = null;
let swallowClick = false;
export function dockDragging() { return Boolean(drag?.moving); }

// What is on screen to drop onto: each group (with where its tab row ends) and, along an edge
// whose side is empty or folded, a strip that takes a new group. The right side is not offered
// while the site or an expert's page fills it.
function dropGeometry() {
  // Floating windows lie on top, so they come first.
  const elements = [...app.querySelectorAll('[data-group^="float:"]'), ...app.querySelectorAll('.dock [data-group]')];
  const groups = elements.map((el) => {
    const r = el.getBoundingClientRect();
    const [side, index] = el.dataset.group.split(':');
    return { side, index: Number(index), left: r.left, right: r.right, top: r.top, bottom: r.bottom, tabsBottom: el.querySelector('.dock-head').getBoundingClientRect().bottom };
  });
  const studio = app.querySelector('.studio').getBoundingClientRect();
  const zones = [];
  if (!sideShown(ui.dock, 'left')) zones.push({ side: 'left', left: studio.left, right: studio.left + EDGE, top: studio.top, bottom: studio.bottom });
  if (!sideShown(ui.dock, 'right') && !currentRoute.agent && !currentRoute.site) zones.push({ side: 'right', left: studio.right - EDGE, right: studio.right, top: studio.top, bottom: studio.bottom });
  const board = app.querySelector('.studio > .board')?.getBoundingClientRect() || null;
  return { groups, zones, board, origin: studio };
}

function hintRect(target, geometry) {
  if (target.place === 'end') return geometry.zones.find((z) => z.side === target.side);
  if (target.place === 'new') {
    const room = geometry.origin;
    const left = room.left + Math.max(0, Math.min(target.x, room.width - FLOAT_SIZE.w));
    const top = room.top + Math.max(0, Math.min(target.y, room.height - FLOAT_SIZE.h));
    return { left, top, right: left + FLOAT_SIZE.w, bottom: top + FLOAT_SIZE.h };
  }
  const g = geometry.groups.find((x) => x.side === target.side && x.index === target.index);
  if (target.place === 'tab') return g;
  const middle = g.tabsBottom + (g.bottom - g.tabsBottom) / 2;
  return target.place === 'above' ? { ...g, top: g.tabsBottom, bottom: middle } : { ...g, top: middle };
}

function showHint(target) {
  let hint = document.querySelector('.dock-hint');
  if (!target) { hint?.remove(); return; }
  if (!hint) { hint = document.createElement('div'); hint.className = 'dock-hint'; document.body.append(hint); }
  const r = hintRect(target, drag.geometry);
  Object.assign(hint.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.right - r.left}px`, height: `${r.bottom - r.top}px` });
}

function endDrag(apply) {
  const d = drag;
  drag = null;
  if (!d) return;
  if (d.tab.hasPointerCapture(d.pointer)) d.tab.releasePointerCapture(d.pointer);
  if (!d.moving) return;
  swallowClick = true; // the click that ends a drag is not a tab click
  setTimeout(() => { swallowClick = false; }, 0);
  d.ghost.remove();
  showHint(null);
  document.body.classList.remove('dock-dragging');
  if (apply && d.target) {
    // A new floating window opens wholly inside the workspace.
    const room = d.geometry.origin;
    const target = d.target.place === 'new'
      ? { ...d.target, x: Math.min(d.target.x, room.width - FLOAT_SIZE.w), y: Math.min(d.target.y, room.height - FLOAT_SIZE.h) }
      : d.target;
    ui.dock = movePanel(ui.dock, d.id, target);
    if (d.id !== 'conductor') ui.narrowSide = d.id;
    saveDock();
    deferred.render = false;
    render(false);
  } else if (deferred.render) {
    deferred.render = false;
    render(false);
  }
}

app.addEventListener('pointerdown', (event) => {
  const tab = event.target.closest('.dock-tab');
  if (!tab || event.button !== 0 || narrow()) return;
  drag = { tab, id: tab.dataset.panel, pointer: event.pointerId, x: event.clientX, y: event.clientY, moving: false, target: null };
  tab.setPointerCapture(event.pointerId);
});

window.addEventListener('pointermove', (event) => {
  if (!drag || event.pointerId !== drag.pointer) return;
  if (!drag.moving) {
    if (Math.hypot(event.clientX - drag.x, event.clientY - drag.y) < 6) return;
    drag.moving = true;
    drag.geometry = dropGeometry();
    drag.ghost = document.createElement('div');
    drag.ghost.className = 'dock-ghost';
    drag.ghost.textContent = drag.tab.textContent;
    document.body.append(drag.ghost);
    document.body.classList.add('dock-dragging');
  }
  drag.ghost.style.transform = `translate(${event.clientX + 12}px, ${event.clientY + 12}px)`;
  const g = drag.geometry;
  drag.target = dropTarget({ x: event.clientX, y: event.clientY }, g.groups, g.zones, g.board, g.origin);
  showHint(drag.target);
});

window.addEventListener('pointerup', (event) => { if (drag && event.pointerId === drag.pointer) endDrag(true); });
window.addEventListener('pointercancel', (event) => { if (drag && event.pointerId === drag.pointer) endDrag(false); });
window.addEventListener('keydown', (event) => { if (event.key === 'Escape' && drag?.moving) { event.preventDefault(); endDrag(false); } }, true);
app.addEventListener('click', (event) => {
  if (!swallowClick) return;
  swallowClick = false;
  event.preventDefault();
  event.stopPropagation();
}, true);

// ------------------------------------------------------------------ moving and sizing a floating window

let floatMove = null;
export function floatMoving() { return Boolean(floatMove); }

app.addEventListener('pointerdown', (event) => {
  const corner = event.target.closest('[data-float-resize]');
  const head = event.target.closest('.dock-float .dock-head');
  if (event.button !== 0 || (!corner && (!head || event.target.closest('button')))) return;
  const win = event.target.closest('[data-float]');
  const index = Number(win.dataset.float);
  event.preventDefault();
  floatMove = { win, index, resize: Boolean(corner), pointer: event.pointerId, x: event.clientX, y: event.clientY, start: { x: win.offsetLeft, y: win.offsetTop, w: win.offsetWidth, h: win.offsetHeight }, layout: ui.dock,
    // The workspace the window must stay over (its head at least).
    room: app.querySelector('.studio').getBoundingClientRect() };
  (corner || head).setPointerCapture(event.pointerId);
  document.body.classList.add(corner ? 'resizing-float' : 'moving-float');
});

window.addEventListener('pointermove', (event) => {
  const m = floatMove;
  if (!m || event.pointerId !== m.pointer) return;
  const dx = event.clientX - m.x;
  const dy = event.clientY - m.y;
  const s = m.start;
  ui.dock = m.resize
    ? moveFloat(m.layout, m.index, s.x, s.y, Math.min(s.w + dx, m.room.width - s.x), Math.min(s.h + dy, m.room.height - s.y))
    : moveFloat(m.layout, m.index, Math.min(s.x + dx, m.room.width - s.w), Math.min(s.y + dy, m.room.height - s.h));
  const g = ui.dock.float[m.index];
  Object.assign(m.win.style, { left: `${g.x}px`, top: `${g.y}px`, width: `${g.w}px`, height: `${g.h}px` });
});

function endFloatMove(event, cancel) {
  const m = floatMove;
  if (!m || event.pointerId !== m.pointer) return;
  floatMove = null;
  document.body.classList.remove('resizing-float', 'moving-float');
  if (cancel) ui.dock = m.layout;
  else saveDock();
  if (deferred.render || cancel) { deferred.render = false; render(false); }
}
window.addEventListener('pointerup', (event) => endFloatMove(event, false));
window.addEventListener('pointercancel', (event) => endFloatMove(event, true));

// ------------------------------------------------------------------ the line between two groups

let split = null;
export function dockSplitting() { return Boolean(split); }

function splitParts(handle) {
  const [side, index] = handle.dataset.dockSplit.split(':');
  const elements = [...app.querySelectorAll(`[data-dock="${side}"] > [data-group]`)];
  return { side, index: Number(index), elements, heights: elements.map((el) => el.getBoundingClientRect().height) };
}

app.addEventListener('pointerdown', (event) => {
  const handle = event.target.closest('[data-dock-split]');
  if (!handle || event.button !== 0) return;
  event.preventDefault();
  split = { ...splitParts(handle), handle, pointer: event.pointerId, y: event.clientY, layout: ui.dock };
  handle.setPointerCapture(event.pointerId);
  handle.focus({ preventScroll: true });
  document.body.classList.add('resizing-groups');
});

window.addEventListener('pointermove', (event) => {
  if (!split || event.pointerId !== split.pointer) return;
  ui.dock = resizeGroups(split.layout, split.side, split.index, event.clientY - split.y, split.heights);
  ui.dock[split.side].groups.forEach((g, i) => { split.elements[i].style.flexGrow = g.size; });
});

function endSplit(event, cancel) {
  if (!split || event.pointerId !== split.pointer) return;
  const s = split;
  split = null;
  if (cancel) ui.dock = s.layout;
  if (s.handle.hasPointerCapture(s.pointer)) s.handle.releasePointerCapture(s.pointer);
  document.body.classList.remove('resizing-groups');
  if (!cancel) saveDock();
  if (deferred.render || cancel) { deferred.render = false; render(false); }
}
window.addEventListener('pointerup', (event) => endSplit(event, false));
window.addEventListener('pointercancel', (event) => endSplit(event, true));

app.addEventListener('keydown', (event) => {
  const handle = event.target.closest('[data-dock-split]');
  if (!handle || !['ArrowUp', 'ArrowDown'].includes(event.key)) return;
  event.preventDefault();
  const { side, index, heights } = splitParts(handle);
  ui.dock = resizeGroups(ui.dock, side, index, (event.key === 'ArrowDown' ? 1 : -1) * (event.shiftKey ? 40 : 16), heights);
  saveDock();
  render(false);
});

app.addEventListener('dblclick', (event) => {
  const handle = event.target.closest('[data-dock-split]');
  if (!handle) return;
  const { side, index, heights } = splitParts(handle);
  const pair = heights[index] + heights[index + 1];
  ui.dock = resizeGroups(ui.dock, side, index, pair / 2 - heights[index], heights);
  saveDock();
  render(false);
});

// Crossing 900px switches between the docked layout and one side at a time.
matchMedia('(max-width: 900px)').addEventListener('change', () => {
  if (currentRoute.page === 'project') { render(false); placeTable(); }
});
