// The viewer page of a share (share.html), served by the Sida data server at /s/<link>: the
// snapshot a designer uploaded (sida/share.py), drawn in 3D with its schemes, the site card, the
// notes and photos, and the comments. With the comment link, a viewer names themselves and leaves
// a comment, on a spot of the model ("댓글 놓기") or on the scheme as a whole. Nothing is kept in
// the browser; everything comes from the server (relay/app.py /s/<link>/...).

import * as THREE from './vendor/three.js';
import { escapeHtml as escape, siteRuleRows } from './model.js';
import {
  viewerSchemes, figureRows, schemeBoxes, localRings, siteRows, commentThreads, commentProblem, commentTime,
  targetLabel, targetPaper, prismTriangles, orbitCamera, startDistance, commentSpot, keptUntil, aroundScene, AROUND_LOOK,
} from './share-model.js';
import { vworldFrame } from './board-model.js';

const link = decodeURIComponent(location.pathname.split('/').filter(Boolean).pop() || '');
const base = `/s/${encodeURIComponent(link)}`;
const $ = (id) => document.getElementById(id);

const state = {
  info: null, version: 0, snapshot: null, comments: [], parcels: [], parcelShapes: [], around: false,
  scheme: '', placing: false, spot: null, tab: 'comments', sending: false,
  view: { x: 0, y: 0, z: 0, turn: 30, tilt: 55, dist: 150 }, home: null,
};

async function get(path) {
  const r = await fetch(`${base}${path}`, { headers: { Accept: 'application/json' } });
  if (!r.ok) {
    let detail = '';
    try { detail = (await r.json()).detail; } catch { /* no body */ }
    const error = new Error(typeof detail === 'string' ? detail : `불러오지 못했습니다 (${r.status})`);
    error.status = r.status;
    throw error;
  }
  return r.json();
}

// ------------------------------------------------------------------ the scene

const gl = {};
const GROUND = -0.4; // m: the ground plane, under the lot (z 0) and the grid

function setupScene() {
  const host = $('scene');
  gl.renderer = new THREE.WebGLRenderer({ antialias: true });
  gl.renderer.setPixelRatio(Math.min(2, devicePixelRatio || 1));
  gl.renderer.setClearColor(0xfbfbfc);
  host.prepend(gl.renderer.domElement);
  gl.scene = new THREE.Scene();
  gl.camera = new THREE.PerspectiveCamera(35, 1, 1, 12000);
  gl.camera.up.set(0, 0, 1);
  gl.scene.add(new THREE.HemisphereLight(0xffffff, 0xd9dde2, 2.2));
  const sun = new THREE.DirectionalLight(0xffffff, 1.4);
  sun.position.set(-300, -500, 800);
  gl.scene.add(sun);
  gl.ground = new THREE.Mesh(new THREE.PlaneGeometry(20000, 20000), new THREE.MeshLambertMaterial({ color: 0xeef0f2 }));
  gl.ground.position.z = GROUND; // a little under the lot lines, so they never fight the ground
  gl.scene.add(gl.ground);
  const grid = new THREE.GridHelper(2000, 200, 0xdfe3e7, 0xe6e9ec);
  grid.rotation.x = Math.PI / 2;
  grid.position.z = GROUND / 2;
  gl.scene.add(grid);
  gl.site = new THREE.Group();
  gl.masses = new THREE.Group();
  gl.scene.add(gl.site, gl.masses);
  gl.ray = new THREE.Raycaster();
  new ResizeObserver(resize).observe(host);
  resize();
  controls(host);
}

function resize() {
  const host = $('scene');
  const w = host.clientWidth;
  const h = host.clientHeight;
  if (!w || !h) return;
  gl.renderer.setSize(w, h, false);
  gl.camera.aspect = w / h;
  gl.camera.updateProjectionMatrix();
  draw();
}

let frame = 0;
function draw() {
  if (frame) return;
  frame = requestAnimationFrame(() => {
    frame = 0;
    const { position, target } = orbitCamera(state.view);
    gl.camera.position.set(...position);
    gl.camera.lookAt(...target);
    gl.renderer.render(gl.scene, gl.camera);
    placePins();
  });
}

