/* 原生 Three.js 示例。螺旋珠链是绘图演示，不代表真实分子结构。 */
(function () {
'use strict';
const { THREE, ss, E, seg } = VK;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 1920 / 1080, 0.1, 100);
camera.position.set(0, 0.6, 17);
camera.lookAt(0, 0.6, 0);
scene.add(new THREE.HemisphereLight('#D7F5FF', '#19253F', 2.0));
const key = new THREE.DirectionalLight('#FFF0CA', 3.5);
key.position.set(-4, 6, 8);
scene.add(key);
const rim = new THREE.DirectionalLight('#57BFFF', 2.0);
rim.position.set(5, -2, -4);
scene.add(rim);

const model = new THREE.Group();
const points = [];
const bead = new THREE.SphereGeometry(0.19, 20, 12);
const cyan = new THREE.MeshStandardMaterial({ color: '#62DBEB', roughness: 0.3, metalness: 0.25 });
const gold = new THREE.MeshStandardMaterial({ color: '#F6C777', roughness: 0.3, metalness: 0.3 });
for (let i = 0; i < 38; i++) {
  const angle = i * 0.43;
  const position = new THREE.Vector3(Math.cos(angle) * 1.45, (i - 18.5) * 0.145, Math.sin(angle) * 1.45);
  points.push(position);
  const mesh = new THREE.Mesh(bead, i === 9 ? gold : cyan);
  mesh.position.copy(position);
  model.add(mesh);
}
const tube = new THREE.Mesh(
  new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points), 180, 0.055, 8, false),
  new THREE.MeshStandardMaterial({ color: '#35798A', roughness: 0.6 })
);
model.add(tube);
scene.add(model);

VK.film({
  dur: 8, theme: 'night', meta: { title: '同一个世界 · Three.js 原生示例' },
  events: [
    { t: 0.4, name: 'chord', params: { gain: 0.5 } },
    { t: 3.4, name: 'soft', params: { gain: 0.5 } },
    { t: 6.0, name: 'tick', params: { pitch: 4 } },
  ],
  draw(fr, t) {
    // 直接由绝对时间设置姿态，任意跳转不会依赖上一帧。
    model.rotation.set(0.18 + Math.sin(t * 0.4) * 0.12, t * 0.55, -0.22);
    model.scale.setScalar(0.75 + 0.25 * E.out3(seg(t, 0, 1.2)));
    fr.look.scene3d = { scene, camera };
    fr.look.bgo.stars = 0.5;
    fr.look.bloom = 0.35;
    fr.text('同一个世界', 960, 120, { font: 'serifl', size: 58, track: 12, color: '#EDF8FF', a: ss(t, 0.1, 0.7) });
    fr.text('THREE.JS · 2D + 3D', 960, 185, { font: 'mono', size: 20, track: 4, color: '#8DA5B8' });
    VKit.subs(fr, t, [
      { a: 0.8, b: 3.6, zh: '同一串珠子，可以从不同方向观察。' },
      { a: 4.0, b: 7.4, zh: '物体有前后，字幕始终留在画面上。' },
    ], 'night');
  },
});
})();
