import { useEffect, useRef } from 'react';
import { cardTitle } from '../shared/Cards.jsx';
import { PlanView } from '../shared/PlanView.jsx';
import { SCHEMES } from '../shared/geometry.js';
import { Paper, PaperContent } from './Papers.jsx';

export function CardDetails({ paper, onClose, onFocus, onAsk, onText, onBeginEdit, onFinishEdit }) {
  const dialog = useRef(null);
  useEffect(() => {
    const element = dialog.current;
    element.showModal();
    return () => { onFinishEdit(); element.close(); };
  }, [paper.id, onFinishEdit]);

  return (
    <dialog ref={dialog} className="card-detail" aria-labelledby="detail-title"
      onCancel={(event) => { event.preventDefault(); onClose(); }}
      onClick={(event) => {
        if (event.target !== event.currentTarget) return;
        const box = event.currentTarget.getBoundingClientRect();
        if (event.clientX < box.left || event.clientX > box.right || event.clientY < box.top || event.clientY > box.bottom) onClose();
      }}>
      <header className="detail-head">
        <div><span className="eyebrow">{{ site: '대지 자료', mass: '매스안 · 예시', expert: '전문가 검토 · 예시', tracing: '트레이싱', note: '설계 메모' }[paper.kind]}</span><h2 id="detail-title">{cardTitle(paper)}</h2></div>
        <button type="button" className="ghost" aria-label="상세 보기 닫기" onClick={onClose} autoFocus>×</button>
      </header>
      <div className="detail-body">
        {paper.kind === 'site' || paper.kind === 'mass' ? <PlanView scheme={paper.kind === 'mass' ? SCHEMES[paper.scheme] : null} height={230} /> : null}
        {paper.kind === 'note' ? <label className="detail-note">메모 내용<textarea value={paper.text} aria-label="상세 메모 내용"
          onFocus={onBeginEdit} onBlur={onFinishEdit} onChange={(event) => onText(paper.id, event.target.value)} /></label>
          : paper.kind === 'tracing' ? <div className="detail-tracing"><Paper paper={paper} /><p>그린 선 {paper.strokes.length}개</p></div>
          : <PaperContent paper={paper} />}
        {paper.kind === 'mass' ? <p className="detail-caption">예시 매스의 계산값 · 층고 4.2m 가정</p> : null}
      </div>
      <footer className="detail-actions">
        <button type="button" className="detail-secondary" onClick={onFocus}>보드에서 크게 보기</button>
        <button type="button" className="detail-primary" onClick={() => { dialog.current.close(); onAsk(); }}>이 카드로 질문하기 →</button>
      </footer>
    </dialog>
  );
}
