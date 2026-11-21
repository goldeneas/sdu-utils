import assert from "node:assert/strict";
import { createServer } from "node:http";
import { connect } from "node:net";
import { once } from "node:events";
import test from "node:test";
import { closePreview } from "../scripts/preview.mjs";

test("preview cleanup releases an unfinished HTTP request", { timeout: 3000 }, async t => {
  const server = createServer();
  server.listen(0, "127.0.0.1");
  await once(server, "listening");
  const socket = connect(server.address().port, "127.0.0.1");
  t.after(() => { socket.destroy(); server.closeAllConnections(); server.close(); });
  await once(socket, "connect");
  const request = once(server, "request");
  socket.write("POST /download HTTP/1.1\r\nHost: localhost\r\nContent-Length: 100\r\n\r\nx");
  await request;
  const closed = once(socket, "close");
  await closePreview({ httpServer: server });
  await closed;
  assert.equal(server.listening, false);
  assert.equal(socket.destroyed, true);
});
