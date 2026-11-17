// The share window (공유): what goes up, the two links, taking comments, usage, turning the share
// off, and the comments that came back with an answer, resolve, delete and "Conductor에게 묻기".
// A side panel like the settings (its own <dialog>, drawn here, so redraws of the page leave it
// be). The comments also stand on the table as pins (table-comments.js); a pin opens this window
// at its comment. The work is on the server: GET/POST/PATCH/DELETE /api/projects/{name}/share...

import { api, projectApi } from './api.js';
import { escapeHtml as escape } from './model.js';
import {
  paperCounts, leftOutLine, sizeLabel, keptUntil, usageView, shareStatus, uploadLabel, commentThreads, unreadComments,
  targetLabel, targetPaper, conductorQuestion, commentTime, MAX_TEXT,
} from './share-model.js';
import { askAbout, table } from './board.js';
import { render } from './render.js';
import { openSettings } from './settings.js';
import { toast, ui } from './state.js';

const share = {
  name: '', // the project these are for
  plan: null, // GET .../share
  comments: [], seen: [], stale: '',
  busy: '', // 'upload' | 'off' | 'change' | 'reply:<id>' …
  error: '',
  confirmOff: false,
  deleting: '', // the comment whose delete waits for a second press
  photos: true, by: '',
  copied: '',
  focus: '', // a comment to show (from a pin)
  replies: new Map(), // comment id → reply being typed
};

let dialog = null;

export function shareUnread(name) {
  return share.name === name ? unreadComments(share.comments, share.seen).length : 0;
}

function ensureDialog() {
  if (dialog) return dialog;
  dialog = document.createElement('dialog');
  dialog.id = 'share-dialog';
  dialog.setAttribute('aria-labelledby', 'share-title');
  document.body.append(dialog);
  dialog.addEventListener('click', (e) => {
    if (e.target === dialog) { dialog.close(); return; } // outside the panel
    const button = e.target.closest('[data-share]');
    if (button) act(button.dataset.share, button);
  });
  dialog.addEventListener('change', (e) => {
    if (e.target.name === 'share-photos') { share.photos = e.target.checked; draw(); }
    if (e.target.name === 'share-comments') change({ comments_open: e.target.checked });
  });
  dialog.addEventListener('input', (e) => {
    if (e.target.name === 'share-by') share.by = e.target.value;
    if (e.target.dataset.reply) share.replies.set(e.target.dataset.reply, e.target.value);
  });
  dialog.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && e.target.dataset.reply && !e.isComposing) { e.preventDefault(); act('reply', e.target); }
  });
  dialog.addEventListener('close', () => { share.confirmOff = false; share.deleting = ''; render(false); });
  return dialog;
}

function applyComments(got) {
  share.comments = got.comments || [];
  share.seen = got.seen || share.seen;
  share.stale = got.stale || '';
  if (share.plan?.share) share.plan.share.on = got.on ?? share.plan.share.on;
  pinsToTable();
}

// The comments with a spot stand on the table as numbered pins.
function pinsToTable() {
  const unread = new Set(unreadComments(share.comments, share.seen).map((c) => c.id));
  const pins = commentThreads(share.comments).filter((c) => c.at).map((c) => ({
    id: c.id, number: c.number, at: c.at, target: c.target, resolved: c.resolved, unread: unread.has(c.id),
    text: c.text, author: c.author,
  }));
  table?.setComments?.(pins);
}

// The pins again, for a table made after the comments came.
export function pinsAgain() {
  if (share.name === ui.project) pinsToTable();
}

// What the project's share is and its comments, when the project opens (no window).
export async function loadShare(name) {
  if (share.name !== name) {
    Object.assign(share, { name, plan: null, comments: [], seen: [], stale: '', error: '', confirmOff: false, focus: '' });
    share.replies.clear();
  }
  try {
    share.plan = await api(`${projectApi(name)}/share`);
    share.photos = share.plan.share?.photos ?? true;
    share.by = share.plan.share?.by || share.by;
    // the kept comments at once, then the server's
    applyComments(await api(`${projectApi(name)}/share/comments?refresh=false`));
    if (share.plan.share?.on) applyComments(await api(`${projectApi(name)}/share/comments`));
  } catch { /* the table opens without its share; the window says why when opened */ }
  if (dialog?.open) draw();
  render(false);
}

export function openShare(name, opener = null, focus = '') {
  ensureDialog();
  share.focus = focus;
  share.error = '';
  if (!dialog.open) {
    const r = opener?.getBoundingClientRect?.();
    dialog.classList.toggle('from-left', Boolean(r && r.left + r.width / 2 < innerWidth / 2));
    dialog.showModal();
  }
  draw();
  loadShare(name).then(markSeen);
}

