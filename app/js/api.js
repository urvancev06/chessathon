/* Mikhail LeTal web app — JSON API client and polling. */
(() => {
  'use strict';
  const LT = window.LT;
  async function request(method, path, body) {
    const options = { method, headers: {} };
    if (body !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(body); }
    let response;
    try { response = await fetch(path, options); } catch (error) {
      throw Object.assign(new Error('the server is not reachable; is it still running?'), { status: 0 });
    }
    const text = await response.text();
    let payload = null;
    try { payload = text ? JSON.parse(text) : null; } catch (error) { payload = { raw: text }; }
    if (!response.ok) {
      const message = payload && payload.error ? payload.error : `${response.status} ${response.statusText}`;
      throw Object.assign(new Error(message), { status: response.status, message });
    }
    return payload;
  }
  /** GET a text resource (the PGN endpoint); an error carries the server's JSON message. */
  async function text(path) {
    let response;
    try { response = await fetch(path); } catch (error) {
      throw Object.assign(new Error('the server is not reachable; is it still running?'), { status: 0 });
    }
    const body = await response.text();
    if (!response.ok) {
      let message = `${response.status} ${response.statusText}`;
      try { message = JSON.parse(body).error || message; } catch (error) { /* not JSON */ }
      throw Object.assign(new Error(message), { status: response.status, message });
    }
    return body;
  }
  const cache = {};
  LT.api = {
    get: (path) => request('GET', path),
    text,
    post: (path, body) => request('POST', path, body || {}),
    del: (path) => request('DELETE', path),
    /** GET once per page load unless forced; used for /api/info and /api/openings. */
    async cached(path, force = false) {
      if (force || !cache[path]) cache[path] = request('GET', path).catch((error) => { delete cache[path]; throw error; });
      return cache[path];
    },
    /**
     * Call `fn` now and then every `ms` after it settles (never overlapping); returns {cancel}.
     * `fn` may return false to stop.
     */
    poll(fn, ms) {
      let active = true;
      let timer = null;
      const run = async () => {
        if (!active) return;
        let more = true;
        try { more = await fn(); } catch (error) { more = true; }
        if (!active || more === false) return;
        timer = setTimeout(run, ms);
      };
      run();
      return { cancel() { active = false; clearTimeout(timer); } };
    },
  };
})();
