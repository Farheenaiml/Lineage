import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { geoEquirectangular, geoPath, geoGraticule10 } from "d3-geo";
import { feature, mesh } from "topojson-client";
import worldData from "world-atlas/countries-110m.json";
import type { GeoNode, GeoEdge } from "../../lib/api";

/**
 * Imperative Three.js engine for the LINEAGE propagation globe.
 *
 * Basemap: Natural Earth (public domain, via world-atlas) rendered locally to a canvas
 * texture — no tile server, no API key, works offline. Nothing on the globe is invented:
 * every node/arc is created from a record passed to setData().
 */

export const TIER_COLOR: Record<string, string> = {
  verified: "#4fe3a1",
  investigator: "#f6b94d",
  inferred: "#9aa7b8",
  mixed: "#8db4ff",
};
export const HEAT_COLOR: Record<string, string> = { low: "#2dd4bf", medium: "#fbbf24", high: "#f0523f" };
export type HeatPt = { id: string; latitude: number; longitude: number; weight: number; level: "low" | "medium" | "high" };
export type Layers = { heat: boolean; nodes: boolean; arcs: boolean };
const HEAT_W = 2048, HEAT_H = 1024;
const hexRgba = (hex: string, a: number) => {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${a})`;
};
/** Angular radius (degrees) a heat blob of this weight covers — shared by paint + region picking. */
const heatRadiusPx = (w: number) => 30 + 70 * Math.sqrt(w);

export const EDGE_COLOR: Record<string, string> = {
  confirmed: "#39d5ff",
  inferred: "#ffb454",
  undirected: "#8fa3b5",
};

const R = 1;
export function latLonToVec3(lat: number, lon: number, r = R): THREE.Vector3 {
  const φ = (lat * Math.PI) / 180, λ = (lon * Math.PI) / 180;
  return new THREE.Vector3(r * Math.cos(φ) * Math.cos(λ), r * Math.sin(φ), -r * Math.cos(φ) * Math.sin(λ));
}

function makeEarthTexture(): THREE.CanvasTexture {
  const W = 4096, H = 2048;
  const c = document.createElement("canvas");
  c.width = W; c.height = H;
  const ctx = c.getContext("2d")!;
  const g = ctx.createLinearGradient(0, 0, 0, H);
  g.addColorStop(0, "#0b1a24"); g.addColorStop(0.5, "#0c2230"); g.addColorStop(1, "#0b1a24");
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

  const proj = geoEquirectangular().scale(W / (2 * Math.PI)).translate([W / 2, H / 2]);
  const path = geoPath(proj, ctx);
  const w: any = worldData;

  ctx.beginPath(); path(geoGraticule10()); ctx.strokeStyle = "rgba(120,190,220,0.10)"; ctx.lineWidth = 1.2; ctx.stroke();

  const countries = feature(w, w.objects.countries) as any;
  ctx.beginPath(); path(countries);
  const lg = ctx.createLinearGradient(0, 0, 0, H);
  lg.addColorStop(0, "#1d3a33"); lg.addColorStop(0.5, "#24473d"); lg.addColorStop(1, "#1d3a33");
  ctx.fillStyle = lg; ctx.fill();

  ctx.beginPath(); path(mesh(w, w.objects.countries, (a: any, b: any) => a !== b));
  ctx.strokeStyle = "rgba(140,220,190,0.28)"; ctx.lineWidth = 1.4; ctx.stroke();
  ctx.beginPath(); path(mesh(w, w.objects.countries, (a: any, b: any) => a === b));
  ctx.strokeStyle = "rgba(160,235,210,0.55)"; ctx.lineWidth = 1.8; ctx.stroke();

  const t = new THREE.CanvasTexture(c);
  t.anisotropy = 8; t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

const EDGE_VERT = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0); }`;
const EDGE_FRAG = `
uniform vec3 uColor; uniform float uTime; uniform float uDash; uniform float uFlow; uniform float uAlpha; varying vec2 vUv;
void main(){
  float u = vUv.x;
  float base = 0.38;
  float pulse = 0.0;
  if (uFlow > 0.5) { float f = fract(u * 4.0 - uTime * 0.55); pulse = pow(1.0 - f, 3.0) * 1.15; }
  float a = base + pulse;
  if (uDash > 0.5) { float d = step(0.5, fract(u * 34.0)); a *= mix(0.12, 1.0, d); }
  float fade = smoothstep(0.0, 0.05, u) * smoothstep(1.0, 0.95, u);
  gl_FragColor = vec4(uColor * (0.85 + pulse), a * uAlpha * fade);
}`;

