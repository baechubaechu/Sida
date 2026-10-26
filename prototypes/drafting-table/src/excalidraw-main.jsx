import { useCallback, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Excalidraw, convertToExcalidrawElements, restoreElements } from '@excalidraw/excalidraw';
import '@excalidraw/excalidraw/index.css';
import './shared/styles.css';
import { Shell } from './shared/Shell.jsx';
import { Card, CARD_SIZES } from './shared/Cards.jsx';

window.EXCALIDRAW_ASSET_PATH = new URL('./excalidraw-assets/', window.location.href).href;
const LINK = 'https://sida.local/card/'; // embeddables need a URL; ours never loads, it only names the card

const START = [
  { id: 'site', kind: 'site', x: 0, y: 0 },
  { id: 'mass-a', kind: 'mass', scheme: 'A', x: 360, y: 0 },
  { id: 'mass-b', kind: 'mass', scheme: 'B', x: 800, y: 0 },
];

function cardElement(card, x, y) {
  const [width, height] = CARD_SIZES[card.kind];
  return { type: 'embeddable', x, y, width, height, link: LINK + card.id, strokeColor: 'transparent', backgroundColor: 'transparent', roundness: null };
}

const dark = window.matchMedia?.('(prefers-color-scheme: dark)').matches;

function App() {
  const api = useRef(null);
  const cards = useRef(Object.fromEntries(START.map(({ x, y, ...c }) => [c.id, c])));
  const [selection, setSelection] = useState([]);
  const [initialData] = useState(() => ({
    elements: convertToExcalidrawElements([
      ...START.map((c) => cardElement(c, c.x, c.y)),
      { type: 'rectangle', x: 40, y: 360, width: 220, height: 90, backgroundColor: '#ffec99', strokeColor: '#e8a33d', fillStyle: 'solid',
        label: { text: '북측 인접 대지 일조\n확인할 것' } },
    ]),
    appState: { viewBackgroundColor: 'transparent' },
    scrollToContent: true,
  }));

  const onChange = useCallback((elements, appState) => {
    const picked = elements.filter((e) => appState.selectedElementIds[e.id] && e.type === 'embeddable' && e.link?.startsWith(LINK))
      .map((e) => cards.current[e.link.slice(LINK.length)]).filter(Boolean);
    setSelection((prev) => (prev.map((c) => c.id).join() === picked.map((c) => c.id).join() ? prev : picked));
  }, []);

  const addCard = useCallback((card) => {
    const a = api.current;
    cards.current[card.id] = card;
    const els = a.getSceneElements();
    const maxX = Math.max(0, ...els.map((e) => e.x + e.width));
    const minY = Math.min(...els.map((e) => e.y));
    const [el] = restoreElements(convertToExcalidrawElements([cardElement(card, maxX + 40, minY)]), null);
    a.updateScene({ elements: [...els, el], appState: { selectedElementIds: { [el.id]: true } } });
    a.scrollToContent(el, { fitToContent: true, animate: true });
  }, []);

  const focusCard = useCallback((cardId) => {
    const a = api.current;
    const el = a.getSceneElements().find((e) => e.link === LINK + cardId);
    if (!el) return;
    a.updateScene({ appState: { selectedElementIds: { [el.id]: true } } });
    a.scrollToContent(el, { fitToContent: true, animate: true });
  }, []);

  const board = (
    <div style={{ position: 'absolute', inset: 0 }}>
      <Excalidraw excalidrawAPI={(a) => { if (!api.current) setTimeout(() => a.scrollToContent(undefined, { fitToContent: true }), 300); api.current = a; }} initialData={initialData} onChange={onChange} langCode="ko-KR"
        theme={dark ? 'dark' : 'light'}
        validateEmbeddable={(link) => link.startsWith(LINK)}
        renderEmbeddable={(el, appState) => {
          const card = cards.current[el.link?.slice(LINK.length)];
          return card ? <Card card={card} selected={Boolean(appState.selectedElementIds[el.id])} /> : null;
        }} />
    </div>
  );
  return <Shell library="Excalidraw" board={board} selection={selection} addCard={addCard} focusCard={focusCard} />;
}

createRoot(document.getElementById('root')).render(<App />);
