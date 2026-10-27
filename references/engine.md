# 引擎

一张 1920×1080 的 WebGL 输出画布，一个 `seek(t)`。**每一帧由绝对时间 t、固定资源和种子决定**，可以只渲一段、只截几帧、乱序跳转；对象和缓存可以保留，动画状态不能依赖上一帧。

主绘制使用 Three.js `WebGLRenderer` 与正交相机，`VK` / `Frame` 将二维画笔操作转换为 GPU 图元。Canvas 仅用于小型字形或静态素材纹理，不承担整帧动画再上传 GPU。需要真实空间关系时用原生 Three.js 场景；普通字幕、图表和扁平角色仍可使用兼容接口。

Three.js 0.186.1 固定在 `engine/vendor/three.module.js`、`three.core.js`、`SVGLoader.js`，运行时从本地服务加载，无 CDN 依赖。保留相应第三方许可。

```
engine/
  vk.js        核心：时间助手、Three.js 渲染、Frame 兼容画笔、背景与后期
  vk-kit.js    每条片都用的件：字幕、片名卡、年份栏、章节标、仪表、骰子、闪、暗一下……
  index.html   页面模板（new_film.py 会拷进工程）
  render.py    逐帧截图 → ffmpeg；也负责静帧、拼图、事件表、预览
  audio.py     按事件表合成声音，或垫一首现成配乐
  get_fonts.py 按需下载字体（需要网络）
  vendor/      固定版本 Three.js、SVGLoader 与许可
  fonts/
```

初始工程包含 `index.html` 和 `film.js`，可继续增加场景模块、事实表、分镜与资源。引擎由 `render.py` 内置的小服务器挂在 `/engine/` 下，不要用 `file://` 直接打开工程。

页面使用 ES modules，最后的模块块依次加载引擎、组件和影片；章节或共享数据模块放在 `film.js` 之前：

```html
<script type="module">
  import "./engine/vk.js";
  import "./engine/vk-kit.js";
  // import "./scenes/ch1.js";
  import "./film.js";
</script>
```

`VK` 与 `VKit` 仍暴露在全局，旧的函数组织方式可以保留；引擎文件本身不能再用普通 `<script src>` 加载。

可选的外观是两套：`night`（C 夜曲）和 `flat`（B 寓言）。下面出现的 `gilt`（鎏金）和它的年份栏、金字卡还在引擎里——寓言的片名卡和货架图在用——但不再作为一套可选外观。

## 命令

```bash
python engine/render.py --doctor                       # 环境自检，不安装依赖
python scripts/new_film.py <工程目录> --world C|B     # 建工程：index.html + 一份没有画面的 film.js 骨架
python engine/render.py <工程> --serve                  # 预览 http://127.0.0.1:8765/?play
python engine/render.py <工程> --stills 2.5 8.5 21      # 截几帧 → review/
python engine/render.py <工程> --sheet 16               # 全片均匀 16 帧拼一张 → review/sheet.jpg
python engine/render.py <工程> --sheet 3.5 9 21.5       # 指定时刻拼一张
python engine/render.py <工程> --motion 8.2 10.6        # 这段时间里均匀取 12 帧拼一张 → review/motion_8.2-10.6.jpg（看转场）
python engine/render.py <工程> --clip 0 30 head         # 只渲 0–30s → renders/head.mp4
python engine/render.py <工程> --det                    # 确定性自检
python engine/render.py <工程>                          # 全片 → renders/raw.mp4（无声）
python engine/render.py <工程> --jobs 4                 # 全片，分 4 段并行渲再无损拼接
python engine/render.py <工程> --events                 # 导出音效事件表 → audio/events.json
python engine/audio.py  <工程>                          # 合成声音 + 合片 → renders/final.mp4
python engine/audio.py  <工程> --bgm 曲子.mp3 -8        # 垫现成配乐（-8 dB），事件音照叠
```

先运行 `--doctor`，检查 Python 依赖、本机 Chrome、ffmpeg、本地 vendor 与字体；需要指定 Chrome 时设置环境变量 `VK_CHROME_EXECUTABLE`。检查不负责安装。依赖或资源缺失时保存诊断，准备好缺失项后再继续。

