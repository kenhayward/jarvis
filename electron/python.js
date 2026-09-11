"use strict";
const fs = require("node:fs");
const path = require("node:path");

// Both names, on every platform, rather than branching on process.platform.
//
// A venv's interpreter is `Scripts/python.exe` on Windows and `bin/python` on
// POSIX, and the wrong one simply does not exist, so trying both costs a stat
// and guessing costs a defect. This project has had three separate defects
// from assuming one name — `claude.cmd`, a bare `npm`, and piper's console
// script, which left JARVIS mute on Windows until it was found by running the
// product. This is the fourth place the question comes up, and the first
// where it was answered before anybody hit it.
const CANDIDATES = [
  path.join(".venv", "Scripts", "python.exe"),
  path.join(".venv", "bin", "python"),
];

function findPython(repoRoot) {
  for (const rel of CANDIDATES) {
    const full = path.join(repoRoot, rel);
    try {
      // isFile(), not a bare existence check: a directory with the
      // interpreter's name is not something to spawn, and spawning it fails
      // with an error that names the wrong thing entirely.
      if (fs.statSync(full).isFile()) return full;
    } catch {
      // not there; try the next
    }
  }
  return null;
}

module.exports = { findPython };