function clear(group) {
  for (const child of [...group.children]) {
    child.geometry?.dispose();
    child.material?.dispose();
  }
  group.clear();
}

function drawLots() {
  clear(gl.site);
  const lot = new THREE.LineDashedMaterial({ color: 0xc0392b, dashSize: 1.2, gapSize: 0.8 });
  for (const ring of state.parcels) {
    const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(ring.map(([x, y]) => new THREE.Vector3(x, y, 0.08))), lot);
    line.computeLineDistances();
    gl.site.add(line);
    const fill = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(ring.map(([x, y]) => new THREE.Vector2(x, y)))),
      new THREE.MeshBasicMaterial({ color: 0xf6e3df, transparent: true, opacity: 0.7, depthWrite: false }));
    fill.position.z = 0.05;
    gl.site.add(fill);
  }
}

function drawMasses() {
  clear(gl.masses);
  const scheme = viewerSchemes(state.snapshot).find((s) => s.id === state.scheme);
  if (!scheme) { draw(); return; }
  const siteFrame = state.snapshot.site?.plan?.frame;
  const body = new THREE.MeshLambertMaterial({ color: 0xb9c7d4 });
  const edges = new THREE.LineBasicMaterial({ color: 0x36536b });
  for (const box of schemeBoxes(scheme.paper, siteFrame)) {
    const geom = new THREE.BufferGeometry();
    geom.setAttribute('position', new THREE.Float32BufferAttribute(prismTriangles(box.corners, box.top), 3));
    geom.computeVertexNormals();
    const mesh = new THREE.Mesh(geom, body.clone());
    mesh.material.side = THREE.DoubleSide;
    mesh.userData.key = box.key;
    gl.masses.add(mesh);
    gl.masses.add(new THREE.LineSegments(new THREE.EdgesGeometry(geom), edges));
  }
  draw();
}

function goHome() {
  const plan = state.snapshot?.site?.plan;
  const schemes = viewerSchemes(state.snapshot);
  const tallest = Math.max(0, ...schemes.map((s) => s.figures?.height_m || 0));
  const middle = plan?.bounds ? { x: (plan.bounds.min_x + plan.bounds.max_x) / 2, y: (plan.bounds.min_y + plan.bounds.max_y) / 2 } : { x: 0, y: 0 };
  state.view = { ...middle, z: Math.min(tallest / 3, 30), turn: 30, tilt: 58, dist: startDistance(plan?.bounds, tallest) };
  draw();
}

// Drag turns, Shift or the right button moves, the wheel (or a pinch) brings it closer.
function controls(host) {
  const canvas = gl.renderer.domElement;
  let drag = null;
  const pointers = new Map();
  canvas.addEventListener('contextmenu', (e) => e.preventDefault());
  canvas.addEventListener('pointerdown', (e) => {
    canvas.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    drag = { x: e.clientX, y: e.clientY, moved: 0, pan: e.button === 2 || e.shiftKey, pinch: pointers.size === 2 ? pinchSpan(pointers) : 0 };
  });
  canvas.addEventListener('pointermove', (e) => {
    if (!drag) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const dx = e.clientX - drag.x;
    const dy = e.clientY - drag.y;
    drag.x = e.clientX;
    drag.y = e.clientY;
    drag.moved += Math.abs(dx) + Math.abs(dy);
    const v = state.view;
    if (pointers.size === 2 && drag.pinch) {
      const span = pinchSpan(pointers);
      v.dist = Math.min(6000, Math.max(15, v.dist * (drag.pinch / span)));
      drag.pinch = span;
    } else if (drag.pan) {
      const k = v.dist / host.clientHeight;
      const a = (v.turn * Math.PI) / 180;
      v.x -= (dx * Math.cos(a) + dy * Math.sin(a)) * k;
      v.y -= (-dx * Math.sin(a) + dy * Math.cos(a)) * k;
    } else {
      v.turn = (v.turn + dx * 0.4) % 360;
      v.tilt = Math.min(85, Math.max(2, v.tilt - dy * 0.3));
    }
    draw();
  });
  const up = (e) => {
    pointers.delete(e.pointerId);
    if (drag && drag.moved < 5 && e.type === 'pointerup' && e.button === 0) pick(e);
    if (!pointers.size) drag = null;
  };
  canvas.addEventListener('pointerup', up);
  canvas.addEventListener('pointercancel', up);
  canvas.addEventListener('wheel', (e) => {
    e.preventDefault();
    state.view.dist = Math.min(6000, Math.max(15, state.view.dist * Math.exp(e.deltaY * 0.0012)));
    draw();
  }, { passive: false });
}

