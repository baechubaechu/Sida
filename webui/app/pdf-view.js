// A page of a PDF drawn into a canvas with pdf.js (webui/app/vendor/pdfjs, README there), so a
// drawing put on the table stays sharp however large it is shown: the table draws the page again
// at the size it is seen (board-model.js pdfCanvasSize). pdf.js is loaded only once a PDF is shown.

const VENDOR = new URL('./vendor/pdfjs/', import.meta.url);
let lib = null;
const docs = new Map(); // url → Promise of the open document

function pdfjs() {
  if (!lib) {
    lib = import('./vendor/pdfjs/pdf.js').then((m) => {
      m.GlobalWorkerOptions.workerSrc = new URL('pdf.worker.js', VENDOR).href;
      return m;
    });
    lib.catch(() => { lib = null; });
  }
  return lib;
}

// What a PDF may use: the Korean character maps shipped beside pdf.js; no scripts, no eval.
const OPTIONS = { cMapUrl: new URL('cmaps/', VENDOR).href, cMapPacked: true, isEvalSupported: false, enableXfa: false };

function open(url) {
  if (!docs.has(url)) {
    const doc = pdfjs().then((m) => m.getDocument({ ...OPTIONS, url }).promise);
    doc.catch(() => docs.delete(url));
    docs.set(url, doc);
  }
  return docs.get(url);
}

// {pages, width, height} of a PDF file before it goes up (the first page, in PDF points), or null
// when it cannot be read.
export async function pdfInfo(file) {
  try {
    const m = await pdfjs();
    const task = m.getDocument({ ...OPTIONS, data: new Uint8Array(await file.arrayBuffer()) });
    const doc = await task.promise;
    const page = await doc.getPage(1);
    const { width, height } = page.getViewport({ scale: 1 });
    const pages = doc.numPages;
    task.destroy();
    return { pages, width, height };
  } catch {
    return null;
  }
}

// Draw page `page` (from 1; past the end, the last) of the PDF at url into canvas, `width`
// device pixels across. The page is drawn aside first and copied in at once, so the canvas
// never shows blank; a later call on the same canvas wins over one still drawing.
// Returns the number of pages, or 0 when a later call took over.
export async function drawPage(canvas, url, page, width) {
  const token = (canvas.pdfToken || 0) + 1;
  canvas.pdfToken = token;
  const doc = await open(url);
  const sheet = await doc.getPage(Math.min(Math.max(1, page || 1), doc.numPages));
  const base = sheet.getViewport({ scale: 1 });
  const viewport = sheet.getViewport({ scale: width / base.width });
  const aside = document.createElement('canvas');
  aside.width = Math.max(1, Math.round(viewport.width));
  aside.height = Math.max(1, Math.round(viewport.height));
  await sheet.render({ canvas: aside, viewport, background: '#ffffff' }).promise;
  if (canvas.pdfToken !== token) return 0;
  canvas.width = aside.width;
  canvas.height = aside.height;
  canvas.getContext('2d').drawImage(aside, 0, 0);
  aside.width = 0; // let the browser free it now
  return doc.numPages;
}
