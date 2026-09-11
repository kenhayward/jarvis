const { test } = require("node:test");
const assert = require("node:assert");
const http = require("node:http");
const net = require("node:net");
const { probe, waitForJarvis } = require("../health");

// Verbatim from server.py's /api/health.
const HEALTH = { status: "online", name: "JARVIS", version: "0.1.0" };

// Real listeners on ephemeral ports: what the probe has to tell apart is
// how a real socket fails, and a fake fetch only fails the way its author
// imagined. Every one is torn down, sockets and all, so no test leaves the
// runner waiting on an open handle.
async function serve(t, server) {
  const sockets = new Set();
  server.on("connection", (s) => { sockets.add(s); s.on("close", () => sockets.delete(s)); });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  t.after(() => new Promise((resolve) => {
    for (const s of sockets) s.destroy();
    server.close(() => resolve());
  }));
  return `http://127.0.0.1:${server.address().port}`;
}

function answering(status, body) {
  return http.createServer((req, res) => {
    res.writeHead(status, { "content-type": "application/json" });
    res.end(typeof body === "string" ? body : JSON.stringify(body));
  });
}

async function freeOrigin() {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const { port } = server.address();
  await new Promise((resolve) => server.close(resolve));
  return `http://127.0.0.1:${port}`;
}

test("recognises a JARVIS by name, not merely by answering", async (t) => {
  assert.strictEqual(await probe(await serve(t, answering(200, HEALTH))), "jarvis");
});

test("a stranger on the port is a stranger, not a JARVIS", async (t) => {
  const origin = await serve(t, answering(200, { hello: "i am something else" }));
  assert.strictEqual(await probe(origin), "stranger");
});

test("an error status is a stranger, whatever its body says", async (t) => {
  assert.strictEqual(await probe(await serve(t, answering(404, HEALTH))), "stranger");
});

test("non-JSON on the port does not throw", async (t) => {
  const origin = await serve(t, answering(200, "<html>hello</html>"));
  assert.strictEqual(await probe(origin), "stranger");
});

test("nothing listening is not an error", async () => {
  assert.strictEqual(await probe(await freeOrigin()), "nothing");
});

// Measured 2026-09-11: a real JARVIS started with cert.pem/key.pem beside it
// serves HTTPS, and fetching it over http:// throws UND_ERR_SOCKET -- the same
// way this listener does. Calling that "nothing" would have the supervisor
// start a second server on a port that is already taken.
test("a listener that hangs up is somebody, not nothing", async (t) => {
  const origin = await serve(t, net.createServer((s) => s.once("data", () => s.destroy())));
  assert.strictEqual(await probe(origin), "stranger");
});

test("a listener that never answers does not hang the probe", async (t) => {
  const origin = await serve(t, net.createServer(() => {}));
  assert.strictEqual(await probe(origin, fetch, 200), "stranger");
});

// waitForJarvis is about timing, so its tests own the clock. The refusal is
// shaped the way Node's fetch really reports it: a TypeError whose cause
// carries the socket error's code.
const jarvis = async () => ({ ok: true, json: async () => HEALTH });
const refused = async () => {
  throw Object.assign(new TypeError("fetch failed"), { cause: { code: "ECONNREFUSED" } });
};

test("waitForJarvis returns true as soon as one answers", async () => {
  let calls = 0;
  const late = async () => { calls++; return calls < 3 ? refused() : jarvis(); };
  const ok = await waitForJarvis("http://127.0.0.1:8340", {
    timeoutMs: 5000, intervalMs: 1, fetchImpl: late, sleep: async () => {},
  });
  assert.strictEqual(ok, true);
  assert.strictEqual(calls, 3);
});

test("waitForJarvis gives up rather than hanging forever", async () => {
  let elapsed = 0;
  const ok = await waitForJarvis("http://127.0.0.1:8340", {
    timeoutMs: 50, intervalMs: 10, fetchImpl: refused,
    sleep: async (ms) => { elapsed += ms; },
    now: () => elapsed,
  });
  assert.strictEqual(ok, false);
});

test("waitForJarvis gives up even when the listener never answers", async (t) => {
  const origin = await serve(t, net.createServer(() => {}));
  const started = Date.now();
  const ok = await waitForJarvis(origin, { timeoutMs: 300, intervalMs: 50, probeTimeoutMs: 100 });
  assert.strictEqual(ok, false);
  assert.ok(Date.now() - started < 2000, `took ${Date.now() - started}ms`);
});
