// Conductor conversations: opening, sending, starting one from the command line, deleting.

import { pickedNames } from './board-model.js';
import { talkPanel, talkMenu } from './talk-panel-model.js';
import { dockOf, panelVisible, reveal, setSideOpen } from './dock-model.js';
import { saveDock } from './dock.js';
import { api, projectApi } from './api.js';
import { loadSession, start } from './jobs.js';
import { render } from './render.js';
import { app, conductorScrolls, currentRoute, deleteTalkConfirm, deleteTalkDialog, draftFor, drafts, jobRunning, talkViewById, toast, ui } from './state.js';
import { talkSummary, talkTitle } from './view-conductor.js';

export function dismissTalkMenu(restoreFocus = false) {
  const opened = app.querySelector('.talk-more[open]');
  ui.talkMenu = talkMenu(ui.talkMenu, 'dismiss');
  for (const menu of app.querySelectorAll('.talk-more[open]')) menu.open = false;
  if (restoreFocus) opened?.querySelector('summary').focus({ preventScroll: true });
}

document.addEventListener('pointerdown', event => {
  if (ui.talkMenu && !event.target.closest('.talk-more')) dismissTalkMenu();
}, true);
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && ui.talkMenu) {
    event.preventDefault();
    event.stopImmediatePropagation();
    dismissTalkMenu(true);
  }
}, true);

export function askDeleteTalk(name, id) {
  dismissTalkMenu();
  if (jobRunning()) { toast('실행 중인 작업이 끝난 뒤 대화를 삭제해 주세요.', 'warn'); return; }
  deleteTalkDialog.dataset.project = name;
  deleteTalkDialog.dataset.talk = id;
  deleteTalkDialog.querySelector('#delete-talk-text').textContent = `‘${talkTitle(talkSummary(id))}’ 대화와 메시지를 삭제할까요? 되돌릴 수 없습니다. 브리프·대지·제도판·전문가 결과는 유지됩니다.`;
  deleteTalkDialog.querySelector('[role="alert"]').textContent = '';
  deleteTalkConfirm.disabled = false;
  deleteTalkDialog.showModal();
}

document.querySelector('#delete-talk-cancel').addEventListener('click', () => deleteTalkDialog.close());
deleteTalkConfirm.addEventListener('click', async () => {
  const { project: name, talk: id } = deleteTalkDialog.dataset;
  deleteTalkConfirm.disabled = true;
  try {
    await api(`${projectApi(name)}/talks/${encodeURIComponent(id)}`, { method: 'DELETE' });
    if (ui.project === name) {
      ui.talks.delete(id);
      ui.talkViews = ui.talkViews.filter(view => view.id !== id);
      drafts.delete(`talk:${id}`);
      conductorScrolls.delete(`talk:${id}`);
      ui.conductor = talkPanel(ui.conductor, 'remove', id);
      if (ui.session) ui.session.talks = ui.session.talks.filter(talk => talk.id !== id);
      await loadSession(name);
    }
    deleteTalkDialog.close();
    render(false);
    toast('대화를 삭제했습니다.', 'success');
  } catch (error) {
    deleteTalkDialog.querySelector('[role="alert"]').textContent = error.message;
    deleteTalkConfirm.disabled = false;
  }
});

// ------------------------------------------------------------------ Conductor conversations

export async function loadTalk(name, id) {
  try {
    const talk = await api(`${projectApi(name)}/talks/${encodeURIComponent(id)}`);
    if (ui.project === name) ui.talks.set(id, { messages: talk.messages });
  } catch (error) {
    if (ui.project === name) ui.talks.set(id, { messages: ui.talks.get(id)?.messages || [], error: error.message });
  }
}

// Selecting a conversation preserves each conversation's draft and paper context.
export function openTalk(name, id, context = []) {
  dismissTalkMenu();
  const known = ui.talkViews.find((p) => p.id === id);
  ui.talkViews = [...ui.talkViews.filter((p) => p.id !== id), { id, context: known?.context || context }];
  ui.conductor = talkPanel(ui.conductor, 'select', id);
  ui.dock = reveal(ui.dock, 'conductor');
  ui.pane = 'conductor';
  if (!ui.talks.has(id)) loadTalk(name, id).then(() => render(false));
  render(false);
}


// 대화 is a docked panel: showing it opens its side and turns its group to it; hiding it folds its
// side (with whatever else is docked there). A narrow screen switches to it with the bottom tabs.
export function changeConductor(action) {
  dismissTalkMenu();
  const narrow = matchMedia('(max-width: 900px)').matches;
  const shown = narrow ? ui.pane === 'conductor' : panelVisible(ui.dock, 'conductor');
  const hide = action === 'close' || (action === 'toggle' && shown);
  ui.conductor = talkPanel(ui.conductor, action === 'toggle' || action === 'close' ? 'show' : action);
  if (hide) {
    if (!narrow) ui.dock = setSideOpen(ui.dock, dockOf(ui.dock, 'conductor').side, false);
    if (ui.pane === 'conductor') ui.pane = 'board';
  } else {
    ui.dock = reveal(ui.dock, 'conductor');
    ui.pane = 'conductor';
  }
  saveDock();
  ui.cmd.help = false;
  render(false);
  if (hide) app.querySelector('[data-action="conductor-toggle"]')?.focus({ preventScroll: true });
}

export function sendTalk(id) {
  const name = currentRoute.name;
  const key = `talk:${id}`;
  const text = draftFor(key).trim();
  const view = talkViewById(id);
  if (!text || !view) return;
  if (jobRunning()) { toast('이전 작업이 아직 실행 중입니다. 끝나면 다시 보내 주세요.', 'warn'); return; }
  drafts.delete(key);
  start(name, `${projectApi(name)}/talks/${encodeURIComponent(id)}/messages`, { text, context: view.context },
    { target: key, text, context: pickedNames(view.context, ui.board) });
}

// A question typed on the command line starts a new talk with the papers picked on the table.
export async function askFromLine(name, text) {
  if (jobRunning() || ui.creatingTalk) { toast('이전 작업이 아직 실행 중입니다. 끝나면 다시 보내 주세요.', 'warn'); return false; }
  ui.creatingTalk = true;
  const context = [...ui.selected];
  try {
    const { talk } = await api(`${projectApi(name)}/talks`, { method: 'POST' });
    ui.talks.set(talk.id, { messages: [] });
    if (ui.session) ui.session.talks = [...(ui.session.talks || []), { ...talk, title: text.split(/\s+/).join(' ').slice(0, 60) }];
    openTalk(name, talk.id, context);
    await start(name, `${projectApi(name)}/talks/${encodeURIComponent(talk.id)}/messages`, { text, context },
      { target: `talk:${talk.id}`, text, context: pickedNames(context, ui.board) });
    return true;
  } catch (error) {
    toast(error.message, 'error');
    return false;
  } finally {
    ui.creatingTalk = false;
  }
}
