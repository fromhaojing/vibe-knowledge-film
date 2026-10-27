# -*- coding: utf-8 -*-
"""按画面事件表合成配乐和音效，再和画面合成成片。
  python audio.py <工程目录>                       # 读 audio/events.json → audio/score.wav → renders/final.mp4
  python audio.py <工程目录> --bgm 曲子.mp3 [-8]   # 用现成配乐垫底（默认 -8 dB），事件音照样叠上去
  python audio.py <工程目录> --wav-only            # 只出 wav，不合成

事件表由 render.py --events 导出：film.js 里每个 fr.sfx(时刻, 名字, 参数) 就是一条。
声音的写法学自参考片（C 家族）：
  低频长音垫底 · 每章开头一记带泛音的钟/垫和弦（约 8 秒衰减）· 屏幕上每打一个字一声"嗒" ·
  提问处一个上滑音 · 说到噪声就真的铺噪声 · 定理落地的那一下之后留 2–3 秒彻底静音（hush）。
事件名：tick / soft / chord / bloom / rise / thud / tock / stamp / shimmer / hush（参数 dur，秒）
META（film.js 的 meta）：{ root: 半音偏移, noise: [[起,止,强度0..1],...], silence: [[起,止],...], drone: 0..1 }
"""
import json, math, subprocess, sys
from pathlib import Path
if __package__:
    from .render import PipelineError, atomic_output, require_ffmpeg, require_module
else:
    from render import PipelineError, atomic_output, require_ffmpeg, require_module
try:
    np = require_module("numpy")
    signal = require_module("scipy.signal", "scipy")
except PipelineError as exc:
    if __name__ == "__main__": sys.exit(str(exc))
    raise
fftconvolve, lfilter, butter = signal.fftconvolve, signal.lfilter, signal.butter

SR = 48000
D3 = 146.83
PENTA = [0, 2, 4, 7, 9, 12, 14, 16, 19, 21]           # 大调五声，嗒声从这里取音高
CHORD = [0, 7, 12, 14, 19, 24, 26]                   # 根音、五度、八度、九度…… 叠成"开阔"的和弦

def hz(semi, base=D3): return base * 2 ** (semi / 12)
def env_exp(n, tau, attack=0.004):
    t = np.arange(n) / SR
    return np.minimum(1, t / attack) * np.exp(-t / tau)
def lowpass(x, fc, order=2):
    b, a = butter(order, fc / (SR / 2), "low"); return lfilter(b, a, x, axis=0)
def highpass(x, fc, order=2):
    b, a = butter(order, fc / (SR / 2), "high"); return lfilter(b, a, x, axis=0)
def pan(x, p):                                        # p: -1 左 … 1 右
    l, r = np.cos((p + 1) * np.pi / 4), np.sin((p + 1) * np.pi / 4); return np.stack([x * l, x * r], 1)
def add(buf, x, t):
    i = int(t * SR)
    if i >= len(buf) or i < 0: return
    n = min(len(x), len(buf) - i); buf[i:i + n] += x[:n]

def tone(f, dur, tau, partials=((1, 1.0),), attack=0.004, vib=0.0):
    n = int(dur * SR); t = np.arange(n) / SR; out = np.zeros(n)
    for mult, amp in partials:
        ph = 2 * np.pi * f * mult * t + (vib * np.sin(2 * np.pi * 4.3 * t) if vib else 0)
        out += amp * np.sin(ph) * np.exp(-t / (tau / (1 + 0.35 * (mult - 1))))   # 高次泛音衰减更快
    return out * np.minimum(1, t / attack)

def ev_tick(rng, p):
    f = hz(PENTA[int(p.get("pitch", 0)) % len(PENTA)] + 24)
    x = tone(f, .5, .09, ((1, 1), (2.01, .28), (3.02, .1)), attack=.002)
    click = highpass(rng.standard_normal(int(.012 * SR)) * env_exp(int(.012 * SR), .003), 3000) * .25
    x[:len(click)] += click
    return pan(x * .16 * p.get("gain", 1), rng.uniform(-.35, .35))
def ev_soft(rng, p):
    return pan(tone(hz(12 + 7), 2.2, .7, ((1, 1), (2, .2)), attack=.03) * .12 * p.get("gain", 1), 0)
def ev_chord(rng, p):
    root = p.get("root", 0); n = int(9 * SR); out = np.zeros((n, 2))
    for k, semi in enumerate(CHORD):
        f = hz(root + semi); x = tone(f, 9, 2.6 - k * .12, ((1, 1), (2.003, .32), (3.01, .14), (4.02, .06)), attack=.012, vib=.6)
        out += pan(x * (.11 / (1 + k * .22)), (k % 3 - 1) * .5)
    sub = tone(hz(root - 12), 6, 2.2, ((1, 1),), attack=.02)
    out[:len(sub)] += pan(sub * .16, 0)
    return out * p.get("gain", 1)
