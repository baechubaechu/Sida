// The Sida screen. Draws from the JSON API and keeps no project data in the browser:
// projects, the Conductor conversation, expert chats and results all live on this PC's server.
// This file routes (the address bar), wires the page's events to the actions, and starts up;
// the state is in state.js, the HTML in view-*.js and render.js, the actions in the other files.

import { projectPath as projectUrl, keepNewDraft, untitledName } from './model.js';
import { COMPARE_QUESTION } from './board-model.js';
import { talkMenu } from './talk-panel-model.js';
import { api, expertUrl, projectApi } from './api.js';
import { applyModelRecommendation, askAbout, closeTable, editProperty, downloadBoard, hideVWorld, loadBoard, openTable, placeTable, table, takePicked, toggleVWorld, unpick } from './board.js';
import { commandKey, focusCommandLine, runCommandLine } from './commands.js';
import { decideProposal, newChat, runExpert, send, sendFeedback } from './experts.js';
import { addTypedIdea, ideaAction, placeIdeaFloat, saveIdea } from './ideas.js';
import { clearExpert, loadExpert, loadOrdinance, loadProjectSites, loadProjects, loadSession, loadSite, resetTracking, start, track } from './jobs.js';
import { syncPanelWidths } from './panels.js';
import { dockAction, followSelection, loadDock } from './dock.js';
import { layerAction } from './layers.js';
import { askDelete, createSample, keepProjectList, openProjectInfo } from './projects.js';
import { render } from './render.js';
import { checkRelayKey, loadSettings, openSettings } from './settings.js';
import { checkUse, chooseRegion, findLot, prepareFind, removeUse, saveSite, searchAddress, searchUses, setOrdinanceOption, togglePick } from './site.js';
import { app, conductorScrolls, currentRoute, deferred, draftFor, newProjectDialog, drafts, freshFind, freshUseFind, jobRunning, openingTried, route, setCurrentRoute, talkViewById, toast, ui } from './state.js';
import { askDeleteTalk, askFromLine, changeConductor, dismissTalkMenu, loadTalk, openTalk, sendTalk } from './talks.js';
import { updateCommandLine } from './view-command.js';
import { projectList } from './view-home.js';

// ------------------------------------------------------------------ routing

async function navigate() {
  const previous = currentRoute;
  setCurrentRoute(route());
  if (currentRoute.agent || currentRoute.site) ui.pane = 'side';
  else if (previous.agent || previous.site) ui.pane = 'board';
  ui.revisionOpen = false;
  if (!currentRoute.site) ui.siteFirst = false; // left the site page without saving a site
  if (currentRoute.page !== 'project' || previous.name !== currentRoute.name || currentRoute.site) {
    if (ui.vworld) { ui.vworld = false; hideVWorld(); }
  }
  if (currentRoute.page !== 'project') closeTable();
  if (currentRoute.page === 'home' || currentRoute.page === 'new') { // the new-project form floats over the list
    render();
    await loadProjects();
    render();
    if (await loadProjectSites() && currentRoute.page === 'home') render(false);
    return;
  } else if (currentRoute.page === 'project') {
    const { name, agent } = currentRoute;
    if (previous.page !== 'project' || previous.name !== name) {
      ui.session = null;
      ui.site = null;
      ui.find = freshFind();
      ui.ordinance = null;
      ui.ordinanceError = '';
      ui.useFind = freshUseFind();
      ui.chat = null;
      ui.job = null;
      resetTracking();
      ui.live = [];
      ui.pending = null;
      ui.project = name;
      ui.board = null;
      ui.selected = [];
      ui.picked = [];
      followSelection(false);
      Object.assign(ui, { layerPick: '', layerRename: '', layerRenameText: '', currentLayer: '', aroundHidden: false, layerFolded: new Set() });
      ui.talks = new Map();
      ui.talkViews = [];
      ui.talkMenu = '';
      ui.conductor = { ...ui.conductor, active: null, list: false };
      conductorScrolls.clear();
      for (const key of drafts.keys()) if (key.startsWith('talk:') || key === 'conductor-new') drafts.delete(key);
      ui.cmd = { lines: [], typed: [], back: -1, prompt: null, last: '', pick: 0, help: false };
      drafts.delete('command');
      await loadDock(); // the panel layout kept on this PC, once (a local read)
      if (currentRoute.name !== name) return;
      render();
      if (!ui.projects) loadProjects().then(() => render(false));
      openTable(name);
      await Promise.all([loadSession(name), loadBoard(name), loadSite(name)]);
    }
    if (currentRoute.site && currentRoute.tab === 'find') prepareFind(name);
    if (currentRoute.site && currentRoute.tab === 'ordinance' && !ui.ordinance && ui.site?.available) loadOrdinance(name);
    if (agent && ui.session) {
      if (agent !== previous.agent) ui.showRaw = false;
      clearExpert();
      render();
      await loadExpert(name, agent);
    }
    if (currentRoute.name !== name) return;
    render();
    if (!ui.session) return;
    if (ui.session.job) {
      if (ui.session.job.talk) openTalk(name, ui.session.job.talk);
      track(name, ui.session.job);
    }
    else if (ui.session.talks?.some(t => t.id === '01') && !ui.session.messages.length && !openingTried.has(name)) {
      openingTried.add(name);
      openTalk(name, '01');
      start(name, `${projectApi(name)}/session/opening`, {});
    }
    return;
  }
  render();
}

