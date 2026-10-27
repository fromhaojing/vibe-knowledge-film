# vibe-knowledge-film

把选题或文案制作成无旁白的横屏知识短片。Agent 研究事实、设计字幕和分镜、编写动画工程，再用浏览器逐帧渲染为 MP4。成片质量取决于讲解设计和样片复核；Skill 提供制作规范、引擎和检查工具。

提供两套外观：C「夜曲」适合抽象概念和机制，B「寓言」适合心理、行为和生活场景。通用字幕、绘图和转场组件可以复用，具体故事与画面根据题材设计。

当前主渲染使用 **Three.js WebGLRenderer + 正交相机**。原有 `VK` / `Frame` 绘图接口由 GPU 兼容画笔执行，Canvas 只用于小型字形或静态素材纹理；需要空间关系时也可使用原生 Three.js 场景。`seek(t)` 按绝对时间生成每一帧，Playwright 截帧、ffmpeg 编码，最后混合事件音和可选配乐。

## 夜曲：《折叠》

题目是蛋白质折叠，2024 年诺贝尔化学奖。这里是开头 33 秒。

![折叠](examples/fold_C.gif)

## 寓言：《鸽子的迷信》

一只鸽子怎么变得迷信。这里是开头 33 秒。

![鸽子的迷信](examples/pigeon_B.gif)

以上 GIF 是原有示例预览；修改引擎后以重新渲染的检查结果为准。

## 本地使用

先在仓库目录运行环境检查：

```bash
python engine/render.py --doctor
```

已在 Python 3.12 验证。运行需要 Python 依赖、本机 Google Chrome、ffmpeg、字体和支持 WebGL 的浏览器环境。自定义 Chrome 路径可设置 `VK_CHROME_EXECUTABLE`。根据检查结果准备缺失项；检查命令不自动安装依赖。

需要安装时，由你或已获安装授权的 Agent 执行：

```bash
pip install -r requirements.txt
python engine/get_fonts.py
```

渲染使用本机 Chrome，不需要另外下载 Playwright 浏览器。字体下载需要网络；字体按各自的 SIL Open Font License 使用。

Three.js **0.186.1** 和 SVGLoader 固定在 `engine/vendor/`，页面从本地服务加载，不访问 CDN；应保留随附的第三方许可说明。无须将整个动态画面绘制到 Canvas 再上传纹理。

在自己的项目目录建立工程：

```bash
python scripts/new_film.py <工程目录> --world C
python engine/render.py <工程目录> --serve
python engine/render.py <工程目录> --sheet 16
python engine/render.py <工程目录> --clip 0 30 head
```

`--world` 可选 `C`（夜曲）或 `B`（寓言）。先检查代表性镜头和样片，通过后再渲染全片：

```bash
python engine/render.py <工程目录> --det
python engine/render.py <工程目录> --jobs 4
python engine/render.py <工程目录> --events
python engine/audio.py <工程目录>
```

`renders/raw.mp4` 是无声画面，`renders/final.mp4` 是合片。音效推荐集中声明为 `EVENTS` 数组并通过 `events: EVENTS` 导出；异步资源可由 `prepare` 准备，准备完成且首帧成功后才就绪。原生 Three.js 场景示例见 `examples/three_native/`。完整命令、ES module 加载方式和 API 见 [references/engine.md](references/engine.md)。

## 验证修改

准备好本地依赖和字体后运行：

```bash
python -m unittest discover -s tests -p "test_*.py" -v
python tests/browser_semantics.py
```

单测覆盖渲染失败、原子输出、进程清理、音频静音和工程创建；浏览器测试覆盖现有示例跳帧、GPU 绘图语义及资源稳定性。测试不会安装 Skill。

## 作为 Skill 使用

将目录放入所用 Agent 的 Skill 目录，文件夹名保持 `vibe-knowledge-film`。例如 Claude Code 常见路径为 `~/.claude/skills/vibe-knowledge-film`。安装位置依宿主而定，完整工作流在 [SKILL.md](SKILL.md)。

给 Agent 一个选题、文案或现有视频工程。它应先检查环境，再建立来源可追溯的事实表和分镜，用静帧及样片判断主体、动作、字幕和讲解是否清楚。用户已要求直接制作时，无须因固定流程等待多轮确认；有明确阶段审核要求时遵守该要求。

修改工程和安装 Skill 是不同操作；制作请求不会自动安装、上传或发布。依赖或渲染失败时保留诊断和工程，修复后继续。

## 许可

引擎、脚本和文档里的方法说明使用 MIT 许可，见 [LICENSE](LICENSE)。Three.js 等第三方依赖遵循各自许可。

`references/analysis.md`、`references/prompts.md` 里按成片填好的 brief，以及 `examples/stim_B`、`info_C`，字幕和画面设计来自他人的短片，版权属于原作者。这两段是学习对照，不要当成自己的作品发布。

## 联系

微信号 Yangdavee，备注来意。

## 友情链接

https://linux.do/
