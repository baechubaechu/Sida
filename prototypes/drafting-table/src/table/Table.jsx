// The drafting table (제도판): one surface at real scale. The site sits in the middle, sheets of
// paper lie around it, and tilting the table turns the plan into an axonometric and then a
// perspective. Masses rise as the table leans. Tracing paper laid on the site snaps into register;
// dragged aside it becomes a sheet of its own.
import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import * as THREE from 'three';
import { CSS3DRenderer, CSS3DObject } from 'three/examples/jsm/renderers/CSS3DRenderer.js';
import { SITE, SITE_BOUNDS, SITE_ANGLE, MASS_ORIGIN, FLOOR_HEIGHT, SCHEMES, blockFootprint } from '../shared/geometry.js';
import { Paper, PX, TRACE_HOME } from './Papers.jsx';
import { TILT, MAX_TILT, cameraFor, riseFor, zoomAround, drawingScale, lerpView } from './view.js';

const SNAP = 7; // metres: a tracing sheet this close to its place on the site clicks into register
const css = (name, fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
const typing = (el) => el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.isContentEditable);
const atHome = (p) => p.kind === 'tracing' && Math.hypot(p.x - TRACE_HOME.x, p.y - TRACE_HOME.y) < 0.01;
// Where a remark about a scheme points: just north of its tallest block, seen from the north.
function pinFor(schemeId, label) {
  const tallest = SCHEMES[schemeId].blocks.reduce((a, c) => (c.floors > a.floors ? c : a));
  const north = [...blockFootprint(tallest)].sort((p, q) => q[1] - p[1]).slice(0, 2);
  return { x: (north[0][0] + north[1][0]) / 2, y: (north[0][1] + north[1][1]) / 2 + 6, turn: 180, label, scheme: schemeId };
}

let seq = 0;
const newId = (k) => `${k}-${Date.now().toString(36)}-${(seq += 1)}`;
const TOOLS = [
  { id: 'select', label: '선택', key: 'v', icon: '↖' },
  { id: 'note', label: '메모', key: 'n', icon: '▤' },
  { id: 'pen', label: '펜', key: 'p', icon: '✎' },
];