// ------------------------------------------------------------------ the page's events

// A project's card and its work screen are one shape that grows and shrinks (a view transition
// pairing the card with the work screen's frame, named project-frame). Off where the browser
// lacks view transitions or motion is reduced.
const canMorph = () => Boolean(document.startViewTransition) && !matchMedia('(prefers-reduced-motion: reduce)').matches;

// Only the given card moves; the other cards fade with the rest of the list behind it.
function nameMorphCard(card) {
  for (const other of app.querySelectorAll('#project-list [style*="view-transition-name"]')) other.style.viewTransitionName = 'none';
  if (card) card.style.viewTransitionName = 'project-frame';
}

// `change` draws the next screen (navigate draws before its first wait). Redraws while the shape
// moves would cut the animation short, so they wait until it ends (data arriving meanwhile).
// Only the moving shape (project-frame) is named in either state; the other cards fade with the
// page. `toButton`: the shape ends as the list's "새 프로젝트" button; it stays the form until it
// has shrunk there and only then turns into the blue button.
function morphProject(direction, change, toButton = false) {
  const root = document.documentElement;
  root.classList.add('project-morph', direction);
  root.classList.toggle('to-button', toButton);
  const morph = transition(() => {
    change();
    for (const el of app.querySelectorAll('#project-list [style*="view-transition-name"]')) {
      if (el.style.viewTransitionName !== 'project-frame') el.style.viewTransitionName = 'none';
    }
    deferred.growing = true;
  });
  morph.finished.finally(() => {
    root.classList.remove('project-morph', direction, 'to-button');
    deferred.growing = false;
    if (deferred.render) { deferred.render = false; render(false); }
  });
}

// Opening a project from the list: the pressed card grows into the work screen (the 3D table
// appears once it is full size). A plain link with a modifier key (a new tab) or without motion.
function openProjectGrowing(event) {
  const link = event.target.closest('a[data-open-project]');
  if (!link || event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || !canMorph()) return false;
  // A project's card, or for a new project the dashed card or the heading's button (it grows into the form).
  const card = link.closest('.project-card, .continue, .project-new, .start-new') || (link.closest('.home-heading') ? link : null);
  if (!card) return false;
  event.preventDefault();
  if (link.getAttribute('href') === '#/new') newFormFrom = link.closest('.home-heading') ? 'button' : 'card';
  nameMorphCard(card);
  morphProject('opening', () => {
    history.pushState(null, '', link.getAttribute('href')); // no hashchange: navigate is called here
    navigate();
  });
  return true;
}

