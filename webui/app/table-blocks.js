// The buildings on the site (blocks of a mass): picking them, the gumball, SketchUp-style
// tools, numeric input, the tape, the mass form, and drawing the masses in 3D.
// Methods of DraftingTable (table.js adds them to its prototype).

import * as THREE from './vendor/three.js';
import { escapeHtml as escape } from './model.js';
import { PX, PAPER_SIZE, riseFor, groundFor, scaleSpan, isOverlaid, blockCorners, freeSpot, folded, foldedInPlan, paperName, readScheme, schemeRows, parseBlockKey, fmt, GUMBALL_PX, GUMBALL_SCALE_PX, editBlocks, blocksCenter, blockKey, pickedBlocks, toFrame, MAX_BLOCKS, numericPushBlock, numericScaleBlocks, snapTape, massIds, changedFields } from './board-model.js';

export const blocksMethods = {
  // The picked blocks, grouped by scheme, of the schemes that stand on the site.
  pickedGroups() {
    return pickedBlocks(this.papers, this.picked).filter((g) => g.paper.id === this.active || this.ghost);
  },
  pickBlocks(keys) {
    this.picked = keys;
    this.drawMasses();
  },
  // The gumball (or a building) taking hold: what the drag edits, the picked blocks as they were.
  gumballGesture(grip, e) {
    const from = new Map(this.pickedGroups().map((g) => [g.paper.id, { blocks: g.paper.blocks, indices: g.indices }]));
    return { kind: 'gumball', grip, axes: this.gumAxes, g0: this.ground(e.clientX, e.clientY), x: e.clientX, y: e.clientY, moved: false, from };
  },
  // Delete takes the picked blocks out of their schemes; a scheme keeps at least one.
  removePicked() {
    this.removeBlocks(this.picked);
  },
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
  },
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
  },
  // A block taken by a tool or a click: it alone is picked, and its scheme stands in 3D.
  takeBlock(key) {
    if (this.selected.length) this.select([]);
    const { id } = parseBlockKey(key);
    if (this.active !== id) this.showScheme(id);
    this.pickBlocks([key]);
  },
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
  },
  // Where one metre out of a block's face goes on the screen: up for the top, else square to
  // the side, turned with the block and the site.
  faceAxis(b, face) {
    const frame = this.site?.plan?.frame || { x: 0, y: 0, angle: 0 };
    const [mx, my] = blockCorners(frame, { ...b, w: 0, d: 0 })[0];
    const z0 = this.blockBase(frame, b); // the block stands on the ground under it (massBase)
    let dir = [0, 0, riseFor(this.view.tilt)];
    if (face !== 'top') {
      const t = frame.angle + ((b.a || 0) * Math.PI) / 180 + (face[0] === 'd' ? Math.PI / 2 : 0);
      const sign = face[1] === '+' ? 1 : -1;
      dir = [sign * Math.cos(t), sign * Math.sin(t), 0];
    }
    const { camera } = this.gl;
    const r = this.root.getBoundingClientRect();
    const at = (x, y, z) => { const p = new THREE.Vector3(x, y, z).project(camera); return [((p.x + 1) / 2) * r.width, ((1 - p.y) / 2) * r.height]; };
    const [ax, ay] = at(mx, my, z0);
    const [bx, by] = at(mx + dir[0], my + dir[1], z0 + dir[2]);
    return [bx - ax, by - ay];
  },
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
  },
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
  },
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
      const outline = blockCorners(frame, b);
      const z = this.blockBase(frame, b);
      const base = outline.map(([x, y]) => ({ x, y, z }));
      ring(base);
      if (riseFor(this.view.tilt) > .01) {
        const top = base.map(p => ({ ...p, z: z + b.floors * (paper.floor_height || 4.2) }));
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
  },
  // A rectangle or the tape measure being drawn on the table (real 3D points).
  drawDraft(points, closed) {
    const d = this.gl.draft;
    d.clear();
    const geom = new THREE.BufferGeometry().setFromPoints(points.map(([x, y, z = 0]) => new THREE.Vector3(x, y, z * riseFor(this.view.tilt) + 0.3)));
    d.add(new (closed ? THREE.LineLoop : THREE.Line)(geom, new THREE.LineBasicMaterial({ color: this.colors.pick, depthTest: false })));
    this.invalidate();
  },
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
  },
  // Ctrl+C and Ctrl+V: the picked blocks, pasted 5 m along u and v from where they were.
  copyPicked() {
    this.clip = this.pickedGroups().flatMap((g) => g.indices.map((i) => g.paper.blocks[i]));
    if (this.clip.length) this.say(`동 ${this.clip.length}개를 복사했습니다. Ctrl+V로 붙여 넣습니다.`);
  },
  pasteClip() {
    if (!this.clip?.length) return;
    this.clip = editBlocks(this.clip, this.clip.map((_, i) => i), { du: 5, dv: 5 });
    this.addBlocks(this.clip);
  },
  // Ctrl+A: every block of the scheme standing in 3D.
  pickAll() {
    const paper = this.papers.find((p) => p.id === this.active && p.kind === 'mass');
    if (paper) this.pickBlocks(paper.blocks.map((_, i) => blockKey(paper.id, i)));
  },
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
  },
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
        const base = this.blockBase(frame, b);
        const geom = new THREE.BoxGeometry(b.w, b.d, h);
        // A click or a selection box on a building picks that block (not an AI scheme in preview).
        const own = tint ? {} : { paper: paper.id, index };
        const picked = !tint && this.picked.includes(blockKey(paper.id, index));
        if (!faint) {
          const box = new THREE.Mesh(geom, new THREE.MeshLambertMaterial({ color: picked ? pick.clone().lerp(new THREE.Color(this.colors.mass), 0.55) : this.colors.mass }));
          box.position.set(b.u, b.v, base + h / 2);
          box.rotation.z = ((b.a || 0) * Math.PI) / 180;
          box.castShadow = true;
          box.userData = own;
          g.masses.add(box);
        }
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom),
          new THREE.LineBasicMaterial({ color: picked ? pick : tint || ink, transparent: faint && !picked, opacity: faint && !picked ? (tint ? 0.9 : 0.35) : 1 }));
        edges.position.set(b.u, b.v, base + h / 2 + 0.05);
        edges.rotation.z = ((b.a || 0) * Math.PI) / 180;
        edges.userData = own;
        g.masses.add(edges);
        if (!faint) {
          const tag = document.createElement('div');
          tag.className = 'floor-tag';
          tag.textContent = `${b.floors}F`;
          const obj = new THREE.CSS3DObject(tag);
          const [cx, cy] = blockCorners(frame, { ...b, w: 0, d: 0 })[0];
          obj.position.set(cx, cy, base + 0.2);
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
  },
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
  },
  // The block (`paperId#index`) of the building under the pointer ('' when none).
  blockAt(clientX, clientY) {
    return this.blockHit(clientX, clientY)?.key || '';
  },
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
  },
  selectMasses() {
    this.select(massIds({ papers: this.papers }));
    this.setTool('select');
  },
  // ------------------------------------------------------------------ the scheme form

  openForm(paper = null) {
    this.form = { id: paper?.id || '', title: paper?.title || '', floorHeight: String(paper?.floor_height ?? 4.2), rows: schemeRows(paper), error: '' };
    this.drawForm();
  },
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
  },
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
  },
  // The scheme that stands in 3D.
  showScheme(id) {
    this.active = id;
    this.drawMasses();
    this.drawControls();
    this.syncPapers();
  }
};