依赖：Python 的 `playwright`（用本机 Chrome）、`numpy`、`scipy`、`Pillow`，以及 `ffmpeg`。字体可在获得下载授权后运行 `python engine/get_fonts.py` 准备。WebGL 绘制加速不等于截帧加速，浏览器截图和视频编码仍会耗时；实际速度依机器、场景和并行数而定。先看拼图，再渲片段，最后渲全片。

资源、浏览器或编码失败后，停止依赖该产物的后续步骤，保留失败命令和诊断；不要将目录中的旧 MP4 当成本次渲染成功。

## film.js 的样子

```js
(function () {
'use strict';
const { W, H, lerp, seg, ss, E, fade, rng } = VK;
const K = VKit, P = K.PAL.night;

const SUBS  = [ { a: 4.0, b: 8.5, zh: '你一定{猜到}了下一个字。', en: 'You already know the next character.' }, … ];
const MARKS = [ { t: .4, no: '00', zh: '序', en: 'PROLOGUE' }, { t: 38.6, no: '01', zh: '猜', en: 'THE GUESS' } ];
const EVENTS = [ { t: 4.0, name: 'tick', params: { gain: 0.4 } } ];

/* 一站一个函数。自己管自己的进场和退场（乘一个透明度），不要靠 draw 里的 if 硬切 */
function hook(fr, t) { const a = 1 - ss(t, 13.5, 14.0); … }
function ch1(fr, t)  { const a = ss(t, 38.6, 39.5); … }

VK.film({
  dur: 300, theme: 'night', meta: { title: '……' },
  events: EVENTS,
  draw(fr, t) {
    fr.look.bgo = { stars: K.dips(t, [14.05, 38.25]) };   // 底的参数每帧可以改
    K.chapterMark(fr, t, MARKS);                          // 常驻元素
    if (t < 14.1) hook(fr, t);
    if (t >= 38.6) ch1(fr, t);                            // 相邻两站的时间窗重叠半秒，各自淡入淡出
    K.flash(fr, t, 24.03);                                // 全幅效果
    K.subs(fr, t, SUBS, 'night');                         // 字幕永远最后画，压在一切之上
  },
});
})();
```

能跑的例子在 `examples/`：`fold_C`（自己的题目，夜曲，33 秒：从血管推进细胞再推到一串珠子，全片一台摄影机；分镜表在同目录 `storyboard.md`）、`pigeon_B`（自己的题目，寓言，33 秒：六个镜头六种景别，计时器按真实时间走）、`stim_B`（寓言，12 秒）、`info_C`（夜曲，47 秒）。
`examples/kit_gallery` 把通用组件各演一遍，`examples/three_native` 展示原生 Three.js 镜头。

**长片按场景或章节拆模块。** `film.js` 保留字幕表、共享起止时间和调度，场景模块负责自己的对象与动作。在页面的模块块中，于 `film.js` 前 `import "./scenes/ch1.js"`；模块可导出函数供 `film.js` 导入，或沿用 `window.CH`。按讲解职责拆分，不必等到固定行数；一次只修改相关镜头更容易复核。

## 资源准备与就绪状态

`VK.film` 可选 `prepare(F)`，允许返回 Promise。`F` 是影片运行上下文，`F.fr` 才是绘图 `Frame`；无需该参数时可定义无参异步函数。把纹理、数据等异步资源的准备放在这里，或在调用 `VK.film` 前完成；不要在逐帧 `draw` 中发起异步加载。场景几何和静态数据也应提前建立，逐帧只更新随 t 变化的属性。

引擎等待 `prepare` 完成并成功绘制首帧后，才将 `window.READY` 设为 `true`。准备或首帧失败会记录 `window.FILM_ERROR`；渲染工具应报告该错误，不能继续输出空帧。手动控制页面时也先等待就绪，再调用 `seek(t)`。控制台的 `renderInfo()` 可检查当前后端、Three.js revision 和帧号。

## 时间

