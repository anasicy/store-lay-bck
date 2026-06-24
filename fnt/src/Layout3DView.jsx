import { useEffect, useRef } from 'react';
import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { CSS2DRenderer, CSS2DObject } from 'three/examples/jsm/renderers/CSS2DRenderer.js';

/**
 * 3D view of the store layout using Three.js.
 * Coordinate mapping: store X→X, store Y (depth)→Z, fixture height→Y (up).
 */
function Layout3DView({ placements, storeBoundary }) {
  const mountRef = useRef(null);

  useEffect(() => {
    if (!placements?.length || !storeBoundary) return;
    const mount = mountRef.current;
    if (!mount) return;

    const W = mount.clientWidth || 760;
    const H = 420;

    const bounds = storeBoundary.bounds;
    const storeW = bounds.max[0] - bounds.min[0];
    const storeD = bounds.max[1] - bounds.min[1];
    const maxDim = Math.max(storeW, storeD);

    // ── Scene ────────────────────────────────────────────────────────────────
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0xf0f4f8);
    scene.fog = new THREE.Fog(0xf0f4f8, maxDim * 2, maxDim * 5);

    // ── Camera ───────────────────────────────────────────────────────────────
    const camera = new THREE.PerspectiveCamera(45, W / H, 10, maxDim * 10);
    camera.position.set(storeW / 2, maxDim * 0.65, storeD + maxDim * 0.55);
    camera.lookAt(storeW / 2, 0, storeD / 2);

    // ── Renderer ─────────────────────────────────────────────────────────────
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.setSize(W, H);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    mount.appendChild(renderer.domElement);

    // ── CSS2D label renderer ──────────────────────────────────────────────────
    const labelRenderer = new CSS2DRenderer();
    labelRenderer.setSize(W, H);
    labelRenderer.domElement.style.position = 'absolute';
    labelRenderer.domElement.style.top = '0';
    labelRenderer.domElement.style.left = '0';
    labelRenderer.domElement.style.pointerEvents = 'none';
    mount.style.position = 'relative';
    mount.appendChild(labelRenderer.domElement);

    // ── Controls ─────────────────────────────────────────────────────────────
    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.08;
    controls.minDistance = maxDim * 0.1;
    controls.maxDistance = maxDim * 3;
    controls.target.set(storeW / 2, 0, storeD / 2);
    controls.update();

    // ── Lights ───────────────────────────────────────────────────────────────
    scene.add(new THREE.AmbientLight(0xffffff, 0.65));
    const sun = new THREE.DirectionalLight(0xffffff, 0.9);
    sun.position.set(storeW * 0.8, maxDim, storeD * 0.3);
    sun.castShadow = true;
    sun.shadow.mapSize.width = 2048;
    sun.shadow.mapSize.height = 2048;
    sun.shadow.camera.near = 10;
    sun.shadow.camera.far = maxDim * 4;
    sun.shadow.camera.left = -maxDim;
    sun.shadow.camera.right = maxDim * 2;
    sun.shadow.camera.top = maxDim;
    sun.shadow.camera.bottom = -maxDim;
    scene.add(sun);

    // ── Floor ────────────────────────────────────────────────────────────────
    const floorGeo = new THREE.PlaneGeometry(storeW, storeD);
    const floorMat = new THREE.MeshLambertMaterial({ color: 0xf5f4f0 });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.set(storeW / 2, 0, storeD / 2);
    floor.receiveShadow = true;
    scene.add(floor);

    // ── Store walls (semi-transparent) ────────────────────────────────────────
    const wallH = 3200;
    const wallT = 120;
    const wallMat = new THREE.MeshLambertMaterial({
      color: 0xe8ecf0, transparent: true, opacity: 0.45,
    });
    const wallDefs = [
      { size: [storeW + wallT * 2, wallH, wallT], pos: [storeW / 2, wallH / 2, 0] },
      { size: [storeW + wallT * 2, wallH, wallT], pos: [storeW / 2, wallH / 2, storeD] },
      { size: [wallT, wallH, storeD], pos: [0, wallH / 2, storeD / 2] },
      { size: [wallT, wallH, storeD], pos: [storeW, wallH / 2, storeD / 2] },
    ];
    wallDefs.forEach(({ size, pos }) => {
      const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), wallMat);
      mesh.position.set(...pos);
      scene.add(mesh);
    });

    // ── Grid on floor ─────────────────────────────────────────────────────────
    const gridHelper = new THREE.GridHelper(
      Math.max(storeW, storeD) * 1.05, 20, 0xbbbbbb, 0xdddddd
    );
    gridHelper.position.set(storeW / 2, 1, storeD / 2);
    scene.add(gridHelper);

    // ── Fixtures ──────────────────────────────────────────────────────────────
    placements.forEach(p => {
      const rot = p.rotation === 90 || p.rotation === 270;
      const fw = rot ? p.d : p.l;   // footprint width  (X axis)
      const fd = rot ? p.l : p.d;   // footprint depth  (Z axis)
      const fh = Math.max(p.h || 1000, 300); // height (Y axis)

      const colorHex = parseInt(
        (p.zone_color || '#94A3B8').replace('#', ''), 16
      );

      const mat = new THREE.MeshLambertMaterial({
        color: colorHex, transparent: true, opacity: 0.82,
      });
      const geo = new THREE.BoxGeometry(fw, fh, fd);
      const mesh = new THREE.Mesh(geo, mat);

      // p.x, p.y are bottom-left in store coords → centre in 3D
      mesh.position.set(
        p.x + fw / 2,   // X centre
        fh / 2,          // Y centre (half-height above floor)
        p.y + fd / 2    // Z centre
      );
      mesh.castShadow = true;
      mesh.receiveShadow = false;
      scene.add(mesh);

      // Edge outline
      const edges = new THREE.EdgesGeometry(geo);
      const lineMat = new THREE.LineBasicMaterial({
        color: 0x1e3a5f, transparent: true, opacity: 0.35,
      });
      mesh.add(new THREE.LineSegments(edges, lineMat));

      // Fixture name label above the fixture
      const shortName = p.fixture.length > 22 ? p.fixture.slice(0, 20) + '…' : p.fixture;
      const div = document.createElement('div');
      div.textContent = shortName;
      div.style.cssText = [
        'background:rgba(255,255,255,0.82)',
        'color:#1e2d3d',
        'font-size:9px',
        'font-family:monospace',
        'padding:1px 4px',
        'border-radius:3px',
        'white-space:nowrap',
        'pointer-events:none',
        'border:1px solid rgba(0,0,0,0.12)',
      ].join(';');
      const label = new CSS2DObject(div);
      label.position.set(0, fh / 2 + 80, 0); // 80 mm above top of fixture
      mesh.add(label);
    });

    // ── Animation loop ────────────────────────────────────────────────────────
    let animId;
    const animate = () => {
      animId = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
      labelRenderer.render(scene, camera);
    };
    animate();

    // ── Resize handler ────────────────────────────────────────────────────────
    const onResize = () => {
      if (!mount) return;
      const w = mount.clientWidth || 760;
      camera.aspect = w / H;
      camera.updateProjectionMatrix();
      renderer.setSize(w, H);
      labelRenderer.setSize(w, H);
    };
    window.addEventListener('resize', onResize);

    return () => {
      cancelAnimationFrame(animId);
      window.removeEventListener('resize', onResize);
      controls.dispose();
      renderer.dispose();
      if (mount.contains(renderer.domElement)) {
        mount.removeChild(renderer.domElement);
      }
      if (mount.contains(labelRenderer.domElement)) {
        mount.removeChild(labelRenderer.domElement);
      }
    };
  }, [placements, storeBoundary]);

  return (
    <div
      ref={mountRef}
      className="layout-3d-mount"
      style={{ width: '100%', height: '420px', borderRadius: '8px', overflow: 'hidden' }}
    />
  );
}

export default Layout3DView;
