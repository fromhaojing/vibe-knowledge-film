# -*- coding: utf-8 -*-
"""逐帧 seek → 截图 → ffmpeg。
  python render.py <工程> [--jobs 4 | --stills 2.5 8.5 | --sheet 16]
  python render.py <工程> --motion 8.2 10.6 [帧数]
  python render.py <工程> --clip 0 12 [名字]
  python render.py <工程> --events | --det | --serve
  python render.py --doctor                     只检查环境，不安装依赖

全片输出 renders/raw.mp4，片段输出 renders/<名字或_clip>.mp4。
设置 VK_CHROME_EXECUTABLE 可指定 Chrome/Chromium 可执行文件；默认使用本机 Chrome。
工程只需 index.html + film.js；共享引擎通过 /engine/ 挂载。
"""
import hashlib, http.server, importlib, io, json, math, os, random, shutil
import signal, subprocess, sys, tempfile, threading, time
from contextlib import contextmanager
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
FONT_FILES = ("NotoSerifSC-VF.ttf", "NotoSansSC-VF.ttf", "CormorantGaramond.ttf",
              "CormorantGaramond-Italic.ttf", "Lora.ttf", "Lora-Italic.ttf",
              "JetBrainsMono.ttf", "CourierPrime-Regular.ttf")
ENGINE_FILES = ("vk.js", "vk-kit.js", "three-canvas.js", "vendor/three.module.js",
                "vendor/three.core.js", "vendor/SVGLoader.js")

class PipelineError(RuntimeError):
    """可直接显示给命令行用户的流水线错误。"""

def require_module(name, package=None):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise PipelineError(f"缺少或无法加载 Python 依赖 {package or name}；请在当前 Python 环境安装 requirements.txt。原错误：{exc}") from exc

def require_ffmpeg():
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise PipelineError("找不到 ffmpeg；请安装并加入 PATH。截图、事件导出和确定性检查不需要 ffmpeg。")
    return ffmpeg

