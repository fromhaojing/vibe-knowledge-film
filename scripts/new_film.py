# -*- coding: utf-8 -*-
"""建一个新片工程：
  python new_film.py <工程目录> --world C|B [--force]
C 夜曲（抽象概念、看不见的机制）· B 寓言（心理和行为机制）。怎么选见 references/worlds.md。

工程里是 ES module index.html 和一份 Three.js film.js 骨架——里面一行画面都没有。
文案不同，屏上的东西就不同，代码也不同：每一镜照 storyboard.md 现写，不要从别的片子里搬画面。
引擎留在 skill 目录里，由 engine/render.py 挂载。"""
import argparse, json, math, shutil, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORLD = {   # 外观名、theme、字幕样式、色板、这套外观的常驻元素（都在 vk-kit.js，用法见 references/engine.md）
    "B": ("B 寓言", "flat", "flat", "flat", "仪表 K.gauge、片名卡 K.titleGilt；场景自己画进 fr.look.under"),
    "C": ("C 夜曲", "night", "night", "night", "章节标 K.chapterMark、片名卡 K.titleNight；字幕带一行英文（en）"),
}
SKELETON = """/* ★ 片名 · {name}
 * 这是骨架，一行画面都没有。每一镜照 storyboard.md 现写——文案不同，屏上的东西就不同。
 * 每个场景的函数头上先写一行：这是什么（日常的词）/ 它在干什么（一个动词）/ 观众明白了什么。
 * 事实和出处、哪些是示意，写在这段注释里。
 * 这套外观的常驻元素：{standing}。规格见 references/worlds.md。 */
(function () {{
'use strict';
const {{ W, H, clamp, lerp, seg, smooth, ss, E, fade, hash, rng, rgba, mix }} = VK;
const K = VKit, P = K.PAL.{pal};

const T = {{ end: {duration} }};                                   // 关键时刻集中写在这里，挪动时只改一处
const SUBS = [                                             // 一句字幕一行，和分镜表对着写；{{词}} 金色，{{!词}} 红色
  // {{ a: 0.8, b: 4.2, zh: '……'{en} }},
];

const EVENTS = [ // 独立事件；使用此数组时不要同时在 draw 中登记 fr.sfx
  // {{ t: 1.2, name: 'tick', params: {{ gain: 0.5 }} }},
];

/* 一个场景一个函数，自己管自己的进场和退场。 */
function scene1(fr, t) {{
}}

VK.film({{
  dur: T.end, fps: {fps}, theme: '{theme}', meta: {{ title: {title} }},
  events: EVENTS,
  draw(fr, t) {{
    scene1(fr, t);
    K.subs(fr, t, SUBS, '{subs}');                         // 字幕永远最后画，压在一切之上
  }},
}});
}})();
"""

def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('project', type=Path)
    parser.add_argument('--world', type=str.upper, choices=WORLD, default='C')
    parser.add_argument('--title', default='')
    parser.add_argument('--duration', type=float, default=30.0)
    parser.add_argument('--fps', type=int, default=30)
    parser.add_argument('--force', action='store_true', help='Replace only index.html and film.js')
    args = parser.parse_args(argv)
    if not math.isfinite(args.duration) or args.duration <= 0:
        parser.error('--duration must be a positive finite number')
    if not 1 <= args.fps <= 240:
        parser.error('--fps must be between 1 and 240')
    proj = args.project.resolve()
    existing = [p for p in (proj / 'index.html', proj / 'film.js') if p.exists()]
    if existing and not args.force:
        parser.error('Already exists: ' + ', '.join(str(p) for p in existing) + '; use --force to replace')
    name, theme, subs, pal, standing = WORLD[args.world]
    source = SKELETON.format(name=name, theme=theme, subs=subs, pal=pal, standing=standing,
        en=", en: '……'" if args.world == 'C' else '', duration=repr(args.duration), fps=args.fps,
        title=json.dumps(args.title, ensure_ascii=False))
    proj.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'engine/index.html', proj / 'index.html')
    (proj / 'film.js').write_text(source, encoding='utf-8', newline='\n')
    render = ROOT / 'engine/render.py'
    print(f'建好了：{proj}（{name}，Three.js）\n'
          f'  自检  python "{render}" --doctor\n'
          f'  预览  python "{render}" "{proj}" --serve\n'
          f'  拼图  python "{render}" "{proj}" --sheet 16\n'
          '下一步：照分镜表填写字幕、事件和场景；骨架没有预制画面。')


if __name__ == '__main__':
    main()