function pinchSpan(pointers) {
  const [a, b] = [...pointers.values()];
  return Math.max(1, Math.hypot(a.x - b.x, a.y - b.y));
}

// A click while placing: the spot on a block or the ground becomes the comment's place.
function pick(e) {
  if (!state.placing) return;
  const r = gl.renderer.domElement.getBoundingClientRect();
  const at = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
  gl.ray.setFromCamera(at, gl.camera);
  const hit = gl.ray.intersectObjects([...gl.masses.children.filter((c) => c.isMesh), gl.ground], false)[0];
  if (!hit) return;
  state.spot = commentSpot({ x: hit.point.x, y: hit.point.y, z: Math.max(0, hit.point.z), key: hit.object.userData.key || '' });
  if (!state.spot.target && state.scheme) state.spot.target = state.scheme; // on the ground: about the scheme shown
  setPlacing(false);
  drawForm();
  draw();
  $('text').focus();
}

// The comments of the version shown stand where they were put.
function placePins() {
  const host = $('scene');
  const w = host.clientWidth;
  const h = host.clientHeight;
  const html = [];
  const pins = commentThreads(state.comments).filter((c) => c.at && c.version === state.version);
  if (state.spot) pins.push({ id: 'new', number: '+', at: state.spot.at, author: '새 댓글', fresh: true });
  for (const c of pins) {
    const v = new THREE.Vector3(c.at.x, c.at.y, c.at.z || 0).project(gl.camera);
    if (v.z > 1 || v.z < -1) continue;
    const x = ((v.x + 1) / 2) * w;
    const y = ((1 - v.y) / 2) * h;
    if (x < -30 || x > w + 30 || y < -30 || y > h + 30) continue;
    html.push(`<button type="button" class="pin${c.fresh ? ' fresh' : c.resolved ? ' resolved' : ''}" data-pin="${escape(c.id)}" style="transform: translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)" aria-label="${escape(`댓글 ${c.number}: ${c.author}`)}">${c.number}</button>`);
  }
  const out = html.join('');
  if ($('pins').innerHTML !== out) $('pins').innerHTML = out;
}

// ------------------------------------------------------------------ the surroundings

// VWorld's 3D map around the site, in one colour, with the scheme on it: the app's own 3D page
// (vworld3d-frame.js), served by this server with its 3D key at /s/<link>/around and driven by
// the same messages as on the table (vworld-view.js). The buildings standing on the site now are
// found on the map and hidden once per visit (VWorld's data is not kept, here or on the server).
// Comments are placed on the model view, not here.
const around = { loaded: false, key: '', calls: new Map(), next: 1, hidden: null };
const TAG = 'vworld3d';

function askAround(method, ...args) {
  const frame = $('around');
  if (!around.loaded || !frame.contentWindow) return Promise.resolve(null);
  const id = around.next++;
  return new Promise((resolve) => {
    around.calls.set(id, resolve);
    frame.contentWindow.postMessage({ sida: TAG, id, method, args }, location.origin);
  });
}

function onAroundMessage(e) {
  const m = e.data;
  if (e.source !== $('around').contentWindow || e.origin !== location.origin || m?.sida !== TAG) return;
  if (m.event === 'pick') { if (m.id) askAround('unpick'); return; } // nothing to pick here
  const done = around.calls.get(m.id);
  if (!done) return;
  around.calls.delete(m.id);
  done(m.error ? null : m.result);
}

