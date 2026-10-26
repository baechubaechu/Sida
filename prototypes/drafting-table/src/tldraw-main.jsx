import { useCallback, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Tldraw, BaseBoxShapeUtil, HTMLContainer, T, createShapeId, toRichText } from 'tldraw';
import { getAssetUrls } from '@tldraw/assets/selfHosted';
import 'tldraw/tldraw.css';
import './shared/styles.css';
import { Shell } from './shared/Shell.jsx';
import { Card, CARD_SIZES } from './shared/Cards.jsx';

class SidaCardUtil extends BaseBoxShapeUtil {
  static type = 'sida-card';
  static props = { w: T.number, h: T.number, card: T.jsonValue };
  getDefaultProps() { return { w: 320, h: 320, card: { kind: 'site', id: 'site' } }; }
  canEdit() { return false; }
  component(shape) {
    const selected = this.editor.getSelectedShapeIds().includes(shape.id);
    return <HTMLContainer style={{ pointerEvents: 'all' }}><Card card={shape.props.card} selected={selected} /></HTMLContainer>;
  }
  getIndicatorPath(shape) {
    const path = new Path2D();
    path.roundRect(0, 0, shape.props.w, shape.props.h, 12);
    return path;
  }
}

const START = [
  { id: 'site', kind: 'site', x: 0, y: 0 },
  { id: 'mass-a', kind: 'mass', scheme: 'A', x: 360, y: 0 },
  { id: 'mass-b', kind: 'mass', scheme: 'B', x: 800, y: 0 },
];

function cardShape(card, x, y) {
  const [w, h] = CARD_SIZES[card.kind];
  const { x: _x, y: _y, ...data } = card;
  return { id: createShapeId(card.id), type: 'sida-card', x, y, props: { w, h, card: data } };
}

function App() {
  const editorRef = useRef(null);
  const [selection, setSelection] = useState([]);
  const shapeUtils = useMemo(() => [SidaCardUtil], []);
  const assetUrls = useMemo(() => getAssetUrls({ baseUrl: './tldraw-assets' }), []);

  const onMount = useCallback((editor) => {
    editorRef.current = editor;
    editor.user.updateUserPreferences({ locale: 'ko-kr' });
    if (!editor.getCurrentPageShapes().length) {
      editor.createShapes(START.map((c) => cardShape(c, c.x, c.y)));
      editor.createShape({ type: 'note', x: 40, y: 360, props: { richText: toRichText('북측 인접 대지 일조 확인할 것'), color: 'yellow' } });
      editor.zoomToFit({ animation: { duration: 0 } });
    }
    let last = '';
    editor.store.listen(() => {
      const cards = editor.getSelectedShapes().filter((s) => s.type === 'sida-card').map((s) => s.props.card);
      const key = cards.map((c) => c.id).join(',');
      if (key !== last) { last = key; setSelection(cards); }
    });
  }, []);

  const addCard = useCallback((card) => {
    const editor = editorRef.current;
    const bounds = editor.getCurrentPageBounds();
    const id = createShapeId(card.id);
    editor.createShape(cardShape(card, bounds ? bounds.maxX + 40 : 0, bounds ? bounds.minY : 0));
    editor.select(id);
    editor.zoomToSelection({ animation: { duration: 400 } });
  }, []);

  const focusCard = useCallback((cardId) => {
    const editor = editorRef.current;
    editor.select(createShapeId(cardId));
    editor.zoomToSelection({ animation: { duration: 400 } });
  }, []);

  const board = (
    <div style={{ position: 'absolute', inset: 0 }}>
      <Tldraw shapeUtils={shapeUtils} assetUrls={assetUrls} onMount={onMount} inferDarkMode />
    </div>
  );
  return <Shell library="tldraw" board={board} selection={selection} addCard={addCard} focusCard={focusCard} />;
}

createRoot(document.getElementById('root')).render(<App />);