| | |
|---|---|
| `seg(t, a, b)` | t 在 [a, b] 里走到哪了，0…1，两头夹住 |
| `ss(t, a, b)` | 同上，再过一道平滑（最常用：某个量在 a→b 之间从 0 到 1） |
| `fade(t, a, b, fin=.5, fout=.5)` | 出现–停留–消失的包络：a 起经 fin 秒亮起，b 前 fout 秒暗下 |
| `E.out3 / io3 / in2 / in3 / out2 / out5 / outExpo / outBack / lin` | 缓动。进场用 `out3`，位移用 `io3`，推近用 `in2`，数字滚动用 `out3` |
| `lerp(a, b, k)` `clamp(x, a=0, b=1)` `smooth(x)` | |
| `K.track([[t, v], …], t)` | 关键帧曲线，平滑穿过每个点。机位、物体轨迹用它 |
| `K.dips(t, [t1, t2, …], half=.55)` | 章与章之间"暗一下"：每个时刻附近降到 0，返回亮度系数 |
| `VK.scene(fr, t, a, b, fn(lt, k), fin, fout)` | 只在 [a, b] 内调用 fn，并替它乘好淡入淡出。lt 是本地时间 |

**随机** 只用 `rng(seed)`（返回一个 0…1 的发生器）和 `hash(n)`。不要用 `Math.random()` 和 `Date.now()`——
同一帧每次渲染必须一模一样，`render.py --det` 会查。

**模拟要真算，但要能回放。** 载入时把整场模拟一次算完、存成表，每帧只按时间查表：

```js
/* 摸 25,000 次石子：DRAWS[n] = 摸完第 n 次时白石的比例 */
const DRAWS = (() => { const r = rng(1713), out = new Float32Array(25001); let w = 0;
  for (let n = 1; n <= 25000; n++) { if (r() < .6) w++; out[n] = w / n; } return out; })();
function urn(fr, t) {
  const n = Math.max(1, Math.floor(25000 * E.in3(seg(t, 75, 82))));   // 这一帧摸到第几次：先慢后快
  /* 折线画到第 n 个点；计数器显示 n 和 DRAWS[n] */
}
```

粒子（钉板的珠子、撒下的针、落下的骨头）同理：每个粒子的出发时刻和随机路径由它的序号决定，
某一帧的位置用"t − 出发时刻"直接算出来，不要一帧一帧积分。

## Frame：`fr`

`fr.t` 当前时间，`fr.frame` 帧号。`fr.x` 是 **GPU 命令兼容画笔，不是浏览器原生 CanvasRenderingContext2D**；现有绘图可沿用它支持的路径、变换、文字和颜色操作，但不能据此假定完整 Canvas API 可用。优先使用下面的 `Frame` 方法。

路径优先交给 `fr.path(svgPathString, o)`。使用低层兼容画笔时，以 `VK.parsePath` 解析路径，不能传入浏览器的 `Path2D`。不要对输出画布调用 Canvas 2D `getContext`，也不要依赖逐帧 `getImageData` / `putImageData` 来制作后期。

**成组**

| | |
|---|---|
| `fr.g({ a, at:[x,y], rot, s, add, blur, clip:[x,y,w,h] }, fn)` | 在一组变换 / 透明度 / 加法混合里画 fn |
| `fr.layer({ a, s, at, rot, cx, cy, blur, add }, fn)` | 隔离成组后整体合成。一组互相重叠的半透明形状要一起淡入淡出时用它，否则重叠处会透 |

**光**

| | |
|---|---|
| `fr.glow(x, y, r, color, a)` | 一团柔光（加法） |
| `fr.spark(x, y, r, color, a)` | 光点：小白核 + 色晕 + 大淡晕 |
| `fr.comet(x, y, len, r, color, a, ang=0)` | 带彗尾的光点，尾巴朝 ang 的反方向 |

**线和形**（最后一个参数都是选项：`color` 描边色、`fill` 填充、`w` 线宽、`a` 透明度、`glow` 辉光半径、`dash`、`add` 加法混合、`cap`）

| | |
|---|---|
| `fr.line(x1, y1, x2, y2, o)` | |
| `fr.poly(pts, o)` | 折线。`o.k`（0…1）只画前 k 这么长——线"长出来"就靠它 |
| `fr.along(pts, k)` | 返回 `[x, y, 切向角]`，给线头安一个光点 |
| `fr.path(svgPathString, o)` | SVG 路径；`o.at / rot / s` 摆放 |
| `fr.circle(cx, cy, r, o)` `fr.ellipse(cx, cy, rx, ry, o)` `fr.arc(cx, cy, r, a0, a1, o)` | `o.a0 / a1` 只画一段弧 |
| `fr.rect(x, y, w, h, o)` | `o.r` 圆角 |
| `fr.grad(x0, y0, x1, y1, [[位置, 色, 透明度], …])` `fr.rgrad(cx, cy, r0, r1, stops)` | 渐变，传给 `fill` |