async function showAround(on) {
  state.around = on;
  $('around-toggle').setAttribute('aria-pressed', String(on));
  $('scene').classList.toggle('around', on);
  $('around').hidden = !on;
  if (on) setPlacing(false);
  if (state.info) drawHead();
  if (!on) { hint(''); draw(); return; }
  const scene = aroundScene(state.snapshot, state.scheme, state.parcelShapes);
  const frame = scene && vworldFrame({ page: `${base}/around` }, scene.center, location.origin);
  if (!frame) { hint('대지 위치가 없어 주변 건물을 보여 줄 수 없습니다.'); return; }
  hint('브이월드 3D 지도를 여는 중…');
  if (around.key !== frame.key) {
    around.key = frame.key;
    around.loaded = false;
    for (const done of around.calls.values()) done(null);
    around.calls.clear();
    const loaded = new Promise((resolve) => $('around').addEventListener('load', resolve, { once: true }));
    $('around').src = frame.src;
    await loaded;
    around.loaded = true;
  }
  const ok = await askAround('show', { center: scene.center, polygons: scene.polygons, hidden: around.hidden || [], appearance: AROUND_LOOK });
  if (!state.around) return;
  if (!ok) { hint((await askAround('failed')) || '브이월드 3D 지도를 열지 못했습니다.'); return; }
  if (around.hidden === null && scene.rings.length) { // the buildings on the site now, once per visit
    hint('대지 위의 지금 건물을 숨기는 중…');
    around.hidden = (await askAround('findSite', scene.rings, scene.center)) || [];
    if (around.hidden.length) await askAround('setHidden', around.hidden);
  }
  if (!state.around) return;
  hint('주변 건물은 브이월드 3D를 한 색으로 보여 줍니다. 댓글은 "주변 건물"을 끄고 놓습니다.');
  setTimeout(() => { if (state.around) hint(''); }, 5000);
}

// ------------------------------------------------------------------ the page

function hint(text) {
  $('hint').textContent = text;
  $('hint').hidden = !text;
}

function setPlacing(on) {
  state.placing = on;
  $('place').setAttribute('aria-pressed', String(on));
  $('scene').classList.toggle('placing', on);
  hint(on ? '댓글을 붙일 곳을 누르세요 · "댓글 놓기"를 다시 누르면 그만둡니다' : '');
}

function drawHead() {
  const info = state.info;
  const snap = state.snapshot;
  $('title').textContent = info.title;
  document.title = `${info.title} · Sida 공유`;
  const kept = keptUntil(info.expires).replace('보관', '열립니다');
  $('byline').textContent = [info.by ? `${info.by}님이 공유함` : '', snap?.address || '', kept ? `링크는 ${kept}` : ''].filter(Boolean).join(' · ');
  const select = $('version');
  select.innerHTML = info.versions.slice().reverse().map((v) => `<option value="${v.number}" ${v.number === state.version ? 'selected' : ''}>${v.number}번째 판 · ${escape(commentTime(v.created))}</option>`).join('');
  select.disabled = info.versions.length < 2;
  $('mode-chip').textContent = info.can_comment ? (info.comments_open ? '보기와 댓글' : '보기 전용 · 댓글 닫힘') : '보기 전용';
  $('place').hidden = state.around || !(info.can_comment && info.comments_open);
  $('around-toggle').hidden = !(info.around && state.snapshot?.site?.plan?.origin);
}

function drawSchemes() {
  const schemes = viewerSchemes(state.snapshot);
  if (!schemes.some((s) => s.id === state.scheme)) state.scheme = schemes[0]?.id || '';
  $('schemes').innerHTML = schemes.length
    ? schemes.map((s) => `<button type="button" data-scheme="${escape(s.id)}" aria-pressed="${s.id === state.scheme}">${escape(s.title)}</button>`).join('')
    : '<span class="muted small">매스안이 없습니다</span>';
  const scheme = schemes.find((s) => s.id === state.scheme);
  $('figures').innerHTML = figureRows(scheme?.figures, state.snapshot.site?.area_m2)
    .map(([label, value]) => `<div><dt>${escape(label)}</dt><dd>${escape(value)}</dd></div>`).join('');
}

