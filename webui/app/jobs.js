// Loading a project's session, site and expert results, and following a job (a Conductor turn or
// an expert run) on the server until it ends.

import { eventNotice, siteCard, sitePageFor } from './model.js';
import { addHistory } from './command-model.js';
import { initialTalk } from './talk-panel-model.js';
import { ApiError, api, projectApi, sleep } from './api.js';
import { loadBoard, table } from './board.js';
import { render } from './render.js';
import { askForSite } from './site.js';
import { POLL_MS, activeChat, announce, currentRoute, expertById, toast, ui } from './state.js';
import { loadTalk } from './talks.js';

let trackToken = 0; // only the newest polling loop keeps going
let trackingId = null;
export function resetTracking() { trackToken += 1; trackingId = null; }

export async function loadProjects() {
  try {
    ui.projects = (await api('/api/projects')).projects;
    ui.projectsError = '';
  } catch (error) {
    ui.projectsError = error.message;
  }
}

// The saved site of each listed project (address, zone, outline) for the project cards. Asked once
// per project change; a project without a site, or a failed request, simply shows no site.
const SITE_CARDS_MAX = 40;
export async function loadProjectSites() {
  const wanted = (ui.projects || []).slice(0, SITE_CARDS_MAX).filter((p) => ui.projectSites.get(p.name)?.stamp !== p.updated_at);
  if (!wanted.length) return false;
  await Promise.all(wanted.map(async (p) => {
    let card = null;
    try { card = siteCard(await api(`${projectApi(p.name)}/site`)); } catch { /* no site shown */ }
    ui.projectSites.set(p.name, { stamp: p.updated_at, card });
  }));
  return true;
}

export async function loadSession(name) {
  try {
    const session = await api(`${projectApi(name)}/session`);
    if (ui.project !== name) return;
    ui.session = session;
    ui.sessionError = '';
    if (ui.conductor.active === null) {
      const id = initialTalk(session.talks || [], null);
      ui.conductor = { ...ui.conductor, active: id };
      if (id) {
        ui.talkViews.push({ id, context: [] });
        await loadTalk(name, id);
      }
    }
  } catch (error) {
    ui.session = null;
    ui.sessionError = error.status === 404 ? '프로젝트를 찾을 수 없습니다.' : error.message;
  }
}

// What the site's ordinance says about 건폐율·용적률 (GET .../site/ordinance), loaded with the tab.
export async function loadOrdinance(name) {
  ui.ordinanceError = '';
  try {
    const ordinance = await api(`${projectApi(name)}/site/ordinance`);
    if (ui.project === name) ui.ordinance = ordinance;
  } catch (error) {
    if (ui.project === name) ui.ordinanceError = error.message;
  }
  render(false);
}

export async function loadSite(name) {
  try {
    ui.site = await api(`${projectApi(name)}/site`);
    ui.siteError = '';
  } catch (error) {
    ui.site = null;
    ui.siteError = error.message;
  }
}

export function clearExpert() {
  ui.chat = null;
  ui.chatMissing = false;
  ui.module = null;
  ui.moduleMissing = false;
  ui.versions = null;
  ui.version = null;
  ui.versionMissing = false;
}

// What the expert page's open tab needs: the result, the list of earlier results, and the
// open analysis chat or earlier result.
export async function loadExpert(name, agent) {
  clearExpert();
  const expert = expertById(agent);
  const { tab, version } = currentRoute;
  const base = `${projectApi(name)}/modules/${encodeURIComponent(agent)}`;
  const skip = Promise.resolve(null);
  const [chat, module, versions, old] = await Promise.allSettled([
    tab === 'chat' && expert?.chat
      ? api(`${projectApi(name)}/experts/${encodeURIComponent(agent)}/chats/${encodeURIComponent(activeChat())}`) : skip,
    expert?.done ? api(base) : Promise.reject(new ApiError(404, '')),
    api(`${base}/versions`),
    tab === 'versions' && version ? api(`${base}/versions/${encodeURIComponent(version)}`) : skip,
  ]);
  if (chat.status === 'fulfilled') ui.chat = chat.value;
  else ui.chatMissing = chat.reason?.status === 404;
  if (module.status === 'fulfilled') ui.module = module.value;
  else ui.moduleMissing = module.reason?.status === 404;
  ui.versions = versions.status === 'fulfilled' ? versions.value.versions : [];
  if (old.status === 'fulfilled') ui.version = old.value;
  else ui.versionMissing = old.reason?.status === 404;
}

