// 모형 판: a model board laid on the loaded 3D range, cut in place layer by layer (the server's
// sida/model_base/board.py). Renders into any element, so the drawing table (the 모형 바닥
// button) and an expert's page can both hold it.
//
// A top view of the range on a canvas (the ground shaded by height, roads, pavements and water,
// contours, buildings, the site) with the board's frame on it; the frame is dragged to move the
// board. 판 크기, 축척, 방향 and 두께 change it; 범위에 맞추기 asks the server for the scale that
// fills the range; 계산하기 gets the exact layers and sheets; 레이저 파일 받기 downloads the zip.
// The server keeps the last settings for the project (GET .../model-base/settings).
import {
  MODEL_BOARDS, BOARD_SCALES, BOARD_THICKNESSES, BOARD_ORIENTS, DEFAULT_BOARD, OUTSIDE,
  boardInfo, boardInfoText, boardBody, boardCenter, frameSize, mapFit, rangeHalf,
} from './board-model.js';

const COLORS = {
  g: [214, 206, 186], r: [190, 190, 196], s: [226, 222, 214], w: [170, 196, 222],
  contour: 'rgba(110, 90, 60, 0.45)', building: 'rgba(70, 70, 76, 0.75)', site: '#c0392b',
  frame: '#1f6feb', outside: '#d1242f', rangeEdge: 'rgba(0, 0, 0, 0.35)',
};
const MAP_W = 460;

