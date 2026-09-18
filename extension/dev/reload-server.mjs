// Dev reload server: watches the extension source and tells the extension
// (loaded unpacked in the user's normal Chrome) to reload itself.
//
// The counterpart lives at the end of background.js: on unpacked installs
// only, the service worker connects to ws://127.0.0.1:18766 and calls
// chrome.runtime.reload() when this server broadcasts "reload". The server
// pings every 20s, which keeps the service worker awake (Chrome 116+ resets
// the idle timer on WebSocket activity), so reloads arrive even after long
// idle periods.
//
// No dependencies: the WebSocket server side (handshake + unmasked text
// frames) is small enough to implement inline.
//
// Usage: node extension/dev/reload-server.mjs
//   POST /reload forces a reload (used by the /reload skill).
//   GET  /       reports status and connected client count.

import { createServer } from 'node:http';
import { createHash } from 'node:crypto';
import { watch } from 'node:fs';
import { join, dirname, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const PORT = 18766;
const EXT_DIR = join(dirname(fileURLToPath(import.meta.url)), '..');
const WS_GUID = '258EAFA5-E914-47DA-95CA-C5AB0DC85B11';

// Changes to these never affect the running extension.
const IGNORE = /(^|\/)(dev|test|node_modules|\.web-ext-profile|\.[^/]+)\/|\.md$|^\.[^/]*$/;

const sockets = new Set();

// A reload requested while the extension's service worker is asleep (no
// client connected) is delivered the moment it reconnects, so changes are
// never lost to the worker's idle timeout.
let pendingReload = false;

function stamp() {
  return new Date().toLocaleTimeString('en-GB');
}

function textFrame(message) {
  const payload = Buffer.from(message);
  if (payload.length > 125) throw new Error('frame too large');
  return Buffer.concat([Buffer.from([0x81, payload.length]), payload]);
}

function broadcast(message) {
  for (const socket of sockets) {
    socket.write(textFrame(message));
  }
  return sockets.size;
}

const server = createServer((req, res) => {
  if (req.method === 'POST' && req.url === '/reload') {
    const clients = broadcast('reload');
    if (!clients) {
      pendingReload = true;
    }
    res.end(JSON.stringify({ reloaded: clients, queued: !clients }));
    console.log(
      clients
        ? `[reload-server] forced reload sent to ${clients} client(s) at ${stamp()}`
        : `[reload-server] forced reload queued at ${stamp()} (no client; delivered on next connect)`,
    );
    return;
  }
  res.end(JSON.stringify({ status: 'ok', clients: sockets.size, pendingReload }));
});

server.on('upgrade', (req, socket) => {
  const key = req.headers['sec-websocket-key'];
  if (!key) {
    socket.destroy();
    return;
  }
  const accept = createHash('sha1')
    .update(key + WS_GUID)
    .digest('base64');
  socket.write(
    'HTTP/1.1 101 Switching Protocols\r\n' +
      'Upgrade: websocket\r\n' +
      'Connection: Upgrade\r\n' +
      `Sec-WebSocket-Accept: ${accept}\r\n\r\n`,
  );
  sockets.add(socket);
  console.log(`[reload-server] ${stamp()} extension connected (${sockets.size} client(s))`);
  if (pendingReload) {
    pendingReload = false;
    socket.write(textFrame('reload'));
    console.log(`[reload-server] ${stamp()} queued reload delivered`);
  }
  const drop = () => {
    if (sockets.delete(socket)) {
      console.log(`[reload-server] ${stamp()} extension disconnected (${sockets.size} client(s))`);
    }
    socket.destroy();
  };
  socket.on('close', drop);
  socket.on('error', drop);
  // Incoming frames (close, etc.) are irrelevant; dropping on close/error
  // above is enough.
  socket.on('data', () => {});
});

// WebSocket activity keeps the extension service worker alive, so the
// connection survives Chrome's 30s idle timeout.
setInterval(() => broadcast('ping'), 20000);

let pending = null;
watch(EXT_DIR, { recursive: true }, (_event, filename) => {
  if (!filename || IGNORE.test(filename)) return;
  clearTimeout(pending);
  pending = setTimeout(() => {
    const clients = broadcast('reload');
    if (!clients) {
      pendingReload = true;
    }
    console.log(
      `[reload-server] ${filename} changed -> reload ${clients ? `sent to ${clients} client(s)` : 'queued (no client)'} at ${stamp()}`,
    );
  }, 300);
});

server.listen(PORT, '127.0.0.1', () => {
  console.log(`[reload-server] watching ${relative(process.cwd(), EXT_DIR) || '.'}`);
  console.log(
    `[reload-server] listening on http://127.0.0.1:${PORT} — the extension reloads on every source change`,
  );
});
