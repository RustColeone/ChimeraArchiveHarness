"use strict";
// A student's gut on her page (students.js mounts it under her card): her star map, how grown up she is, her bars
// lately against usual, and, for the owner, her dials and locks: growing up, sensitivity, each feeling, each person
// she knows and her sides. It reads her views (`api/gut/<name>`, `api/starmap/<name>`: worked out when asked, never
// stored) and changes her with `$tune` (`POST api/gut/<name>`, extensions/students/panel.py), one change at a time;
// the answer is her gut as it is then. Only the owner reads it: for anyone else the server says no and nothing shows.
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
  let open = null; // {name, holder, view, map, three, turn, drag, rested, pick, stop, timer, toast}

  function endName(end) {
    const found = open?.view?.ends.find((item) => item.end === end);
    return chinese() && found ? found.zh : end;
  }
  function barName(bar) {
    const named = bar.bar === "composure" ? "SAN" : bar.bar === "pride" ? "self-esteem" : "";
    const name = chinese() ? bar.zh : bar.bar;
    return named ? `${name} · ${named}` : name;
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
  async function tune(change, done) {
    const mine = open;
    try {
      const response = await fetch(`api/gut/${encodeURIComponent(mine.name)}`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(change) });
      const answer = response.ok ? await response.json() : { ok: false, text: "Not changed." };
      if (!answer.ok) mine.toast(answer.text || "Not changed.");
      if (answer.gut && mine === open) mine.view = { ...mine.view, ...answer.gut };
    } catch {
      mine.toast("Could not reach the page's server.");
    }
    if (done) done();
    if (mine === open) {
      render();
      look(); // (her star map, when her heart has changed: her age set by hand, someone forgotten)
    }
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

  // ---- her dials and locks (the owner's) --------------------------------------------------------------------
  function slider({ label, value, low, high, step, show, onChange, disabled = false }) {
    const row = make("label", "gut-slider");
    const out = make("output", "gut-value", show(value));
    const input = make("input");
    Object.assign(input, { type: "range", min: low, max: high, step, value, disabled });
    input.oninput = () => { out.textContent = show(Number(input.value)); };
    input.onchange = () => onChange(Number(input.value), input);
    row.append(make("span", "gut-slider-name", label), input, out);
    return row;
  }
  function check({ label, checked, onChange, disabled = false }) {
    const row = make("label", "gut-check");
    const input = make("input");
    Object.assign(input, { type: "checkbox", checked, disabled });
    input.onchange = () => onChange(input.checked, input);
    row.append(input, make("span", "", label));
    return row;
  }
  function button(label, onClick, kind = "") {
    const node = make("button", `small-button${kind ? ` ${kind}` : ""}`, label);
    node.type = "button";
    node.onclick = onClick;
    return node;
  }
  function pickList(kind, items, chosen) { // one list to choose from; the editor beside it
    const list = make("div", "gut-list");
    for (const item of items) {
      if (item.heading) { list.append(make("div", "gut-list-heading", item.heading)); continue; }
      const row = make("button", `gut-pick${item.key === chosen ? " is-on" : ""}`);
      row.type = "button";
      row.setAttribute("aria-pressed", String(item.key === chosen));
      if (item.colour) {
        const swatch = make("span", "gut-swatch");
        swatch.style.background = item.colour;
        row.append(swatch);
      }
      row.append(make("span", "gut-pick-name", item.label));
      if (item.note) row.append(make("span", "gut-pick-note", item.note));
      row.onclick = () => { open.pick[kind] = item.key; render(); };
      list.append(row);
    }
    return list;
  }

  function growing() {
    const view = open.view, report = view.report, box = make("div", "gut-tune-part");
    box.append(make("h3", "", "Growing up"));
    const age = make("label", "gut-field");
    const ageInput = make("input");
    Object.assign(ageInput, { type: "number", min: 0, step: 1, value: report.age });
    ageInput.onchange = () => {
      const value = Number(ageInput.value);
      if (Number.isFinite(value) && value >= 0) tune({ age: value });
    };
    age.append(make("span", "", "Age (lessons)"), ageInput);
    const tau = make("label", "gut-field");
    const tauInput = make("input");
    Object.assign(tauInput, { type: "number", min: 1, step: 1, value: report.tau });
    tauInput.onchange = () => {
      const value = Number(tauInput.value);
      if (Number.isFinite(value) && value > 0) tune({ tau: value });
    };
    tau.append(make("span", "", "tau (lessons)"), tauInput);
    const row = make("div", "gut-row");
    row.append(age, button("Young again", () => tune({ age: 0 })), tau);
    box.append(row, make("p", "panel-note", "Lower age makes her younger: she learns faster again and forgets nothing. " +
                                            "tau is how fast her heart grows up: fully grown at five times it."),
               check({ label: "Lock her heart", checked: view.locked, onChange: (locked) => tune({ locked }) }),
               make("p", "panel-note", "A locked heart learns nothing and does not grow up, so her nature stays as " +
                                       "set. How she is with each person still learns, unless they are locked too."),
               slider({ label: "Sensitivity", value: report.sensitivity, low: -1, high: 1, step: 0.05,
                        show: (value) => signed(value), onChange: (sensitivity) => tune({ sensitivity }) }),
               make("p", "panel-note", "How hard every moment hits her: -1 thick-skinned, 1 sensitive, 0 as she is."));
    return box;
  }

  function feelings() {
    const view = open.view, box = make("div", "gut-tune-part");
    box.append(make("h3", "", "Each feeling"),
               make("p", "panel-note", "Nature (−6 to 6) is where she stands on a feeling, as if she had been born so: " +
                                       "3 is about even, 6 fully. What she lives moves her on from there. Now (−1 to 1) " +
                                       "is how much more or less she feels it lately than usual. It fades."));
    const items = [];
    for (const bar of view.bars) {
      items.push({ heading: barName(bar) });
      for (const end of bar.ends.filter(Boolean)) {
        const tuned = view.ends.find((item) => item.end === end);
        const marks = [tuned.nature ? `nature ${signed(tuned.nature, 1)}` : "", tuned.now ? `now ${signed(tuned.now)}` : ""];
        items.push({ key: end, label: endName(end), colour: colourOf(end), note: marks.filter(Boolean).join(" · ") });
      }
    }
    const chosen = view.ends.some((item) => item.end === open.pick.end) ? open.pick.end : view.ends[0].end;
    const tuned = view.ends.find((item) => item.end === chosen);
    const editor = make("div", "gut-editor");
    editor.append(make("div", "soft-title", endName(chosen)),
                  slider({ label: "Nature", value: tuned.nature, low: -view.nature, high: view.nature, step: 0.1,
                           show: (value) => signed(value, 1),
                           onChange: (nature) => tune({ tune: [{ end: chosen, nature }] }) }),
                  slider({ label: "Now", value: tuned.now, low: -1, high: 1, step: 0.05, show: (value) => signed(value),
                           onChange: (now) => tune({ tune: [{ end: chosen, now }] }) }));
    const split = make("div", "gut-split");
    split.append(pickList("end", items, chosen), editor);
    box.append(split);
    return box;
  }

  function people() {
    const view = open.view, box = make("div", "gut-tune-part");
    box.append(make("h3", "", "People she knows"),
               make("p", "panel-note", "How she is with each person: what is theirs alone rides on her heart, more as " +
                                       "she knows them (at most 70%). Closeness lives in her memory."));
    if (!view.people.length) {
      box.append(make("p", "panel-note", "Nobody yet."));
      return box;
    }
    const chosen = view.people.some((item) => item.subject === open.pick.person) ? open.pick.person : view.people[0].subject;
    const person = view.people.find((item) => item.subject === chosen);
    const items = view.people.map((item) => ({ key: item.subject, label: personName(item),
                                               note: `${item.lessons} lessons · ${percent(item.weight)}` }));
    const editor = make("div", "gut-editor");
    editor.append(make("div", "soft-title", personName(person)),
                  make("div", "soft-note", `${person.subject} · ${person.lessons} lessons · ${percent(person.weight)} theirs`));
    const byHand = person.set !== null && person.set !== undefined;
    editor.append(check({ label: "Set how much is theirs by hand", checked: byHand,
                          onChange: (on) => tune({ people: [{ subject: chosen, weight: on ? person.weight : "learned" }] }) }),
                  slider({ label: "Theirs", value: byHand ? person.set : person.weight, low: 0, high: 1, step: 0.01,
                           show: percent, disabled: !byHand,
                           onChange: (weight) => tune({ people: [{ subject: chosen, weight }] }) }),
                  check({ label: "Lock how she is with them: what they say teaches nothing, and they do not fade",
                          checked: person.locked, onChange: (locked) => tune({ people: [{ subject: chosen, locked }] }) }));
    const close = person.closeness;
    if (close) {
      editor.append(slider({ label: `closeness (${close.role})`, value: close.value, low: close.floor, high: close.ceiling,
                             step: 1, show: (value) => String(Math.round(value)),
                             onChange: (closeness) => tune({ people: [{ subject: chosen, closeness }] }) }),
                    check({ label: "Hold closeness where it is", checked: close.locked,
                            onChange: (hold) => tune({ people: [{ subject: chosen, hold }] }) }));
    }
    const pickedEnd = view.ends.some((item) => item.end === open.pick.personEnd) ? open.pick.personEnd : view.ends[0].end;
    const ends = make("select", "gut-select");
    ends.setAttribute("aria-label", "A feeling with them");
    for (const bar of view.bars) {
      const group = make("optgroup");
      group.label = barName(bar);
      for (const end of bar.ends.filter(Boolean)) {
        const option = make("option", "", endName(end));
        option.value = end;
        option.selected = end === pickedEnd;
        group.append(option);
      }
      ends.append(group);
    }
    ends.onchange = () => { open.pick.personEnd = ends.value; render(); };
    editor.append(make("div", "soft-note", "A nudge to a feeling with them alone, on top of all she is. It stays."), ends,
                  slider({ label: endName(pickedEnd), value: Number(person.nudge[pickedEnd] || 0), low: -view.nature,
                           high: view.nature, step: 0.1, show: (value) => signed(value, 1),
                           onChange: (nature) => tune({ people: [{ subject: chosen, tune: [{ end: pickedEnd, nature }] }] }) }));
    const nudged = Object.keys(person.nudge || {});
    if (nudged.length) {
      const chips = make("div", "chips");
      for (const end of nudged) {
        const chip = button(`${endName(end)} ${signed(person.nudge[end], 1)}`, () => { open.pick.personEnd = end; render(); },
                            "chip");
        chips.append(chip);
      }
      editor.append(chips);
    }
    editor.append(button("Forget them", () => {
      if (!confirm(window.t("Forget {name}? How she is with them goes, and the sides only they wanted. What they did " +
                            "to her heart stays. Her memory of them is not touched.", { name: window.t(personName(person)) }))) return;
      tune({ people: [{ subject: chosen, forget: true }] });
    }, "is-danger"));
    const split = make("div", "gut-split");
    split.append(pickList("person", items, chosen), editor);
    box.append(split);
    return box;
  }

  function sides() {
    const view = open.view, box = make("div", "gut-tune-part");
    box.append(make("h3", "", "Sides (属性)"),
               make("p", "panel-note", "A side is a kind of character: a name and one sentence saying what she does. " +
                                       "She is in one at a time, for a month at least, drawn by weight. One locked by hand " +
                                       "is hers until unlocked."));
    const tags = make("div", "chips gut-tags");
    const chosen = view.sides.some((item) => item.name === open.pick.side) ? open.pick.side : view.sides[0]?.name;
    for (const side of view.sides) {
      const tag = button(side.name, () => { open.pick.side = side.name; render(); },
                         `chip gut-tag${side.name === chosen ? " is-on" : ""}${view.side?.name === side.name ? " is-locked" : ""}`);
      tag.setAttribute("aria-pressed", String(side.name === chosen));
      tags.append(tag);
    }
    const names = make("select", "gut-select");
    names.setAttribute("aria-label", "A name");
    const blank = make("option", "", "Choose a name");
    blank.value = "";
    names.append(blank);
    for (const name of view.names.filter((item) => !view.sides.some((side) => side.name === item))) {
      const option = make("option", "", name);
      option.value = name;
      names.append(option);
    }
    const add = button("Add", () => {
      if (!names.value) return;
      const what = prompt(window.t("What she does in her {side} side, said to her (\"You…\")", { side: names.value }));
      if (!what || !what.trim()) return;
      open.pick.side = names.value;
      tune({ sides: [{ name: names.value, what: what.trim(), weight: view.grows }] });
    });
    const adding = make("div", "gut-row");
    adding.append(names, add);
    box.append(tags, adding);
    const side = view.sides.find((item) => item.name === chosen);
    if (!side) {
      box.append(make("p", "panel-note", "No sides yet."));
      return box;
    }
    const editor = make("div", "gut-editor");
    const sentence = make("textarea", "gut-sentence");
    sentence.value = side.what;
    sentence.maxLength = 200;
    sentence.rows = 2;
    sentence.setAttribute("aria-label", "What she does, said to her");
    const weight = make("label", "gut-field");
    const weightInput = make("input");
    Object.assign(weightInput, { type: "number", min: 0, step: 0.5, value: side.own || side.weight });
    weight.append(make("span", "", "Weight when drawn"), weightInput);
    const locked = view.side?.name === side.name;
    editor.append(make("div", "soft-title", side.name), sentence,
                  button("Save the sentence", () => {
                    const what = sentence.value.trim();
                    if (what) tune({ sides: [{ name: side.name, what }] });
                  }), weight,
                  check({ label: "Lock her in this side", checked: locked,
                          onChange: (on) => tune({ side: on ? { name: side.name, often: view.side?.often ?? 1 } : null }) }));
    weightInput.onchange = () => {
      const value = Number(weightInput.value);
      if (Number.isFinite(value) && value >= 0) tune({ sides: [{ name: side.name, weight: value }] });
    };
    if (locked) {
      editor.append(slider({ label: "How often", value: view.side.often, low: 0, high: 1, step: 0.05, show: percent,
                             onChange: (often) => tune({ side: { name: side.name, often } }) }),
                    make("p", "panel-note", "The share of her turns the sentence goes beside the message."));
    }
    editor.append(button("Remove", () => {
      if (!confirm(window.t("Drop her {side} side? It goes with what taught it, so growing it again starts over.",
                            { side: side.name }))) return;
      tune({ sides: [{ name: side.name, drop: true }] });
    }, "is-danger"));
    box.append(editor);
    return box;
  }

  // ---- the section ---------------------------------------------------------------------------------------------
  function render() {
    if (!open || !open.view) return;
    open.stop?.();
    open.stop = null;
    const holder = open.holder;
    const scrolled = [...holder.querySelectorAll(".gut-list")].map((node) => node.scrollTop);
    const section = make("section", "panel gut-panel");
    const title = make("h2", "", "Her gut");
    title.append(make("span", "panel-aside", " · mneme-llm"));
    section.append(title, make("p", "panel-note", "What stays of her when her memory is wiped and her model is swapped: " +
                                                  "her heart, how she is with each person, her sides. Only you see this."));
    const top = make("div", "gut-top");
    top.append(starMap(), standing());
    const tuning = make("div", "gut-tune");
    tuning.append(make("h3", "gut-tune-title", "Tune her"), growing(), feelings(), people(), sides());
    section.append(top, tuning);
    holder.replaceChildren(section);
    holder.querySelectorAll(".gut-list").forEach((node, index) => { node.scrollTop = scrolled[index] || 0; });
  }

  /** Her gut under her card, in `holder` (empty until it is read, and stays so for anyone but the owner). */
  function mount(holder, name, toast) {
    if (open) { open.stop?.(); clearInterval(open.timer); }
    open = { name, holder, view: null, map: null, three: kept.get(SAVED) === "3d", turn: { yaw: 0.6, pitch: -0.32 },
             drag: null, rested: 0, pick: { end: null, person: null, personEnd: null, side: null }, stop: null,
             timer: setInterval(look, EVERY), toast: toast || (() => {}) };
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
  window.GutPanel = { mount, unmount };
})();
