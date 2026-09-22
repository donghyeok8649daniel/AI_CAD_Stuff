import test from 'node:test';
import assert from 'node:assert/strict';
import * as G from '../static/sketch-geometry.js';
import {DesignJournal} from '../static/history.js';
const p=(x,y)=>({x,y}),near=(a,b)=>assert.ok(Math.abs(a-b)<1e-7,`${a} != ${b}`);
test('three point circles and clockwise/anticlockwise arcs keep exact points',()=>{
  const e=G.threeArc(p(10,0),p(0,10),p(-10,0));near(e.radius,10);near(e.sweep,180);
  assert.ok(G.dist(G.at(e,0),p(10,0))<1e-7);assert.ok(G.dist(G.at(e,1),p(-10,0))<1e-7);
  const cw=G.threeArc(p(10,0),p(0,-10),p(-10,0));near(cw.sweep,-180);
  assert.throws(()=>G.threeArc(p(0,0),p(1,1),p(2,2)));
});
test('rectangle variants retain right angles',()=>{
  for(const tool of ['rectangle','center-rectangle','rectangle-3']){
    const e=G.createGeometry(tool,[p(0,0),p(10,5),p(3,12)]);assert.equal(e.length,4);
    for(let i=0;i<4;i++){assert.ok(G.dist(e[i].end,e[(i+1)%4].start)<1e-7);near(G.dot(G.sub(e[i].end,e[i].start),G.sub(e[(i+1)%4].end,e[(i+1)%4].start)),0);}
  }
});
test('slot is a connected loop of analytic lines and semicircles',()=>{
  const e=G.createGeometry('slot',[p(0,0),p(20,0),p(10,5)]);assert.equal(e.length,4);
  for(let i=0;i<4;i++)assert.ok(G.dist(G.at(e[i],1),G.at(e[(i+1)%4],0))<1e-7);
  near(e[1].radius,5);near(e[3].radius,5);
});
test('line/circle and circle/circle intersections distinguish tangency',()=>{
  const c=G.circle(p(0,0),5),a=G.line(p(-10,0),p(10,0));assert.equal(G.intersections(a,c).length,2);
  assert.equal(G.intersections(G.line(p(-10,5),p(10,5)),c).length,1);
  assert.equal(G.intersections(c,G.circle(p(10,0),5)).length,1);
  assert.equal(G.intersections(c,G.circle(p(8,0),5)).length,2);
});
test('trim removes only the clicked region of a line or circle',()=>{
  const a=G.line(p(-10,0),p(10,0)),b=G.line(p(0,-10),p(0,10));
  const t=G.trim(a,[a,b],p(5,0));assert.equal(t.length,1);near(t[0].end.x,0);near(t[0].start.x,-10);
  const c=G.circle(p(0,0),5),arcs=G.trim(c,[c,b],p(5,0));assert.equal(arcs.length,1);near(arcs[0].sweep,180);assert.ok(G.at(arcs[0],.5).x<0);
});
test('extend chooses the closest forward boundary and split retains length',()=>{
  const a=G.line(p(0,0),p(5,0)),b=G.line(p(10,-5),p(10,5));const e=G.extend(a,[b],p(4,0));near(e[0].end.x,10);
  const split=G.split(a,p(2,0));near(G.dist(split[0].start,split[0].end),2);near(G.dist(split[1].start,split[1].end),3);
});
test('polygon offsets miter corners; circle offset retains its center',()=>{
  const rect=G.closedLines([p(0,0),p(10,0),p(10,10),p(0,10)]),off=G.offset(rect,1);
  near(off[0].start.x,1);near(off[0].start.y,1);near(off[0].end.x,9);
  for(let i=0;i<4;i++)assert.ok(G.dist(off[i].end,off[(i+1)%4].start)<1e-7);
  near(G.offset([G.circle(p(3,4),10)],2)[0].radius,12);
});
test('fillet meets both lines tangentially',()=>{
  const a=G.line(p(10,0),p(0,0)),b=G.line(p(0,0),p(0,10));
  const [l,arc,r]=G.corner(a,b,2,true);near(arc.radius,2);near(arc.center.x,2);near(arc.center.y,2);
  assert.ok(G.dist(l.end,G.at(arc,0))<1e-7);assert.ok(G.dist(r.start,G.at(arc,1))<1e-7);
  near(G.dot(G.sub(l.end,arc.center),G.sub(l.end,l.start)),0);
});
test('mirror reverses arc winding without changing radius',()=>{
  const e=G.arc(p(4,0),2,0,90),m=G.transform(e,{axis:G.line(p(0,-10),p(0,10))});near(m.center.x,-4);near(m.radius,2);near(m.sweep,-90);
  assert.ok(G.dist(G.at(m,0),p(-6,0))<1e-7);assert.ok(G.dist(G.at(m,1),p(-4,2))<1e-7);
});
test('legacy hole conversion contains no unexpected center properties',()=>{
  const g=G.toEntities({points:[p(0,0),p(30,0),p(30,30),p(0,30)],holes:[{x:10,y:10,diameter:4}],constraints:[],thickness:3});
  assert.equal(g.entities.length,5);assert.deepEqual(g.entities[4].center,p(10,10));assert.equal(g.entity_constraints.length,4);
});
test('control spline closed endpoint is continuous',()=>{
  const e=G.entity('spline',{style:'control',closed:true,points:[p(-10,0),p(0,10),p(10,0),p(0,-10)]});
  assert.ok(G.dist(G.at(e,0),G.at(e,1))<1e-7);
});
test('journal restores old geometry and retains branches after more than 30 steps',()=>{
  const base={name:'base',parts:[{id:'a',height:1}]},j=new DesignJournal(base);let previous=base;
  for(let i=2;i<=50;i++){const next={...base,parts:[{id:'a',height:i}]};j.append(previous,next,'높이');previous=next;}
  const oldHead=j.data.head,root=j.data.entries[0].id;j.move(root);j.append(base,{...base,name:'branch'},'분기');
  assert.equal(j.data.entries.length,51);assert.equal(j.at(oldHead).parts[0].height,50);assert.equal(j.at(root).parts[0].height,1);
  const restored=new DesignJournal(null,'',j.export());assert.equal(restored.at(restored.data.cursor).name,'branch');
  restored.move(oldHead);assert.equal(restored.data.head,oldHead);assert.equal(restored.path().length,50);
});
