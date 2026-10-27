# vibe-knowledge-film · Three.js

让 Agent 把选题或文案制作成无旁白的知识短片：先研究事实、设计分镜，再编写动画，用字幕和画面演示概念，最后导出 MP4。

本项目基于 [HeyChengC/vibe-knowledge-film](https://github.com/HeyChengC/vibe-knowledge-film) 修改。本版本将主画面迁移到 **Three.js WebGL**，保留原有讲解设计和 `VK` / `Frame` 接口，并改进渲染、音频和错误处理。

## 功能

- **二维与三维画面**：正交相机绘制二维图形，原生 Three.js 场景表现空间关系；字幕和标注可与三维场景组合。
- **两套外观**：C「夜曲」适合抽象概念与机制，B「寓言」适合心理、行为和生活场景。
- **按时间生成画面**：`seek(t)` 支持跳帧、静帧检查、片段导出和并行渲染。
- **事件音与配乐**：合成音效，可混入已有 BGM；输出无声画面或带音轨的最终视频。
- **本地依赖**：Three.js 0.186.1 与 SVGLoader 随仓库提供，运行时不依赖 CDN。

主画面由 Three.js 几何体、着色器和 GPU 图层绘制。Canvas 用于字形和静态素材纹理；兼容画笔覆盖本仓库使用的常见操作，完整范围见 [引擎文档](references/engine.md)。

## 环境准备

在仓库根目录执行命令。需要：

- Python 3.12（已验证）与 [requirements.txt](requirements.txt) 中的依赖；建议使用虚拟环境。
- 本机 Google Chrome，浏览器环境支持 WebGL 2。
- ffmpeg，可通过 `PATH` 调用。

准备 Python 依赖和字体：

~~~bash
python -m pip install -r requirements.txt
python engine/get_fonts.py
python engine/render.py --doctor
~~~

字体首次下载需要网络。渲染使用本机 Chrome，无须再运行 `playwright install`；如需指定 Chrome，可设置环境变量 `VK_CHROME_EXECUTABLE`。页面应通过渲染工具的本地服务打开。

## 先运行一个示例

[原生 Three.js 示例](examples/three_native/) 是一段 8 秒的三维珠链演示，结合二维标题、字幕和事件音。下图来自当前引擎渲染：

![Three.js 二维字幕与三维场景预览](examples/three_native/preview.jpg)

浏览器预览：

~~~bash
python engine/render.py examples/three_native --serve
~~~

打开终端显示的地址。导出完整示例：

~~~bash
python engine/render.py examples/three_native --det
python engine/render.py examples/three_native --jobs 2
python engine/render.py examples/three_native --events
python engine/audio.py examples/three_native
~~~

输出位于：

| 文件 | 内容 |
|---|---|
| `examples/three_native/renders/raw.mp4` | 无声视频 |
| `examples/three_native/renders/final.mp4` | 带合成声音的视频 |

更多示例见 [examples/](examples/README.md)：`fold_C`、`pigeon_B` 展示具体分镜，`kit_gallery` 展示通用组件。

## 创建自己的短片

~~~bash
python scripts/new_film.py ../my-film --world C --title "我的短片" --duration 30
~~~

`--world` 可选 `C` 或 `B`，帧率默认为 30，可用 `--fps` 指定。默认画面为 1920×1080。

**初始化只生成 `index.html` 和空的 `film.js` 骨架。** 作者或 Agent 仍需建立事实表、编写分镜、填入字幕和音效，并实现镜头；初始化命令不会自动完成内容创作。

完成镜头后，先检查画面：

~~~bash
python engine/render.py ../my-film --stills 3 8 15
python engine/render.py ../my-film --motion 8 10
python engine/render.py ../my-film --clip 0 30 head
~~~

`--clip` 输出检查用的无声片段。全片导出时，使用上节的确定性检查、全片渲染、事件导出和音频合成命令，将工程路径替换为 `../my-film`。

命令、模块拆分、字幕、声音和原生 Three.js API 见 [references/engine.md](references/engine.md)。

## 交给 Agent 制作

让 Agent 读取本仓库的 [SKILL.md](SKILL.md)，再提供选题、文案或已有工程。例如：

> 使用这个 Skill，制作一条 30 秒、无旁白的知识短片，用抛硬币的小实验向普通观众解释大数定律。先建立事实表和分镜，再制作样片并检查画面。

工作流包括事实研究、形象设计、字幕与分镜、代表性镜头、样片检查和成片导出。Python 依赖准备与 Skill 注册是两个独立步骤；若需要注册 Skill，按所用 Agent 的约定操作。

## 测试

准备好依赖、Chrome、ffmpeg 和字体后运行：

~~~bash
python -m unittest discover -s tests -p "test_*.py" -v
python tests/browser_semantics.py
~~~

测试覆盖渲染失败、原子输出、进程清理、音频静音、工程创建，以及浏览器中的示例跳帧、GPU 绘图语义和资源稳定性。

## 来源与许可

原始项目与讲解方法来自 [HeyChengC/vibe-knowledge-film](https://github.com/HeyChengC/vibe-knowledge-film)。本仓库的引擎、脚本和方法说明按 [MIT License](LICENSE) 使用；Three.js 的许可位于 [engine/vendor/LICENSE](engine/vendor/LICENSE)，字体按各自的 SIL Open Font License 使用。

参考片内容不包含在 MIT 授权内。`references/analysis.md`、`references/prompts.md`、`references/visualization.md` 中来自他人作品的字幕和画面，以及 `examples/stim_B`、`examples/info_C` 的内容，仅供学习对照；具体说明见 [LICENSE](LICENSE)。制作新片时应使用自己的内容和分镜。