export const Table = forwardRef(function Table({ initialPapers, onSelection }, ref) {
  const host = useRef(null);
  const gl = useRef(null);
  const [papers, setPapers] = useState(initialPapers);
  const [pins, setPins] = useState([]);
  const [view, setView] = useState({ x: TRACE_HOME.x + 20, y: TRACE_HOME.y, span: 260, tilt: 0, turn: 0 });
  const [scheme, setScheme] = useState('A');
  const [ghost, setGhost] = useState(false);
  const [tool, setTool] = useState('select');
  const [selected, setSelected] = useState(() => new Set());
  const [editing, setEditing] = useState('');
  const [draft, setDraft] = useState(null); // { id: tracing id, points }
  const [hint, setHint] = useState('');
  const [size, setSize] = useState({ w: 800, h: 600 });
  const live = useRef({});
  live.current = { papers, pins, view, scheme, selected, tool };
  const slots = useRef(new Map()); // paper id → the DOM element CSS3D places on the table
  const pinLayer = useRef(null); // pins float over the scene and follow their spot on the ground
  const gesture = useRef(null);
  const tween = useRef(0);
  const hintTimer = useRef(0);

  const slot = (id) => {
    if (!slots.current.has(id)) { const d = document.createElement('div'); d.className = 'slot'; slots.current.set(id, d); }
    return slots.current.get(id);
  };

  // ------------------------------------------------------------------ scene
  useEffect(() => {
    const el = host.current;
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.domElement.className = 'table-gl';
    el.appendChild(renderer.domElement);
    const cssRenderer = new CSS3DRenderer();
    cssRenderer.domElement.className = 'table-css';
    el.appendChild(cssRenderer.domElement);

    const scene = new THREE.Scene();
    scene.background = new THREE.Color(css('--table', '#e9ecee'));
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
    scene.add(sun);
    scene.add(sun.target);

    // The table keeps its own colour; a separate catcher only darkens where shadows fall.
    scene.add(new THREE.Mesh(new THREE.PlaneGeometry(6000, 6000), new THREE.MeshBasicMaterial({ color: css('--table', '#e9ecee') })));
    const catcher = new THREE.Mesh(new THREE.PlaneGeometry(1200, 1200), new THREE.ShadowMaterial({ opacity: 0.22 }));
    catcher.position.z = 0.01;
    catcher.receiveShadow = true;
    scene.add(catcher);
    const grid = new THREE.GridHelper(2000, 200, css('--line', '#d9dfe4'), css('--line', '#d9dfe4'));
    grid.rotation.x = Math.PI / 2;
    grid.position.z = 0.02;
    scene.add(grid);

    const lot = new THREE.Color(css('--lot', '#cf3f2e'));
    for (const p of SITE) {
      const shape = new THREE.Shape(p.local.map(([x, y]) => new THREE.Vector2(x, y)));
      const fill = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({ color: lot, transparent: true, opacity: 0.08, depthWrite: false }));
      fill.position.z = 0.04;
      scene.add(fill);
      const line = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(p.local.map(([x, y]) => new THREE.Vector3(x, y, 0.08))),
        new THREE.LineDashedMaterial({ color: lot, dashSize: 2.4, gapSize: 1.2 }));
      line.computeLineDistances();
      scene.add(line);
    }
    const masses = new THREE.Group();
    masses.position.set(MASS_ORIGIN[0], MASS_ORIGIN[1], 0);
    masses.rotation.z = SITE_ANGLE;
    scene.add(masses);
    const traces = new THREE.Group();
    scene.add(traces);
    const labels = [];

    gl.current = { renderer, cssRenderer, scene, cssScene, camera, masses, traces, labels, objects: new Map(), raycaster: new THREE.Raycaster() };

    const resize = () => {
      const w = el.clientWidth || 1;
      const h = el.clientHeight || 1;
      renderer.setSize(w, h);
      cssRenderer.setSize(w, h);
      camera.aspect = w / h;
      setSize({ w, h });
    };
    const ro = new ResizeObserver(resize);
    ro.observe(el);
    resize();

    let frame = 0;
    const tick = () => {
      const v = live.current.view;
      const c = cameraFor(v);
      camera.fov = c.fov;
      camera.near = c.dist * 0.05;
      camera.far = c.dist * 20;
      camera.position.set(...c.position);
      camera.up.set(...c.up);
      camera.lookAt(...c.target);
      camera.updateProjectionMatrix();
      const rise = riseFor(v.tilt);
      masses.scale.z = rise;
      for (const l of labels) l.element.style.opacity = rise < 0.25 ? String(1 - rise * 4) : '0';
      // An overlaid tracing reads as paper in plan; once the table leans its lines lie on the ground.
      const flat = v.tilt < 8;
      traces.visible = !flat;
      for (const [id, obj] of gl.current.objects) {
        const p = live.current.papers.find((x) => x.id === id);
        if (p && atHome(p)) { obj.element.style.opacity = flat ? '1' : '0'; obj.element.style.pointerEvents = flat ? '' : 'none'; }
      }
      for (const node of pinLayer.current?.children || []) {
        const pin = live.current.pins.find((x) => x.id === node.dataset.pin);
        if (!pin) continue;
        const q = new THREE.Vector3(pin.x, pin.y, 0).project(camera);
        node.style.transform = `translate(${((q.x + 1) / 2) * el.clientWidth}px, ${((1 - q.y) / 2) * el.clientHeight}px)`;
        node.hidden = q.z > 1;
      }
      renderer.render(scene, camera);
      cssRenderer.render(cssScene, camera);
      frame = requestAnimationFrame(tick);
    };
    tick();
    return () => { cancelAnimationFrame(frame); ro.disconnect(); renderer.dispose(); el.replaceChildren(); };
  }, []);

  // ------------------------------------------------------------------ masses for the chosen scheme (+ a ghost of the other)
  useEffect(() => {
    const g = gl.current;
    g.masses.clear();
    for (const l of g.labels.splice(0)) g.cssScene.remove(l);
    const ink = new THREE.Color(css('--ink', '#1f2a33'));
    const build = (sch, faint) => {
      for (const b of sch.blocks) {
        const h = b.floors * FLOOR_HEIGHT;
        const geom = new THREE.BoxGeometry(b.w, b.d, h);
        if (!faint) {
          const box = new THREE.Mesh(geom, new THREE.MeshLambertMaterial({ color: css('--mass', '#e8ebee') }));
          box.position.set(b.u, b.v, h / 2);
          box.castShadow = true;
          g.masses.add(box);
        }
        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geom), new THREE.LineBasicMaterial({ color: ink, transparent: faint, opacity: faint ? 0.35 : 1 }));
        edges.position.set(b.u, b.v, h / 2 + 0.05);
        g.masses.add(edges);
        if (!faint) {
          const tag = document.createElement('div');
          tag.className = 'floor-tag';
          tag.textContent = `${b.floors}F`;
          const obj = new CSS3DObject(tag);
          const c = Math.cos(SITE_ANGLE); const s = Math.sin(SITE_ANGLE);
          obj.position.set(MASS_ORIGIN[0] + b.u * c - b.v * s, MASS_ORIGIN[1] + b.u * s + b.v * c, 0.2);
          obj.scale.setScalar(PX);
          g.cssScene.add(obj);
          g.labels.push(obj);
        }
      }
    };
    build(SCHEMES[scheme], false);
    if (ghost) for (const [id, s] of Object.entries(SCHEMES)) if (id !== scheme) build(s, true);
  }, [scheme, ghost]);

  // ------------------------------------------------------------------ papers and pins on the table
  useEffect(() => {
    const g = gl.current;
    const want = new Map(papers.map((p) => [p.id, p]));
    for (const [id, obj] of g.objects) {
      if (!want.has(id)) { g.cssScene.remove(obj); g.objects.delete(id); slots.current.delete(id); }
    }
    for (const [id, item] of want) {
      let obj = g.objects.get(id);
      if (!obj) {
        obj = new CSS3DObject(slot(id));
        obj.scale.setScalar(PX);
        g.cssScene.add(obj);
        g.objects.set(id, obj);
      }
      obj.position.set(item.x, item.y, item.kind === 'tracing' ? 0.3 : 0.1);
    }
    // Overlaid tracings as ground lines (seen when the table leans).
    g.traces.clear();
    const mat = new THREE.LineBasicMaterial({ color: css('--pen', '#2b5d8a') });
    for (const p of papers) {
      if (!atHome(p)) continue;
      for (const s of p.strokes) g.traces.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(s.map(([x, y]) => new THREE.Vector3(x, y, 0.15))), mat));
    }
  }, [papers]);

  useEffect(() => {
    onSelection(papers.filter((p) => selected.has(p.id)));
  }, [papers, selected, onSelection]);

  // ------------------------------------------------------------------ view helpers
  const ground = useCallback((clientX, clientY, v = live.current.view) => {
    const g = gl.current;
    const r = host.current.getBoundingClientRect();
    const cam = new THREE.PerspectiveCamera(0, r.width / r.height, 1, 50000);
    const c = cameraFor(v);
    cam.fov = c.fov; cam.near = c.dist * 0.05; cam.far = c.dist * 20;
    cam.position.set(...c.position); cam.up.set(...c.up); cam.lookAt(...c.target); cam.updateProjectionMatrix(); cam.updateMatrixWorld();
    g.raycaster.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), cam);
    const hit = new THREE.Vector3();
    return g.raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), 0), hit) ? { x: hit.x, y: hit.y } : null;
  }, []);

  const animateTo = useCallback((target, ms = 450) => {
    const from = live.current.view;
    const start = performance.now();
    const id = (tween.current += 1);
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const step = (now) => {
      if (id !== tween.current) return;
      const t = reduce ? 1 : Math.min(1, (now - start) / ms);
      setView(lerpView(from, { ...from, ...target }, 1 - (1 - t) ** 3));
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }, []);

  const fit = useCallback(() => {
    const items = live.current.papers.map((p) => ({ x0: p.x - (p.w * PX) / 2, x1: p.x + (p.w * PX) / 2, y0: p.y - (p.h * PX) / 2, y1: p.y + (p.h * PX) / 2 }));
    const b = SITE_BOUNDS;
    const x0 = Math.min(b.minX, ...items.map((i) => i.x0)); const x1 = Math.max(b.maxX, ...items.map((i) => i.x1));
    const y0 = Math.min(b.minY, ...items.map((i) => i.y0)); const y1 = Math.max(b.maxY, ...items.map((i) => i.y1));
    const r = host.current.getBoundingClientRect();
    animateTo({ x: (x0 + x1) / 2, y: (y0 + y1) / 2, span: Math.max(y1 - y0, ((x1 - x0) * r.height) / r.width) * 1.12, tilt: 0, turn: 0 });
  }, [animateTo]);

  useEffect(() => { const t = setTimeout(fit, 50); return () => clearTimeout(t); }, [fit]);

  const say = (text) => { setHint(text); clearTimeout(hintTimer.current); hintTimer.current = setTimeout(() => setHint(''), 4000); };

  const layTracing = useCallback(() => {
    const { papers: ps } = live.current;
    const covering = ps.find(atHome);
    if (covering) { setSelected(new Set([covering.id])); setTool('pen'); say(`${covering.title}이(가) 이미 대지 위에 있습니다. 그 위에 그리세요.`); return; }
    const n = ps.filter((p) => p.kind === 'tracing').length + 1;
    const sheet = { id: newId('tracing'), kind: 'tracing', title: `트레이싱 ${n}`, strokes: [], x: TRACE_HOME.x, y: TRACE_HOME.y, w: TRACE_HOME.w, h: TRACE_HOME.h };
    setPapers([...ps, sheet]);
    setSelected(new Set([sheet.id]));
    setTool('pen');
    animateTo({ tilt: 0 });
    say('대지 위에 트레이싱지를 덮었습니다. 펜으로 그린 뒤 종이를 옆으로 끌어내면 떼어집니다.');
  }, [animateTo]);

  useImperativeHandle(ref, () => ({
    addExpert(card, label) {
      const pin = pinFor(live.current.scheme, label);
      const ps = live.current.papers;
      const east = Math.max(SITE_BOUNDS.maxX, ...ps.map((p) => p.x + (p.w * PX) / 2));
      const paper = { ...card, x: east + 4 + (card.w * PX) / 2, y: SITE_BOUNDS.maxY - (card.h * PX) / 2 };
      setPapers([...ps, paper]);
      if (pin) setPins((list) => [...list, { ...pin, id: newId('pin'), kind: 'pin', paper: paper.id }]);
      setSelected(new Set([paper.id]));
      animateTo({ x: (paper.x + TRACE_HOME.x) / 2, y: TRACE_HOME.y, span: 200, tilt: 0, turn: 0 });
    },
    focusCard(id) {
      const p = live.current.papers.find((x) => x.id === id);
      if (!p) return;
      setSelected(new Set([id]));
      animateTo({ x: p.x, y: p.y, span: Math.max(60, p.h * PX * 1.6), tilt: 0, turn: 0 });
    },
  }), [animateTo]);

  // ------------------------------------------------------------------ input
  useEffect(() => {
    const el = host.current;
    const onWheel = (e) => {
      if (typing(e.target)) return;
      e.preventDefault();
      const v = live.current.view;
      tween.current += 1;
      if (e.ctrlKey || e.metaKey) {
        const g0 = ground(e.clientX, e.clientY);
        if (g0) setView(zoomAround(v, g0.x, g0.y, Math.exp(e.deltaY * 0.01)));
      } else if (e.shiftKey && !e.deltaX) {
        setView({ ...v, turn: v.turn + e.deltaY * 0.15 });
      } else {
        const a = ground(e.clientX, e.clientY);
        const b = ground(e.clientX + e.deltaX, e.clientY + e.deltaY);
        if (a && b) setView({ ...v, x: v.x + (b.x - a.x), y: v.y + (b.y - a.y) });
      }
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [ground]);

  const down = (e) => {
    if (e.target.closest('.table-ui') || typing(e.target)) return;
    e.preventDefault(); // no text selection while dragging across the panes
    const { view: v, tool: t, papers: ps, selected: sel } = live.current;
    host.current.setPointerCapture(e.pointerId);
    tween.current += 1;
    if (e.button === 2 || e.altKey) { gesture.current = { kind: 'orbit', x: e.clientX, y: e.clientY, v }; return; }
    const g0 = ground(e.clientX, e.clientY);
    if (!g0) return;
    const pinId = e.target.closest('[data-pin]')?.dataset.pin;
    if (pinId) {
      const pin = live.current.pins.find((p) => p.id === pinId);
      setScheme(pin.scheme);
      animateTo({ x: pin.x, y: pin.y, span: 110, tilt: 52, turn: pin.turn }, 700);
      return;
    }
    if (t === 'pen') {
      const sheet = [...ps].reverse().find((p) => p.kind === 'tracing' && Math.abs(g0.x - p.x) <= (p.w * PX) / 2 && Math.abs(g0.y - p.y) <= (p.h * PX) / 2);
      if (!sheet) { say('트레이싱지 위에만 그릴 수 있습니다. 먼저 [트레이싱지 덮기]를 누르세요.'); return; }
      const off = { x: sheet.x - TRACE_HOME.x, y: sheet.y - TRACE_HOME.y };
      gesture.current = { kind: 'draw', id: sheet.id, off, points: [[g0.x - off.x, g0.y - off.y]] };
      setDraft({ id: sheet.id, points: gesture.current.points });
      return;
    }
    if (t === 'note') {
      e.preventDefault();
      const note = { id: newId('note'), kind: 'note', text: '', x: g0.x, y: g0.y, w: 200, h: 140 };
      setPapers([...ps, note]);
      setSelected(new Set([note.id]));
      setEditing(note.id);
      setTool('select');
      return;
    }
    const paperId = e.target.closest('[data-paper]')?.dataset.paper;
    if (paperId) {
      let next = sel;
      if (e.shiftKey) { next = new Set(sel); if (next.has(paperId)) next.delete(paperId); else next.add(paperId); } else if (!sel.has(paperId)) next = new Set([paperId]);
      setSelected(next);
      gesture.current = { kind: 'move', g0, ids: next, from: new Map(ps.map((p) => [p.id, { x: p.x, y: p.y }])), moved: false, x: e.clientX, y: e.clientY };
      return;
    }
    gesture.current = { kind: 'pan', g0, v, x: e.clientX, y: e.clientY, moved: false };
  };

  const move = (e) => {
    const g = gesture.current;
    if (!g) return;
    if (g.kind === 'orbit') {
      setView({ ...g.v, turn: g.v.turn - (e.clientX - g.x) * 0.3, tilt: Math.min(MAX_TILT, Math.max(0, g.v.tilt + (e.clientY - g.y) * 0.25)) });
    } else if (g.kind === 'pan') {
      const p = ground(e.clientX, e.clientY, g.v);
      if (p) setView({ ...g.v, x: g.v.x - (p.x - g.g0.x), y: g.v.y - (p.y - g.g0.y) });
      if (Math.hypot(e.clientX - g.x, e.clientY - g.y) > 3) g.moved = true;
    } else if (g.kind === 'move') {
      const p = ground(e.clientX, e.clientY);
      if (!p) return;
      if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) < 3) return;
      g.moved = true;
      const dx = p.x - g.g0.x;
      const dy = p.y - g.g0.y;
      setPapers((ps) => ps.map((q) => {
        if (!g.ids.has(q.id)) return q;
        const f = g.from.get(q.id);
        let x = f.x + dx;
        let y = f.y + dy;
        if (q.kind === 'tracing' && g.ids.size === 1 && Math.hypot(x - TRACE_HOME.x, y - TRACE_HOME.y) < SNAP) { x = TRACE_HOME.x; y = TRACE_HOME.y; }
        return { ...q, x, y };
      }));
    } else if (g.kind === 'draw') {
      const p = ground(e.clientX, e.clientY);
      if (!p) return;
      const pt = [p.x - g.off.x, p.y - g.off.y];
      const last = g.points[g.points.length - 1];
      if (Math.hypot(pt[0] - last[0], pt[1] - last[1]) < live.current.view.span / 500) return;
      g.points = [...g.points, pt];
      setDraft({ id: g.id, points: g.points });
    }
  };

  const up = () => {
    const g = gesture.current;
    gesture.current = null;
    if (!g) return;
    if (g.kind === 'draw') {
      if (g.points.length > 1) setPapers((ps) => ps.map((q) => (q.id === g.id ? { ...q, strokes: [...q.strokes, g.points] } : q)));
      setDraft(null);
    } else if (g.kind === 'pan' && !g.moved) {
      setSelected(new Set());
    } else if (g.kind === 'move' && g.moved && g.ids.size === 1) {
      const p = live.current.papers.find((q) => g.ids.has(q.id));
      if (p?.kind === 'tracing') say(atHome(p) ? `${p.title}을(를) 대지 위에 다시 덮었습니다.` : `${p.title}을(를) 떼어냈습니다. 배치도 옆에 두고 보거나, 다시 대지 위로 끌어 덮으세요.`);
    }
  };

  const onDouble = (e) => {
    const id = e.target.closest('[data-paper]')?.dataset.paper;
    if (live.current.papers.find((p) => p.id === id)?.kind === 'note') setEditing(id);
  };

  const remove = useCallback(() => {
    const { selected: sel } = live.current;
    if (!sel.size) return;
    setPapers((ps) => ps.filter((p) => !sel.has(p.id) || p.kind === 'site'));
    setPins((list) => list.filter((pin) => !sel.has(pin.paper)));
    setSelected(new Set());
  }, []);

  useEffect(() => {
    const key = (e) => {
      if (typing(e.target) || e.metaKey || e.ctrlKey) return;
      const k = e.key.toLowerCase();
      if (k === '1') animateTo({ tilt: TILT.plan, turn: 0 });
      else if (k === '2') animateTo({ tilt: TILT.axo, turn: live.current.view.turn || -30 });
      else if (k === '3') animateTo({ tilt: TILT.eye, turn: live.current.view.turn || -30 });
      else if (k === '0') fit();
      else if (k === 't') layTracing();
      else if (k === 'delete' || k === 'backspace') remove();
      else if (k === 'escape') { setSelected(new Set()); setTool('select'); }
      else { const tl = TOOLS.find((x) => x.key === k); if (tl) setTool(tl.id); }
    };
    window.addEventListener('keydown', key);
    return () => window.removeEventListener('keydown', key);
  }, [animateTo, fit, layTracing, remove]);

  const onText = useCallback((id, text) => setPapers((ps) => ps.map((p) => (p.id === id ? { ...p, text } : p))), []);
  const onDone = useCallback(() => setEditing(''), []);

  const tiltPreset = (name) => animateTo({ tilt: TILT[name], turn: name === 'plan' ? 0 : (view.turn || -30) });
  return (
    <div className={`table tool-${tool}`} ref={host} onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up}
      onDoubleClick={onDouble} onContextMenu={(e) => e.preventDefault()} role="application" aria-label="제도판">
      {papers.map((p) => createPortal(
        <Paper paper={p} selected={selected.has(p.id)} overlaid={atHome(p)} editing={editing === p.id} onText={onText} onDone={onDone}
          draft={draft?.id === p.id ? draft.points : null} />, slot(p.id), p.id))}
      <div className="pin-layer" ref={pinLayer}>
        {pins.map((pin) => (
          <button key={pin.id} type="button" className="pin" data-pin={pin.id} title={`${pin.label} · 누르면 이 자리를 봅니다`}>
            <span>{pin.label}</span>
          </button>
        ))}
      </div>

      <div className="table-ui ui-tools" role="toolbar" aria-label="도구">
        {TOOLS.map((t) => (
          <button key={t.id} type="button" aria-pressed={tool === t.id} onClick={() => setTool(t.id)} title={`${t.label} (${t.key.toUpperCase()})`}>
            <span aria-hidden="true">{t.icon}</span> {t.label}
          </button>
        ))}
        <span className="sep" />
        <button type="button" onClick={layTracing} title="트레이싱지 덮기 (T)">트레이싱지 덮기</button>
        <button type="button" onClick={remove} disabled={!selected.size} title="삭제 (Delete)">삭제</button>
      </div>

      <div className="table-ui ui-scheme">
        <div className="seg" role="group" aria-label="매스안">
          {Object.entries(SCHEMES).map(([id, s]) => (
            <button key={id} type="button" aria-pressed={scheme === id} onClick={() => setScheme(id)}>{s.name}</button>
          ))}
        </div>
        <label className="check"><input type="checkbox" checked={ghost} onChange={(e) => setGhost(e.target.checked)} /> 다른 안 겹쳐 보기</label>
      </div>

      <div className="table-ui ui-tilt" aria-label="기울기">
        <div className="seg vertical" role="group" aria-label="보는 각도">
          {[['plan', '평면', '1'], ['axo', '액소', '2'], ['eye', '투시', '3']].map(([id, label, k]) => (
            <button key={id} type="button" title={`${label} (${k})`} aria-pressed={Math.abs(view.tilt - TILT[id]) < 4} onClick={() => tiltPreset(id)}>{label}</button>
          ))}
        </div>
        <input type="range" min="0" max={MAX_TILT} value={Math.round(view.tilt)} aria-label="기울기 각도"
          onChange={(e) => { tween.current += 1; setView((v) => ({ ...v, tilt: Number(e.target.value) })); }} />
        <span className="num tilt-read">{Math.round(view.tilt)}°</span>
        <button type="button" className="compass" title="북쪽을 위로" onClick={() => animateTo({ turn: 0 })}>
          <span style={{ transform: `rotate(${-view.turn}deg)` }} aria-hidden="true">▲</span><small>N</small>
        </button>
      </div>

      <div className="table-ui ui-zoom">
        <span className="num scale">{drawingScale(view.span, size.h)}</span>
        <button type="button" onClick={() => animateTo({ span: view.span / 1.4 }, 200)} aria-label="확대">+</button>
        <button type="button" onClick={() => animateTo({ span: view.span * 1.4 }, 200)} aria-label="축소">−</button>
        <button type="button" onClick={fit} title="전체 보기 (0)">맞춤</button>
      </div>

      <p className="table-ui ui-help">끌기: 책상 이동 · ⌘/Ctrl+휠: 확대 · 우클릭(Alt)+끌기: 돌리고 기울이기 · 1 평면 2 액소 3 투시</p>
      {hint ? <p className="table-ui ui-hint" role="status">{hint}</p> : null}
    </div>
  );
});
