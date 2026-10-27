# 原生 Three.js 示例

8 秒可重复跳帧的三维珠链，和同一引擎的二维标题、字幕组合。它是绘图示例，不是科学模拟。

从仓库根目录执行：

```bash
python engine/render.py examples/three_native --sheet 0.8 2.5 4.5 6.5
python engine/render.py examples/three_native --det
python engine/render.py examples/three_native --clip 0 8 native
```

`film.js` 在载入时建立 Three.js 场景、几何体和材质；每次 `draw` 只按绝对时间设置对象属性，并将 `{scene, camera}` 赋给 `fr.look.scene3d`。声音使用独立的 `events` 数组。
