import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

/* ------------------------------------------------------------------ *
 *  The Moon's Pull — an interactive Earth–Moon tidal model.
 *
 *  The scene shows Earth with a translucent "ocean" shell that is
 *  deformed into two tidal bulges along the Earth→Moon axis, with a
 *  weaker contribution along the Earth→Sun axis. When the two align we
 *  get an exaggerated spring tide; when perpendicular, a muted neap.
 *  Distances and sizes are stylised, not to scale, so the effect reads.
 * ------------------------------------------------------------------ */

const canvas = document.getElementById("scene");
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const renderer = new THREE.WebGLRenderer({
  canvas,
  antialias: true,
  alpha: true,
});
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.setSize(window.innerWidth, window.innerHeight);

const scene = new THREE.Scene();

const camera = new THREE.PerspectiveCamera(
  45,
  window.innerWidth / window.innerHeight,
  0.1,
  1000
);
camera.position.set(0, 6, 18);

const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.06;
controls.minDistance = 9;
controls.maxDistance = 40;
controls.enablePan = false;

/* ---------- Lighting (the "Sun") ---------- */
const sunLight = new THREE.DirectionalLight(0xfff4e0, 2.4);
scene.add(sunLight);
scene.add(new THREE.AmbientLight(0x33406a, 0.6));