// The new-project dialog: typing keeps a draft (it survives closing), the backdrop and Esc go back
// to the list keeping it, "취소" goes back and forgets it.
newProjectDialog.addEventListener('input', (event) => {
  const { target } = event;
  if (target.form?.id === 'new-project-form') ui.newDraft = keepNewDraft(ui.newDraft, target.name, target.value);
});
newProjectDialog.addEventListener('click', (event) => {
  if (event.target === newProjectDialog) location.hash = '#/'; // the backdrop
  if (event.target.closest('[data-new="cancel"]')) { ui.newDraft = {}; location.hash = '#/'; }
});
newProjectDialog.addEventListener('cancel', (event) => { // Esc: close through the route, so it animates
  event.preventDefault();
  location.hash = '#/';
});

// What the new-project form grew from (the dashed card or the heading's button): it shrinks back there.
let newFormFrom = 'card';

// Back to the list (a link or the browser's back): the work screen shrinks into its project's
// card, the "이어서 하기" one when it is the latest.
// The new-project form shrinks back into the dashed card the same way, and grows into the work
// screen once the project is made.
function onHashChange() {
  const from = currentRoute.page;
  const to = route().page;
  if (!canMorph()) { navigate(); return; }
  if (from === 'new' && to === 'project') { nameMorphCard(null); morphProject('opening', navigate); return; }
  if (to !== 'home' || (from !== 'project' && from !== 'new')) { navigate(); return; }
  const leaving = currentRoute.name;
  nameMorphCard(null); // the list under the new-project form: nothing there moves on its own
  morphProject('closing', () => {
    navigate();
    const named = `[data-project="${CSS.escape(leaving || '')}"]`;
    const newHome = newFormFrom === 'button' ? '.home-heading .primary' : '.project-new, .start-new';
    nameMorphCard(from === 'new' ? app.querySelector(newHome) || app.querySelector('.home-heading .primary')
      : app.querySelector(`.continue${named}`) || app.querySelector(`.project-card${named}`));
  }, from === 'new' && newFormFrom === 'button');
}

