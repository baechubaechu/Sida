// The three-pane workspace: Conductor on the left, the design board in the middle,
// experts and what they are doing on the right. Conversation and expert runs are examples.
import { useEffect, useRef, useState } from 'react';
import { cardTitle } from './Cards.jsx';
import { SCHEMES, schemeFigures, LIMITS, fmt } from './geometry.js';

const EXPERTS = [
  { id: 'site_reader', name: '대지 분석가', phase: '분석', done: true },
  { id: 'program_analyst', name: '프로그램 분석가', phase: '분석', done: true },
  { id: 'regulation_checker', name: '법규 검토자', phase: '분석', done: true },
  { id: 'precedent_scout', name: '선례 연구자', phase: '분석', done: false },
  { id: 'design_critic', name: '설계 비평가', phase: '비평', done: false },
  { id: 'representation_planner', name: '표현 계획자', phase: '전달', done: false },
  { id: 'presentation_editor', name: '발표 편집자', phase: '전달', done: false },
];

const FIRST = [
  { role: 'conductor', text: '군포 금정동 689-14, 689-15 두 필지를 하나의 대지로 봤습니다. 일반공업지역이라 건폐율 70%, 용적률 350%가 상한입니다. 보드에 매스안 두 개를 올려 두었으니 비교할 카드를 골라 물어보세요.' },
];

function massSummary(cards) {
  return cards.filter((c) => c.kind === 'mass').map((c) => {
    const f = schemeFigures(SCHEMES[c.scheme]);
    return `${SCHEMES[c.scheme].name}: 건폐율 ${fmt(f.coverage, 1)}%, 용적률 ${fmt(f.far, 1)}%`;
  });
}

function exampleReply(text, context) {
  const masses = massSummary(context);
  if (masses.length >= 2) {
    return `선택한 두 안을 비교하면 ${masses.join(' / ')}입니다. 둘 다 상한(${LIMITS.coverage}%, ${LIMITS.farMax}%) 안이고, 안 B가 연면적을 더 쓰는 대신 북측 동이 높습니다. 설계 비평가에게 두 안을 보여 주고 일조와 동선을 따져 볼까요?`;
  }
  if (masses.length === 1) return `${masses[0]}. 용적률에 여유가 있어 층을 올리거나 바닥을 넓힐 수 있습니다. 어느 쪽으로 키울지 정하면 매스를 고쳐 보겠습니다.`;
  if (context.length) return `선택한 ${context.map(cardTitle).join(', ')}을(를) 보고 답합니다. "${text}"에 대해 더 구체적으로 알려 주세요.`;
  return '보드에서 카드를 골라 함께 보내면 그 카드를 근거로 답합니다. 예: 안 A와 안 B를 골라 "비교해 줘".';
}

function stepsFor(expert, context) {
  const masses = context.filter((c) => c.kind === 'mass');
  const target = masses.length ? masses.map(cardTitle).join(', ') : '보드의 매스안 전부';
  return [
    '대지 사실 읽기 · 필지 2개, 일반공업지역',
    `매스 수치 읽기 · ${target}`,
    '법정·조례 수치와 비교',
    `${expert.name} 의견 쓰기`,
    '보드에 결과 카드 놓기',
  ];
}

function resultCard(expert, context) {
  const masses = context.filter((c) => c.kind === 'mass');
  const names = masses.length ? masses.map(cardTitle).join(' · ') : '안 A · 안 B';
  return {
    id: `expert-${Date.now()}`, kind: 'expert', agent: expert.id, agentName: expert.name,
    title: `${names} 검토`,
    points: [
      '두 안 모두 법정 상한 안에 있음. 수치보다 배치가 쟁점',
      '안 B의 7층 동이 북측 인접 대지에 그림자를 길게 드리움 → 동지 일조 확인',
      '안 A는 하역 마당이 남측에 넓게 남아 동선이 단순함',
      '다음: 표현 계획자에게 두 안의 그림자 다이어그램 요청',
    ],
  };
}

