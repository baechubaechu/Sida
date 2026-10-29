import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

const which = process.env.BOARD; // tldraw | excalidraw
export default defineConfig({
  plugins: [react()],
  base: './',
  build: {
    outDir: `dist-${which}`,
    emptyOutDir: true,
    cssCodeSplit: false,
    assetsInlineLimit: 0,
    rollupOptions: {
      input: which === 'test-shell' ? 'tests/shell.html' : which === 'test-workflow' ? 'tests/workflow.html' : `src/${which}-main.jsx`,
      output: { entryFileNames: 'app.js', assetFileNames: '[name][extname]', codeSplitting: false },
    },
  },
});
