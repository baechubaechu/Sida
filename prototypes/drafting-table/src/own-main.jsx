import { useCallback, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './shared/styles.css';
import './board/board.css';
import { Shell } from './shared/Shell.jsx';
import { CARD_SIZES } from './shared/Cards.jsx';
import { World } from './shared/World.jsx';
import { WorldContext } from './shared/context.js';
import { Board } from './board/Board.jsx';

const sized = (card, x, y) => ({ ...card, x, y, w: CARD_SIZES[card.kind][0], h: CARD_SIZES[card.kind][1] });
const START = [
  sized({ id: 'site', kind: 'site' }, 0, 0),
  sized({ id: 'mass-a', kind: 'mass', scheme: 'A' }, 360, 0),
  sized({ id: 'mass-b', kind: 'mass', scheme: 'B', view: '2d' }, 800, 0),
  { id: 'note-1', kind: 'note', text: '북측 인접 대지 일조 확인할 것', x: 40, y: 360, w: 200, h: 140 },
];

function App() {
  const board = useRef(null);
  const [selection, setSelection] = useState([]);
  const [scheme, setScheme] = useState('A');
  const [center, setCenter] = useState('board');
  const [tracings, setTracings] = useState([]);
  const [overlaid, setOverlaid] = useState(() => new Set());

  const onSelection = useCallback((cards) => {
    setSelection((prev) => (prev.map((c) => c.id).join() === cards.map((c) => c.id).join() ? prev : cards));
    const mass = cards.find((c) => c.kind === 'mass');
    if (mass) setScheme(mass.scheme);
  }, []);
  const onItems = useCallback((items) => {
    const next = items.filter((i) => i.kind === 'tracing');
    setTracings((prev) => (prev.length === next.length && prev.every((t, i) => t === next[i]) ? prev : next));
  }, []);
  const addCard = useCallback((card) => {
    const [w, h] = CARD_SIZES[card.kind];
    board.current.addCard({ ...card, w, h });
  }, []);
  const focusCard = useCallback((id) => board.current.focusCard(id), []);
  const peel = useCallback((strokes) => {
    const title = `트레이싱 ${tracings.length + 1}`;
    addCard({ id: `tracing-${Date.now()}`, kind: 'tracing', title, strokes });
    return title;
  }, [tracings.length, addCard]);

  const world = useMemo(() => ({
    overlaid,
    toggleOverlay: (id) => setOverlaid((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; }),
    openWorld: () => setCenter('world'),
  }), [overlaid]);

  return (
    <WorldContext.Provider value={world}>
      <Shell library="Sida 자체 보드" selection={selection} addCard={addCard} focusCard={focusCard} center={center} onCenter={setCenter}
        board={<Board ref={board} initialItems={START} onSelection={onSelection} onItems={onItems} />}
        world={<World schemeId={scheme} onScheme={setScheme} tracings={tracings} onPeel={peel} />} />
    </WorldContext.Provider>
  );
}

createRoot(document.getElementById('root')).render(<App />);