// The comments now on screen are seen: the 새 댓글 count leaves them out.
async function markSeen() {
  const ids = unreadComments(share.comments, share.seen).map((c) => c.id);
  if (!ids.length || !dialog?.open) return;
  try { applyComments(await api(`${projectApi(share.name)}/share/comments/seen`, { method: 'PUT', body: { ids } })); }
  catch { return; }
  render(false);
}

async function busy(what, call) {
  if (share.busy) return null;
  share.busy = what;
  share.error = '';
  draw();
  try { return await call(); }
  catch (error) { share.error = error.message; return null; }
  finally { share.busy = ''; draw(); render(false); }
}

async function upload() {
  const done = await busy('upload', () => api(`${projectApi(share.name)}/share`, { method: 'POST', body: { photos: share.photos, by: share.by.trim() } }));
  if (!done) return;
  share.plan = { ...share.plan, share: done.share };
  share.confirmOff = false;
  toast(done.share.version > 1 ? `${done.share.version}번째 판을 올렸습니다. 같은 링크에서 새 판이 보입니다.` : '공유했습니다. 링크를 복사해 보내세요.', 'success');
  draw();
}

async function change(body) {
  const done = await busy('change', () => api(`${projectApi(share.name)}/share`, { method: 'PATCH', body }));
  if (done) share.plan = { ...share.plan, share: done.share };
  if (done && body.new_links) toast('링크를 바꿨습니다. 예전 링크는 이제 열리지 않습니다.', 'success');
  draw();
}

async function turnOff() {
  const done = await busy('off', () => api(`${projectApi(share.name)}/share`, { method: 'DELETE' }));
  if (!done) return;
  share.plan = { ...share.plan, share: done.share };
  share.confirmOff = false;
  toast('공유를 껐습니다. 링크가 막히고 서버의 사본이 지워졌습니다.', 'success');
  draw();
}

async function copy(which) {
  const s = share.plan?.share || {};
  const url = which === 'view' ? s.view_url : s.comment_url;
  try { await navigator.clipboard.writeText(url); share.copied = which; }
  catch { share.error = '복사하지 못했습니다. 링크를 길게 눌러 직접 복사해 주세요.'; }
  draw();
  setTimeout(() => { if (share.copied === which) { share.copied = ''; draw(); } }, 2000);
}

async function commentCall(what, method, path, body) {
  const done = await busy(what, () => api(`${projectApi(share.name)}/share/comments${path}`, { method, body }));
  if (done) applyComments(done);
  return done;
}

function askConductor(id) {
  const comment = share.comments.find((c) => c.id === id);
  if (!comment) return;
  const papers = ui.board?.papers || [];
  const label = targetLabel(comment.target, papers);
  const paperId = targetPaper(comment.target);
  if (paperId && papers.some((p) => p.id === paperId)) { // the scheme it is about goes with the question
    ui.selected = [paperId];
    table?.setSelected([paperId]);
  }
  dialog.close();
  askAbout(conductorQuestion(comment, label));
}

function act(action, el) {
  const id = el.dataset.id || el.dataset.reply || '';
  if (action === 'close') dialog.close();
  if (action === 'settings') { dialog.close(); openSettings('#settings-relay'); }
  if (action === 'upload') upload();
  if (action === 'copy') copy(el.dataset.which);
  if (action === 'ask-off') { share.confirmOff = true; draw(); dialog.querySelector('[data-share="off"]')?.focus(); }
  if (action === 'keep') { share.confirmOff = false; draw(); }
  if (action === 'off') turnOff();
  if (action === 'new-links') change({ new_links: true });
  if (action === 'reply') {
    const text = (share.replies.get(id) || '').trim();
    if (!text) { share.error = '답글을 적어 주세요.'; draw(); return; }
    commentCall(`reply:${id}`, 'POST', '', { parent: id, text }).then((done) => { if (done) { share.replies.delete(id); draw(); } });
  }
  if (action === 'resolve') commentCall(`resolve:${id}`, 'PATCH', `/${encodeURIComponent(id)}`, { resolved: el.dataset.resolved === 'true' });
  if (action === 'delete') {
    if (share.deleting !== id) { share.deleting = id; draw(); return; }
    share.deleting = '';
    commentCall(`delete:${id}`, 'DELETE', `/${encodeURIComponent(id)}`);
  }
  if (action === 'ask') askConductor(id);
  if (action === 'show-pin') { dialog.close(); table?.showComment?.(id); }
}

// ------------------------------------------------------------------ drawing

function linkRow(label, url, which) {
  return `<div class="share-link"><span class="share-link-text"><b>${label}</b><span class="share-url" title="${escape(url)}">${escape(url.replace(/^https?:\/\//, ''))}</span></span>
    <button type="button" class="secondary" data-share="copy" data-which="${which}">${share.copied === which ? '복사됨' : '링크 복사'}</button></div>`;
}

