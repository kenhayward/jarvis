// Deliberately empty of privilege. The renderer is the ordinary JARVIS page
// served over HTTP; it needs nothing from Node, and `contextIsolation` stays
// on. This file exists so that adding something later is a change to a file
// that is already wired up rather than a change to the security model.
