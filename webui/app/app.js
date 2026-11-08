// The Sida screen. Draws from the JSON API and keeps no project data in the browser:
// projects, the Conductor conversation, expert chats and results all live on this PC's server.
// This file routes (the address bar), wires the page's events to the actions, and starts up;
// the state is in state.js, the HTML in view-*.js and render.js, the actions in the other files.

import { projectPath as projectUrl, keepNewDraft } from './model.js';
import { COMPARE_QUESTION } from './board-model.js';
import { talkMenu } from './talk-panel-model.js';
import { api, expertUrl, projectApi } from './api.js';
import { applyModelRecommendation, askAbout, closeTable, downloadBoard, hideVWorld, loadBoard, openTable, placeTable, table, takePicked, toggleVWorld, unpick } from './board.js';
import { commandKey, focusCommandLine, runCommandLine } from './commands.js';
import { decideProposal, newChat, runExpert, send, sendFeedback } from './experts.js';
import { addTypedIdea, ideaAction, placeIdeaFloat, saveIdea } from './ideas.js';
import { clearExpert, loadExpert, loadOrdinance, loadProjectSites, loadProjects, loadSession, loadSite, resetTracking, start, track } from './jobs.js';
import { syncPanelWidths } from './panels.js';
import { askDelete, createSample, openProjectInfo } from './projects.js';
import { render } from './render.js';
import { checkRelayKey, loadSettings, openSettings } from './settings.js';
import { checkUse, chooseRegion, findLot, prepareFind, removeUse, saveSite, searchAddress, searchUses, setOrdinanceOption, togglePick } from './site.js';
import { app, conductorScrolls, currentRoute, draftFor, drafts, freshFind, freshUseFind, jobRunning, openingTried, route, setCurrentRoute, talkViewById, toast, ui } from './state.js';
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
  if (currentRoute.page === 'home') {
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
      ui.talks = new Map();
      ui.talkViews = [];
      ui.talkMenu = '';
      ui.conductor = { ...ui.conductor, active: null, list: false };
      conductorScrolls.clear();
      for (const key of drafts.keys()) if (key.startsWith('talk:') || key === 'conductor-new') drafts.delete(key);
      ui.cmd = { lines: [], typed: [], back: -1, prompt: null, last: '', pick: 0, help: false };
      drafts.delete('command');
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

app.addEventListener('click', (event) => {
  if (!event.target.closest('.talk-more')) dismissTalkMenu();
  const button = event.target.closest('[data-action]');
  if (!button) return;
  const { action } = button.dataset;
  const { name, agent } = currentRoute;
  if (action === 'settings') openSettings(button.dataset.target);
  if (action === 'export-board') { button.closest('details')?.removeAttribute('open'); downloadBoard(name, button.dataset.format); }
  if (action === 'vworld-3d') toggleVWorld(name);
  if (action === 'sample') createSample();
  if (action === 'delete-project') askDelete(button.dataset.project);
  if (action === 'project-info') openProjectInfo(button.dataset.project);
  if (action === 'pane') { ui.pane = button.dataset.pane; if (ui.pane === 'conductor') ui.conductor = { ...ui.conductor, open: true }; render(false); }
  if (action === 'conductor-toggle') changeConductor('toggle');
  if (action === 'conductor-close') changeConductor('close');
  if (action === 'talks-toggle') changeConductor('list');
  if (action === 'talk-new') { changeConductor('new'); app.querySelector('[data-focus="conductor-new"]')?.focus({ preventScroll: true }); }
  if (action === 'collapse-experts') { ui.expertsCollapsed = true; if (ui.pane === 'side') ui.pane = 'board'; render(false); }
  if (action === 'toggle-experts-panel') { ui.expertsCollapsed = !ui.expertsCollapsed; render(false); }
  if (action === 'inspect-paper') table?.inspect(button.dataset.id);
  if (action === 'clear-selection') { ui.selected = []; table?.setSelected([]); render(false); }
  if (action === 'select-masses') table?.selectMasses();
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
  const moving = document.startViewTransition(swap);
  moving.ready.catch(() => {}); // a newer search skips this one; that is expected
  moving.finished.finally(() => {
    listMoves -= 1;
    if (!listMoves) root.classList.remove('list-moving');
  });
}
let listMoves = 0; // transitions still running; a newer one may start before an older one ends

app.addEventListener('input', (event) => {
  const { target } = event;
  if (target.id === 'project-search') {
    ui.query = target.value;
    swapProjectList();
  }
  if (target.form?.id === 'new-project-form') ui.newDraft = keepNewDraft(ui.newDraft, target.name, target.value);
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
    swapProjectList();
  }
  const { region, pick, lot } = event.target.dataset || {};
  if (region) chooseRegion(region, event.target.value);
  if (pick) togglePick(pick, event.target.checked);
  if (lot === 'mountain') ui.find.mountain = event.target.checked;
  if (event.target.id === 'idea-new-link') ui.ideaLinkNew = event.target.checked;
  const { ordDetailed } = event.target.dataset || {};
  if (ordDetailed) setOrdinanceOption(currentRoute.name, ordDetailed, { detailed: event.target.checked });
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

app.addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  if (form.id === 'new-project-form') {
    const name = form.elements.name.value.trim();
    const error = form.querySelector('#new-project-error');
    if (!name) { error.textContent = '프로젝트 이름을 입력해 주세요.'; form.elements.name.focus(); return; }
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
      location.hash = projectUrl(project.name);
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
});

app.addEventListener('keydown', (event) => {
  if (event.target.id === 'command-input') { commandKey(event); return; }
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

window.addEventListener('hashchange', navigate);
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