function commentView(c, papers, unread) {
  const label = targetLabel(c.target, papers);
  const busyHere = share.busy.endsWith(`:${c.id}`);
  const on = Boolean(share.plan?.share?.on);
  const replies = c.replies.map((r) => `<li class="share-reply${r.by_owner ? ' mine' : ''}"><b>${escape(r.author)}</b><span class="muted"> · ${commentTime(r.created)}</span><p>${escape(r.text)}</p></li>`).join('');
  return `<li class="share-comment${c.resolved ? ' resolved' : ''}${share.focus === c.id ? ' focused' : ''}" id="share-comment-${escape(c.id)}">
      <div class="share-comment-head"><span class="comment-number${unread.has(c.id) ? ' unread' : ''}" aria-hidden="true">${c.number}</span>
        <b>${escape(c.author)}</b><span class="muted">${commentTime(c.created)} · ${c.version}번째 판</span>
        ${unread.has(c.id) ? '<span class="share-new">새로 옴</span>' : ''}${c.resolved ? '<span class="share-done">해결됨</span>' : ''}</div>
      ${label ? `<span class="share-target">${escape(label)}</span>` : ''}
      <p class="share-comment-text">${escape(c.text)}</p>
      ${replies ? `<ul class="share-replies">${replies}</ul>` : ''}
      ${on ? `<label class="sr-only" for="reply-${escape(c.id)}">답글</label>
      <div class="share-reply-form"><input id="reply-${escape(c.id)}" data-reply="${escape(c.id)}" maxlength="${MAX_TEXT}" placeholder="답글은 보는 사람 화면에도 보입니다" value="${escape(share.replies.get(c.id) || '')}">
        <button type="button" class="primary-small" data-share="reply" data-id="${escape(c.id)}" ${busyHere ? 'disabled' : ''}>답글 보내기</button></div>` : ''}
      <div class="share-comment-actions">
        <button type="button" class="secondary" data-share="resolve" data-id="${escape(c.id)}" data-resolved="${!c.resolved}">${c.resolved ? '해결 취소' : '해결로 표시'}</button>
        <button type="button" class="secondary" data-share="ask" data-id="${escape(c.id)}">Conductor에게 묻기</button>
        ${c.at ? `<button type="button" class="secondary" data-share="show-pin" data-id="${escape(c.id)}">제도판에서 보기</button>` : ''}
        <button type="button" class="ghost danger-text" data-share="delete" data-id="${escape(c.id)}">${share.deleting === c.id ? '정말 지우기' : '지우기'}</button>
      </div>
    </li>`;
}