function drawComments() {
  const papers = state.snapshot?.board?.papers || [];
  const threads = commentThreads(state.comments);
  $('tab-comments').textContent = `댓글 ${threads.length}`;
  $('comments').innerHTML = threads.length ? threads.map((c) => {
    const label = targetLabel(c.target, papers);
    const replies = c.replies.map((r) => `<li class="reply${r.by_owner ? ' owner' : ''}"><b>${escape(r.author)}${r.by_owner ? ' <span class="owner-tag">설계자</span>' : ''}</b><p>${escape(r.text)}</p></li>`).join('');
    const other = c.version !== state.version ? `<span class="muted small">${c.version}번째 판에 남김</span>` : '';
    return `<li class="comment${c.resolved ? ' resolved' : ''}" data-comment="${escape(c.id)}">
      <div class="comment-head"><span class="badge" aria-hidden="true">${c.number}</span><b>${escape(c.author)}</b><span class="muted small">${commentTime(c.created)}</span>${c.resolved ? '<span class="done">해결됨</span>' : ''}</div>
      ${label ? `<span class="anchor">${escape(label)}</span>` : ''}${other}
      <p>${escape(c.text)}</p>
      ${replies ? `<ul class="replies">${replies}</ul>` : ''}
      ${canComment() ? `<button type="button" class="reply-button" data-reply="${escape(c.id)}">답글</button>` : ''}
    </li>`;
  }).join('') : `<li class="empty"><b>아직 댓글이 없습니다</b><span>${canComment() ? '"댓글 놓기"를 누르고 3D에서 의견을 붙일 곳을 고르세요. 붙일 곳 없이 남겨도 됩니다.' : '이 링크로는 볼 수만 있습니다.'}</span></li>`;
}

function canComment() {
  return Boolean(state.info?.can_comment && state.info?.comments_open);
}

let replyTo = '';
function drawForm() {
  const form = $('comment-form');
  form.hidden = !canComment();
  const note = $('comments-note');
  note.hidden = canComment();
  note.textContent = state.info?.can_comment ? '설계자가 새 댓글을 닫았습니다. 지금 있는 댓글만 볼 수 있습니다.' : '보기만 하는 링크입니다. 댓글을 남기려면 설계자에게 "보기와 댓글" 링크를 받으세요.';
  const papers = state.snapshot?.board?.papers || [];
  const scheme = viewerSchemes(state.snapshot).find((s) => s.id === state.scheme);
  const parent = replyTo && state.comments.find((c) => c.id === replyTo);
  $('spot').innerHTML = parent
    ? `<span class="spot-chip">${escape(parent.author)}님 댓글에 답글 <button type="button" data-clear="reply" aria-label="답글 그만두기">×</button></span>`
    : state.spot
      ? `<span class="spot-chip">${escape(targetLabel(state.spot.target, papers) || '고른 곳')}에 붙임 <button type="button" data-clear="spot" aria-label="붙일 곳 지우기">×</button></span>`
      : `<span class="muted small">붙일 곳 없이 남기면 ${escape(scheme?.title || '이 안')} 전체에 대한 댓글이 됩니다</span>`;
  $('form-note').textContent = state.info?.by ? `댓글은 ${state.info.by}님의 Sida에 바로 전달됩니다.` : '댓글은 설계자의 Sida에 바로 전달됩니다.';
}

function drawSitePanel() {
  const site = state.snapshot?.site;
  const panel = $('panel-site');
  if (!site) { panel.innerHTML = '<p class="muted">공유한 사람이 아직 대지를 고르지 않았습니다.</p>'; return; }
  const area = site.area_m2 ? `${Number(site.area_m2).toLocaleString('ko-KR', { maximumFractionDigits: 1 })}㎡` : '미확인';
  const rows = siteRows(site).map((r) => `<dt>${escape(r.label)}</dt><dd>${escape(r.text)}</dd>`).join('');
  const rules = siteRuleRows(site.rules).map((r) => `<li class="rule ${escape(r.tone)}"><div><b>${escape(r.title)}</b><span class="rule-badge">${escape(r.badge)}</span></div>
      <p class="rule-value">${escape(r.value)}</p>${r.detail ? `<p class="muted small">${escape(r.detail)}</p>` : ''}
      ${r.quote ? `<details><summary>근거 원문</summary><blockquote>${escape(r.quote)}</blockquote>${r.source ? `<p class="muted small">${escape(r.source)}</p>` : ''}</details>` : ''}</li>`).join('');
  panel.innerHTML = `<div class="site-head"><b>${escape(state.snapshot.address || '대지')}</b>
      <span class="muted small">정부 자료와 조례 원문에서 Sida가 규칙으로 읽은 값입니다. 올린 때의 값입니다.</span></div>
    <dl class="site-facts"><dt>대지면적</dt><dd>${escape(area)}</dd>${rows}</dl>
    ${rules ? `<h2 class="side-heading">이 대지에 걸리는 것</h2><ul class="rules">${rules}</ul>` : ''}
    <div class="cta"><b>내 대지도 이렇게 볼 수 있나요?</b><span>Sida는 주소만 넣으면 대지 조건을 조문과 함께 정리하고, 매스안을 바로 세워 봅니다.</span><a href="/">Sida 알아보기</a></div>`;
}