**字**

`fr.text(str, x, y, o)`，返回宽度。选项：

| | |
|---|---|
| `font` | 字体键，见下 |
| `size` `color` `a` | |
| `track` | 字距，像素（参考片的字距都很大：字幕 0.1em，片名 0.1–0.3em，小标 0.3–0.6em） |
| `align` | `'c'`（默认）`'l'` `'r'` |
| `glow` `glowColor` `glowA` | 字自己的辉光 |
| `shadow` | 深色投影的透明度（压在亮底上的字要开） |
| `blur` | 模糊，像素 |
| `grad` | 竖向渐变 `[[0, 色], [1, 色]]`（金字用） |

`fr.chars(str, x, y, o, per)` 逐字画：`per(i, 字)` 返回 `{ a, blur, dy, color, glow, s }` 覆盖这个字的样子——逐字显影、打字、单字变色都用它。
`fr.layout(str, x, o)` 只算不画，返回每个字的 `{ ch, x, w, cx }`；`fr.measure(str, o)` 返回整行宽。定稿前用它量一下最长的那句字幕。

字体键：

| 键 | 是什么 | 用在哪 |
|---|---|---|
| `serifh` `serif` `serifm` `serifr` `serifl` `serifx` | 宋体 900 / 700 / 500 / 400 / 300 / 200 | A 的字幕用 `serif`，金字片名用 `serifh`；C 的大字用 `serifl`，字幕用 `serifr` |
| `sansh` `sans` `sansm` `sansr` | 黑体 900 / 700 / 500 / 400 | B 的字幕和标注 |
| `latin` `latinl` `latinm` `latini` `latinim` | Cormorant Garamond 常规 / 细 / 半粗 / 斜体 / 斜体中粗 | 数字、外文题名、公式 |
| `lora` | Lora 斜体 | C 的英文字幕 |
| `mono` | JetBrains Mono | 等宽小标、章节编号 |
| `type` | Courier Prime | 打字机文稿 |

**声音事件优先声明为数据。** `VK.film({ events: EVENTS, ... })` 接受 `[{ t, name, params }]`，也可接受返回该数组的函数。`render.py --events` 可直接导出这份事件表，无须遍历 `draw` 来触发事件。初始化器生成 `const EVENTS = []` 与 `events: EVENTS`；动作、字幕和事件都使用影片绝对时间。

旧工程未提供 `events` 时，才兼容 `fr.sfx(时刻, 名字, 参数)` 的采集方式：遍历全片并按时间、名称与参数去重，采集期间的绘制错误会上抛。一个工程选一种事件来源，推荐把声音集中写进 `EVENTS`，不要与 `draw` 内的旧式 `fr.sfx` 混用。
名字：`tick`（一声嗒，`pitch` 选音高）`soft` `chord`（`root` 半音偏移）`bloom`（和弦 + 一口气）`rise`（上滑音，`dur`）
`thud` `tock` `stamp` `shimmer` `hush`（之后彻底静音 `dur` 秒）。都有 `gain`。

## 底和出帧：`fr.look`

每帧开始时 `fr.look` 是默认值，`draw` 里可以改：

| | |
|---|---|
| `fr.look.bg` | `'gilt'` `'night'` `'flat'`，默认是 `film({ theme })` |
| `fr.look.bgo` | 底的参数。gilt：`warm`（0 冷蓝…1 暖棕）`pool`（上方光池）`floor`（脚下暖光）`horizon`（桌面地平线）`dust`；night：`core`（中央深蓝）`stars`（星点密度）`tint`；flat：`color` |
| `fr.look.bloom` | 辉光强度。默认 night 1、gilt 0.34、flat 0.12 |
| `fr.look.grain` | 胶片颗粒，默认 0.05 |
| `fr.look.under(ctx, t)` | 画在底之上、内容之下；`ctx` 是 GPU 兼容画笔 |
| `fr.look.post(ctx, t)` | 全幅后期兼容钩子，`ctx` 是 GPU 兼容画笔；一般使用下面的组件 |
| `fr.look.scene3d` | 可选 `{ scene, camera }`，提交原生 Three.js 场景；见下节 |

