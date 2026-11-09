// The widths of the left and right docked sides (or the page on the right): dragged, keyed,
// reset, kept as ratios with the layout on this PC (dock.js).

import { panelWidths, resizePanel } from './talk-panel-model.js';
import { DEFAULT_PANEL_RATIOS, dockOf, sideShown } from './dock-model.js';
import { saveDock } from './dock.js';
import { placeTable } from './board.js';
import { render } from './render.js';
import { app, currentRoute, deferred, ui } from './state.js';

let panelResize = null;
export function panelResizing() { return Boolean(panelResize); }

function workspaceWidth(studio) {
  const css = getComputedStyle(studio);
  return studio.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight);
}

// A side's narrowest width: the site or an expert's page 320px, a side with Conductor 280px,
// lists 240px.
function sideMinimum(side) {
  if (side === 'right' && (currentRoute.agent || currentRoute.site)) return 320;
  return dockOf(ui.dock, 'conductor')?.side === side ? 280 : 240;
}

function applyPanelWidths(studio, widths, total) {
  studio.style.setProperty('--left-width', `${widths.left}px`);
  studio.style.setProperty('--right-width', `${widths.right}px`);
  for (const handle of studio.querySelectorAll('[data-resize-side]')) {
    const side = handle.dataset.resizeSide;
    const minimum = sideMinimum(side);
    const maximum = widths[side] + widths.board - 320;
    handle.setAttribute('aria-valuenow', Math.round(widths[side] / total * 100));
    handle.setAttribute('aria-valuemin', Math.round(Math.min(minimum, maximum) / total * 100));
    handle.setAttribute('aria-valuemax', Math.round(maximum / total * 100));
    handle.setAttribute('aria-valuetext', `${Math.round(widths[side])}픽셀`);
  }
}

export function syncPanelWidths() {
  const studio = app.querySelector('.studio');
  if (!studio) return;
  if (matchMedia('(max-width: 900px)').matches) {
    studio.style.removeProperty('--left-width');
    studio.style.removeProperty('--right-width');
    return;
  }
  const total = workspaceWidth(studio);
  const detail = Boolean(currentRoute.agent || currentRoute.site);
  const widths = panelWidths(total, { left: ui.panelRatios.left, right: ui.panelRatios[detail ? 'detail' : 'right'] },
    { left: sideShown(ui.dock, 'left'), right: detail || sideShown(ui.dock, 'right'), detail, minimums: { left: sideMinimum('left'), right: sideMinimum('right') } });
  applyPanelWidths(studio, widths, total);
}

// Resize without redrawing the conversation or the WebGL table while the pointer is held.
function panelWidthKey(side) {
  return side === 'right' && (currentRoute.agent || currentRoute.site) ? 'detail' : side;
}

function currentPanelWidths(studio) {
  const css = getComputedStyle(studio);
  const total = workspaceWidth(studio);
  const left = parseFloat(css.getPropertyValue('--left-width')) || 0;
  const right = parseFloat(css.getPropertyValue('--right-width')) || 0;
  return { total, widths: { left, right, board: total - left - right } };
}

app.addEventListener('pointerdown', (event) => {
  const handle = event.target.closest('[data-resize-side]');
  if (!handle || event.button !== 0 || matchMedia('(max-width: 900px)').matches) return;
  event.preventDefault();
  const studio = handle.closest('.studio');
  const side = handle.dataset.resizeSide;
  panelResize = { ...currentPanelWidths(studio), side, studio, handle, pointer: event.pointerId, x: event.clientX,
    before: { ...ui.panelRatios }, minimum: sideMinimum(side) };
  handle.focus({ preventScroll: true });
  handle.setPointerCapture(event.pointerId);
  document.body.classList.add('resizing-panels');
});

window.addEventListener('pointermove', (event) => {
  const drag = panelResize;
  if (!drag || event.pointerId !== drag.pointer) return;
  const delta = (event.clientX - drag.x) * (drag.side === 'left' ? 1 : -1);
  const widths = resizePanel(drag.widths, drag.side, delta, drag.minimum);
  ui.panelRatios[panelWidthKey(drag.side)] = widths[drag.side] / drag.total;
  applyPanelWidths(drag.studio, widths, drag.total);
  placeTable();
});

function finishPanelResize(event, cancel = false) {
  if (!panelResize || event.pointerId !== panelResize.pointer) return;
  const drag = panelResize;
  panelResize = null;
  if (cancel) ui.panelRatios = drag.before;
  else saveDock();
  if (drag.handle.hasPointerCapture(drag.pointer)) drag.handle.releasePointerCapture(drag.pointer);
  document.body.classList.remove('resizing-panels');
  if (deferred.render) {
    deferred.render = false;
    render(false);
  } else {
    // Keep the same handle for a following click (including double-click to reset).
    syncPanelWidths();
    placeTable();
  }
}
window.addEventListener('pointerup', (event) => finishPanelResize(event));
window.addEventListener('pointercancel', (event) => finishPanelResize(event, true));
app.addEventListener('lostpointercapture', (event) => finishPanelResize(event, true));

app.addEventListener('keydown', (event) => {
  const handle = event.target.closest('[data-resize-side]');
  if (!handle || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  event.preventDefault();
  const studio = handle.closest('.studio');
  const { total, widths } = currentPanelWidths(studio);
  const side = handle.dataset.resizeSide;
  const delta = event.key === 'Home' ? -total : event.key === 'End' ? total
    : (event.key === 'ArrowRight' ? 1 : -1) * (side === 'left' ? 1 : -1) * (event.shiftKey ? 40 : 16);
  ui.panelRatios[panelWidthKey(side)] = resizePanel(widths, side, delta, sideMinimum(side))[side] / total;
  saveDock();
  render(false);
});

app.addEventListener('dblclick', (event) => {
  const handle = event.target.closest('[data-resize-side]');
  if (!handle) return;
  const key = panelWidthKey(handle.dataset.resizeSide);
  ui.panelRatios[key] = DEFAULT_PANEL_RATIOS[key];
  saveDock();
  render(false);
});
