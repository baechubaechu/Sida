import { useCallback, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './shared/styles.css';
import './table/table.css';
import { Shell } from './shared/Shell.jsx';
import { Table } from './table/Table.jsx';
import { SITE_BOUNDS } from './shared/geometry.js';

const b = SITE_BOUNDS;
const START = [
  { id: 'site', kind: 'site', w: 300, h: 250, x: b.minX - 22, y: b.maxY - 12 },
  { id: 'mass-a', kind: 'mass', scheme: 'A', w: 300, h: 210, x: b.maxX + 22, y: b.maxY - 12 },
  { id: 'mass-b', kind: 'mass', scheme: 'B', w: 300, h: 210, x: b.maxX + 22, y: b.maxY - 38 },
  { id: 'note-1', kind: 'note', text: '북측 인접 대지 일조 확인할 것', w: 220, h: 140, x: b.minX - 20, y: b.minY + 20 },
];

function App() {
  const table = useRef(null);
  const [selection, setSelection] = useState([]);
  const onSelection = useCallback((cards) => setSelection((prev) => (prev.map((c) => c.id).join() === cards.map((c) => c.id).join() ? prev : cards)), []);
  const addCard = useCallback((card) => {
    table.current.addExpert({ ...card, w: 320, h: 270 }, `${card.agentName}: 북측 그림자 확인`);
  }, []);
  const focusCard = useCallback((id) => table.current.focusCard(id), []);
  return (
    <Shell library="제도판" title="제도판" hint="기울이면 배치도가 3D가 됩니다 · 트레이싱지는 대지 위에 덮고, 옆으로 끌어내면 떼어집니다"
      selection={selection} addCard={addCard} focusCard={focusCard}
      board={<Table ref={table} initialPapers={START} onSelection={onSelection} />} />
  );
}

createRoot(document.getElementById('root')).render(<App />);