def ev_bloom(rng, p):                                 # 闪白：和弦 + 一口气的噪声扫过
    out = ev_chord(rng, {"root": p.get("root", 0), "gain": 1.15 * p.get("gain", 1)})
    n = int(1.6 * SR); ns = rng.standard_normal((n, 2)) * env_exp(n, .35, .01)[:, None]
    out[:n] += lowpass(highpass(ns, 500), 7000) * .12
    return out
def ev_rise(rng, p):                                  # 上滑音：提问、蓄势
    dur = p.get("dur", 1.0); n = int(dur * SR); t = np.arange(n) / SR
    f = hz(7) * 2 ** (t / dur * 1.0); ph = 2 * np.pi * np.cumsum(f) / SR
    e = np.sin(np.pi * np.minimum(1, t / dur) ** 1.6) ** 1.2
    ns = lowpass(rng.standard_normal(n), 2500) * (t / dur) ** 2 * .22
    return pan((np.sin(ph) * .1 + ns * .1) * e * p.get("gain", 1), 0)
def ev_thud(rng, p):
    n = int(.6 * SR); t = np.arange(n) / SR; f = 95 * np.exp(-t * 9) + 48
    x = np.sin(2 * np.pi * np.cumsum(f) / SR) * env_exp(n, .13, .002) + lowpass(rng.standard_normal(n), 600) * env_exp(n, .04) * .5
    return pan(x * .42 * p.get("gain", 1), 0)
def ev_tock(rng, p):
    f = 520 * 2 ** (int(p.get("pitch", 0)) * 2 / 12); n = int(.25 * SR)
    x = tone(f, .25, .04, ((1, 1), (2.7, .4), (5.1, .15)), attack=.001) + highpass(rng.standard_normal(n), 2500) * env_exp(n, .006) * .3
    return pan(x * .2 * p.get("gain", 1), rng.uniform(-.5, .5))
def ev_stamp(rng, p):
    n = int(.5 * SR); x = ev_thud(rng, {"gain": 1.1})[:n, 0] + highpass(rng.standard_normal(n), 1800) * env_exp(n, .02) * .35
    return pan(x * p.get("gain", 1), 0)
def ev_shimmer(rng, p):
    n = int(2.4 * SR); t = np.arange(n) / SR; out = np.zeros(n)
    for k in range(7): out += np.sin(2 * np.pi * hz(24 + PENTA[k + 2]) * t + rng.uniform(0, 6)) * np.exp(-((t - .25 - k * .06) / .5) ** 2)
    return pan(out * .035 * p.get("gain", 1), 0)
EV = dict(tick=ev_tick, soft=ev_soft, chord=ev_chord, bloom=ev_bloom, rise=ev_rise, thud=ev_thud, tock=ev_tock, stamp=ev_stamp, shimmer=ev_shimmer)

def reverb(x, rng, t60=3.6, wet=.42):
    n = int(t60 * SR); t = np.arange(n) / SR
    ir = lowpass(rng.standard_normal((n, 2)) * np.exp(-6.9 * t / t60)[:, None], 5200); ir[:int(.012 * SR)] *= np.linspace(0, 1, int(.012 * SR))[:, None]
    ir /= np.sqrt((ir ** 2).sum(0)).max()
    wetsig = np.stack([fftconvolve(x[:, c], ir[:, c])[:len(x)] for c in (0, 1)], 1)
    return x + wetsig * wet

def silence_windows(spec):
    windows = list((spec.get("meta") or {}).get("silence", []))
    windows += [(when, when + params.get("dur", 2.5))
                for when, name, params in spec["events"] if name == "hush"]
    for a, b in windows:
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in (a, b)) or b < a:
            raise PipelineError(f"无效静音区间：{a!r}, {b!r}")
    return windows

def audio_envelope(spec, t):
    """静音前 0.15s 收掉、结束后 0.4s 恢复，保留全片淡入淡出。"""
    gain = np.ones_like(t)
    for a, b in silence_windows(spec):
        gain *= 1 - np.clip((t - a) / .15, 0, 1) * (1 - np.clip((t - b) / .4, 0, 1))
    gain *= np.clip(t / .6, 0, 1) * np.clip((spec["end"] - t) / 1.2, 0, 1)
    return gain

def envelope_filter(spec):
    # aeval 按采样计算；在最终混音与 loudnorm 后使用，BGM 也能彻底静音。
    end = spec["end"]
    terms = ["clip(t/0.6,0,1)", f"clip(({end:.12g}-t)/1.2,0,1)"]
    for a, b in silence_windows(spec):
        terms.append(f"(1-clip((t-({a:.12g}))/0.15,0,1)*(1-clip((t-({b:.12g}))/0.4,0,1)))")
    gain = "*".join(terms)
    return f"aeval=exprs='val(0)*({gain})|val(1)*({gain})':c=stereo"