function drawPapers() {
  const papers = state.snapshot?.board?.papers || [];
  const notes = papers.filter((p) => p.kind === 'note' && p.text);
  const photos = papers.filter((p) => p.kind === 'photo' && p.photo);
  const left = state.snapshot?.left_out || {};
  const parts = [];
  if (notes.length) parts.push(`<h2 class="side-heading">메모</h2><ul class="notes">${notes.map((n) => `<li>${escape(n.text)}</li>`).join('')}</ul>`);
  if (photos.length) parts.push(`<h2 class="side-heading">사진</h2><ul class="photos">${photos.map((p) => `<li><img src="${base}/v/${state.version}/${escape(p.photo)}" alt="${escape(p.title || '사진')}" loading="lazy">${p.title ? `<span>${escape(p.title)}</span>` : ''}</li>`).join('')}</ul>`);
  if (!parts.length) parts.push('<p class="muted">함께 올린 메모나 사진이 없습니다.</p>');
  if (left.photo) parts.push('<p class="muted small">설계자가 사진을 빼고 올렸습니다.</p>');
  $('panel-papers').innerHTML = parts.join('');
  $('tab-papers').hidden = !notes.length && !photos.length;
}

function showTab(tab) {
  state.tab = tab;
  for (const name of ['comments', 'site', 'papers']) {
    $(`tab-${name}`).setAttribute('aria-selected', String(name === tab));
    $(`panel-${name}`).hidden = name !== tab;
  }
}

async function loadVersion(number) {
  state.version = number;
  state.snapshot = await get(`/v/${number}/snapshot.json`);
  drawHead();
  drawSchemes();
  drawMasses();
  drawComments();
  drawForm();
  drawSitePanel();
  drawPapers();
}

async function loadComments() {
  state.comments = (await get('/comments')).comments || [];
  drawComments();
  draw();
}

async function loadParcels() {
  const origin = state.snapshot?.site?.plan?.origin;
  if (!origin) return;
  try {
    const got = await get('/parcels');
    state.parcelShapes = got.parcels || [];
    state.parcels = state.parcelShapes.flatMap((p) => localRings(p.shape, origin));
  } catch { state.parcels = []; state.parcelShapes = []; }
  drawLots();
  draw();
}

