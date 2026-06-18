# The Moon's Pull — Gravitational Effects on Earth

An interactive, single-page science explainer covering how the Moon's gravity
affects Earth: ocean tides, spring/neap cycles, the lengthening day from tidal
friction, the Moon's slow recession, tidal locking, and axial stabilisation.

## Stack

- **Three.js** (loaded from a CDN via import map) for a live, orbit-able
  Earth–Moon model with deforming tidal bulges and a movable Sun.
- Vanilla **CSS** (glassmorphism, scroll-reveal) and **JavaScript** — no build
  step, no bundler.

## Run it

It's fully static. Because it uses ES modules + an import map, open it through a
local server rather than `file://`:

```bash
cd moon-gravity
python3 -m http.server 8000
# then visit http://localhost:8000
```

## Controls

- **Drag** the scene to orbit the camera, **scroll** to zoom.
- **Time speed** slider — speeds up / pauses the orbit and Earth's spin.
- **Sun alignment** slider — rotates the Sun; align it with the Moon for a
  spring tide, set it perpendicular for a neap tide (watch the readout).
- **Tidal bulge** / **Orbit path** toggles.

## Note on accuracy

Sizes and distances are stylised so the tidal bulge is visible; the physics of
*why* the effects happen is faithful, and the quoted figures (3.8 cm/yr
recession, +1.7 ms/century, 23.4° tilt, etc.) are standard astronomical
estimates rounded for clarity.