app.addEventListener('click', (event) => {
  if (openProjectGrowing(event)) return;
  if (!event.target.closest('.talk-more')) dismissTalkMenu();
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const { action } = button.dataset;
  const { name, agent } = currentRoute;
  if (action === 'settings') openSettings(button.dataset.target, button);
  if (action === 'export-board') { button.closest('details')?.removeAttribute('open'); downloadBoard(name, button.dataset.format); }
  if (action === 'vworld-3d') toggleVWorld(name);
  if (action === 'sample') createSample();
  if (action === 'delete-project') askDelete(button.dataset.project);
  if (action === 'project-info') openProjectInfo(button.dataset.project);
  if (action === 'pane') { ui.pane = button.dataset.pane; render(false); }
  if (action === 'conductor-toggle') changeConductor('toggle');
  if (action === 'talks-toggle') changeConductor('list');
  if (action === 'talk-new') { changeConductor('new'); app.querySelector('[data-focus="conductor-new"]')?.focus({ preventScroll: true }); }
  if (action.startsWith('dock-')) dockAction(action, button);
  if (action === 'inspect-paper') table?.inspect(button.dataset.id);
  if (action.startsWith('layer-')) layerAction(action, button);
  if (action === 'clear-selection') { ui.selected = []; followSelection(false); table?.setSelected([]); render(false); }
  if (action === 'select-masses') table?.selectMasses();
  if (action === 'ungroup') table?.command('ungroup');
  if (action === 'paper-detail') table?.detailActionFor(button.dataset.id, button.dataset.detail);
  if (action === 'ask-selection') askAbout(button.dataset.compare === 'true' ? COMPARE_QUESTION : '');
  if (action === 'open-expert') location.hash = expertUrl(name, button.dataset.agent);
  if (action === 'model-apply') applyModelRecommendation();
  if (action === 'open-chat') location.hash = expertUrl(name, button.dataset.agent, button.dataset.chat);
  if (action === 'new-chat') newChat(button.dataset.agent);
  if (action === 'run-expert') runExpert(name, button.dataset.agent, button.dataset.withoutSite === 'true');
  if (action === 'unpick') unpick(button.dataset.id);
  if (action.startsWith('idea-')) ideaAction(name, action, button);
  const talkId = button.dataset.talk;
  if (action === 'talk-menu') { event.preventDefault(); ui.talkMenu = talkMenu(ui.talkMenu, 'toggle', talkId); render(false); }
  if (action === 'talk-open') {
    openTalk(name, talkId);
    loadTalk(name, talkId).then(() => render(false));
    app.querySelector(`[data-focus="talk:${CSS.escape(talkId)}"]`)?.focus({ preventScroll: true });
  }
  if (action === 'talk-delete') askDeleteTalk(name, talkId);
  if (action === 'talk-unpick') { const p = talkViewById(talkId); if (p) p.context = p.context.filter((id) => id !== button.dataset.id); render(false); }
  if (action === 'talk-add-picked') { const p = talkViewById(talkId); if (p) p.context = [...new Set([...p.context, ...ui.selected])]; render(false); }
  if (action === 'cmd-help') { ui.cmd.help = false; render(false); focusCommandLine(); }
  if (action === 'cmd-option' && ui.cmd.prompt) {
    drafts.set('command', String(Number(button.dataset.index) + 1));
    render(false);
    runCommandLine();
  }
  if (action === 'cmd-pick') {
    drafts.set('command', button.dataset.command);
    ui.cmd.pick = 0;
    render(false);
    runCommandLine();
  }
  if (action === 'open-revision') { ui.revisionOpen = true; render(false); app.querySelector('#revision-text')?.focus(); }
  if (action === 'close-revision') { ui.revisionOpen = false; render(false); }
  if (action === 'apply-proposal') decideProposal(button.dataset.id, true);
  if (action === 'skip-proposal') decideProposal(button.dataset.id, false);
  if (action === 'feedback') sendFeedback(button.dataset.rating);
  if (action === 'site-mode') { ui.find.mode = button.dataset.mode; ui.find.error = ''; render(false); }
  if (action === 'site-unpick') togglePick(button.dataset.pnu, false);
  if (action === 'site-save') saveSite(name);
  if (action === 'ord-dismiss') setOrdinanceOption(name, button.dataset.id, { dismissed: button.dataset.on === 'true' });
  if (action === 'use-check') checkUse(name, button.dataset.use);
  if (action === 'use-remove') removeUse(name, button.dataset.use);
});

// Redraw the project cards after a search or a new order. Cards that stay slide to their new place,
// new ones fade in and dropped ones fade out (a view transition of the named cards only, so the
// search field stays live while typing). Instant when the browser lacks it or motion is reduced.
function swapProjectList() {
  const list = document.querySelector('#project-list');
  if (!list) return;
  const swap = () => { list.innerHTML = projectList(); };
  if (!document.startViewTransition || matchMedia('(prefers-reduced-motion: reduce)').matches) { swap(); return; }
  const root = document.documentElement;
  listMoves += 1;
  root.classList.add('list-moving');
  const moving = transition(swap);
  moving.finished.finally(() => {
    listMoves -= 1;
    if (!listMoves) root.classList.remove('list-moving');
  });
}
let listMoves = 0; // transitions still running; a newer one may start before an older one ends

// A view transition that never holds the change back: the browser waits for a drawn frame before
// it calls `update`, and a window that is not being drawn (minimised, covered) gives none, so after
// a moment the animation is dropped and the change happens at once. Skipping is expected, so its
// rejection is not reported.
function transition(update) {
  let ran = false;
  const t = document.startViewTransition(() => { ran = true; return update(); });
  t.ready.catch(() => {});
  setTimeout(() => { if (!ran) t.skipTransition(); }, 300);
  return t;
}