export async function refreshProject() {
  const { name, agent } = currentRoute;
  if (currentRoute.page !== 'project') return;
  await Promise.all([loadSession(name), loadBoard(name), ...ui.talkViews.map((p) => loadTalk(name, p.id))]);
  if (agent && ui.session) await loadExpert(name, agent);
}

// ------------------------------------------------------------------ jobs

export async function start(name, path, body, pending = null) {
  try {
    const { job } = await api(path, { method: 'POST', body });
    ui.pending = pending;
    track(name, job);
    return true;
  } catch (error) {
    if (error.status === 409) {
      toast('이전 작업이 아직 실행 중입니다. 끝나면 다시 보내 주세요.', 'warn');
      await refreshProject();
      if (ui.session?.job) track(name, ui.session.job);
    } else {
      toast(error.message, 'error');
    }
    render(false);
    return false;
  }
}

function handleEvent(event) {
  if (event.kind === 'tray_added' && ui.project) {
    loadBoard(ui.project).then(() => table?.openTray());
  }
  const sitePageHash = ui.project ? sitePageFor(event, ui.project, ui.site) : null;
  if (sitePageHash && location.hash !== sitePageHash) location.hash = sitePageHash;
  if (event.kind === 'run_skipped' && event.data?.reason === 'no_site' && ui.project) askForSite(ui.project, event.data.address);
  if (event.kind === 'conductor_reply') ui.live.push({ kind: 'conductor', text: event.data.text || '' });
  else if (event.kind === 'expert_reply') ui.live.push({ kind: 'expert', text: event.data.text || '' });
  else {
    const notice = eventNotice(event);
    if (!notice) return;
    // A talk shows its own progress; an expert run started from the command line reports
    // on the command line.
    if (ui.job?.kind === 'expert') ui.cmd.lines = addHistory(ui.cmd.lines, notice.text, notice.tone);
    else ui.live.push({ kind: 'note', text: notice.text, tone: notice.tone });
    if (notice.toast) toast(notice.text, notice.tone);
    announce(notice.text);
  }
}

export async function track(name, job) {
  if (trackingId === job.id) return; // already following it
  const token = ++trackToken;
  trackingId = job.id;
  ui.job = job;
  ui.live = [];
  let seen = 0;
  const take = (view) => {
    for (const event of view.events || []) {
      if (event.seq <= seen) continue;
      seen = event.seq;
      handleEvent(event);
    }
  };
  take(job);
  render(false);
  let view = job;
  let misses = 0;
  while (view.status === 'running') {
    await sleep(POLL_MS);
    if (token !== trackToken || ui.project !== name) return; // left the project; the server keeps going
    try {
      view = await api(`${projectApi(name)}/session/jobs/${encodeURIComponent(job.id)}?after=${seen}`);
      misses = 0;
    } catch (error) {
      if (error.status === 404) break; // the server restarted and forgot the job
      misses += 1;
      if (misses >= 5) { toast(error.message, 'error'); break; }
      continue;
    }
    take(view);
    ui.job = { ...view, events: [] };
    render(false);
  }
  if (token !== trackToken) return;
  trackingId = null;
  if (view.status === 'failed') toast(view.error || '작업이 실패했습니다.', 'error');
  ui.job = null;
  await refreshProject();
  ui.live = [];
  ui.pending = null;
  render(false);
  loadProjects();
}
