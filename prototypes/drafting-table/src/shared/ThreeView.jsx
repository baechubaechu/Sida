// A live view of the site and one massing scheme: '3d' (drag to orbit) or '2d' (plan from above,
// north up; drag to pan). Wheel zooms in both.
// Pointer events stop here so the board does not pan while the model turns.
import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { SITE, SITE_ANGLE, MASS_ORIGIN, FLOOR_HEIGHT } from './geometry.js';

const plan2d = (mode, scheme) => (mode === '2d'
  ? `${scheme.name} 배치 평면. 끌어서 옮기고 휠로 확대합니다.`
  : `${scheme.name} 3D 모델. 끌어서 돌리고 휠로 확대합니다.`);

function css(name, fallback) {
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

export function ThreeView({ scheme, height = 260, mode = '3d', overlays = [] }) {
  const overlayKey = overlays.map((t) => `${t.id}:${t.strokes.length}`).join('|');
  const host = useRef(null);
  useEffect(() => {
    const el = host.current;
    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    el.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const plan = mode === '2d';
    const PLAN_SPAN = 150; // metres shown across the shorter side at the start
    const camera = plan
      ? new THREE.OrthographicCamera(-PLAN_SPAN / 2, PLAN_SPAN / 2, PLAN_SPAN / 2, -PLAN_SPAN / 2, 1, 2000)
      : new THREE.PerspectiveCamera(35, 1, 1, 2000);
    camera.up.set(0, plan ? 1 : 0, plan ? 0 : 1);
    if (plan) camera.position.set(-6, 8, 500);
    else camera.position.set(-95, -150, 125);
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.target.set(plan ? -6 : -4, plan ? 8 : 6, plan ? 0 : 8);
    if (plan) {
      controls.enableRotate = false;
      controls.screenSpacePanning = true;
      controls.mouseButtons = { LEFT: THREE.MOUSE.PAN, MIDDLE: THREE.MOUSE.DOLLY, RIGHT: THREE.MOUSE.PAN };
      controls.touches = { ONE: THREE.TOUCH.PAN, TWO: THREE.TOUCH.DOLLY_PAN };
    }

    scene.add(new THREE.HemisphereLight(0xffffff, 0x8a8f99, 1.6));
    const sun = new THREE.DirectionalLight(0xffffff, 1.4);
    sun.position.set(-60, -40, 120);
    scene.add(sun);

    const ink = new THREE.Color(css('--ink', '#1f2a33'));
    const mass = new THREE.Color(css('--mass', '#e9e4d8'));
    const lot = new THREE.Color(css('--lot', '#c96f3b'));
    const ground = new THREE.Mesh(new THREE.CircleGeometry(plan ? 600 : 160, 64), new THREE.MeshLambertMaterial({ color: css('--ground', '#dfe3e1') }));
    ground.position.z = -0.05;
    scene.add(ground);
    const grid = new THREE.GridHelper(320, 32, ink, ink);
    grid.rotation.x = Math.PI / 2;
    grid.material.opacity = 0.08;
    grid.material.transparent = true;
    scene.add(grid);

    // Parcels: a thin slab and a bold boundary line each.
    for (const p of SITE) {
      const shape = new THREE.Shape(p.local.map(([x, y]) => new THREE.Vector2(x, y)));
      const slab = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshLambertMaterial({ color: lot, transparent: true, opacity: 0.18 }));
      slab.position.z = 0.02;
      scene.add(slab);
      const line = new THREE.LineLoop(
        new THREE.BufferGeometry().setFromPoints(p.local.map(([x, y]) => new THREE.Vector3(x, y, 0.1))),
        new THREE.LineBasicMaterial({ color: lot }),
      );
      scene.add(line);
    }

    // Masses: boxes along the site's main direction, with floor lines.
    const group = new THREE.Group();
    group.position.set(MASS_ORIGIN[0], MASS_ORIGIN[1], 0);
    group.rotation.z = SITE_ANGLE;
    for (const b of scheme.blocks) {
      const h = b.floors * FLOOR_HEIGHT;
      const box = new THREE.Mesh(new THREE.BoxGeometry(b.w, b.d, h), new THREE.MeshLambertMaterial({ color: mass }));
      box.position.set(b.u, b.v, h / 2);
      group.add(box);
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(box.geometry), new THREE.LineBasicMaterial({ color: ink }));
      edges.position.copy(box.position);
      group.add(edges);
      for (let f = 1; f < b.floors && !plan; f += 1) {
        const ring = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints([
          [-b.w / 2, -b.d / 2], [b.w / 2, -b.d / 2], [b.w / 2, b.d / 2], [-b.w / 2, b.d / 2],
        ].map(([x, y]) => new THREE.Vector3(b.u + x, b.v + y, f * FLOOR_HEIGHT))), new THREE.LineBasicMaterial({ color: ink, transparent: true, opacity: 0.35 }));
        group.add(ring);
      }
    }
    scene.add(group);

    // Tracing sheets laid over the plan show up as lines on the ground.
    const trace = new THREE.LineBasicMaterial({ color: css('--pen', '#2b5d8a') });
    for (const t of overlays) {
      for (const st of t.strokes) {
        scene.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(st.map(([x, y]) => new THREE.Vector3(x, y, 0.3))), trace));
      }
    }

    // North arrow on the ground.
    const north = new THREE.ArrowHelper(new THREE.Vector3(0, 1, 0), new THREE.Vector3(-55, 60, 0.2), 18, ink, 5, 3);
    scene.add(north);

    const resize = () => {
      const w = el.clientWidth || 1;
      const hgt = el.clientHeight || 1;
      renderer.setSize(w, hgt, false);
      renderer.domElement.style.width = '100%';
      renderer.domElement.style.height = '100%';
      if (plan) {
        const half = PLAN_SPAN / 2;
        const ax = w >= hgt ? (half * w) / hgt : half;
        const ay = w >= hgt ? half : (half * hgt) / w;
        Object.assign(camera, { left: -ax, right: ax, top: ay, bottom: -ay });
      } else camera.aspect = w / hgt;
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(el);
    resize();
    let frame = 0;
    const tick = () => { controls.update(); renderer.render(scene, camera); frame = requestAnimationFrame(tick); };
    tick();
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      controls.dispose();
      renderer.dispose();
      el.removeChild(renderer.domElement);
    };
  }, [scheme, mode, overlayKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const stop = (e) => e.stopPropagation();
  return (
    <div className="three" ref={host} style={{ height }}
      onPointerDown={stop} onPointerMove={stop} onPointerUp={stop} onWheel={stop} onDoubleClick={stop}
      aria-label={plan2d(mode, scheme)} role="img" />
  );
}
