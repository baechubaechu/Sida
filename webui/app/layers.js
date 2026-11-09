// The 레이어 panel's buttons (view-dock.js layersBody): new layer, sublayer, delete, up, down;
// picking and renaming a layer; its current mark, visibility, lock and colour. The layers are saved
// with the board (PUT .../board/layers) and the board is read back, since taking a layer away moves
// what was on it. The surroundings' row is for the screen only. The current layer is kept for this
// visit: new papers go onto it (board.js add hook).

import { api, projectApi } from './api.js';
import { addLayer, boardLayers, changeLayer, layerRows, moveLayer, removeLayer } from './board-model.js';
import { boardCall, loadBoard, table } from './board.js';
import { render } from './render.js';
import { app, currentRoute, ui } from './state.js';

// Saves go one after another (a quick run of clicks must not land out of order); the board is read
// back after the last, since taking a layer away moves what was on it.
let saving = Promise.resolve();
function saveLayers(layers) {
  const name = currentRoute.name;
  if (ui.board) ui.board = { ...ui.board, layers };
  table?.setLayers(layers);
  render(false);
  ui.layersSaving += 1;
  saving = saving.then(() => boardCall(name, () => api(`${projectApi(name)}/board/layers`, { method: 'PUT', body: { layers } })))
    .finally(() => {
      ui.layersSaving -= 1;
      if (!ui.layersSaving) loadBoard(name).then(() => render(false));
    });
}

const newId = () => `layer-${Math.random().toString(16).slice(2, 10).padEnd(8, '0')}`;

export function layerAction(action, button) {
  const layers = boardLayers(ui.board);
  const id = button.dataset.layer || ui.layerPick;
  if (action === 'layer-pick') { ui.layerPick = id; render(false); return true; }
  if (action === 'layer-fold') {
    if (ui.layerFolded.has(id)) ui.layerFolded.delete(id); else ui.layerFolded.add(id);
    render(false);
    return true;
  }
  if (action === 'layer-add' || action === 'layer-add-sub') {
    const made = newId();
    ui.layerPick = made;
    ui.layerRename = made;
    ui.layerRenameText = '';
    saveLayers(addLayer(layers, { id: made, parent: action === 'layer-add-sub' ? id : '' }));
    focusRename();
    return true;
  }
  if (action === 'layer-eye' && id.startsWith('around:')) {
    const part = id.slice('around:'.length);
    const hidden = new Set(table?.aroundPartsHidden || []);
    if (hidden.has(part)) hidden.delete(part); else hidden.add(part);
    table?.setAroundParts(hidden);
    render(false);
    return true;
  }
  if (action === 'layer-eye' && id === 'around') {
    ui.aroundHidden = !ui.aroundHidden;
    table?.setLayers(layers, { aroundHidden: ui.aroundHidden });
    render(false);
    return true;
  }
  const layer = layers.find((l) => l.id === id);
  if (!layer) return false;
  if (action === 'layer-remove') {
    if (ui.currentLayer === id) ui.currentLayer = '';
    ui.layerPick = '';
    saveLayers(removeLayer(layers, id));
  } else if (action === 'layer-up' || action === 'layer-down') {
    saveLayers(moveLayer(layers, id, action === 'layer-up' ? 'up' : 'down'));
  } else if (action === 'layer-eye') {
    saveLayers(changeLayer(layers, id, { visible: !layer.visible }));
  } else if (action === 'layer-lock') {
    saveLayers(changeLayer(layers, id, { locked: !layer.locked }));
  } else if (action === 'layer-current') {
    ui.currentLayer = ui.currentLayer === id ? '' : id;
    render(false);
  } else {
    return false;
  }
  return true;
}

// Renaming: double-click a name; Enter or leaving the field keeps it, Esc does not. What is typed
// is kept in ui.layerRenameText, so a redraw meanwhile does not lose it.
function focusRename() {
  const input = app.querySelector('[data-layer-rename]');
  input?.focus();
  input?.select();
}

function finishRename(id, text, keep) {
  if (ui.layerRename !== id) return;
  ui.layerRename = '';
  ui.layerRenameText = '';
  const name = text.trim();
  const layers = boardLayers(ui.board);
  if (keep && name && layers.find((l) => l.id === id)?.name !== name) saveLayers(changeLayer(layers, id, { name }));
  else render(false);
}

app.addEventListener('dblclick', (event) => {
  const label = event.target.closest('.layer-label');
  if (!label || label.dataset.layer === 'around') return;
  ui.layerPick = label.dataset.layer;
  ui.layerRename = label.dataset.layer;
  ui.layerRenameText = '';
  render(false);
  focusRename();
});

app.addEventListener('input', (event) => {
  if (event.target.dataset?.layerRename) ui.layerRenameText = event.target.value;
});

app.addEventListener('keydown', (event) => {
  const input = event.target.closest?.('[data-layer-rename]');
  if (!input) return;
  if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); finishRename(input.dataset.layerRename, input.value, true); }
  if (event.key === 'Escape') { event.preventDefault(); finishRename(input.dataset.layerRename, '', false); }
});

// Leaving the field keeps the name. A redraw also takes the field away (and puts a new one in its
// place, focused), so this waits a moment and keeps the name only if renaming has really ended.
app.addEventListener('focusout', (event) => {
  const input = event.target.closest?.('[data-layer-rename]');
  if (!input) return;
  const id = input.dataset.layerRename;
  const text = input.value;
  setTimeout(() => {
    if (document.activeElement?.dataset?.layerRename === id) return;
    finishRename(id, ui.layerRenameText || text, true);
  }, 0);
});

app.addEventListener('change', (event) => {
  const id = event.target.dataset?.layerColor;
  if (!id) return;
  saveLayers(changeLayer(boardLayers(ui.board), id, { color: event.target.value.toLowerCase() }));
});

// The layers of the board as `layer` command options: "이름" (with its parents for a sublayer).
export function layerOptions() {
  const rows = layerRows(ui.board);
  const names = new Map(rows.map((r) => [r.id, r.name]));
  const parents = new Map(boardLayers(ui.board).map((l) => [l.id, l.parent]));
  const path = (id) => { const out = []; for (let at = id, n = 0; at && n < rows.length; at = parents.get(at), n += 1) out.unshift(names.get(at)); return out.join(' / '); };
  return rows.map((r) => ({ key: r.id, label: path(r.id) }));
}
