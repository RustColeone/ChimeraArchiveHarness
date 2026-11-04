"use strict";
// Her star map on a canvas, for her page (students.js draws it from her `students.starmap` view): flat, or in 3D,
// turned by a drag and slowly by itself. The same drawing as the mneme-llm tuner's (docs/tune/starmap.js) and the
// DSH plugin's panel, so her map looks the same everywhere. `look`: { dark, ink, names (each end's name, in her ends'
// order), colours (each end's) }.
(() => {
  const ARM = 2.0 // an arm is drawn at most this many base radii long
  const LABELS = 2.2 // and the names of the ends no further out than this
  const EYE = 6.0 // in 3D, the eye is this many base radii from the middle: what is near looks a little bigger
  const MOST = 0.7 // the most of how she is with someone that is theirs alone (`MOST` in mneme-llm's gut)
  const T = { MOST }
  const angleOf = (map, k) => -Math.PI / 2 + 2 * Math.PI * k / map.ends.length

  // One colour for each of her 14 bars, in her bars' order, as the tuner and the DSH plugin's panel have them: the first
  // end of a bar a deeper shade, the second (and a one-sided bar's only end) a lighter one, stepped for each theme.
  const COLOURS = {
    dark: {
      deep: ['#ca5551', '#12976b', '#9167ca', '#a57710', '#128eaa', '#c35481', '#54932d', '#6676d8', '#c36109',
        '#13938f', '#b05bab', '#888510', '#1485d4', '#0f919c'],
      light: ['#ffaba3', '#72ddae', '#d0b4fd', '#ecbb64', '#58d6f9', '#fea6c5', '#a1d687', '#b2c0ff', '#fdb080',
        '#4fddd7', '#f0a7ea', '#cbca69', '#91caff', '#4ddae9']
    },
    light: {
      deep: ['#972e2d', '#0c6849', '#674098', '#735100', '#0b6276', '#912d59', '#316802', '#424da5', '#884204',
        '#0f6562', '#81357d', '#5d5b0a', '#0a5c94', '#0d646c'],
      light: ['#ce766f', '#44a87f', '#9f81cb', '#b68a37', '#22a2c0', '#c97493', '#73a25b', '#7d8cd7', '#c87e4d',
        '#0ca8a3', '#b878b3', '#99973d', '#5498d3', '#05a5b3']
    }
  }

  // ---- drawing ----------------------------------------------------------------------------------------------------
  // `look`: { dark, ink, names (each end's name, in ENDS order), colours (each end's), label (subject → the name
  // shown) }.

  function canvasOf (canvas) {
    const width = Math.max(120, Math.round(canvas.getBoundingClientRect().width))
    const ratio = (typeof window !== 'undefined' && window.devicePixelRatio) || 1
    if (canvas.width !== width * ratio) {
      canvas.width = width * ratio
      canvas.height = width * ratio
    }
    const g = canvas.getContext('2d')
    g.setTransform(ratio, 0, 0, ratio, 0, 0)
    g.clearRect(0, 0, width, width)
    return { g, width }
  }

  function sky (g, width, dark) {
    g.fillStyle = dark ? '#0a0d16' : 'rgba(127, 127, 127, 0.07)'
    g.beginPath()
    if (g.roundRect) g.roundRect(0, 0, width, width, 12)
    else g.rect(0, 0, width, width)
    g.fill()
  }

  /** How bright each star is drawn: against the brighter stars of this map. */
  function topOf (map) {
    const brights = map.stars.map(star => star[2]).sort((one, other) => one - other)
    return Math.max(0.05, brights[Math.floor(brights.length * 0.97)] ?? 1)
  }

  function personDot (g, { px, py, size, person }, look, colour, width, font) {
    if (look.dark) {
      g.fillStyle = 'rgba(255, 255, 255, 0.14)'
      g.beginPath()
      g.arc(px, py, size * 2.4, 0, 2 * Math.PI)
      g.fill()
    }
    g.fillStyle = look.dark ? '#ffffff' : '#1d1d1f'
    g.strokeStyle = colour[person.end] ?? look.ink
    g.lineWidth = 2
    g.beginPath()
    g.arc(px, py, size, 0, 2 * Math.PI)
    g.fill()
    g.stroke()
    const label = look.label ? look.label(person.subject) : person.subject
    g.font = `600 ${font + 1}px system-ui, -apple-system, sans-serif`
    g.textBaseline = 'middle'
    const left = px + size + 4 + g.measureText(label).width > width - 4
    g.textAlign = left ? 'right' : 'left'
    g.lineWidth = 3
    g.strokeStyle = look.dark ? '#0a0d16' : 'rgba(255, 255, 255, 0.9)'
    g.strokeText(label, left ? px - size - 4 : px + size + 4, py)
    g.fillStyle = look.ink
    g.fillText(label, left ? px - size - 4 : px + size + 4, py)
    g.lineWidth = 1
  }

  /** The base radius of the flat map: as big as fits, with each end's name at its arm's tip, read outward. */
  function baseRadius (half, arms, widths, gap = 0.12) {
    return Math.min(...arms.map((arm, k) => (half - 4 - widths[k] - 6) / Math.min(LABELS, Math.min(ARM, arm) + gap)))
  }

  /** Her star map, flat. */
  function drawFlat (canvas, map, look) {
    const { g, width } = canvasOf(canvas)
    const half = width / 2, font = Math.max(9, Math.min(12, width / 36))
    const scale = Math.max(0.55, Math.min(1, width / 520)) // (stars smaller on a small map)
    sky(g, width, look.dark)
    g.font = `${font}px system-ui, -apple-system, sans-serif`
    const arms = map.reach.map(reach => Math.min(ARM, reach))
    const R = Math.max(10, baseRadius(half, arms, look.names.map(name => g.measureText(name).width)))
    const colour = look.colours
    // the ring: as she was born; then her arms, and the names of her ends at their tips
    g.strokeStyle = look.dark ? 'rgba(255, 255, 255, 0.16)' : 'rgba(0, 0, 0, 0.14)'
    g.setLineDash([3, 4])
    g.beginPath()
    g.arc(half, half, R, 0, 2 * Math.PI)
    g.stroke()
    g.setLineDash([])
    map.ends.forEach((end, k) => {
      const a = angleOf(map, k), x = half + arms[k] * R * Math.cos(a), y = half + arms[k] * R * Math.sin(a)
      g.strokeStyle = colour[k]
      g.globalAlpha = 0.45
      g.beginPath()
      g.moveTo(half, half)
      g.lineTo(x, y)
      g.stroke()
      g.globalAlpha = 1
      g.fillStyle = colour[k]
      g.beginPath()
      g.arc(x, y, 2.2, 0, 2 * Math.PI)
      g.fill()
      const out = Math.min(LABELS, arms[k] + 0.12) * R, back = Math.cos(a) < -1e-6
      g.save()
      g.translate(half, half)
      g.rotate(back ? a + Math.PI : a)
      g.fillStyle = look.ink
      g.globalAlpha = 0.8
      g.textBaseline = 'middle'
      g.textAlign = back ? 'right' : 'left'
      g.fillText(look.names[k], back ? -out : out, 0)
      g.restore()
    })
    // the stars, dimmest first
    const top = topOf(map)
    const place = (x, y) => {
      const far = Math.hypot(x, y), cut = far > ARM ? ARM / far : 1 // (inside the map, whatever her arms)
      return [half + x * cut * R, half + y * cut * R]
    }
    for (let i = map.stars.length - 1; i >= 0; i--) {
      const [x, y, bright, end] = map.stars[i], [px, py] = place(x, y)
      const lean = Math.min(1, bright / top), size = (0.7 + 2.3 * lean) * scale
      g.fillStyle = colour[end]
      if (look.dark && lean > 0.5) { // (a glow on the dark sky, for the stars that lean most)
        g.globalCompositeOperation = 'lighter'
        g.globalAlpha = 0.12 * lean
        g.beginPath()
        g.arc(px, py, size * 3.2, 0, 2 * Math.PI)
        g.fill()
        g.globalCompositeOperation = 'source-over'
      }
      g.globalAlpha = 0.25 + 0.75 * lean
      g.beginPath()
      g.arc(px, py, size, 0, 2 * Math.PI)
      g.fill()
    }
    g.globalAlpha = 1
    // the people she knows: one big star each, as big as how much of how she is with them is theirs
    const people = map.people.map(person => {
      const [px, py] = place(person.x, person.y)
      return { px, py, size: (4 + 8 * Math.min(1, person.weight / T.MOST)) * scale, person }
    })
    for (const item of people) personDot(g, item, look, colour, width, font)
  }

  /** A point of the 3D map seen from where it is turned: across, down the screen, toward the eye, and how much nearer
   * things look bigger. */
  function project ([x, y, z], { yaw, pitch }) {
    const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch)
    const x1 = x * cy + z * sy, z1 = z * cy - x * sy
    const y2 = y * cp - z1 * sp, z2 = y * sp + z1 * cp
    const near = EYE / (EYE - z2)
    return [x1 * near, -y2 * near, z2, near]
  }

  /** Where each end's name goes in 3D, the front ones first: a line up or down off a nearer name it would cover, or
   * left out while it cannot be (it is further back; as the map turns, it comes back). k → {x, y, align}. */
  function placeNames (g, tips, names, half, font) {
    const taken = [], places = new Map(), tall = font + 2
    for (const tip of [...tips].sort((one, other) => other.z - one.z)) {
      const [x, at] = tip.label, wide = g.measureText(names[tip.k]).width
      const align = x < half - 2 ? 'right' : x > half + 2 ? 'left' : 'center'
      const left = align === 'right' ? x - wide : align === 'center' ? x - wide / 2 : x
      const free = y => !taken.some(([x0, y0, x1, y1]) => left < x1 && left + wide > x0 && y - tall / 2 < y1 &&
        y + tall / 2 > y0)
      const y = [at, at - tall, at + tall].find(free)
      if (y === undefined) continue
      taken.push([left - 2, y - tall / 2, left + wide + 2, y + tall / 2])
      places.set(tip.k, { x, y, align })
    }
    return places
  }

  /** Her star map in 3D, turned by `turn` ({yaw, pitch}): the nearer, the brighter. */
  function drawRound (canvas, map, look, turn) {
    const { g, width } = canvasOf(canvas)
    const half = width / 2, font = Math.max(9, Math.min(12, width / 36))
    const scale = Math.max(0.55, Math.min(1, width / 520))
    sky(g, width, look.dark)
    g.font = `${font}px system-ui, -apple-system, sans-serif`
    const longest = Math.max(1, ...map.reach.map(reach => Math.min(ARM, reach)))
    // (as big as fits, names too, however it is turned: a point this far out is drawn at most far / √(1 − (far/EYE)²)
    // from the middle, when it leans toward the eye by far/EYE)
    const out = Math.min(LABELS, longest + 0.15), seen = out / Math.sqrt(1 - (out / EYE) ** 2)
    const R = Math.max(10, (half - 6 - 5 * font) / seen)
    const colour = look.colours
    const depth = z => Math.max(0, Math.min(1, (z + ARM) / (2 * ARM))) // 0 at the back, 1 at the front
    const screen = at => {
      const far = Math.hypot(...at), cut = far > ARM ? ARM / far : 1
      const [x, y, z, near] = project(at.map(value => value * cut), turn)
      return [half + x * R, half + y * R, z, near]
    }
    // the sphere she was born with, seen from outside; then her arms, the far ones fainter
    g.strokeStyle = look.dark ? 'rgba(255, 255, 255, 0.16)' : 'rgba(0, 0, 0, 0.14)'
    g.setLineDash([3, 4])
    g.beginPath()
    g.arc(half, half, R * EYE / Math.sqrt(EYE * EYE - 1), 0, 2 * Math.PI)
    g.stroke()
    g.setLineDash([])
    const tips = map.directions.map((direction, k) => {
      const arm = Math.min(ARM, map.reach[k])
      const [x, y, z] = screen(direction.map(value => value * arm))
      g.strokeStyle = colour[k]
      g.globalAlpha = 0.15 + 0.4 * depth(z)
      g.beginPath()
      g.moveTo(half, half)
      g.lineTo(x, y)
      g.stroke()
      g.globalAlpha = 1
      return { k, x, y, z, label: screen(direction.map(value => value * Math.min(LABELS, arm + 0.15))) }
    })
    // the stars, from the back to the front
    const top = topOf(map)
    const placed = map.stars.map(star => [star, screen(star.slice(5, 8))]).sort((one, other) => one[1][2] - other[1][2])
    for (const [star, [px, py, z, near]] of placed) {
      const lean = Math.min(1, star[2] / top), size = (0.7 + 2.3 * lean) * scale * near, front = depth(z)
      g.fillStyle = colour[star[3]]
      if (look.dark && lean > 0.5) {
        g.globalCompositeOperation = 'lighter'
        g.globalAlpha = 0.12 * lean * (0.4 + 0.6 * front)
        g.beginPath()
        g.arc(px, py, size * 3.2, 0, 2 * Math.PI)
        g.fill()
        g.globalCompositeOperation = 'source-over'
      }
      g.globalAlpha = (0.25 + 0.75 * lean) * (0.35 + 0.65 * front)
      g.beginPath()
      g.arc(px, py, size, 0, 2 * Math.PI)
      g.fill()
    }
    g.globalAlpha = 1
    // the tips of her arms and the names of her ends, the front ones over the back
    g.textBaseline = 'middle'
    const places = placeNames(g, tips, look.names, half, font)
    for (const tip of [...tips].sort((one, other) => one.z - other.z)) {
      const front = depth(tip.z), place = places.get(tip.k)
      g.fillStyle = colour[tip.k]
      g.globalAlpha = 0.4 + 0.6 * front
      g.beginPath()
      g.arc(tip.x, tip.y, 2.2, 0, 2 * Math.PI)
      g.fill()
      if (!place) continue
      g.fillStyle = look.ink
      g.globalAlpha = 0.3 + 0.6 * front
      g.textAlign = place.align
      g.fillText(look.names[tip.k], place.x, place.y)
    }
    g.globalAlpha = 1
    // the people she knows, from the back to the front
    const people = map.people.map(person => {
      const [px, py, z, near] = screen(person.at)
      return { px, py, z, size: (4 + 8 * Math.min(1, person.weight / T.MOST)) * scale * near, person }
    }).sort((one, other) => one.z - other.z)
    for (const item of people) {
      g.globalAlpha = 0.55 + 0.45 * depth(item.z)
      personDot(g, item, look, colour, width, font)
      g.font = `${font}px system-ui, -apple-system, sans-serif`
    }
    g.globalAlpha = 1
  }


  /** Each end's colour: its bar's, the first end of a bar deeper and the second lighter. */
  function colours (bars, dark) {
    const shades = COLOURS[dark ? 'dark' : 'light'], found = []
    bars.forEach((bar, index) => {
      if (bar.ends[0]) found.push(shades.deep[index % shades.deep.length])
      found.push(shades.light[index % shades.light.length])
    })
    return found
  }

  window.GutMap = { drawFlat, drawRound, colours, COLOURS }
})()