背景、主体和辉光通过 WebGL 图元、纹理及混合合成；不是把整帧 Canvas 反复上传。**越亮的东西光晕越明显**。
在夜空里画实心的大色块会糊成一团——把它画暗一点，或者这一段把 `bloom` 调低。

## 原生 Three.js 镜头

`VK.THREE` 暴露本地固定版本的库。场景、相机、几何体和材质在影片载入时建立；在 `draw(fr, t)` 里根据绝对时间设置位置、旋转、可见性等属性，再提交 `fr.look.scene3d = { scene, camera }`。不另开 `requestAnimationFrame` 或依据真实时钟推进动画。

```js
const THREE = VK.THREE;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(40, VK.W / VK.H, 0.1, 100);
camera.position.z = 6;
const model = new THREE.Mesh(
  new THREE.SphereGeometry(1, 32, 24),
  new THREE.MeshBasicMaterial({ color: 0x64e3f6, wireframe: true })
);
scene.add(model);

VK.film({
  dur: 8, theme: 'night',
  events: [{ t: 1, name: 'soft', params: { gain: 0.3 } }],
  draw(fr, t) {
    model.rotation.set(0.15, t * 0.4, 0);
    fr.look.scene3d = { scene, camera };
    VKit.subs(fr, t, [
      { a: 1, b: 6, zh: '旋转让我们看清它的空间结构' }
    ], 'night');
  }
});
```

默认二维画笔仍使用正交相机；本例显式提交透视相机，只在需要空间关系时采用。原生镜头也必须通过 `--det` 和跳转截帧检查；预计算物理过程后按 t 查表，不依赖上一帧积分。跨项目释放不再使用的 GPU 资源，避免逐帧创建或销毁材质和几何体。

## 件：`VKit`

**字幕** `K.subs(fr, t, list, 'gilt' | 'flat' | 'night')`

```js
{ a: 3.45, b: 6.5, zh: '运气，能被{计算}吗?', big: 1 }        // {词} 金色，{!词} 红色；big: 1 放大，2 再大
{ a: 9.0, b: 13.6, zh: '……', en: '……' }                     // en 只有 night 用
{ a: 42, b: 45, zh: '蛋越大，越值得孵', tone: 'gold' }        // 整句金色（规则句）
```
`a` 是第一个字开始出现的时刻，`b` 是完全消失的时刻。相邻两句之间留 0.15–0.3 秒空。位置和字号见 `worlds.md`，改默认值改 `K.SUB`。

**A 的年份栏** `K.hudYear(fr, t, chapters, end)`

```js
{ t: 17.0, year: '1494', place: '威尼斯 · 帕乔利',
  src: { la: 'Summa de Arithmetica', zh: '《算术大全》', by: '卢卡·帕乔利 · 威尼斯 · 1494' } }   // src 可省；approx: true 在年份前加"约"
```
到了下一条的 `t`，年份逐位滚过去，地点人物上下交替，出处先退后进。`end` 是整个栏退场的时刻。
`K.seal(fr, cx, cy, 半宽, ['中', '断'], a, { rot, s })` 朱印；`K.meander(fr, y, a)` 回纹边。

**C 的章节标** `K.chapterMark(fr, t, [{ t, no: '03', zh: '余', en: 'REDUNDANCY' }, …], end)`

**B 的仪表** `K.gauge(fr, x, y, { value, max: 150, redFrom: 100, label: '本能读数', zone: '超常', caption: '对象：{一杯奶茶}' })`
`value` 自己按时间插值好再传。过了 `redFrom` 整个表变红。

**片名卡**

- `K.titleGilt(fr, lt, { la, zh, tag, motif(fr, lt, a), a, cy, size, track, rays, tagDy })`：A / B 的金字卡。`lt` 是片名卡的本地时间，0 = 闪白最亮的那一刻。
  `motif` 画片名下面的母题图形；没有母题图形时把 `tagDy` 设成 212 让副题靠上。
- `K.titleNight(fr, lt, { zh, sub, en, a, cy, lineY, size, track })`：C 的点阵成字。lt 0 = 闪亮那一帧，约 3.3 秒聚拢完，4.6 秒出副题。
- `K.dustText(fr, str, cx, cy, 文字选项, k, t)`：单独用"点聚成字"，k 0…1。

**全幅效果**（可以叠用）