def mix_filter(spec, bgm_db=-8):
    end = spec["end"]
    fade = min(1.5, end)
    return (f"[2:a]atrim=0:{end},volume={bgm_db}dB,afade=t=in:d=0.4,"
            f"afade=t=out:st={max(0, end - fade)}:d={fade}[b];"
            "[1:a][b]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,"
            + envelope_filter(spec) + "[a]")

def synth(spec, bgm=False, apply_envelope=True):
    end = spec["end"]; meta = spec.get("meta") or {}; n = int((end + .05) * SR); rng = np.random.default_rng(20261006)
    dry = np.zeros((n, 2)); t = np.arange(n) / SR; root = meta.get("root", 0)
    for when, name, p in spec["events"]:
        if name in EV: add(dry, EV[name](rng, dict(p, root=p.get("root", 0) + root) if name in ("chord", "bloom") else p), when)
    out = reverb(dry, rng)
    if not bgm:                                       # 低频长音垫底：两个略微失谐的正弦 + 很慢的呼吸
        lv = .05 * meta.get("drone", 1)
        d = (np.sin(2 * np.pi * hz(root - 24) * t) + .6 * np.sin(2 * np.pi * hz(root - 24 + .08) * 2 * t) + .25 * np.sin(2 * np.pi * hz(root - 12 + 7) * t)) * (.75 + .25 * np.sin(2 * np.pi * t / 11))
        air = lowpass(highpass(rng.standard_normal(n), 300), 1800) * .012 * (.6 + .4 * np.sin(2 * np.pi * t / 17))
        out += np.stack([d * lv + air, d * lv + np.roll(air, 4000)], 1)
    for a, b, k in meta.get("noise", []):             # 文案说到噪声，配乐里就真的有噪声
        g = np.clip((t - a) / max(.01, b - a), 0, 1) ** 1.5 * (t <= b) * k
        out += lowpass(highpass(rng.standard_normal((n, 2)), 200), 6000) * (g * .12)[:, None]
    if apply_envelope:
        out *= audio_envelope(spec, t)[:, None]
    return out

def write_wav(path, x):
    import wave
    x = np.clip(x, -1, 1); pcm = (x * 32767).astype("<i2")
    with atomic_output(path) as tmp:
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes(pcm.tobytes())

def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args: print(__doc__); return 1
    try:
        proj = Path(args[0]).resolve()
        spec = json.loads((proj / "audio/events.json").read_text(encoding="utf-8"))
        end = spec["end"]
        if not isinstance(end, (int, float)) or not math.isfinite(end) or end <= 0:
            raise PipelineError("事件表 end 必须是有限正数。")
        silence_windows(spec)
        bgm = args[args.index("--bgm") + 1] if "--bgm" in args else None
        bgm_db = -8.0
        if bgm:
            if not Path(bgm).is_file(): raise PipelineError(f"BGM 文件不存在：{bgm}")
            pos = args.index("--bgm") + 2
            if len(args) > pos and args[pos] != "--wav-only": bgm_db = float(args[pos])
            if not math.isfinite(bgm_db): raise PipelineError("BGM 音量必须是有限数值。")
        wav_only = "--wav-only" in args
        raw, out = proj / "renders/raw.mp4", proj / "renders/final.mp4"
        if not wav_only:
            ffmpeg = require_ffmpeg()
            if not raw.is_file(): raise PipelineError(f"缺少无声视频：{raw}；请先运行 render.py。")
        # 外部 BGM 模式在最终混音后统一施加包络，防止事件音重复淡入淡出。
        x = synth(spec, bgm=bool(bgm), apply_envelope=not bgm or wav_only)
        pk = np.abs(x).max() or 1
        x = x / pk * 10 ** (-3 / 20)
        wav = proj / "audio/score.wav"
        write_wav(wav, x)
        print("score:", wav, f"{len(x) / SR:.1f}s", len(spec["events"]), "events")
        if wav_only: return 0
        if bgm:
            cmd = [ffmpeg, "-v", "error", "-y", "-i", str(raw), "-i", str(wav), "-stream_loop", "-1", "-i", bgm,
                   "-filter_complex", mix_filter(spec, bgm_db)]
        else:
            cmd = [ffmpeg, "-v", "error", "-y", "-i", str(raw), "-i", str(wav),
                   "-filter_complex", "[1:a]loudnorm=I=-18:TP=-1.5:LRA=14[a]"]
        with atomic_output(out) as tmp:
            subprocess.run(cmd + ["-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", str(tmp)], check=True)
        print("done", out)
        return 0
    except KeyboardInterrupt:
        print("已中止，未完成输出已清理。", file=sys.stderr); return 130
    except (PipelineError, ValueError, TypeError, KeyError, IndexError, OSError, subprocess.SubprocessError) as exc:
        print(f"错误：{exc}", file=sys.stderr); return 1

if __name__ == "__main__":
    sys.exit(main())
