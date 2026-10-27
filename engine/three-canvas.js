/**
 * Three.js drawing-command bridge. Shapes, strokes, gradients, layers and effects
 * are GPU geometry/shaders. Canvas2D is used only to measure/rasterize text glyphs.
 */
import * as THREE from './vendor/three.module.js';
import { SVGLoader } from './vendor/SVGLoader.js';

const TAU = Math.PI * 2;
const IDENTITY = [1, 0, 0, 1, 0, 0];
const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
const point = (m, x, y) => [m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5]];
const multiply = (a, b) => [a[0]*b[0]+a[2]*b[1],a[1]*b[0]+a[3]*b[1],a[0]*b[2]+a[2]*b[3],a[1]*b[2]+a[3]*b[3],a[0]*b[4]+a[2]*b[5]+a[4],a[1]*b[4]+a[3]*b[5]+a[5]];
const samePoint = (a, b) => a && b && Math.hypot(a[0]-b[0], a[1]-b[1]) < 1e-7;

// Flatten in screen coordinates: tiny local circles can be huge after an affine transform.
const CURVE_TOLERANCE = .2, MAX_CURVE_SEGMENTS = 4096;
function maximumScale(m) {
  const xx=m[0]*m[0]+m[1]*m[1],yy=m[2]*m[2]+m[3]*m[3],xy=m[0]*m[2]+m[1]*m[3];
  return Math.sqrt(Math.max(0,(xx+yy+Math.sqrt((xx-yy)*(xx-yy)+4*xy*xy))/2));
}
function segmentDistanceSquared(p,a,b) {
  const dx=b[0]-a[0],dy=b[1]-a[1],l=dx*dx+dy*dy,t=l?clamp(((p[0]-a[0])*dx+(p[1]-a[1])*dy)/l):0;
  return (p[0]-a[0]-t*dx)**2+(p[1]-a[1]-t*dy)**2;
}
const midpoint=(a,b)=>[(a[0]+b[0])/2,(a[1]+b[1])/2];
function appendCurve(out,p,budget) { if(budget.count>=MAX_CURVE_SEGMENTS)out[out.length-1]=p;else{out.push(p);budget.count++;} }
function flattenQuadratic(a,b,c,out,budget,depth=0) {
  if(depth>=16||budget.count>=MAX_CURVE_SEGMENTS-1||segmentDistanceSquared(b,a,c)<=CURVE_TOLERANCE**2){appendCurve(out,c,budget);return;}
  const ab=midpoint(a,b),bc=midpoint(b,c),m=midpoint(ab,bc);flattenQuadratic(a,ab,m,out,budget,depth+1);flattenQuadratic(m,bc,c,out,budget,depth+1);
}
function flattenCubic(a,b,c,d,out,budget,depth=0) {
  if(depth>=16||budget.count>=MAX_CURVE_SEGMENTS-1||Math.max(segmentDistanceSquared(b,a,d),segmentDistanceSquared(c,a,d))<=CURVE_TOLERANCE**2){appendCurve(out,d,budget);return;}
  const ab=midpoint(a,b),bc=midpoint(b,c),cd=midpoint(c,d),abc=midpoint(ab,bc),bcd=midpoint(bc,cd),m=midpoint(abc,bcd);
  flattenCubic(a,ab,abc,m,out,budget,depth+1);flattenCubic(m,bcd,cd,d,out,budget,depth+1);
}

let measureCanvas, measureContext;
function nativeText() {
  if (!measureContext) {
    measureCanvas = document.createElement('canvas');
    measureContext = measureCanvas.getContext('2d', { willReadFrequently: true });
  }
  return measureContext;
}
function fontSize(font) { const m = /([\d.]+)px/.exec(font); return m ? Number(m[1]) : 10; }
function initialState() {
  return { matrix: IDENTITY.slice(), globalAlpha: 1, globalCompositeOperation: 'source-over',
    fillStyle: '#000000', strokeStyle: '#000000', lineWidth: 1, lineCap: 'butt', lineJoin: 'miter',
    miterLimit: 10, lineDashOffset: 0, dash: [], font: '10px sans-serif', letterSpacing: '0px',
    textBaseline: 'alphabetic', textAlign: 'start', fontKerning: 'auto', direction: 'inherit',
    shadowColor: 'rgba(0,0,0,0)', shadowBlur: 0, shadowOffsetX: 0, shadowOffsetY: 0,
    filter: 'none', imageSmoothingEnabled: true, clips: [] };
}
function cloneState(s) { return Object.assign({}, s, { matrix: s.matrix.slice(), dash: s.dash.slice(), clips: s.clips.slice() }); }
function snapshotPaint(p) { return p && p._vkGradient ? { ...p, matrix: p.matrix.slice(), stops: p.stops.map(s => s.slice()) } : p; }
function snapshotStyle(s) { const a = cloneState(s); a.fillStyle = snapshotPaint(a.fillStyle); a.strokeStyle = snapshotPaint(a.strokeStyle); return a; }
class Gradient {
  constructor(type, values, matrix) { this._vkGradient = true; this.type = type; this.values = values; this.matrix = matrix.slice(); this.stops = []; }
  addColorStop(offset, color) {
    offset = Number(offset); if (!Number.isFinite(offset) || offset < 0 || offset > 1) throw new RangeError('Gradient stop must be between 0 and 1');
    this.stops.push([offset, String(color)]); this.stops.sort((a,b) => a[0] - b[0]);
  }
}
const svgLoader = new SVGLoader();
const svgContours = new Map();
export function parsePath(d) { return Object.freeze({ _vkPath: true, d: String(d) }); }
function parsedContours(d,m=IDENTITY) {
  let subpaths=svgContours.get(d);
  if(!subpaths){
    const safe=d.replaceAll('&','&amp;').replaceAll('"','&quot;').replaceAll('<','&lt;');
    const data=svgLoader.parse('<svg xmlns="http://www.w3.org/2000/svg"><path d="'+safe+'"/></svg>');subpaths=data.paths.flatMap(p=>p.subPaths);
    if(svgContours.size>512)svgContours.delete(svgContours.keys().next().value);svgContours.set(d,subpaths);
  }
  return subpaths.map(sub=>{
    const points=[];
    for(const curve of sub.curves){
      const sample=t=>{const p=curve.getPoint(t);return point(m,p.x,p.y);};
      if(!points.length)points.push(sample(0));
      if(curve.isLineCurve||curve.type==='LineCurve')points.push(sample(1));
      else if(curve.isQuadraticBezierCurve||curve.type==='QuadraticBezierCurve')flattenQuadratic(point(m,curve.v0.x,curve.v0.y),point(m,curve.v1.x,curve.v1.y),point(m,curve.v2.x,curve.v2.y),points,{count:0});
      else if(curve.isCubicBezierCurve||curve.type==='CubicBezierCurve')flattenCubic(point(m,curve.v0.x,curve.v0.y),point(m,curve.v1.x,curve.v1.y),point(m,curve.v2.x,curve.v2.y),point(m,curve.v3.x,curve.v3.y),points,{count:0});
      else if(curve.isEllipseCurve||curve.type==='EllipseCurve'){
        const rot=curve.aRotation||0,co=Math.cos(rot),si=Math.sin(rot),rx=curve.xRadius,ry=curve.yRadius,R=maximumScale([(m[0]*co+m[2]*si)*rx,(m[1]*co+m[3]*si)*rx,(-m[0]*si+m[2]*co)*ry,(-m[1]*si+m[3]*co)*ry]),step=R>CURVE_TOLERANCE?2*Math.acos(clamp(1-CURVE_TOLERANCE/R,-1,1)):Math.PI/2,n=Math.min(MAX_CURVE_SEGMENTS,Math.max(16,Math.ceil(TAU/(step||Math.PI/8))));
        for(let i=1;i<=n;i++)points.push(sample(i/n));
      }else{
        const subdivide=(a,b,pa,pb,depth=0)=>{const mid=(a+b)/2,pm=sample(mid),p1=sample((a+mid)/2),p3=sample((mid+b)/2);if(depth>=12||points.length>=MAX_CURVE_SEGMENTS||Math.max(segmentDistanceSquared(pm,pa,pb),segmentDistanceSquared(p1,pa,pb),segmentDistanceSquared(p3,pa,pb))<=CURVE_TOLERANCE**2){points.push(pb);return;}subdivide(a,mid,pa,pm,depth+1);subdivide(mid,b,pm,pb,depth+1);};subdivide(0,1,sample(0),sample(1));
      }
    }
    return {points,closed:Boolean(sub.autoClose)};
  });
}