type Picked = { kind: "node" | "edge"; id: string } | null;

export class GlobeEngine {
  private renderer: THREE.WebGLRenderer;
  private scene = new THREE.Scene();
  private camera: THREE.PerspectiveCamera;
  private controls: OrbitControls;
  private root = new THREE.Group();
  private dataGroup = new THREE.Group();
  private nodeGroup = new THREE.Group();
  private edgeGroup = new THREE.Group();
  private heatMesh!: THREE.Mesh;
  private heatCanvas = document.createElement("canvas");
  private heatTex!: THREE.CanvasTexture;
  private heatPts: HeatPt[] = [];
  private layers: Layers = { heat: false, nodes: true, arcs: true };
  private marker!: THREE.Mesh;
  private raycaster = new THREE.Raycaster();
  private ray = new THREE.Vector2();
  private clock = new THREE.Clock();
  private raf = 0;
  private disposed = false;
  private labelLayer: HTMLDivElement;

  private nodeObjs = new Map<string, { node: GeoNode; group: THREE.Group; core: THREE.Mesh; hit: THREE.Mesh; ring: THREE.Mesh; label: HTMLDivElement; normal: THREE.Vector3; base: number }>();
  private edgeObjs = new Map<string, { edge: GeoEdge; mesh: THREE.Mesh; hit: THREE.Mesh; mat: THREE.ShaderMaterial; arrows: THREE.Mesh[]; curve: THREE.QuadraticBezierCurve3; particles: THREE.Mesh[]; mode: string }>();

  private selected: Picked = null;
  private hovered: Picked = null;
  private flyTo: { pos: THREE.Vector3; t: number } | null = null;
  private homePos = new THREE.Vector3(0.9, 0.7, 2.9);
  private downAt = { x: 0, y: 0, t: 0 };
  private resizeObs: ResizeObserver;

  onSelect: (p: Picked) => void = () => {};
  onHover: (p: Picked) => void = () => {};