app.addEventListener('input', (event) => {
  const { target } = event;
  if (target.dataset?.prop) drafts.set(`prop:${target.dataset.prop}`, target.value);
  if (target.id === 'project-search') {
    ui.query = target.value;
    swapProjectList();
  }
  if (target.matches('.composer textarea')) drafts.set(target.closest('form').dataset.composer, target.value);
  if (target.id === 'command-input') {
    drafts.set('command', target.value);
    ui.cmd.pick = 0;
    updateCommandLine();
  }
  if (target.dataset.ideaDraft) drafts.set(target.dataset.ideaDraft, target.value);
  if (target.id === 'revision-text') drafts.set(`revision:${currentRoute.agent}`, target.value);
  if (target.id === 'feedback-text') drafts.set(`feedback:${currentRoute.agent}`, target.value);
  if (target.id === 'site-query') ui.find.query = target.value;
  if (target.id === 'use-query') ui.useFind.query = target.value;
  if (target.dataset.lot === 'main' || target.dataset.lot === 'sub') ui.find[target.dataset.lot] = target.value;
});

app.addEventListener('change', (event) => {
  if (event.target.id === 'project-sort') {
    ui.sort = event.target.value;
    keepProjectList();
    swapProjectList();
  }
  const { region, pick, lot } = event.target.dataset || {};
  if (region) chooseRegion(region, event.target.value);
  if (pick) togglePick(pick, event.target.checked);
  if (lot === 'mountain') ui.find.mountain = event.target.checked;
  if (event.target.id === 'idea-new-link') ui.ideaLinkNew = event.target.checked;
  const { ordDetailed } = event.target.dataset || {};
  if (ordDetailed) setOrdinanceOption(currentRoute.name, ordDetailed, { detailed: event.target.checked });
  if (event.target.dataset?.prop) {
    drafts.delete(`prop:${event.target.dataset.prop}`);
    editProperty(event.target.dataset.prop, event.target.value);
  }
  // Checklist ticks stay on screen only for now (not saved to the project).
  const check = event.target.dataset?.check;
  if (check) {
    if (event.target.checked) ui.checks.add(check);
    else ui.checks.delete(check);
  }
});

// Keep which experts are unfolded in the panel, and the raw document, across redraws ('toggle' does not bubble).
app.addEventListener('toggle', (event) => {
  const row = event.target;
  if (row.matches?.('details.site-lines')) ui.showSiteLines = row.open;
  else if (row.matches?.('details.raw-doc')) ui.showRaw = row.open;
  if (!row.matches?.('details.expert-row')) return;
  if (row.open) ui.openExperts.add(row.dataset.agent);
  else ui.openExperts.delete(row.dataset.agent);
}, true);

