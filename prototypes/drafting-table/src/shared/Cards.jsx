// What sits on the board: the site, a massing scheme in 3D, an expert's result.
import { useContext } from 'react';
import { ThreeView } from './ThreeView.jsx';
import { PlanView, Sheet } from './PlanView.jsx';
import { BoardContext, WorldContext } from './context.js';
import { SITE, SITE_AREA, SITE_BOUNDS, SCHEMES, LIMITS, schemeFigures, fmt } from './geometry.js';

export const CARD_SIZES = { site: [320, 318], mass: [400, 490], expert: [340, 300], tracing: [340, 330] };

export function cardTitle(card) {
  if (card.kind === 'site') return '대지 사실';
  if (card.kind === 'note') return `메모: ${(card.text || '').slice(0, 14) || '빈 메모'}`;
  if (card.kind === 'mass') return SCHEMES[card.scheme].name;
  if (card.kind === 'tracing') return card.title;
  return card.title;
}

function Gauge({ label, value, limit, unit = '%', note }) {
  const over = value > limit;
  return (
    <div className={`gauge ${over ? 'over' : ''}`}>
      <div className="gauge-head"><span>{label}</span><b className="num">{fmt(value, 1)}{unit}</b></div>
      <div className="gauge-bar"><i style={{ width: `${Math.min(100, (value / limit) * 100)}%` }} /></div>
      <div className="gauge-note">{note}</div>
    </div>
  );
}

// 3D ↔ plan switch, shared by the mass cards and the full-screen 3D view.
export function ViewSwitch({ mode, onChange }) {
  return (
    <div className="view-switch" role="group" aria-label="보기 방식" onPointerDown={(e) => e.stopPropagation()}>
      {[['3d', '3D'], ['2d', '평면']].map(([id, label]) => (
        <button key={id} type="button" aria-pressed={mode === id} onClick={() => onChange(id)}>{label}</button>
      ))}
    </div>
  );
}

// A peeled tracing sheet on its own: the lines, registration marks at the site's corners so it can
// be laid back in place, and a faint ghost of the site boundary.
function TracingBody({ card }) {
  const { overlaid, toggleOverlay, openWorld } = useContext(WorldContext);
  const b = SITE_BOUNDS;
  const m = 22;
  const marks = [[b.minX, b.minY], [b.maxX, b.minY], [b.minX, b.maxY], [b.maxX, b.maxY]];
  const on = overlaid.has(card.id);
  return (
    <div className="card-body tracing-card">
      <svg className="plan sheet-only" viewBox={`${b.minX - m} ${-(b.maxY + m)} ${b.maxX - b.minX + m * 2} ${b.maxY - b.minY + m * 2}`} role="img" aria-label={`${card.title} 트레이싱`}>
        {SITE.map((p) => <polygon key={p.pnu} className="ghost" points={p.local.map(([x, y]) => `${x},${-y}`).join(' ')} />)}
        <Sheet tracing={card} />
        {marks.map(([x, y]) => <path key={`${x},${y}`} className="reg" d={`M${x - 3} ${-y} H${x + 3} M${x} ${-y - 3} V${-y + 3}`} />)}
      </svg>
      <div className="tracing-actions" onPointerDown={(e) => e.stopPropagation()}>
        <button type="button" className="mini" aria-pressed={on} onClick={() => { toggleOverlay(card.id); if (!on) openWorld(); }}>{on ? '3D 화면에서 떼기' : '3D 화면 배치도에 씌우기'}</button>
      </div>
      <p className="source">획 {card.strokes.length}개 · 매스안 카드 위로 끌어 놓으면 그 배치도에 씌웁니다</p>
    </div>
  );
}

export function CardBody({ card }) {
  const { items, updateItem } = useContext(BoardContext);
  if (card.kind === 'tracing') return <TracingBody card={card} />;
  if (card.kind === 'site') {
    return (
      <div className="card-body site-card">
        <dl className="facts">
          <div><dt>필지</dt><dd>{SITE.map((p) => p.address.replace('경기도 군포시 ', '')).join(', ')}</dd></div>
          <div><dt>면적</dt><dd className="num">{fmt(SITE_AREA, 1)}㎡ <small>(토지 특성 합계)</small></dd></div>
          <div><dt>지목</dt><dd>공장용지</dd></div>
          <div><dt>용도지역</dt><dd>{LIMITS.zone}</dd></div>
          <div><dt>건폐율</dt><dd className="num">{LIMITS.coverage}% 이하</dd></div>
          <div><dt>용적률</dt><dd className="num">{LIMITS.farMin}~{LIMITS.farMax}%</dd></div>
        </dl>
        <p className="source">녹화된 정부 응답(브이월드) · 조례 {LIMITS.ordinance}</p>
      </div>
    );
  }
  if (card.kind === 'mass') {
    const scheme = SCHEMES[card.scheme];
    const f = schemeFigures(scheme);
    const mode = card.view || '3d';
    const sheets = (card.overlays || []).map((id) => items.find((i) => i.id === id)).filter(Boolean);
    return (
      <div className="card-body mass-card">
        <div className="view-wrap">
          {mode === '2d'
            ? <PlanView scheme={scheme} overlays={sheets} height={270} />
            : <ThreeView scheme={scheme} height={270} overlays={sheets} />}
          <ViewSwitch mode={mode} onChange={(m) => updateItem(card.id, { view: m })} />
          {sheets.length ? (
            <div className="overlay-chips" onPointerDown={(e) => e.stopPropagation()}>
              {sheets.map((t) => (
                <button key={t.id} type="button" title="떼어내기"
                  onClick={() => updateItem(card.id, { overlays: card.overlays.filter((x) => x !== t.id) })}>{t.title} 씌움 ✕</button>
              ))}
            </div>
          ) : null}
        </div>
        <div className="gauges">
          <Gauge label="건폐율" value={f.coverage} limit={LIMITS.coverage} note={`상한 ${LIMITS.coverage}% · 건축면적 ${fmt(f.footprint)}㎡`} />
          <Gauge label="용적률" value={f.far} limit={LIMITS.farMax} note={`상한 ${LIMITS.farMax}% · 연면적 ${fmt(f.floorArea)}㎡`} />
        </div>
        <p className="source">최고 높이 {fmt(f.height, 1)}m · 층고 4.2m 가정</p>
      </div>
    );
  }
  return (
    <div className="card-body expert-card">
      <ul>{card.points.map((p) => <li key={p}>{p}</li>)}</ul>
      <p className="source">시험판 예시 결과 · 실제 모델이 쓴 글이 아닙니다</p>
    </div>
  );
}

export function Card({ card, selected }) {
  return (
    <article className={`card kind-${card.kind} ${selected ? 'is-selected' : ''}`}>
      <header className="card-head">
        <span className="card-kind">{{ site: '대지', mass: '매스안', tracing: '트레이싱' }[card.kind] || card.agentName}</span>
        <h3>{cardTitle(card)}</h3>
      </header>
      <CardBody card={card} />
    </article>
  );
}
