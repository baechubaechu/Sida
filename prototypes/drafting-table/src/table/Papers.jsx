// Sheets of paper on the drafting table. Sizes are CSS pixels; on the table 1px = PX metres.
import { useEffect, useRef } from 'react';
import { SITE, SITE_AREA, SITE_BOUNDS, SCHEMES, LIMITS, schemeFigures, fmt } from '../shared/geometry.js';

export const PX = 0.1; // metres per CSS pixel of paper
export const TRACE_MARGIN = 14; // metres of tracing paper around the site
export const TRACE_HOME = {
  x: (SITE_BOUNDS.minX + SITE_BOUNDS.maxX) / 2,
  y: (SITE_BOUNDS.minY + SITE_BOUNDS.maxY) / 2,
  w: (SITE_BOUNDS.maxX - SITE_BOUNDS.minX + TRACE_MARGIN * 2) / PX,
  h: (SITE_BOUNDS.maxY - SITE_BOUNDS.minY + TRACE_MARGIN * 2) / PX,
};

const strokePath = (pts) => pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)} ${(-y).toFixed(2)}`).join(' ');

function Gauge({ label, value, limit, note }) {
  return (
    <div className={`gauge ${value > limit ? 'over' : ''}`}>
      <div className="gauge-head"><span>{label}</span><b className="num">{fmt(value, 1)}%</b></div>
      <div className="gauge-bar"><i style={{ width: `${Math.min(100, (value / limit) * 100)}%` }} /></div>
      <div className="gauge-note">{note}</div>
    </div>
  );
}

function NoteText({ paper, editing, onText, onDone }) {
  const ref = useRef(null);
  useEffect(() => { if (editing) { ref.current?.focus(); ref.current?.select(); } }, [editing]);
  return editing
    ? <textarea ref={ref} aria-label="메모 내용" value={paper.text} onChange={(e) => onText(paper.id, e.target.value)}
        onBlur={onDone} onKeyDown={(e) => { e.stopPropagation(); if (e.key === 'Escape') e.currentTarget.blur(); }} />
    : <p>{paper.text || '메모'}</p>;
}

export function Paper({ paper, selected, overlaid, editing, onText, onDone, draft }) {
  const cls = `paper kind-${paper.kind} ${selected ? 'is-selected' : ''} ${overlaid ? 'is-overlaid' : ''}`;
  if (paper.kind === 'note') {
    return (
      <article className={cls} data-paper={paper.id} style={{ width: paper.w, height: paper.h }}>
        <NoteText paper={paper} editing={editing} onText={onText} onDone={onDone} />
      </article>
    );
  }
  if (paper.kind === 'tracing') {
    const b = SITE_BOUNDS;
    const m = TRACE_MARGIN;
    return (
      <article className={cls} data-paper={paper.id} style={{ width: paper.w, height: paper.h }}>
        <svg viewBox={`${b.minX - m} ${-(b.maxY + m)} ${b.maxX - b.minX + m * 2} ${b.maxY - b.minY + m * 2}`} aria-hidden="true">
          {[[b.minX, b.minY], [b.maxX, b.minY], [b.minX, b.maxY], [b.maxX, b.maxY]].map(([x, y]) => (
            <path key={`${x}${y}`} className="reg" d={`M${x - 3} ${-y} H${x + 3} M${x} ${-y - 3} V${-y + 3}`} />
          ))}
          {paper.strokes.map((s, i) => <path key={i} className="trace" d={strokePath(s)} />)}
          {draft ? <path className="trace" d={strokePath(draft)} /> : null}
        </svg>
        <span className="paper-tag" data-drag>{paper.title}{overlaid ? ' · 덮음' : ''}</span>
      </article>
    );
  }
  let title = '';
  let body = null;
  if (paper.kind === 'site') {
    title = '대지 사실';
    body = (
      <dl className="facts">
        <div><dt>필지</dt><dd>{SITE.map((p) => p.address.replace('경기도 군포시 금정동 ', '')).join(', ')}</dd></div>
        <div><dt>면적</dt><dd className="num">{fmt(SITE_AREA, 1)}㎡</dd></div>
        <div><dt>용도지역</dt><dd>{LIMITS.zone}</dd></div>
        <div><dt>건폐율</dt><dd className="num">{LIMITS.coverage}% 이하</dd></div>
        <div><dt>용적률</dt><dd className="num">{LIMITS.farMin}~{LIMITS.farMax}%</dd></div>
        <p className="source">녹화된 정부 응답 · {LIMITS.ordinance}</p>
      </dl>
    );
  } else if (paper.kind === 'mass') {
    const s = SCHEMES[paper.scheme];
    const f = schemeFigures(s);
    title = s.name;
    body = (
      <>
        <div className="gauges">
          <Gauge label="건폐율" value={f.coverage} limit={LIMITS.coverage} note={`상한 ${LIMITS.coverage}% · ${fmt(f.footprint)}㎡`} />
          <Gauge label="용적률" value={f.far} limit={LIMITS.farMax} note={`상한 ${LIMITS.farMax}% · ${fmt(f.floorArea)}㎡`} />
        </div>
        <p className="source">최고 {fmt(f.height, 1)}m · {s.blocks.map((b) => `${b.floors}층`).join(' + ')}</p>
      </>
    );
  } else if (paper.kind === 'expert') {
    title = paper.title;
    body = (
      <>
        <ul>{paper.points.map((p) => <li key={p}>{p}</li>)}</ul>
        <p className="source">시험판 예시 결과 · 핀을 누르면 그 자리를 봅니다</p>
      </>
    );
  }
  return (
    <article className={cls} data-paper={paper.id} style={{ width: paper.w, height: paper.h }}>
      <header className="paper-head" data-drag>
        <span className="paper-kind">{{ site: '대지', mass: '매스안', expert: paper.agentName }[paper.kind]}</span>
        <h3>{title}</h3>
      </header>
      <div className="paper-body">{body}</div>
    </article>
  );
}