| | |
|---|---|
| `K.flash(fr, t, t0, { rise, fall, color, edge, peak })` | 闪。A 进片名：`{ rise: .3, fall: .4 }`；C：默认（一帧到顶，0.35 秒落回） |
| `K.ripple(fr, t, t0, cx, cy, { r0, r1, dur, color })` | 一圈扩散的细环。和 `flash`、`hush` 一起用，就是"定理落地" |
| `K.noiseOverlay(fr, k)` | 全幅噪点 |

`K.sepia(fr, k)` 是老纪录片效果（泛黄 + 椭圆暗角 + 片门抖动），它不是全幅后期：调用的那一刻作用在**已经画好的东西**上。
所以顺序是：画场景 → `K.sepia` → 再画仪表和字幕，后者保持原色。

**小道具**

| | |
|---|---|
| `K.die(fr, cx, cy, size, R, { wire, label, a })` | 3D 骰子。`R` 是旋转矩阵（`K.M3.mm(K.M3.rx(a), K.M3.ry(b), …)`）；`wire` 0…1 从实体溶成金线框，`label` 写在线框的每个面上 |
| `K.dieFace(fr, cx, cy, 半宽, 点数, { a, fill })` | 平面的骰面小图标 |
| `K.numberLine(fr, x0, x1, y, { lo, hi, ticks, k, a })` | 数轴，返回 `X(v)` 把数值换成横坐标 |
| `K.bellPts(x0, x1, yBase, 高)` | 钟形曲线的点列，交给 `fr.poly` |
| `K.PAL.gilt / flat / night` | 三套色板 |

通用绘图、字幕、计量和转场组件可以复用。每条片的具体装置与叙事按分镜设计，放在对应场景模块里；`examples/` 用来研究实现方法，避免搬用版权受限的画面设计。

## 容易踩的坑

- **字幕区被占。** 纵向 80%–95% 只属于字幕。装置的最低点不要低于 y=840。
- **相邻两站硬切。** `if (t < 17) a(); else b();` 会切。让两个时间窗重叠半秒，各自乘 `ss` 淡入淡出。
- **辉光过曝。** 见上。A 的实物（骰子、金币、骨头）本身颜色要压暗一档，否则加上辉光会发白。
- **大块的实心东西。** 细胞、身体、场景这类有体积的东西，画进 `fr.look.under = ctx => { … }`：它在底之上、内容之下，不参加辉光。`ctx` 是 GPU 兼容画笔。写法见 `examples/fold_C/film.js` 的 `heroCell`。
- **推拉镜头。** 跨好几个数量级的推近、拉远，缩放要在对数空间里插值（`exp(lerp(ln s0, ln s1, k))`），焦点按 `1/s` 插值，否则会先平移再猛冲。需要线宽与字号不随主体缩放时，单独换算屏幕坐标，或将标注放在独立的二维层。见 `fold_C` 的 `camAt`。
- **老式数字。** Cormorant 默认是高低不齐的老式数字；页面模板已经打开等高数字（`lnum`），自己换字体时记得。
- **半透明叠半透明。** 线框、粒子堆用 `add: true`；实体叠实体用 `fr.layer` 整组淡。
- **一帧创建太多资源。** 原生 Three.js 几何体、材质与场景在载入时建立，逐帧只按 t 更新属性；大量重复对象优先考虑 `InstancedMesh` / `Points`。兼容画笔尽量复用路径和字形；慢的预处理（字形取样、模拟）放在载入时。不要每帧创建纹理或把整张动态画布上传。
- **文字太长。** 定稿前 `fr.measure` 量最长的字幕：A 不超过 1300px，C 中文不超过 1400px。
- **时间写死在好几处。** 每站开头定一个本地时间 `const lt = t - 17`，站内全用 `lt`；整站挪动时只改一个数。


## 兼容边界

兼容画笔覆盖仓库示例使用的路径、文字、变换、渐变和图层操作，不是完整的 Canvas 2D 实现。CSS filter 当前支持 blur；裁剪最多四层嵌套、八个轮廓，裁剪边界在 GPU 的有限顶点预算内取样。复杂混合、特殊浏览器字体或超复杂路径应先制作代表性静帧检查。WebGL 与原生 Canvas 的抗锯齿和辉光不保证逐像素一致，须以本次渲染画面验收。
