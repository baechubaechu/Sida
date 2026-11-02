// The drafting table (제도판): the site at real scale in the middle of a table, sheets of paper
// around it, and tilting the table turns the plan into a 3D view.
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
  PX, TILT, MAX_TILT, PAPER_SIZE, cameraFor, riseFor, groundFor, zoomAround, drawingScale, scaleSpan, scaleBar, lerpView, dragMode, wheelZoom, orbitBy, viewName, viewFor, panBy, EDGE_TILT,
  siteBounds, traceHome, isOverlaid, blockCorners, placeUnplaced, freeSpot, fitView,
  folded, foldedInPlan, pinnedPapers, peekSpot,
  paperName, resultPreview, KIND_LABELS, originLabel, figureLines, readScheme, schemeRows, toggleSelected, boxPick, boxMode, parseBlockKey, fmt,
  GUMBALL_PX, GUMBALL_SCALE_PX, frameDelta, editBlocks, axisDrag, blocksCenter, blockKey, pickedBlocks,
  toFrame, rectBlock, pushBlock, copyBlocks, turnBlocks, scaleBlocks, snapAngle, MAX_BLOCKS,
  numericToolClick, numericPushBlock, numericScaleBlocks,
  snapTape,
  massIds, createHistory, recordStep, undoStep, redoStep, changedFields, planDrawing,
} from './board-model.js';