  constructor(private container: HTMLElement) {
    const w = container.clientWidth || 800, h = container.clientHeight || 520;
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.setSize(w, h);
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.appendChild(this.renderer.domElement);
    this.renderer.domElement.style.touchAction = "none";

    this.labelLayer = document.createElement("div");
    Object.assign(this.labelLayer.style, { position: "absolute", inset: "0", pointerEvents: "none", overflow: "hidden" });
    container.appendChild(this.labelLayer);

    this.camera = new THREE.PerspectiveCamera(42, w / h, 0.05, 100);
    this.camera.position.copy(this.homePos);

    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    Object.assign(this.controls, { enableDamping: true, dampingFactor: 0.08, minDistance: 1.3, maxDistance: 6, enablePan: true, autoRotate: true, autoRotateSpeed: 0.35, rotateSpeed: 0.6, zoomSpeed: 0.8, panSpeed: 0.6 });
    this.controls.addEventListener("start", () => { this.controls.autoRotate = false; this.flyTo = null; });

    this.buildStatic();
    this.scene.add(this.root);
    this.root.add(this.dataGroup);
    this.dataGroup.add(this.nodeGroup, this.edgeGroup);
    this.buildHeat();
    this.marker = new THREE.Mesh(new THREE.RingGeometry(0.034, 0.041, 56), new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.9, side: THREE.DoubleSide, depthWrite: false }));
    this.marker.visible = false;
    this.root.add(this.marker);

    const el = this.renderer.domElement;
    el.addEventListener("pointerdown", this.onDown);
    el.addEventListener("pointerup", this.onUp);
    el.addEventListener("pointermove", this.onMove);
    this.resizeObs = new ResizeObserver(() => this.resize());
    this.resizeObs.observe(container);
    this.loop();
  }

  private buildStatic() {
    // starfield
    const n = 1400, pos = new Float32Array(n * 3);
    for (let i = 0; i < n; i++) {
      const v = new THREE.Vector3().randomDirection().multiplyScalar(20 + Math.random() * 20);
      pos.set([v.x, v.y, v.z], i * 3);
    }
    const sg = new THREE.BufferGeometry(); sg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
    this.scene.add(new THREE.Points(sg, new THREE.PointsMaterial({ color: 0x9fc8d8, size: 0.06, transparent: true, opacity: 0.6, sizeAttenuation: true })));

    // earth
    const earth = new THREE.Mesh(
      new THREE.SphereGeometry(R, 96, 96),
      new THREE.MeshStandardMaterial({ map: makeEarthTexture(), roughness: 0.85, metalness: 0.05, emissive: new THREE.Color("#0a2a2c"), emissiveIntensity: 0.55 })
    );
    this.root.add(earth);

    // atmosphere (fresnel)
    const atm = new THREE.Mesh(
      new THREE.SphereGeometry(R * 1.14, 64, 64),
      new THREE.ShaderMaterial({
        transparent: true, side: THREE.BackSide, blending: THREE.AdditiveBlending, depthWrite: false,
        vertexShader: `varying vec3 vN; void main(){ vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position,1.0);} `,
        fragmentShader: `varying vec3 vN; void main(){ float i = pow(0.72 - dot(vN, vec3(0.,0.,1.)), 3.0); gl_FragColor = vec4(0.25,0.85,0.8,1.0) * i * 1.3; }`,
      })
    );
    this.scene.add(atm);
    const rim = new THREE.Mesh(new THREE.SphereGeometry(R * 1.008, 64, 64), new THREE.MeshBasicMaterial({ color: 0x5fe0c8, transparent: true, opacity: 0.05, side: THREE.FrontSide }));
    this.root.add(rim);

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.9));
    const sun = new THREE.DirectionalLight(0xbfefff, 1.4); sun.position.set(4, 2, 5); this.scene.add(sun);
  }

  /* ------------------------------ heat layer ------------------------------ */
  private buildHeat() {
    this.heatCanvas.width = HEAT_W; this.heatCanvas.height = HEAT_H;
    this.heatTex = new THREE.CanvasTexture(this.heatCanvas);
    this.heatTex.colorSpace = THREE.SRGBColorSpace;
    this.heatMesh = new THREE.Mesh(
      new THREE.SphereGeometry(R * 1.005, 96, 96),
      new THREE.MeshBasicMaterial({ map: this.heatTex, transparent: true, depthWrite: false, opacity: 0.96 })
    );
    this.heatMesh.visible = false;
    this.root.add(this.heatMesh);
  }

  /** Smooth heat field painted from AGGREGATED points only (one gradient per location, not per observation). */
  setHeat(points: HeatPt[]) {
    this.heatPts = points;
    const ctx = this.heatCanvas.getContext("2d")!;
    ctx.globalCompositeOperation = "source-over";
    ctx.clearRect(0, 0, HEAT_W, HEAT_H);
    ctx.globalCompositeOperation = "lighter";
    for (const p of points) {
      const cx = ((p.longitude + 180) / 360) * HEAT_W, cy = ((90 - p.latitude) / 180) * HEAT_H;
      const r = heatRadiusPx(p.weight);
      const sx = 1 / Math.max(Math.cos((p.latitude * Math.PI) / 180), 0.3);   // undo equirect stretch toward poles
      const a = 0.3 + 0.6 * p.weight, col = HEAT_COLOR[p.level] ?? HEAT_COLOR.low;
      for (const dx of [-HEAT_W, 0, HEAT_W]) {
        if ((dx < 0 && cx - r * sx > 0) || (dx > 0 && cx + r * sx < HEAT_W)) continue;   // wrap only near the date line
        ctx.save(); ctx.translate(cx + dx, cy); ctx.scale(sx, 1);
        const g = ctx.createRadialGradient(0, 0, 0, 0, 0, r);
        g.addColorStop(0, hexRgba(col, a)); g.addColorStop(0.4, hexRgba(col, a * 0.55)); g.addColorStop(1, hexRgba(col, 0));
        ctx.fillStyle = g; ctx.beginPath(); ctx.arc(0, 0, r, 0, Math.PI * 2); ctx.fill(); ctx.restore();
      }
    }
    this.heatTex.needsUpdate = true;
  }

  /** Visibility only — nothing is rebuilt when a layer is toggled. */
  setLayers(l: Layers) {
    this.layers = l;
    this.heatMesh.visible = l.heat;
    this.nodeGroup.visible = l.nodes;
    this.edgeGroup.visible = l.arcs;
    this.labelLayer.style.display = l.nodes ? "block" : "none";
    this.updateMarker();
  }

  /** Click on a heat area (no node/arc hit): resolve to the nearest recorded location whose blob covers the point. */
  private pickHeat(): Picked {
    if (!this.layers.heat || !this.heatPts.length) return null;
    const earth = this.root.children[0];
    const hit = this.raycaster.intersectObject(earth, false)[0];
    if (!hit) return null;
    const p = this.root.worldToLocal(hit.point.clone()).normalize();
    const lat = (Math.asin(THREE.MathUtils.clamp(p.y, -1, 1)) * 180) / Math.PI;
    const lon = (Math.atan2(-p.z, p.x) * 180) / Math.PI;
    let best: { id: string; d: number } | null = null;
    for (const h of this.heatPts) {
      const φ1 = (lat * Math.PI) / 180, φ2 = (h.latitude * Math.PI) / 180, dλ = (((lon - h.longitude) * Math.PI) / 180);
      const d = (Math.acos(THREE.MathUtils.clamp(Math.sin(φ1) * Math.sin(φ2) + Math.cos(φ1) * Math.cos(φ2) * Math.cos(dλ), -1, 1)) * 180) / Math.PI;
      const reach = heatRadiusPx(h.weight) * (180 / HEAT_H) * 0.85;
      if (d <= reach && (!best || d < best.d)) best = { id: h.id, d };
    }
    return best ? { kind: "node", id: best.id } : null;
  }

  /* ------------------------------ data ------------------------------ */
  setData(nodes: GeoNode[], edges: GeoEdge[], opts: { showEdges: boolean }) {
    // clear
    this.dataGroup.traverse((o: any) => { o.geometry?.dispose?.(); if (o.material && !Array.isArray(o.material)) o.material.dispose?.(); });
    this.nodeGroup.clear(); this.edgeGroup.clear();
    this.labelLayer.innerHTML = "";
    this.nodeObjs.clear(); this.edgeObjs.clear();

    const maxObs = Math.max(1, ...nodes.map((n) => n.observation_count));
    const nodeTop = new Map<string, THREE.Vector3>();

    for (const n of nodes) {
      const normal = latLonToVec3(n.latitude, n.longitude, 1).normalize();
      const size = 0.016 + 0.014 * Math.sqrt(n.observation_count) + (n.observation_count / maxObs) * 0.006;
      const beamH = 0.05 + 0.05 * Math.log2(n.observation_count + 1);
      const color = new THREE.Color(TIER_COLOR[n.tier] ?? TIER_COLOR.inferred);
      const g = new THREE.Group();
      g.position.copy(normal.clone().multiplyScalar(R));
      g.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), normal);

      const beam = new THREE.Mesh(new THREE.CylinderGeometry(0.0035, 0.0035, beamH, 8), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.55 }));
      beam.position.y = beamH / 2; g.add(beam);
      const core = new THREE.Mesh(new THREE.SphereGeometry(size, 24, 24), new THREE.MeshBasicMaterial({ color }));
      core.position.y = beamH; g.add(core);
      const halo = new THREE.Mesh(new THREE.SphereGeometry(size * 1.9, 20, 20), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.16, depthWrite: false }));
      halo.position.y = beamH; g.add(halo);
      const ring = new THREE.Mesh(new THREE.RingGeometry(size * 1.6, size * 1.9, 48), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.7, side: THREE.DoubleSide, depthWrite: false }));
      ring.rotation.x = -Math.PI / 2; ring.position.y = 0.002; g.add(ring);
      const hit = new THREE.Mesh(new THREE.SphereGeometry(Math.max(size * 2.6, 0.045), 12, 12), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
      hit.position.y = beamH; hit.userData = { kind: "node", id: n.id }; g.add(hit);
      this.nodeGroup.add(g);

      const label = document.createElement("div");
      label.innerHTML = `<b>${escapeHtml(n.name)}</b><span>${n.observation_count} obs</span>`;
      label.className = "geo-label";
      this.labelLayer.appendChild(label);

      nodeTop.set(n.id, normal.clone().multiplyScalar(R + beamH));
      this.nodeObjs.set(n.id, { node: n, group: g, core, hit, ring, label, normal, base: size });
    }

    if (opts.showEdges) {
      const maxCount = Math.max(1, ...edges.map((e) => e.count));
      for (const e of edges) {
        const a = nodeTop.get(e.source), b = nodeTop.get(e.target);
        if (!a || !b) continue;
        const ang = a.angleTo(b);
        const mid = a.clone().add(b).multiplyScalar(0.5).normalize().multiplyScalar(R + 0.12 + ang * 0.42);
        const curve = new THREE.QuadraticBezierCurve3(a, mid, b);
        const radius = 0.0045 + 0.0045 * Math.sqrt(e.count) + (e.count / maxCount) * 0.002;
        const color = new THREE.Color(EDGE_COLOR[e.mode]);
        const mat = new THREE.ShaderMaterial({
          transparent: true, depthWrite: false, side: THREE.DoubleSide, blending: THREE.AdditiveBlending,
          uniforms: { uColor: { value: color }, uTime: { value: 0 }, uDash: { value: e.mode === "confirmed" ? 0 : 1 }, uFlow: { value: e.mode === "undirected" ? 0 : 1 }, uAlpha: { value: 1 } },
          vertexShader: EDGE_VERT, fragmentShader: EDGE_FRAG,
        });
        const mesh = new THREE.Mesh(new THREE.TubeGeometry(curve, 96, radius, 8, false), mat);
        this.edgeGroup.add(mesh);
        const hit = new THREE.Mesh(new THREE.TubeGeometry(curve, 48, Math.max(radius * 3.2, 0.014), 6, false), new THREE.MeshBasicMaterial({ transparent: true, opacity: 0, depthWrite: false }));
        hit.userData = { kind: "edge", id: e.id };
        this.edgeGroup.add(hit);

        const arrows: THREE.Mesh[] = [], particles: THREE.Mesh[] = [];
        if (e.mode !== "undirected") {
          // arrowheads: one near the destination + one at the midpoint so direction reads at any zoom
          for (const t of [0.5, 0.93]) {
            const p = curve.getPoint(t), tan = curve.getTangent(t).normalize();
            const cone = new THREE.Mesh(new THREE.ConeGeometry(radius * 3.2 + 0.006, 0.05, 14), new THREE.MeshBasicMaterial({ color, transparent: t === 0.5, opacity: t === 0.5 ? 0.85 : 1 }));
            cone.position.copy(p); cone.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), tan);
            this.edgeGroup.add(cone); arrows.push(cone);
          }
          for (let i = 0; i < 3; i++) {
            const dot = new THREE.Mesh(new THREE.SphereGeometry(radius * 1.9 + 0.003, 10, 10), new THREE.MeshBasicMaterial({ color: 0xffffff }));
            dot.userData.phase = i / 3; this.edgeGroup.add(dot); particles.push(dot);
          }
        }
        this.edgeObjs.set(e.id, { edge: e, mesh, hit, mat, arrows, curve, particles, mode: e.mode });
      }
    }
    this.applySelection();
  }

  /* --------------------------- interaction --------------------------- */
  private onDown = (ev: PointerEvent) => { this.downAt = { x: ev.clientX, y: ev.clientY, t: performance.now() }; };
  private onUp = (ev: PointerEvent) => {
    const moved = Math.hypot(ev.clientX - this.downAt.x, ev.clientY - this.downAt.y);
    if (moved > 5 || performance.now() - this.downAt.t > 600) return;
    const p = this.pick(ev);
    this.select(p);
    this.onSelect(p);
  };
  private onMove = (ev: PointerEvent) => {
    const p = this.pick(ev);
    const changed = (p?.id ?? null) !== (this.hovered?.id ?? null);
    this.hovered = p;
    this.renderer.domElement.style.cursor = p ? "pointer" : "grab";
    if (changed) this.onHover(p);
  };

  private pick(ev: PointerEvent): Picked {
    const r = this.renderer.domElement.getBoundingClientRect();
    this.ray.set(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
    this.raycaster.setFromCamera(this.ray, this.camera);
    const hits: THREE.Object3D[] = [];
    if (this.layers.nodes) this.nodeObjs.forEach((o) => hits.push(o.hit));
    if (this.layers.arcs) this.edgeObjs.forEach((o) => hits.push(o.hit));
    // occlude by the globe itself
    const earthHit = this.raycaster.intersectObject(this.root.children[0], false)[0];
    const res = this.raycaster.intersectObjects(hits, false).filter((h) => !earthHit || h.distance < earthHit.distance + 0.02);
    const first = res[0]?.object.userData as any;
    return first?.id ? { kind: first.kind, id: first.id } : this.pickHeat();
  }

  select(p: Picked) { this.selected = p; this.applySelection(); }
  focus(nodeId: string) {
    const o = this.nodeObjs.get(nodeId);
    if (!o) return;
    this.controls.autoRotate = false;
    this.flyTo = { pos: o.normal.clone().multiplyScalar(2.3), t: 0 };
  }
  private updateMarker() {
    const o = this.selected?.kind === "node" ? this.nodeObjs.get(this.selected.id) : null;
    this.marker.visible = !!o && (!this.layers.nodes || this.layers.heat);
    if (o) {
      this.marker.position.copy(o.normal.clone().multiplyScalar(R * 1.012));
      this.marker.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), o.normal);
    }
  }
  private applySelection() {
    this.updateMarker();
    this.nodeObjs.forEach((o, id) => {
      const sel = this.selected?.kind === "node" && this.selected.id === id;
      o.group.scale.setScalar(sel ? 1.35 : 1);
      o.label.classList.toggle("sel", sel);
    });
    this.edgeObjs.forEach((o, id) => {
      const sel = this.selected?.kind === "edge" && this.selected.id === id;
      o.mat.uniforms.uAlpha.value = this.selected?.kind === "edge" && !sel ? 0.35 : sel ? 1.8 : 1;
    });
  }

  /* ----------------------------- controls ----------------------------- */
  zoom(f: number) {
    const d = this.camera.position.distanceTo(this.controls.target);
    const nd = THREE.MathUtils.clamp(d * f, this.controls.minDistance, this.controls.maxDistance);
    this.camera.position.sub(this.controls.target).setLength(nd).add(this.controls.target);
  }
  rotate(dx: number, dy: number) {
    const off = this.camera.position.clone().sub(this.controls.target);
    const s = new THREE.Spherical().setFromVector3(off);
    s.theta += dx; s.phi = THREE.MathUtils.clamp(s.phi + dy, 0.15, Math.PI - 0.15);
    this.camera.position.copy(new THREE.Vector3().setFromSpherical(s).add(this.controls.target));
  }
  setAutoRotate(v: boolean) { this.controls.autoRotate = v; }
  get autoRotating() { return this.controls.autoRotate; }
  reset() {
    this.controls.target.set(0, 0, 0);
    this.flyTo = { pos: this.homePos.clone(), t: 0 };
  }

  /* ------------------------------ render ------------------------------ */
  private resize() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    if (!w || !h) return;
    this.renderer.setSize(w, h); this.camera.aspect = w / h; this.camera.updateProjectionMatrix();
  }

  private loop = () => {
    if (this.disposed) return;
    this.raf = requestAnimationFrame(this.loop);
    const t = this.clock.getElapsedTime(), dt = Math.min(this.clock.getDelta(), 0.05);
    if (this.flyTo) {
      this.flyTo.t = Math.min(1, this.flyTo.t + 0.035);
      const k = 1 - Math.pow(1 - this.flyTo.t, 3);
      const cur = this.camera.position.clone().sub(this.controls.target);
      const dir = cur.clone().normalize().lerp(this.flyTo.pos.clone().normalize(), k * 0.25 + 0.02).normalize();
      const len = THREE.MathUtils.lerp(cur.length(), this.flyTo.pos.length(), 0.08);
      this.camera.position.copy(this.controls.target.clone().add(dir.multiplyScalar(len)));
      if (this.flyTo.t >= 1 && cur.distanceTo(this.flyTo.pos) < 0.02) this.flyTo = null;
    }
    this.controls.update();

    this.nodeObjs.forEach((o, id) => {
      const pulse = (t * 0.6 + o.base * 10) % 1;
      o.ring.scale.setScalar(1 + pulse * 2.2);
      (o.ring.material as THREE.MeshBasicMaterial).opacity = 0.7 * (1 - pulse);
      const hov = this.hovered?.kind === "node" && this.hovered.id === id;
      o.core.scale.setScalar(hov ? 1.3 : 1);
    });
    this.edgeObjs.forEach((o) => {
      o.mat.uniforms.uTime.value = t;
      o.particles.forEach((p) => {
        const u = (t * 0.22 + (p.userData.phase as number)) % 1;
        p.position.copy(o.curve.getPoint(u));
      });
    });
    if (this.marker.visible) this.marker.scale.setScalar(1 + 0.18 * Math.sin(t * 3));
    this.updateLabels();
    this.renderer.render(this.scene, this.camera);
  };

  private updateLabels() {
    const w = this.container.clientWidth, h = this.container.clientHeight;
    const camDir = this.camera.position.clone().normalize();
    const v = new THREE.Vector3();
    this.nodeObjs.forEach((o) => {
      o.core.getWorldPosition(v);
      const facing = o.normal.clone().applyMatrix4(this.root.matrixWorld).normalize().dot(camDir);
      v.project(this.camera);
      const visible = facing > 0.12 && v.z < 1;
      o.label.style.opacity = visible ? "1" : "0";
      o.label.style.transform = `translate(${(v.x * 0.5 + 0.5) * w}px, ${(-v.y * 0.5 + 0.5) * h}px) translate(-50%, -150%)`;
    });
  }

  dispose() {
    this.disposed = true; cancelAnimationFrame(this.raf); this.resizeObs.disconnect();
    const el = this.renderer.domElement;
    el.removeEventListener("pointerdown", this.onDown); el.removeEventListener("pointerup", this.onUp); el.removeEventListener("pointermove", this.onMove);
    this.controls.dispose();
    this.scene.traverse((o: any) => { o.geometry?.dispose?.(); const m = o.material; if (m) (Array.isArray(m) ? m : [m]).forEach((x: any) => { x.map?.dispose?.(); x.dispose?.(); }); });
    this.renderer.dispose(); el.remove(); this.labelLayer.remove();
  }
}

function escapeHtml(s: string) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]!));
}