const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export class ModelMaker {
  // hooks: { around() -> Promise<surroundings|null>, site() -> site|null, range() -> Promise<range>,
  //   settings() -> Promise<settings>, fit(params) -> Promise<{scale, center, frame_m}>,
  //   plan(body) -> Promise<plan>, files(body) -> Promise<summary>, stepped?(interval) -> Promise }
  constructor(host, hooks) {
    this.host = host;
    this.hooks = hooks;
    this.s = { ...DEFAULT_BOARD };
    this.range = null;
    this.around = null;
    this.summary = null; // the server's numbers for the settings as they are (cleared on a change)
    this.busy = '';
    this.note = '';
    this.drag = null;
    this.custom = { scale: false, thickness: false }; // 직접 입력 picked for the scale or the thickness
    this.host.classList.add('model-maker');
    this.host.innerHTML = `<canvas class="mm-map" width="${MAP_W}" height="${MAP_W}" aria-label="3D 범위 위의 모형 판 (끌어서 옮기기)"></canvas>
      <div class="mm-form"></div>
      <p class="mm-info" role="status"></p>
      <div class="mm-actions">
        <button type="button" data-mm="fit">범위에 맞추기</button>
        <button type="button" data-mm="plan">계산하기</button>
        <button type="button" class="primary-small" data-mm="files">레이저 파일 받기</button>
        ${hooks.stepped ? '<button type="button" data-mm="stepped">계단식 보기</button>' : ''}
      </div>
      <p class="mm-note" role="status"></p>`;
    this.canvas = this.host.querySelector('.mm-map');
    this.form = this.host.querySelector('.mm-form');
    this.info = this.host.querySelector('.mm-info');
    this.noteEl = this.host.querySelector('.mm-note');
    this.host.addEventListener('click', (e) => this.onClick(e));
    this.host.addEventListener('change', (e) => this.onChange(e));
    this.canvas.addEventListener('pointerdown', (e) => this.onDown(e));
    this.canvas.addEventListener('pointermove', (e) => this.onMove(e));
    this.canvas.addEventListener('pointerup', (e) => this.onUp(e));
    this.canvas.addEventListener('pointercancel', (e) => this.onUp(e));
  }

  // Read the range, the surroundings and the kept settings, and draw.
  async open() {
    this.say('3D 범위를 읽는 중…');
    try {
      const [range, kept] = await Promise.all([this.hooks.range(), this.hooks.settings().catch(() => null)]);
      this.range = range;
      if (kept) this.s = { ...DEFAULT_BOARD, ...kept };
      this.around = await this.hooks.around();
      this.say(this.around ? '' : '3D 범위를 불러오지 못했습니다. 제도판의 "주변 3D"를 먼저 켜 보세요.');
    } catch (error) {
      this.say(error.message);
    }
    this.draw();
  }

  // Put the settings an expert recommended ({board, scale, orient, thickness}) on the panel.
  apply(rec) {
    if (!rec) return;
    const next = { ...this.s };
    if (MODEL_BOARDS.some((b) => b.key === rec.board)) next.board = rec.board;
    if (Number(rec.scale) > 0) next.scale = Math.round(Number(rec.scale));
    if (rec.orient === 'landscape' || rec.orient === 'portrait') next.orient = rec.orient;
    const t = Number(rec.thickness ?? rec.thickness_mm);
    if (t > 0) next.thickness_mm = t;
    next.center = null; // the site's middle
    this.custom = { scale: !BOARD_SCALES.includes(next.scale), thickness: !BOARD_THICKNESSES.includes(next.thickness_mm) };
    this.change(next);
    this.say('추천한 판을 놓았습니다. 범위를 벗어나면 빨갛게 보입니다.');
  }

  say(text) { this.note = text; if (this.noteEl) this.noteEl.textContent = text; }

  change(next) {
    this.s = next;
    this.summary = null;
    this.draw();
  }

  get site() { return this.hooks.site?.() || null; }

  draw() {
    this.drawForm();
    this.drawMap();
    const info = boardInfo(this.s, { range: this.range, site: this.site, terrain: this.around?.terrain, groundElev: this.around?.ground_elev });
    this.info.textContent = boardInfoText(info, this.summary);
    this.info.classList.toggle('mm-bad', Boolean(info && info.overflow > 0));
    for (const b of this.host.querySelectorAll('[data-mm]')) b.disabled = Boolean(this.busy) || (b.dataset.mm !== 'fit' && Boolean(info?.overflow > 0 || !info));
    const files = this.host.querySelector('[data-mm="files"]');
    if (files) files.textContent = this.busy === 'files' ? '만드는 중…' : '레이저 파일 받기';
    const plan = this.host.querySelector('[data-mm="plan"]');
    if (plan) plan.textContent = this.busy === 'plan' ? '계산하는 중…' : '계산하기';
  }

  drawForm() {
    const s = this.s;
    const scaleIn = !this.custom.scale && BOARD_SCALES.includes(Number(s.scale));
    const thickIn = !this.custom.thickness && BOARD_THICKNESSES.includes(Number(s.thickness_mm));
    const pick = (name, label, items, value) => `<label>${label} <select data-field="${name}">${items.map((o) => `<option value="${esc(o.key)}" ${String(o.key) === String(value) ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select></label>`;
    this.form.innerHTML = `${pick('board', '판 크기', MODEL_BOARDS, s.board)}
      ${s.board === 'custom' ? `<label>가로 <input data-field="width_mm" type="number" min="100" max="3000" step="10" value="${esc(s.width_mm ?? '')}"> mm</label>
        <label>세로 <input data-field="height_mm" type="number" min="100" max="3000" step="10" value="${esc(s.height_mm ?? '')}"> mm</label>` : ''}
      ${pick('scale', '축척', [...BOARD_SCALES.map((n) => ({ key: n, label: `1:${n}` })), { key: 'custom', label: '직접 입력' }], scaleIn ? s.scale : 'custom')}
      ${scaleIn ? '' : `<label>1: <input data-field="scale_custom" type="number" min="50" max="5000" step="10" value="${esc(s.scale)}"></label>`}
      ${pick('orient', '방향', BOARD_ORIENTS, s.orient)}
      ${pick('thickness_mm', '두께', [...BOARD_THICKNESSES.map((n) => ({ key: n, label: `${n} mm` })), { key: 'custom', label: '직접 입력' }], thickIn ? s.thickness_mm : 'custom')}
      ${thickIn ? '' : `<label><input data-field="thickness_custom" type="number" min="0.5" max="20" step="0.5" value="${esc(s.thickness_mm)}"> mm</label>`}
      <label class="mm-check"><input type="checkbox" data-field="save_material" ${s.save_material ? 'checked' : ''}> 재료 아끼기 <small>(위층도 모아 자르기)</small></label>`;
  }

  // ---------------------------------------------------------------- the map
  get fitBox() { return mapFit(this.range, this.canvas.width, this.canvas.height); }

  toPx([x, y]) { const f = this.fitBox; return [(x - f.west) * f.k, (f.north - y) * f.k]; }

  toM(px, py) { const f = this.fitBox; return [px / f.k + f.west, f.north - py / f.k]; }

  drawMap() {
    const c = this.canvas;
    const { hx, hy } = rangeHalf(this.range);
    c.height = Math.round(MAP_W * Math.min(1.4, Math.max(0.5, hy / hx)));
    const g = c.getContext('2d');
    if (!g) return;
    g.clearRect(0, 0, c.width, c.height);
    const t = this.around?.terrain;
    if (t) {
      let lo = Infinity; let hi = -Infinity;
      for (const z of t.z) { lo = Math.min(lo, z); hi = Math.max(hi, z); }
      const span = Math.max(1e-6, hi - lo);
      const f = this.fitBox;
      const cell = t.step * f.k + 0.6;
      for (let j = 0; j < t.n; j += 1) {
        for (let i = 0; i < t.n; i += 1) {
          const k = j * t.n + i;
          const cls = t.classes?.[k] || 'g';
          if (cls === OUTSIDE) continue;
          const shade = 0.78 + 0.22 * ((t.z[k] - lo) / span);
          const [r, gg, b] = (COLORS[cls] || COLORS.g).map((v) => Math.round(v * shade));
          g.fillStyle = `rgb(${r},${gg},${b})`;
          const [px, py] = this.toPx([t.min + i * t.step, t.min + j * t.step]);
          g.fillRect(px - cell / 2, py - cell / 2, cell, cell);
        }
      }
    }
    const line = (pts, closed) => {
      if (!pts?.length) return;
      g.beginPath();
      pts.forEach((p, i) => { const [x, y] = this.toPx(p); if (i) g.lineTo(x, y); else g.moveTo(x, y); });
      if (closed) g.closePath();
    };
    g.lineWidth = 0.8;
    g.strokeStyle = COLORS.contour;
    for (const ct of this.around?.contours || []) { line(ct.points, false); g.stroke(); }
    g.fillStyle = COLORS.building;
    for (const b of [...(this.around?.buildings || []), ...(this.around?.unknown_buildings || [])]) {
      if (!b.outline) continue;
      line(b.outline, true); g.fill();
    }
    g.strokeStyle = COLORS.site;
    g.lineWidth = 2;
    for (const p of this.site?.plan?.parcels || []) for (const r of p.rings || []) { line(r, true); g.stroke(); }
    // the range's edge
    g.strokeStyle = COLORS.rangeEdge;
    g.lineWidth = 1;
    g.setLineDash([4, 3]);
    const { round } = rangeHalf(this.range);
    if (round) {
      const [cx, cy] = this.toPx([0, 0]);
      g.beginPath(); g.arc(cx, cy, hx * this.fitBox.k, 0, Math.PI * 2); g.stroke();
    } else { line([[-hx, -hy], [hx, -hy], [hx, hy], [-hx, hy]], true); g.stroke(); }
    g.setLineDash([]);
    // the board
    const frame = frameSize(this.s);
    if (!frame) return;
    const [cx, cy] = boardCenter(this.s, this.site);
    const info = boardInfo(this.s, { range: this.range, site: this.site });
    const corners = [[cx - frame[0] / 2, cy - frame[1] / 2], [cx + frame[0] / 2, cy - frame[1] / 2],
      [cx + frame[0] / 2, cy + frame[1] / 2], [cx - frame[0] / 2, cy + frame[1] / 2]];
    g.strokeStyle = info?.overflow > 0 ? COLORS.outside : COLORS.frame;
    g.fillStyle = info?.overflow > 0 ? 'rgba(209, 36, 47, 0.10)' : 'rgba(31, 111, 235, 0.10)';
    g.lineWidth = 2.5;
    line(corners, true); g.fill(); g.stroke();
  }

  // ---------------------------------------------------------------- dragging the board
  onDown(e) {
    const frame = frameSize(this.s);
    if (!frame || !this.range) return;
    const r = this.canvas.getBoundingClientRect();
    const sx = this.canvas.width / r.width;
    const [mx, my] = this.toM((e.clientX - r.left) * sx, (e.clientY - r.top) * sx);
    const [cx, cy] = boardCenter(this.s, this.site);
    if (Math.abs(mx - cx) > frame[0] / 2 || Math.abs(my - cy) > frame[1] / 2) return;
    this.drag = { id: e.pointerId, from: [mx, my], center: [cx, cy], scale: sx, rect: r };
    this.canvas.setPointerCapture?.(e.pointerId);
  }

  onMove(e) {
    if (!this.drag || e.pointerId !== this.drag.id) return;
    const { rect, scale } = this.drag;
    const [mx, my] = this.toM((e.clientX - rect.left) * scale, (e.clientY - rect.top) * scale);
    const center = [this.drag.center[0] + mx - this.drag.from[0], this.drag.center[1] + my - this.drag.from[1]];
    this.s = { ...this.s, center };
    this.summary = null;
    this.draw();
  }

  onUp(e) {
    if (!this.drag || e.pointerId !== this.drag.id) return;
    this.drag = null;
  }

  // ---------------------------------------------------------------- the form and the actions
  onChange(e) {
    const field = e.target.dataset.field;
    if (!field) return;
    const v = e.target.type === 'checkbox' ? e.target.checked : e.target.value;
    const next = { ...this.s };
    if (field === 'board') next.board = v;
    if (field === 'width_mm' || field === 'height_mm') next[field] = Number(v) || null;
    if (field === 'scale') { this.custom.scale = v === 'custom'; if (v !== 'custom') next.scale = Number(v); }
    if (field === 'scale_custom') next.scale = Math.round(Number(v)) || this.s.scale;
    if (field === 'orient') next.orient = v;
    if (field === 'thickness_mm') { this.custom.thickness = v === 'custom'; if (v !== 'custom') next.thickness_mm = Number(v); }
    if (field === 'thickness_custom') next.thickness_mm = Number(v) || this.s.thickness_mm;
    if (field === 'save_material') next.save_material = Boolean(v);
    this.change(next);
  }

  async onClick(e) {
    const what = e.target.closest('[data-mm]')?.dataset.mm;
    if (!what || this.busy) return;
    if (what === 'fit') await this.run('fit', async () => {
      const got = await this.hooks.fit({ board: this.s.board, thickness: this.s.thickness_mm, orient: this.s.orient,
        width: this.s.width_mm, height: this.s.height_mm });
      this.s = { ...this.s, scale: got.scale, center: got.center };
      this.custom.scale = false;
      return `범위에 맞췄습니다: 1:${got.scale}, 판 범위 ${Math.round(got.frame_m[0])}×${Math.round(got.frame_m[1])} m`;
    });
    if (what === 'plan') await this.run('plan', async () => {
      this.summary = await this.hooks.plan(boardBody(this.s, boardCenter(this.s, this.site)));
      return '계산했습니다.';
    });
    if (what === 'files') await this.run('files', async () => {
      const summary = await this.hooks.files(boardBody(this.s, boardCenter(this.s, this.site)));
      if (summary?.sheets) this.summary = summary;
      return `받았습니다: 판 ${summary?.sheets ?? '?'}장 · 조각 ${summary?.pieces ?? '?'}개`;
    });
    if (what === 'stepped' && this.hooks.stepped) await this.run('stepped', async () => {
      const info = boardInfo(this.s, {});
      const on = await this.hooks.stepped(info.interval);
      return on ? `제도판에 ${info.interval} m 간격 계단식 지형을 보였습니다. 한 번 더 누르면 끕니다.` : '계단식 지형을 껐습니다.';
    });
  }

  async run(what, fn) {
    this.busy = what;
    this.say('');
    this.draw();
    try {
      this.say(await fn());
    } catch (error) {
      this.say(error.message);
    }
    this.busy = '';
    this.draw();
  }
}