const SNAP = 7; // metres: a tracing sheet this close to its place on the site clicks into register
const typing = (el) => el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.isContentEditable);
// The tools, with SketchUp's basic modeling tools on blocks (2026-11-02 지훈). No single-key
// shortcuts: a tool starts from its button or its command word on the command line (`cmd`).
const TOOLS = [
  { id: 'select', label: '선택', cmd: 'select', icon: '↖' },
  { id: 'rect', label: '사각형', cmd: 'rect', icon: '▭', group: 'model', hint: '땅 위에서 끌어 새 동을 그립니다. 그다음 밀고끌기(pushpull)로 올리세요.' },
  { id: 'push', label: '밀고끌기', cmd: 'pushpull', icon: '⇕', group: 'model', hint: '면을 끌어서 조절하거나, 클릭해 목표 층수·길이를 숫자로 입력합니다.' },
  { id: 'move', label: '이동', cmd: 'move', icon: '✥', group: 'model', hint: '고른 동(또는 누른 동)을 끌어 옮깁니다. Ctrl을 누르고 시작하면 복사합니다.' },
  { id: 'rotate', label: '회전', cmd: 'rotate', icon: '⟲', group: 'model', hint: '고른 동(또는 누른 동)의 가운데를 기준으로 끌어 돌립니다. 5° 단위, Shift는 1° 단위.' },
  { id: 'scale', label: '크기', cmd: 'scale', icon: '⤡', group: 'model', hint: '동을 끌어서 크기를 조절하거나, 클릭해 배율을 입력합니다. 층수는 유지됩니다.' },
  { id: 'erase', label: '지우개', cmd: 'eraser', icon: '⌫', group: 'model', hint: '누르거나 끌고 지나간 동을 지웁니다.' },
  { id: 'tape', label: '줄자', cmd: 'dist', icon: '↔', group: 'model', hint: '매스 꼭짓점·모서리와 대지·트레이싱 선에 스냅합니다. Alt를 누르면 스냅을 끕니다.' },
  { id: 'note', label: '메모', cmd: 'note', icon: '▤' },
  { id: 'pen', label: '펜', cmd: 'pen', icon: '✎' },
];
const MODEL_TOOLS = new Set(TOOLS.filter((t) => t.group === 'model').map((t) => t.id));
const DETAIL_KINDS = { site: '대지 자료', mass: '매스안', expert: '전문가 검토', tracing: '트레이싱', note: '설계 메모' };
const cm = (metres) => Math.round(metres * 100) / 100; // pen points are kept to the centimetre
const strokePath = (pts) => pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)} ${(-y).toFixed(2)}`).join(' ');

export class DraftingTable {
  // hooks: { add(paper), update(id, changes), remove(id), place(id, placement), discard(id),
  //          select(ids), ask(id), openExpert(agent), experts() } — the first five return promises.
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
    this.history = createHistory(); // the designer's edits, for undo and redo (this session only)
    this.trayOpen = false;
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
      <p class="table-ui ui-help">왼쪽 끌기: 선택 상자(→ 안에 든 것, ← 걸친 것, Shift 더하기, Ctrl 빼기) · 건물 클릭: 그 동만 고르기(끌면 옮김, 검볼, Delete 지우기) · 스케치업 도구는 명령으로: rect pushpull move copy rotate scale eraser dist (제도판에서 글자를 치면 명령창으로) · Ctrl+C/V 복사·붙여넣기, Ctrl+A 모든 동 · 고른 이름표 끌기: 종이 옮기기 · 휠: 커서 기준 확대 · 우클릭 끌기: 돌리기 · Shift+우클릭·가운데 버튼 끌기: 이동 · Ctrl+Z: 되돌리기</p>
      <p class="table-ui ui-hint" role="status" hidden></p>
      <aside class="table-ui tray" aria-label="AI 섹션"></aside>
      <section class="table-ui peek" aria-label="종이 내용" hidden></section>
      <section class="table-ui scheme-form" aria-label="매스안 입력" hidden></section>
      <dialog class="card-detail" aria-labelledby="detail-title"></dialog>
      <dialog class="tool-number" aria-labelledby="tool-number-title" aria-describedby="tool-number-help"></dialog>`;
    this.stage = this.root.querySelector('.table-stage');
    this.pinLayer = this.root.querySelector('.table-pins');
    this.boxEl = this.root.querySelector('.table-box');
    this.snapEl = this.root.querySelector('.tape-snap');
    this.gumEl = this.root.querySelector('.table-gumball');
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
    };
    this.setupScene();
    this.listen();
    this.drawControls();
  }

  // ------------------------------------------------------------------ mounting

  destroy() {
    this.ui.number.close();
    window.removeEventListener('keydown', this.onWindowKey);
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
    this.picked = pickedBlocks(this.papers, this.picked).flatMap((g) => g.indices.map((i) => blockKey(g.paper.id, i)));
    if (this.peekId && !this.papers.some((p) => p.id === this.peekId)) this.peekId = '';
    if (this.detailId) {
      const writing = this.ui.detail.contains(document.activeElement) && typing(document.activeElement);
      if (!this.find(this.detailId)) this.closeDetail();
      else if (!writing) this.drawDetail();
    }
    if (moved || !this.lotDrawn) this.drawSite();
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
    scene.add(new THREE.Mesh(new THREE.PlaneGeometry(6000, 6000), new THREE.MeshBasicMaterial({ color: this.colors.table })));
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
    scene.add(lot, masses, traces, draft);
    this.gl = { renderer, cssRenderer, scene, cssScene, camera, grid, catcher, horizon, lot, masses, traces, draft, labels: [], objects: new Map(), raycaster: new THREE.Raycaster() };
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
    const { renderer, cssRenderer, scene, cssScene, camera, grid, catcher, horizon, lot, masses, traces, labels, objects } = this.gl;
    const v = this.view;
    this.aimCamera(camera, v);
    const rise = riseFor(v.tilt);
    masses.scale.z = rise;
    // Lying flat for an elevation the ground fades away and only the buildings stand, on a ground line.
    const ground = groundFor(v.tilt);
    grid.material.opacity = ground;
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
    renderer.render(scene, camera);
    cssRenderer.render(cssScene, camera);
    if (fold || shut.size) this.placePins(fold ? null : shut);
    this.placeGumball();
  }

  // The picked blocks, grouped by scheme, of the schemes that stand on the site.
  pickedGroups() {
    return pickedBlocks(this.papers, this.picked).filter((g) => g.paper.id === this.active || this.ghost);
  }

  pickBlocks(keys) {
    this.picked = keys;
    this.drawMasses();
  }

  // The gumball (or a building) taking hold: what the drag edits, the picked blocks as they were.
  gumballGesture(grip, e) {
    const from = new Map(this.pickedGroups().map((g) => [g.paper.id, { blocks: g.paper.blocks, indices: g.indices }]));
    return { kind: 'gumball', grip, axes: this.gumAxes, g0: this.ground(e.clientX, e.clientY), x: e.clientX, y: e.clientY, moved: false, from };
  }

  // Delete takes the picked blocks out of their schemes; a scheme keeps at least one.
  removePicked() {
    this.removeBlocks(this.picked);
  }

  removeBlocks(keys) {
    const edits = [];
    for (const { paper, indices } of pickedBlocks(this.papers, keys)) {
      const blocks = paper.blocks.filter((_, i) => !indices.includes(i));
      if (!blocks.length) { this.say(`${paperName(paper)}에는 동이 하나는 있어야 합니다. 매스안을 지우려면 종이를 골라 지우세요.`); continue; }
      edits.push({ op: 'update', id: paper.id, before: { blocks: paper.blocks }, after: { blocks } });
      paper.blocks = blocks;
      this.save(paper.id, { blocks });
    }
    this.record(edits);
    this.pickBlocks([]);
  }

  // Blocks changed by a drag (or a key), saved and kept for undo: `from` maps a scheme to its
  // blocks before.
  saveBlocks(from) {
    const edits = [];
    for (const [id, before] of from) {
      const p = this.papers.find((q) => q.id === id);
      if (!p || p.blocks === before) continue;
      edits.push({ op: 'update', id, before: { blocks: before }, after: { blocks: p.blocks } });
      this.save(id, { blocks: p.blocks });
    }
    this.record(edits);
  }

  // A block taken by a tool or a click: it alone is picked, and its scheme stands in 3D.
  takeBlock(key) {
    if (this.selected.length) this.select([]);
    const { id } = parseBlockKey(key);
    if (this.active !== id) this.showScheme(id);
    this.pickBlocks([key]);
  }

  // ------------------------------------------------------------------ SketchUp's tools
  // A drag with one of SketchUp's basic tools (2026-11-02 지훈). Move, rotate and scale work on
  // the picked blocks, or on the block pressed (which is then picked).
  modelGesture(e, g0) {
    this.gl?.draft.clear();
    const hit = this.blockHit(e.clientX, e.clientY);
    const base = { x: e.clientX, y: e.clientY, g0, moved: false };
    switch (this.tool) {
      case 'rect': return g0 ? { ...base, kind: this.tool } : null;
      case 'tape': {
        const point = this.tapePoint(e);
        return point ? { ...base, g0: point, kind: 'tape' } : null;
      }
      case 'erase': {
        const keys = new Set(hit ? [hit.key] : []);
        this.pickBlocks([...keys]); // what will go shows picked until the button is let go
        return { ...base, kind: 'erase', keys };
      }
      case 'push': {
        if (!hit) return null;
        this.takeBlock(hit.key);
        const { id, index } = parseBlockKey(hit.key);
        const paper = this.papers.find((p) => p.id === id);
        return { ...base, kind: 'push', id, index, face: hit.face, before: paper.blocks, axis: this.faceAxis(paper.blocks[index], hit.face) };
      }
      default: {
        if (hit && !this.picked.includes(hit.key)) this.takeBlock(hit.key);
        if (!this.pickedGroups().length || !g0) return null;
        const g = this.gumballGesture(this.tool === 'move' ? 'free' : this.tool, e);
        if (this.tool === 'move') return { ...g, copy: this.copyMode || e.ctrlKey || e.metaKey };
        const frame = this.site?.plan?.frame;
        const c = blocksCenter(frame, this.pickedGroups().flatMap((p) => p.indices.map((i) => p.paper.blocks[i])));
        return { ...g, numeric: this.tool === 'scale' && Boolean(hit), center: c, centerUV: toFrame(frame, c.x, c.y) };
      }
    }
  }

  // Where one metre out of a block's face goes on the screen: up for the top, else square to
  // the side, turned with the block and the site.
  faceAxis(b, face) {
    const frame = this.site?.plan?.frame || { x: 0, y: 0, angle: 0 };
    const [mx, my] = blockCorners(frame, { ...b, w: 0, d: 0 })[0];
    let dir = [0, 0, riseFor(this.view.tilt)];
    if (face !== 'top') {
      const t = frame.angle + ((b.a || 0) * Math.PI) / 180 + (face[0] === 'd' ? Math.PI / 2 : 0);
      const sign = face[1] === '+' ? 1 : -1;
      dir = [sign * Math.cos(t), sign * Math.sin(t), 0];
    }
    const { camera } = this.gl;
    const r = this.root.getBoundingClientRect();
    const at = (x, y, z) => { const p = new THREE.Vector3(x, y, z).project(camera); return [((p.x + 1) / 2) * r.width, ((1 - p.y) / 2) * r.height]; };
    const [ax, ay] = at(mx, my, 0);
    const [bx, by] = at(mx + dir[0], my + dir[1], dir[2]);
    return [bx - ax, by - ay];
  }

  openToolNumber(gesture) {
    const push = gesture.kind === 'push';
    const paper = push && this.papers.find((p) => p.id === gesture.id);
    if (push && !paper?.blocks[gesture.index]) return;
    const groups = push
      ? [{ id: gesture.id, blocks: structuredClone(gesture.before), indices: [gesture.index] }]
      : [...gesture.from].map(([id, from]) => ({ id, blocks: structuredClone(from.blocks), indices: [...from.indices] }));
    if (!groups.length) return;
    this.numberEdit = { push, groups, face: gesture.face, center: gesture.centerUV };
    const block = push && gesture.before[gesture.index];
    const top = push && gesture.face === 'top';
    const label = !push ? '크기 배율' : top ? '목표 층수' : `목표 ${gesture.face[0] === 'w' ? '가로' : '세로'} 길이 (m)`;
    const value = !push ? 1 : top ? block.floors : block[gesture.face[0] === 'w' ? 'w' : 'd'];
    const help = !push ? '1.2는 120%, 0.5는 50%입니다. 선택한 동들의 가로·세로와 배치 간격을 함께 조절하며 층수는 유지합니다.'
      : top ? `현재 ${block.floors}층 · 층고 ${fmt(paper.floor_height || 4.2, 2)}m. 1~200층 안에서 입력하세요.`
        : '선택한 면을 움직여 이 길이로 맞춥니다. 반대쪽 면은 유지합니다. 1~1000m 안에서 입력하세요.';
    this.ui.number.innerHTML = `<form data-form="tool-number" novalidate>
      <header><h2 id="tool-number-title">${push ? '밀고끌기' : '크기'} 수치 입력</h2><button type="button" data-ui="number-cancel" aria-label="수치 입력 닫기">×</button></header>
      <p class="source">${push ? `${escape(paperName(paper))} · ${gesture.index + 1}동` : `선택한 동 ${groups.reduce((n, g) => n + g.indices.length, 0)}개`}</p>
      <label for="tool-number-value">${label}</label><input id="tool-number-value" name="value" type="number" inputmode="decimal" step="${top ? '1' : 'any'}" value="${value}" autocomplete="off" autofocus>
      <p id="tool-number-help">${help}</p><p class="form-error" role="alert"></p>
      <footer><button type="button" data-ui="number-cancel">취소</button><button type="submit" class="primary-small">적용</button></footer>
    </form>`;
    this.ui.number.showModal();
    this.ui.number.querySelector('input').select();
  }

  applyToolNumber() {
    const edit = this.numberEdit;
    if (!edit) return;
    const value = this.ui.number.querySelector('input').value;
    if (edit.viewScale) {
      const result = scaleSpan(value, this.root.clientHeight);
      if (result.error) {
        this.ui.number.querySelector('.form-error').textContent = `${result.error} 범위: 1:${result.min}~1:${result.max}`;
        return;
      }
      this.tween += 1;
      this.setView({ ...this.view, span: result.span });
      this.ui.number.close();
      return;
    }
    const changes = [];
    let error = '';
    for (const group of edit.groups) {
      const paper = this.papers.find((p) => p.id === group.id);
      if (!paper || JSON.stringify(paper.blocks) !== JSON.stringify(group.blocks)) { error = '입력 중 동이 바뀌었습니다. 닫고 조절할 동을 다시 눌러 주세요.'; break; }
      const result = edit.push ? numericPushBlock(paper.blocks[group.indices[0]], edit.face, value)
        : numericScaleBlocks(paper.blocks, group.indices, edit.center, value);
      if (result.error) { error = result.error; break; }
      const blocks = edit.push ? paper.blocks.map((b, i) => i === group.indices[0] ? result.block : b) : result.blocks;
      if (JSON.stringify(blocks) !== JSON.stringify(paper.blocks)) changes.push({ paper, blocks });
    }
    if (error) { this.ui.number.querySelector('.form-error').textContent = error; return; }
    const before = new Map(changes.map(({ paper }) => [paper.id, paper.blocks]));
    for (const { paper, blocks } of changes) paper.blocks = blocks;
    this.saveBlocks(before);
    this.drawMasses();
    this.ui.number.close();
    this.say(changes.length ? '입력한 수치를 적용했습니다. Ctrl+Z로 되돌릴 수 있습니다.' : '수치가 같아 변경하지 않았습니다.');
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

  tapePoint(event) {
    this.snapEl.hidden = true;
    const fallback = () => this.ground(event.clientX, event.clientY);
    if (!this.gl || event.altKey) return fallback();
    const segments = [];
    const edge = (a, b) => segments.push([a, b]);
    const ring = (points) => points.forEach((p, i) => edge(p, points[(i + 1) % points.length]));
    const frame = this.site?.plan?.frame;
    const papers = this.papers.filter(p => p.kind === 'mass' && (p.id === this.active || this.ghost));
    const preview = this.tray.find(p => p.id === this.preview && p.kind === 'mass');
    if (preview) papers.push(preview);
    for (const paper of papers) for (const b of paper.blocks) {
      const base = blockCorners(frame, b).map(([x, y]) => ({ x, y, z: 0 }));
      ring(base);
      if (riseFor(this.view.tilt) > .01) {
        const top = base.map(p => ({ ...p, z: b.floors * (paper.floor_height || 4.2) }));
        ring(top); base.forEach((p, i) => edge(p, top[i]));
      }
    }
    if (groundFor(this.view.tilt) > .5) {
      for (const parcel of this.site?.plan?.parcels || []) for (const points of parcel.rings) ring(points.map(([x, y]) => ({ x, y, z: 0 })));
      for (const paper of this.papers) {
        if (!isOverlaid(paper, this.home)) continue;
        for (const stroke of paper.strokes || []) for (let i = 1; i < stroke.length; i++) {
          const [x, y] = stroke[i - 1], [bx, by] = stroke[i];
          edge({ x, y, z: 0 }, { x: bx, y: by, z: 0 });
        }
      }
    }
    const rect = this.root.getBoundingClientRect();
    const camera = this.gl.camera;
    this.aimCamera(camera, this.view);
    const project = p => {
      const v = new THREE.Vector3(p.x, p.y, (p.z || 0) * riseFor(this.view.tilt));
      const depth = -v.clone().applyMatrix4(camera.matrixWorldInverse).z;
      v.project(camera);
      return depth > 0 && v.z >= -1 && v.z <= 1 ? { x: (v.x + 1) * rect.width / 2, y: (1 - v.y) * rect.height / 2, w: depth } : null;
    };
    const hit = snapTape({ x: event.clientX - rect.left, y: event.clientY - rect.top }, segments, project);
    if (!hit) return fallback();
    this.snapEl.hidden = false;
    this.snapEl.style.transform = `translate(${hit.screen.x}px, ${hit.screen.y}px)`;
    this.snapEl.querySelector('span').textContent = hit.type;
    return hit.point;
  }

  // A rectangle or the tape measure being drawn on the table (real 3D points).
  drawDraft(points, closed) {
    const d = this.gl.draft;
    d.clear();
    const geom = new THREE.BufferGeometry().setFromPoints(points.map(([x, y, z = 0]) => new THREE.Vector3(x, y, z * riseFor(this.view.tilt) + 0.3)));
    d.add(new (closed ? THREE.LineLoop : THREE.Line)(geom, new THREE.LineBasicMaterial({ color: this.colors.pick, depthTest: false })));
    this.invalidate();
  }

  // A new block (from the rectangle tool, or pasted) goes into the scheme standing in 3D; with
  // none, it starts a new scheme. It is picked.
  async addBlocks(blocks) {
    const paper = this.papers.find((p) => p.id === this.active && p.kind === 'mass');
    if (paper) {
      if (paper.blocks.length + blocks.length > MAX_BLOCKS) { this.say(`한 매스안에는 동이 ${MAX_BLOCKS}개까지입니다.`); return; }
      const before = paper.blocks;
      paper.blocks = [...before, ...blocks];
      this.saveBlocks(new Map([[paper.id, before]]));
      this.pickBlocks(blocks.map((_, k) => blockKey(paper.id, before.length + k)));
      return;
    }
    const [w, h] = PAPER_SIZE.mass;
    const spot = freeSpot(this.papers, this.bounds, w, h);
    const done = await this.hooks.add({ kind: 'mass', title: '새 매스안', floor_height: 4.2, blocks: blocks.slice(0, MAX_BLOCKS), w, h, ...spot });
    if (!done?.paper) return;
    this.record([{ op: 'add', paper: done.paper }]);
    this.showScheme(done.paper.id);
    this.pickBlocks(blocks.map((_, k) => blockKey(done.paper.id, k)));
  }

  // Ctrl+C and Ctrl+V: the picked blocks, pasted 5 m along u and v from where they were.
  copyPicked() {
    this.clip = this.pickedGroups().flatMap((g) => g.indices.map((i) => g.paper.blocks[i]));
    if (this.clip.length) this.say(`동 ${this.clip.length}개를 복사했습니다. Ctrl+V로 붙여 넣습니다.`);
  }

  pasteClip() {
    if (!this.clip?.length) return;
    this.clip = editBlocks(this.clip, this.clip.map((_, i) => i), { du: 5, dv: 5 });
    this.addBlocks(this.clip);
  }

  // Ctrl+A: every block of the scheme standing in 3D.
  pickAll() {
    const paper = this.papers.find((p) => p.id === this.active && p.kind === 'mass');
    if (paper) this.pickBlocks(paper.blocks.map((_, i) => blockKey(paper.id, i)));
  }

  // The gumball on the picked blocks, drawn over the scene: u, v and z arrows, size squares on
  // u and v, and a square in the middle.
  placeGumball() {
    const el = this.gumEl;
    const groups = this.tool === 'select' ? this.pickedGroups() : [];
    const frame = this.site?.plan?.frame;
    const c = blocksCenter(frame, groups.flatMap((g) => g.indices.map((i) => g.paper.blocks[i])));
    this.gumAxes = null;
    if (!c || !this.gl) { el.hidden = true; return; }
    const { camera } = this.gl;
    const w = this.size?.w || this.root.clientWidth;
    const h = this.size?.h || this.root.clientHeight;
    const screen = (x, y, z = 0) => {
      const at = new THREE.Vector3(x, y, z).project(camera);
      return [((at.x + 1) / 2) * w, ((1 - at.y) / 2) * h, at.z];
    };
    const [cx, cy, cz] = screen(c.x, c.y);
    if (cz > 1 || cx < -40 || cx > w + 40 || cy < -40 || cy > h + 40) { el.hidden = true; return; }
    const a = frame?.angle || 0;
    const rise = riseFor(this.view.tilt); // the buildings stand this much of their height
    const axes = {};
    const place = (sel, along, at, size) => {
      const r = el.querySelector(sel);
      r.style.display = along ? '' : 'none';
      if (!along) return;
      r.setAttribute('x', cx + along[0] * at - size / 2);
      r.setAttribute('y', cy + along[1] * at - size / 2);
    };
    for (const [name, [ux, uy, uz]] of [['u', [Math.cos(a), Math.sin(a), 0]], ['v', [-Math.sin(a), Math.cos(a), 0]], ['z', [0, 0, rise]]]) {
      const [tx, ty] = screen(c.x + ux, c.y + uy, uz);
      axes[name] = [tx - cx, ty - cy];
      const len = Math.hypot(...axes[name]);
      const g = el.querySelector(`[data-gumball="${name}"]`);
      const shown = len >= 0.5; // not seen end-on, as z in plan or u or v in an elevation
      g.style.display = shown ? '' : 'none';
      const dir = shown && [axes[name][0] / len, axes[name][1] / len];
      if (name !== 'z') place(`[data-gumball="${name === 'u' ? 'w' : 'd'}"]`, dir, GUMBALL_SCALE_PX, 10);
      if (!shown) continue;
      const [dx, dy] = dir;
      const [ex, ey] = [cx + dx * GUMBALL_PX, cy + dy * GUMBALL_PX];
      for (const line of g.querySelectorAll('line')) {
        line.setAttribute('x1', cx + dx * 12); line.setAttribute('y1', cy + dy * 12);
        line.setAttribute('x2', ex); line.setAttribute('y2', ey);
      }
      const [bx, by] = [ex - dx * 12, ey - dy * 12];
      g.querySelector('polygon').setAttribute('points', `${ex + dx * 4},${ey + dy * 4} ${bx - dy * 6},${by + dx * 6} ${bx + dy * 6},${by - dx * 6}`);
    }
    place('.gb-free', [0, 0], 0, 14);
    this.gumAxes = axes;
    el.hidden = false;
  }

  foldChanged(fold) {
    this.root.classList.toggle('is-3d', fold);
    if (!fold && this.peekId) { this.peekId = ''; this.drawPeek(); }
    if (fold && !this.toldFold && this.pins.size) {
      this.toldFold = true;
      this.say('3D에서는 종이가 이름표로 접힙니다. 이름표를 누르면 내용이 열립니다.');
    }
  }

  // Each pin stands where its paper lies; the open card follows its pin. In plan only the
  // pins of folded papers (`only`) show.
  placePins(only = null) {
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
      const shown = (!only || only.has(id)) && at.z < 1 && x > -40 && x < w + 40 && y > -20 && y < h + 60;
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
    const pick = new THREE.Color(this.colors.pick);
    const build = (paper, faint, tint) => {
      for (const [index, b] of (paper.blocks || []).entries()) {
        const h = b.floors * (paper.floor_height || 4.2);
        const geom = new THREE.BoxGeometry(b.w, b.d, h);
        // A click or a selection box on a building picks that block (not an AI scheme in preview).
        const own = tint ? {} : { paper: paper.id, index };
        const picked = !tint && this.picked.includes(blockKey(paper.id, index));
        if (!faint) {
          const box = new THREE.Mesh(geom, new THREE.MeshLambertMaterial({ color: picked ? pick.clone().lerp(new THREE.Color(this.colors.mass), 0.55) : this.colors.mass }));
          box.position.set(b.u, b.v, h / 2);
          box.rotation.z = ((b.a || 0) * Math.PI) / 180;
          box.castShadow = true;
          box.userData = own;
          g.masses.add(box);
        }
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom),
          new THREE.LineBasicMaterial({ color: picked ? pick : tint || ink, transparent: faint && !picked, opacity: faint && !picked ? (tint ? 0.9 : 0.35) : 1 }));
        edges.position.set(b.u, b.v, h / 2 + 0.05);
        edges.rotation.z = ((b.a || 0) * Math.PI) / 180;
        edges.userData = own;
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

  // Where things show on the screen, for a selection box. papers: each paper itself, or its pin
  // when folded (in 3D, or folded in plan); a tracing laid on the site in 3D has no pin.
  // blocks: each building on the site, by its block key.
  screenBoxes() {
    const fold = folded(this.view.tilt);
    const shut = new Set(foldedInPlan(this.papers, this.home));
    const out = { papers: [], blocks: [] };
    for (const p of this.papers) {
      const el = fold || shut.has(p.id) ? this.pins.get(p.id) : this.slots.get(p.id);
      if (!el || el.hidden) continue;
      const r = el.getBoundingClientRect();
      if (r.width && r.height) out.papers.push({ id: p.id, left: r.left, top: r.top, right: r.right, bottom: r.bottom });
    }
    if (!this.gl) return out;
    const { camera, masses } = this.gl;
    const root = this.root.getBoundingClientRect();
    masses.updateMatrixWorld(true);
    const at = new THREE.Vector3();
    for (const obj of masses.children) {
      if (!obj.userData.paper) continue;
      if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox();
      const { min, max } = obj.geometry.boundingBox;
      const xs = [];
      const ys = [];
      for (const x of [min.x, max.x]) for (const y of [min.y, max.y]) for (const z of [min.z, max.z]) {
        at.set(x, y, z).applyMatrix4(obj.matrixWorld).project(camera);
        xs.push(root.left + ((at.x + 1) / 2) * root.width);
        ys.push(root.top + ((1 - at.y) / 2) * root.height);
      }
      out.blocks.push({ id: blockKey(obj.userData.paper, obj.userData.index), left: Math.min(...xs), top: Math.min(...ys), right: Math.max(...xs), bottom: Math.max(...ys) });
    }
    return out;
  }

  // The block (`paperId#index`) of the building under the pointer ('' when none).
  blockAt(clientX, clientY) {
    return this.blockHit(clientX, clientY)?.key || '';
  }

  // The building under the pointer and which face of it: 'top', or a side 'w+', 'w-', 'd+',
  // 'd-' (its +u, −u, +v, −v face, turned with it). null when none. A solid face wins over an
  // outline (a scheme seen only as outlines gives 'top').
  blockHit(clientX, clientY) {
    if (!this.gl) return null;
    const { camera, masses, raycaster } = this.gl;
    const r = this.root.getBoundingClientRect();
    masses.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), camera);
    const hits = raycaster.intersectObjects(masses.children.filter((o) => o.userData.paper), false);
    const hit = hits.find((h) => h.object.isMesh) || hits[0];
    if (!hit) return null;
    const n = hit.face?.normal;
    const face = !n || n.z > 0.5 || n.z < -0.5 ? 'top' : Math.abs(n.x) > 0.5 ? (n.x > 0 ? 'w+' : 'w-') : (n.y > 0 ? 'd+' : 'd-');
    return { key: blockKey(hit.object.userData.paper, hit.object.userData.index), face, point: hit.point };
  }

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
    const foldButton = overlaid || state.editing ? ''
      : `<button type="button" class="paper-fold" data-fold="${escape(p.id)}" aria-label="${escape(paperName(p))} 이름표로 접기" title="이름표로 접기">접기</button>`;
    if (p.kind === 'note') {
      el.innerHTML = `<article class="${cls}" data-paper="${escape(p.id)}" style="${size}">${madeTag}${foldButton}
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
        ${this.traceSvg(p)}<span class="paper-tag">${escape(paperName(p))}${overlaid ? ' · 덮음' : ''}</span>${foldButton}</article>`;
      return;
    }
    const { title, body } = this.paperContent(p, state.active, state.f);
    el.innerHTML = `<article class="${cls}" data-paper="${escape(p.id)}" style="${size}">${foldButton}
      <header class="paper-head"><span class="paper-kind">${escape(KIND_LABELS[p.kind] || p.kind)}</span>${madeTag}<h3>${escape(title)}</h3>
        <button type="button" class="paper-open" data-inspect="${escape(p.id)}" aria-label="${escape(title)} 상세 보기">상세 보기 ↗</button></header>
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
          ${card ? '' : `<p class="source">${active ? '3D로 보는 안' : '누르면 3D로 세웁니다'} · 상세 보기에서 고칩니다</p>`}`,
      };
    }
    if (p.kind === 'expert') {
      return {
        title: paperName(p),
        body: `<pre class="preview">${escape(resultPreview(p.text))}</pre>
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
      p.folded ? `<button type="button" data-peek="unfold" data-id="${id}">펴기</button>` : '',
      `<button type="button" data-peek="plan" data-id="${id}">평면에서 보기</button>`,
      `<button type="button" data-peek="inspect" data-id="${id}">상세 보기</button>`,
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
        body = `<pre class="preview">${escape(resultPreview(p.text, 5))}</pre>`;
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

  // ------------------------------------------------------------------ the detail panel
  // A click on a paper (or its 상세 보기) opens it at reading size beside the table, whatever the
  // zoom: the site plan with the scheme drawn on it, the figures, a note to write in.

  inspect(id) {
    if (!this.find(id)) return;
    if (this.detailId && this.detailId !== id) this.saveDetailNote();
    this.detailId = id;
    if (this.peekId) { this.peekId = ''; this.drawPins(); this.drawPeek(); }
    this.drawDetail();
    const dialog = this.ui.detail;
    if (!dialog.open) {
      if (typeof dialog.showModal === 'function') dialog.showModal();
      else dialog.setAttribute('open', '');
    }
  }

  closeDetail() {
    this.saveDetailNote();
    this.detailId = '';
    const dialog = this.ui.detail;
    if (dialog.open) dialog.close();
  }

  planSvg(plan) {
    if (!plan) return '';
    const [x0, top, width] = plan.viewBox.split(' ').map(Number);
    const font = Math.max(1.4, plan.size / 42);
    return `<svg class="plan" viewBox="${plan.viewBox}" role="img" aria-label="배치도" style="font-size:${font.toFixed(2)}px">
      ${plan.lots.map((d) => `<path class="lot" d="${d}"/>`).join('')}
      ${plan.blocks.map((b) => `<path class="footprint" d="${b.d}"/><text class="floors" x="${b.x}" y="${b.y}">${escape(String(b.floors))}F</text>`).join('')}
      <g class="north" transform="translate(${(x0 + width - font * 1.6).toFixed(2)} ${(top + font * 2).toFixed(2)})"><path d="M0 ${-font} L${font * 0.6} ${font * 0.6} L0 ${font * 0.2} L${-font * 0.6} ${font * 0.6} Z"/><text y="${font * 1.9}">N</text></g>
      <g class="scalebar"><path d="M${plan.scale.x} ${plan.scale.y} h${plan.scale.length}"/><text x="${plan.scale.x + plan.scale.length / 2}" y="${plan.scale.y - font * 0.6}">${escape(plan.scale.label)}</text></g>
    </svg>`;
  }

  drawDetail() {
    const dialog = this.ui.detail;
    const p = this.find(this.detailId);
    if (!p) { dialog.innerHTML = ''; return; }
    const id = escape(p.id);
    const onTable = this.papers.some((x) => x.id === p.id);
    const made = originLabel(p, this.hooks.experts());
    const where = [DETAIL_KINDS[p.kind] || p.kind, made, onTable ? '' : 'AI 섹션'].filter(Boolean).join(' · ');
    let body = '';
    if (p.kind === 'site') {
      body = `${this.planSvg(planDrawing(this.site))}${this.paperContent(p, false, null, true).body}`;
    } else if (p.kind === 'mass') {
      body = `${this.planSvg(planDrawing(this.site, p))}${this.paperContent(p, this.active === p.id, this.figures[p.id], true).body}
        <p class="detail-caption">층고 ${escape(fmt(p.floor_height ?? 4.2, 1))}m · 수치는 서버가 대지 사실로 계산한 값입니다</p>`;
    } else if (p.kind === 'expert') {
      body = `<pre class="preview">${escape(resultPreview(p.text))}</pre>
        <button type="button" class="paper-link" data-open-expert="${escape(p.agent || '')}">결과 문서 보기 ↗</button>`;
    } else if (p.kind === 'note') {
      body = onTable
        ? `<label class="detail-note">메모 내용<textarea data-detail-note="${id}" maxlength="4000">${escape(p.text || '')}</textarea></label>`
        : `<p class="note-text">${escape(p.text || '메모')}</p>`;
    } else if (p.kind === 'tracing') {
      body = `<div class="detail-tracing">${this.traceSvg(p)}</div><p class="detail-caption">그린 선 ${(p.strokes || []).length}개${isOverlaid(p, this.home) ? ' · 대지 위에 덮여 있음' : ''}</p>`;
    }
    const why = [p.based_on ? `${paperName(this.find(p.based_on)) || p.based_on}의 수정안` : '', p.reason || ''].filter(Boolean)
      .map((t) => `<p class="detail-caption">${escape(t)}</p>`).join('');
    const actions = [
      p.kind === 'mass' && onTable && this.active !== p.id ? `<button type="button" data-detail="show">3D로 세우기</button>` : '',
      p.kind === 'mass' && onTable ? `<button type="button" data-detail="edit">고치기</button>` : '',
      p.folded ? `<button type="button" data-detail="unfold">펴기</button>` : '',
      onTable ? `<button type="button" data-detail="focus">제도판에서 크게 보기</button>` : `<button type="button" data-detail="place">제도판에 놓기</button>`,
    ].join('');
    dialog.innerHTML = `<header class="detail-head"><div><span class="eyebrow">${escape(where)}</span><h2 id="detail-title">${escape(p.kind === 'site' ? '대지 사실' : paperName(p))}</h2></div>
        <button type="button" class="detail-close" data-detail="close" aria-label="상세 보기 닫기">×</button></header>
      <div class="detail-body kind-${escape(p.kind)}">${why}${body}</div>
      <footer class="detail-actions"><div class="detail-more">${actions}</div>
        <button type="button" class="detail-primary" data-detail="ask">이 종이로 질문하기 →</button></footer>`;
  }

  detailAction(action) {
    const id = this.detailId;
    const p = this.find(id);
    if (action === 'close' || !p) { this.closeDetail(); return; }
    switch (action) {
      case 'show': this.showScheme(id); this.drawDetail(); this.showView('3d'); break;
      case 'edit': this.closeDetail(); this.openForm(p); break;
      case 'unfold': this.setFolded(id, false); this.drawDetail(); break;
      case 'focus': this.closeDetail(); this.planAt(p); this.select([id]); break;
      case 'place': this.closeDetail(); this.placeFromTray(id); break;
      case 'ask': this.closeDetail(); if (!this.selected.includes(id)) this.select(toggleSelected(this.selected, id, true)); this.hooks.ask?.(id); break;
      default: break;
    }
  }

  // A note written in the detail panel is saved when it loses focus or the panel closes.
  saveDetailNote() {
    const area = this.ui.detail.querySelector('[data-detail-note]');
    if (area) this.saveNoteText(area.dataset.detailNote, area.value);
  }

  saveNoteText(id, text) {
    const p = this.papers.find((x) => x.id === id);
    if (!p || (p.text || '') === text) return;
    this.record([{ op: 'update', id, before: { text: p.text || '' }, after: { text } }]);
    p.text = text;
    this.drawPaper(p);
    this.drawPins();
    this.save(id, { text });
  }

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

  selectMasses() {
    this.select(massIds({ papers: this.papers }));
    this.setTool('select');
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
      <table><thead><tr><th>동</th><th>가로 m</th><th>세로 m</th><th>층수</th><th>u m</th><th>v m</th><th>회전°</th><th></th></tr></thead>
      <tbody>${f.rows.map((_, i) => `<tr><th>${i + 1}</th>${cell(i, 'w', '가로')}${cell(i, 'd', '세로')}${cell(i, 'floors', '층수')}${cell(i, 'u', 'u')}${cell(i, 'v', 'v')}${cell(i, 'a', '회전')}
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
      const before = this.papers.find((p) => p.id === f.id) || {};
      const change = changedFields({ title: before.title || '', floor_height: before.floor_height ?? 4.2, blocks: before.blocks }, scheme);
      done = await this.hooks.update(f.id, scheme);
      if (done) this.record([{ op: 'update', id: f.id, ...change }]);
    } else {
      const [w, h] = PAPER_SIZE.mass;
      const spot = freeSpot(this.papers, this.bounds, w, h);
      const paper = { kind: 'mass', ...scheme, w, h, ...spot };
      done = await this.hooks.add(paper);
      if (done?.paper) { this.record([{ op: 'add', paper: done.paper }]); this.showScheme(done.paper.id); }
    }
    if (!done) { f.error = '저장하지 못했습니다. 위 알림을 확인해 주세요.'; this.drawForm(); return; }
    this.form = null;
    this.drawForm();
    this.showView('3d');
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

  // Fold a paper into its name tag (in plan too) or open it again; saved with the paper.
  setFolded(id, on) {
    const p = this.papers.find((x) => x.id === id);
    if (!p || Boolean(p.folded) === on) return;
    this.record([{ op: 'update', id, before: { folded: !on }, after: { folded: on } }]);
    if (on) p.folded = true;
    else delete p.folded;
    if (!on && this.peekId === id && !folded(this.view.tilt)) this.peekId = '';
    this.drawPins();
    this.drawPeek();
    if (on && !this.toldPlanFold) {
      this.toldPlanFold = true;
      this.say('접은 종이는 이름표로 남습니다. 이름표를 누르고 [펴기]를 누르면 다시 펼쳐집니다.');
    }
    this.save(id, { folded: on });
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
      this.record([{ op: 'add', paper: done.paper }]);
      this.select([done.paper.id]);
      this.setTool('pen');
      this.animateTo({ tilt: 0 });
      this.say('대지 위에 트레이싱지를 덮었습니다. 펜으로 그린 뒤 종이를 옆으로 끌어내면 떼어집니다.');
    });
  }

  removeSelected() {
    const ids = this.selected.filter((id) => this.papers.some((p) => p.id === id && p.kind !== 'site'));
    if (!ids.length) return;
    this.record(this.papers.filter((p) => ids.includes(p.id)).map((p) => ({ op: 'remove', paper: structuredClone(p) })));
    if (ids.includes(this.detailId)) this.closeDetail();
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

  // ------------------------------------------------------------------ input

  listen() {
    const root = this.root;
    root.addEventListener('wheel', (e) => this.onWheel(e), { passive: false });
    // Focus on a pin at the edge must not scroll the table (older browsers without overflow: clip).
    root.addEventListener('scroll', () => { root.scrollLeft = 0; root.scrollTop = 0; });
    root.addEventListener('pointerdown', (e) => this.onDown(e));
    root.addEventListener('pointermove', (e) => this.onMove(e));
    root.addEventListener('pointerup', () => this.onUp());
    root.addEventListener('pointercancel', () => this.onUp(true));
    root.addEventListener('dblclick', (e) => this.onDouble(e));
    root.addEventListener('contextmenu', (e) => { if (!typing(e.target) && !e.target.closest('dialog')) e.preventDefault(); });
    root.addEventListener('keydown', (e) => this.onKey(e));
    // Ctrl+Z also works while the focus is elsewhere on the page (a button beside the table, or
    // nothing), but never in a text field or another dialog, which keep their own undo.
    this.onWindowKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || !this.root.isConnected || this.root.parentElement?.hidden) return;
      const at = document.activeElement;
      if (this.root.contains(at) || typing(at) || at?.closest?.('dialog')) return;
      this.onKey(e);
    };
    window.addEventListener('keydown', this.onWindowKey);
    root.addEventListener('click', (e) => this.onClick(e));
    root.addEventListener('input', (e) => this.onInput(e));
    root.addEventListener('change', (e) => {
      if (e.target.dataset.ui === 'ghost') { this.ghost = e.target.checked; this.drawMasses(); }
    });
    root.addEventListener('submit', (e) => { e.preventDefault(); if (e.target.dataset.form === 'scheme') this.saveForm(); if (e.target.dataset.form === 'tool-number') this.applyToolNumber(); });
    this.ui.number.addEventListener('close', () => { this.numberEdit = null; this.root.focus({ preventScroll: true }); });
    root.addEventListener('focusout', (e) => {
      // A note being written is saved when it loses focus.
      if (e.target.dataset?.detailNote) { this.saveNoteText(e.target.dataset.detailNote, e.target.value); return; }
      if (e.target.tagName !== 'TEXTAREA' || !this.editing) return;
      const id = this.editing;
      const p = this.papers.find((x) => x.id === id);
      this.editing = '';
      if (p) { this.saveNoteText(id, e.target.value); this.drawPaper(p); }
    });
    const detail = this.ui.detail;
    detail.addEventListener('close', () => { this.saveDetailNote(); this.detailId = ''; });
    detail.addEventListener('click', (e) => {
      // A click on the backdrop (outside the panel) closes it.
      if (e.target !== detail) return;
      const r = detail.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) this.closeDetail();
    });
  }

  onClick(e) {
    const t = e.target.closest('button, [data-open-expert]');
    if (!t) return;
    if (t.dataset.ui === 'view-scale') { this.openViewScale(); return; }
    if (t.dataset.ui === 'number-cancel') { this.ui.number.close(); return; }
    if (t.dataset.openExpert) { this.closeDetail(); this.hooks.openExpert(t.dataset.openExpert); return; }
    if (t.dataset.inspect) { this.select([t.dataset.inspect]); this.inspect(t.dataset.inspect); return; }
    if (t.dataset.detail) { this.detailAction(t.dataset.detail); return; }
    if (t.dataset.tool) { this.setTool(t.dataset.tool); return; }
    if (t.dataset.active) { this.showScheme(t.dataset.active); return; }
    if (t.dataset.fold) { this.setFolded(t.dataset.fold, true); return; }
    if (t.dataset.pin) {
      if (performance.now() < (this.skipClickUntil || 0)) return;
      // A click picks the pin's paper (Shift adds or takes away) and opens its card; a picked pin drags.
      if (e.shiftKey) this.select(toggleSelected(this.selected, t.dataset.pin, true));
      else { if (!this.selected.includes(t.dataset.pin)) this.select([t.dataset.pin]); this.openPeek(t.dataset.pin); }
      return;
    }
    if (t.dataset.peek) {
      this.peekAction(t.dataset.peek, t.dataset.id);
      // The card was redrawn under the pointer: keep the keys (Esc, Delete) on the table.
      if (!this.root.contains(document.activeElement)) this.root.focus({ preventScroll: true });
      return;
    }
    if (t.dataset.tilt) { this.showView(t.dataset.tilt); return; }
    const id = t.dataset.id;
    switch (t.dataset.trayAction) {
      case 'place': this.placeFromTray(id); return;
      case 'discard': if (this.preview === id) { this.preview = ''; this.drawMasses(); } this.hooks.discard(id); return;
      case 'preview': this.preview = this.preview === id ? '' : id; this.drawMasses(); this.drawTray(); if (this.preview) this.showView('3d'); return;
      case 'pick': this.select(toggleSelected(this.selected, id, true)); return;
      default: break;
    }
    switch (t.dataset.ui) {
      case 'scheme-new': this.openForm(); break;
      case 'undo': this.travel('undo'); break;
      case 'redo': this.travel('redo'); break;
      case 'trace': this.layTracing(); break;
      case 'delete': this.removeSelected(); break;
      case 'tray': this.trayOpen = !this.trayOpen; this.drawTray(); this.drawControls(); break;
      case 'north': this.animateTo({ turn: 0 }); break;
      case 'zoom-in': this.animateTo({ span: this.view.span / 1.4 }, 200); break;
      case 'zoom-out': this.animateTo({ span: this.view.span * 1.4 }, 200); break;
      case 'fit': this.fit(); break;
      case 'form-close': this.form = null; this.drawForm(); break;
      case 'row-add': if (this.form.rows.length < 20) { this.form.rows.push({ u: '0', v: '0', w: '20', d: '15', floors: '3', a: '0' }); this.drawForm(); } break;
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
      case 'unfold': this.setFolded(id, false); break;
      case 'inspect': this.inspect(id); break;
      case 'write': this.setFolded(id, false); this.planAt(p, () => { this.editing = id; this.select([id]); }); break;
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
    if (e.target.closest('.tray, .scheme-form, dialog') || typing(e.target)) return;
    e.preventDefault();
    this.hooks.viewMoved?.();
    const v = this.view;
    this.tween += 1;
    const pinch = e.ctrlKey || e.metaKey;
    if (!pinch && e.shiftKey && !e.deltaX) {
      this.setView({ ...v, turn: v.turn + e.deltaY * 0.15 });
    } else if (!pinch && e.deltaX) {
      // A trackpad's two-finger slide: the table goes along with the fingers.
      const a = v.tilt < EDGE_TILT && this.ground(e.clientX, e.clientY);
      const b = a && this.ground(e.clientX + e.deltaX, e.clientY + e.deltaY);
      if (a && b) this.setView({ ...v, x: v.x + (b.x - a.x), y: v.y + (b.y - a.y) });
      else this.setView(panBy(v, -e.deltaX, -e.deltaY, this.root.clientHeight));
    } else {
      // The wheel zooms around the point under the cursor, as in Rhino.
      // Seen near edge-on (an elevation) the table under the cursor is far off or missing: zoom on the middle.
      const g0 = (v.tilt < EDGE_TILT && this.ground(e.clientX, e.clientY)) || v;
      this.setView(zoomAround(v, g0.x, g0.y, wheelZoom(e.deltaY, e.deltaMode, pinch)));
    }
  }

  onDown(e) {
    // Dragging a pin moves its paper straight away, picked or not (2026-11-02 지훈); a picked
    // pin takes the other picked papers along. The pointer is not captured, so a press without
    // a drag stays a click on the pin.
    const pinId = e.button === 0 && !e.shiftKey && e.target.closest('[data-pin]')?.dataset.pin;
    if (pinId) {
      const g0 = this.ground(e.clientX, e.clientY);
      const ids = new Set(this.selected.includes(pinId) ? this.selected.filter((id) => this.papers.some((p) => p.id === id)) : [pinId]);
      if (g0) this.gesture = { kind: 'move', pin: true, g0, ids, id: pinId, shift: false, from: new Map(this.papers.map((q) => [q.id, { x: q.x, y: q.y, overlaid: q.overlaid }])), moved: false, x: e.clientX, y: e.clientY };
      return;
    }
    if (e.target.closest('.table-ui, dialog') || typing(e.target) || e.target.closest('button, a')) return;
    e.preventDefault(); // no text selection while dragging across the panes
    this.root.focus({ preventScroll: true });
    this.root.setPointerCapture(e.pointerId);
    this.tween += 1;
    const v = this.view;
    const grip = e.button === 0 && this.gumAxes && e.target.closest('[data-gumball]')?.dataset.gumball;
    if (grip) { this.gesture = this.gumballGesture(grip, e); return; }
    const mode = dragMode({ button: e.button, shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey, alt: e.altKey });
    if (mode === 'orbit') { this.gesture = { kind: 'orbit', x: e.clientX, y: e.clientY, v }; return; }
    const g0 = this.ground(e.clientX, e.clientY);
    if (mode) { this.gesture = { kind: mode, g0: (v.tilt < EDGE_TILT && g0) || { x: v.x, y: v.y }, edge: v.tilt >= EDGE_TILT || !g0, v, x: e.clientX, y: e.clientY, moved: false, button: e.button }; return; }
    if (e.button !== 0) return;
    if (MODEL_TOOLS.has(this.tool)) { this.gesture = this.modelGesture(e, g0); return; }
    // Empty table (or the sky above it, in a view near edge-on): a selection box, as in Rhino.
    const box = { kind: 'box', x: e.clientX, y: e.clientY, add: e.shiftKey, remove: e.ctrlKey || e.metaKey, moved: false };
    if (!g0) {
      if (this.tool === 'select') this.gesture = box;
      return;
    }
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
        this.record([{ op: 'add', paper: done.paper }]);
        this.editing = done.paper.id;
        this.select([done.paper.id]);
      });
      return;
    }
    const paperId = e.target.closest('[data-paper]')?.dataset.paper;
    const block = !paperId && this.tool === 'select' && this.blockAt(e.clientX, e.clientY);
    if (block) {
      // A click on a building picks that block alone (Shift adds or takes away); dragging it
      // moves the picked blocks on the ground, as an object in Rhino.
      if (e.shiftKey) { this.pickBlocks(this.picked.includes(block) ? this.picked.filter((k) => k !== block) : [...this.picked, block]); return; }
      if (!this.picked.includes(block)) {
        if (this.selected.length) this.select([]);
        const { id } = parseBlockKey(block);
        if (this.active !== id) this.showScheme(id);
        this.pickBlocks([block]);
      }
      this.gesture = this.gumballGesture('free', e);
      return;
    }
    if (paperId) {
      if (!e.shiftKey && this.picked.length) this.pickBlocks([]);
      const next = e.shiftKey || this.selected.includes(paperId) ? (e.shiftKey ? toggleSelected(this.selected, paperId, true) : this.selected) : [paperId];
      if (next !== this.selected) this.select(next);
      const p = this.papers.find((x) => x.id === paperId);
      if (p?.kind === 'mass' && !e.shiftKey && this.active !== paperId) this.showScheme(paperId);
      this.gesture = { kind: 'move', g0, ids: new Set(next), id: paperId, shift: e.shiftKey, from: new Map(this.papers.map((q) => [q.id, { x: q.x, y: q.y, overlaid: q.overlaid }])), moved: false, x: e.clientX, y: e.clientY };
      return;
    }
    this.gesture = box;
  }

  onMove(e) {
    const g = this.gesture;
    if (!g) { if (this.tool === 'tape' && !e.target.closest('.table-ui, dialog')) this.tapePoint(e); else this.snapEl.hidden = true; return; }
    if ((g.kind === 'push' || (g.kind === 'gumball' && g.grip === 'scale')) && Math.hypot(e.clientX - g.x, e.clientY - g.y) >= 3) g.dragged = true;
    // The designer moves the view by hand: the talk popups fold away to keep the view clear.
    if ((g.kind === 'orbit' || g.kind === 'pan' || g.kind === 'zoom') && !g.told && Math.hypot(e.clientX - g.x, e.clientY - g.y) > 6) {
      g.told = true;
      this.hooks.viewMoved?.();
    }
    if (g.kind === 'orbit') {
      // As in Rhino the model turns with the hand: drag right and its near side comes right,
      // drag down and its top comes toward you (the view rises toward a plan).
      this.setView({ ...g.v, ...orbitBy(g.v, e.clientX - g.x, e.clientY - g.y) });
    } else if (g.kind === 'pan') {
      const p = !g.edge && this.ground(e.clientX, e.clientY, g.v);
      if (p) this.setView({ ...g.v, x: g.v.x - (p.x - g.g0.x), y: g.v.y - (p.y - g.g0.y) });
      else if (g.edge) this.setView(panBy(g.v, e.clientX - g.x, e.clientY - g.y, this.root.clientHeight));
      if (Math.hypot(e.clientX - g.x, e.clientY - g.y) > 3) g.moved = true;
    } else if (g.kind === 'gumball') {
      if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) < 3) return;
      let delta = {};
      let up = 0; // metres up, for the z arrow
      const ground = ['free', 'rotate', 'scale'].includes(g.grip);
      const p = ground && g.g0 && this.ground(e.clientX, e.clientY);
      if (ground && !p) return;
      if (g.grip === 'free') {
        delta = frameDelta(this.site?.plan?.frame, p.x - g.g0.x, p.y - g.g0.y);
      } else if (!ground) {
        const m = axisDrag(g.axes[{ w: 'u', d: 'v' }[g.grip] || g.grip], e.clientX - g.x, e.clientY - g.y);
        // A size square widens on both sides, about each block's middle.
        delta = { u: { du: m }, v: { dv: m }, w: { dw: 2 * m }, d: { dd: 2 * m } }[g.grip] || {};
        if (g.grip === 'z') up = m;
      }
      const c = g.center;
      // Rotate: the angle swept about the middle, in 5° steps (Shift: 1°). Scale: how much further
      // from the middle the pointer is than where it started.
      const sweep = g.grip === 'rotate' && snapAngle((Math.atan2(p.y - c.y, p.x - c.x) - Math.atan2(g.g0.y - c.y, g.g0.x - c.x)) * 180 / Math.PI, e.shiftKey ? 1 : 5);
      const r0 = g.grip === 'scale' && Math.hypot(g.g0.x - c.x, g.g0.y - c.y);
      if (g.grip === 'scale' && r0 < 0.5) return;
      const k = g.grip === 'scale' && Math.max(0.05, Math.round((Math.hypot(p.x - c.x, p.y - c.y) / r0) * 100) / 100);
      g.moved = true;
      g.copies = new Map();
      for (const q of this.papers) {
        const from = g.from.get(q.id);
        if (!from) continue;
        if (g.copy) {
          const done = copyBlocks(from.blocks, from.indices, delta.du, delta.dv);
          if (done.blocks.length > MAX_BLOCKS) continue; // too many to copy here: left as it was
          q.blocks = done.blocks;
          g.copies.set(q.id, done.indices);
        } else if (g.grip === 'rotate') q.blocks = turnBlocks(from.blocks, from.indices, g.centerUV, sweep);
        else if (g.grip === 'scale') q.blocks = scaleBlocks(from.blocks, from.indices, g.centerUV, k);
        else q.blocks = editBlocks(from.blocks, from.indices, { ...delta, df: up / (q.floor_height || 4.2) });
      }
      if (g.grip === 'rotate') this.say(`회전 ${sweep}°`);
      if (g.grip === 'scale') this.say(`크기 ${k}배`);
      this.drawMasses();
    } else if (g.kind === 'push') {
      if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) < 3) return;
      g.moved = true;
      const p = this.papers.find((q) => q.id === g.id);
      const m = axisDrag(g.axis, e.clientX - g.x, e.clientY - g.y);
      p.blocks = g.before.map((b, i) => (i === g.index ? pushBlock(b, g.face, m, p.floor_height || 4.2) : b));
      const b = p.blocks[g.index];
      this.say(g.face === 'top' ? `${b.floors}층` : `${fmt(g.face[0] === 'w' ? b.w : b.d, 1)} m`);
      this.drawMasses();
    } else if (g.kind === 'rect' || g.kind === 'tape') {
      const p = g.kind === 'tape' ? this.tapePoint(e) : this.ground(e.clientX, e.clientY);
      if (!p) return;
      g.moved = true;
      const frame = this.site?.plan?.frame;
      if (g.kind === 'tape') {
        this.drawDraft([[g.g0.x, g.g0.y, g.g0.z || 0], [p.x, p.y, p.z || 0]], false);
        this.say(`거리 ${fmt(Math.hypot(p.x - g.g0.x, p.y - g.g0.y, (p.z || 0) - (g.g0.z || 0)), 2)} m${this.snapEl.hidden ? '' : ' · 스냅'}`);
        return;
      }
      g.block = rectBlock(frame, g.g0, p);
      const a = toFrame(frame, g.g0.x, g.g0.y);
      const b = toFrame(frame, p.x, p.y);
      this.drawDraft(blockCorners(frame, { u: (a.u + b.u) / 2, v: (a.v + b.v) / 2, w: Math.abs(b.u - a.u), d: Math.abs(b.v - a.v) }), true);
      this.say(`${fmt(Math.abs(b.u - a.u), 1)} × ${fmt(Math.abs(b.v - a.v), 1)} m`);
    } else if (g.kind === 'erase') {
      const key = this.blockAt(e.clientX, e.clientY);
      if (key && !g.keys.has(key)) { g.keys.add(key); this.pickBlocks([...g.keys]); }
    } else if (g.kind === 'box') {
      if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) < 4) return;
      g.moved = true;
      g.to = { x: e.clientX, y: e.clientY };
      const r = this.root.getBoundingClientRect();
      const el = this.boxEl;
      el.hidden = false;
      el.classList.toggle('is-crossing', boxMode(g, g.to) === 'crossing');
      Object.assign(el.style, {
        left: `${Math.min(g.x, g.to.x) - r.left}px`, top: `${Math.min(g.y, g.to.y) - r.top}px`,
        width: `${Math.abs(g.to.x - g.x)}px`, height: `${Math.abs(g.to.y - g.y)}px`,
      });
    } else if (g.kind === 'zoom') {
      // Drag up to zoom in, down to zoom out, around the point first pressed.
      this.setView(zoomAround(g.v, g.g0.x, g.g0.y, Math.exp((e.clientY - g.y) * 0.005)));
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

  onUp(cancelled = false) {
    const g = this.gesture;
    this.gesture = null;
    if (cancelled && (g?.kind === 'push' || g?.kind === 'gumball')) {
      const before = g.kind === 'push' ? new Map([[g.id, g.before]]) : new Map([...g.from].map(([id, from]) => [id, from.blocks]));
      for (const paper of this.papers) if (before.has(paper.id)) paper.blocks = before.get(paper.id);
      this.drawMasses();
      if (this.pending) { const view = this.pending; this.pending = null; this.setBoard(view); }
      return;
    }
    if (g?.kind === 'draw' && g.points.length > 1) {
      const p = this.papers.find((q) => q.id === g.id);
      if (p) {
        this.record([{ op: 'update', id: p.id, before: { strokes: p.strokes || [] }, after: { strokes: [...(p.strokes || []), g.points] } }]);
        p.strokes = [...(p.strokes || []), g.points];
        this.syncPapers();
        this.save(p.id, { strokes: p.strokes });
      }
    } else if (g?.kind === 'gumball' && g.moved) {
      this.saveBlocks(new Map([...g.from].map(([id, f]) => [id, f.blocks])));
      // A copy leaves the copies picked, as in SketchUp.
      if (g.copies?.size) this.pickBlocks([...g.copies].flatMap(([id, indices]) => indices.map((i) => blockKey(id, i))));
    } else if (g?.kind === 'push' && g.moved) {
      this.saveBlocks(new Map([[g.id, g.before]]));
    } else if (numericToolClick(g, cancelled)) {
      this.openToolNumber(g);
    } else if (g?.kind === 'rect') {
      this.gl.draft.clear();
      this.invalidate();
      if (g.block) this.addBlocks([g.block]);
      else if (g.moved) this.say('가로·세로가 1m 이상이 되게 그려 주세요.');
    } else if (g?.kind === 'erase') {
      if (g.keys.size) this.removeBlocks([...g.keys]);
    } else if (g?.kind === 'box') {
      this.boxEl.hidden = true;
      // A box picks the papers and the buildings it holds (or touches); a plain click on empty
      // table picks nothing.
      if (g.moved) {
        const boxes = this.screenBoxes();
        this.pickBlocks(boxPick(this.picked, g, g.to, boxes.blocks, { ...g, limit: Infinity }));
        this.select(boxPick(this.selected, g, g.to, boxes.papers, g));
      } else if (!g.add && !g.remove) {
        if (this.selected.length) this.select([]);
        if (this.picked.length) this.pickBlocks([]);
      }
    } else if (g?.kind === 'move' && g.moved) {
      const edits = [];
      for (const q of this.papers) {
        if (!g.ids.has(q.id)) continue;
        const was = g.from.get(q.id);
        const changes = { x: q.x, y: q.y };
        const before = { x: was.x, y: was.y };
        if (q.kind === 'tracing') { q.overlaid = isOverlaid(q, this.home); changes.overlaid = q.overlaid; before.overlaid = Boolean(was.overlaid); }
        edits.push({ op: 'update', id: q.id, before, after: changes });
        this.save(q.id, changes);
      }
      this.record(edits);
      this.syncPapers();
      if (g.ids.size === 1) {
        const p = this.papers.find((q) => g.ids.has(q.id));
        if (p?.kind === 'tracing') this.say(isOverlaid(p, this.home) ? `${paperName(p)}을(를) 대지 위에 다시 덮었습니다.` : `${paperName(p)}을(를) 떼어냈습니다. 옆에 두고 보거나, 다시 대지 위로 끌어 덮으세요.`);
      }
    }
    // A pin dragged: the click that ends the drag must not open its card.
    if (g?.kind === 'move' && g.pin && g.moved) this.skipClickUntil = performance.now() + 400;
    if (g?.kind === 'move' && !g.moved && !g.shift && !g.pin) {
      // A click on a paper: it alone is picked, and opens at reading size (a note is written in place).
      const p = this.papers.find((q) => q.id === g.id);
      if (p && this.selected.length > 1) this.select([p.id]);
      if (p && p.kind !== 'note') this.inspect(p.id);
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
  }

  onKey(e) {
    if (typing(e.target) || e.target.closest?.('dialog')) return;
    const k = e.key.toLowerCase();
    if ((e.metaKey || e.ctrlKey) && (k === 'z' || k === 'y')) {
      e.preventDefault();
      this.travel(k === 'y' || e.shiftKey ? 'redo' : 'undo');
      return;
    }
    if ((e.metaKey || e.ctrlKey) && !e.altKey && ['c', 'v', 'a'].includes(k)) {
      // Copy, paste and pick-all work on the blocks, as in SketchUp.
      if (k === 'c' && this.picked.length) { e.preventDefault(); this.copyPicked(); }
      if (k === 'v' && this.clip?.length) { e.preventDefault(); this.pasteClip(); }
      if (k === 'a') { e.preventDefault(); this.pickAll(); }
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    // No letter or number shortcuts (2026-11-02 지훈): a word typed on the table goes to the
    // command line (app.js). Only Delete and Esc act here.
    if (k === 'delete' || k === 'backspace') { e.preventDefault(); if (this.picked.length) this.removePicked(); else this.removeSelected(); }
    else if (k === 'escape') {
      if (this.peekId) { this.peekId = ''; this.drawPins(); this.drawPeek(); return; }
      this.select([]);
      if (this.picked.length) this.pickBlocks([]);
      this.setTool('select');
    }
  }
}

