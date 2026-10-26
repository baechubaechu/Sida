// The drafting table (제도판): the site at real scale in the middle of a table, sheets of paper
// around it, and tilting the table turns the plan into an axonometric and then a perspective.
// Masses rise as the table leans, and the papers fold into pins so the model can be read
// (a pin opens its paper as a card). A tracing sheet laid on the site snaps into register; dragged
// aside it becomes a sheet of its own. What the AI made waits in the AI section beside the table.
//
// This file only draws and takes input. Saving goes through the callbacks app.js gives (which
// call the JSON API, docs/board-api.md), and figures come from the server. The table keeps its
// own element, which app.js lays over a slot in the page, so redraws of the page leave it be.
import * as THREE from './vendor/three.js';
import { escapeHtml as escape } from './model.js';
import {
  PX, TILT, MAX_TILT, PAPER_SIZE, cameraFor, riseFor, zoomAround, drawingScale, lerpView,
  siteBounds, traceHome, isOverlaid, blockCorners, placeUnplaced, freeSpot, fitView,
  folded, pinnedPapers, peekSpot,
  paperName, KIND_LABELS, originLabel, figureLines, readScheme, schemeRows, toggleSelected, fmt,
} from './board-model.js';

const SNAP = 7; // metres: a tracing sheet this close to its place on the site clicks into register
const typing = (el) => el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.isContentEditable);
const TOOLS = [
  { id: 'select', label: '선택', key: 'v', icon: '↖' },
  { id: 'note', label: '메모', key: 'n', icon: '▤' },
  { id: 'pen', label: '펜', key: 'p', icon: '✎' },
];
const cm = (metres) => Math.round(metres * 100) / 100; // pen points are kept to the centimetre
const strokePath = (pts) => pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)} ${(-y).toFixed(2)}`).join(' ');

export class DraftingTable {
  // hooks: { add(paper), update(id, changes), remove(id), place(id, placement), discard(id),
  //          select(ids), openExpert(agent), experts() } — the first five return promises.
  constructor(hooks) {
    this.hooks = hooks;
    this.papers = [];
    this.tray = [];
    this.site = null;
    this.figures = {};
    this.bounds = siteBounds(null);
    this.home = traceHome(this.bounds);
    this.view = { x: 0, y: 0, span: 160, tilt: 0, turn: 0 };
    this.tool = 'select';
    this.selected = [];
    this.active = '';
    this.ghost = false;
    this.preview = '';
    this.editing = '';
    this.peekId = ''; // the paper whose card is open from its pin in 3D
    this.trayOpen = false;
    this.form = null;
    this.gesture = null;
    this.pending = null;
    this.fitted = false;
    this.tween = 0;
    this.frame = 0;
    this.slots = new Map();
    this.drawn = new Map(); // paper id → what its element last showed
    this.pins = new Map(); // paper id → its pin element (3D)
    this.toldFold = false;
    this.root = document.createElement('div');
    this.root.className = 'table';
    this.root.tabIndex = 0;
    this.root.setAttribute('role', 'application');
    this.root.setAttribute('aria-label', '제도판');
    this.root.innerHTML = `<div class="table-stage"></div>
      <div class="table-pins" role="group" aria-label="종이 이름표"></div>
      <div class="table-ui ui-tools" role="toolbar" aria-label="제도판 도구"></div>
      <div class="table-ui ui-scheme"></div>
      <div class="table-ui ui-tilt" aria-label="기울기"></div>
      <div class="table-ui ui-zoom"></div>
      <p class="table-ui ui-help">끌기: 책상 이동 · Ctrl+휠: 확대 · 우클릭(Alt)+끌기: 돌리고 기울이기 · 1 평면 2 액소 3 투시 · Shift+클릭: 여러 장 골라 대화에 보내기</p>
      <p class="table-ui ui-hint" role="status" hidden></p>
      <aside class="table-ui tray" aria-label="AI 섹션"></aside>
      <section class="table-ui peek" aria-label="종이 내용" hidden></section>
      <section class="table-ui scheme-form" aria-label="매스안 입력" hidden></section>`;
    this.stage = this.root.querySelector('.table-stage');
    this.pinLayer = this.root.querySelector('.table-pins');
    this.ui = {
      tools: this.root.querySelector('.ui-tools'),
      scheme: this.root.querySelector('.ui-scheme'),
      tilt: this.root.querySelector('.ui-tilt'),
      zoom: this.root.querySelector('.ui-zoom'),
      hint: this.root.querySelector('.ui-hint'),
      tray: this.root.querySelector('.tray'),
      form: this.root.querySelector('.scheme-form'),
      peek: this.root.querySelector('.peek'),
    };
    this.setupScene();
    this.listen();
    this.drawControls();
  }

  // ------------------------------------------------------------------ mounting

  destroy() {
    cancelAnimationFrame(this.frame);
    this.observer?.disconnect();
    this.gl?.renderer.dispose();
    this.root.remove();
  }

  // ------------------------------------------------------------------ data from the server

  setBoard(view) {
    if (this.gesture) { this.pending = view; return; }
    this.site = view.site || null;
    this.figures = view.figures || {};
    this.tray = view.tray || [];
    this.papers = (view.papers || []).map((p) => ({ ...p }));
    const bounds = siteBounds(this.site);
    const moved = JSON.stringify(bounds) !== JSON.stringify(this.bounds);
    this.bounds = bounds;
    this.home = traceHome(bounds);
    // New papers sit at 0, 0 until placed: put them beside the site and save where.
    for (const spot of placeUnplaced(this.papers, this.bounds)) {
      const paper = this.papers.find((p) => p.id === spot.id);
      Object.assign(paper, { x: spot.x, y: spot.y });
      this.save(paper.id, { x: spot.x, y: spot.y });
    }
    const masses = this.papers.filter((p) => p.kind === 'mass');
    if (!masses.some((p) => p.id === this.active)) this.active = masses[0]?.id || '';
    if (this.preview && !this.tray.some((p) => p.id === this.preview)) this.preview = '';
    this.selected = this.selected.filter((id) => this.find(id));
    if (this.peekId && !this.papers.some((p) => p.id === this.peekId)) this.peekId = '';
    if (moved || !this.lotDrawn) this.drawSite();
    this.syncPapers();
    this.drawMasses();
    this.drawTray();
    this.drawControls();
    if (!this.fitted && this.root.clientWidth) { this.fitted = true; this.fit(false); }
    this.invalidate();
  }

  setSelected(ids) {
    this.selected = ids.filter((id) => this.find(id));
    this.syncPapers();
    this.drawTray();
    this.drawControls();
  }

  openTray() {
    this.trayOpen = true;
    this.drawTray();
    this.drawControls();
  }

  find(id) {
    return this.papers.find((p) => p.id === id) || this.tray.find((p) => p.id === id) || null;
  }

  // ------------------------------------------------------------------ scene

  setupScene() {
    const css = getComputedStyle(document.documentElement);
    const color = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
    this.colors = {
      table: color('--table', '#e9ecee'), line: color('--table-grid', '#d9dfe4'), lot: color('--lot', '#cf3f2e'),
      mass: color('--mass', '#e8ebee'), ink: color('--text', '#20262d'), pen: color('--pen', '#2b5d8a'),
      ghost: color('--brand', '#36536b'),
    };
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true });
    } catch {
      this.stage.innerHTML = '<p class="table-error">이 브라우저에서는 제도판의 3D 화면을 그릴 수 없습니다. 하드웨어 가속을 켜거나 다른 브라우저로 열어 주세요.</p>';
      this.gl = null;
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.domElement.className = 'table-gl';
    this.stage.append(renderer.domElement);
    const cssRenderer = new THREE.CSS3DRenderer();
    cssRenderer.domElement.className = 'table-css';
    this.stage.append(cssRenderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(this.colors.table);
    const cssScene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(30, 1, 1, 50000);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa3ad, 1.5));
    const sun = new THREE.DirectionalLight(0xffffff, 1.6);
    sun.position.set(-90, -160, 140); // a low southern sun throws shadows to the north
    sun.castShadow = true;
    sun.shadow.mapSize.set(2048, 2048);
    sun.shadow.bias = -0.0004;
    sun.shadow.normalBias = 0.3;
    Object.assign(sun.shadow.camera, { left: -160, right: 160, top: 160, bottom: -160, near: 10, far: 600 });
    scene.add(sun, sun.target);
    // The table keeps its own colour; a separate catcher only darkens where shadows fall.
    scene.add(new THREE.Mesh(new THREE.PlaneGeometry(6000, 6000), new THREE.MeshBasicMaterial({ color: this.colors.table })));
    const catcher = new THREE.Mesh(new THREE.PlaneGeometry(1200, 1200), new THREE.ShadowMaterial({ opacity: 0.22 }));
    catcher.position.z = 0.01;
    catcher.receiveShadow = true;
    scene.add(catcher);
    const grid = new THREE.GridHelper(2000, 200, this.colors.line, this.colors.line);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = 0.02;
    scene.add(grid);
    const lot = new THREE.Group();
    const masses = new THREE.Group();
    const traces = new THREE.Group();
    scene.add(lot, masses, traces);
    this.gl = { renderer, cssRenderer, scene, cssScene, camera, lot, masses, traces, labels: [], objects: new Map(), raycaster: new THREE.Raycaster() };
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(this.root);
  }

  resize() {
    if (!this.gl) return;
    const w = this.root.clientWidth;
    const h = this.root.clientHeight;
    if (!w || !h || (w === this.size?.w && h === this.size?.h)) return;
    this.size = { w, h };
    this.gl.renderer.setSize(w, h);
    this.gl.cssRenderer.setSize(w, h);
    this.gl.camera.aspect = w / h;
    if (!this.fitted && this.papers.length) { this.fitted = true; this.fit(false); }
    this.drawControls();
    this.invalidate();
  }

  invalidate() {
    if (this.frame || !this.gl) return;
    this.frame = requestAnimationFrame(() => { this.frame = 0; this.render(); });
  }

  aimCamera(camera, v) {
    const c = cameraFor(v);
    camera.fov = c.fov;
    camera.near = c.dist * 0.05;
    camera.far = c.dist * 20;
    camera.position.set(...c.position);
    camera.up.set(...c.up);
    camera.lookAt(...c.target);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld();
  }

  render() {
    if (!this.gl || !this.root.isConnected || !this.root.clientWidth) return;
    const { renderer, cssRenderer, scene, cssScene, camera, masses, traces, labels, objects } = this.gl;
    const v = this.view;
    this.aimCamera(camera, v);
    const rise = riseFor(v.tilt);
    masses.scale.z = rise;
    for (const l of labels) l.element.style.opacity = rise < 0.25 ? String(1 - rise * 4) : '0';
    // In plan the papers lie on the table. Once it leans they fold into pins (drawn over the
    // scene, upright), and an overlaid tracing's lines lie on the ground.
    const fold = folded(v.tilt);
    traces.visible = fold;
    for (const obj of objects.values()) obj.visible = !fold;
    if (fold !== this.root.classList.contains('is-3d')) this.foldChanged(fold);
    renderer.render(scene, camera);
    cssRenderer.render(cssScene, camera);
    if (fold) this.placePins();
  }

  foldChanged(fold) {
    this.root.classList.toggle('is-3d', fold);
    if (!fold && this.peekId) { this.peekId = ''; this.drawPeek(); }
    if (fold && !this.toldFold && this.pins.size) {
      this.toldFold = true;
      this.say('3D에서는 종이가 이름표로 접힙니다. 이름표를 누르면 내용이 열립니다.');
    }
  }

  // Each pin stands where its paper lies; the open card follows its pin.
  placePins() {
    const { camera } = this.gl;
    const w = this.size?.w || this.root.clientWidth;
    const h = this.size?.h || this.root.clientHeight;
    const at = new THREE.Vector3();
    let anchor = null;
    for (const [id, el] of this.pins) {
      const p = this.papers.find((x) => x.id === id);
      if (!p) continue;
      at.set(p.x, p.y, 0.1).project(camera);
      const x = ((at.x + 1) / 2) * w;
      const y = ((1 - at.y) / 2) * h;
      const shown = at.z < 1 && x > -40 && x < w + 40 && y > -20 && y < h + 60;
      el.hidden = !shown;
      if (shown) el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, calc(-100% - 8px))`;
      if (id === this.peekId && shown) anchor = { x, y: y - 8 - el.offsetHeight / 2, w: el.offsetWidth };
    }
    const card = this.ui.peek;
    if (!this.peekId || card.hidden) return;
    if (!anchor) { card.style.visibility = 'hidden'; return; }
    // Keep clear of the view panel on the right and the toolbars at the top and bottom.
    const box = { left: (this.trayOpen ? this.ui.tray.offsetWidth : 0) + 12, top: 12, right: w - (this.ui.tilt.offsetWidth || 0) - 24, bottom: h - 64 };
    const spot = peekSpot(anchor, { w: card.offsetWidth, h: card.offsetHeight }, box);
    card.style.visibility = '';
    card.style.transform = `translate(${spot.x.toFixed(1)}px, ${spot.y.toFixed(1)}px)`;
  }

  drawSite() {
    if (!this.gl) return;
    const { lot } = this.gl;
    lot.clear();
    this.lotDrawn = true;
    const color = new THREE.Color(this.colors.lot);
    for (const parcel of this.site?.plan?.parcels || []) {
      for (const ring of parcel.rings) {
        const shape = new THREE.Shape(ring.map(([x, y]) => new THREE.Vector2(x, y)));
        const fill = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.08, depthWrite: false }));
        fill.position.z = 0.04;
        lot.add(fill);
        const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(ring.map(([x, y]) => new THREE.Vector3(x, y, 0.08))),
          new THREE.LineDashedMaterial({ color, dashSize: 2.4, gapSize: 1.2 }));
        line.computeLineDistances();
        lot.add(line);
      }
    }
  }

  // The active scheme stands solid; the others (and an AI scheme being previewed) as outlines.
  drawMasses() {
    if (!this.gl) return;
    const g = this.gl;
    g.masses.clear();
    for (const l of g.labels.splice(0)) g.cssScene.remove(l);
    const frame = this.site?.plan?.frame || { x: 0, y: 0, angle: 0 };
    g.masses.position.set(frame.x, frame.y, 0);
    g.masses.rotation.z = frame.angle;
    const ink = new THREE.Color(this.colors.ink);
    const build = (paper, faint, tint) => {
      for (const b of paper.blocks || []) {
        const h = b.floors * (paper.floor_height || 4.2);
        const geom = new THREE.BoxGeometry(b.w, b.d, h);
        if (!faint) {
          const box = new THREE.Mesh(geom, new THREE.MeshLambertMaterial({ color: this.colors.mass }));
          box.position.set(b.u, b.v, h / 2);
          box.castShadow = true;
          g.masses.add(box);
        }
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom),
          new THREE.LineBasicMaterial({ color: tint || ink, transparent: faint, opacity: faint ? (tint ? 0.9 : 0.35) : 1 }));
        edges.position.set(b.u, b.v, h / 2 + 0.05);
        g.masses.add(edges);
        if (!faint) {
          const tag = document.createElement('div');
          tag.className = 'floor-tag';
          tag.textContent = `${b.floors}F`;
          const obj = new THREE.CSS3DObject(tag);
          const [cx, cy] = blockCorners(frame, { ...b, w: 0, d: 0 })[0];
          obj.position.set(cx, cy, 0.2);
          obj.scale.setScalar(PX);
          g.cssScene.add(obj);
          g.labels.push(obj);
        }
      }
    };
    const active = this.papers.find((p) => p.id === this.active);
    if (active) build(active, false);
    if (this.ghost) for (const p of this.papers) if (p.kind === 'mass' && p.id !== this.active) build(p, true);
    const preview = this.tray.find((p) => p.id === this.preview);
    if (preview) build(preview, true, new THREE.Color(this.colors.ghost));
    this.invalidate();
  }

  // ------------------------------------------------------------------ papers

  slot(id) {
    if (!this.slots.has(id)) {
      const el = document.createElement('div');
      el.className = 'slot';
      this.slots.set(id, el);
    }
    return this.slots.get(id);
  }

  syncPapers() {
    if (!this.gl) return;
    const g = this.gl;
    const want = new Map(this.papers.map((p) => [p.id, p]));
    for (const [id, obj] of g.objects) {
      if (!want.has(id)) { g.cssScene.remove(obj); g.objects.delete(id); this.slots.delete(id); this.drawn.delete(id); }
    }
    for (const [id, p] of want) {
      let obj = g.objects.get(id);
      if (!obj) {
        obj = new THREE.CSS3DObject(this.slot(id));
        obj.scale.setScalar(PX);
        g.cssScene.add(obj);
        g.objects.set(id, obj);
      }
      obj.position.set(p.x, p.y, p.kind === 'tracing' ? 0.3 : 0.1);
      this.drawPaper(p);
    }
    g.traces.clear();
    const mat = new THREE.LineBasicMaterial({ color: this.colors.pen });
    for (const p of this.papers) {
      if (!isOverlaid(p, this.home)) continue;
      for (const s of p.strokes || []) {
        g.traces.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(s.map(([x, y]) => new THREE.Vector3(x, y, 0.15))), mat));
      }
    }
    this.drawPins();
    this.drawPeek();
    this.invalidate();
  }

  drawPaper(p) {
    const overlaid = isOverlaid(p, this.home);
    const state = {
      p: { ...p, x: 0, y: 0 }, sel: this.selected.includes(p.id), overlaid, editing: this.editing === p.id,
      active: this.active === p.id, f: this.figures[p.id], site: p.kind === 'site' ? this.site : null,
    };
    const key = JSON.stringify(state);
    if (this.drawn.get(p.id) === key) return;
    this.drawn.set(p.id, key);
    const el = this.slot(p.id);
    const cls = `paper kind-${p.kind} ${state.sel ? 'is-selected' : ''} ${overlaid ? 'is-overlaid' : ''} ${state.active ? 'is-active' : ''}`;
    const size = `width:${p.w}px;height:${p.h}px`;
    const made = originLabel(p, this.hooks.experts());
    const madeTag = made ? `<span class="paper-made">${escape(made)}</span>` : '';
    if (p.kind === 'note') {
      el.innerHTML = `<article class="${cls}" data-paper="${escape(p.id)}" style="${size}">${madeTag}
        ${state.editing
    ? `<textarea aria-label="메모 내용" maxlength="4000">${escape(p.text || '')}</textarea>`
    : `<p>${escape(p.text || '메모')}</p>`}</article>`;
      if (state.editing) {
        const area = el.querySelector('textarea');
        requestAnimationFrame(() => { area.focus(); area.select(); });
      }
      return;
    }
    if (p.kind === 'tracing') {
      el.innerHTML = `<article class="${cls}" data-paper="${escape(p.id)}" style="width:${this.home.w}px;height:${this.home.h}px">
        ${this.traceSvg(p)}<span class="paper-tag">${escape(paperName(p))}${overlaid ? ' · 덮음' : ''}</span></article>`;
      return;
    }
    const { title, body } = this.paperContent(p, state.active, state.f);
    el.innerHTML = `<article class="${cls}" data-paper="${escape(p.id)}" style="${size}">
      <header class="paper-head"><span class="paper-kind">${escape(KIND_LABELS[p.kind] || p.kind)}</span>${madeTag}<h3>${escape(title)}</h3></header>
      <div class="paper-body">${body}</div></article>`;
  }

  // What a site, mass or expert paper says: the same on the table and in its card in 3D.
  paperContent(p, active, f, card = false) {
    if (p.kind === 'site') {
      const lines = this.site?.lines || [];
      return {
        title: '대지 사실',
        body: lines.length
          ? `<ul class="facts">${lines.map((l) => `<li>${escape(l)}</li>`).join('')}</ul>
            <p class="source">정부 자료(대지 사실)${this.site?.plan ? '' : ' · 필지 경계 미확인'}</p>`
          : '<p class="muted">대지 사실이 아직 없습니다. 대지 주소를 조회하면 필지 경계와 면적이 여기에 나옵니다.</p>',
      };
    }
    if (p.kind === 'mass') {
      const blocks = (p.blocks || []).map((b) => `${fmt(b.w, 1)}×${fmt(b.d, 1)}m ${b.floors}층`).join(' + ');
      return {
        title: paperName(p),
        body: `<p class="blocks">${escape(blocks)}</p>
          ${figureLines(f).map((l) => `<p class="figure">${escape(l)}</p>`).join('')}
          ${card ? '' : `<p class="source">${active ? '3D로 보는 안' : '누르면 3D로 봅니다'} · 두 번 누르면 고칩니다</p>`}`,
      };
    }
    if (p.kind === 'expert') {
      return {
        title: paperName(p),
        body: `<pre class="preview">${escape(p.text || '')}</pre>
          <button type="button" class="paper-link" data-open-expert="${escape(p.agent || '')}">결과 문서 보기 ↗</button>`,
      };
    }
    return { title: paperName(p), body: '' };
  }

  traceSvg(p) {
    const b = this.bounds;
    const m = (this.home.w * PX - (b.maxX - b.minX)) / 2;
    const marks = [[b.minX, b.minY], [b.maxX, b.minY], [b.minX, b.maxY], [b.maxX, b.maxY]]
      .map(([x, y]) => `<path class="reg" d="M${x - 3} ${-y} H${x + 3} M${x} ${-y - 3} V${-y + 3}"/>`).join('');
    return `<svg viewBox="${b.minX - m} ${-(b.maxY + m)} ${b.maxX - b.minX + m * 2} ${b.maxY - b.minY + m * 2}" aria-hidden="true">${marks}
      ${(p.strokes || []).map((s) => `<path class="trace" d="${strokePath(s)}"/>`).join('')}<path class="trace draft" d=""/></svg>`;
  }

  // ------------------------------------------------------------------ pins and cards (3D)

  // Pins are rebuilt only when papers come or go; selection and the open card just restyle
  // them, so a pin keeps keyboard focus.
  drawPins() {
    const want = pinnedPapers(this.papers, this.home);
    const key = JSON.stringify(want.map((p) => [p.id, paperName(p), p.kind]));
    if (key !== this.pinKey) {
      this.pinKey = key;
      this.pins.clear();
      this.pinLayer.innerHTML = want.map((p) => `<button type="button" class="pin kind-${p.kind}" data-pin="${escape(p.id)}"
        aria-label="${escape(paperName(p))} 열기" title="Shift+클릭: 대화에 보낼 종이로 고르기" hidden>
        <span class="pin-kind">${escape(KIND_LABELS[p.kind] || p.kind)}</span><span class="pin-name">${escape(paperName(p))}</span><b hidden>3D</b></button>`).join('');
      for (const el of this.pinLayer.querySelectorAll('[data-pin]')) this.pins.set(el.dataset.pin, el);
    }
    for (const [id, el] of this.pins) {
      const active = this.active === id && el.classList.contains('kind-mass');
      el.classList.toggle('is-selected', this.selected.includes(id));
      el.classList.toggle('is-active', active);
      el.querySelector('b').hidden = !active;
      el.setAttribute('aria-pressed', String(this.peekId === id));
    }
    this.invalidate();
  }

  drawPeek() {
    const card = this.ui.peek;
    const p = this.papers.find((x) => x.id === this.peekId);
    if (!p) { card.hidden = true; card.innerHTML = ''; return; }
    const id = escape(p.id);
    const picked = this.selected.includes(p.id);
    const made = originLabel(p, this.hooks.experts());
    let body;
    if (p.kind === 'note') body = `<p class="note-text">${escape(p.text || '메모')}</p>`;
    else if (p.kind === 'tracing') body = `<div class="peek-trace">${this.traceSvg(p)}</div><p class="source">획 ${(p.strokes || []).length}개 · 대지에서 떼어 둔 종이</p>`;
    else body = this.paperContent(p, this.active === p.id, this.figures[p.id], true).body;
    const actions = [
      p.kind === 'mass' && this.active !== p.id ? `<button type="button" data-peek="show" data-id="${id}">3D로 세우기</button>` : '',
      p.kind === 'mass' ? `<button type="button" data-peek="edit" data-id="${id}">고치기</button>` : '',
      p.kind === 'note' ? `<button type="button" data-peek="write" data-id="${id}">평면에서 고치기</button>` : '',
      `<button type="button" data-peek="pick" data-id="${id}" aria-pressed="${picked}">${picked ? '대화에 보냄' : '대화에 보내기'}</button>`,
      `<button type="button" data-peek="plan" data-id="${id}">평면에서 보기</button>`,
    ].join('');
    card.className = `table-ui peek kind-${p.kind}`;
    card.innerHTML = `<header><p class="tray-meta">${escape(KIND_LABELS[p.kind] || p.kind)}${made ? ` · ${escape(made)}` : ''}</p>
        <button type="button" class="tray-close" data-peek="close" aria-label="닫기">×</button></header>
      <h4>${escape(paperName(p))}</h4>
      <div class="peek-body">${body}</div>
      <div class="tray-actions">${actions}</div>`;
    card.hidden = false;
    card.style.visibility = 'hidden'; // placed beside its pin on the next frame
    this.invalidate();
  }

  openPeek(id) {
    this.peekId = this.peekId === id ? '' : id;
    const p = this.papers.find((x) => x.id === id);
    if (this.peekId && p?.kind === 'mass' && this.active !== id) this.showScheme(id);
    else { this.drawPins(); this.drawPeek(); }
  }

  // Back to the plan, centred on a paper.
  planAt(p, then) {
    this.peekId = '';
    this.drawPeek();
    this.animateTo({ x: p.x, y: p.y, tilt: 0, turn: 0, span: Math.max(60, Math.min(this.view.span, 160)) });
    if (then) setTimeout(then, 480);
  }

  // ------------------------------------------------------------------ the AI section

  drawTray() {
    const t = this.ui.tray;
    t.classList.toggle('open', this.trayOpen);
    this.root.classList.toggle('tray-open', this.trayOpen);
    if (!this.trayOpen) { t.innerHTML = ''; return; }
    const experts = this.hooks.experts();
    const named = (id) => { const p = this.papers.find((x) => x.id === id) || this.tray.find((x) => x.id === id); return p ? paperName(p) : id; };
    const cards = [...this.tray].reverse().map((p) => {
      const id = escape(p.id);
      const picked = this.selected.includes(p.id);
      let body = '';
      if (p.kind === 'mass') {
        body = `<p class="blocks">${escape((p.blocks || []).map((b) => `${fmt(b.w, 1)}×${fmt(b.d, 1)}m ${b.floors}층`).join(' + '))}</p>
          ${figureLines(this.figures[p.id]).map((l) => `<p class="figure">${escape(l)}</p>`).join('')}`;
      } else if (p.kind === 'note') {
        body = `<p class="note-text">${escape(p.text || '')}</p>`;
      } else if (p.kind === 'expert') {
        body = `<pre class="preview">${escape((p.text || '').split('\n').slice(0, 5).join('\n'))}</pre>`;
      }
      return `<article class="tray-card kind-${p.kind} ${picked ? 'is-selected' : ''}" data-tray="${id}">
        <p class="tray-meta">${escape(originLabel(p, experts) || 'AI')} · ${escape(KIND_LABELS[p.kind] || p.kind)}</p>
        <h4>${escape(paperName(p))}</h4>
        ${p.based_on ? `<p class="tray-why">${escape(named(p.based_on))}의 수정안</p>` : ''}
        ${p.reason ? `<p class="tray-why">${escape(p.reason)}</p>` : ''}
        ${body}
        <div class="tray-actions">
          <button type="button" class="tray-place" data-tray-action="place" data-id="${id}">제도판에 놓기</button>
          ${p.kind === 'mass' ? `<button type="button" data-tray-action="preview" data-id="${id}" aria-pressed="${this.preview === p.id}">3D 미리 보기</button>` : ''}
          ${p.kind === 'expert' ? `<button type="button" data-open-expert="${escape(p.agent || '')}">결과 문서</button>` : ''}
          <button type="button" data-tray-action="pick" data-id="${id}" aria-pressed="${picked}">${picked ? '대화에 보냄' : '대화에 보내기'}</button>
          <button type="button" class="tray-discard" data-tray-action="discard" data-id="${id}" aria-label="${escape(paperName(p))} 버리기">버리기</button>
        </div></article>`;
    }).join('');
    t.innerHTML = `<header><h3>AI 섹션</h3><button type="button" class="tray-close" data-ui="tray" aria-label="AI 섹션 닫기">×</button></header>
      <p class="tray-intro">Conductor와 전문가가 만든 종이입니다. 마음에 드는 것만 제도판에 놓으세요.</p>
      ${cards || '<p class="tray-empty">아직 없습니다. Conductor에게 매스안이나 메모를 부탁하거나 전문가를 실행하면 여기에 놓입니다.</p>'}`;
  }

  async placeFromTray(id) {
    const p = this.tray.find((x) => x.id === id);
    if (!p) return;
    const [w, h] = PAPER_SIZE[p.kind] || [p.w, p.h];
    const spot = freeSpot(this.papers, this.bounds, w, h);
    if (this.preview === id) this.preview = '';
    const done = await this.hooks.place(id, { ...spot, w, h });
    if (!done) return;
    if (p.kind === 'mass') this.showScheme(id);
    this.say(`${paperName(p)}을(를) 제도판에 놓았습니다.`);
    this.animateTo({ x: spot.x, y: spot.y, span: Math.max(this.view.span, 120), tilt: 0, turn: 0 });
  }

  // ------------------------------------------------------------------ the scheme form

  openForm(paper = null) {
    this.form = { id: paper?.id || '', title: paper?.title || '', floorHeight: String(paper?.floor_height ?? 4.2), rows: schemeRows(paper), error: '' };
    this.drawForm();
  }

  drawForm() {
    const f = this.form;
    const el = this.ui.form;
    el.hidden = !f;
    if (!f) { el.innerHTML = ''; return; }
    const cell = (i, key, label) => `<td><input inputmode="decimal" aria-label="${i + 1}동 ${label}" data-row="${i}" data-key="${key}" value="${escape(f.rows[i][key])}"></td>`;
    el.innerHTML = `<form data-form="scheme">
      <header><h3>${f.id ? '매스안 고치기' : '새 매스안'}</h3><button type="button" class="tray-close" data-ui="form-close" aria-label="닫기">×</button></header>
      <label>이름 <input data-key="title" maxlength="120" placeholder="예: 안 A · 판상형" value="${escape(f.title)}"></label>
      <label>층고(m) <input data-key="floorHeight" inputmode="decimal" value="${escape(f.floorHeight)}"></label>
      <table><thead><tr><th>동</th><th>가로 m</th><th>세로 m</th><th>층수</th><th>u m</th><th>v m</th><th></th></tr></thead>
      <tbody>${f.rows.map((_, i) => `<tr><th>${i + 1}</th>${cell(i, 'w', '가로')}${cell(i, 'd', '세로')}${cell(i, 'floors', '층수')}${cell(i, 'u', 'u')}${cell(i, 'v', 'v')}
        <td><button type="button" data-ui="row-remove" data-row="${i}" aria-label="${i + 1}동 빼기" ${f.rows.length < 2 ? 'disabled' : ''}>−</button></td></tr>`).join('')}</tbody></table>
      <button type="button" class="row-add" data-ui="row-add">＋ 동 추가</button>
      <p class="form-hint">u는 대지의 긴 변을 따라, v는 그와 직각으로, 큰 필지 가운데에서 잰 동 중심 위치입니다. 건폐율·용적률은 저장하면 서버가 계산합니다.</p>
      <p class="form-error" role="alert">${escape(f.error)}</p>
      <div class="form-buttons"><button type="button" data-ui="form-close">취소</button><button type="submit" class="primary-small">저장</button></div>
    </form>`;
  }

  async saveForm() {
    const f = this.form;
    const scheme = readScheme(f);
    if (scheme.error) { f.error = scheme.error; this.drawForm(); return; }
    let done;
    if (f.id) {
      done = await this.hooks.update(f.id, scheme);
    } else {
      const [w, h] = PAPER_SIZE.mass;
      const spot = freeSpot(this.papers, this.bounds, w, h);
      const paper = { kind: 'mass', ...scheme, w, h, ...spot };
      done = await this.hooks.add(paper);
      if (done?.paper) this.showScheme(done.paper.id);
    }
    if (!done) { f.error = '저장하지 못했습니다. 위 알림을 확인해 주세요.'; this.drawForm(); return; }
    this.form = null;
    this.drawForm();
    this.animateTo({ tilt: TILT.axo, turn: this.view.turn || -30 });
  }

  // ------------------------------------------------------------------ controls

  drawControls() {
    const v = this.view;
    const masses = this.papers.filter((p) => p.kind === 'mass');
    this.ui.tools.innerHTML = `${TOOLS.map((t) => `<button type="button" data-tool="${t.id}" aria-pressed="${this.tool === t.id}" title="${t.label} (${t.key.toUpperCase()})"><span aria-hidden="true">${t.icon}</span> ${t.label}</button>`).join('')}
      <span class="sep"></span>
      <button type="button" data-ui="scheme-new" title="숫자로 매스안 만들기">＋ 매스안</button>
      <button type="button" data-ui="trace" title="트레이싱지 덮기 (T)">트레이싱지 덮기</button>
      <button type="button" data-ui="delete" ${this.selected.some((id) => this.papers.some((p) => p.id === id && p.kind !== 'site')) ? '' : 'disabled'} title="삭제 (Delete)">삭제</button>
      <span class="sep"></span>
      <button type="button" data-ui="tray" aria-pressed="${this.trayOpen}">AI 섹션${this.tray.length ? ` <b>${this.tray.length}</b>` : ''}</button>`;
    this.ui.scheme.hidden = !masses.length;
    this.ui.scheme.innerHTML = masses.length ? `<div class="seg" role="group" aria-label="3D로 볼 매스안">
        ${masses.map((p) => `<button type="button" data-active="${escape(p.id)}" aria-pressed="${this.active === p.id}">${escape(paperName(p))}</button>`).join('')}</div>
      ${masses.length > 1 ? `<label class="check"><input type="checkbox" data-ui="ghost" ${this.ghost ? 'checked' : ''}> 다른 안 겹쳐 보기</label>` : ''}` : '';
    this.ui.tilt.innerHTML = `<div class="seg vertical" role="group" aria-label="보는 각도">
        ${[['plan', '평면', '1'], ['axo', '액소', '2'], ['eye', '투시', '3']].map(([id, label, k]) => `<button type="button" data-tilt="${id}" title="${label} (${k})" aria-pressed="${Math.abs(v.tilt - TILT[id]) < 4}">${label}</button>`).join('')}</div>
      <input type="range" min="0" max="${MAX_TILT}" value="${Math.round(v.tilt)}" aria-label="기울기 각도" data-ui="tilt-range">
      <span class="num tilt-read">${Math.round(v.tilt)}°</span>
      <button type="button" class="compass" data-ui="north" title="북쪽을 위로"><span style="transform: rotate(${-v.turn}deg)" aria-hidden="true">▲</span><small>N</small></button>`;
    this.ui.zoom.innerHTML = `<span class="num scale">${drawingScale(v.span, this.root.clientHeight || 600)}</span>
      <button type="button" data-ui="zoom-in" aria-label="확대">+</button>
      <button type="button" data-ui="zoom-out" aria-label="축소">−</button>
      <button type="button" data-ui="fit" title="전체 보기 (0)">맞춤</button>`;
  }

  // Cheap updates while the view moves (the full control redraw would steal the slider).
  updateReadouts() {
    const v = this.view;
    const read = this.ui.tilt.querySelector('.tilt-read');
    if (read) read.textContent = `${Math.round(v.tilt)}°`;
    const range = this.ui.tilt.querySelector('input[type="range"]');
    if (range && document.activeElement !== range) range.value = String(Math.round(v.tilt));
    const needle = this.ui.tilt.querySelector('.compass span');
    if (needle) needle.style.transform = `rotate(${-v.turn}deg)`;
    for (const b of this.ui.tilt.querySelectorAll('[data-tilt]')) b.setAttribute('aria-pressed', String(Math.abs(v.tilt - TILT[b.dataset.tilt]) < 4));
    const scale = this.ui.zoom.querySelector('.scale');
    if (scale) scale.textContent = drawingScale(v.span, this.root.clientHeight || 600);
  }

  setView(v) {
    this.view = v;
    this.updateReadouts();
    this.invalidate();
  }

  say(text) {
    const hint = this.ui.hint;
    hint.textContent = text;
    hint.hidden = !text;
    clearTimeout(this.hintTimer);
    this.hintTimer = setTimeout(() => { hint.hidden = true; }, 4000);
  }

  animateTo(target, ms = 450) {
    const from = this.view;
    const start = performance.now();
    const id = (this.tween += 1);
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const step = (now) => {
      if (id !== this.tween) return;
      const t = reduce ? 1 : Math.min(1, (now - start) / ms);
      this.setView(lerpView(from, { ...from, ...target }, 1 - (1 - t) ** 3));
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  fit(animate = true) {
    const r = this.root.getBoundingClientRect();
    const target = fitView(this.papers, this.bounds, r.width / Math.max(1, r.height));
    if (animate) this.animateTo(target);
    else this.setView(target);
  }

  // The table point under the pointer, for the view `v`.
  ground(clientX, clientY, v = this.view) {
    if (!this.gl) return null;
    const r = this.root.getBoundingClientRect();
    const cam = new THREE.PerspectiveCamera(30, r.width / Math.max(1, r.height), 1, 50000);
    this.aimCamera(cam, v);
    this.gl.raycaster.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), cam);
    const hit = new THREE.Vector3();
    return this.gl.raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), 0), hit) ? { x: hit.x, y: hit.y } : null;
  }

  // ------------------------------------------------------------------ edits

  save(id, changes) {
    return this.hooks.update(id, changes);
  }

  select(ids) {
    this.selected = ids;
    this.hooks.select(ids);
    this.syncPapers();
    this.drawTray();
    this.drawControls();
  }

  layTracing() {
    const covering = this.papers.find((p) => isOverlaid(p, this.home));
    if (covering) {
      this.select([covering.id]);
      this.setTool('pen');
      this.say(`${paperName(covering)}이(가) 이미 대지 위에 있습니다. 그 위에 그리세요.`);
      return;
    }
    const n = this.papers.filter((p) => p.kind === 'tracing').length + 1;
    const sheet = { kind: 'tracing', title: `트레이싱 ${n}`, strokes: [], overlaid: true, x: this.home.x, y: this.home.y, w: this.home.w, h: this.home.h };
    this.hooks.add(sheet).then((done) => {
      if (!done?.paper) return;
      this.select([done.paper.id]);
      this.setTool('pen');
      this.animateTo({ tilt: 0 });
      this.say('대지 위에 트레이싱지를 덮었습니다. 펜으로 그린 뒤 종이를 옆으로 끌어내면 떼어집니다.');
    });
  }

  removeSelected() {
    const ids = this.selected.filter((id) => this.papers.some((p) => p.id === id && p.kind !== 'site'));
    if (!ids.length) return;
    this.papers = this.papers.filter((p) => !ids.includes(p.id));
    this.select(this.selected.filter((id) => !ids.includes(id)));
    this.syncPapers();
    this.drawMasses();
    for (const id of ids) this.hooks.remove(id);
  }

  // The scheme that stands in 3D.
  showScheme(id) {
    this.active = id;
    this.drawMasses();
    this.drawControls();
    this.syncPapers();
  }

  setTool(tool) {
    this.tool = tool;
    if (tool === 'pen' && folded(this.view.tilt)) {
      this.animateTo({ tilt: 0, turn: 0 });
      this.say('펜은 평면에서 씁니다. 평면으로 돌아왔습니다.');
    }
    this.root.classList.toggle('tool-pen', tool === 'pen');
    this.root.classList.toggle('tool-note', tool === 'note');
    this.drawControls();
  }

  // ------------------------------------------------------------------ input

  listen() {
    const root = this.root;
    root.addEventListener('wheel', (e) => this.onWheel(e), { passive: false });
    // Focus on a pin at the edge must not scroll the table (older browsers without overflow: clip).
    root.addEventListener('scroll', () => { root.scrollLeft = 0; root.scrollTop = 0; });
    root.addEventListener('pointerdown', (e) => this.onDown(e));
    root.addEventListener('pointermove', (e) => this.onMove(e));
    root.addEventListener('pointerup', () => this.onUp());
    root.addEventListener('pointercancel', () => this.onUp());
    root.addEventListener('dblclick', (e) => this.onDouble(e));
    root.addEventListener('contextmenu', (e) => { if (!typing(e.target)) e.preventDefault(); });
    root.addEventListener('keydown', (e) => this.onKey(e));
    root.addEventListener('click', (e) => this.onClick(e));
    root.addEventListener('input', (e) => this.onInput(e));
    root.addEventListener('change', (e) => {
      if (e.target.dataset.ui === 'ghost') { this.ghost = e.target.checked; this.drawMasses(); }
    });
    root.addEventListener('submit', (e) => { e.preventDefault(); if (e.target.dataset.form === 'scheme') this.saveForm(); });
    root.addEventListener('focusout', (e) => {
      // A note being written is saved when it loses focus.
      if (e.target.tagName !== 'TEXTAREA' || !this.editing) return;
      const id = this.editing;
      const p = this.papers.find((x) => x.id === id);
      this.editing = '';
      if (p) { p.text = e.target.value; this.drawPaper(p); this.save(id, { text: p.text }); }
    });
  }

  onClick(e) {
    const t = e.target.closest('button, [data-open-expert]');
    if (!t) return;
    if (t.dataset.openExpert) { this.hooks.openExpert(t.dataset.openExpert); return; }
    if (t.dataset.tool) { this.setTool(t.dataset.tool); return; }
    if (t.dataset.active) { this.showScheme(t.dataset.active); return; }
    if (t.dataset.pin) {
      if (e.shiftKey) this.select(toggleSelected(this.selected, t.dataset.pin, true));
      else this.openPeek(t.dataset.pin);
      return;
    }
    if (t.dataset.peek) {
      this.peekAction(t.dataset.peek, t.dataset.id);
      // The card was redrawn under the pointer: keep the keys (Esc, 1–3) on the table.
      if (!this.root.contains(document.activeElement)) this.root.focus({ preventScroll: true });
      return;
    }
    if (t.dataset.tilt) { const id = t.dataset.tilt; this.animateTo({ tilt: TILT[id], turn: id === 'plan' ? 0 : (this.view.turn || -30) }); return; }
    const id = t.dataset.id;
    switch (t.dataset.trayAction) {
      case 'place': this.placeFromTray(id); return;
      case 'discard': if (this.preview === id) { this.preview = ''; this.drawMasses(); } this.hooks.discard(id); return;
      case 'preview': this.preview = this.preview === id ? '' : id; this.drawMasses(); this.drawTray(); if (this.preview && this.view.tilt < 20) this.animateTo({ tilt: TILT.axo, turn: this.view.turn || -30 }); return;
      case 'pick': this.select(toggleSelected(this.selected, id, true)); return;
      default: break;
    }
    switch (t.dataset.ui) {
      case 'scheme-new': this.openForm(); break;
      case 'trace': this.layTracing(); break;
      case 'delete': this.removeSelected(); break;
      case 'tray': this.trayOpen = !this.trayOpen; this.drawTray(); this.drawControls(); break;
      case 'north': this.animateTo({ turn: 0 }); break;
      case 'zoom-in': this.animateTo({ span: this.view.span / 1.4 }, 200); break;
      case 'zoom-out': this.animateTo({ span: this.view.span * 1.4 }, 200); break;
      case 'fit': this.fit(); break;
      case 'form-close': this.form = null; this.drawForm(); break;
      case 'row-add': if (this.form.rows.length < 20) { this.form.rows.push({ u: '0', v: '0', w: '20', d: '15', floors: '3' }); this.drawForm(); } break;
      case 'row-remove': this.form.rows.splice(Number(t.dataset.row), 1); this.drawForm(); break;
      default: break;
    }
  }

  peekAction(action, id) {
    const p = this.papers.find((x) => x.id === id);
    if (action === 'close' || !p) { this.peekId = ''; this.drawPins(); this.drawPeek(); return; }
    switch (action) {
      case 'show': this.showScheme(id); break;
      case 'edit': this.openForm(p); break;
      case 'pick': this.select(toggleSelected(this.selected, id, true)); break;
      case 'plan': this.planAt(p); break;
      case 'write': this.planAt(p, () => { this.editing = id; this.select([id]); }); break;
      default: break;
    }
  }

  onInput(e) {
    const t = e.target;
    if (t.dataset.ui === 'tilt-range') {
      this.tween += 1;
      this.setView({ ...this.view, tilt: Number(t.value) });
      return;
    }
    if (!this.form || !t.closest('.scheme-form')) return;
    if (t.dataset.row !== undefined) this.form.rows[Number(t.dataset.row)][t.dataset.key] = t.value;
    else if (t.dataset.key) this.form[t.dataset.key] = t.value;
  }

  onWheel(e) {
    if (e.target.closest('.tray, .scheme-form') || typing(e.target)) return;
    e.preventDefault();
    const v = this.view;
    this.tween += 1;
    if (e.ctrlKey || e.metaKey) {
      const g0 = this.ground(e.clientX, e.clientY);
      if (g0) this.setView(zoomAround(v, g0.x, g0.y, Math.exp(e.deltaY * 0.01)));
    } else if (e.shiftKey && !e.deltaX) {
      this.setView({ ...v, turn: v.turn + e.deltaY * 0.15 });
    } else {
      const a = this.ground(e.clientX, e.clientY);
      const b = this.ground(e.clientX + e.deltaX, e.clientY + e.deltaY);
      if (a && b) this.setView({ ...v, x: v.x + (b.x - a.x), y: v.y + (b.y - a.y) });
    }
  }

  onDown(e) {
    if (e.target.closest('.table-ui') || typing(e.target) || e.target.closest('button, a')) return;
    e.preventDefault(); // no text selection while dragging across the panes
    this.root.focus({ preventScroll: true });
    this.root.setPointerCapture(e.pointerId);
    this.tween += 1;
    const v = this.view;
    if (e.button === 2 || e.altKey) { this.gesture = { kind: 'orbit', x: e.clientX, y: e.clientY, v }; return; }
    const g0 = this.ground(e.clientX, e.clientY);
    if (!g0) return;
    if (this.tool === 'pen') {
      const sheet = [...this.papers].reverse().find((p) => p.kind === 'tracing'
        && Math.abs(g0.x - p.x) <= (p.w * PX) / 2 && Math.abs(g0.y - p.y) <= (p.h * PX) / 2);
      if (!sheet) { this.say('트레이싱지 위에만 그릴 수 있습니다. 먼저 [트레이싱지 덮기]를 누르세요.'); return; }
      const off = { x: sheet.x - this.home.x, y: sheet.y - this.home.y };
      this.gesture = { kind: 'draw', id: sheet.id, off, points: [[cm(g0.x - off.x), cm(g0.y - off.y)]] };
      return;
    }
    if (this.tool === 'note') {
      const [w, h] = PAPER_SIZE.note;
      this.setTool('select');
      this.hooks.add({ kind: 'note', text: '', x: g0.x, y: g0.y, w, h }).then((done) => {
        if (!done?.paper) return;
        this.editing = done.paper.id;
        this.select([done.paper.id]);
      });
      return;
    }
    const paperId = e.target.closest('[data-paper]')?.dataset.paper;
    if (paperId) {
      const next = e.shiftKey || this.selected.includes(paperId) ? (e.shiftKey ? toggleSelected(this.selected, paperId, true) : this.selected) : [paperId];
      if (next !== this.selected) this.select(next);
      const p = this.papers.find((x) => x.id === paperId);
      if (p?.kind === 'mass' && !e.shiftKey && this.active !== paperId) this.showScheme(paperId);
      this.gesture = { kind: 'move', g0, ids: new Set(next), from: new Map(this.papers.map((q) => [q.id, { x: q.x, y: q.y }])), moved: false, x: e.clientX, y: e.clientY };
      return;
    }
    this.gesture = { kind: 'pan', g0, v, x: e.clientX, y: e.clientY, moved: false };
  }

  onMove(e) {
    const g = this.gesture;
    if (!g) return;
    if (g.kind === 'orbit') {
      this.setView({ ...g.v, turn: g.v.turn - (e.clientX - g.x) * 0.3, tilt: Math.min(MAX_TILT, Math.max(0, g.v.tilt + (e.clientY - g.y) * 0.25)) });
    } else if (g.kind === 'pan') {
      const p = this.ground(e.clientX, e.clientY, g.v);
      if (p) this.setView({ ...g.v, x: g.v.x - (p.x - g.g0.x), y: g.v.y - (p.y - g.g0.y) });
      if (Math.hypot(e.clientX - g.x, e.clientY - g.y) > 3) g.moved = true;
    } else if (g.kind === 'move') {
      const p = this.ground(e.clientX, e.clientY);
      if (!p) return;
      if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) < 3) return;
      g.moved = true;
      const dx = p.x - g.g0.x;
      const dy = p.y - g.g0.y;
      for (const q of this.papers) {
        if (!g.ids.has(q.id)) continue;
        const f = g.from.get(q.id);
        q.x = f.x + dx;
        q.y = f.y + dy;
        if (q.kind === 'tracing' && g.ids.size === 1 && Math.hypot(q.x - this.home.x, q.y - this.home.y) < SNAP) { q.x = this.home.x; q.y = this.home.y; }
        this.gl?.objects.get(q.id)?.position.set(q.x, q.y, q.kind === 'tracing' ? 0.3 : 0.1);
      }
      this.invalidate();
    } else if (g.kind === 'draw') {
      const p = this.ground(e.clientX, e.clientY);
      if (!p) return;
      const pt = [cm(p.x - g.off.x), cm(p.y - g.off.y)];
      const last = g.points[g.points.length - 1];
      if (Math.hypot(pt[0] - last[0], pt[1] - last[1]) < this.view.span / 500) return;
      g.points.push(pt);
      const draft = this.slot(g.id).querySelector('.draft');
      if (draft) draft.setAttribute('d', strokePath(g.points));
      this.invalidate();
    }
  }

  onUp() {
    const g = this.gesture;
    this.gesture = null;
    if (g?.kind === 'draw' && g.points.length > 1) {
      const p = this.papers.find((q) => q.id === g.id);
      if (p) {
        p.strokes = [...(p.strokes || []), g.points];
        this.syncPapers();
        this.save(p.id, { strokes: p.strokes });
      }
    } else if (g?.kind === 'pan' && !g.moved) {
      if (this.selected.length) this.select([]);
    } else if (g?.kind === 'move' && g.moved) {
      for (const q of this.papers) {
        if (!g.ids.has(q.id)) continue;
        const changes = { x: q.x, y: q.y };
        if (q.kind === 'tracing') { q.overlaid = isOverlaid(q, this.home); changes.overlaid = q.overlaid; }
        this.save(q.id, changes);
      }
      this.syncPapers();
      if (g.ids.size === 1) {
        const p = this.papers.find((q) => g.ids.has(q.id));
        if (p?.kind === 'tracing') this.say(isOverlaid(p, this.home) ? `${paperName(p)}을(를) 대지 위에 다시 덮었습니다.` : `${paperName(p)}을(를) 떼어냈습니다. 옆에 두고 보거나, 다시 대지 위로 끌어 덮으세요.`);
      }
    }
    if (g?.kind === 'draw') {
      const draft = this.slot(g.id).querySelector('.draft');
      if (draft) draft.setAttribute('d', '');
    }
    if (!this.gesture && this.pending) { const view = this.pending; this.pending = null; this.setBoard(view); }
  }

  onDouble(e) {
    const id = e.target.closest('[data-paper]')?.dataset.paper;
    const p = this.papers.find((x) => x.id === id);
    if (p?.kind === 'note') { this.editing = id; this.drawPaper(p); }
    if (p?.kind === 'mass') this.openForm(p);
  }

  onKey(e) {
    if (typing(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase();
    const handled = () => e.preventDefault();
    if (k === '1') { handled(); this.animateTo({ tilt: TILT.plan, turn: 0 }); }
    else if (k === '2') { handled(); this.animateTo({ tilt: TILT.axo, turn: this.view.turn || -30 }); }
    else if (k === '3') { handled(); this.animateTo({ tilt: TILT.eye, turn: this.view.turn || -30 }); }
    else if (k === '0') { handled(); this.fit(); }
    else if (k === 't') { handled(); this.layTracing(); }
    else if (k === 'delete' || k === 'backspace') { handled(); this.removeSelected(); }
    else if (k === 'escape') {
      if (this.peekId) { this.peekId = ''; this.drawPins(); this.drawPeek(); return; }
      this.select([]);
      this.setTool('select');
    }
    else {
      const tool = TOOLS.find((x) => x.key === k);
      if (tool) { handled(); this.setTool(tool.id); }
    }
  }
}