@contextmanager
def atomic_output(path):
    """同目录临时文件，完整成功后才替换已有输出。后缀保留给 ffmpeg/Pillow。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=path.suffix, dir=path.parent)
    os.close(fd)
    tmp = Path(name)
    try:
        yield tmp
        if not tmp.is_file() or tmp.stat().st_size == 0:
            raise PipelineError(f"未生成有效输出：{path}")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)

class Handler(http.server.SimpleHTTPRequestHandler):
    proj = None
    def translate_path(self, path):
        p = path.split("?", 1)[0].split("#", 1)[0]
        if p.startswith("/engine/"): return str(ENGINE / p[len("/engine/"):])
        return str(self.proj / p.lstrip("/")) if p != "/" else str(self.proj / "index.html")
    def do_GET(self):
        if self.path.startswith("/favicon"): self.send_response(204); self.end_headers(); return
        super().do_GET()
    def end_headers(self):
        self.send_header("Cache-Control", "no-store"); super().end_headers()
    def log_message(self, *a): pass

def serve(proj, port=0):
    h = type("H", (Handler,), {"proj": proj})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), h)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"

def check_cancel():
    cancel = os.environ.get("VK_RENDER_CANCEL_FILE")
    if cancel and Path(cancel).exists():
        raise PipelineError("另一分段失败或渲染已取消。")

def check_page(pg):
    errors = getattr(pg, "_vk_errors", [])
    if errors:
        raise PipelineError("页面执行失败：" + "；".join(errors[:5]))

def evaluate(pg, expression, *args):
    check_cancel()
    check_page(pg)
    try:
        result = pg.evaluate(expression, *args)
    except Exception as exc:
        raise PipelineError(f"页面调用失败（{expression[:80]}）：{exc}") from exc
    check_page(pg)
    return result

def open_page(p, url):
    check_cancel()
    options = {"args": ["--disable-lcd-text", "--run-all-compositor-stages-before-draw", "--force-color-profile=srgb"]}
    executable = os.environ.get("VK_CHROME_EXECUTABLE")
    if executable:
        if not Path(executable).is_file():
            raise PipelineError(f"VK_CHROME_EXECUTABLE 指向的文件不存在：{executable}")
        options["executable_path"] = executable
    else:
        options["channel"] = "chrome"
    try:
        browser = p.chromium.launch(**options)
    except Exception as exc:
        raise PipelineError(f"无法启动浏览器；请安装本机 Chrome，或设置 VK_CHROME_EXECUTABLE 指定可执行文件。原错误：{exc}") from exc
    try:
        pg = browser.new_page(viewport={"width": 1920, "height": 1080}, device_scale_factor=1)
        pg._vk_errors = []
        def console(message):
            if message.type == "error": pg._vk_errors.append(message.text)
            elif message.type == "warning": print("[page warning]", message.text, file=sys.stderr)
        pg.on("console", console)
        pg.on("pageerror", lambda error: pg._vk_errors.append(str(error)))
        pg.on("requestfailed", lambda request: pg._vk_errors.append(f"资源加载失败 {request.url}: {request.failure}"))
        response = pg.goto(url)
        if response is not None and not response.ok:
            raise PipelineError(f"页面加载失败：HTTP {response.status}，{url}")
        timeout = float(os.environ.get("VK_READY_TIMEOUT_MS", "180000"))
        if not math.isfinite(timeout) or timeout <= 0:
            raise PipelineError("VK_READY_TIMEOUT_MS 必须是正数。")
        deadline = time.monotonic() + timeout / 1000
        while True:
            state = evaluate(pg, "({ ready: window.READY === true, error: window.FILM_ERROR || null })")
            if state["error"]:
                raise PipelineError(f"影片初始化失败：{state['error']}")
            if state["ready"]: break
            if time.monotonic() >= deadline:
                raise PipelineError(f"页面 READY 等待超时（{timeout:g}ms）；检查 film.js、资源路径和字体。")
            pg.wait_for_timeout(min(100, timeout))
        check_page(pg)
        return browser, pg
    except BaseException as exc:
        browser.close()
        if isinstance(exc, (PipelineError, KeyboardInterrupt, SystemExit)): raise
        raise PipelineError(f"页面初始化失败：{exc}") from exc

def shot(pg, t):
    if not math.isfinite(t): raise PipelineError("截图时间必须是有限数值。")
    evaluate(pg, "t => window.seek(t)", t)
    try:
        result = pg.screenshot(type="png")
    except Exception as exc:
        raise PipelineError(f"截图失败（t={t:g}）：{exc}") from exc
    check_page(pg)
    return result

def with_page(proj, fn):
    sync_playwright = require_module("playwright.sync_api", "playwright").sync_playwright
    srv, url = serve(proj)
    try:
        with sync_playwright() as p:
            browser, pg = open_page(p, url)
            try:
                result = fn(pg)
                check_page(pg)
                return result
            finally: browser.close()
    finally:
        srv.shutdown()
        srv.server_close()

def timeline(pg):
    end, fps = evaluate(pg, "END"), evaluate(pg, "FPS")
    if not all(isinstance(v, (int, float)) and math.isfinite(v) and v > 0 for v in (end, fps)):
        raise PipelineError(f"END 和 FPS 必须是有限正数，得到 END={end!r}, FPS={fps!r}")
    return end, fps

def stills(proj, ts):
    def go(pg):
        for t in ts:
            with atomic_output(proj / f"review/s_{t:07.2f}.png") as tmp:
                tmp.write_bytes(shot(pg, t))
    with_page(proj, go)
    print("stills:", len(ts))

def sheet(proj, args, name="sheet"):
    require_module("PIL", "Pillow")
    from PIL import Image, ImageDraw, ImageFont
    def go(pg):
        end, _ = timeline(pg)
        count = int(args[0] if args else 16) if len(args) <= 1 else len(args)
        if count <= 0: raise PipelineError("拼图帧数必须大于 0。")
        ts = [float(x) for x in args] if len(args) > 1 else [round((i + .5) * end / count, 2) for i in range(count)]
        cols = 4 if len(ts) > 6 else 2 if len(ts) > 1 else 1; tw = 1920 // cols; th = tw * 9 // 16
        out = Image.new("RGB", (cols * tw, -(-len(ts) // cols) * th), (20, 20, 20)); d = ImageDraw.Draw(out)
        try: font = ImageFont.truetype(str(ENGINE / "fonts/JetBrainsMono.ttf"), 18)
        except OSError: font = ImageFont.load_default()
        for i, t in enumerate(ts):
            im = Image.open(io.BytesIO(shot(pg, t))).convert("RGB").resize((tw, th), Image.Resampling.LANCZOS)
            x, y = (i % cols) * tw, (i // cols) * th; out.paste(im, (x, y))
            d.rectangle([x, y + th - 24, x + 78, y + th], fill=(0, 0, 0)); d.text((x + 5, y + th - 22), f"{t:.2f}", font=font, fill=(255, 230, 0))
        path = proj / f"review/{name}.jpg"
        with atomic_output(path) as tmp: out.save(tmp, quality=90)
        print("sheet:", path, len(ts))
    with_page(proj, go)

def stop_process(proc, tree=False):
    """回收进程；也用于异常和 Ctrl+C，防止后台编码器继续工作。"""
    if proc.poll() is None:
        if tree:
            if os.name == "nt":
                # 仅针对本次创建的渲染进程树，避免强制退出时遗留 Chrome/ffmpeg。
                try:
                    subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                except OSError: pass
            else:
                try: os.killpg(proc.pid, signal.SIGTERM)
                except ProcessLookupError: pass
        if proc.poll() is None:
            try: proc.terminate()
            except ProcessLookupError: pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    else:
        proc.wait()

def frames(proj, out, a=0.0, b=None):
    ffmpeg = require_ffmpeg()
    def go(pg):
        end, fps = timeline(pg)
        bb = end if b is None else min(b, end)
        if not math.isfinite(a) or not math.isfinite(bb) or a < 0 or bb <= a:
            raise PipelineError(f"无效片段范围：{a} 到 {bb} 秒。")
        n0, n1 = round(a * fps), round(bb * fps)
        if n1 <= n0: raise PipelineError("片段不足一帧。")
        with atomic_output(out) as tmp, tempfile.TemporaryFile() as errors:
            ff = subprocess.Popen([ffmpeg, "-v", "error", "-y", "-f", "image2pipe", "-framerate", str(fps), "-i", "-",
                                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "14", "-preset", "medium", "-movflags", "+faststart", str(tmp)],
                                  stdin=subprocess.PIPE, stderr=errors)
            try:
                try:
                    for i in range(n0, n1):
                        ff.stdin.write(shot(pg, i / fps))
                        if (i - n0) % 150 == 0: print(f"  {i - n0}/{n1 - n0}", flush=True)
                    ff.stdin.close()
                except BrokenPipeError:
                    # 等待并读取真正的编码错误，避免仅显示 Broken pipe。
                    pass
                status = ff.wait()
                if status:
                    errors.seek(0)
                    detail = errors.read().decode("utf-8", errors="replace")[-4000:]
                    raise PipelineError(f"ffmpeg 编码失败（退出码 {status}）：{detail.strip()}")
            finally:
                stop_process(ff)
                if ff.stdin is not None and not ff.stdin.closed:
                    try: ff.stdin.close()
                    except BrokenPipeError: pass
    with_page(proj, go)
    print("done", out)

def wait_children(procs):
    pending = set(range(len(procs)))
    while pending:
        for i in list(pending):
            status = procs[i].poll()
            if status is not None:
                procs[i].wait()
                pending.remove(i)
                if status:
                    raise PipelineError(f"分段 {i + 1} 渲染失败（退出码 {status}）；未发布拼接结果。")
        if pending: time.sleep(.05)

def frames_parallel(proj, out, jobs):
    ffmpeg = require_ffmpeg()
    end, fps = with_page(proj, timeline)
    total = round(end * fps)
    if total < 1 or jobs < 1: raise PipelineError("片长至少一帧，jobs 必须大于 0。")
    jobs = min(jobs, total)
    cuts = [round(total * i / jobs) for i in range(jobs + 1)]
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".vk-parts-", dir=out.parent) as directory:
        directory = Path(directory)
        parts, procs = [], []
        cancel = directory / "cancel"
        child_env = dict(os.environ, VK_RENDER_CANCEL_FILE=str(cancel))
        process_options = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True})
        complete = False
        try:
            for i in range(jobs):
                part = directory / f"part{i:02d}.mp4"; parts.append(part)
                name = part.with_suffix("").relative_to(proj / "renders").as_posix()
                procs.append(subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(proj), "--clip", repr(cuts[i] / fps), repr(cuts[i + 1] / fps), name],
                                              stdout=subprocess.DEVNULL if i else None, env=child_env, **process_options))
            wait_children(procs)
            missing = [str(part) for part in parts if not part.is_file() or part.stat().st_size == 0]
            if missing: raise PipelineError("分段没有有效输出：" + "、".join(missing))
            listing = directory / "parts.txt"
            listing.write_text("".join("file '" + part.as_posix().replace("'", "'\\''") + "'\n" for part in parts), encoding="utf-8")
            with atomic_output(out) as tmp:
                subprocess.run([ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", "-movflags", "+faststart", str(tmp)], check=True)
            complete = True
        finally:
            if not complete: cancel.touch(exist_ok=True)
            for proc in procs:
                if not complete:
                    try: proc.wait(timeout=10)
                    except subprocess.TimeoutExpired: stop_process(proc, tree=True)
                else: stop_process(proc)
    print("done", out, f"{end:.2f}s", f"({jobs} 路并行)")

def events(proj):
    def go(pg):
        ev = evaluate(pg, "events()")
        meta = evaluate(pg, "({end: END, fps: FPS, meta: META})")
        timeline(pg)
        with atomic_output(proj / "audio/events.json") as tmp:
            tmp.write_text(json.dumps(dict(meta, events=ev), ensure_ascii=False), encoding="utf-8")
        print("events:", len(ev))
    with_page(proj, go)

def det(proj, n=12):
    def go(pg):
        end, _ = timeline(pg); r = random.Random(7)
        ts = [round(r.uniform(0, end), 3) for _ in range(n)]
        first = {t: hashlib.md5(shot(pg, t)).hexdigest() for t in ts}
        order = ts[:]; r.shuffle(order)
        bad = [t for t in order if hashlib.md5(shot(pg, t)).hexdigest() != first[t]]
        if bad: raise PipelineError(f"NOT deterministic at {bad} —— 检查跨帧状态和 Math.random()。")
        print("deterministic")
    with_page(proj, go)

def chrome_location():
    # Windows treats environment names without regard to case. Keep that behavior
    # when a launcher supplies a plain/sanitized environment as well.
    def env_value(*names):
        wanted = {name.casefold() for name in names}
        return next((value for key, value in os.environ.items() if key.casefold() in wanted and value), None)
    configured = env_value("VK_CHROME_EXECUTABLE")
    if configured: return Path(configured) if Path(configured).is_file() else None
    candidates = [shutil.which("google-chrome"), shutil.which("google-chrome-stable"),
                  "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    drive = env_value("SystemDrive")
    if not drive:
        drive = Path(env_value("SystemRoot", "windir") or sys.executable).anchor
    drive_root = Path(drive.rstrip("/\\") + "/") if drive else None
    profile = env_value("USERPROFILE")
    if not profile:
        try: profile = str(Path.home())
        except RuntimeError: profile = None
    bases = [env_value("ProgramW6432", "ProgramFiles"), env_value("ProgramFiles(x86)"), env_value("LocalAppData")]
    # Launchers sometimes omit these three variables; use the actual system drive
    # and user profile rather than assuming Windows lives on C:.
    if drive_root:
        bases.extend([str(drive_root / "Program Files"), str(drive_root / "Program Files (x86)")])
    if profile: bases.append(str(Path(profile) / "AppData/Local"))
    for base in bases:
        if base: candidates.append(str(Path(base) / "Google/Chrome/Application/chrome.exe"))
    return next((Path(path) for path in candidates if path and Path(path).is_file()), None)

def doctor():
    failed = False
    for module, package in (("playwright.sync_api", "playwright"), ("numpy", "numpy"), ("scipy", "scipy"), ("PIL", "Pillow")):
        try:
            loaded = require_module(module, package)
            print(f"[OK] {package} {getattr(loaded, '__version__', '')}")
        except PipelineError as exc:
            print(f"[缺失] {exc}"); failed = True
    chrome = chrome_location()
    print(f"[{'OK' if chrome else '缺失'}] Chrome: {chrome or '请安装本机 Chrome，或设置 VK_CHROME_EXECUTABLE'}")
    failed |= chrome is None
    try:
        ffmpeg = require_ffmpeg()
        result = subprocess.run([ffmpeg, "-version"], capture_output=True, text=True, check=True)
        print("[OK] " + result.stdout.splitlines()[0])
    except (PipelineError, OSError, subprocess.SubprocessError, IndexError) as exc:
        print(f"[缺失] ffmpeg: {exc}"); failed = True
    missing_engine = [name for name in ENGINE_FILES if not (ENGINE / name).is_file() or (ENGINE / name).stat().st_size == 0]
    print("[缺失] 引擎模块缺失或为空：" + "、".join(missing_engine) + "；请恢复完整仓库文件。" if missing_engine else "[OK] 引擎适配器和本地 Three.js 模块齐全")
    failed |= bool(missing_engine)
    missing = [name for name in FONT_FILES if not (ENGINE / "fonts" / name).is_file() or (ENGINE / "fonts" / name).stat().st_size < 1000]
    print("[缺失] 字体：" + "、".join(missing) + "；请运行 engine/get_fonts.py" if missing else "[OK] 字体齐全")
    failed |= bool(missing)
    print("自检未安装或修改任何依赖；Chrome 这里只检查路径，实际启动由渲染验证。")
    return int(failed)

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if "--help" in args or "-h" in args: print(__doc__); return 0
    if not args: print(__doc__); return 1
    try:
        if "--doctor" in args: return doctor()
        proj = Path(args[0]).resolve()
        if not (proj / "film.js").is_file(): raise PipelineError(f"{proj} 里没有 film.js")
        if not (proj / "index.html").is_file(): raise PipelineError(f"{proj} 里没有 index.html")
        if "--serve" in args:
            srv, url = serve(proj, 8765); print("预览:", url + "?play", "（Ctrl+C 结束）")
            try: threading.Event().wait()
            finally: srv.shutdown(); srv.server_close()
        elif "--stills" in args: stills(proj, [float(x) for x in args[args.index("--stills") + 1:]])
        elif "--sheet" in args: sheet(proj, args[args.index("--sheet") + 1:])
        elif "--motion" in args:
            i = args.index("--motion"); t0, t1 = float(args[i + 1]), float(args[i + 2]); n = int(args[i + 3]) if len(args) > i + 3 else 12
            if n < 2 or not all(math.isfinite(t) for t in (t0, t1)) or t1 < t0: raise PipelineError("--motion 需要有效时间范围和至少 2 帧。")
            sheet(proj, [repr(round(t0 + (t1 - t0) * k / (n - 1), 3)) for k in range(n)], f"motion_{t0:g}-{t1:g}")
        elif "--clip" in args:
            i = args.index("--clip"); name = args[i + 3] if len(args) > i + 3 else "_clip"
            output = (proj / "renders" / f"{name}.mp4").resolve()
            if not output.is_relative_to(proj / "renders"): raise PipelineError("片段名字必须位于 renders 目录内。")
            frames(proj, output, float(args[i + 1]), float(args[i + 2]))
        elif "--events" in args: events(proj)
        elif "--det" in args: det(proj)
        elif "--jobs" in args:
            jobs = int(args[args.index("--jobs") + 1])
            if jobs < 1: raise PipelineError("--jobs 必须大于 0。")
            if jobs == 1: frames(proj, proj / "renders/raw.mp4")
            else: frames_parallel(proj, proj / "renders/raw.mp4", jobs)
        else: frames(proj, proj / "renders/raw.mp4")
        return 0
    except KeyboardInterrupt:
        print("已中止，未完成输出已清理。", file=sys.stderr); return 130
    except (PipelineError, ValueError, IndexError, OSError, subprocess.SubprocessError) as exc:
        print(f"错误：{exc}", file=sys.stderr); return 1

if __name__ == "__main__":
    sys.exit(main())
