"use strict";

// Whether the recogniser JARVIS is configured with can hear anything here,
// read from /api/settings/status. Two ways it cannot, both silent:
//
// - `browser`: Electron has no speech service. Measured in 4-zero,
//   webkitSpeechRecognition is DEFINED there and fails at runtime with
//   error=network, so the page looks alive and never returns a word.
// - `whisper` without its package or model: stt.transcribe returns None for
//   every utterance and says so only in the server's log.
//
// This reports; it does not fix. Rewriting the user's .env to suit the
// application is worse than explaining what is wrong -- a program that edits
// configuration behind you is harder to trust than one that is inconvenient.
// And it says nothing when it cannot tell: a warning built on a guess is
// noise the next real one has to talk over.
function sttWarning(status, python) {
  if (!status || typeof status.stt_backend !== "string") return null;
  const py = /\s/.test(python) ? `"${python}"` : python;
  const install =
    `    ${py} -m pip install -r requirements-stt.txt\n` +
    `    ${py} -c "from faster_whisper import WhisperModel; WhisperModel('base.en')"`;

  if (status.stt_backend === "browser") {
    return (
      "JARVIS is set to use the browser's speech recogniser, and Electron has " +
      "no speech service behind it -- nothing will be transcribed.\n\n" +
      "Set JARVIS_STT_BACKEND=whisper in .env and restart JARVIS. If the " +
      "local recogniser is not installed yet, from the repository:\n" + install
    );
  }

  const ready = status.stt_backends_ready;
  if (status.stt_backend === "whisper" && ready && ready.whisper === false) {
    return (
      "JARVIS is set to use the local speech recogniser, but it is not " +
      "installed -- nothing will be transcribed.\n\n" +
      "From the repository (the second line fetches the model, about " +
      "141 MB, once; use your JARVIS_STT_MODEL if you set one):\n" + install
    );
  }
  return null;
}

module.exports = { sttWarning };
