// Persistent branching design history. Changes are data; never executable code.
const copy=value=>structuredClone(value);
const same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
const blocked=new Set(['__proto__','constructor','prototype']);
export function differences(before,after,path=[]){
  if(same(before,after))return [];
  if(before&&after&&typeof before==='object'&&typeof after==='object'&&Array.isArray(before)===Array.isArray(after)){
    if(!Array.isArray(before)||before.length===after.length){
      const result=[];
      for(const key of new Set([...Object.keys(before),...Object.keys(after)])){
        const segment=Array.isArray(before)?Number(key):key,p=[...path,segment];
        if(!Object.hasOwn(after,key))result.push({path:p,operation:'remove',existed:true,before:copy(before[key]),after:null});
        else if(!Object.hasOwn(before,key))result.push({path:p,operation:'set',existed:false,before:null,after:copy(after[key])});
        else result.push(...differences(before[key],after[key],p));
      }
      return result;
    }
  }
  return [{path,operation:'set',existed:true,before:copy(before),after:copy(after)}];
}
export function replay(design,changes){
  const result=copy(design);
  for(const c of changes){
    if(!c.path.length||c.path.some(k=>blocked.has(k)))throw new Error('허용되지 않는 이력 경로입니다.');
    let node=result;
    for(const key of c.path.slice(0,-1)){if(!Object.hasOwn(node,key))throw new Error('이력 경로가 없습니다.');node=node[key];}
    const key=c.path.at(-1);
    if(c.operation==='remove')delete node[key];else node[key]=copy(c.after);
  }
  return result;
}
function identifier(){return 'step-'+crypto.randomUUID().replaceAll('-','');}
export class DesignJournal{
  constructor(design,label='설계 시작',saved=null,context={}){
    this.data=saved?copy(saved):{version:1,base:copy(design),entries:[{id:identifier(),parent:null,label,created_at:new Date().toISOString(),source:context.source||'manual',changes:[],context}],cursor:'',head:''};
    if(!saved)this.data.cursor=this.data.head=this.data.entries[0].id;
    this.cache=new Map();this.index=new Map(this.data.entries.map(e=>[e.id,e]));
  }
  path(id=this.data.head){const result=[];while(id){const step=this.index.get(id);if(!step)throw new Error('이력 단계가 없습니다.');result.push(step);id=step.parent;}return result.reverse();}
  at(id){if(this.cache.has(id))return copy(this.cache.get(id));let result=copy(this.data.base);for(const step of this.path(id))result=replay(result,step.changes);this.cache.set(id,result);if(this.cache.size>10)this.cache.delete(this.cache.keys().next().value);return copy(result);}
  append(before,after,label,context={}){
    const changes=differences(before,after);
    if(!changes.length&&!context.tool_actions?.length)return;
    const entry={id:identifier(),parent:this.data.cursor,label,created_at:new Date().toISOString(),source:context.source||'manual',changes,context:copy(context)};
    this.data.entries.push(entry);this.index.set(entry.id,entry);this.data.cursor=this.data.head=entry.id;
    this.cache.set(entry.id,copy(after));if(this.cache.size>10)this.cache.delete(this.cache.keys().next().value);
  }
  move(id){if(!this.index.has(id))throw new Error('이력 단계가 없습니다.');if(!this.path().some(e=>e.id===id))this.data.head=id;this.data.cursor=id;}
  export(){return copy(this.data);}
}

