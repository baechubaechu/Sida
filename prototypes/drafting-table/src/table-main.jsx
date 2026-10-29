import { createRoot } from 'react-dom/client';
import './shared/styles.css';
import './table/table.css';
import { DraftingTableApp } from './table/App.jsx';

createRoot(document.getElementById('root')).render(<DraftingTableApp />);
