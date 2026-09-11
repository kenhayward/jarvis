"use strict";

// The contract, verbatim from server.py's /api/health:
//   {"status": "online", "name": "JARVIS", "version": "0.1.0"}
//
// The NAME is what identifies it. "Something answered on 8340" is not the
// same fact, and the difference matters: attaching to a stranger would point
// the window at somebody else's server and, worse, could mean this process
// later decides not to start the one JARVIS actually needs.
const JARVIS_NAME = "JARVIS";

// Loopback answers in milliseconds. This bounds a listener that accepts the
// connection and then says nothing, which fetch would otherwise wait on for
// minutes (undici's own header timeout is 300s).
const PROBE_TIMEOUT_MS = 5000;

// "nothing" is ONLY a refused connection. Every other failure means a socket
// was there to fail: measured 2026-09-11, a JARVIS serving HTTPS (cert.pem
// and key.pem beside server.py switch it on) makes an http:// fetch throw
// UND_ERR_SOCKET, not ECONNREFUSED. Reading that as "nothing" would start a
// second server on a taken port. Wrong in this direction, the shell refuses
// loudly instead -- the cheaper mistake.
function refused(error) {
  return Boolean(error && error.cause && error.cause.code === "ECONNREFUSED");
}

async function probe(origin, fetchImpl = fetch, timeoutMs = PROBE_TIMEOUT_MS) {
  const signal = AbortSignal.timeout(timeoutMs);
  let response;
  try {
    response = await fetchImpl(`${origin}/api/health`, { signal });
  } catch (error) {
    return refused(error) ? "nothing" : "stranger";
  }
  if (!response || !response.ok) return "stranger";
  try {
    const body = await response.json();   // the same signal bounds the body
    return body && body.name === JARVIS_NAME ? "jarvis" : "stranger";
  } catch {
    return "stranger";          // answered, but not with our JSON
  }
}

async function waitForJarvis(origin, {
  timeoutMs = 30000,
  intervalMs = 250,
  probeTimeoutMs = PROBE_TIMEOUT_MS,
  fetchImpl = fetch,
  sleep = (ms) => new Promise((r) => setTimeout(r, ms)),
  now = () => Date.now(),
} = {}) {
  const started = now();
  for (;;) {
    if (await probe(origin, fetchImpl, probeTimeoutMs) === "jarvis") return true;
    if (now() - started >= timeoutMs) return false;
    await sleep(intervalMs);
  }
}

module.exports = { probe, waitForJarvis, JARVIS_NAME };
