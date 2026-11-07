// The drafting table (제도판): the site at real scale in the middle of a table, sheets of paper
// around it, and tilting the table turns the plan into a 3D view.
// Masses rise as the table leans, and the papers fold into pins so the model can be read
// (a pin opens its paper as a card). A tracing sheet laid on the site snaps into register; dragged
// aside it becomes a sheet of its own. What the AI made waits in the AI section beside the table.
//
// The table's files only draw and take input: this file has the scene, the views, undo and the
// controls, and table-*.js add the papers, the blocks, the surroundings, the detail window and
// the pointer handling to the class. Saving goes through the callbacks board.js gives (which
// call the JSON API, docs/board-api.md), and figures come from the server. The table keeps its
// own element, which render.js lays over a slot in the page, so redraws of the page leave it be.
import * as THREE from './vendor/three.js';
import { escapeHtml as escape } from './model.js';
import { PX, MAX_TILT, cameraFor, riseFor, groundFor, drawingScale, scaleBar, lerpView, viewName, viewFor, siteBounds, traceHome, placeUnplaced, fitView, folded, foldedInPlan, paperName, fmt, blockKey, pickedBlocks, createHistory, recordStep, undoStep, redoStep, CONTOUR_STEPS } from './board-model.js';
import { typing, TOOLS, MODEL_TOOLS } from './table-shared.js';
import { blocksMethods } from './table-blocks.js';
import { aroundMethods } from './table-around.js';
import { papersMethods } from './table-papers.js';
import { detailMethods } from './table-detail.js';
import { pointerMethods } from './table-pointer.js';