function draw() {
  if (!dialog) return;
  const plan = share.plan;
  const s = plan?.share || { on: false };
  const status = shareStatus(s);
  const head = `<div class="dialog-heading"><div><h2 id="share-title">공유</h2>
      <span class="share-status"><span class="share-dot${status.on ? ' on' : ''}" aria-hidden="true"></span>${escape(status.text)}</span></div>
      <button type="button" class="icon-button" data-share="close" aria-label="공유 창 닫기"><svg class="icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><path d="M5 5l10 10M15 5 5 15"/></svg></button></div>`;
  if (!plan) {
    dialog.innerHTML = `<div class="share-panel">${head}<div class="share-body"><p class="${share.error ? 'error-text' : 'muted'}">${escape(share.error || '공유 상태를 불러오는 중입니다.')}</p></div></div>`;
    return;
  }
  const counts = paperCounts(plan.papers);
  const left = leftOutLine({ ...plan.left_out, ...(share.photos ? {} : { photo: plan.papers.photo || 0 }) });
  const usage = usageView(s);
  const threads = commentThreads(share.comments);
  const unread = new Set(unreadComments(share.comments, share.seen).map((c) => c.id));
  const papers = ui.board?.papers || [];
  const noKey = !plan.has_key;
  const uploading = share.busy === 'upload';
  dialog.innerHTML = `<div class="share-panel">${head}
    <div class="share-body">
      <section class="share-section" aria-labelledby="share-up">
        <h3 id="share-up">올라가는 것</h3>
        <div class="share-box">
          <div class="share-row"><span><b>제도판</b><small>${escape(counts || '대지만 있습니다')}</small></span></div>
          <div class="share-row"><span><b>대지 정보</b><small>${plan.site ? '대지 카드와 근거 조문' : '아직 대지를 고르지 않았습니다'}</small></span></div>
          ${plan.papers.photo ? `<label class="share-row check"><span><b>사진 ${plan.papers.photo}장</b><small>긴 변 2,000px로 줄여서 올립니다</small></span>
            <span class="muted">${share.photos ? sizeLabel(plan.photo_bytes) + ' 원본' : '빠짐'}</span><input type="checkbox" name="share-photos" ${share.photos ? 'checked' : ''}></label>` : ''}
          <div class="share-row locked"><svg class="icon" viewBox="0 0 20 20" aria-hidden="true" focusable="false"><rect x="4.5" y="9" width="11" height="8" rx="1.5"/><path d="M7 9V6.5a3 3 0 0 1 6 0V9"/></svg>
            <span><b>대화는 올라가지 않습니다</b><small>Conductor와 전문가 대화는 이 PC에서 본인만 봅니다.</small></span></div>
        </div>
        <p class="share-note">${escape(left)} 지형·등고선·주변 3D 파일은 올리지 않습니다. 레이어를 끈 것도 올리지 않습니다.</p>
        <label class="share-field" for="share-by">보는 사람에게 보일 이름 <small class="muted">(선택)</small></label>
        <input id="share-by" name="share-by" maxlength="40" placeholder="예: 김시다" value="${escape(share.by)}">
      </section>
      ${s.on ? `<section class="share-section" aria-labelledby="share-links">
        <h3 id="share-links">링크</h3>
        ${linkRow('보기와 댓글', s.comment_url || '', 'comment')}
        ${linkRow('보기만', s.view_url || '', 'view')}
        <label class="share-row toggle"><span><b>새 댓글 받기</b><small>끄면 기존 댓글만 남고 새 댓글은 막힙니다</small></span>
          <input type="checkbox" name="share-comments" ${s.comments_open ? 'checked' : ''} ${share.busy ? 'disabled' : ''}></label>
        <button type="button" class="ghost share-small" data-share="new-links">링크 바꾸기 (예전 링크는 막힘)</button>
      </section>` : ''}
      <section class="share-section" aria-labelledby="share-comments-title">
        <h3 id="share-comments-title">댓글 ${threads.length ? `<span class="muted">${threads.length}개</span>` : ''}</h3>
        ${share.stale ? `<p class="share-note">${escape(share.stale)} 받아 둔 댓글을 보여 줍니다.</p>` : ''}
        ${threads.length ? `<ol class="share-comments">${threads.map((c) => commentView(c, papers, unread)).join('')}</ol>`
          : `<p class="muted share-empty">${s.on ? '아직 댓글이 없습니다. 링크를 받은 사람이 3D 위를 눌러 댓글을 남기면 여기와 제도판에 핀으로 옵니다.' : '공유하면 링크를 받은 사람이 댓글을 남길 수 있습니다.'}</p>`}
      </section>
      ${s.on ? `<section class="share-section" aria-labelledby="share-usage">
        <h3 id="share-usage">사용량</h3>
        <div class="share-usage"><span>이 프로젝트</span><b>${escape(usage.project.text)}</b></div>
        <div class="share-bar" aria-hidden="true"><span style="width:${usage.project.pct}%"></span></div>
        <div class="share-usage muted"><span>${escape(usage.line)}</span><span>${escape(keptUntil(s.expires))}</span></div>
      </section>` : ''}
    </div>
    <div class="share-foot">
      ${noKey ? '<p class="share-note">공유하려면 Sida 키가 필요합니다. <button type="button" class="link-button" data-share="settings">설정에서 받기</button></p>' : ''}
      ${share.error ? `<p class="error-text" role="alert">${escape(share.error)}</p>` : ''}
      ${share.confirmOff ? `<div class="share-confirm" role="alertdialog" aria-label="공유 끄기 확인">
        <p>"${escape(plan.title)}" 공유를 끄면 두 링크가 바로 막히고, 서버의 사본과 댓글이 지워집니다. 받아 둔 댓글은 내 Sida에 남습니다.</p>
        <div><button type="button" class="secondary" data-share="keep">그대로 두기</button>
          <button type="button" class="primary danger" data-share="off" ${share.busy ? 'disabled' : ''}>공유 끄고 사본 지우기</button></div></div>` : ''}
      <div class="share-actions">
        ${s.on ? `<button type="button" class="secondary danger-text" data-share="ask-off" ${share.busy ? 'disabled' : ''}>공유 끄기</button>` : ''}
        <button type="button" class="primary" data-share="upload" ${share.busy || noKey ? 'disabled' : ''} aria-busy="${uploading}">${uploading ? '<span class="spinner" aria-hidden="true"></span>올리는 중…' : escape(uploadLabel(s))}</button>
      </div>
    </div></div>`;
  if (share.focus) {
    dialog.querySelector(`#share-comment-${CSS.escape(share.focus)}`)?.scrollIntoView({ block: 'center' });
    share.focus = '';
  }
}
