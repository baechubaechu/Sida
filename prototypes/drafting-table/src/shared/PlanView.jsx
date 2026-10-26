// The site plan (배치도) drawn as SVG in metres, north up: parcels, scheme footprints with floor
// counts, north arrow and scale bar. Tracing sheets lie over it at the same coordinates, and the
// active sheet takes pen strokes. Drag pans, wheel zooms; the board under it does not move.
import { useEffect, useRef, useState } from 'react';
import { SITE, SITE_BOUNDS, blockFootprint } from './geometry.js';

const MARGIN = 22;
const initialBox = () => {
  const b = SITE_BOUNDS;
  return { x: b.minX - MARGIN, y: -(b.maxY + MARGIN), w: b.maxX - b.minX + MARGIN * 2, h: b.maxY - b.minY + MARGIN * 2 };
};
const pts = (ring) => ring.map(([x, y]) => `${x.toFixed(2)},${(-y).toFixed(2)}`).join(' ');
const path = (points) => points.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)} ${(-y).toFixed(2)}`).join(' ');

export function Sheet({ tracing, active }) {
  return (
    <g className={`sheet ${active ? 'is-active' : ''}`}>
      <rect className="paper" x="-2000" y="-2000" width="4000" height="4000" />
      {tracing.strokes.map((s, i) => <path key={i} d={path(s)} className="trace" />)}
    </g>
  );
}

export function PlanView({ scheme, overlays = [], active = null, draw = false, onStroke, height = 270 }) {
  const svg = useRef(null);
  const [box, setBox] = useState(initialBox);
  const [draft, setDraft] = useState(null);
  const drag = useRef(null);
  const points = useRef([]); // the stroke being drawn, read on release before React re-renders

  const toPlan = (e) => {
    const p = svg.current.createSVGPoint();
    p.x = e.clientX; p.y = e.clientY;
    const q = p.matrixTransform(svg.current.getScreenCTM().inverse());
    return [q.x, -q.y];
  };

  useEffect(() => {
    const el = svg.current;
    const onWheel = (e) => {
      e.preventDefault();
      e.stopPropagation();
      const [px, py] = toPlan(e);
      const f = Math.exp(e.deltaY * 0.0015);
      setBox((b) => {
        const w = Math.min(2000, Math.max(8, b.w * f));
        const h = (b.h * w) / b.w;
        return { x: px - ((px - b.x) * w) / b.w, y: -py - ((-py - b.y) * h) / b.h, w, h };
      });
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, []);

  const down = (e) => {
    e.stopPropagation();
    svg.current.setPointerCapture(e.pointerId);
    if (draw && active && e.button === 0) {
      drag.current = { kind: 'draw' };
      points.current = [toPlan(e)];
      setDraft(points.current);
    } else {
      const r = svg.current.getBoundingClientRect();
      drag.current = { kind: 'pan', x: e.clientX, y: e.clientY, box, scale: box.w / r.width };
    }
  };
  const move = (e) => {
    e.stopPropagation();
    const d = drag.current;
    if (!d) return;
    if (d.kind === 'pan') {
      setBox({ ...d.box, x: d.box.x - (e.clientX - d.x) * d.scale, y: d.box.y - (e.clientY - d.y) * d.scale });
    } else {
      const p = toPlan(e);
      const [lx, ly] = points.current[points.current.length - 1];
      if (Math.hypot(p[0] - lx, p[1] - ly) < box.w / 600) return;
      points.current = [...points.current, p];
      setDraft(points.current);
    }
  };
  const up = (e) => {
    e.stopPropagation();
    if (drag.current?.kind === 'draw' && points.current.length > 1) onStroke?.(points.current);
    points.current = [];
    drag.current = null;
    setDraft(null);
  };

  const b = SITE_BOUNDS;
  const north = [b.minX - 10, b.maxY + 4];
  const scale = [b.minX - 10, b.minY - 12];
  return (
    <svg ref={svg} className={`plan ${draw && active ? 'is-drawing' : ''}`} style={{ height }} viewBox={`${box.x} ${box.y} ${box.w} ${box.h}`}
      preserveAspectRatio="xMidYMid meet" role="img" aria-label={`${scheme ? scheme.name : '대지'} 배치 평면`}
      onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerCancel={up} onDoubleClick={(e) => e.stopPropagation()}>
      <rect className="plan-ground" x="-2000" y="-2000" width="4000" height="4000" />
      {SITE.map((p) => <polygon key={p.pnu} points={pts(p.local)} className="lot" />)}
      {scheme?.blocks.map((blk, i) => {
        const fp = blockFootprint(blk);
        const cx = fp.reduce((s, q) => s + q[0], 0) / 4;
        const cy = fp.reduce((s, q) => s + q[1], 0) / 4;
        return (
          <g key={i}>
            <polygon points={pts(fp)} className="footprint" />
            <text x={cx} y={-cy} className="floors">{blk.floors}F</text>
          </g>
        );
      })}
      <g className="north" transform={`translate(${north[0]} ${-north[1]})`}>
        <path d="M0 -7 L3 3 L0 1 L-3 3 Z" /><text y="-9">N</text>
      </g>
      <g className="scalebar" transform={`translate(${scale[0]} ${-scale[1]})`}>
        <path d="M0 0 H20 M0 -1.2 V1.2 M10 -0.8 V0.8 M20 -1.2 V1.2" /><text x="10" y="4.5">20m</text>
      </g>
      {overlays.map((t) => <Sheet key={t.id} tracing={t} />)}
      {active ? <Sheet tracing={active} active /> : null}
      {draft ? <path d={path(draft)} className="trace" /> : null}
    </svg>
  );
}