class DrawingContext {
  constructor(canvas) { this.canvas = canvas; this._commands = []; this._state = initialState(); this._stack = []; this.beginPath(); }
  save() { this._stack.push(cloneState(this._state)); }
  restore() { if (this._stack.length) this._state = this._stack.pop(); }
  reset() { this._commands.length = 0; this._state = initialState(); this._stack.length = 0; this.beginPath(); }
  setTransform(a, b, c, d, e, f) {
    if (typeof a === 'object') this._state.matrix = [a.a,a.b,a.c,a.d,a.e,a.f];
    else this._state.matrix = [a,b,c,d,e,f].map(Number);
  }
  resetTransform() { this._state.matrix = IDENTITY.slice(); }
  transform(a,b,c,d,e,f) { this._state.matrix = multiply(this._state.matrix, [a,b,c,d,e,f]); }
  translate(x,y) { this.transform(1,0,0,1,x,y); }
  rotate(a) { this.transform(Math.cos(a),Math.sin(a),-Math.sin(a),Math.cos(a),0,0); }
  scale(x,y) { this.transform(x,0,0,y,0,0); }
  getTransform() { const m=this._state.matrix; return {a:m[0],b:m[1],c:m[2],d:m[3],e:m[4],f:m[5]}; }
  setLineDash(d) { this._state.dash = Array.from(d, Number); if (d.length % 2) this._state.dash.push(...this._state.dash); }
  getLineDash() { return this._state.dash.slice(); }
  beginPath() { this._path = []; this._current = null; }
  _moveWorld(p) { const s = { points: [p], closed: false }; this._path.push(s); this._current = s; }
  moveTo(x,y) { this._moveWorld(point(this._state.matrix,x,y)); }
  lineTo(x,y) { const p=point(this._state.matrix,x,y); if (!this._current) this._moveWorld(p); else this._current.points.push(p); }
  closePath() {
    if (!this._current || !this._current.points.length) return;
    this._current.closed = true;
    const p=this._current.points[0]; if (!samePoint(p,this._current.points.at(-1))) this._current.points.push(p.slice());
  }
  quadraticCurveTo(cx,cy,x,y) {
    const m=this._state.matrix,c=point(m,cx,cy),q=point(m,x,y);if(!this._current)this._moveWorld(c);
    flattenQuadratic(this._current.points.at(-1),c,q,this._current.points,{count:0});
  }
  bezierCurveTo(x1,y1,x2,y2,x,y) {
    const m=this._state.matrix,a=point(m,x1,y1),b=point(m,x2,y2),q=point(m,x,y);if(!this._current)this._moveWorld(a);
    flattenCubic(this._current.points.at(-1),a,b,q,this._current.points,{count:0});
  }
  ellipse(cx,cy,rx,ry,rot,start,end,anticlockwise=false) {
    if(rx<0||ry<0)throw new RangeError('Ellipse radii must be non-negative');
    let delta=end-start;
    if(!anticlockwise){if(delta>=TAU)delta=TAU;else delta=((delta%TAU)+TAU)%TAU;}
    else{if(delta<=-TAU)delta=-TAU;else delta=-(((-delta%TAU)+TAU)%TAU);}
    if(Math.abs(end-start)>=TAU&&Math.abs(delta)<1e-9)delta=anticlockwise?-TAU:TAU;
    const m=this._state.matrix,co=Math.cos(rot),si=Math.sin(rot);
    const screenRadius=maximumScale([(m[0]*co+m[2]*si)*rx,(m[1]*co+m[3]*si)*rx,(-m[0]*si+m[2]*co)*ry,(-m[1]*si+m[3]*co)*ry]);
    const step=screenRadius>CURVE_TOLERANCE?2*Math.acos(clamp(1-CURVE_TOLERANCE/screenRadius,-1,1)):Math.PI/2;
    const n=Math.max(1,Math.min(MAX_CURVE_SEGMENTS,Math.ceil(Math.abs(delta)/Math.min(Math.PI/8,step||Math.PI/8))));
    for(let i=0;i<=n;i++){const a=start+delta*i/n,xx=rx*Math.cos(a),yy=ry*Math.sin(a),p=point(m,cx+xx*co-yy*si,cy+xx*si+yy*co);if(!this._current)this._moveWorld(p);else if(i||!samePoint(p,this._current.points.at(-1)))this._current.points.push(p);}
  }
  arc(x,y,r,a,b,ccw=false) { this.ellipse(x,y,r,r,0,a,b,ccw); }
  rect(x,y,w,h) { this.moveTo(x,y);this.lineTo(x+w,y);this.lineTo(x+w,y+h);this.lineTo(x,y+h);this.closePath(); }
  roundRect(x,y,w,h,radii=0) {
    let rs=Array.isArray(radii)?radii:[radii];rs=rs.map(r=>typeof r==='number'?r:Math.max(r.x||0,r.y||0));
    if(rs.some(r=>r<0))throw new RangeError('Corner radius must be non-negative');
    if(rs.length===1)rs=[rs[0],rs[0],rs[0],rs[0]];else if(rs.length===2)rs=[rs[0],rs[1],rs[0],rs[1]];else if(rs.length===3)rs=[rs[0],rs[1],rs[2],rs[1]];
    if(w<0){x+=w;w=-w;rs=[rs[1],rs[0],rs[3],rs[2]];}if(h<0){y+=h;h=-h;rs=[rs[3],rs[2],rs[1],rs[0]];}
    const scale=Math.min(1,w/(rs[0]+rs[1]||1),w/(rs[3]+rs[2]||1),h/(rs[0]+rs[3]||1),h/(rs[1]+rs[2]||1));rs=rs.map(r=>r*scale);
    this.moveTo(x+rs[0],y);this.lineTo(x+w-rs[1],y);this.quadraticCurveTo(x+w,y,x+w,y+rs[1]);this.lineTo(x+w,y+h-rs[2]);this.quadraticCurveTo(x+w,y+h,x+w-rs[2],y+h);this.lineTo(x+rs[3],y+h);this.quadraticCurveTo(x,y+h,x,y+h-rs[3]);this.lineTo(x,y+rs[0]);this.quadraticCurveTo(x,y,x+rs[0],y);this.closePath();
  }
  _contours(path) {
    if(path&&path._vkPath||typeof path==='string'&&!['evenodd','nonzero'].includes(path)){
      return parsedContours(typeof path==='string'?path:path.d,this._state.matrix);
    }
    return this._path.map(c=>({closed:c.closed,points:c.points.map(p=>p.slice())}));
  }
  fill(path,rule='nonzero') { if(path==='evenodd'||path==='nonzero'){rule=path;path=null;}this._recordPath(this._contours(path),false,rule); }
  stroke(path) { this._recordPath(this._contours(path),true,'nonzero'); }
  clip(path,rule='nonzero') { if(path==='evenodd'||path==='nonzero'){rule=path;path=null;}this._state.clips.push({contours:this._contours(path),rule}); }
  _recordPath(contours,stroke,rule) { if(contours.length)this._commands.push({kind:'path',contours,stroke,rule,style:snapshotStyle(this._state)}); }
  fillRect(x,y,w,h) { const m=this._state.matrix;this._recordPath([{closed:true,points:[[x,y],[x+w,y],[x+w,y+h],[x,y+h]].map(p=>point(m,...p))}],false,'nonzero'); }
  strokeRect(x,y,w,h) { const m=this._state.matrix;this._recordPath([{closed:true,points:[[x,y],[x+w,y],[x+w,y+h],[x,y+h],[x,y]].map(p=>point(m,...p))}],true,'nonzero'); }
  clearRect(x,y,w,h) {
    if(x===0&&y===0&&w>=this.canvas.width&&h>=this.canvas.height&&this._state.matrix.every((v,i)=>v===IDENTITY[i])){this._commands.length=0;return;}
    const old=this._state;this._state=cloneState(old);this._state.fillStyle='#ffffff';this._state.globalAlpha=1;this._state.globalCompositeOperation='destination-out';this.fillRect(x,y,w,h);this._state=old;
  }
  createLinearGradient(x0,y0,x1,y1) { return new Gradient('linear',[x0,y0,x1,y1],this._state.matrix); }
  createRadialGradient(x0,y0,r0,x1,y1,r1) { if(r0<0||r1<0)throw new RangeError('Gradient radii must be non-negative');return new Gradient('radial',[x0,y0,r0,x1,y1,r1],this._state.matrix); }
  _textContext() { const c=nativeText(),s=this._state;c.font=s.font;c.letterSpacing=s.letterSpacing;c.fontKerning=s.fontKerning;c.textBaseline='alphabetic';c.textAlign='left';c.direction=s.direction;return c; }
  measureText(text) { return this._textContext().measureText(String(text)); }
  fillText(text,x,y,maxWidth) { this._text(text,x,y,maxWidth,false); }
  strokeText(text,x,y,maxWidth) { this._text(text,x,y,maxWidth,true); }
  _text(text,x,y,maxWidth,stroke) { if(String(text))this._commands.push({kind:'text',text:String(text),x,y,maxWidth,stroke,style:snapshotStyle(this._state)}); }
  drawImage(source,...args) {
    const width=source.naturalWidth||source.videoWidth||source.width,height=source.naturalHeight||source.videoHeight||source.height;if(!width||!height)return;
    let sx=0,sy=0,sw=width,sh=height,dx,dy,dw=width,dh=height;
    if(args.length===2)[dx,dy]=args;else if(args.length===4)[dx,dy,dw,dh]=args;else if(args.length===8)[sx,sy,sw,sh,dx,dy,dw,dh]=args;else throw new TypeError('drawImage requires 3, 5 or 9 arguments');
    const image=source._vkSurface?{_vkSnapshot:true,width,height,commands:source.context._commands.slice()}:source;
    this._commands.push({kind:'image',source:image,sx,sy,sw,sh,dx,dy,dw,dh,style:snapshotStyle(this._state)});
  }
  effect(name,params={}) { this._commands.push({kind:'effect',name,params:{...params}}); }
  getImageData() { throw new Error('A GPU drawing surface has no Canvas2D pixels. Rasterize only the text glyph in a small native canvas, or read a WebGL render target.'); }
}
for(const key of Object.keys(initialState())){
  if(['matrix','dash','clips'].includes(key))continue;
  Object.defineProperty(DrawingContext.prototype,key,{get(){return this._state[key];},set(v){if(key==='globalAlpha'&&(!Number.isFinite(v)||v<0||v>1))return;this._state[key]=v;}});
}
export function createSurface(width,height) {
  const surface={_vkSurface:true,width,height,context:null,getContext(type){if(type!=='2d')return null;return this.context;}};
  surface.context=new DrawingContext(surface);return surface;
}


