// Sida's own design board: an infinite canvas with cards, notes and pen strokes.
// Camera: world point (x, y) sits at the viewport's top-left, scaled by zoom.
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { BoardContext } from '../shared/context.js';
import { Card } from '../shared/Cards.jsx';
import {
  boundsOf, clampZoom, fitCamera, intersects, nextSpot, pushHistory, rectFrom, toWorld, zoomAt,
} from './model.js';

const NOTE_SIZE = { w: 200, h: 140 };
const MIN_SIZE = { w: 140, h: 90 };
const DRAG_START = 3; // px before a press becomes a drag
const TOOLS = [
  { id: 'select', label: '선택', key: 'V', icon: '↖' },
  { id: 'hand', label: '손', key: 'H', icon: '✋' },
  { id: 'note', label: '메모', key: 'N', icon: '▤' },
  { id: 'pen', label: '펜', key: 'P', icon: '✎' },
];

let seq = 0;
const newId = (prefix) => `${prefix}-${Date.now().toString(36)}-${(seq += 1)}`;
const pathOf = (points) => points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
const strokeBox = (s) => {
  const xs = s.points.map((p) => p[0]);
  const ys = s.points.map((p) => p[1]);
  return { x: Math.min(...xs), y: Math.min(...ys), w: Math.max(...xs) - Math.min(...xs) || 1, h: Math.max(...ys) - Math.min(...ys) || 1 };
};
const typing = (el) => el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.isContentEditable);

const Note = memo(function Note({ item, editing, onText, onDone }) {
  const ref = useRef(null);
  useEffect(() => { if (editing) { ref.current?.focus(); ref.current?.select(); } }, [editing]);
  return (
    <div className="bd-note">
      {editing
        ? <textarea ref={ref} aria-label="메모 내용" value={item.text} onChange={(e) => onText(item.id, e.target.value)}
            onBlur={onDone} onKeyDown={(e) => { if (e.key === 'Escape') e.currentTarget.blur(); e.stopPropagation(); }} />
        : <p>{item.text || '메모'}</p>}
    </div>
  );
});

const Item = memo(function Item({ item, selected, editing, onText, onDone, dropTarget }) {
  return (
    <div className={`bd-item ${selected ? 'is-selected' : ''} ${dropTarget ? 'is-drop-target' : ''}`} data-item={item.id}
      style={{ transform: `translate(${item.x}px, ${item.y}px)`, width: item.w, height: item.h }}>
      {item.kind === 'note'
        ? <Note item={item} editing={editing} onText={onText} onDone={onDone} />
        : <Card card={item} selected={selected} />}
      {selected ? <span className="bd-handle" data-handle={item.id} aria-hidden="true" /> : null}
    </div>
  );
});