async function onSubmit(event) {
  event.preventDefault();
  const form = event.target;
  if (form.id === 'new-project-form') {
    const name = form.elements.name.value.trim() || untitledName(ui.projects); // 비워 두면 무제1, 무제2, …
    const error = form.querySelector('#new-project-error');
    const fields = {};
    for (const key of ['type', 'site', 'intention']) {
      const value = form.elements[key].value.trim();
      if (value) fields[key] = value;
    }
    ui.creating = true;
    form.querySelector('button[type="submit"]').disabled = true;
    try {
      const { project, created } = await api('/api/projects', { method: 'POST', body: { name, fields } });
      ui.newDraft = {};
      if (!created) toast(`같은 이름의 프로젝트 "${project.name}"를 열었습니다.`, 'info');
      await loadProjects();
      // The work screen takes the new-project window's place in the history, so "back" from it
      // returns to the list, not to the window. (replaceState fires no hashchange: go there here.)
      history.replaceState(null, '', projectUrl(project.name));
      onHashChange();
    } catch (err) {
      error.textContent = err.message;
      form.querySelector('button[type="submit"]').disabled = false;
    } finally {
      ui.creating = false;
    }
  } else if (form.id === 'lot-form') {
    findLot();
  } else if (form.id === 'address-form') {
    searchAddress(currentRoute.name);
  } else if (form.id === 'use-form') {
    searchUses();
  } else if (form.id === 'command-form') {
    runCommandLine();
  } else if (form.id === 'idea-new-form') {
    addTypedIdea(currentRoute.name);
  } else if (form.dataset.ideaForm) {
    saveIdea(currentRoute.name, form.dataset.ideaForm);
  } else if (form.dataset.composer === 'conductor-new') {
    const key = 'conductor-new';
    const text = draftFor(key).trim();
    if (!text || ui.creatingTalk || jobRunning()) return;
    if (await askFromLine(currentRoute.name, text)) drafts.delete(key);
    render(false);
  } else if (form.matches('.talk-composer')) {
    sendTalk(form.dataset.composer.slice('talk:'.length));
  } else if (form.matches('.composer')) {
    send(form.dataset.composer);
  } else if (form.id === 'revision-form') {
    const { name, agent } = currentRoute;
    const key = `revision:${agent}`;
    const revision = draftFor(key).trim();
    if (!revision || jobRunning()) return;
    drafts.delete(key);
    ui.revisionOpen = false;
    start(name, `${projectApi(name)}/session/experts/${encodeURIComponent(agent)}/run`, { revision, context: takePicked().ids });
  }
}
app.addEventListener('submit', onSubmit);
newProjectDialog.addEventListener('submit', onSubmit);

app.addEventListener('keydown', (event) => {
  if (event.target.id === 'command-input') { commandKey(event); return; }
  // The 속성 panel's fields: Enter saves (through 'change'), Esc puts the saved value back.
  if (event.target.dataset?.prop) {
    if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); event.target.blur(); }
    if (event.key === 'Escape') {
      event.preventDefault();
      drafts.delete(`prop:${event.target.dataset.prop}`);
      event.target.value = event.target.dataset.saved;
      ui.propError = null;
      event.target.blur();
    }
    return;
  }
  if (event.target.dataset?.ideaDraft) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
      event.preventDefault();
      event.target.closest('form').requestSubmit();
    } else if (event.key === 'Escape' && ui.ideaEdit) {
      event.preventDefault();
      drafts.delete(`idea-edit:${ui.ideaEdit}`);
      ui.ideaEdit = '';
      render(false);
    }
    return;
  }
  if (event.target.matches('.composer textarea') && event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    event.target.closest('form').requestSubmit();
  }
});

// Space anywhere outside a text field puts the cursor on the command line. There are no
// one-letter shortcuts (2026-11-02 지훈): a letter or number typed outside a text field goes
// to the command line as the start of a command word, as in CAD.
window.addEventListener('keydown', (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey || currentRoute.page !== 'project') return;
  const el = event.target;
  if (el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.isContentEditable || el.closest?.('dialog'))) return;
  if (event.key === ' ') {
    if (el?.tagName !== 'BUTTON' && focusCommandLine()) event.preventDefault();
    return;
  }
  // The key itself then lands on the command line (focus moves before it is typed).
  if ((event.key.length === 1 && /\S/.test(event.key)) || event.key === 'Process') focusCommandLine();
});

// ------------------------------------------------------------------ start

window.addEventListener('hashchange', onHashChange);
window.addEventListener('resize', () => { syncPanelWidths(); placeTable(); placeIdeaFloat(); });
matchMedia('(max-width: 900px)').addEventListener('change', () => {
  if (currentRoute.page === 'project') render(false);
});
document.querySelector('.skip-link').addEventListener('click', (event) => {
  event.preventDefault();
  document.querySelector('#main')?.focus();
});

navigate();
loadSettings().then(() => {
  if (ui.settings?.first_run) openSettings();
  else render(false);
  checkRelayKey({ quiet: true }); // a Sida key approved since the last visit arrives now
});
