# pdf.js for PDF papers on the drafting table

`webui/app/pdf-view.js` draws a page of a PDF the designer put on the table at the size it is
shown, so a drawing stays sharp however large. The screen has no build step, so the built files
of `pdfjs-dist` are copied here and committed; they are loaded only when a PDF is shown.

- `pdf.js` ← `build/pdf.min.mjs`, `pdf.worker.js` ← `build/pdf.worker.min.mjs` (renamed to `.js`
  so every server sends them as JavaScript)
- `cmaps/` ← the Korean character maps of `cmaps/` (`Adobe-Korea1-*`, `KSC*`, `UniKS-*`), for PDFs
  whose Korean text uses a font that is not embedded

To update (version 6.5.438 now):

```bash
npm pack pdfjs-dist@6.5.438 && tar xzf pdfjs-dist-6.5.438.tgz
cp package/build/pdf.min.mjs webui/app/vendor/pdfjs/pdf.js
cp package/build/pdf.worker.min.mjs webui/app/vendor/pdfjs/pdf.worker.js
cp package/cmaps/{Adobe-Korea1,KSC,UniKS}* webui/app/vendor/pdfjs/cmaps/
cp package/LICENSE webui/app/vendor/pdfjs/LICENSE.txt
rm -rf package pdfjs-dist-6.5.438.tgz
```

pdf.js is Apache-2.0 licensed (`LICENSE.txt`).