async function send(event) {
  event.preventDefault();
  if (state.sending) return;
  const name = $('who').value;
  const text = $('text').value;
  const problem = commentProblem({ name, text });
  $('form-error').textContent = problem;
  if (problem) { (name.trim() ? $('text') : $('who')).focus(); return; }
  const body = replyTo ? { name: name.trim(), text: text.trim(), parent: replyTo }
    : { name: name.trim(), text: text.trim(), version: state.version, target: state.spot?.target || state.scheme || '', ...(state.spot ? { at: state.spot.at } : {}) };
  state.sending = true;
  const button = $('comment-form').querySelector('[type="submit"]');
  button.disabled = true;
  try {
    const r = await fetch(`${base}/comments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (!r.ok) {
      let detail = '';
      try { detail = (await r.json()).detail; } catch { /* no body */ }
      throw new Error(r.status === 429 ? '잠시 뒤에 다시 남겨 주세요. 1분에 남길 수 있는 댓글 수를 넘었습니다.'
        : r.status === 403 ? '설계자가 새 댓글을 닫았습니다.' : `댓글을 남기지 못했습니다. ${typeof detail === 'string' ? detail : ''}`.trim());
    }
    $('text').value = '';
    state.spot = null;
    replyTo = '';
    await loadComments();
    drawForm();
    hint('댓글을 남겼습니다. 설계자의 Sida에 전달됩니다.');
    setTimeout(() => hint(''), 3000);
  } catch (error) {
    $('form-error').textContent = error.message;
  } finally {
    state.sending = false;
    button.disabled = false;
  }
}

function wire() {
  $('schemes').addEventListener('click', (e) => {
    const b = e.target.closest('[data-scheme]');
    if (!b) return;
    state.scheme = b.dataset.scheme;
    drawSchemes();
    drawMasses();
    drawForm();
    if (state.around) askAround('setMasses', aroundScene(state.snapshot, state.scheme)?.polygons || []);
  });
  $('version').addEventListener('change', async (e) => {
    state.spot = null;
    await loadVersion(Number(e.target.value));
    await loadParcels();
    if (state.around) await showAround(true);
  });
  $('place').addEventListener('click', () => { replyTo = ''; setPlacing(!state.placing); drawForm(); });
  $('home').addEventListener('click', () => (state.around ? showAround(true) : goHome()));
  $('around-toggle').addEventListener('click', () => showAround(!state.around));
  window.addEventListener('message', onAroundMessage);
  for (const tab of ['comments', 'site', 'papers']) $(`tab-${tab}`).addEventListener('click', () => showTab(tab));
  $('comment-form').addEventListener('submit', send);
  $('who').addEventListener('input', () => { $('form-error').textContent = ''; });
  $('text').addEventListener('input', () => { $('form-error').textContent = ''; });
  $('spot').addEventListener('click', (e) => {
    const b = e.target.closest('[data-clear]');
    if (!b) return;
    if (b.dataset.clear === 'reply') replyTo = '';
    else state.spot = null;
    drawForm();
    draw();
  });
  $('comments').addEventListener('click', (e) => {
    const reply = e.target.closest('[data-reply]');
    if (reply) {
      replyTo = reply.dataset.reply;
      state.spot = null;
      setPlacing(false);
      drawForm();
      $('text').focus();
      return;
    }
    const item = e.target.closest('[data-comment]');
    const c = item && state.comments.find((x) => x.id === item.dataset.comment);
    if (c?.at) focusComment(c);
  });
  $('pins').addEventListener('click', (e) => {
    const pin = e.target.closest('[data-pin]');
    if (!pin || pin.dataset.pin === 'new') return;
    showTab('comments');
    const item = $('comments').querySelector(`[data-comment="${CSS.escape(pin.dataset.pin)}"]`);
    item?.scrollIntoView({ block: 'center', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });
    item?.classList.add('flash');
    setTimeout(() => item?.classList.remove('flash'), 1500);
  });
  window.addEventListener('keydown', (e) => { if (e.key === 'Escape' && state.placing) setPlacing(false); });
}

// A comment picked in the list: its scheme shows and the view turns to its spot.
function focusComment(c) {
  const paper = targetPaper(c.target);
  if (paper && viewerSchemes(state.snapshot).some((s) => s.id === paper) && paper !== state.scheme) {
    state.scheme = paper;
    drawSchemes();
    drawMasses();
  }
  state.view = { ...state.view, x: c.at.x, y: c.at.y, z: Math.min(c.at.z || 0, 60) };
  draw();
}

async function start() {
  setupScene();
  wire();
  try {
    state.info = await get('/info');
  } catch (error) {
    $('title').textContent = error.status === 404 ? '이 공유는 닫혔거나 링크가 바뀌었습니다' : '공유를 열지 못했습니다';
    $('byline').textContent = error.status === 404 ? '설계자에게 새 링크를 받아 주세요.' : error.message;
    document.body.classList.add('gone');
    return;
  }
  await loadVersion(state.info.latest);
  goHome();
  await Promise.all([loadComments(), loadParcels()]);
}

start();

