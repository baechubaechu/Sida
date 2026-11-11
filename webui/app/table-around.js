// The site's surroundings in 3D (ground, roads, nearby buildings), the range menu, and the
// stepped ground of the laser-cut model.
// Methods of DraftingTable (table.js adds them to its prototype).

import * as THREE from './vendor/three.js';
import { escapeHtml as escape } from './model.js';
import { viewFor, blockCorners, RANGE_SIZES, RANGE_SHAPES, RANGE_ORIENTS, DEFAULT_RANGE, parseRange, OUTSIDE, terrainFaces, GROUND_COLORS, aroundLegend, contourLines, aroundNote, isEstimate, massBase, paintTriangles, PAINT_COLORS, treeTriangles, TREE_COLORS } from './board-model.js';

export const aroundMethods = {
  // ------------------------------------------------------------------ the site's surroundings

  // 모형 바닥: the representation planner's 모형 tab (the model board panel and its advice);
  // 계단식: the ground stepped as the kept board settings would cut it.
  modelMenu() {
    return `<button type="button" data-ui="model-panel" title="표현 계획자의 모형 탭: 모형 판 크기·축척을 정해 레이저 커팅 파일 받기">모형 바닥</button>
      <button type="button" data-ui="model-stepped" aria-pressed="${this.steppedOn}" title="저장한 모형 판 설정(축척 × 두께) 간격으로 계단식 지형 보기">계단식</button>`;
  },
  async toggleStepped() {
    let interval = this.stepInterval || 1.5;
    try {
      const s = await this.hooks.modelSettings?.();
      if (s) interval = Math.round(Number(s.thickness_mm) * Number(s.scale)) / 1000;
    } catch { /* the last height stays */ }
    await this.showStepped(interval);
  },
  // 계단식 보기 at this step height (m): the stepped ground in place of the smooth one; asked
  // again for the same height, the smooth ground comes back. True when the steps are shown.
  async showStepped(interval) {
    if (this.steppedOn && this.stepInterval === interval) { // asked again: the smooth ground
      this.steppedOn = false;
      this.drawAround();
      this.drawControls();
      return false;
    }
    if (!this.aroundOn) await this.toggleAround();
    if (!this.aroundOn || !this.hooks.modelBase) return false;
    this.stepInterval = interval;
    await this.loadStepped();
    return this.steppedOn;
  },
  async loadStepped() {
    if (!this.hooks.modelBase) return;
    try {
      this.stepped = await this.hooks.modelBase(this.stepInterval || 1.5, this.aroundRange);
      this.steppedOn = true;
    } catch (error) {
      this.say(error.message);
    }
    this.drawAround();
    this.drawControls();
  },
  // 범위, 모양 and (for a rectangle) 방향 for the surroundings, beside the 주변 3D button.
  rangeSelects() {
    this.readRange();
    const r = this.aroundRange || DEFAULT_RANGE;
    const off = this.aroundBusy ? 'disabled' : '';
    const pick = (ui, label, items, value) => `<label class="check">${label} <select data-ui="${ui}" aria-label="주변 ${label}" ${off}>${items.map((s) => `<option value="${s.key}" ${s.key === value ? 'selected' : ''}>${s.label}</option>`).join('')}</select></label>`;
    return `${pick('around-size', '범위', RANGE_SIZES, r.size)}
      ${pick('around-shape', '모양', RANGE_SHAPES, r.shape)}
      ${r.shape === 'rect' ? pick('around-orient', '방향', RANGE_ORIENTS, r.orient) : ''}
      ${this.modelMenu()}`;
  },
  // A new range (size, shape, orient): kept for the project, and the surroundings made again if shown.
  async changeRange(change) {
    const range = { ...(this.aroundRange || DEFAULT_RANGE), ...change };
    this.aroundRange = range;
    try {
      if (this.hooks.saveRange) await this.hooks.saveRange(range);
    } catch (error) {
      this.say(`범위를 저장하지 못했습니다. ${error.message}`);
    }
    const shown = this.aroundOn;
    const stepped = this.steppedOn;
    this.around = null;
    this.aroundOn = false;
    this.stepped = null;
    this.steppedOn = false;
    if (shown) await this.toggleAround();
    else this.drawControls();
    if (shown && stepped) await this.loadStepped();
  },
  // The project's range, read once (for the selects before the surroundings are fetched).
  async readRange() {
    if (this.aroundRange || this.aroundRangeAsked || !this.hooks.range) return;
    this.aroundRangeAsked = true;
    try {
      const range = await this.hooks.range();
      if (!this.aroundRange) this.aroundRange = parseRange(range);
      this.aroundWanted = range?.shown === true;
      if (Array.isArray(range?.hidden_parts)) this.setAroundParts(range.hidden_parts, { save: false });
      this.drawControls();
      this.restoreAround();
    } catch { /* the defaults stay */ }
  },
  // The surroundings are meant to be on (saved so, or turned on here) but are not: put them back
  // once the site is known, without moving the view. Also after a board read that briefly came
  // without the site (which takes them away). Not again after they failed to load, until the
  // designer turns them on.
  restoreAround() {
    if (!this.aroundWanted || this.aroundFailed || this.aroundOn || this.aroundBusy || !this.site?.plan) return;
    this.toggleAround({ restore: true });
  },
  // Show or hide the ground and buildings around the site; the first time they are fetched.
  async toggleAround({ restore = false } = {}) {
    if (this.aroundBusy) return;
    if (this.aroundOn) {
      this.aroundOn = false;
      this.aroundWanted = false;
      this.hooks.saveShown?.(false);
      this.drawAround(); this.drawMasses(); this.drawControls();
      return;
    }
    if (!this.site?.plan) { this.say('먼저 대지를 조회하세요. 대지 경계가 있어야 주변을 놓을 수 있습니다.'); return; }
    if (!this.around && this.hooks.context) {
      const request = Symbol();
      this.aroundRequest = request;
      this.aroundBusy = true;
      this.drawControls();
      try {
        const context = await this.hooks.context(this.aroundRange);
        if (request !== this.aroundRequest) return;
        this.around = context;
        this.aroundRange = parseRange(context);
      } catch (error) {
        if (request !== this.aroundRequest) return;
        this.aroundFailed = restore; // a restore that failed is not tried again by itself
        this.say(`주변 지형·건물을 불러오지 못했습니다. ${error.message}`);
      }
      this.aroundBusy = false;
    }
    this.aroundOn = Boolean(this.around);
    if (this.aroundOn) { this.aroundWanted = true; this.aroundFailed = false; }
    if (this.aroundOn && !restore) this.hooks.saveShown?.(true);
    this.drawAround();
    this.drawMasses();
    this.drawControls();
    // Lean the table and step back so the whole neighbourhood is in view around the site (not
    // when they come back after a reload: the view stays as it opens).
    if (this.aroundOn && !restore) {
      this.animateTo({ ...(viewFor('3d', this.view) || {}), x: 0, y: 0, span: Math.max(this.view.span, 1.6 * this.around.radius) });
    }
  },
  // The ground coloured by what it is, the contour lines, and each building standing on it with
  // its foundation down to the lowest ground under it; buildings of unknown height as a line only.
  drawAround() {
    if (!this.gl) return;
    const { around } = this.gl;
    around.traverse((o) => o.geometry?.dispose());
    around.clear();
    const data = this.aroundOn ? this.around : null;
    this.drawAroundLegend(data);
    this.aroundLow = 0;
    if (!data) { this.invalidate(); return; }
    const t = data.terrain;
    if (this.steppedOn && this.stepped) this.drawSteps(around);
    if (t && !(this.steppedOn && this.stepped)) {
      // A plane with one vertex per ground point (three.js lays its rows from the top, north),
      // lifted to the heights and coloured by what the ground is.
      const { n } = t;
      const span = (n - 1) * t.step;
      const geom = new THREE.PlaneGeometry(span, span, n - 1, n - 1);
      const pos = geom.getAttribute('position');
      const col = pos.clone();
      const c = new THREE.Color();
      for (let r = 0; r < n; r += 1) {
        const j = n - 1 - r;
        for (let i = 0; i < n; i += 1) {
          const k = j * n + i;
          const v = r * n + i;
          pos.setXYZ(v, t.min + i * t.step, t.min + j * t.step, t.z[k]);
          c.setHex(GROUND_COLORS[t.classes?.[k]] ?? GROUND_COLORS.g);
          col.setXYZ(v, c.r, c.g, c.b);
          this.aroundLow = Math.min(this.aroundLow, t.z[k]);
        }
      }
      geom.setAttribute('color', col);
      if (t.classes?.includes(OUTSIDE)) geom.setIndex(terrainFaces(t)); // a round or oblong range: the cells inside
      geom.computeVertexNormals();
      const ground = new THREE.Mesh(geom, new THREE.MeshLambertMaterial({ vertexColors: true }));
      ground.receiveShadow = true;
      ground.userData.part = 'ground';
      around.add(ground);
      for (const line of contourLines(t, this.contourStep)) {
        const pts = line.segments.flatMap(([x1, y1, x2, y2]) => [new THREE.Vector3(x1, y1, line.z + 0.05), new THREE.Vector3(x2, y2, line.z + 0.05)]);
        const contour = new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(pts),
          new THREE.LineBasicMaterial({ color: line.index ? 0x7d6b4a : 0xb7a988 }));
        contour.userData.part = 'contours';
        around.add(contour);
      }
    }
    if (data.road_marks && !(this.steppedOn && this.stepped)) this.drawPaint(around, data.road_marks);
    if (data.trees && !(this.steppedOn && this.stepped)) this.drawTrees(around, data.trees);
    const lineOf = (points, material) => new THREE.Line(
      new THREE.BufferGeometry().setFromPoints(points.map(([x, y, z]) => new THREE.Vector3(x, y, z))), material);
    const touch = new THREE.LineBasicMaterial({ color: 0x5f646b });
    const edgeInk = new THREE.LineBasicMaterial({ color: 0x9aa0a6 });
    for (const b of data.buildings || []) {
      // Walls from the bottom of the foundation to the top, and a flat roof.
      const ring = b.outline;
      const partOf = b.on_site ? 'onsite' : isEstimate(b) ? 'estimated' : 'buildings';
      const add = (obj) => { obj.userData.part = partOf; around.add(obj); };
      const material = new THREE.MeshLambertMaterial({
        color: isEstimate(b) ? 0xe8d6b0 : 0xedede9, transparent: b.on_site, opacity: b.on_site ? 0.35 : 1,
      });
      const walls = [];
      ring.forEach(([x1, y1], k) => {
        const [x2, y2] = ring[(k + 1) % ring.length];
        const a = new THREE.Vector3(x1, y1, b.base), bb = new THREE.Vector3(x2, y2, b.base);
        const at = new THREE.Vector3(x1, y1, b.top), bt = new THREE.Vector3(x2, y2, b.top);
        walls.push(a, bb, bt, a, bt, at);
      });
      const wallGeom = new THREE.BufferGeometry().setFromPoints(walls);
      wallGeom.computeVertexNormals();
      const roof = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(ring.map(([x, y]) => new THREE.Vector2(x, y)))), material);
      roof.position.z = b.top;
      for (const part of [new THREE.Mesh(wallGeom, material), roof]) {
        part.userData.building = b; // a click on it tells where its height and outline came from
        part.castShadow = !b.on_site;
        part.receiveShadow = true;
        add(part);
      }
      const corners = ring.flatMap(([x, y]) => [new THREE.Vector3(x, y, b.base), new THREE.Vector3(x, y, b.top)]);
      add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(corners), edgeInk));
      add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(ring.map(([x, y]) => new THREE.Vector3(x, y, b.top + 0.02))), edgeInk));
      if (b.ground_line) add(lineOf(b.ground_line, touch));
    }
    const unknown = new THREE.LineBasicMaterial({ color: 0xc8742f });
    for (const b of data.unknown_buildings || []) {
      if (!b.ground_line) continue;
      const line = lineOf(b.ground_line, unknown);
      line.userData.part = 'unknown';
      around.add(line);
    }
    this.showAroundParts();
    this.invalidate();
  },
  // The lane lines and road marks of the 정밀도로지도, filled at their real width just above the
  // drawn ground (not on the stepped ground, whose plates are at other heights).
  drawPaint(group, paint) {
    const tri = paintTriangles(paint);
    const add = (obj, part, count) => { obj.userData.part = part; obj.userData.count = count; group.add(obj); };
    const fill = (positions, color) => {
      const geom = new THREE.BufferGeometry();
      geom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      geom.computeVertexNormals();
      const mesh = new THREE.Mesh(geom, new THREE.MeshLambertMaterial({
        color, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
      }));
      mesh.receiveShadow = true;
      return mesh;
    };
    let first = true; // the count goes on one object of each part, so the panel shows lines, not meshes
    for (const [color, positions] of Object.entries(tri.lines)) {
      if (!positions.length) continue;
      add(fill(positions, PAINT_COLORS[color] ?? PAINT_COLORS.white), 'lanes', first ? tri.counts.lanes : 0);
      first = false;
    }
    if (tri.marks.length) add(fill(tri.marks, PAINT_COLORS.white), 'marks', tri.counts.marks);
    if (tri.outlines.length) {
      const geom = new THREE.BufferGeometry();
      geom.setAttribute('position', new THREE.Float32BufferAttribute(tri.outlines, 3));
      add(new THREE.LineSegments(geom, new THREE.LineBasicMaterial({ color: PAINT_COLORS.white })), 'marks', tri.marks.length ? 0 : tri.counts.marks);
    }
  },
  // The street trees set out by the rule (표현용), on the drawn ground like the paint.
  drawTrees(group, trees) {
    const tri = treeTriangles(trees);
    const mesh = (positions, color) => {
      const geom = new THREE.BufferGeometry();
      geom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
      geom.computeVertexNormals();
      const m = new THREE.Mesh(geom, new THREE.MeshLambertMaterial({ color }));
      m.castShadow = true;
      m.receiveShadow = true;
      m.userData.part = 'trees';
      return m;
    };
    if (!tri.count) return;
    const crowns = mesh(tri.crowns, TREE_COLORS.crown);
    crowns.userData.count = tri.count; // the panel counts trees, not meshes
    const trunks = mesh(tri.trunks, TREE_COLORS.trunk);
    trunks.userData.count = 0;
    group.add(crowns, trunks);
  },
  // The parts the shown surroundings have ([{id, count}], for the 레이어 panel's sublayers).
  aroundParts() {
    if (!this.aroundOn || !this.around || !this.gl) return [];
    const counts = new Map();
    for (const obj of this.gl.around.children) {
      const part = obj.userData.part;
      if (part) counts.set(part, (counts.get(part) || 0) + (obj.userData.count ?? 1));
    }
    if (this.steppedOn && this.stepped) counts.set('ground', counts.get('ground') || 1); // the stepped ground stands in
    const per = { buildings: 4, estimated: 4, onsite: 4 }; // walls, roof and two edge lines a building
    return [...counts].map(([id, n]) => ({ id, count: Math.round(n / (per[id] || 1)) }));
  },
  // Turn parts of the surroundings off or on (the 레이어 panel), kept for the project.
  setAroundParts(hidden, { save = true } = {}) {
    this.aroundPartsHidden = new Set(hidden);
    this.showAroundParts();
    this.invalidate();
    if (save) this.hooks.saveAroundParts?.([...this.aroundPartsHidden]);
  },
  // At eye level the building on the site follows the 지금 건물 / 매스안 choice instead, solid
  // when shown (on the table it is see-through, so a mass inside it shows).
  showAroundParts() {
    const hidden = this.aroundPartsHidden || new Set();
    for (const obj of this.gl?.around.children || []) {
      const part = obj.userData.part || (this.steppedOn ? 'ground' : '');
      obj.visible = part === 'onsite' && this.eye ? this.eyeBefore : !hidden.has(part);
      if (part === 'onsite' && obj.isMesh && obj.material.transparent !== !this.eye) {
        obj.material.transparent = !this.eye;
        obj.material.opacity = this.eye ? 1 : 0.35;
        obj.material.needsUpdate = true;
      }
    }
  },
  // The colour legend in one line at the bottom right while the surroundings are shown (where the
  // data comes from is in the settings' 자료 출처, not over the drawing: 2026-11-09 지훈).
  drawAroundLegend(data) {
    const el = this.ui.aroundLegend;
    el.hidden = !data;
    if (!data) return;
    const hex = (k) => `#${GROUND_COLORS[k].toString(16).padStart(6, '0')}`;
    el.innerHTML = aroundLegend(data).map(([k, name]) => (GROUND_COLORS[k] === undefined
      ? `<span><i class="${k}"></i>${escape(name)}</span>` : `<span><i style="background:${hex(k)}"></i>${escape(name)}</span>`)).join('');
  },
  // The surroundings' legend and where each part comes from, for the settings' 자료 출처 section
  // (2026-11-09 지훈: not over the table): {legend: [[key, name, colour or '']], lines}, or null
  // while the surroundings are not shown.
  aroundInfo() {
    const data = this.aroundOn ? this.around : null;
    if (!data) return null;
    const hex = (k) => (GROUND_COLORS[k] === undefined ? '' : `#${GROUND_COLORS[k].toString(16).padStart(6, '0')}`);
    return { legend: aroundLegend(data).map(([k, name]) => [k, name, hex(k)]), lines: aroundNote(data) };
  },
  // How high a block stands: on the lowest ground under it while the surroundings are shown
  // (the same rule as the export), else on the table (0).
  blockBase(frame, b) {
    return massBase(blockCorners(frame, b), this.aroundOn ? this.around?.terrain : null);
  },
  // The stepped ground (계단식 보기): each step a flat plate at its height with its outline.
  drawSteps(group) {
    const tones = [0xe7dcc6, 0xd9cdb4];
    const ink = new THREE.LineBasicMaterial({ color: 0x8a7a5c });
    this.stepped.steps.forEach((step, k) => {
      const material = new THREE.MeshLambertMaterial({ color: tones[k % 2], side: THREE.DoubleSide });
      for (const poly of step.polygons) {
        const shape = new THREE.Shape(poly.outline.map(([x, y]) => new THREE.Vector2(x, y)));
        for (const hole of poly.holes || []) shape.holes.push(new THREE.Path(hole.map(([x, y]) => new THREE.Vector2(x, y))));
        const plate = new THREE.Mesh(new THREE.ShapeGeometry(shape), material);
        plate.position.z = step.top;
        plate.receiveShadow = true;
        group.add(plate);
        group.add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(poly.outline.map(([x, y]) => new THREE.Vector3(x, y, step.top + 0.02))), ink));
      }
      this.aroundLow = Math.min(this.aroundLow, step.bottom);
    });
  },
  // The building around the site under the pointer (while the surroundings are shown), or null.
  aroundBuildingAt(clientX, clientY) {
    if (!this.gl || !this.aroundOn) return null;
    const { camera, around, raycaster } = this.gl;
    const r = this.root.getBoundingClientRect();
    around.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), camera);
    const hit = raycaster.intersectObjects(around.children.filter((o) => o.userData.building), false)[0];
    return hit?.object.userData.building || null;
  }
};
