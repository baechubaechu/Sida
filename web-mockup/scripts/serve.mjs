import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';

const root = new URL('../public/', import.meta.url);
const port = Number(process.env.PORT || 4173);
const files = { '/': ['index.html', 'text/html'], '/index.html': ['index.html', 'text/html'], '/styles.css': ['styles.css', 'text/css'], '/app.js': ['app.js', 'text/javascript'], '/model.js': ['model.js', 'text/javascript'] };
const server = createServer(async (req, res) => {
  const path = new URL(req.url, 'http://localhost').pathname;
  const file = files[path];
  if (!['GET', 'HEAD'].includes(req.method) || !file) {
    res.writeHead(404); res.end('Not found'); return;
  }
  try {
    const content = await readFile(new URL(file[0], root));
    res.writeHead(200, { 'Content-Type': `${file[1]}; charset=utf-8`, 'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff' });
    res.end(req.method === 'HEAD' ? undefined : content);
  } catch {
    res.writeHead(500); res.end('Unable to read page');
  }
});
server.listen(port, '127.0.0.1', () => process.stdout.write(`Sida mockup: http://127.0.0.1:${port}\n`));
