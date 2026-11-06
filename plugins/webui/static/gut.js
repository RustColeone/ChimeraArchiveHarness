"use strict";
// A student's gut on her page (students.js mounts it under her card): her star map, how grown up she is and her bars
// lately against usual. It reads her views (`api/gut/<name>`, `api/starmap/<name>`: worked out when asked, never
// stored), and looks again while it is in view. What changes her is her settings, below it (mneme-settings.js, its Gut
// tab). Only the owner reads it: for anyone else the server says no and nothing shows.
(() => {
  const EVERY = 15000; // how often it looks again while it is in view (a lesson lands a few seconds after a turn)
  const TURNING = 0.12; // in 3D, radians a second it turns by itself while nobody turns it
  const RESTS = 3000; // and milliseconds after a drag before it does again
  const SAVED = "students.map3d"; // (the browser keeps which view was chosen)
  const make = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = text;
    return node;
  };
  const kept = {
    get(key) { try { return localStorage.getItem(key); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* private window */ } },
  };
  const percent = (value) => `${Math.round((Number(value) || 0) * 100)}%`;
  const signed = (value, digits = 2) => `${value > 0 ? "+" : value < 0 ? "−" : "±"}${Math.abs(value).toFixed(digits)}`;
  const chinese = () => window.uiLanguage === "zh";
  const dark = () => {
    const theme = document.documentElement.dataset.theme;
    return theme === "dark" || (theme !== "light" && Boolean(window.matchMedia?.("(prefers-color-scheme: dark)").matches));
  };

  // What is open: one student's gut at a time.
  let open = null; // {name, holder, view, map, three, turn, drag, rested, stop, timer, toast}

  function endName(end) {
    const found = open?.view?.ends.find((item) => item.end === end);
    return chinese() && found ? found.zh : end;
  }
  function personName(person) {
    return person.you ? "You" : person.name || person.subject;
  }
  function colourOf(end) {
    const view = open.view, index = view.ends.findIndex((item) => item.end === end);
    return window.GutMap.colours(view.bars, dark())[index] || "currentColor";
  }

  // ---- reading and changing -------------------------------------------------------------------------------
  async function read(path) {
    const response = await fetch(path, { headers: { Accept: "application/json" } });
    if (response.status === 401) { location.href = "login"; return null; }
    if (!response.ok) return { refused: response.status };
    return response.json();
  }
  async function look() {
    if (!open || document.hidden || !open.holder.isConnected) return;
    const mine = open;
    const view = await read(`api/gut/${encodeURIComponent(mine.name)}`).catch(() => null);
    if (mine !== open) return;
    if (!view || view.refused) {
      if (view?.refused === 403 || view?.refused === 404) mine.holder.replaceChildren(); // not hers to see, or no gut
      return;
    }
    const changed = mine.view?.stamp !== view.stamp;
    mine.view = view;
    if (changed || !mine.map) {
      const map = await read(`api/starmap/${encodeURIComponent(mine.name)}`).catch(() => null);
      if (mine === open && map && !map.refused) mine.map = map;
    }
    if (mine === open) render();
  }
  // ---- her star map ---------------------------------------------------------------------------------------
  function starMap() {
    const map = open.map, box = make("div", "gut-map");
    const head = make("div", "gut-map-head");
    const views = make("div", "segmented is-small");
    views.setAttribute("role", "group");
    views.setAttribute("aria-label", "View");
    for (const three of [false, true]) {
      const button = make("button", "", three ? "3D" : "2D");
      button.type = "button";
      button.setAttribute("aria-pressed", String(open.three === three));
      button.onclick = () => { open.three = three; kept.set(SAVED, three ? "3d" : "2d"); render(); };
      views.append(button);
    }
    head.append(make("h3", "", "Star map"), views);
    box.append(head);
    if (!map) {
      box.append(make("p", "panel-note", "Reading her heart…"));
      return box;
    }
    const canvas = make("canvas", `gut-canvas${open.three ? " is-turning" : ""}`);
    canvas.setAttribute("role", "img");
    canvas.setAttribute("aria-label", "Her star map: each dot is one thing she notices, placed toward the feeling " +
                                      "it pulls her to. The big stars are people.");
    const paint = () => {
      if (!canvas.isConnected || !open?.map) return;
      const look = { dark: dark(), ink: getComputedStyle(canvas).color, colours: window.GutMap.colours(open.view.bars, dark()),
                     names: open.map.ends.map(endName),
                     label: (subject) => {
                       const person = open.view.people.find((item) => item.subject === subject);
                       return person ? window.t(personName(person)) : subject;
                     } };
      if (open.three) window.GutMap.drawRound(canvas, open.map, look, open.turn);
      else window.GutMap.drawFlat(canvas, open.map, look);
    };
    canvas.addEventListener("pointerdown", (event) => {
      if (!open.three) return;
      open.drag = { x: event.clientX, y: event.clientY };
      try { canvas.setPointerCapture(event.pointerId); } catch { /* a pointer the page no longer holds */ }
    });
    canvas.addEventListener("pointermove", (event) => {
      const held = open.drag;
      if (!open.three || !held) return;
      open.turn.yaw += (event.clientX - held.x) * 0.01;
      open.turn.pitch = Math.max(-1.4, Math.min(1.4, open.turn.pitch + (event.clientY - held.y) * 0.01));
      held.x = event.clientX;
      held.y = event.clientY;
      paint();
    });
    const up = () => { open.drag = null; open.rested = Date.now(); };
    canvas.addEventListener("pointerup", up);
    canvas.addEventListener("pointercancel", up);
    const resized = typeof ResizeObserver === "function" ? new ResizeObserver(paint) : null;
    resized?.observe(canvas);
    let frame = null, last = null, painted = 0, seen = true;
    const watched = typeof IntersectionObserver === "function"
      ? new IntersectionObserver((entries) => { seen = entries.some((entry) => entry.isIntersecting); }) : null;
    watched?.observe(canvas);
    const still = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    const tick = (at) => {
      if (last !== null && seen && !document.hidden && !open?.drag && Date.now() - (open?.rested || 0) > RESTS) {
        open.turn.yaw += TURNING * Math.min(0.1, (at - last) / 1000);
        if (at - painted >= 33) { paint(); painted = at; } // (about 30 a second: it turns slowly)
      }
      last = at;
      frame = requestAnimationFrame(tick);
    };
    if (open.three && !still && window.requestAnimationFrame) frame = requestAnimationFrame(tick);
    if (!resized) requestAnimationFrame(paint);
    open.stop = () => {
      resized?.disconnect();
      watched?.disconnect();
      if (frame !== null) cancelAnimationFrame(frame);
    };
    box.append(canvas);
    if (open.three) box.append(make("p", "panel-note", "Drag to turn it. A few seconds later it turns slowly by itself. " +
                                                       "The two ends of each bar sit side by side."));
    box.append(make("p", "panel-note", map.probed >= 20
      ? `${map.stars.length} brightest of ${map.rows} · arms from her last ${map.probed} lessons`
      : `${map.stars.length} brightest of ${map.rows} · arms as born until 20 lessons (${map.probed} so far)`));
    box.append(make("p", "panel-note", "Each dot is one thing she notices, placed toward the feeling it pulls her to: " +
                                       "the brighter, the more it leans. The lines are her arms: how much more or less " +
                                       "of each feeling she has now than when she was born (the ring). The big stars are people."));
    return box;
  }

  // ---- how she is --------------------------------------------------------------------------------------------
  function barRow(bar) {
    const [left, right] = bar.ends, two = Boolean(left);
    const at = (value) => two ? 50 + Math.max(-1, Math.min(1, value)) * 50 : Math.max(0, Math.min(1, value)) * 100;
    const row = make("div", "gut-bar");
    const track = make("div", `gut-track${two ? " is-two" : ""}`);
    if (two) track.append(make("span", "gut-middle"));
    const fill = make("span", "gut-fill");
    const from = two ? Math.min(50, at(bar.lately)) : 0, to = two ? Math.max(50, at(bar.lately)) : at(bar.lately);
    fill.style.left = `${from}%`;
    fill.style.width = `${Math.max(0.5, to - from)}%`;
    fill.style.background = colourOf(two && bar.lately < 0 ? left : right);
    const tick = make("span", "gut-tick");
    tick.style.left = `${at(bar.usual)}%`;
    track.append(fill, tick);
    track.title = `lately ${signed(bar.lately)} · usual ${signed(bar.usual)}`;
    row.append(make("span", "gut-end", left ? endName(left) : ""), track, make("span", "gut-end is-right", endName(right)));
    return row;
  }
  function standing() {
    const view = open.view, report = view.report, box = make("div", "gut-standing");
    const grown = make("div", "soft-box");
    grown.append(make("div", "soft-title", `Grown up ${percent(report.grown)}`),
                 make("div", "soft-note", `${report.age} lessons of ${report.lessons} taught her heart · fully grown ` +
                                          `at ${Math.round(5 * report.tau)} (tau ${report.tau})`),
                 make("div", "soft-note", view.locked ? `She learns at ${percent(report.learning)} of her young pace · ` +
                                                        "her heart is locked" : `She learns at ${percent(report.learning)} of her young pace`));
    const levels = make("div", "gut-levels");
    for (const [name, value] of [["SAN", report.SAN], ["Self-esteem", report["self-esteem"]]]) {
      const cell = make("div", "soft-box gut-level");
      cell.append(make("div", "soft-note", name), make("div", "gut-level-number", signed(value)));
      levels.append(cell);
    }
    const bars = make("div", "gut-bars");
    bars.append(make("h3", "", "Lately against usual"),
                make("p", "panel-note", "The bar is lately, the tick is usual. A two-sided bar leans from the middle toward one end."));
    for (const bar of view.bars) bars.append(barRow(bar));
    box.append(grown, levels, bars);
    return box;
  }

  // ---- the section ---------------------------------------------------------------------------------------------
  function render() {
    if (!open || !open.view) return;
    open.stop?.();
    open.stop = null;
    const holder = open.holder;
    const section = make("section", "panel gut-panel");
    const title = make("h2", "", "Her gut");
    title.append(make("span", "panel-aside", " · mneme-llm"));
    section.append(title, make("p", "panel-note", "What stays of her when her memory is wiped and her model is swapped: " +
                                                  "her heart, how she is with each person, her sides. Only you see this."));
    const top = make("div", "gut-top");
    top.append(starMap(), standing());
    section.append(top);
    holder.replaceChildren(section);
  }

  /** Her gut under her card, in `holder` (empty until it is read, and stays so for anyone but the owner). */
  function mount(holder, name, toast) {
    if (open) { open.stop?.(); clearInterval(open.timer); }
    open = { name, holder, view: null, map: null, three: kept.get(SAVED) === "3d", turn: { yaw: 0.6, pitch: -0.32 },
             drag: null, rested: 0, stop: null, timer: setInterval(look, EVERY), toast: toast || (() => {}) };
    look();
  }
  /** Her page is gone: nothing more is read. */
  function unmount() {
    if (!open) return;
    open.stop?.();
    clearInterval(open.timer);
    open = null;
  }
  window.matchMedia?.("(prefers-color-scheme: dark)").addEventListener?.("change", render);
  /** Read her again now (a save on her settings page changed her). */
  function refresh() {
    if (open) look();
  }
  window.GutPanel = { mount, unmount, refresh };
})();