/* ---------- Starfield ---------- */
function makeStars(count) {
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(count * 3);
  for (let i = 0; i < count; i++) {
    const r = 120 + Math.random() * 260;
    const theta = Math.random() * Math.PI * 2;
    const phi = Math.acos(2 * Math.random() - 1);
    pos[i * 3] = r * Math.sin(phi) * Math.cos(theta);
    pos[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
    pos[i * 3 + 2] = r * Math.cos(phi);
  }
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  const mat = new THREE.PointsMaterial({ color: 0x9fb4ff, size: 0.7, sizeAttenuation: true, transparent: true, opacity: 0.85 });
  return new THREE.Points(geo, mat);
}
scene.add(makeStars(1800));

/* ---------- Earth (axial tilt 23.4°) ---------- */
const earthGroup = new THREE.Group();
earthGroup.rotation.z = THREE.MathUtils.degToRad(23.4);
scene.add(earthGroup);

const EARTH_R = 3;

const earthGeo = new THREE.SphereGeometry(EARTH_R, 64, 64);
const earthMat = new THREE.MeshStandardMaterial({
  color: 0x1d3b6e,
  roughness: 0.85,
  metalness: 0.05,
  emissive: 0x0a1733,
  emissiveIntensity: 0.4,
});
const earth = new THREE.Mesh(earthGeo, earthMat);
earthGroup.add(earth);

// Stylised continents as a few rotated blobs for visual grounding.
const landMat = new THREE.MeshStandardMaterial({ color: 0x2f7d4f, roughness: 1 });
const landSeeds = [
  [0.5, 0.8, 0.2], [-0.6, 0.3, 0.5], [0.1, -0.7, -0.4],
  [-0.4, -0.2, -0.8], [0.8, 0.0, -0.3],
];
landSeeds.forEach(([x, y, z], i) => {
  const dir = new THREE.Vector3(x, y, z).normalize();
  const blob = new THREE.Mesh(new THREE.SphereGeometry(0.7 + (i % 3) * 0.25, 20, 20), landMat);
  blob.position.copy(dir.multiplyScalar(EARTH_R - 0.05));
  blob.scale.set(1, 0.55, 1);
  blob.lookAt(0, 0, 0);
  earth.add(blob);
});

/* ---------- Ocean shell that deforms into tidal bulges ---------- */
const oceanGeo = new THREE.SphereGeometry(EARTH_R + 0.18, 96, 96);
oceanGeo.userData.base = oceanGeo.attributes.position.array.slice();
const oceanMat = new THREE.MeshStandardMaterial({
  color: 0x49b4ff,
  transparent: true,
  opacity: 0.4,
  roughness: 0.25,
  metalness: 0.1,
  emissive: 0x0d4a7a,
  emissiveIntensity: 0.5,
});
const ocean = new THREE.Mesh(oceanGeo, oceanMat);
earthGroup.add(ocean);

/* ---------- Moon ---------- */
const moonGroup = new THREE.Group(); // orbital frame around Earth
scene.add(moonGroup);
const MOON_DIST = 9;
const moonMat = new THREE.MeshStandardMaterial({ color: 0xcfcfd6, roughness: 1 });
const moon = new THREE.Mesh(new THREE.SphereGeometry(0.85, 32, 32), moonMat);
moon.position.set(MOON_DIST, 0, 0);
// a couple of craters for character
const craterMat = new THREE.MeshStandardMaterial({ color: 0x9a9aa6, roughness: 1 });
[[0.4, 0.3, 0.6], [-0.5, 0.2, 0.5], [0.1, -0.6, 0.5]].forEach(([x, y, z], i) => {
  const c = new THREE.Mesh(new THREE.SphereGeometry(0.12 + i * 0.04, 12, 12), craterMat);
  c.position.set(x, y, z).normalize().multiplyScalar(0.85);
  moon.add(c);
});
moonGroup.add(moon);

/* ---------- Moon orbit ring ---------- */
const orbitRing = new THREE.Mesh(
  new THREE.RingGeometry(MOON_DIST - 0.02, MOON_DIST + 0.02, 128),
  new THREE.MeshBasicMaterial({ color: 0x7db2ff, side: THREE.DoubleSide, transparent: true, opacity: 0.25 })
);
orbitRing.rotation.x = -Math.PI / 2;
scene.add(orbitRing);

/* ---------- State + UI wiring ---------- */
const state = {
  speed: 1,
  sunPhase: 0,
  showTides: true,
  showOrbit: true,
  moonAngle: 0,
};

const speedEl = document.getElementById("speed");
const sunEl = document.getElementById("sunPhase");
const tideBtn = document.getElementById("toggleTides");
const orbitBtn = document.getElementById("toggleOrbit");
const readout = document.getElementById("readout");

speedEl.addEventListener("input", (e) => (state.speed = parseFloat(e.target.value)));
sunEl.addEventListener("input", (e) => (state.sunPhase = parseFloat(e.target.value)));
tideBtn.addEventListener("click", () => {
  state.showTides = !state.showTides;
  tideBtn.classList.toggle("is-active", state.showTides);
});
orbitBtn.addEventListener("click", () => {
  state.showOrbit = !state.showOrbit;
  orbitBtn.classList.toggle("is-active", state.showOrbit);
  orbitRing.visible = state.showOrbit;
});

/* ---------- Tidal deformation ---------- *
 * For each ocean vertex we add a bulge proportional to cos²(angle) to
 * the Moon axis (two bulges, near + far), plus a weaker Sun term. The
 * relative alignment of the two axes produces the spring/neap range. */
const MOON_AMP = 0.55;
const SUN_AMP = 0.25; // ~46% of lunar, exaggerated for visibility

const basePos = oceanGeo.userData.base;
const oceanPos = oceanGeo.attributes.position;
const v = new THREE.Vector3();
const moonAxis = new THREE.Vector3();
const sunAxis = new THREE.Vector3();

function deformOcean() {
  const baseR = EARTH_R + 0.18;

  // Axes expressed in earthGroup's local space (ocean is a child of it).
  moon.getWorldPosition(moonAxis);
  earthGroup.worldToLocal(moonAxis).normalize();

  sunLight.getWorldPosition(sunAxis);
  earthGroup.worldToLocal(sunAxis).normalize();

  const amp = state.showTides ? 1 : 0;

  for (let i = 0; i < oceanPos.count; i++) {
    v.set(basePos[i * 3], basePos[i * 3 + 1], basePos[i * 3 + 2]).normalize();
    const m = v.dot(moonAxis);
    const s = v.dot(sunAxis);
    const bulge = (MOON_AMP * m * m + SUN_AMP * s * s) * amp;
    const r = baseR + bulge;
    oceanPos.setXYZ(i, v.x * r, v.y * r, v.z * r);
  }
  oceanPos.needsUpdate = true;
  oceanGeo.computeVertexNormals();
}

function updateReadout() {
  // Angle between Moon direction and Sun direction in the orbital plane.
  const moonDir = Math.atan2(moon.position.z, moon.position.x); // in moonGroup frame
  const worldMoon = state.moonAngle; // moonGroup.rotation.y
  const lunar = worldMoon + moonDir;
  const diff = Math.abs(((lunar - state.sunPhase + Math.PI) % (Math.PI * 2)) - Math.PI);
  const aligned = Math.min(diff, Math.PI - diff); // 0 = aligned/opposite, ~PI/2 = perpendicular
  if (aligned < 0.5) {
    readout.innerHTML = "Configuration: <strong>Spring tide</strong> — Sun and Moon aligned, maximal pull.";
  } else if (aligned > Math.PI / 2 - 0.5) {
    readout.innerHTML = "Configuration: <strong>Neap tide</strong> — Sun and Moon at right angles, pulls partly cancel.";
  } else {
    readout.innerHTML = "Configuration: <strong>Mid cycle</strong> — tidal range between spring and neap.";
  }
}

/* ---------- Animate ---------- */
const clock = new THREE.Clock();

function animate() {
  const dt = clock.getDelta();
  const step = reducedMotion ? 0 : dt * state.speed;

  // Moon orbits Earth.
  state.moonAngle += step * 0.25;
  moonGroup.rotation.y = state.moonAngle;

  // Earth spins faster than the Moon orbits.
  earth.rotation.y += step * 1.2;

  // Sun direction set by slider (the whole system bathed from this angle).
  const sunR = 60;
  sunLight.position.set(
    Math.cos(state.sunPhase) * sunR,
    8,
    Math.sin(state.sunPhase) * sunR
  );

  deformOcean();
  updateReadout();

  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}
animate();

/* ---------- Resize ---------- */
window.addEventListener("resize", () => {
  camera.aspect = window.innerWidth / window.innerHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(window.innerWidth, window.innerHeight);
});

/* ---------- Scroll reveal for panels ---------- */
const io = new IntersectionObserver(
  (entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) e.target.classList.add("is-visible");
    });
  },
  { threshold: 0.25 }
);
document.querySelectorAll(".panel").forEach((p) => io.observe(p));
