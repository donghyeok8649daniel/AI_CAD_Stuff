// Geometry operations keep analytic lines, circles and arcs in the project.
export const copy=v=>structuredClone(v);
export const uid=()=>crypto.randomUUID().replaceAll('-','');
export const add=(a,b)=>({x:a.x+b.x,y:a.y+b.y});
export const sub=(a,b)=>({x:a.x-b.x,y:a.y-b.y});
export const mul=(a,k)=>({x:a.x*k,y:a.y*k});
export const dot=(a,b)=>a.x*b.x+a.y*b.y;
export const cross=(a,b)=>a.x*b.y-a.y*b.x;
export const len=a=>Math.hypot(a.x,a.y);
export const dist=(a,b)=>len(sub(a,b));
export const unit=a=>mul(a,1/Math.max(len(a),1e-12));
export const left=a=>({x:-a.y,y:a.x});
export const angle=a=>Math.atan2(a.y,a.x)*180/Math.PI;
export const norm=a=>((a+180)%360+360)%360-180;
export const rotate=(p,a)=>{const t=a*Math.PI/180;return {x:p.x*Math.cos(t)-p.y*Math.sin(t),y:p.x*Math.sin(t)+p.y*Math.cos(t)};};
export const entity=(kind,fields)=>({id:uid(),construction:false,kind,...fields});
export const line=(a,b)=>entity('line',{start:copy(a),end:copy(b)});
export const circle=(c,r)=>entity('circle',{center:copy(c),radius:r});
export const arc=(c,r,start,sweep)=>entity('arc',{center:copy(c),radius:r,start_angle:norm(start),sweep});
export function at(e,t){
  if(e.kind==='line')return add(e.start,mul(sub(e.end,e.start),t));
  if(['point','text'].includes(e.kind))return e.position;
  if(e.kind==='spline'){
    // Control splines use de Boor; interpolating splines receive exact server samples.
    const ps=e.points,n=ps.length,k=Math.min(3,n-1);
    if(e.style==='control'){
      const poles=e.closed?[...ps,...ps.slice(0,k)]:ps;
      const knots=e.closed?Array.from({length:n+2*k+1},(_,i)=>(i-k)/n):[...Array(k+1).fill(0),...Array.from({length:n-k-1},(_,i)=>(i+1)/(n-k)),...Array(k+1).fill(1)];
      let span=k;while(span<poles.length-1&&t>=knots[span+1])span++;
      const d=Array.from({length:k+1},(_,j)=>copy(poles[span-k+j]));
      for(let r=1;r<=k;r++)for(let j=k;j>=r;j--){const i=span-k+j,a=(t-knots[i])/(knots[j+1+span-r]-knots[i]);d[j]=add(mul(d[j-1],1-a),mul(d[j],a));}return d[k];
    }
    const m=e.closed?n:n-1,u=Math.min(t*m,m-1e-9),i=Math.floor(u),f=u-i;
    const get=j=>ps[e.closed?(j+n)%n:Math.max(0,Math.min(n-1,j))],a=get(i-1),b=get(i),c=get(i+1),d=get(i+2);
    return Object.fromEntries(['x','y'].map(key=>[key,.5*((2*b[key])+(-a[key]+c[key])*f+(2*a[key]-5*b[key]+4*c[key]-d[key])*f*f+(-a[key]+3*b[key]-3*c[key]+d[key])*f*f*f)]));
  }
  const a=(e.start_angle||0)+t*(e.sweep??360),v=rotate({x:(e.radius??e.radius_x)*Math.cos(a*Math.PI/180),y:(e.radius??e.radius_y)*Math.sin(a*Math.PI/180)},e.rotation||0);return add(e.center,v);
}
export function anchors(e){
  if(e.kind==='line')return [['start',e.start],['end',e.end]];
  if(e.kind==='arc')return [['start',at(e,0)],['end',at(e,1)],['center',e.center]];
  if(e.kind==='spline')return e.points.map((p,i)=>['point'+i,p]);
  return [[e.center?'center':'position',e.center||e.position]];
}
export function parameters(e){
  if(e.kind==='line')return [e.start.x,e.start.y,e.end.x,e.end.y];
  if(e.kind==='circle')return [e.center.x,e.center.y,e.radius];
  if(e.kind==='arc')return [e.center.x,e.center.y,e.radius,e.start_angle,e.sweep];
  if(e.kind==='ellipse')return [e.center.x,e.center.y,e.radius_x,e.radius_y,e.rotation];
  if(e.kind==='spline')return e.points.flatMap(p=>[p.x,p.y]);
  return [e.position.x,e.position.y,...(e.kind==='text'?[e.size,e.rotation]:[])];
}
export function threeArc(a,b,c,full=false){
  const v=sub(b,a),w=sub(c,a),den=2*cross(v,w);
  if(Math.abs(den)<1e-7)throw Error('세 점이 한 직선 위에 있습니다.');
  const center=add(a,{x:(len(v)**2*w.y-len(w)**2*v.y)/den,y:(v.x*len(w)**2-w.x*len(v)**2)/den}),r=dist(center,a);
  if(full)return circle(center,r);
  const start=angle(sub(a,center)),mid=(angle(sub(b,center))-start+360)%360,end=(angle(sub(c,center))-start+360)%360;
  return arc(center,r,start,mid<end?end:end-360);
}
export function closedLines(points){return points.map((p,i)=>line(p,points[(i+1)%points.length]));}
export function createGeometry(tool,p,o={}){
  const [a,b,c]=p,r=b?dist(a,b):0;
  if(tool==='line')return [line(a,b)];
  if(tool==='point')return [entity('point',{position:a})];
  if(tool==='text')return [entity('text',{position:a,text:o.text||'CAD',size:o.size||10,rotation:0,font:o.font||'Arial'})];
  if(tool==='rectangle'||tool==='center-rectangle'){const first=tool==='rectangle'?a:sub(mul(a,2),b);return closedLines([first,{x:b.x,y:first.y},b,{x:first.x,y:b.y}]);}
  if(tool==='rectangle-3'){const v=unit(sub(b,a)),h=mul(left(v),cross(v,sub(c,b)));return closedLines([a,b,add(b,h),add(a,h)]);}
  if(tool==='circle')return [circle(a,r)];
  if(tool==='circle-2')return [circle(mul(add(a,b),.5),r/2)];
  if(tool==='circle-3')return [threeArc(a,b,c,true)];
  if(tool==='arc-3')return [threeArc(a,b,c)];
  if(tool==='arc-center'){const start=angle(sub(b,a)),sweep=(angle(sub(c,a))-start+360)%360;return [arc(a,r,start,o.clockwise?sweep-360:sweep)];}
  if(tool==='ellipse'){const v=unit(sub(b,a));return [entity('ellipse',{center:a,radius_x:r,radius_y:Math.abs(cross(v,sub(c,a))),rotation:angle(v)})];}
  if(tool==='polygon'||tool==='polygon-inscribed'){const n=Math.max(3,Math.min(32,Math.round(o.count||6))),radius=tool==='polygon-inscribed'?r/Math.cos(Math.PI/n):r,phase=angle(sub(b,a))+(tool==='polygon-inscribed'?180/n:0);return closedLines(Array.from({length:n},(_,i)=>add(a,rotate({x:radius,y:0},phase+i*360/n))));}
  if(tool==='slot'||tool==='center-slot'){
    const first=tool==='slot'?a:sub(mul(a,2),b),v=unit(sub(b,first)),radius=Math.abs(cross(v,sub(c,first))),n=mul(left(v),radius),start=angle(n);
    return [line(add(first,n),add(b,n)),arc(b,radius,start,-180),line(sub(b,n),sub(first,n)),arc(first,radius,start+180,-180)];
  }
  if(tool==='spline-fit'||tool==='spline-control')return [entity('spline',{points:copy(p),style:tool==='spline-fit'?'fit':'control',closed:!!o.closed})];
  throw Error('선택한 도구의 입력을 확인하세요.');
}
export function transform(e,{dx=0,dy=0,degrees=0,scale=1,center={x:0,y:0},axis=null}={}){
  const f=p=>{let q=mul(sub(p,center),scale);if(axis){const v=unit(sub(axis.end,axis.start));q=add(axis.start,sub(mul(v,2*dot(sub(add(q,center),axis.start),v)),sub(add(q,center),axis.start)));return add(q,{x:dx,y:dy});}return add(add(rotate(q,degrees),center),{x:dx,y:dy});};
  const out=copy(e);if(e.start)out.start=f(e.start);if(e.end)out.end=f(e.end);if(e.center)out.center=f(e.center);if(e.position)out.position=f(e.position);if(e.points)out.points=e.points.map(f);
  for(const key of ['radius','radius_x','radius_y','size'])if(key in out)out[key]*=Math.abs(scale);
  if(e.kind==='arc'){out.start_angle=angle(sub(f(at(e,0)),out.center));if(axis)out.sweep=-out.sweep;}
  if(['ellipse','text'].includes(e.kind)){out.rotation=norm(axis?2*angle(sub(axis.end,axis.start))-e.rotation:e.rotation+degrees);if(axis&&e.kind==='text')throw Error('텍스트 반사는 먼저 다른 도형으로 바꾸어야 합니다. 텍스트는 이동·회전·배율을 사용하세요.');}
  return out;
}
export function parameter(e,p){
  if(e.kind==='line'){const v=sub(e.end,e.start);return dot(sub(p,e.start),v)/dot(v,v);}
  const a=angle(sub(p,e.center)),s=e.start_angle||0,d=e.sweep??360;
  return d>0?((a-s+360)%360)/d:-((s-a+360)%360)/d;
}
export function intersections(a,b,infiniteA=false,infiniteB=false){
  if(!['line','circle','arc'].includes(a.kind)||!['line','circle','arc'].includes(b.kind))return [];
  let pts=[];
  if(a.kind==='line'&&b.kind==='line'){const v=sub(a.end,a.start),w=sub(b.end,b.start),den=cross(v,w);if(Math.abs(den)>1e-10)pts=[add(a.start,mul(v,cross(sub(b.start,a.start),w)/den))];}
  else if(a.kind==='line'||b.kind==='line'){
    const l=a.kind==='line'?a:b,c=a.kind==='line'?b:a,v=sub(l.end,l.start),q=sub(l.start,c.center),aa=dot(v,v),bb=2*dot(q,v),cc=dot(q,q)-c.radius**2,d=bb*bb-4*aa*cc;
    if(d>=-1e-9){const s=Math.sqrt(Math.max(0,d));pts=[(-bb-s)/(2*aa),(-bb+s)/(2*aa)].map(t=>add(l.start,mul(v,t)));}
  }else{const v=sub(b.center,a.center),d=len(v);if(d>1e-9&&d<=a.radius+b.radius+1e-8&&d>=Math.abs(a.radius-b.radius)-1e-8){const x=(a.radius**2-b.radius**2+d*d)/(2*d),h=Math.sqrt(Math.max(0,a.radius**2-x*x)),mid=add(a.center,mul(v,x/d)),n=mul(left(v),h/d);pts=[add(mid,n),sub(mid,n)];}}
  const within=(e,p,inf)=>inf||e.kind==='circle'||(parameter(e,p)>=-1e-7&&parameter(e,p)<=1+1e-7)||dist(at(e,1),p)<1e-6;
  return pts.filter((p,i)=>within(a,p,infiniteA)&&within(b,p,infiniteB)&&!pts.slice(0,i).some(q=>dist(p,q)<1e-7));
}
function piece(e,from,to){const out=e.kind==='line'?line(at(e,from),at(e,to)):arc(e.center,e.radius,(e.start_angle||0)+(e.sweep??360)*from,(e.sweep??360)*(to-from));out.construction=e.construction;return out;}
export function trim(e,others,p){
  if(!['line','circle','arc'].includes(e.kind))throw Error('자르기는 직선·원·원호를 지원합니다.');
  const times=others.filter(o=>o.id!==e.id&&!o.construction).flatMap(o=>intersections(e,o).map(q=>parameter(e,q))).filter(t=>t>1e-7&&t<1-1e-7).sort((a,b)=>a-b).filter((t,i,a)=>!i||t-a[i-1]>1e-7),t=parameter(e,p);
  if(e.kind==='circle'){
    if(times.length<2)throw Error('원을 자르려면 다른 도형과 두 곳 이상 교차해야 합니다.');
    let upper=times.find(x=>x>t);if(upper===undefined)upper=times[0]+1;let lower=[...times].reverse().find(x=>x<t);if(lower===undefined)lower=times.at(-1)-1;
    return [piece(e,upper,lower+1)];
  }
  if(!times.length)throw Error('교차하는 경계가 없습니다. 전체 삭제는 삭제 버튼을 사용하세요.');
  const lower=[0,...times].filter(x=>x<t).at(-1)??0,upper=[...times,1].find(x=>x>t)??1,result=[];
  if(lower>1e-7)result.push(piece(e,0,lower));if(upper<1-1e-7)result.push(piece(e,upper,1));return result;
}
export function split(e,p){
  if(!['line','arc'].includes(e.kind))throw Error('분할은 직선·원호를 지원합니다. 원은 자르기를 사용하세요.');
  const t=parameter(e,p);if(t<.001||t>.999)throw Error('끝점 사이를 클릭하세요.');return [piece(e,0,t),piece(e,t,1)];
}
export function extend(e,others,p){
  if(e.kind!=='line')throw Error('연장은 현재 직선을 지원합니다.');
  const end=dist(p,e.start)>dist(p,e.end),ts=others.filter(o=>o.id!==e.id).flatMap(o=>intersections(e,o,true).map(q=>parameter(e,q))).filter(t=>end?t>1+1e-7:t< -1e-7).sort((a,b)=>end?a-b:b-a);
  if(!ts.length)throw Error('연장 방향에 경계가 없습니다.');return [piece(e,end?0:ts[0],end?ts[0]:1)];
}
export function offset(entities,d){
  const out=entities.map(e=>{
    if(e.kind==='line'){const n=mul(left(unit(sub(e.end,e.start))),d);return {...line(add(e.start,n),add(e.end,n)),construction:e.construction};}
    if(['circle','arc'].includes(e.kind)){if(e.radius+d<=.01)throw Error('간격이 반지름보다 큽니다.');return {...copy(e),id:uid(),radius:e.radius+d};}
    throw Error('간격띄우기는 직선·연결된 직선 외곽·원·원호를 지원합니다.');
  });
  for(let i=0;i<entities.length;i++)for(let j=i+1;j<entities.length;j++)if(entities[i].kind===entities[j].kind&&entities[i].kind==='line'){
    const hit=intersections(out[i],out[j],true,true)[0];if(!hit)continue;
    for(const a of ['start','end'])for(const b of ['start','end'])if(dist(entities[i][a],entities[j][b])<1e-5){out[i][a]=copy(hit);out[j][b]=copy(hit);}
  }return out;
}
export function corner(a,b,d,fillet){
  if(a.kind!=='line'||b.kind!=='line')throw Error('두 직선을 선택하세요.');
  const v=intersections(a,b,true,true)[0];if(!v||d<=0)throw Error('평행선이거나 유효하지 않은 크기입니다.');
  const far=e=>dist(e.start,v)>dist(e.end,v)?e.start:e.end,pa=far(a),pb=far(b),u=unit(sub(pa,v)),w=unit(sub(pb,v)),theta=Math.acos(Math.max(-1,Math.min(1,dot(u,w))));
  if(theta<.001||Math.PI-theta<.001)throw Error('모서리 각도가 너무 작습니다.');
  const cut=fillet?d/Math.tan(theta/2):d;if(cut>=Math.min(dist(pa,v),dist(pb,v)))throw Error('모서리 크기가 선보다 큽니다.');
  const x=add(v,mul(u,cut)),y=add(v,mul(w,cut)),l1=line(pa,x),l2=line(y,pb);l1.id=a.id;l2.id=b.id;
  if(!fillet)return [l1,line(x,y),l2];
  const c=add(v,mul(unit(add(u,w)),d/Math.sin(theta/2))),s=angle(sub(x,c)),sweep=norm(angle(sub(y,c))-s);return [l1,arc(c,d,s,sweep),l2];
}
export function toEntities(sketch){
  const g=copy(sketch);if(g.sketch_mode==='entities')return g;
  g.sketch_mode='entities';g.entities=closedLines(g.points);g.entity_constraints=[];g.profiles=[];
  const ids=g.entities.map(e=>e.id),constraint=(kind,a,b,fields={})=>g.entity_constraints.push({id:uid(),kind,a,b,...fields});
  ids.forEach((id,i)=>constraint('coincident',id,ids[(i+1)%ids.length],{a_point:'end',b_point:'start'}));
  for(const c of g.constraints||[]){if(c.kind==='angle'){const helper=line(g.points[c.a],g.points[c.b]);helper.construction=true;g.entities.push(helper);constraint('coincident',helper.id,ids[c.a]);constraint('coincident',helper.id,ids[c.b],{a_point:'end'});constraint('angle',helper.id,'',{value:c.value});}else constraint(c.kind,ids[c.a],c.kind==='fixed'?'':ids[c.b],{value:c.value,x:c.x,y:c.y});}
  for(const h of g.holes)g.entities.push(circle({x:h.x,y:h.y},h.diameter/2));
  g.constraints=[];g.holes=[];return g;
}
