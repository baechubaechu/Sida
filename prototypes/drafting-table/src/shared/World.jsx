// The middle pane's 3D · plan mode: the site and one scheme at full size. In plan, lay a tracing
// sheet over the 배치도, draw on it, and peel it off onto the board as its own artboard.
import { useContext, useState } from 'react';
import { ThreeView } from './ThreeView.jsx';
import { PlanView } from './PlanView.jsx';
import { ViewSwitch } from './Cards.jsx';
import { WorldContext } from './context.js';
import { SCHEMES, LIMITS, schemeFigures, fmt } from './geometry.js';

export function World({ schemeId, onScheme, tracings, onPeel }) {
  const { overlaid, toggleOverlay } = useContext(WorldContext);
  const [mode, setMode] = useState('3d');
  const [active, setActive] = useState(null);
  const [peeled, setPeeled] = useState(null);
  const scheme = SCHEMES[schemeId];
  const f = schemeFigures(scheme);
  const shown = tracings.filter((t) => overlaid.has(t.id));

  const lay = () => { setMode('2d'); setPeeled(null); setActive({ id: 'active', title: '새 트레이싱', strokes: [] }); };
  const peel = () => { setPeeled(onPeel(active.strokes)); setActive(null); };

  return (
    <div className="world">
      {mode === '2d'
        ? <PlanView scheme={scheme} overlays={shown} active={active} draw onStroke={(pts) => setActive((a) => ({ ...a, strokes: [...a.strokes, pts] }))} height="100%" />
        : <ThreeView scheme={scheme} height="100%" overlays={active ? [...shown, active] : shown} />}

      <div className="world-panel">
        <div className="scheme-switch" role="group" aria-label="매스안">
          {Object.entries(SCHEMES).map(([id, s]) => (
            <button key={id} type="button" aria-pressed={id === schemeId} onClick={() => onScheme(id)}>{s.name}</button>
          ))}
        </div>
        <dl className="world-figures">
          <div className={f.coverage > LIMITS.coverage ? 'over' : ''}><dt>건폐율</dt><dd className="num">{fmt(f.coverage, 1)}%<small> / {LIMITS.coverage}%</small></dd></div>
          <div className={f.far > LIMITS.farMax ? 'over' : ''}><dt>용적률</dt><dd className="num">{fmt(f.far, 1)}%<small> / {LIMITS.farMax}%</small></dd></div>
          <div><dt>연면적</dt><dd className="num">{fmt(f.floorArea)}㎡</dd></div>
          <div><dt>최고 높이</dt><dd className="num">{fmt(f.height, 1)}m</dd></div>
        </dl>
      </div>

      <div className="world-view"><ViewSwitch mode={mode} onChange={setMode} /></div>

      <section className="trace-panel" aria-label="트레이싱지">
        <h2>트레이싱지</h2>
        {active ? (
          <>
            <p className="muted">배치도 위에 덮었습니다. 끌어서 그리세요. 획 {active.strokes.length}개</p>
            <div className="trace-buttons">
              <button type="button" className="mini" disabled={!active.strokes.length} onClick={() => setActive((a) => ({ ...a, strokes: a.strokes.slice(0, -1) }))}>마지막 획 지우기</button>
              <button type="button" className="mini" onClick={() => setActive(null)}>버리기</button>
              <button type="button" className="mini primary" disabled={!active.strokes.length} onClick={peel}>떼어내 보드에 붙이기</button>
            </div>
          </>
        ) : (
          <>
            <button type="button" className="mini primary" onClick={lay}>트레이싱지 덮기</button>
            {peeled ? <p className="muted">"{peeled}"를 보드에 붙였습니다. 보드에서 배치도 옆에 두거나, 매스안 카드 위로 끌어 다시 씌울 수 있습니다.</p> : null}
          </>
        )}
        {tracings.length ? (
          <ul className="trace-list">
            {tracings.map((t) => (
              <li key={t.id}><label><input type="checkbox" checked={overlaid.has(t.id)} onChange={() => toggleOverlay(t.id)} /> {t.title} 씌우기</label></li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  );
}
