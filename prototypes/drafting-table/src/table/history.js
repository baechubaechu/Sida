// Immutable document history. A drag or text edit can group many updates into one step.
const LIMIT = 100;
const same = (a, b) => a === b || JSON.stringify(a) === JSON.stringify(b);

export const createHistory = (present) => ({ past: [], present, future: [], transaction: null });

function finish(history) {
  if (!history.transaction) return history;
  if (same(history.transaction, history.present)) return { ...history, transaction: null };
  return { ...history, past: [...history.past, history.transaction].slice(-LIMIT), future: [], transaction: null };
}

export function historyReducer(history, action) {
  if (action.type === 'begin') return history.transaction ? history : { ...history, transaction: history.present };
  if (action.type === 'finish') return finish(history);
  if (action.type === 'cancel') return history.transaction ? { ...history, present: history.transaction, transaction: null } : history;
  if (action.type === 'change') {
    const present = action.update(history.present);
    if (same(present, history.present)) return history;
    if (history.transaction) return { ...history, present };
    return { past: [...history.past, history.present].slice(-LIMIT), present, future: [], transaction: null };
  }
  const current = finish(history);
  if (action.type === 'undo' && current.past.length) {
    return { past: current.past.slice(0, -1), present: current.past.at(-1), future: [current.present, ...current.future], transaction: null };
  }
  if (action.type === 'redo' && current.future.length) {
    return { past: [...current.past, current.present].slice(-LIMIT), present: current.future[0], future: current.future.slice(1), transaction: null };
  }
  return current;
}

export const canUndo = (history) => history.past.length > 0 || (history.transaction && !same(history.transaction, history.present));