/* Paths become triangle meshes, including winding-rule holes and wide strokes. */
function signedArea(p) { let a=0;for(let i=0,j=p.length-1;i<p.length;j=i++)a+=p[j][0]*p[i][1]-p[i][0]*p[j][1];return a/2; }
function inside(p,poly) { let yes=false;for(let i=0,j=poly.length-1;i<poly.length;j=i++){const a=poly[i],b=poly[j];if((a[1]>p[1])!==(b[1]>p[1])&&p[0]<(b[0]-a[0])*(p[1]-a[1])/(b[1]-a[1])+a[0])yes=!yes;}return yes; }
function cleanContour(c) { const p=[];for(const q of c.points)if(!samePoint(q,p.at(-1)))p.push(q);if(p.length>1&&samePoint(p[0],p.at(-1)))p.pop();return p; }
function fillGeometry(contours,rule) {
  const nodes=contours.map(cleanContour).filter(p=>p.length>=3).map(p=>({p,area:signedArea(p),parent:null,children:[]}));
  nodes.sort((a,b)=>Math.abs(b.area)-Math.abs(a.area));
  for(let i=0;i<nodes.length;i++){const n=nodes[i];for(let j=i-1;j>=0;j--)if(inside(n.p[0],nodes[j].p)){n.parent=nodes[j];nodes[j].children.push(n);break;}n.before=n.parent?n.parent.after:0;n.after=rule==='evenodd'?(n.before?0:1):n.before+(n.area>=0?1:-1);}
  const positions=[];
  for(const n of nodes){if(n.before!==0||n.after===0)continue;const outer=n.p.map(p=>new THREE.Vector2(...p)),holes=[];
    const findHoles=q=>{for(const c of q.children){if(c.before!==0&&c.after===0)holes.push(c.p.map(p=>new THREE.Vector2(...p)));else findHoles(c);}};findHoles(n);
    const vertices=outer.concat(...holes),faces=THREE.ShapeUtils.triangulateShape(outer,holes);
    for(const face of faces)for(const i of face){const p=vertices[i];positions.push(p.x,p.y,0);}
  }
  if(!positions.length)return null;const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));g.setAttribute('uv',new THREE.Float32BufferAttribute(new Float32Array(positions.length/3*2),2));return g;
}
function dashedSegments(points,dash,offset) {
  if(!dash.length||dash.every(v=>v<=0))return [points];
  dash=dash.map(v=>Math.max(0,v));const total=dash.reduce((a,b)=>a+b,0);let phase=((offset%total)+total)%total,di=0;
  while(phase>=dash[di]&&di<dash.length-1){phase-=dash[di];di++;}
  let remain=dash[di]-phase,on=di%2===0,current=[],out=[];
  for(let i=1;i<points.length;i++){let a=points[i-1],b=points[i],len=Math.hypot(b[0]-a[0],b[1]-a[1]);if(len<1e-8)continue;let done=0;
    while(done<len-1e-8){if(remain<1e-8){if(on&&current.length>1)out.push(current);current=[];di=(di+1)%dash.length;on=di%2===0;remain=dash[di];continue;}
      const step=Math.min(remain,len-done),p=[a[0]+(b[0]-a[0])*done/len,a[1]+(b[1]-a[1])*done/len],q=[a[0]+(b[0]-a[0])*(done+step)/len,a[1]+(b[1]-a[1])*(done+step)/len];
      if(on){if(!current.length)current.push(p);current.push(q);}done+=step;remain-=step;
    }
  }
  if(on&&current.length>1)out.push(current);return out;
}
function strokeGeometries(contours,s) {
  const scale=Math.sqrt(Math.abs(s.matrix[0]*s.matrix[3]-s.matrix[1]*s.matrix[2])),width=Number(s.lineWidth)*scale;if(width<=0)return [];
  const style=SVGLoader.getStrokeStyle(width,'#fff',s.lineJoin,s.lineCap,s.miterLimit),out=[];
  for(const contour of contours){let p=contour.points.slice();if(contour.closed&&!samePoint(p[0],p.at(-1)))p.push(p[0]);
    for(const seg of dashedSegments(p,s.dash.map(v=>v*scale),s.lineDashOffset*scale)){if(seg.length<2)continue;const g=SVGLoader.pointsToStroke(seg.map(v=>new THREE.Vector2(...v)),style,10,.00001);if(g)out.push(g);}
  }return out;
}
function quadGeometry(x,y,w,h,m=IDENTITY,uv=[0,1,1,0]) {
  const ps=[[x,y],[x+w,y],[x+w,y+h],[x,y+h]].map(p=>point(m,...p)),p=[],u=[],us=[[uv[0],uv[1]],[uv[2],uv[1]],[uv[2],uv[3]],[uv[0],uv[3]]];
  for(const i of [0,1,2,0,2,3]){p.push(...ps[i],0);u.push(...us[i]);}const g=new THREE.BufferGeometry();g.setAttribute('position',new THREE.Float32BufferAttribute(p,3));g.setAttribute('uv',new THREE.Float32BufferAttribute(u,2));return g;
}
const colorCache=new Map();
function colorAlpha(value) {
  const key=String(value||'#000');if(colorCache.has(key))return colorCache.get(key);
  let a=1,c=key;if(c==='transparent'){c='#000';a=0;}
  const rgba=/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)$/i.exec(c);
  let col;
  if(rgba){col=new THREE.Color().setRGB(+rgba[1]/255,+rgba[2]/255,+rgba[3]/255,THREE.SRGBColorSpace);a=rgba[4]==null?1:+rgba[4];}
  else{if(/^#[0-9a-f]{8}$/i.test(c)){a=parseInt(c.slice(-2),16)/255;c=c.slice(0,7);}else if(/^#[0-9a-f]{4}$/i.test(c)){a=parseInt(c[4]+c[4],16)/255;c=c.slice(0,4);}col=new THREE.Color(c);}
  const out=[col.r,col.g,col.b,clamp(a)];if(colorCache.size>2048)colorCache.clear();colorCache.set(key,out);return out;
}
const VERTEX=String.raw`
varying vec2 vWorld;
varying vec2 vUv;
void main(){vWorld=position.xy;vUv=uv;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);}
`;
const PAINT_FRAGMENT=String.raw`
precision highp float;
varying vec2 vWorld;
varying vec2 vUv;
uniform vec4 uColor;
uniform float uOpacity;
uniform int uPaintType;
uniform mat3 uPaintInverse;
uniform vec4 uLinear;
uniform vec4 uRadial0;
uniform vec2 uRadial1;
uniform sampler2D uRamp;
uniform sampler2D uMap;
uniform int uMapMode;
uniform int uMapPremultiplied;
uniform vec2 uTexel;
uniform float uBlur;
uniform int uClipCount;
uniform int uClipGroups;
uniform vec2 uClipPoints[64];
uniform vec3 uClipMeta[8];
uniform vec4 uClipRules;
float cross2(vec2 a,vec2 b){return a.x*b.y-a.y*b.x;}
bool clipped(){
 for(int group=0;group<4;group++){
  if(group>=uClipGroups)break;
  float winding=0.0;
  for(int contour=0;contour<8;contour++){
   if(contour>=uClipCount)break;
   vec3 meta=uClipMeta[contour];if(int(meta.z+0.5)!=group)continue;
   int start=int(meta.x+0.5),count=int(meta.y+0.5);
   for(int i=0;i<64;i++){
    if(i>=count)break;
    vec2 a=uClipPoints[start+i],b=uClipPoints[start+int(mod(float(i+1),float(count)))];
    if(a.y<=vWorld.y&&b.y>vWorld.y&&cross2(b-a,vWorld-a)>0.0)winding+=1.0;
    if(a.y>vWorld.y&&b.y<=vWorld.y&&cross2(b-a,vWorld-a)<0.0)winding-=1.0;
   }
  }
  bool evenodd=false;
  if(group==0)evenodd=uClipRules.x>0.5;else if(group==1)evenodd=uClipRules.y>0.5;else if(group==2)evenodd=uClipRules.z>0.5;else evenodd=uClipRules.w>0.5;
  if(evenodd?mod(abs(winding),2.0)<0.5:abs(winding)<0.5)return true;
 }
 return false;
}
vec4 imageSample(vec2 p){
 vec4 c=texture2D(uMap,p);
 if(uBlur<0.05)return c;
 vec2 r=uTexel*uBlur;
 c*=0.20;
 c+=texture2D(uMap,p+vec2(r.x,0.0))*0.10;c+=texture2D(uMap,p-vec2(r.x,0.0))*0.10;
 c+=texture2D(uMap,p+vec2(0.0,r.y))*0.10;c+=texture2D(uMap,p-vec2(0.0,r.y))*0.10;
 c+=texture2D(uMap,p+r*0.7071)*0.10;c+=texture2D(uMap,p-r*0.7071)*0.10;
 c+=texture2D(uMap,p+vec2(r.x,-r.y)*0.7071)*0.10;c+=texture2D(uMap,p+vec2(-r.x,r.y)*0.7071)*0.10;
 return c;
}
void main(){
 if(clipped())discard;
 vec4 c=uColor;
 if(uPaintType>0){
  vec2 p=(uPaintInverse*vec3(vWorld,1.0)).xy;float t=0.0;
  if(uPaintType==1){vec2 d=uLinear.zw-uLinear.xy;t=dot(p-uLinear.xy,d)/max(dot(d,d),0.000001);}
  else{
   vec2 v=p-uRadial0.xy,d=uRadial0.zw-uRadial0.xy;float r0=uRadial1.x,dr=uRadial1.y-r0;
   float A=dot(d,d)-dr*dr,B=-2.0*(dot(v,d)+r0*dr),C=dot(v,v)-r0*r0;
   if(abs(A)<0.000001)t=abs(B)>0.000001?-C/B:0.0;
   else{float disc=B*B-4.0*A*C;if(disc<0.0)discard;float root=sqrt(max(0.0,disc)),t1=(-B-root)/(2.0*A),t2=(-B+root)/(2.0*A);bool ok1=r0+t1*dr>=0.0,ok2=r0+t2*dr>=0.0;if(!ok1&&!ok2)discard;t=ok1&&ok2?max(t1,t2):(ok1?t1:t2);}
  }
  c=texture2D(uRamp,vec2(clamp(t,0.0,1.0),0.5));
 }
 if(uMapMode>0){vec4 tex=imageSample(vUv);if(uMapMode==1)c.a*=tex.a;else{c=tex;if(uMapPremultiplied==1&&c.a>0.00001)c.rgb/=c.a;}}
 c.a*=uOpacity;if(c.a<0.0001)discard;gl_FragColor=c;
 #include <colorspace_fragment>
}
`;
const FULLSCREEN_VERTEX=String.raw`
varying vec2 vUv;
void main(){vUv=uv;gl_Position=vec4(position.xy,0.0,1.0);}
`;
const EFFECT_FRAGMENT=String.raw`
precision highp float;
varying vec2 vUv;
uniform sampler2D uMap;
uniform sampler2D uBloom;
uniform sampler2D uSource;
uniform vec2 uSize;
uniform vec2 uShift;
uniform vec2 uDirection;
uniform int uMode;
uniform float uStrength;
uniform float uGrain;
uniform float uFrame;
float random(vec2 p){return fract(sin(dot(p,vec2(12.9898,78.233))+uFrame*37.719)*43758.5453);}
void main(){
 vec2 uv=vUv-uShift/uSize;
 vec4 c=texture2D(uMap,uv);
 if(uMode==1){
  float sigma=max(abs(uDirection.x),abs(uDirection.y));vec2 axis=uDirection/max(sigma,.0001)/uSize;
  c=vec4(0.0);float weight=0.0;
  for(int i=-32;i<=32;i++){float f=float(i);if(abs(f)>sigma*3.0)continue;float w=exp(-.5*f*f/max(.0001,sigma*sigma));c+=texture2D(uMap,uv+axis*f)*w;weight+=w;}
  c/=max(weight,.0001);
 }else if(uMode==2){
  vec3 s=vec3(dot(c.rgb,vec3(.393,.769,.189)),dot(c.rgb,vec3(.349,.686,.168)),dot(c.rgb,vec3(.272,.534,.131)));
  float vignette=smoothstep(.43,.78,length((vUv-.5)*vec2(1.0,.8)));
  c.rgb=mix(c.rgb,s,uStrength*.72)*(1.0-vignette*uStrength*.6);
 }else if(uMode==3){c.rgb+=texture2D(uBloom,vUv).rgb*uStrength;}else if(uMode==4||uMode==5){
  vec4 src=texture2D(uSource,vUv);float sa=src.a,da=c.a;vec3 cs=src.rgb/max(sa,.00001),cd=c.rgb/max(da,.00001),blend;
  if(uMode==4)blend=mix(2.0*cs*cd,1.0-2.0*(1.0-cs)*(1.0-cd),step(vec3(.5),cd));
  else{float lum=dot(cd,vec3(.3,.59,.11));blend=cs+vec3(lum-dot(cs,vec3(.3,.59,.11)));float lo=min(min(blend.r,blend.g),blend.b),hi=max(max(blend.r,blend.g),blend.b);if(lo<0.0)blend=vec3(lum)+(blend-vec3(lum))*lum/max(.00001,lum-lo);if(hi>1.0)blend=vec3(lum)+(blend-vec3(lum))*(1.0-lum)/max(.00001,hi-lum);}
  c=vec4((1.0-sa)*da*cd+(1.0-da)*sa*cs+sa*da*blend,sa+da*(1.0-sa));
 }
 if(uGrain>0.0)c.rgb*=1.0+(random(floor(vUv*uSize))-0.5)*uGrain*.8;
 gl_FragColor=c;
 #include <colorspace_fragment>
}
`;


/** Create the actual WebGL renderer; a surface never owns a 2D frame bitmap. */
export function createRenderer(stageCanvas,width,height) {
  const three=new THREE.WebGLRenderer({canvas:stageCanvas,antialias:true,alpha:false,preserveDrawingBuffer:true});
  three.setPixelRatio(1);three.setSize(width,height,false);three.outputColorSpace=THREE.SRGBColorSpace;three.toneMapping=THREE.NoToneMapping;
  three.autoClear=false;three.sortObjects=true;three.info.autoReset=false;
  const camera=new THREE.OrthographicCamera(0,width,0,height,.1,1000);camera.position.z=100;
  const passCamera=new THREE.Camera(),passScene=new THREE.Scene(),passGeometry=new THREE.PlaneGeometry(2,2),passMesh=new THREE.Mesh(passGeometry);
  passScene.add(passMesh);passMesh.frustumCulled=false;
  const frameResources=new Set(),glyphCache=new Map(),blurCache=new Map(),rampCache=new Map(),imageCache=new WeakMap(),imageTextures=new Set();
  const emptyPoints=Array.from({length:64},()=>new THREE.Vector2()),emptyMeta=Array.from({length:8},()=>new THREE.Vector3());
  let memo=new WeakMap(),disposed=false;
  const track=r=>(frameResources.add(r),r);
  function beginFrame(){if(disposed)throw new Error('Renderer has been disposed');for(const r of frameResources)r.dispose();frameResources.clear();memo=new WeakMap();three.info.reset();}
  function target(w=width,h=height,keep=false,antialias=true){const rt=new THREE.WebGLRenderTarget(w,h,{minFilter:THREE.LinearFilter,magFilter:THREE.LinearFilter,depthBuffer:true,stencilBuffer:false,type:three.extensions.has('EXT_color_buffer_float')?THREE.HalfFloatType:THREE.UnsignedByteType});if(!keep)track(rt);rt.texture.colorSpace=THREE.LinearSRGBColorSpace;rt.samples=antialias?Math.min(4,three.capabilities.maxSamples||0):0;return rt;}
  function clear(rt){three.setRenderTarget(rt);three.setClearColor(0x000000,0);three.clear(true,true,true);}
  function fullPass(input,output,options={}){
    const mat=track(new THREE.ShaderMaterial({vertexShader:FULLSCREEN_VERTEX,fragmentShader:EFFECT_FRAGMENT,
      uniforms:{uMap:{value:input.texture||input},uSource:{value:options.source?.texture||input.texture||input},uBloom:{value:options.bloom?.texture||input.texture||input},uSize:{value:new THREE.Vector2(input.width||width,input.height||height)},uShift:{value:new THREE.Vector2(options.dx||0,-(options.dy||0))},uDirection:{value:new THREE.Vector2(options.blurX||0,options.blurY||0)},uMode:{value:options.mode||0},uStrength:{value:options.strength??1},uGrain:{value:options.grain||0},uFrame:{value:options.frame||0}},
      depthTest:false,depthWrite:false,transparent:false,toneMapped:false}));
    passMesh.material=mat;three.setRenderTarget(output);three.render(passScene,passCamera);
  }
  function ramp(paint){
    const key=JSON.stringify(paint.stops);if(rampCache.has(key)){const t=rampCache.get(key);rampCache.delete(key);rampCache.set(key,t);return t;}
    const stops=paint.stops.length?paint.stops:[[0,'transparent'],[1,'transparent']],data=new Uint16Array(512*4);
    for(let i=0;i<512;i++){const t=i/511;let a=stops[0],b=stops.at(-1);for(let j=1;j<stops.length;j++)if(t<stops[j][0]){a=stops[j-1];b=stops[j];break;}if(t<=stops[0][0])a=b=stops[0];if(t>=stops.at(-1)[0])a=b=stops.at(-1);const ca=colorAlpha(a[1]),cb=colorAlpha(b[1]),k=a===b?0:clamp((t-a[0])/(b[0]-a[0]||1));for(let c=0;c<4;c++)data[i*4+c]=THREE.DataUtils.toHalfFloat(ca[c]+(cb[c]-ca[c])*k);}
    const texture=new THREE.DataTexture(data,512,1,THREE.RGBAFormat,THREE.HalfFloatType);texture.minFilter=texture.magFilter=THREE.LinearFilter;texture.generateMipmaps=false;texture.needsUpdate=true;rampCache.set(key,texture);
    if(rampCache.size>256){const oldest=rampCache.keys().next().value;track(rampCache.get(oldest));rampCache.delete(oldest);}return texture;
  }
  function clipUniforms(clips){
    if(!clips.length)return {points:emptyPoints,meta:emptyMeta,count:0,groups:0,rules:new THREE.Vector4()};
    if(clips.length>4)throw new Error('At most four nested GPU clip regions are supported');
    const ps=Array.from({length:64},()=>new THREE.Vector2()),ms=Array.from({length:8},()=>new THREE.Vector3()),rules=new THREE.Vector4();let pi=0,ci=0;
    clips.forEach((clip,group)=>{rules.setComponent(group,clip.rule==='evenodd'?1:0);for(const raw of clip.contours){const p=cleanContour(raw);if(p.length<3)continue;if(ci>=8)throw new Error('At most eight clip contours are supported');const left=64-pi,reserve=Math.max(0,clips.length-group-1)*4,n=Math.min(p.length,left-reserve);if(n<3)throw new Error('GPU clip contour budget exceeded');ms[ci++].set(pi,n,group);for(let i=0;i<n;i++)ps[pi++].set(...p[Math.floor(i*p.length/n)]);}});
    return {points:ps,meta:ms,count:ci,groups:clips.length,rules};
  }
  function applyBlend(material,op){
    if(op==='lighter'){material.blending=THREE.CustomBlending;material.blendSrc=THREE.SrcAlphaFactor;material.blendDst=THREE.OneFactor;material.blendSrcAlpha=THREE.OneFactor;material.blendDstAlpha=THREE.OneFactor;}
    else if(op==='destination-out'){material.blending=THREE.CustomBlending;material.blendSrc=THREE.ZeroFactor;material.blendDst=THREE.OneMinusSrcAlphaFactor;material.blendSrcAlpha=THREE.ZeroFactor;material.blendDstAlpha=THREE.OneMinusSrcAlphaFactor;}
    else if(op==='destination-in'){material.blending=THREE.CustomBlending;material.blendSrc=THREE.ZeroFactor;material.blendDst=THREE.SrcAlphaFactor;material.blendSrcAlpha=THREE.ZeroFactor;material.blendDstAlpha=THREE.SrcAlphaFactor;}
    else if(op==='copy'){material.blending=THREE.NoBlending;}
    else if(op==='multiply'){material.blending=THREE.CustomBlending;material.blendSrc=THREE.DstColorFactor;material.blendDst=THREE.OneMinusSrcAlphaFactor;material.blendSrcAlpha=THREE.OneFactor;material.blendDstAlpha=THREE.OneMinusSrcAlphaFactor;material.uniforms.uPremultiply.value=1;}
    else if(op==='screen'){material.blending=THREE.CustomBlending;material.blendSrc=THREE.OneFactor;material.blendDst=THREE.OneMinusSrcColorFactor;material.blendSrcAlpha=THREE.OneFactor;material.blendDstAlpha=THREE.OneMinusSrcAlphaFactor;material.uniforms.uPremultiply.value=1;}
    else if(op==='source-in'){material.blending=THREE.CustomBlending;material.blendSrc=THREE.DstAlphaFactor;material.blendDst=THREE.ZeroFactor;material.blendSrcAlpha=THREE.DstAlphaFactor;material.blendDstAlpha=THREE.ZeroFactor;}
    else if(!['source-over','overlay','color'].includes(op))throw new Error('Unsupported GPU composite operation: '+op);
  }
  const vertex=VERTEX;
  const fragment=PAINT_FRAGMENT.replace('uniform float uOpacity;','uniform float uOpacity; uniform int uPremultiply;').replace('gl_FragColor=c;','if(uPremultiply==1)c.rgb*=c.a;gl_FragColor=c;');
  const batchVertex=vertex.replace('varying vec2 vWorld;','attribute vec4 aColor; varying vec4 vColor; varying vec2 vWorld;').replace('void main(){','void main(){vColor=aColor;');
  const batchFragment=fragment.replace('varying vec2 vWorld;','varying vec4 vColor; varying vec2 vWorld;').replace('vec4 c=uColor;','vec4 c=vColor;');
  function paintMaterial(paint,s,map=null,options={}){
    const c=paint?._vkGradient?[1,1,1,1]:colorAlpha(paint),clip=clipUniforms(s.clips),inv=new THREE.Matrix3(),values=paint?._vkGradient?paint.values:[];
    if(paint?._vkGradient){const m=paint.matrix;inv.set(m[0],m[2],m[4],m[1],m[3],m[5],0,0,1).invert();}
    const uniforms={uColor:{value:new THREE.Vector4(...c)},uOpacity:{value:s.globalAlpha},uPaintType:{value:paint?._vkGradient?(paint.type==='linear'?1:2):0},uPaintInverse:{value:inv},uLinear:{value:new THREE.Vector4(...(values.length===4?values:[0,0,1,0]))},uRadial0:{value:new THREE.Vector4(values[0]||0,values[1]||0,values[3]||0,values[4]||0)},uRadial1:{value:new THREE.Vector2(values[2]??0,values[5]??1)},uRamp:{value:paint?._vkGradient?ramp(paint):null},uMap:{value:map?.texture||null},uMapMode:{value:map?(map.mask?1:2):0},uMapPremultiplied:{value:map?.premultiplied?1:0},uTexel:{value:new THREE.Vector2(1/(map?.width||1),1/(map?.height||1))},uBlur:{value:options.blur||0},uClipCount:{value:clip.count},uClipGroups:{value:clip.groups},uClipPoints:{value:clip.points},uClipMeta:{value:clip.meta},uClipRules:{value:clip.rules},uPremultiply:{value:0}};
    const mat=track(new THREE.ShaderMaterial({vertexShader:options.batch?batchVertex:vertex,fragmentShader:options.batch?batchFragment:fragment,uniforms,transparent:true,depthTest:false,depthWrite:false,side:THREE.DoubleSide,toneMapped:false}));applyBlend(mat,s.globalCompositeOperation);return mat;
  }
  function glyph(cmd){
    const s=cmd.style,key=[s.font,s.letterSpacing,s.fontKerning,cmd.text,cmd.stroke?s.lineWidth:0].join('|');
    if(glyphCache.has(key)){const g=glyphCache.get(key);glyphCache.delete(key);glyphCache.set(key,g);return g;}
    const c=nativeText();c.font=s.font;c.letterSpacing=s.letterSpacing;c.fontKerning=s.fontKerning;c.textBaseline='alphabetic';c.textAlign='left';const metrics=c.measureText(cmd.text),size=fontSize(s.font),left=Math.ceil(metrics.actualBoundingBoxLeft||0),right=Math.ceil(metrics.actualBoundingBoxRight||metrics.width),asc=Math.ceil(metrics.actualBoundingBoxAscent||size*.8),desc=Math.ceil(metrics.actualBoundingBoxDescent||size*.2),pad=Math.ceil(Math.max(64,size*.2,cmd.stroke?s.lineWidth*2:0));
    const w=Math.max(1,left+right+pad*2),h=Math.max(1,asc+desc+pad*2),canvas=document.createElement('canvas'),resolution=Math.min(2,4096/w,4096/h);
    canvas.width=Math.max(1,Math.ceil(w*resolution));canvas.height=Math.max(1,Math.ceil(h*resolution));const x=canvas.getContext('2d');x.scale(resolution,resolution);x.font=s.font;x.letterSpacing=s.letterSpacing;x.fontKerning=s.fontKerning;x.textBaseline='alphabetic';x.textAlign='left';x.fillStyle=x.strokeStyle='#fff';x.lineWidth=s.lineWidth;x.lineJoin=s.lineJoin;if(cmd.stroke)x.strokeText(cmd.text,left+pad,asc+pad);else x.fillText(cmd.text,left+pad,asc+pad);
    const texture=new THREE.CanvasTexture(canvas);texture.colorSpace=THREE.NoColorSpace;texture.minFilter=texture.magFilter=THREE.LinearFilter;texture.generateMipmaps=false;
    const out={texture,width:w,height:h,pixelWidth:canvas.width,pixelHeight:canvas.height,left:-left-pad,top:-asc-pad,advance:metrics.width,fontAsc:metrics.fontBoundingBoxAscent||size*.8,fontDesc:metrics.fontBoundingBoxDescent||size*.2};glyphCache.set(key,out);
    if(glyphCache.size>1024){const oldest=glyphCache.keys().next().value;track(glyphCache.get(oldest).texture);glyphCache.delete(oldest);}return out;
  }

  // Blur only the cached glyph mask on the GPU, in two dense separable passes.
  // This avoids translated copies of letters and never rasterizes a full frame on the CPU.
  function blurredGlyph(g,radius){
    radius=Math.round(Math.max(0,radius)*16)/16;if(radius<.05)return {texture:g.texture,width:g.pixelWidth,height:g.pixelHeight,mask:true};
    const key=g.texture.uuid+'|'+radius;if(blurCache.has(key)){const item=blurCache.get(key);blurCache.delete(key);blurCache.set(key,item);return item;}
    const resolution=g.pixelWidth/g.width,downsample=Math.max(1,radius*resolution/10,Math.max(g.pixelWidth,g.pixelHeight)/512),w=Math.max(1,Math.ceil(g.pixelWidth/downsample)),h=Math.max(1,Math.ceil(g.pixelHeight/downsample));
    const small=target(w,h,false,false),horizontal=target(w,h,false,false),vertical=target(w,h,true,false);
    fullPass({texture:g.texture,width:g.pixelWidth,height:g.pixelHeight},small);
    const sigma=radius*resolution/downsample;fullPass(small,horizontal,{mode:1,blurX:sigma});fullPass(horizontal,vertical,{mode:1,blurY:sigma});
    const result={texture:vertical.texture,width:w,height:h,mask:true,target:vertical};blurCache.set(key,result);
    if(blurCache.size>512){const oldest=blurCache.keys().next().value;track(blurCache.get(oldest).target);blurCache.delete(oldest);}return result;
  }
  function nativeImage(source){let texture=imageCache.get(source);if(!texture){texture=new THREE.Texture(source);texture.colorSpace=THREE.SRGBColorSpace;texture.minFilter=texture.magFilter=THREE.LinearFilter;texture.generateMipmaps=false;imageCache.set(source,texture);imageTextures.add(texture);}texture.needsUpdate=true;return {texture,width:source.naturalWidth||source.videoWidth||source.width,height:source.naturalHeight||source.videoHeight||source.height};}
  const blurOf=s=>{const m=/blur\(([\d.]+)px\)/.exec(s.filter||'');return m?+m[1]:0;};
  function meshesFor(cmd){
    const s=cmd.style,meshes=[];
    const add=(geometry,paint,map,extra={})=>{if(!geometry)return;track(geometry);const mesh=new THREE.Mesh(geometry,paintMaterial(paint,s,map,extra));mesh.frustumCulled=false;meshes.push(mesh);};
    if(cmd.kind==='path'){
      const gs=cmd.stroke?strokeGeometries(cmd.contours,s):[fillGeometry(cmd.contours,cmd.rule)].filter(Boolean),paint=cmd.stroke?s.strokeStyle:s.fillStyle;
      const shadow=colorAlpha(s.shadowColor);
      if(shadow[3]>0&&(s.shadowBlur>0||s.shadowOffsetX||s.shadowOffsetY)){
        const offsets=s.shadowBlur>0?[[0,0],[-.7,0],[.7,0],[0,-.7],[0,.7],[-.5,-.5],[.5,-.5],[-.5,.5],[.5,.5]]:[[0,0]];
        for(const [ox,oy]of offsets)for(const g of gs){const copy=track(g.clone());copy.translate(s.shadowOffsetX+ox*s.shadowBlur,s.shadowOffsetY+oy*s.shadowBlur,0);const st={...s,globalAlpha:s.globalAlpha/offsets.length},mesh=new THREE.Mesh(copy,paintMaterial(s.shadowColor,st));mesh.frustumCulled=false;meshes.push(mesh);}
      }
      for(const g of gs)add(g,paint,null);return meshes;
    }
    if(cmd.kind==='text'){
      const g=glyph(cmd),size=fontSize(s.font);let x=cmd.x,y=cmd.y,scale=cmd.maxWidth!=null?Math.min(1,cmd.maxWidth/Math.max(.001,g.advance)):1;
      if(['center'].includes(s.textAlign))x-=g.advance*scale/2;else if(['right','end'].includes(s.textAlign))x-=g.advance*scale;
      if(s.textBaseline==='middle')y+=(g.fontAsc-g.fontDesc)/2;else if(s.textBaseline==='top')y+=g.fontAsc;else if(s.textBaseline==='hanging')y+=g.fontAsc*.8;else if(['bottom','ideographic'].includes(s.textBaseline))y-=g.fontDesc;
      const map=blurredGlyph(g,blurOf(s)),paint=cmd.stroke?s.strokeStyle:s.fillStyle,shadow=colorAlpha(s.shadowColor);
      if(shadow[3]>0){const shape=track(quadGeometry(x+g.left*scale+s.shadowOffsetX,y+g.top+s.shadowOffsetY,g.width*scale,g.height,s.matrix)),mesh=new THREE.Mesh(shape,paintMaterial(s.shadowColor,s,blurredGlyph(g,Math.hypot(s.shadowBlur,blurOf(s)))));mesh.frustumCulled=false;meshes.push(mesh);}
      add(quadGeometry(x+g.left*scale,y+g.top,g.width*scale,g.height,s.matrix),paint,map);return meshes;
    }
    if(cmd.kind==='image'){
      const source=cmd.source._vkSnapshot?renderSnapshot(cmd.source):nativeImage(cmd.source),uv=[cmd.sx/cmd.source.width,1-cmd.sy/cmd.source.height,(cmd.sx+cmd.sw)/cmd.source.width,1-(cmd.sy+cmd.sh)/cmd.source.height];
      // Native images may expose naturalWidth instead of width; the recorded dimensions are authoritative.
      if(!cmd.source._vkSnapshot){const w=source.width,h=source.height;uv[0]=cmd.sx/w;uv[1]=1-cmd.sy/h;uv[2]=(cmd.sx+cmd.sw)/w;uv[3]=1-(cmd.sy+cmd.sh)/h;}
      add(quadGeometry(cmd.dx,cmd.dy,cmd.dw,cmd.dh,s.matrix,uv),'#fff',source,{blur:blurOf(s)});return meshes;
    }
    return meshes;
  }

  function runCommands(commands,output){
    const drawCamera=new THREE.OrthographicCamera(0,output.width,0,output.height,.1,1000);drawCamera.position.z=100;
    let scene=new THREE.Scene(),order=0,batch=null;
    function flushBatch(){if(!batch)return;const geometry=track(new THREE.BufferGeometry());geometry.setAttribute('position',new THREE.Float32BufferAttribute(batch.positions,3));geometry.setAttribute('uv',new THREE.Float32BufferAttribute(new Float32Array(batch.positions.length/3*2),2));geometry.setAttribute('aColor',new THREE.Float32BufferAttribute(batch.colors,4));const style={...batch.style,globalAlpha:1},mesh=new THREE.Mesh(geometry,paintMaterial('#fff',style,null,{batch:true}));mesh.frustumCulled=false;mesh.renderOrder=order++;scene.add(mesh);batch=null;}
    function flush(){flushBatch();if(scene.children.length){three.setRenderTarget(output);three.render(scene,drawCamera);scene=new THREE.Scene();}}
    function appendBatch(cmd){
      const s=cmd.style,paint=cmd.stroke?s.strokeStyle:s.fillStyle;
      if(paint?._vkGradient||s.clips.length||colorAlpha(s.shadowColor)[3]>0||blurOf(s)>0||['overlay','color','copy','destination-in','source-in'].includes(s.globalCompositeOperation))return false;
      if(batch&&batch.style.globalCompositeOperation!==s.globalCompositeOperation)flushBatch();
      if(!batch)batch={positions:[],colors:[],style:s};const color=colorAlpha(paint).slice();color[3]*=s.globalAlpha;
      const gs=cmd.stroke?strokeGeometries(cmd.contours,s):[fillGeometry(cmd.contours,cmd.rule)].filter(Boolean);
      for(const g of gs){const p=g.getAttribute('position'),index=g.getIndex(),n=index?index.count:p.count;for(let i=0;i<n;i++){const j=index?index.getX(i):i;batch.positions.push(p.getX(j),p.getY(j),p.getZ(j));batch.colors.push(...color);}g.dispose();}return true;
    }
    for(const cmd of commands){
      if(cmd.kind==='effect'){
        if(cmd.name!=='sepia')throw new Error('Unsupported GPU effect: '+cmd.name);
        flush();const temp=target(output.width,output.height);fullPass(output,temp,{mode:cmd.name==='sepia'?2:0,strength:cmd.params.k??1,dx:cmd.params.dx||0,dy:cmd.params.dy||0});fullPass(temp,output);continue;
      }
      if(cmd.kind==='path'&&blurOf(cmd.style)>0){
        flush();const src=target(output.width,output.height),horizontal=target(output.width,output.height),vertical=target(output.width,output.height);clear(src);
        const isolated={...cmd,style:{...cmd.style,globalAlpha:1,filter:'none',globalCompositeOperation:'source-over',clips:[]}},srcScene=new THREE.Scene();srcScene.add(...meshesFor(isolated));three.setRenderTarget(src);three.render(srcScene,drawCamera);
        const radius=blurOf(cmd.style);fullPass(src,horizontal,{mode:1,blurX:radius});fullPass(horizontal,vertical,{mode:1,blurY:radius});
        const image={texture:vertical.texture,width:output.width,height:output.height,premultiplied:true},style={...cmd.style,matrix:IDENTITY,filter:'none'},geometry=track(quadGeometry(0,0,output.width,output.height)),mesh=new THREE.Mesh(geometry,paintMaterial('#fff',style,image));mesh.frustumCulled=false;mesh.renderOrder=order++;scene.add(mesh);continue;
      }
      if(cmd.kind==='path'&&appendBatch(cmd))continue;
      flushBatch();
      if(['overlay','color'].includes(cmd.style.globalCompositeOperation)){
        flush();const layer=target(output.width,output.height);clear(layer);const isolated={...cmd,style:{...cmd.style,globalCompositeOperation:'source-over'}},srcScene=new THREE.Scene();srcScene.add(...meshesFor(isolated));three.setRenderTarget(layer);three.render(srcScene,drawCamera);const temp=target(output.width,output.height);fullPass(output,temp,{mode:cmd.style.globalCompositeOperation==='overlay'?4:5,source:layer});fullPass(temp,output);continue;
      }
      for(const mesh of meshesFor(cmd)){mesh.renderOrder=order++;scene.add(mesh);}
    }
    flush();
  }
  function renderSnapshot(source){
    if(memo.has(source))return memo.get(source);
    const rt=target(source.width,source.height),result={texture:rt.texture,width:source.width,height:source.height,premultiplied:true,target:rt};memo.set(source,result);clear(rt);
    runCommands(source._vkSurface?source.context._commands:source.commands,rt);return result;
  }
  function drawSurface(surface,output){
    if(!surface)return;const image=surface._vkSurface||surface._vkSnapshot?renderSnapshot(surface):nativeImage(surface),s=initialState();
    const geometry=track(quadGeometry(0,0,width,height)),mat=paintMaterial('#fff',s,image),mesh=new THREE.Mesh(geometry,mat),scene=new THREE.Scene();mesh.frustumCulled=false;scene.add(mesh);three.setRenderTarget(output);three.render(scene,camera);
  }
  function render(surface,output=null){beginFrame();const result=renderSnapshot(surface);if(output){clear(output);fullPass(result.target,output);}else fullPass(result.target,null);return output||stageCanvas;}
  function compose({background,under,content,post,bloom=0,grain=0,frame=0,scene3d}={}){
    beginFrame();const output=target();clear(output);drawSurface(background,output);drawSurface(under,output);
    if(scene3d?.scene&&scene3d?.camera){three.setRenderTarget(output);three.clearDepth();three.render(scene3d.scene,scene3d.camera);}
    drawSurface(content,output);
    if(bloom>0&&content){
      const src=renderSnapshot(content),smallW=Math.max(1,Math.round(width/4)),smallH=Math.max(1,Math.round(height/4)),small=target(smallW,smallH),horizontal=target(smallW,smallH),vertical=target(smallW,smallH);
      fullPass(src.target,small);fullPass(small,horizontal,{mode:1,blurX:3});fullPass(horizontal,vertical,{mode:1,blurY:3});
      const combined=target();fullPass(output,combined,{mode:3,bloom:vertical,strength:.42*bloom});fullPass(combined,output);
      fullPass(small,horizontal,{mode:1,blurX:11});fullPass(horizontal,vertical,{mode:1,blurY:11});fullPass(output,combined,{mode:3,bloom:vertical,strength:.34*bloom});fullPass(combined,output);
    }
    if(typeof post==='function'){const surface=createSurface(width,height);post(surface.context);drawSurface(surface,output);}else if(post)drawSurface(post,output);
    fullPass(output,null,{grain,frame});return stageCanvas;
  }
  function dispose(){if(disposed)return;for(const r of frameResources)r.dispose();for(const g of glyphCache.values())g.texture.dispose();for(const g of blurCache.values())g.target.dispose();for(const t of rampCache.values())t.dispose();for(const t of imageTextures)t.dispose();frameResources.clear();glyphCache.clear();blurCache.clear();rampCache.clear();imageTextures.clear();passGeometry.dispose();three.dispose();disposed=true;}
  return {render,compose,dispose,three,get info(){return three.info;}};
}