export class DraftingTable {
  // hooks: { add(paper), update(id, changes), remove(id), place(id, placement), discard(id),
  //          addPhoto(blob, fileName, fields), select(ids), ask(id), openExpert(agent), experts(),
  //          photoUrl(id) } — the first six return promises.
  // ask(id): the designer wants to ask about this paper (app.js picks it and opens the composer).
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
    this.picked = []; // blocks (buildings) picked on their own: `paperId#index`
    this.active = '';
    this.ghost = false;
    this.preview = '';
    this.editing = '';
    this.peekId = ''; // the paper whose card is open from its pin in 3D
    this.detailId = ''; // the paper open in the detail panel (a click on it, or 상세 보기)
    this.paperZoom = 1; // screen px per paper px in plan (the corner grips and PDF pages follow it)
    this.pdfs = new Map(); // 'card:'/'detail:'/'peek:' + paper id → {canvas, url, page, size}
    this.pdfPages = new Map(); // PDF url → its number of pages
    this.history = createHistory(); // the designer's edits, for undo and redo (this session only)
    this.trayOpen = false;
    this.carrying = ''; // a moved paper's circle: '' (none), 'on' (carried) or 'over' (over the idea board)
    this.form = null;
    this.numberEdit = null;
    this.gesture = null;
    this.pending = null;
    this.fitted = false;
    this.tween = 0;
    this.frame = 0;
    this.slots = new Map();
    this.drawn = new Map(); // paper id → what its element last showed
    this.pins = new Map(); // paper id → its pin element (3D)
    this.toldFold = false;
    this.around = null; // the site's surroundings (GET .../site/context), fetched when first shown
    this.aroundOn = false;
    this.aroundBusy = false;
    this.aroundRequest = null;
    this.aroundNoteOpen = null; // the source note: open or folded (decided by the width when first shown)
    this.aroundRange = null; // {size, shape, orient}: the project's range for the surroundings, read once
    this.stepped = null; // the stepped ground (GET .../site/model-base) for the 계단식 보기
    this.steppedOn = false;
    this.aroundLow = 0;
    this.contourStep = 1;
    this.root = document.createElement('div');
    this.root.className = 'table';
    this.root.tabIndex = 0;
    this.root.setAttribute('role', 'application');
    this.root.setAttribute('aria-label', '제도판');
    this.root.innerHTML = `<div class="table-stage"></div>
      <div class="table-pins" role="group" aria-label="종이 이름표"></div>
      <div class="table-box" hidden></div>
      <div class="tape-snap" hidden aria-hidden="true"><span></span></div>
      <div class="table-gumball" hidden aria-hidden="true"><svg>
        ${['u', 'v', 'z'].map((a) => `<g data-gumball="${a}" class="gb-${a}"><line class="gb-hit"/><line class="gb-shaft"/><polygon class="gb-head"/></g>`).join('')}
        ${['w', 'd'].map((a) => `<rect data-gumball="${a}" class="gb-size gb-${a === 'w' ? 'u' : 'v'}" width="10" height="10"><title>${a === 'w' ? '가로' : '세로'} 크기</title></rect>`).join('')}
        <rect data-gumball="free" class="gb-free" width="14" height="14"/>
      </svg></div>
      <div class="table-ui ui-left"><div class="ui-history" role="group" aria-label="편집 기록"></div>
        <div class="ui-tools" role="toolbar" aria-orientation="vertical" aria-label="제도판 도구"></div></div>
      <div class="table-ui ui-scheme"></div>
      <div class="table-ui ui-tilt" aria-label="기울기"></div>
      <div class="table-ui ui-zoom"></div>
      <p class="table-ui ui-help">왼쪽 끌기: 선택 상자(→ 안에 든 것, ← 걸친 것, Shift 더하기, Ctrl 빼기) · 건물 클릭: 그 동만 고르기(끌면 옮김, 검볼, Delete 지우기) · 스케치업 도구는 명령으로: rect pushpull move copy rotate scale eraser dist (제도판에서 글자를 치면 명령창으로) · Ctrl+C/V 복사·붙여넣기, Ctrl+A 모든 동 · 고른 이름표 끌기: 종이 옮기기 · 휠: 커서 기준 확대 · 우클릭 끌기: 돌리기 · Shift+우클릭·가운데 버튼 끌기: 이동 · Ctrl+Z: 되돌리기 · 사진·PDF: 파일을 끌어다 놓거나 붙여넣기(photo) · 종이 모서리 끌기: 크기 조절</p>
      <p class="table-ui ui-hint" role="status" hidden></p>
      <section class="table-ui around-note" aria-label="주변 3D 자료 출처" hidden></section>
      <aside class="table-ui tray" aria-label="AI 섹션"></aside>
      <section class="table-ui peek" aria-label="종이 내용" hidden></section>
      <section class="table-ui scheme-form" aria-label="매스안 입력" hidden></section>
      <dialog class="card-detail" aria-labelledby="detail-title"></dialog>
      <dialog class="tool-number" aria-labelledby="tool-number-title" aria-describedby="tool-number-help"></dialog>
      <input type="file" class="photo-input" accept="image/*,application/pdf,.pdf" multiple hidden aria-hidden="true" tabindex="-1">
      <div class="photo-drop" hidden aria-hidden="true"><span>여기에 놓으면 사진·PDF가 제도판에 올라갑니다</span></div>`;
    this.stage = this.root.querySelector('.table-stage');
    this.pinLayer = this.root.querySelector('.table-pins');
    this.boxEl = this.root.querySelector('.table-box');
    this.snapEl = this.root.querySelector('.tape-snap');
    this.gumEl = this.root.querySelector('.table-gumball');
    this.photoInput = this.root.querySelector('.photo-input');
    this.dropEl = this.root.querySelector('.photo-drop');
    this.ui = {
      tools: this.root.querySelector('.ui-tools'),
      scheme: this.root.querySelector('.ui-scheme'),
      tilt: this.root.querySelector('.ui-tilt'),
      zoom: this.root.querySelector('.ui-zoom'),
      hint: this.root.querySelector('.ui-hint'),
      tray: this.root.querySelector('.tray'),
      form: this.root.querySelector('.scheme-form'),
      peek: this.root.querySelector('.peek'),
      history: this.root.querySelector('.ui-history'),
      detail: this.root.querySelector('.card-detail'),
      number: this.root.querySelector('.tool-number'),
      aroundNote: this.root.querySelector('.around-note'),
    };
    this.setupScene();
    this.listen();
    this.drawControls();
  }

  // ------------------------------------------------------------------ mounting

  destroy() {
    this.aroundRequest = null;
    this.ui.number.close();
    window.removeEventListener('keydown', this.onWindowKey);
    window.removeEventListener('paste', this.onPaste);
    cancelAnimationFrame(this.frame);
    this.observer?.disconnect();
    clearTimeout(this.pdfTimer);
    this.gl?.renderer.dispose();
    this.root.remove();
  }

  // ------------------------------------------------------------------ data from the server

  setBoard(view) {
    if (this.gesture) { this.pending = view; return; }
    const siteChanged = JSON.stringify(this.site?.plan) !== JSON.stringify(view.site?.plan);
    this.site = view.site || null;
    if (siteChanged) {
      this.aroundRequest = null;
      this.aroundBusy = false;
      this.aroundOn = false;
      this.around = null;
      this.drawAround();
    }
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
    this.picked = pickedBlocks(this.papers, this.picked).flatMap((g) => g.indices.map((i) => blockKey(g.paper.id, i)));
    if (this.peekId && !this.papers.some((p) => p.id === this.peekId)) this.peekId = '';
    if (this.detailId) {
      const writing = this.ui.detail.contains(document.activeElement) && typing(document.activeElement);
      if (!this.find(this.detailId)) this.closeDetail();
      else if (!writing) this.drawDetail();
    }
    if (siteChanged || !this.lotDrawn) this.drawSite();
    if (moved && this.boardSeen) this.fit(); // a newly saved site: bring it into view
    this.boardSeen = true;
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

  // A command typed on the command line (command-model.js COMMANDS). Returns '' when it ran,
  // or a line saying why it could not.
  command(name) {
    switch (name) {
      case 'plan': this.showView('plan'); return '';
      case 'persp': this.showView('3d'); return '';
      case 'zoom': this.fit(); return '';
      case 'north': this.animateTo({ turn: 0 }); return '';
      case 'select': case 'note': case 'pen': this.setTool(name); return '';
      case 'rect': case 'move': case 'rotate': case 'scale': this.setTool(name); return '';
      case 'pushpull': this.setTool('push'); return '';
      case 'eraser': this.setTool('erase'); return '';
      case 'dist': this.setTool('tape'); return '';
      case 'copy': this.setTool('move', { copy: true }); return '';
      case 'trace': this.layTracing(); return '';
      case 'mass': this.openForm(); return '';
      case 'photo': this.pickPhotos(); return '';
      case 'delete':
        if (this.picked.length) { this.removePicked(); return ''; }
        if (!this.selected.some((id) => this.papers.some((p) => p.id === id && p.kind !== 'site'))) return '먼저 지울 종이나 동을 고르세요.';
        this.removeSelected();
        return '';
      case 'undo': case 'redo':
        if (!(name === 'undo' ? this.history.past : this.history.future).length) return name === 'undo' ? '되돌릴 것이 없습니다.' : '다시 할 것이 없습니다.';
        this.travel(name);
        return '';
      case 'tray': this.trayOpen = !this.trayOpen; this.drawTray(); this.drawControls(); return '';
      default: return '제도판에서 쓰는 명령이 아닙니다.';
    }
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
      ghost: color('--brand', '#36536b'), pick: color('--pick', '#e3a008'), // a picked block, yellow as in Rhino
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
    const desk = new THREE.Mesh(new THREE.PlaneGeometry(6000, 6000), new THREE.MeshBasicMaterial({ color: this.colors.table }));
    scene.add(desk);
    const catcher = new THREE.Mesh(new THREE.PlaneGeometry(1200, 1200), new THREE.ShadowMaterial({ opacity: 0.22 }));
    catcher.position.z = 0.01;
    catcher.receiveShadow = true;
    scene.add(catcher);
    const grid = new THREE.GridHelper(2000, 200, this.colors.line, this.colors.line);
    grid.rotation.x = Math.PI / 2;
    grid.position.z = 0.02;
    grid.material.transparent = true;
    scene.add(grid);
    // The ground line of an elevation: one long line across the view, through the target.
    const horizon = new THREE.Line(new THREE.BufferGeometry().setFromPoints([new THREE.Vector3(-5000, 0, 0), new THREE.Vector3(5000, 0, 0)]),
      new THREE.LineBasicMaterial({ color: this.colors.ink, transparent: true }));
    scene.add(horizon);
    const lot = new THREE.Group();
    const masses = new THREE.Group();
    const traces = new THREE.Group();
    const draft = new THREE.Group(); // what a tool is drawing: a rectangle, the tape measure
    const around = new THREE.Group(); // the site's surroundings: ground, nearby buildings, contours
    scene.add(lot, masses, traces, draft, around);
    this.gl = { renderer, cssRenderer, scene, cssScene, camera, desk, grid, catcher, horizon, lot, masses, traces, draft, around, labels: [], objects: new Map(), raycaster: new THREE.Raycaster() };
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
    const { renderer, cssRenderer, scene, cssScene, camera, desk, grid, catcher, horizon, lot, masses, traces, around, labels, objects } = this.gl;
    const v = this.view;
    this.aimCamera(camera, v);
    const rise = riseFor(v.tilt);
    masses.scale.z = rise;
    // The surroundings rise with the masses; the table top goes below the lowest ground under them.
    const shown = Boolean(this.aroundOn && this.around);
    around.visible = shown;
    around.scale.z = rise;
    desk.position.z = shown ? Math.min(0, this.aroundLow) * rise - 0.5 : 0;
    catcher.position.z = desk.position.z + 0.01;
    // Lying flat for an elevation the ground fades away and only the buildings stand, on a ground line.
    const ground = groundFor(v.tilt);
    grid.material.opacity = ground;
    grid.visible = !shown;
    catcher.material.opacity = 0.22 * ground;
    lot.visible = ground > 0.5;
    horizon.visible = ground < 1;
    horizon.material.opacity = 1 - ground;
    horizon.position.set(v.x, v.y, 0.1);
    horizon.rotation.z = (-v.turn * Math.PI) / 180; // across the view, square to where the viewer faces
    for (const l of labels) l.element.style.opacity = rise < 0.25 ? String(1 - rise * 4) : '0';
    // In plan the papers lie on the table. Once it leans they fold into pins (drawn over the
    // scene, upright), and an overlaid tracing's lines lie on the ground.
    // A paper the designer folded stays a pin in plan too.
    const fold = folded(v.tilt);
    const shut = new Set(foldedInPlan(this.papers, this.home));
    traces.visible = fold && ground > 0.5;
    for (const [id, obj] of objects) obj.visible = !fold && !shut.has(id);
    if (fold !== this.root.classList.contains('is-3d')) this.foldChanged(fold);
    this.root.classList.toggle('has-folded', shut.size > 0);
    // How large a paper px is on the screen, for the corner grips (a steady size on the screen)
    // and the PDF pages (drawn again, a moment after a zoom, as sharp as they are now seen).
    const zoom = (PX * this.root.clientHeight) / v.span;
    if (!fold && Math.abs(zoom / this.paperZoom - 1) > 0.02) {
      this.paperZoom = zoom;
      this.root.style.setProperty('--paper-zoom', zoom.toFixed(4));
      clearTimeout(this.pdfTimer);
      this.pdfTimer = setTimeout(() => this.refreshPdfs(), 180);
    }
    renderer.render(scene, camera);
    cssRenderer.render(cssScene, camera);
    if (fold || shut.size) this.placePins(fold ? null : shut);
    this.placeGumball();
  }

  openViewScale() {
    this.numberEdit = { viewScale: true };
    this.ui.number.innerHTML = `<form data-form="tool-number" novalidate>
      <header><h2 id="tool-number-title">화면 축척 설정</h2><button type="button" data-ui="number-cancel" aria-label="축척 입력 닫기">×</button></header>
      <label for="view-scale-value">축척 (1:n)</label><input id="view-scale-value" type="text" inputmode="decimal" value="${drawingScale(this.view.span, this.root.clientHeight)}" autocomplete="off">
      <p id="tool-number-help">500 또는 1:500으로 입력하세요. 평면은 대지 평면, 3D는 시선 중심의 거리 기준입니다. 화면 축척은 CSS 픽셀(96dpi) 기준이며, 거리 막대가 모델의 실제 길이를 나타냅니다.</p>
      <p class="form-error" role="alert"></p><footer><button type="button" data-ui="number-cancel">취소</button><button type="submit" class="primary-small">적용</button></footer>
    </form>`;
    this.ui.number.showModal();
    this.ui.number.querySelector('input').select();
  }

  scaleReadout() {
    const h = this.root.clientHeight || 600;
    const bar = scaleBar(this.view.span, h);
    const ratio = drawingScale(this.view.span, h);
    const reference = this.view.tilt > 0 ? '3D 중심' : '평면';
    return `<button type="button" class="num scale" data-ui="view-scale" title="화면 축척 설정 · ${reference} 기준 (CSS 96dpi)" aria-label="화면 축척 ${ratio} 수정">${ratio}<small>${reference}</small></button>
      <span class="view-scale-bar" title="${reference} 기준 실제 거리"><span>${fmt(bar.metres, bar.metres < 1 ? 2 : 0)} m</span><i style="width:${bar.pixels}px"></i></span>`;
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

  openModel() { this.hooks.openExpert?.('representation_planner', 'model'); }

  // ------------------------------------------------------------------ undo and redo
  // Every edit is saved through the API as it happens, so undo sends the inverse edit.

  record(edits) {
    this.history = recordStep(this.history, edits);
    this.drawHistory();
  }

  drawHistory() {
    this.ui.history.innerHTML = `<button type="button" data-ui="undo" aria-label="실행 취소" title="실행 취소 (Ctrl/⌘+Z)" ${this.history.past.length ? '' : 'disabled'}>↶</button>
      <button type="button" data-ui="redo" aria-label="다시 실행" title="다시 실행 (Ctrl/⌘+Shift+Z, Ctrl+Y)" ${this.history.future.length ? '' : 'disabled'}>↷</button>`;
  }

  async travel(direction) {
    if (this.travelling) return;
    const out = direction === 'undo' ? undoStep(this.history) : redoStep(this.history);
    if (!out.step) return;
    this.history = out.history;
    this.drawHistory();
    this.gesture = null;
    this.editing = '';
    this.travelling = true;
    try {
      for (const edit of out.step) await this.applyEdit(edit);
    } finally {
      this.travelling = false;
    }
    this.syncPapers();
    this.drawMasses();
    this.drawControls();
    if (this.detailId) this.drawDetail();
    this.say(direction === 'undo' ? '되돌렸습니다.' : '다시 했습니다.');
  }

  async applyEdit(edit) {
    if (edit.op === 'update') {
      const p = this.papers.find((x) => x.id === edit.id);
      if (p) {
        Object.assign(p, edit.after);
        if (edit.after.folded === false) delete p.folded;
        this.syncPapers();
        this.drawMasses();
      }
      await this.hooks.update(edit.id, edit.after);
    } else if (edit.op === 'remove') {
      this.papers = this.papers.filter((p) => p.id !== edit.paper.id);
      if (this.selected.includes(edit.paper.id)) this.select(this.selected.filter((x) => x !== edit.paper.id));
      if (this.detailId === edit.paper.id) this.closeDetail();
      this.syncPapers();
      this.drawMasses();
      await this.hooks.remove(edit.paper.id);
    } else if (edit.op === 'add') {
      await this.hooks.add(edit.paper);
    }
  }

  // ------------------------------------------------------------------ controls

  drawControls() {
    this.drawHistory();
    const v = this.view;
    const masses = this.papers.filter((p) => p.kind === 'mass');
    const toolButton = (t) => `<button type="button" data-tool="${t.id}" aria-pressed="${this.tool === t.id}" title="${t.label} (명령: ${t.cmd})${t.hint ? ` — ${t.hint}` : ''}"><span aria-hidden="true">${t.icon}</span> ${t.label}</button>`;
    this.ui.tools.innerHTML = `${TOOLS.filter((t) => !t.group).slice(0, 1).map(toolButton).join('')}
      <span class="sep"></span>${TOOLS.filter((t) => t.group === 'model').map(toolButton).join('')}
      <span class="sep"></span>${TOOLS.filter((t) => !t.group).slice(1).map(toolButton).join('')}
      <span class="sep"></span>
      <button type="button" data-ui="scheme-new" title="숫자로 매스안 만들기">＋ 매스안</button>
      <button type="button" data-ui="trace" title="트레이싱지 덮기 (명령: trace)">트레이싱지 덮기</button>
      <button type="button" data-ui="photo" title="사진·PDF 올리기 (명령: photo) — 사진이나 PDF 도면을 제도판에 끌어다 놓거나 붙여넣어도 됩니다">사진·PDF 올리기</button>
      <button type="button" data-ui="around" aria-pressed="${this.aroundOn}" ${this.site?.plan && !this.aroundBusy ? '' : 'disabled'} title="대지 주변(옆에서 고른 범위·모양)의 지형과 건물을 3D로 보기 (공공 자료로 만든 참고용 모형)">${this.aroundBusy ? '주변 불러오는 중…' : '주변 3D'}</button>
      ${this.site?.plan ? this.rangeSelects() : ''}
      ${this.aroundOn && this.around?.terrain ? `<label class="check">등고선 <select data-ui="contour-step" aria-label="등고선 간격">${CONTOUR_STEPS.map((s) => `<option value="${s}" ${s === this.contourStep ? 'selected' : ''}>${s}m</option>`).join('')}</select></label>` : ''}
      <button type="button" data-ui="delete" ${this.selected.some((id) => this.papers.some((p) => p.id === id && p.kind !== 'site')) ? '' : 'disabled'} title="삭제 (Delete)">삭제</button>
      <span class="sep"></span>
      <button type="button" data-ui="tray" aria-pressed="${this.trayOpen}">AI 섹션${this.tray.length ? ` <b>${this.tray.length}</b>` : ''}</button>`;
    this.ui.scheme.hidden = !masses.length;
    this.ui.scheme.innerHTML = masses.length ? `<div class="seg" role="group" aria-label="3D로 볼 매스안">
        ${masses.map((p) => `<button type="button" data-active="${escape(p.id)}" aria-pressed="${this.active === p.id}">${escape(paperName(p))}</button>`).join('')}</div>
      ${masses.length > 1 ? `<label class="check"><input type="checkbox" data-ui="ghost" ${this.ghost ? 'checked' : ''}> 다른 안 겹쳐 보기</label>` : ''}` : '';
    this.ui.tilt.innerHTML = `<div class="seg vertical" role="group" aria-label="보는 각도">
        ${[['plan', '평면', 'plan'], ['3d', '3D', 'persp']].map(([id, label, k]) => `<button type="button" data-tilt="${id}" title="${label} (명령: ${k})" aria-pressed="${viewName(v.tilt) === id}">${label}</button>`).join('')}</div>
      <input type="range" min="0" max="${MAX_TILT}" value="${Math.round(v.tilt)}" aria-label="기울기 각도" data-ui="tilt-range">
      <span class="num tilt-read">${Math.round(v.tilt)}°</span>
      <button type="button" class="compass" data-ui="north" title="북쪽을 위로"><span style="transform: rotate(${-v.turn}deg)" aria-hidden="true">▲</span><small>N</small></button>`;
    this.ui.zoom.innerHTML = `<span class="scale-readout">${this.scaleReadout()}</span>
      <button type="button" data-ui="zoom-in" aria-label="확대">+</button>
      <button type="button" data-ui="zoom-out" aria-label="축소">−</button>
      <button type="button" data-ui="fit" title="전체 보기 (명령: zoom)">맞춤</button>`;
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
    for (const b of this.ui.tilt.querySelectorAll('[data-tilt]')) b.setAttribute('aria-pressed', String(viewName(v.tilt) === b.dataset.tilt));
    const scale = this.ui.zoom.querySelector('.scale-readout');
    if (scale) scale.innerHTML = this.scaleReadout();
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

  // The plan or the 3D view (board-model.js viewFor): the buttons, keys 1·2 and plan/persp.
  showView(name) {
    const target = viewFor(name, this.view);
    if (target) this.animateTo(target);
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

  setTool(tool, { copy = false } = {}) {
    this.snapEl.hidden = true;
    this.tool = tool;
    this.copyMode = copy; // the copy command: the move tool copies without Ctrl
    if (tool === 'pen' && folded(this.view.tilt)) {
      this.animateTo({ tilt: 0, turn: 0 });
      this.say('펜은 평면에서 씁니다. 평면으로 돌아왔습니다.');
    }
    const hint = copy ? '고른 동(또는 누른 동)을 끌어 복사합니다.' : TOOLS.find((t) => t.id === tool)?.hint;
    if (hint) this.say(hint);
    this.root.classList.toggle('tool-pen', tool === 'pen');
    this.root.classList.toggle('tool-note', tool === 'note');
    this.root.classList.toggle('tool-model', MODEL_TOOLS.has(tool));
    this.gl?.draft.clear();
    this.drawControls();
    this.invalidate();
  }
}

Object.assign(DraftingTable.prototype, blocksMethods, aroundMethods, papersMethods, detailMethods, pointerMethods);
