"use strict";

// What the JARVIS window will let a page do. Kept free of Electron so it can
// be tested with node:test, like the supervisor.

// Parsed origins, never string prefixes: "http://127.0.0.1:8340.example.com"
// starts with the JARVIS origin and is somebody else entirely.
function sameOrigin(url, origin) {
  try {
    return new URL(url).origin === new URL(origin).origin;
  } catch {
    return false;
  }
}

// Electron DENIES media unless a permission handler says yes (measured in
// 4-zero), so there has to be one -- and a handler that says yes to "media"
// says it to whatever page the window is showing, camera included. This one
// says yes to the JARVIS page's microphone and to nothing else.
function grantsPermission(permission, details, origin) {
  if (permission !== "media") return false;
  if (!details || !sameOrigin(details.requestingUrl, origin)) return false;
  const types = details.mediaTypes;
  return Array.isArray(types) && types.length > 0 && types.every((t) => t === "audio");
}

module.exports = { sameOrigin, grantsPermission };