export const Board = forwardRef(function Board({ initialItems, onSelection, onItems }, ref) {
  const view = useRef(null);
  const [items, setItems] = useState(initialItems);
  const [strokes, setStrokes] = useState([]);
  const [selected, setSelected] = useState(() => new Set());
  const [cam, setCam] = useState({ x: -100, y: -100, zoom: 1 });
  const [tool, setTool] = useState('select');
  const [editing, setEditing] = useState('');
  const [marquee, setMarquee] = useState(null);
  const [draft, setDraft] = useState(null); // stroke being drawn
  const [history, setHistory] = useState({ past: [], future: [] });
  const [spaceHeld, setSpaceHeld] = useState(false);
  const [dropTarget, setDropTarget] = useState('');
  const live = useRef({});
  live.current = { items, strokes, selected, cam, tool, history, spaceHeld, editing };
  const gesture = useRef(null);
  const pointers = useRef(new Map());

  const snapshot = () => ({ items: live.current.items, strokes: live.current.strokes });
  const commit = useCallback((nextItems, nextStrokes = live.current.strokes) => {
    setHistory((h) => pushHistory(h, snapshot()));
    setItems(nextItems);
    setStrokes(nextStrokes);
  }, []);

  useEffect(() => { onItems?.(items); }, [items, onItems]);

  const updateItem = useCallback((id, patch) => {
    commit(live.current.items.map((i) => (i.id === id ? { ...i, ...patch } : i)));
  }, [commit]);
  const context = useMemo(() => ({ items, updateItem }), [items, updateItem]);

  // A single tracing sheet dragged over a scheme card is laid on that card's plan when dropped.
  const dropOn = (ids, world, before) => {
    if (ids.size !== 1) return null;
    const sheet = before.items.find((i) => ids.has(i.id) && i.kind === 'tracing');
    if (!sheet) return null;
    const target = before.items.find((i) => i.kind === 'mass' && world.x >= i.x && world.x <= i.x + i.w && world.y >= i.y && world.y <= i.y + i.h);
    return target ? { sheet, target } : null;
  };

  // Tell the shell which cards are selected.
  useEffect(() => {
    onSelection(items.filter((i) => selected.has(i.id)));
  }, [items, selected, onSelection]);

  const viewport = () => view.current.getBoundingClientRect();
  const screen = (e) => { const r = viewport(); return { sx: e.clientX - r.left, sy: e.clientY - r.top }; };

  const animateTo = useCallback((target) => {
    const from = live.current.cam;
    const start = performance.now();
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const step = (now) => {
      const t = reduce ? 1 : Math.min(1, (now - start) / 320);
      const k = 1 - (1 - t) ** 3;
      setCam({ x: from.x + (target.x - from.x) * k, y: from.y + (target.y - from.y) * k, zoom: from.zoom + (target.zoom - from.zoom) * k });
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }, []);

  const fit = useCallback((only) => {
    const r = viewport();
    const all = [...live.current.items, ...live.current.strokes.map(strokeBox)];
    animateTo(fitCamera(boundsOf(only || all), r.width, r.height, 60, only ? 1.2 : 1));
  }, [animateTo]);

  useEffect(() => {
    const r = viewport();
    setCam(fitCamera(boundsOf(initialItems), r.width, r.height, 60, 1));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useImperativeHandle(ref, () => ({
    addCard(card) {
      const { items: now } = live.current;
      const spot = nextSpot(now);
      const item = { ...card, ...spot, w: card.w, h: card.h };
      commit([...now, item]);
      setSelected(new Set([item.id]));
      fit([item]);
    },
    focusCard(id) {
      const item = live.current.items.find((i) => i.id === id);
      if (!item) return;
      setSelected(new Set([id]));
      fit([item]);
    },
  }), [commit, fit]);

  // ---------------------------------------------------------------- wheel: pan, ctrl/⌘ + wheel or pinch: zoom
  useEffect(() => {
    const el = view.current;
    const onWheel = (e) => {
      if (typing(e.target) && !e.ctrlKey) return;
      e.preventDefault();
      const { sx, sy } = screen(e);
      if (e.ctrlKey || e.metaKey) setCam((c) => zoomAt(c, sx, sy, Math.exp(-e.deltaY * 0.01)));
      else setCam((c) => ({ ...c, x: c.x + e.deltaX / c.zoom, y: c.y + e.deltaY / c.zoom }));
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  // ---------------------------------------------------------------- pointer gestures
  const onPointerDown = (e) => {
    if (e.button === 2) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    view.current.setPointerCapture(e.pointerId);
    if (pointers.current.size === 2) { // two fingers: pinch and pan, whatever the tool
      const [a, b] = [...pointers.current.values()];
      gesture.current = { kind: 'pinch', dist: Math.hypot(a.x - b.x, a.y - b.y), mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 } };
      setDraft(null);
      setMarquee(null);
      return;
    }
    const { cam: c, tool: t, selected: sel, items: its, spaceHeld: space } = live.current;
    const { sx, sy } = screen(e);
    const world = toWorld(c, sx, sy);
    const handle = e.target.closest('[data-handle]')?.dataset.handle;
    const itemId = e.target.closest('[data-item]')?.dataset.item;
    const strokeId = e.target.closest('[data-stroke]')?.dataset.stroke;
    if (typing(e.target)) return;
    if (t === 'hand' || space || e.button === 1) {
      gesture.current = { kind: 'pan', sx, sy, cam: c };
      return;
    }
    if (t === 'pen') {
      gesture.current = { kind: 'draw' };
      setDraft({ id: newId('stroke'), points: [[world.x, world.y]] });
      return;
    }
    if (t === 'note') {
      e.preventDefault(); // keep the focus in the new note's text box
      const note = { id: newId('note'), kind: 'note', text: '', x: world.x - NOTE_SIZE.w / 2, y: world.y - NOTE_SIZE.h / 2, ...NOTE_SIZE };
      commit([...its, note]);
      setSelected(new Set([note.id]));
      setEditing(note.id);
      setTool('select');
      return;
    }
    if (handle) {
      const item = its.find((i) => i.id === handle);
      gesture.current = { kind: 'resize', id: handle, start: world, from: { w: item.w, h: item.h }, before: snapshot(), moved: false };
      return;
    }
    const hit = itemId || strokeId;
    if (hit) {
      let next = sel;
      if (e.shiftKey) { next = new Set(sel); if (next.has(hit)) next.delete(hit); else next.add(hit); }
      else if (!sel.has(hit)) next = new Set([hit]);
      setSelected(next);
      gesture.current = { kind: 'move', start: world, ids: next, before: snapshot(), moved: false, sx, sy };
      return;
    }
    gesture.current = { kind: 'marquee', start: world, sx, sy, additive: e.shiftKey, base: sel };
  };

  const onPointerMove = (e) => {
    if (!pointers.current.has(e.pointerId)) return;
    pointers.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const g = gesture.current;
    if (!g) return;
    const { cam: c } = live.current;
    const { sx, sy } = screen(e);
    const world = toWorld(c, sx, sy);
    if (g.kind === 'pinch') {
      if (pointers.current.size < 2) return;
      const [a, b] = [...pointers.current.values()];
      const dist = Math.hypot(a.x - b.x, a.y - b.y);
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      const r = viewport();
      setCam((cc) => {
        const zoomed = zoomAt(cc, mid.x - r.left, mid.y - r.top, dist / g.dist);
        return { ...zoomed, x: zoomed.x - (mid.x - g.mid.x) / zoomed.zoom, y: zoomed.y - (mid.y - g.mid.y) / zoomed.zoom };
      });
      gesture.current = { ...g, dist, mid };
    } else if (g.kind === 'pan') {
      setCam({ ...g.cam, x: g.cam.x - (sx - g.sx) / g.cam.zoom, y: g.cam.y - (sy - g.sy) / g.cam.zoom });
    } else if (g.kind === 'draw') {
      setDraft((d) => {
        if (!d) return d;
        const [lx, ly] = d.points[d.points.length - 1];
        return Math.hypot(world.x - lx, world.y - ly) * c.zoom < 2 ? d : { ...d, points: [...d.points, [world.x, world.y]] };
      });
    } else if (g.kind === 'move') {
      if (!g.moved && Math.hypot(sx - g.sx, sy - g.sy) < DRAG_START) return;
      g.moved = true;
      const dx = world.x - g.start.x;
      const dy = world.y - g.start.y;
      setItems(g.before.items.map((i) => (g.ids.has(i.id) ? { ...i, x: i.x + dx, y: i.y + dy } : i)));
      setDropTarget(dropOn(g.ids, world, g.before)?.target.id || '');
      setStrokes(g.before.strokes.map((s) => (g.ids.has(s.id) ? { ...s, points: s.points.map(([x, y]) => [x + dx, y + dy]) } : s)));
    } else if (g.kind === 'resize') {
      g.moved = true;
      const w = Math.max(MIN_SIZE.w, g.from.w + world.x - g.start.x);
      const h = Math.max(MIN_SIZE.h, g.from.h + world.y - g.start.y);
      setItems((its) => its.map((i) => (i.id === g.id ? { ...i, w, h } : i)));
    } else if (g.kind === 'marquee') {
      if (Math.hypot(sx - g.sx, sy - g.sy) < DRAG_START && !marquee) return;
      const box = rectFrom(g.start, world);
      setMarquee(box);
      const hits = [
        ...live.current.items.filter((i) => intersects(box, i)).map((i) => i.id),
        ...live.current.strokes.filter((s) => intersects(box, strokeBox(s))).map((s) => s.id),
      ];
      setSelected(new Set([...(g.additive ? g.base : []), ...hits]));
    }
  };

  const onPointerUp = (e) => {
    pointers.current.delete(e.pointerId);
    const g = gesture.current;
    if (!g) return;
    if (g.kind === 'pinch') { if (pointers.current.size === 0) gesture.current = null; return; }
    gesture.current = null;
    if (g.kind === 'draw') {
      setDraft((d) => {
        if (d && d.points.length > 1) {
          setHistory((h) => pushHistory(h, snapshot()));
          setStrokes((s) => [...s, { ...d, color: 'var(--pen)' }]);
        }
        return null;
      });
    } else if ((g.kind === 'move' || g.kind === 'resize') && g.moved) {
      setHistory((h) => pushHistory(h, g.before));
      setDropTarget('');
      const { sx, sy } = screen(e);
      const drop = g.kind === 'move' ? dropOn(g.ids, toWorld(live.current.cam, sx, sy), g.before) : null;
      if (drop) { // the sheet goes back where it was; its lines now lie on the scheme's plan
        const { sheet, target } = drop;
        setItems(g.before.items.map((i) => (i.id === target.id
          ? { ...i, view: '2d', overlays: [...new Set([...(i.overlays || []), sheet.id])] } : i)));
        setStrokes(g.before.strokes);
        setSelected(new Set([target.id]));
      }
    } else if (g.kind === 'marquee') {
      if (!marquee && !g.additive) setSelected(new Set());
      setMarquee(null);
    }
  };

  const onDoubleClick = (e) => {
    const id = e.target.closest('[data-item]')?.dataset.item;
    const item = live.current.items.find((i) => i.id === id);
    if (item?.kind === 'note') setEditing(item.id);
  };

  // ---------------------------------------------------------------- notes
  const editStart = useRef(null);
  const onText = useCallback((id, text) => {
    if (!editStart.current) editStart.current = snapshot();
    setItems((its) => its.map((i) => (i.id === id ? { ...i, text } : i)));
  }, []);
  const onDone = useCallback(() => {
    if (editStart.current) { const before = editStart.current; setHistory((h) => pushHistory(h, before)); }
    editStart.current = null;
    setEditing('');
  }, []);

  // ---------------------------------------------------------------- commands
  const undo = useCallback(() => {
    const { history: h } = live.current;
    if (!h.past.length) return;
    const prev = h.past[h.past.length - 1];
    setHistory({ past: h.past.slice(0, -1), future: [snapshot(), ...h.future] });
    setItems(prev.items);
    setStrokes(prev.strokes);
  }, []);
  const redo = useCallback(() => {
    const { history: h } = live.current;
    if (!h.future.length) return;
    const [next, ...rest] = h.future;
    setHistory({ past: [...h.past, snapshot()], future: rest });
    setItems(next.items);
    setStrokes(next.strokes);
  }, []);
  const remove = useCallback(() => {
    const { items: its, strokes: sts, selected: sel } = live.current;
    if (!sel.size) return;
    commit(its.filter((i) => !sel.has(i.id)), sts.filter((s) => !sel.has(s.id)));
    setSelected(new Set());
  }, [commit]);
  const duplicate = useCallback(() => {
    const { items: its, selected: sel } = live.current;
    const copies = its.filter((i) => sel.has(i.id)).map((i) => ({ ...i, id: newId(i.kind), x: i.x + 30, y: i.y + 30 }));
    if (!copies.length) return;
    commit([...its, ...copies]);
    setSelected(new Set(copies.map((c) => c.id)));
  }, [commit]);
  const zoomBy = (factor) => { const r = viewport(); setCam((c) => zoomAt(c, r.width / 2, r.height / 2, factor)); };

  useEffect(() => {
    const down = (e) => {
      if (typing(e.target)) return;
      const mod = e.metaKey || e.ctrlKey;
      const k = e.key.toLowerCase();
      if (mod && k === 'z') { e.preventDefault(); if (e.shiftKey) redo(); else undo(); return; }
      if (mod && k === 'y') { e.preventDefault(); redo(); return; }
      if (mod && k === 'd') { e.preventDefault(); duplicate(); return; }
      if (mod && k === 'a') { e.preventDefault(); setSelected(new Set([...live.current.items.map((i) => i.id), ...live.current.strokes.map((s) => s.id)])); return; }
      if (mod) return;
      if (k === 'delete' || k === 'backspace') { e.preventDefault(); remove(); }
      else if (k === 'escape') { setSelected(new Set()); setTool('select'); }
      else if (k === ' ') { e.preventDefault(); setSpaceHeld(true); }
      else if (e.shiftKey && (k === '!' || k === '1')) fit();
      else { const t = TOOLS.find((x) => x.key.toLowerCase() === k); if (t) setTool(t.id); }
    };
    const up = (e) => { if (e.key === ' ') setSpaceHeld(false); };
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    return () => { window.removeEventListener('keydown', down); window.removeEventListener('keyup', up); };
  }, [undo, redo, remove, duplicate, fit]);

  const grid = 24 * cam.zoom;
  const panning = tool === 'hand' || spaceHeld;
  return (
    <BoardContext.Provider value={context}>
    <div className={`bd tool-${panning ? 'hand' : tool}`} ref={view} role="application" aria-label="디자인 보드. 화살표 대신 마우스와 단축키로 다룹니다."
      onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}
      onDoubleClick={onDoubleClick}
      style={{ backgroundSize: `${grid}px ${grid}px`, backgroundPosition: `${-cam.x * cam.zoom}px ${-cam.y * cam.zoom}px` }}>
      <div className="bd-world" style={{ transform: `scale(${cam.zoom}) translate(${-cam.x}px, ${-cam.y}px)` }}>
        <svg className="bd-ink" aria-hidden="true">
          {strokes.map((s) => (
            <path key={s.id} d={pathOf(s.points)} data-stroke={s.id} className={selected.has(s.id) ? 'is-selected' : ''} />
          ))}
          {draft ? <path d={pathOf(draft.points)} /> : null}
        </svg>
        {items.map((item) => (
          <Item key={item.id} item={item} selected={selected.has(item.id)} editing={editing === item.id} onText={onText} onDone={onDone} dropTarget={dropTarget === item.id} />
        ))}
        {marquee ? <div className="bd-marquee" style={{ transform: `translate(${marquee.x}px, ${marquee.y}px)`, width: marquee.w, height: marquee.h }} /> : null}
      </div>

      <div className="bd-toolbar" role="toolbar" aria-label="보드 도구" onPointerDown={(e) => e.stopPropagation()}>
        {TOOLS.map((t) => (
          <button key={t.id} aria-pressed={tool === t.id} onClick={() => setTool(t.id)} title={`${t.label} (${t.key})`}>
            <span aria-hidden="true">{t.icon}</span><span className="bd-label">{t.label}</span>
          </button>
        ))}
        <span className="bd-sep" />
        <button onClick={undo} disabled={!history.past.length} title="되돌리기 (⌘Z)">↶</button>
        <button onClick={redo} disabled={!history.future.length} title="다시하기 (⇧⌘Z)">↷</button>
        <button onClick={duplicate} disabled={!selected.size} title="복제 (⌘D)">⧉</button>
        <button onClick={remove} disabled={!selected.size} title="삭제 (Delete)">⌫</button>
      </div>
      <div className="bd-zoom" onPointerDown={(e) => e.stopPropagation()}>
        <button onClick={() => zoomBy(1 / 1.2)} aria-label="축소">−</button>
        <button onClick={() => setCam((c) => { const r = viewport(); return zoomAt(c, r.width / 2, r.height / 2, 1 / c.zoom); })} className="num" title="100%로">{Math.round(cam.zoom * 100)}%</button>
        <button onClick={() => zoomBy(1.2)} aria-label="확대">+</button>
        <button onClick={() => fit()} title="전체 보기 (⇧1)">맞춤</button>
      </div>
      <p className="bd-hint">두 손가락으로 이동 · ⌘/Ctrl+휠로 확대 · 스페이스를 누른 채 끌면 손 도구</p>
    </div>
    </BoardContext.Provider>
  );
});

export { clampZoom };