export function Shell({ library, title = '디자인 보드', hint, board, world, selection, addCard, focusCard, inspectCard, onDeselect, onClearSelection, onSelectMasses, questionRequest = 0, center: centerProp, onCenter }) {
  const [messages, setMessages] = useState(FIRST);
  const [draft, setDraft] = useState('');
  const [experts, setExperts] = useState(EXPERTS);
  const [runs, setRuns] = useState([]);
  const [pane, setPane] = useState('board');
  const [collapsed, setCollapsed] = useState(false);
  const [expertsCollapsed, setExpertsCollapsed] = useState(false);
  const [composerFocus, setComposerFocus] = useState(0);
  const [centerState, setCenterState] = useState('board');
  const center = centerProp ?? centerState;
  const setCenter = onCenter ?? setCenterState;
  const scroller = useRef(null);
  const composerInput = useRef(null);
  useEffect(() => { scroller.current?.scrollTo(0, scroller.current.scrollHeight); }, [messages]);
  useEffect(() => {
    if (!questionRequest) return;
    setCollapsed(false);
    setPane('conductor');
    setComposerFocus((value) => value + 1);
  }, [questionRequest]);
  useEffect(() => {
    if (composerFocus && pane === 'conductor' && !collapsed) composerInput.current?.focus();
  }, [composerFocus, pane, collapsed]);

  const prepareQuestion = (text = '') => {
    setCollapsed(false);
    setPane('conductor');
    if (text) setDraft((current) => current.trim() ? `${current}\n${text}` : text);
    setComposerFocus((value) => value + 1);
  };
  const compareQuestion = '선택한 두 매스안의 배치와 건폐율·용적률을 비교하고, 검토할 차이점을 알려줘.';
  const canCompare = selection.filter((card) => card.kind === 'mass').length >= 2;

  const send = (e) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    const context = selection;
    setMessages((m) => [...m, { role: 'user', text, context: context.map(cardTitle) }]);
    setDraft('');
    setTimeout(() => setMessages((m) => [...m, { role: 'conductor', text: exampleReply(text, context), example: true }]), 900);
  };

  const run = (expert) => {
    const context = selection;
    const steps = stepsFor(expert, context);
    const runId = `${expert.id}-${Date.now()}`;
    setExperts((list) => list.map((x) => (x.id === expert.id ? { ...x, running: true } : x)));
    setRuns((r) => [{ id: runId, expert, steps, at: 0, context: context.map(cardTitle) }, ...r]);
    steps.forEach((_, i) => setTimeout(() => {
      setRuns((r) => r.map((x) => (x.id === runId ? { ...x, at: i + 1 } : x)));
      if (i === steps.length - 1) {
        const card = resultCard(expert, context);
        addCard(card);
        setExperts((list) => list.map((x) => (x.id === expert.id ? { ...x, running: false, done: true } : x)));
        setMessages((m) => [...m, { role: 'conductor', text: `${expert.name} 결과를 보드에 올렸습니다.`, card: card.id }]);
      }
    }, 800 * (i + 1)));
  };

  return (
    <div className={`shell pane-${pane} ${collapsed ? 'conductor-collapsed' : ''} ${expertsCollapsed ? 'experts-collapsed' : ''}`}>
      <section className="conductor" aria-label="Conductor 대화">
        <header className="pane-head">
          <div><span className="eyebrow">설계 대화</span><h2>Conductor</h2><p>금정동 공장 증축</p></div>
          <button className="ghost" onClick={() => setCollapsed(true)} aria-label="Conductor 접기">⟨</button>
        </header>
        <div className="messages" ref={scroller} role="log">
          {messages.map((m, i) => (
            <div key={i} className={`msg ${m.role === 'conductor' ? 'assistant' : m.role}`}>
              {m.role === 'conductor' ? <span className="speaker">Sida <span>Conductor</span></span> : null}
              {m.context?.length ? <div className="chips">{m.context.map((t) => <span key={t} className="chip">{t}</span>)}</div> : null}
              <p>{m.text}</p>
              {m.card ? <button className="link" onClick={() => { setCenter('board'); focusCard(m.card); }}>보드에서 보기 →</button> : null}
              {m.example ? <small>시험판 예시 답</small> : null}
            </div>
          ))}
        </div>
        <form className="composer" onSubmit={send}>
          <div className="context" aria-label="질문에 함께 보낼 자료">
            {selection.length ? <span className="attachment-label">함께 보낼 자료 {selection.length}개</span> : null}
            <div className="chips">
            {selection.length
              ? selection.map((c) => <span key={c.id} className="attachment">
                <button type="button" className="attachment-title" onClick={() => (inspectCard || focusCard)(c.id)}>{cardTitle(c)}</button>
                {onDeselect ? <button type="button" className="attachment-remove" onClick={() => onDeselect(c.id)} aria-label={`${cardTitle(c)} 질문 자료에서 빼기`}>×</button> : null}
              </span>)
              : <span className="hint">카드를 선택하면 이 질문에 자료로 붙습니다</span>}
            </div>
          </div>
          <label className="sr" htmlFor="ask">Conductor에게 메시지</label>
          <textarea ref={composerInput} id="ask" rows={2} value={draft} onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) send(e); }}
            placeholder={canCompare ? '선택한 두 안에 대해 물어보세요' : selection.length ? '선택한 자료에 대해 물어보세요' : '설계에 대해 물어보세요'} />
          <button className="send" type="submit" aria-label="보내기">↑</button>
          <span className="composer-note">Enter로 보내기 · Shift+Enter로 줄 바꿈</span>
        </form>
      </section>
      <main className="board" aria-label="디자인 보드">
        <header className="board-head">
          <div className="board-heading"><span className="eyebrow">금정동 공장 증축 <span aria-hidden="true">/</span> 디자인</span><h1>{title}</h1></div>
          <span className="tag">{library} · 미리보기</span>
          <div className="panel-toggles">
            {collapsed ? <button type="button" className="panel-toggle" onClick={() => setCollapsed(false)} aria-label="Conductor 펼치기">대화 펼치기</button> : null}
            <button type="button" className="panel-toggle" aria-controls="experts-panel" aria-expanded={!expertsCollapsed}
              aria-label={expertsCollapsed ? '전문가 펼치기' : '전문가 접기'} onClick={() => setExpertsCollapsed((value) => !value)}>
              <span aria-hidden="true">{expertsCollapsed ? '‹' : '›'}</span> 전문가
            </button>
          </div>
          {world ? (
            <div className="center-switch" role="group" aria-label="가운데 화면">
              <button type="button" aria-pressed={center === 'board'} onClick={() => setCenter('board')}>보드</button>
              <button type="button" aria-pressed={center === 'world'} onClick={() => setCenter('world')}>3D · 배치도</button>
            </div>
          ) : null}
          <span className="muted">{hint || (center === 'world' ? '평면에서 트레이싱지를 덮고 그린 뒤 떼어내면 보드에 붙습니다' : '카드 머리를 끌어 옮기고, 카드 안 3D는 끌어서 돌립니다')}</span>
        </header>
        <div className={`selection-bar ${selection.length ? 'has-selection' : ''}`} aria-label="선택한 카드">
          {selection.length ? <>
            <span className="selection-count" role="status">선택 {selection.length}개</span>
            <div className="selection-items">{selection.map((card) => <button key={card.id} type="button" onClick={() => (inspectCard || focusCard)(card.id)} title="상세 보기">{cardTitle(card)} ↗</button>)}</div>
            <button type="button" className="selection-ask" onClick={() => prepareQuestion(canCompare ? compareQuestion : '')}>{canCompare ? '두 안 비교 질문 →' : '이 자료로 질문 →'}</button>
            {onClearSelection ? <button type="button" className="selection-clear" aria-label="선택 모두 해제" onClick={onClearSelection}>×</button> : null}
          </> : <><span className="selection-guide">카드 클릭: 선택·상세 보기 · Shift+클릭: 여러 장 선택</span>{onSelectMasses ? <button type="button" className="selection-ask" onClick={onSelectMasses}>매스안 선택</button> : null}</>}
        </div>
        <div className="board-canvas" hidden={center !== 'board'}>{board}</div>
        {world ? <div className="board-canvas" hidden={center !== 'world'}>{world}</div> : null}
      </main>

      <aside id="experts-panel" className="experts" aria-label="전문가">
        <header className="pane-head"><div><span className="eyebrow">함께 검토하기</span><h2>전문가 <span className="expert-count">{experts.length}</span></h2><p>{selection.length ? `선택한 카드 ${selection.length}개로 실행` : '보드 전체를 보고 실행'}</p></div>
          <button type="button" className="ghost" aria-label="전문가 패널 닫기" aria-controls="experts-panel" aria-expanded={!expertsCollapsed}
            onClick={() => { setExpertsCollapsed(true); setPane('board'); }}>›</button>
        </header>
        <ul className="expert-list">
          {experts.map((x) => (
            <li key={x.id}>
              <span className={`dot ${x.running ? 'run' : x.done ? 'done' : ''}`} aria-hidden="true" />
              <span className="name">{x.name}<small>{x.phase}</small></span>
              <button className="mini" disabled={x.running} onClick={() => run(x)}>{x.running ? '실행 중' : '실행'}</button>
            </li>
          ))}
        </ul>
        <div className="runs">
          <h3>검토 진행</h3>
          {runs.length ? runs.map((r) => (
            <div key={r.id} className="run">
              <b>{r.expert.name}</b>
              <ol>{r.steps.map((s, i) => <li key={s} className={i < r.at ? 'ok' : i === r.at ? 'now' : ''}>{s}</li>)}</ol>
            </div>
          )) : <p className="muted">전문가를 실행하면 무엇을 읽고 무엇을 만드는지 여기 단계별로 보입니다.</p>}
        </div>
      </aside>

      <nav className="tabs" aria-label="화면 바꾸기">
        {[['conductor', '대화'], ['board', '보드'], ['experts', '전문가']].map(([id, label]) => (
          <button key={id} aria-pressed={pane === id} onClick={() => { setPane(id); if (id === 'experts') setExpertsCollapsed(false); }}>{label}</button>
        ))}
      </nav>
    </div>
  );
}
