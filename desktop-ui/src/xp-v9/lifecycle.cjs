'use strict';

// Presentation coordinator, not a task runner. Seconds come from a monotonic
// clock. This module owns no timer, worker, result file, audio node, or canvas.
function createLifecycle(options = {}) {
  const clock = options.now || (() => globalThis.performance.now() / 1000);
  const minimumSuccessLevel = Number.isInteger(options.minimumSuccessLevel)
    ? Math.max(0, options.minimumSuccessLevel) : 8;
  const onEffect = typeof options.onEffect === 'function' ? options.onEffect : () => {};
  const closingDuration = options.closingDuration === undefined ? 5.8 : options.closingDuration;
  const maxResources = 32;
  let generation = 0, token = null, phase = 'idle', startAt = 0;
  let successAt = 0, deadline = 0, completionLevel = 0, resultReady = false;
  let lastNow = -Infinity, lastOutcome = null, effectErrors = 0, cleanupErrors = 0;
  const resources = new Set();

  function now() {
    const n = clock();
    if (!Number.isFinite(n)) throw new TypeError('The monotonic clock must return finite seconds');
    // A faulty clock cannot make the level or deadline move backwards.
    lastNow = Math.max(lastNow, n);
    return lastNow;
  }
  function emit(type, eventToken, extra = {}) {
    try { onEffect(Object.freeze({type, token: eventToken, ...extra})); }
    catch (_) { effectErrors++; } // A failed presentation effect never blocks task state.
  }
  function isCurrent(candidate) {
    return token !== null && candidate === token && phase !== 'disposed';
  }
  function clearResources() {
    const old = [...resources];
    resources.clear(); // Clear before callbacks to make reentrant cleanup safe.
    for (const fn of old) {
      try { fn(); } catch (_) { cleanupErrors++; }
    }
  }
  function invalidate(reason, nextPhase = 'idle', preserveResult = false) {
    const oldToken = token;
    token = null;
    generation++;
    phase = nextPhase;
    completionLevel = 0;
    if (!preserveResult) resultReady = false;
    clearResources();
    if (oldToken !== null) emit('presentation-stop', oldToken, {reason});
  }
  function elapsed(at) {
    return Math.max(0, at - startAt);
  }
  function secondsLevel(value) {
    return Math.min(Number.MAX_SAFE_INTEGER, Math.floor(value));
  }
  function durationFor(level) {
    let duration;
    try { duration = typeof closingDuration === 'function' ? closingDuration(level) : closingDuration; }
    catch (_) { duration = 5.8; }
    return Number.isFinite(duration) ? Math.max(0, Math.min(30, duration)) : 5.8;
  }

  function start() {
    if (phase === 'disposed') throw new Error('Lifecycle is disposed');
    const at = now();
    invalidate('superseded');
    // No task cancellation is performed. The job owner decides job policy.
    token = ++generation;
    phase = 'running';
    startAt = at;
    successAt = deadline = 0;
    lastOutcome = null;
    const current = token;
    emit('presentation-start', current);
    return current;
  }

  function complete(candidate) {
    if (!isCurrent(candidate) || phase !== 'running') return false;
    const at = now();
    const seconds = elapsed(at);
    completionLevel = Math.max(minimumSuccessLevel, secondsLevel(seconds));
    successAt = at;
    deadline = at + durationFor(completionLevel);
    phase = 'closing';
    resultReady = true;
    lastOutcome = 'success';
    // Stop running audio/frames/particles. The adapter can register the new
    // closing resources on the same token in response to these effects.
    clearResources();
    if (!isCurrent(candidate) || phase !== 'closing') return true;
    emit('running-stop', candidate, {reason: 'success'});
    if (!isCurrent(candidate) || phase !== 'closing') return true;
    emit('result-ready', candidate, {elapsedSeconds: seconds, completionLevel});
    if (!isCurrent(candidate) || phase !== 'closing') return true;
    emit('success-sound', candidate); // One attempt, only for a true success event.
    if (isCurrent(candidate) && phase === 'closing') {
      emit('closing-start', candidate, {completionLevel, elapsedSeconds: seconds, deadline});
    }
    return true;
  }

  function fail(candidate, outcome) {
    if (!isCurrent(candidate) || phase !== 'running') return false;
    lastOutcome = outcome;
    invalidate(outcome);
    return true;
  }

  function finish(candidate, reason = 'ended') {
    if (!isCurrent(candidate) || phase !== 'closing') return false;
    invalidate(reason, 'idle', true);
    return true;
  }

  function sample() {
    const at = now();
    // The media/animation ended callback is optional. A later frame, visibility
    // change, UI event, or watchdog can sample this deadline and release it.
    if (phase === 'closing' && at >= deadline) finish(token, 'deadline');
    const running = phase === 'running';
    const closing = phase === 'closing';
    const seconds = running ? elapsed(at) : closing ? successAt - startAt : 0;
    const whole = secondsLevel(seconds);
    const level = running ? whole : closing ? completionLevel : 0;
    return Object.freeze({
      phase, token, resultReady, lastOutcome,
      elapsedSeconds: seconds,
      level,
      // No modulo on digits: 999 -> 1000 stays 1000 rather than wrapping.
      levelText: String(level),
      barFraction: running ? seconds - Math.floor(seconds) : 0,
      completionLevel: closing ? completionLevel : 0,
      closingElapsed: closing ? at - successAt : 0,
      deadline: closing ? deadline : null,
      resourceCount: resources.size,
      effectErrors, cleanupErrors
    });
  }

  function registerCleanup(candidate, fn) {
    if (typeof fn !== 'function') throw new TypeError('Cleanup must be a function');
    if (!isCurrent(candidate) || resources.size >= maxResources) {
      try { fn(); } catch (_) { cleanupErrors++; }
      return () => {};
    }
    resources.add(fn);
    return () => resources.delete(fn);
  }

  function reset() {
    if (phase === 'disposed') return;
    if (token === null && phase === 'idle' && resources.size === 0) return;
    invalidate('reset');
  }

  function dispose() {
    if (phase === 'disposed') return;
    invalidate('disposed', 'disposed', true);
  }

  return Object.freeze({
    start, complete, sample, registerCleanup, reset, dispose,
    cancel: candidate => fail(candidate, 'cancelled'),
    error: candidate => fail(candidate, 'error'),
    ended: candidate => finish(candidate, 'ended'),
    skip: candidate => finish(candidate, 'skipped'),
    isCurrent
  });
}

module.exports = {createLifecycle};
