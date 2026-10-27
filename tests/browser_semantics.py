#!/usr/bin/env python3
"""Repeatable WebGL drawing-bridge semantics checks; no package installation.

Run: python tests/browser_semantics.py
Optional: --browser-executable PATH --artifacts-dir PATH --stress-frames 12
Set VK_BROWSER_EXECUTABLE to an existing Chromium executable, or let Playwright
use an installed browser. VK_SOFTWARE_WEBGL=0 allows the system GPU instead of
SwiftShader. No output files are written unless --artifacts-dir is supplied.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[1]


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def log_message(self, *_args):
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/__bridge_semantics__":
            body = b'<!doctype html><meta charset="utf-8"><title>GPU semantics</title><canvas id="stage"></canvas>'
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    def guess_type(self, path):
        if str(path).endswith(".js"):
            return "text/javascript"
        return super().guess_type(path)


def existing_browser(explicit: str | None) -> str | None:
    if explicit:
        candidate = Path(explicit)
        if not candidate.is_file():
            raise SystemExit("Browser executable does not exist: " + explicit)
        return str(candidate)
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        candidate = shutil.which(name)
        if candidate:
            return candidate
    directories = [os.environ.get(name) for name in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
    if os.name == "nt":
        # Some app launchers expose a reduced environment without PROGRAMFILES.
        drive = os.environ.get("SystemDrive", "C:")
        directories += [drive + "/Program Files", drive + "/Program Files (x86)"]
    for directory in directories:
        if not directory:
            continue
        for relative in ("Google/Chrome/Application/chrome.exe", "Microsoft/Edge/Application/msedge.exe"):
            candidate = Path(directory) / relative
            if candidate.is_file():
                return str(candidate)
    return None


CHECKS = r"""async ({stressFrames}) => {
  const {createSurface, createRenderer, parsePath} = await import('/engine/three-canvas.js');
  const THREE = await import('/engine/vendor/three.module.js');
  const width=640, height=360, stage=document.querySelector('#stage');
  const contexts=[], originalGetContext=stage.getContext.bind(stage);
  stage.getContext=(kind, options)=>{contexts.push(kind);return originalGetContext(kind,options);};
  const renderer=createRenderer(stage,width,height), gl=renderer.three.getContext();
  function check(ok, message) { if(!ok)throw new Error(message); }
  function pixel(x,y) { const p=new Uint8Array(4);gl.readPixels(x,height-y-1,1,1,gl.RGBA,gl.UNSIGNED_BYTE,p);return Array.from(p); }
  function near(actual,expected,tolerance=3) { return expected.every((v,i)=>Math.abs(actual[i]-v)<=tolerance); }
  function hashFrame() { const data=new Uint8Array(width*height*4);gl.readPixels(0,0,width,height,gl.RGBA,gl.UNSIGNED_BYTE,data);let h=2166136261;for(const b of data)h=Math.imul(h^b,16777619);return h>>>0; }
  function memory() { return {...renderer.info.memory}; }
  const results={backend:gl.getParameter(gl.VERSION),checks:[]};
  check(gl instanceof WebGL2RenderingContext,'Stage must use a real WebGL2 context');
  check(!contexts.includes('2d'),'Stage must never request Canvas2D');

  const surface=createSurface(width,height), x=surface.context;
  x.fillStyle='#101020';x.fillRect(0,0,width,height);
  x.fillStyle='#ff0000';x.fillRect(20,20,80,60);
  const gradient=x.createLinearGradient(120,0,300,0);gradient.addColorStop(0,'#00ff00');gradient.addColorStop(1,'#0000ff');x.fillStyle=gradient;x.fillRect(120,20,180,60);
  x.fillStyle='#ffff00';x.beginPath();x.arc(370,70,45,0,Math.PI*2);x.moveTo(390,70);x.arc(370,70,20,0,Math.PI*2,true);x.fill();
  x.strokeStyle='#ffffff';x.lineWidth=9;x.beginPath();x.moveTo(30,115);x.lineTo(300,115);x.stroke();
  x.setLineDash([12,8]);x.beginPath();x.moveTo(30,140);x.lineTo(300,140);x.stroke();x.setLineDash([]);
  x.font='30px sans-serif';x.textBaseline='alphabetic';x.fillStyle='#ffffff';x.fillText('GPU 中文',20,190);
  const layer=createSurface(width,height);layer.context.fillStyle='rgba(255,0,255,.5)';layer.context.fillRect(20,230,120,60);x.drawImage(layer,0,0);
  layer.context.reset();layer.context.fillStyle='#00ff00';layer.context.fillRect(300,230,80,60);x.drawImage(layer,0,0);
  x.fillStyle='#ffdd00';x.fill(parsePath('M 440 180 L 520 180 L 520 260 L 440 260 Z M 460 200 L 460 240 L 500 240 L 500 200 Z'));
  x.save();x.beginPath();x.rect(480,20,40,80);x.clip();x.fillStyle='#0000ff';x.fillRect(450,0,100,120);x.restore();
  renderer.render(surface);
  check(near(pixel(50,50),[255,0,0]),'Solid sRGB color changed');
  check(near(pixel(600,300),[16,16,32]),'Dark sRGB color lost precision in intermediate targets');
  const green=pixel(125,50), blue=pixel(295,50);check(green[1]>240&&green[2]<80&&blue[2]>240&&blue[1]<80,'Linear gradient endpoints are incorrect');
  check(near(pixel(370,70),[16,16,32])&&near(pixel(400,70),[255,255,0]),'Opposite-winding arc must cut a hole');
  check(near(pixel(480,220),[16,16,32])&&near(pixel(445,220),[255,221,0]),'SVG compound-path hole must remain transparent');
  check(near(pixel(50,115),[255,255,255])&&near(pixel(50,109),[16,16,32]),'Wide stroke thickness must exceed the native one-pixel WebGL line');
  check(near(pixel(35,140),[255,255,255])&&near(pixel(46,140),[16,16,32]),'Stroke dash pattern is incorrect');
  const translucent=pixel(60,245);check(translucent[0]>170&&translucent[0]<200&&translucent[1]<30&&translucent[2]>170&&translucent[2]<200,'Render-target alpha was multiplied twice');
  check(near(pixel(330,245),[0,255,0]),'Reused source surface changed an earlier drawImage snapshot');
  check(near(pixel(500,50),[0,0,255])&&near(pixel(460,50),[16,16,32]),'Saved clip region leaked or was ignored');
  const glyphPixels=new Uint8Array(230*50*4);gl.readPixels(10,height-200,230,50,gl.RGBA,gl.UNSIGNED_BYTE,glyphPixels);let ink=0;for(let i=0;i<glyphPixels.length;i+=4)if(glyphPixels[i]>100&&glyphPixels[i+1]>100&&glyphPixels[i+2]>100)ink++;
  check(ink>100,'Text glyph masks did not produce visible GPU geometry');
  check(gl.getError()===gl.NO_ERROR,'WebGL error during basic drawing semantics');
  results.checks.push('sRGB colors','gradients','arc and SVG holes','wide and dashed strokes','glyph masks','clip save/restore','premultiplied layer alpha','drawImage snapshot reuse');
  results.pixels={solid:pixel(50,50),background:pixel(600,300),gradientStart:green,gradientEnd:blue,translucentLayer:translucent};


  // Dice pips use radii around .155 and are enlarged by a face's affine matrix.
  // Sampling in local units produced triangles/diamonds before this regression check.
  const affine=createSurface(width,height), ax=affine.context, matrix=[180,65,-45,140,180,110], rotation=.4, rx=.155, ry=.11;
  ax.setTransform(...matrix);ax.fillStyle='#ffffff';ax.beginPath();ax.ellipse(0,0,rx,ry,rotation,0,Math.PI*2);ax.fill();renderer.render(affine);
  let affineInside=0,affineOutside=0;
  for(let i=0;i<32;i++){
    const angle=i/32*Math.PI*2;
    function ellipsePixel(rho){const xx=rx*Math.cos(angle)*rho,yy=ry*Math.sin(angle)*rho,x=xx*Math.cos(rotation)-yy*Math.sin(rotation),y=xx*Math.sin(rotation)+yy*Math.cos(rotation);return pixel(Math.round(matrix[0]*x+matrix[2]*y+matrix[4]),Math.round(matrix[1]*x+matrix[3]*y+matrix[5]));}
    if(ellipsePixel(.85)[0]>240)affineInside++;if(ellipsePixel(1.2)[0]<10)affineOutside++;
  }
  check(affineInside===32&&affineOutside===32,'A tiny local ellipse enlarged by an affine matrix must remain round, with subpixel tessellation error');
  results.checks.push('screen-space affine ellipse tessellation');results.affineEllipse={insideSamples:affineInside,outsideSamples:affineOutside};

  // An isolated I should have one smooth Gaussian glow, not translated letter copies.
  const glow=createSurface(width,height), gx=glow.context;gx.font='80px Arial, sans-serif';gx.textBaseline='alphabetic';gx.fillStyle='transparent';gx.shadowColor='#ffffff';gx.shadowBlur=12;gx.fillText('I',100,180);renderer.render(glow);
  const rawProfile=[];for(let xx=50;xx<=180;xx++)rawProfile.push(pixel(xx,150)[0]);
  const profile=rawProfile.map((_,i)=>{let sum=0,n=0;for(let k=-2;k<=2;k++)if(i+k>=0&&i+k<rawProfile.length){sum+=rawProfile[i+k];n++;}return sum/n;});
  const peak=profile.indexOf(Math.max(...profile));let backstep=0;for(let i=1;i<=peak;i++)backstep=Math.max(backstep,profile[i-1]-profile[i]);for(let i=peak+1;i<profile.length;i++)backstep=Math.max(backstep,profile[i]-profile[i-1]);
  check(profile[peak]>20&&backstep<4,'Glyph glow has secondary outlines instead of a single dense Gaussian lobe');
  results.checks.push('single-lobe GPU glyph glow');results.glyphGlow={peak:profile[peak],largestSecondaryRise:backstep};

  const bg=createSurface(width,height), under=createSurface(width,height), content=createSurface(width,height), post=createSurface(width,height);
  bg.context.fillStyle='#101020';bg.context.fillRect(0,0,width,height);
  under.context.fillStyle='#ffff00';under.context.fillRect(20,20,80,80);
  content.context.fillStyle='#ff0000';content.context.fillRect(20,20,80,80);content.context.effect('sepia',{k:1});
  content.context.fillStyle='#00ff00';content.context.fillRect(120,20,80,80);
  const scene=new THREE.Scene(), camera=new THREE.OrthographicCamera(0,width,0,height,.1,1000);camera.position.z=100;
  const geometry=new THREE.BoxGeometry(60,60,60), material=new THREE.MeshBasicMaterial({color:'#ff00ff'}), box=new THREE.Mesh(geometry,material);box.position.set(400,70,0);scene.add(box);
  post.context.fillStyle='#00ffff';post.context.fillRect(400,60,25,20);
  const composition={background:bg,under,content,post,scene3d:{scene,camera},bloom:0,grain:0,frame:0};renderer.compose(composition);
  const sepia=pixel(50,50);check(sepia[1]>60&&sepia[2]>40,'Sepia effect did not alter preceding drawing commands');
  check(near(pixel(150,50),[0,255,0]),'Sepia effect tinted commands drawn afterwards');
  check(near(pixel(380,70),[255,0,255]),'Native Three.js scene was not composed between under and content');
  check(near(pixel(410,70),[0,255,255]),'Post surface did not draw above the native scene');
  results.checks.push('GPU sepia command ordering','native Three.js scene','post composition ordering');

  const blurred=createSurface(width,height);blurred.context.filter='blur(6px)';blurred.context.fillStyle='#ff0000';blurred.context.fillRect(20,20,60,60);renderer.render(blurred);
  const blurCentre=pixel(50,50),blurEdge=pixel(16,50);check(blurCentre[0]>240&&blurEdge[0]>20&&blurEdge[0]<220,'Vector path blur must be a GPU filter with visible falloff');
  results.checks.push('GPU vector blur');

  composition.bloom=.5;composition.grain=.05;composition.frame=17;renderer.compose(composition);const firstHash=hashFrame(),before=memory();renderer.compose(composition);check(hashFrame()===firstHash,'Repeated seek/frame must be deterministic');
  for(let i=0;i<stressFrames;i++){composition.frame=i;renderer.compose(composition);}
  const after=memory();check(after.geometries===before.geometries&&after.textures===before.textures,'GPU geometries or textures grow across repeated frames');
  check(gl.getError()===gl.NO_ERROR,'WebGL error after repeated GPU composition');
  results.checks.push('deterministic frame output','stable GPU resource counts','subtle multiplicative grain and GPU bloom');
  results.resources={before,after,stressFrames};results.frameHash=firstHash;results.contextRequests=contexts;results.calls=renderer.info.render.calls;
  window.__semanticsRenderer=renderer;window.__semanticsNativeResources={geometry,material};return results;
}"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable", default=os.environ.get("VK_BROWSER_EXECUTABLE") or os.environ.get("VK_CHROME_EXECUTABLE"))
    parser.add_argument("--artifacts-dir", type=Path)
    parser.add_argument("--stress-frames", type=int, default=12)
    args = parser.parse_args()
    if args.stress_frames < 0:
        parser.error("--stress-frames must be non-negative")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit("Python Playwright is required in the selected environment; this test does not install dependencies.") from exc

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as playwright:
            launch = {"headless": True, "args": ["--enable-webgl", "--no-sandbox"]}
            executable = existing_browser(args.browser_executable)
            if executable:
                launch["executable_path"] = executable
            if os.environ.get("VK_SOFTWARE_WEBGL", "1") != "0":
                launch["args"] += ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]
            browser = playwright.chromium.launch(**launch)
            try:
                page = browser.new_page(viewport={"width": 640, "height": 360}, device_scale_factor=1)
                page.set_default_timeout(90000)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
                page.goto("http://127.0.0.1:" + str(server.server_port) + "/__bridge_semantics__")
                result = page.evaluate("(" + CHECKS + ")(" + json.dumps({"stressFrames": args.stress_frames}) + ")")
                if errors:
                    raise AssertionError("Browser errors: " + " | ".join(errors))
                if args.artifacts_dir:
                    args.artifacts_dir.mkdir(parents=True, exist_ok=True)
                    page.screenshot(path=str(args.artifacts_dir / "gpu-semantics.png"))
                    (args.artifacts_dir / "gpu-semantics.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
                page.evaluate("() => { const r=window.__semanticsNativeResources; r.geometry.dispose(); r.material.dispose(); window.__semanticsRenderer.dispose(); }")
                print(json.dumps(result, indent=2, ensure_ascii=False))
                print("PASS: WebGL drawing semantics")
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
