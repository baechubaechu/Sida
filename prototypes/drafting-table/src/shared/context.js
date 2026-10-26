import { createContext } from 'react';

// Board items and a way for a card to change itself (its view, the tracings laid over it).
export const BoardContext = createContext({ items: [], updateItem() {} });
// Tracings laid over the plan in the full-screen 3D/plan view.
export const WorldContext = createContext({ overlaid: new Set(), toggleOverlay() {}, openWorld() {} });
