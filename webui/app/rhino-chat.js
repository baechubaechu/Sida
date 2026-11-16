// Asking Sida from the panel in Rhino: a Conductor talk of the document's project (the same
// talks the Sida screen shows), written and read through the talks API. What makes it about
// the model is on the server: while this Rhino is connected the Conductor is told how the
// document stands and what is selected (sida/experts/rhino/hooks.py). Nothing is sent from here
// but the question.

import { api, projectApi, sleep } from './api.js';
import { escapeHtml as escape, eventNotice, renderMarkdown } from './model.js';
import { chatRows } from './rhino-model.js';

const POLL_MS = 1000;
const EXAMPLES = ['지금 용적률이면 한도까지 얼마나 남았어?', '고른 매스를 두고 검토할 점을 알려 줘', '이 구성에서 다음에 정할 것은 뭐야?'];

export const chat = {
  project: '', talk: '',
  messages: [], pending: '', live: [],
  busy: false, error: '',
  unsent: '',  // a question whose answer failed and that Sida did not keep: the page puts it back in the field
  changed: () => {},  // the page redraws (and keeps its address) when the talk changes
};

// Another project, or none: the talk shown belongs to the one before.
export function chatFor(project, talk = '') {
  if (project === chat.project && (!talk || talk === chat.talk)) return;
  Object.assign(chat, { project, talk, messages: [], pending: '', live: [], error: '' });
  if (project && talk) loadTalk().then(chat.changed);
}

async function loadTalk() {
  const { project, talk } = chat;
  try {
    const got = await api(`${projectApi(project)}/talks/${encodeURIComponent(talk)}`);
    if (chat.project !== project || chat.talk !== talk) return;
    chat.messages = got.messages || [];
    if (got.job && got.job.talk === talk && !chat.busy) follow(project, got.job);  // a question still being answered (the page was reloaded)
  } catch (error) {
    if (chat.project !== project || chat.talk !== talk) return;
    if (error.status === 404) Object.assign(chat, { talk: '', messages: [] });  // the talk was deleted in Sida
    else chat.error = error.message;
  }
}

export function newTalk() {
  if (chat.busy) return;
  Object.assign(chat, { talk: '', messages: [], pending: '', live: [], error: '' });
  chat.changed();
}

export async function send(text) {
  const project = chat.project;
  if (!project || chat.busy || !text.trim()) return false;
  Object.assign(chat, { busy: true, error: '', pending: text.trim(), live: [] });
  chat.changed();
  try {
    if (!chat.talk) chat.talk = (await api(`${projectApi(project)}/talks`, { method: 'POST' })).talk.id;
    const { job } = await api(`${projectApi(project)}/talks/${encodeURIComponent(chat.talk)}/messages`, { method: 'POST', body: { text: text.trim(), context: [] } });
    follow(project, job);
    return true;
  } catch (error) {
    chat.error = error.status === 409 ? '이 프로젝트에서 다른 작업이 아직 실행 중입니다. 끝난 뒤 다시 보내 주세요.' : error.message;
    Object.assign(chat, { busy: false, pending: '' });
    chat.changed();
    return false;
  }
}

// Follow the job until it ends: the Conductor's replies as they come, the rest as notes.
async function follow(project, job) {
  chat.busy = true;
  let seen = 0;
  let view = job;
  let misses = 0;
  const take = (got) => {
    for (const event of got.events || []) {
      if (event.seq <= seen) continue;
      seen = event.seq;
      if (event.kind === 'conductor_reply' || event.kind === 'expert_reply') chat.live.push({ kind: 'conductor', text: event.data?.text || '' });
      else {
        const notice = eventNotice(event);
        if (notice?.text) chat.live.push({ kind: 'note', text: notice.text, tone: notice.tone });
      }
    }
  };
  take(job);
  chat.changed();
  while (view.status === 'running') {
    await sleep(POLL_MS);
    if (chat.project !== project) return;  // the document was moved to another project; the server keeps going
    try {
      view = await api(`${projectApi(project)}/session/jobs/${encodeURIComponent(job.id)}?after=${seen}`);
      misses = 0;
    } catch (error) {
      if (error.status === 404) break;  // Sida restarted and forgot the job
      misses += 1;
      if (misses >= 5) { chat.error = error.message; break; }
      continue;
    }
    take(view);
    chat.changed();
  }
  if (chat.project !== project) return;
  if (view.status === 'failed') chat.error = view.error || '답을 받지 못했습니다. 다시 보내 주세요.';
  const asked = chat.pending;
  await loadTalk();
  if (view.status === 'failed' && asked && !chat.messages.some((m) => m.role === 'user' && m.text === asked)) chat.unsent = asked;
  Object.assign(chat, { busy: false, pending: '', live: [] });
  chat.changed();
}

// The talk's rows, or what to do when there are none yet.
export function chatHtml(canAsk) {
  const rows = chatRows(chat.messages, chat.pending, chat.live);
  const body = rows.map((row) => {
    if (row.kind === 'user') return `<article class="rc-user" aria-label="내 질문">${escape(row.text)}</article>`;
    if (row.kind === 'note') return `<p class="rc-note ${escape(row.tone || '')}">${escape(row.text)}</p>`;
    return `<article class="rc-answer"><h3>Sida</h3><div class="markdown">${renderMarkdown(row.text)}</div></article>`;
  }).join('');
  const empty = rows.length ? '' : `<div class="rc-empty">
      <p>지금 열려 있는 모델을 두고 Sida에게 물어보세요. 모델의 수치(연면적, 건폐율, 용적률, 레이어의 의미)와 라이노에서 고른 개체가 질문과 함께 갑니다. 화면 캡처와 도형은 가지 않습니다.</p>
      ${canAsk ? `<ul>${EXAMPLES.map((text) => `<li><button type="button" data-example="${escape(text)}">${escape(text)}</button></li>`).join('')}</ul>` : ''}
      <p class="rc-where">여기서 나눈 대화는 Sida 화면의 "이전 대화"에도 남습니다.</p></div>`;
  return `${empty}${body}
    ${chat.busy ? '<p class="rc-working" role="status">Sida가 답하는 중입니다…</p>' : ''}
    ${chat.error ? `<p class="rc-note error" role="alert">${escape(chat.error)}</p>` : ''}`;
}
