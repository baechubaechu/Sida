// Expert actions: run, revise, analysis chats, feedback, the project-state proposal.

import { sitePath, needsSiteFirst, deckFileUrl, downloadName, DECK_FORMATS } from './model.js';
import { api, expertUrl, projectApi } from './api.js';
import { saveBlob, takePicked } from './board.js';
import { loadExpert, loadSession, refreshProject, start } from './jobs.js';
import { render } from './render.js';
import { activeChat, currentRoute, draftFor, drafts, jobRunning, toast, ui } from './state.js';

// The deck as a file (the presentation editor's 발표자료 tab): made by the server when asked, then
// saved under the name the server gives it.
export async function downloadDeck(format) {
  const { name } = currentRoute;
  const word = DECK_FORMATS.find((f) => f.format === format)?.word || '파일';
  if (ui.deckMaking) return;
  ui.deckMaking = format;
  render(false);
  try {
    const response = await fetch(deckFileUrl(name, format));
    if (!response.ok) {
      let detail = '';
      try { detail = (await response.json()).detail; } catch { /* not JSON */ }
      throw new Error(typeof detail === 'string' && detail ? detail : `요청이 실패했습니다 (${response.status})`);
    }
    const filename = downloadName(response.headers.get('Content-Disposition'), `발표자료.${format}`);
    saveBlob(await response.blob(), filename);
    toast(`${filename}을(를) 내려받았습니다.`, 'success');
  } catch (error) {
    const text = error instanceof TypeError ? 'Sida 서버에 연결할 수 없습니다.' : error.message;
    toast(`${word}을 만들지 못했습니다: ${text}`, 'error');
  }
  ui.deckMaking = '';
  render(false);
}

export async function decideProposal(id, apply) {
  const { name } = currentRoute;
  try {
    const path = apply
      ? `${projectApi(name)}/state-proposals/${encodeURIComponent(id)}/apply`
      : `${projectApi(name)}/state-proposals/${encodeURIComponent(id)}/skip`;
    await api(path, { method: 'POST' });
    toast(apply ? '설계 상태에 반영했습니다.' : '이번 반영안은 건너뛰었습니다.', apply ? 'success' : 'info');
  } catch (error) {
    toast(error.message, 'error');
  }
  await refreshProject();
  render(false);
}

export function send(key) {
  const { name, agent } = currentRoute;
  const text = draftFor(key).trim();
  if (!text || jobRunning()) return;
  drafts.delete(key);
  const { ids, context } = takePicked();
  const chat = activeChat();
  start(name, `${projectApi(name)}/experts/${encodeURIComponent(agent)}/chats/${encodeURIComponent(chat)}/messages`, { text, context: ids }, { target: `${agent}/${chat}`, text, context });
}

export async function sendFeedback(rating) {
  const { name, agent } = currentRoute;
  const key = `feedback:${agent}`;
  try {
    const { recorded } = await api(`${projectApi(name)}/experts/${encodeURIComponent(agent)}/feedback`, {
      method: 'POST', body: { rating, comment: draftFor(key).trim() },
    });
    drafts.delete(key);
    ui.feedback[agent] = { rating, recorded };
  } catch (error) {
    toast(error.message, 'error');
  }
  render(false);
}

export async function newChat(agent) {
  const { name } = currentRoute;
  try {
    const { chat } = await api(`${projectApi(name)}/experts/${encodeURIComponent(agent)}/chats`, { method: 'POST' });
    await loadSession(name);
    ui.openExperts.add(agent);
    const target = expertUrl(name, agent, chat.id);
    if (location.hash !== target) { location.hash = target; return; }
    await loadExpert(name, agent);
    render(false);
  } catch (error) {
    toast(error.message, 'error');
  }
}

// Running the site reader with no site saved opens the site page to find it first; saving the site
// then runs it (or the designer runs it on the brief alone).
export function runExpert(name, agent, withoutSite = false) {
  if (!withoutSite && needsSiteFirst(agent, ui.site)) {
    ui.siteFirst = true;
    location.hash = sitePath(name, 'find');
    return;
  }
  ui.siteFirst = false;
  start(name, `${projectApi(name)}/session/experts/${encodeURIComponent(agent)}/run`, { context: takePicked().ids });
}