let database;
function openDatabase(){if(!database)database=new Promise((resolve,reject)=>{const request=indexedDB.open('prompt-cad-studio',1);request.onupgradeneeded=()=>request.result.createObjectStore('workspace');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});return database;}
export async function saveWorkspace(value){const db=await openDatabase();await new Promise((resolve,reject)=>{const tx=db.transaction('workspace','readwrite');tx.objectStore('workspace').put(value,'last');tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}
export async function loadWorkspace(){const db=await openDatabase();const saved=await new Promise((resolve,reject)=>{const request=db.transaction('workspace').objectStore('workspace').get('last');request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);});return saved||JSON.parse(localStorage.getItem('prompt-cad-last')||'null');}

const labels={parts:'부품',geometry:'기본 형상',features:'피처',sketch:'스케치',constraints:'스케치 구속',mates:'조립 구속',transform:'위치·회전',points:'외곽점',holes:'구멍',length:'길이',width:'폭',thickness:'두께/깊이',diameter:'직경',hole_diameter:'구멍 직경',hole_spacing:'구멍 간격',face:'면 번호',normal:'면 법선',origin:'스케치 원점',x_direction:'스케치 X축',support_feature:'이전 피처',support_face_count:'참조 형상의 면 수',fixed:'월드 고정',operation:'가공 방식',parent:'부모 부품',child:'자식 부품',parent_anchor:'부모 기준점',child_anchor:'자식 기준점',kind:'종류',id:'ID',name:'이름',color:'색상',value:'치수값',a:'점 A (0부터)',b:'점 B (0부터)',entities:'스케치 요소',entity_constraints:'요소 구속'};
const kinds={round_specimen:'베지어 단면 → X축 360° 회전',flat_specimen:'베지어 외곽 스케치 → 돌출',wafer:'원 스케치 → 돌출 → 플랫 절삭',plate:'사각형 스케치 → 돌출 → 구멍 패턴',link:'캡슐 스케치 → 돌출 → 양단 구멍',bracket:'바닥·수직판 돌출 → 합치기 → 두 면 구멍',cylinder:'동심원 스케치 → 돌출',extrusion:'XY 스케치 → 돌출'};
const node=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
function pretty(value){return value===undefined?'없음':typeof value==='object'?JSON.stringify(value,null,2):String(value);}
function row(parent,title,value){const block=node('div',undefined,'history-detail-block');block.append(node('strong',title));const pre=node('pre',pretty(value));block.append(pre);parent.append(block);}
export class HistoryInspector{
  constructor(getState,checkout,selectPart){
    this.getState=getState;this.checkout=checkout;this.selectPart=selectPart;
    this.dialog=node('dialog',undefined,'history-dialog');this.dialog.id='history-dialog';
    this.dialog.innerHTML='<div class="dialog-head"><div><span class="overline">DESIGN HISTORY / FEATURES</span><h2>설계 작업 기록</h2></div><button id="history-close" class="icon-btn" aria-label="작업 기록 닫기">×</button></div><p class="field-help">저장·다시 열기·CAD JSON에 기록이 보존됩니다. 이전 단계에서 새 작업을 시작해도 기존 분기를 삭제하지 않습니다.</p><div class="history-tabs"><button id="history-steps-tab">전체 작업 기록</button><button id="history-features-tab">현재 피처 구조</button><span id="history-count"></span></div><div class="history-layout"><nav id="history-list" aria-label="저장된 작업 단계"></nav><section id="history-detail"></section></div>';
    document.body.append(this.dialog);this.$=id=>this.dialog.querySelector('#'+id);
    this.$('history-close').onclick=()=>this.dialog.close();this.$('history-steps-tab').onclick=()=>this.openSteps();this.$('history-features-tab').onclick=()=>this.features();
  }
  open(id){this.openSteps(id);if(!this.dialog.open)this.dialog.showModal();}
  openSteps(id){const s=this.getState(),j=s.journal,active=new Set(j.path(j.data.cursor).map(e=>e.id));this.$('history-list').replaceChildren();this.$('history-count').textContent=`총 ${j.data.entries.length}단계 · 모든 분기 보존`;
    for(const [i,e] of j.data.entries.entries()){const b=node('button',undefined,'history-step'+(e.id===j.data.cursor?' current':''));b.append(node('strong',`${i+1}. ${e.label}`),node('small',`${new Date(e.created_at).toLocaleString('ko-KR')} · ${active.has(e.id)?'현재 경로':'다른 단계/분기'}`));b.onclick=()=>this.detail(e.id);this.$('history-list').append(b);}
    this.detail(id||j.data.cursor);
  }
  detail(id){const s=this.getState(),j=s.journal,e=j.index.get(id),design=j.at(id),panel=this.$('history-detail');panel.replaceChildren();panel.append(node('h3',e.label),node('p',`${new Date(e.created_at).toLocaleString('ko-KR')} · ${e.source==='openai'?'OpenAI 설계':e.source==='local'?'로컬 치수 명령':e.source==='import'?'파일 가져오기':'직접 설계'}`,'field-help'));
    const show=node('button','이 단계 형상으로 이동','primary');show.id='history-checkout';show.onclick=async()=>{try{await this.checkout(id);this.dialog.close();}catch(error){row(panel,'이 단계의 형상을 복원하지 못했습니다',error.message);}};panel.append(show);
    if(e.context.part_id){const part=design.parts.find(p=>p.id===e.context.part_id);row(panel,'대상 부품',part?`${part.name} · ${part.id}`:e.context.part_id);}
    if(e.context.face)row(panel,'선택한 면과 기준 피처',e.context.face);
    if(e.context.prompt)row(panel,'설계 요청',e.context.prompt);
    if(e.context.tool_actions?.length){panel.append(node('h3','스케치 도구 사용 순서'));for(const [i,a] of e.context.tool_actions.entries()){const detail=node('details',undefined,'history-action');detail.append(node('summary',`${i+1}. ${a.tool}${a.after?.length?' · 요소 '+a.after.length+'개':''}`));row(detail,'좌표·치수·구속 참조',a);panel.append(detail);}}
    if(e.context.feature_id)row(panel,'피처 ID',e.context.feature_id);
    if(!e.changes.length){row(panel,e.source==='import'?'파일에 포함된 초기 설계 (이전 작업은 소급 생성하지 않음)':'초기 설계',design);return;}
    const table=node('table',undefined,'history-changes');const head=node('tr');['대상/항목','이전','이후'].forEach(t=>head.append(node('th',t)));table.append(head);
    for(const change of e.changes){const tr=node('tr');let path=change.path.map(v=>labels[v]||String(v));if(change.path[0]==='parts'&&typeof change.path[1]==='number'){const p=design.parts[change.path[1]];if(p)path[1]=p.name+' ('+p.id+')';}tr.append(node('td',path.join(' / ')),node('td',change.existed?pretty(change.before):'없음'),node('td',change.operation==='remove'?'제거됨':pretty(change.after)));table.append(tr);}
    panel.append(table);
  }
  features(){const s=this.getState(),list=this.$('history-list'),panel=this.$('history-detail');list.replaceChildren();panel.replaceChildren();this.$('history-count').textContent='현재 형상의 스케치·가공·구속 참조';
    for(const p of s.design.parts){const b=node('button',p.name,'history-step');b.onclick=()=>this.partFeatures(p);list.append(b);}this.partFeatures(s.design.parts.find(p=>p.id===s.selected)||s.design.parts[0]);
  }
  partFeatures(p){const s=this.getState(),panel=this.$('history-detail');panel.replaceChildren();panel.append(node('h3',p.name+' · 피처 구조'));const choose=node('button','3D에서 이 부품 선택');choose.onclick=()=>{this.dialog.close();this.selectPart(p.id);};panel.append(choose);
    row(panel,'기본 피처 · '+(kinds[p.geometry.kind]||p.geometry.kind),{id:'base',plane:p.geometry.kind==='round_specimen'?'XY 단면 / X 회전축':'XY',...p.geometry});
    for(const [i,f] of (p.features||[]).entries()){row(panel,`${i+1}. ${f.name} · ${f.operation==='add'?'돌출':'파내기'}`,{id:f.id,support_feature:f.support_feature||'이전 버전: 면 번호 참조',face:f.face,face_count:f.support_face_count,origin:f.origin,normal:f.normal,x_direction:f.x_direction,depth:f.sketch.thickness,sketch:f.sketch});}
    row(panel,'월드 고정 / 배치',{fixed:p.fixed,transform:p.transform});
    for(const mate of s.design.mates||[])if(mate.parent===p.id||mate.child===p.id)row(panel,'조립 구속 · '+mate.id,mate);
  }
}
