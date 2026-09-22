import { CADViewer } from './viewer.js';
import { SketchEditor } from './sketch.js';
import { DesignJournal, HistoryInspector, loadWorkspace, saveWorkspace } from './history.js';

const $=id=>document.getElementById(id), clone=value=>structuredClone(value);
const state={catalog:[],design:null,result:null,selected:null,mode:'specimen',history:[],historyIndex:-1,journal:null,persisting:0,projectId:null,dirty:false,busy:false,pending:null,hidden:new Set(),status:null};
const symbols={round_specimen:'⌁',flat_specimen:'▱',wafer:'◯',link:'⊙',plate:'▦',bracket:'∟',cylinder:'◉',extrusion:'⬡',robot_arm:'⌁'};
const subtitles={round_specimen:'목이 얇은 원통형 · 매끄러운 곡선 전이',flat_specimen:'평판형 인장 시편 · 평행부와 그립',wafer:'실리콘 웨이퍼 · 원판과 플랫',link:'양단 관통 구멍 · 연결 링크',plate:'기계 부품 · 직사각형 구멍판',bracket:'직각 브래킷 · 두 면의 관통 구멍',cylinder:'원통과 튜브 · 회전 부품',extrusion:'선 · 원 · 호 · 스플라인 기반 돌출',robot_arm:'베이스 · 두 링크 · 연결 핀'};
let viewer,toastTimer,sketchEditor,historyInspector;

function el(tag,className,text){const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;}
function toast(message,error=false){clearTimeout(toastTimer);$('toast').textContent=message;$('toast').classList.toggle('error',error);$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,error?8000:3500);}
async function api(path,data,method='POST'){
  const options=data===undefined?{}:{method,headers:{'Content-Type':'application/json','X-CAD-Request':'1'},body:JSON.stringify(data)};
  const response=await fetch(path,options);
  if(!response.ok){let body;try{body=await response.json();}catch{throw new Error(`서버 응답 오류 (${response.status})`);}const detail=typeof body.detail==='string'?body.detail:'설계 요청을 처리하지 못했습니다.';throw new Error(detail+(body.issues?'\n'+body.issues.map(i=>i.message).join('\n'):''));}
  return response.json();
}
function busy(on,text='CAD 형상 생성 중'){
  state.busy=on;$('busy-overlay').hidden=!on;$('busy-text').textContent=text;
  refreshControls();
}
function refreshControls(){
  document.querySelectorAll('button, input, select, textarea').forEach(n=>{if(n.id!=='prompt')n.disabled=state.busy;});
  if(state.pending){for(const id of ['dimension-form','part-tree','templates','constraints-panel'])$(id).querySelectorAll('button,input,textarea,select').forEach(n=>n.disabled=true);for(const id of ['new-part','sketch-tool','duplicate-part','remove-part','export-step','export-stl','export-autodesk','face-sketch','assembly-mate','save-project','download-project','open-project','undo','redo','project-name','part-color'])$(id).disabled=true;}
  document.querySelectorAll('#timeline button').forEach(b=>b.disabled=state.busy||!!state.pending);
  $('undo').disabled=state.busy||!!state.pending||state.historyIndex<=0;
  $('redo').disabled=state.busy||!!state.pending||state.historyIndex>=state.history.length-1;
  $('remove-part').disabled=state.busy||!!state.pending||!state.design||state.design.parts.length<=1;
  if(state.design&&state.design.parts.length>=12)$('new-part').disabled=true;
  if($('provider').value==='openai'&&!state.status?.api_configured)$('generate-draft').disabled=true;
  const constrained=state.design?.mates?.some(m=>m.child===state.selected)||selectedPart()?.fixed;
  if(sketchEditor?.dialog.open)sketchEditor.$('sketch-operation').disabled=!sketchEditor.context?.feature;
  if(constrained)document.querySelectorAll('#transform-fields input').forEach(n=>n.disabled=true);
}
function selectedPart(){return state.design?.parts.find(p=>p.id===state.selected)||state.design?.parts[0];}
function entry(kind){return state.catalog.find(x=>x.kind===kind);}
function requireReady(){if(state.busy)return false;if(state.pending){toast('설계 초안을 적용하거나 취소한 후 진행하세요.');return false;}return true;}
async function persist(){state.persisting++;try{await saveWorkspace({project:project(),id:state.projectId});$('save-state').textContent='형상·작업 기록 저장됨';}catch{toast('작업 기록 자동 저장에 실패했습니다. 설계 파일을 내보내거나 프로젝트를 저장하세요. 기록은 현재 메모리에 남아 있습니다.',true);}finally{state.persisting--;}}
function project(){return {format:'prompt-cad-project',version:2,design:clone(state.design),prompt:$('prompt').value,history:state.journal?.export()||null};}
function updateMetadata(result){
  const d=result.design,s=result.stats;$('model-title').textContent=d.name;$('model-subtitle').textContent=d.parts.length>1?'부품을 선택해 치수와 배치를 편집하세요.':subtitles[d.parts[0].geometry.kind];
  $('viewport-kicker').textContent=d.mode==='specimen'?'SPECIMEN / PARAMETRIC':'COMPONENT / ASSEMBLY';
  const f=n=>new Intl.NumberFormat('ko-KR',{maximumFractionDigits:2}).format(n);
  $('bounds-value').textContent=s.bounds.map(f).join(' × ');$('volume-value').textContent=f(s.volume);$('solid-value').textContent=s.parts;
  $('valid-badge').textContent=s.valid?'유효한 솔리드':'형상 확인 필요';
  const collisions=s.collisions||[];$('collision-notice').hidden=!collisions.length;
  $('collision-notice').textContent=collisions.length?`부품 간 체적 간섭 ${collisions.length}건 · 부품의 위치와 간격을 확인하세요. 부피는 개별 부품의 합입니다.`:'';
}
function commit(result,label,{reset=false,record=true,fit=true,context={},historyCursor=null}={}){
  const before=state.design,added=result.design.parts.find(p=>!before?.parts.some(old=>old.id===p.id));
  const metadata={part_id:added?.id||state.selected,part_name:selectedPart()?.name||'',...context};
  if(!state.journal)state.journal=new DesignJournal(result.design,label,null,metadata);
  else if(record&&before)state.journal.append(before,result.design,label,metadata);
  if(historyCursor)state.journal.move(historyCursor);
  state.history=state.journal.path();state.historyIndex=state.history.findIndex(e=>e.id===state.journal.data.cursor);
  state.design=clone(result.design);state.result=result;state.pending=null;state.dirty=false;state.mode=result.design.mode;
  if(!state.design.parts.some(p=>p.id===state.selected))state.selected=state.design.parts[0].id;
  state.hidden=new Set([...state.hidden].filter(id=>state.design.parts.some(p=>p.id===id)));
  if(viewer){viewer.load(result,fit);viewer.select(state.selected);state.hidden.forEach(id=>viewer.setVisibility(id,false));}
  $('draft-banner').hidden=true;$('save-state').textContent='브라우저 저장됨';$('project-name').value=state.design.name;
  $('tree-title').textContent=state.design.name;updateMetadata(result);renderTree();renderInspector();renderTemplates();renderTimeline();refreshControls();persist();
}
async function build(design,label,options){
  busy(true);try{const result=await api('/api/build',design);commit(result,label,options);return result;}finally{busy(false);}
}
function renderTree(){
  const list=$('part-tree');list.replaceChildren();$('part-count').textContent=String(state.design.parts.length).padStart(2,'0');
  for(const part of state.design.parts){const row=el('div','part-row'+(part.id===state.selected?' selected':''));row.setAttribute('role','listitem');
    const visibility=el('button','visibility-button',state.hidden.has(part.id)?'○':'◉');visibility.title='미리보기 표시 전환';visibility.setAttribute('aria-label',`${part.name} 표시 전환`);visibility.onclick=()=>{if(state.hidden.has(part.id))state.hidden.delete(part.id);else state.hidden.add(part.id);viewer?.setVisibility(part.id,!state.hidden.has(part.id));renderTree();};
    const button=el('button','part-select');button.setAttribute('aria-label',`${part.name} 선택`);const dot=el('span','part-dot');dot.style.background=part.color;button.append(dot,el('span','name',part.name));button.onclick=()=>selectPart(part.id);row.append(visibility,button);list.append(row);
  }
}
async function selectPart(id){
  if(!requireReady())return;
  if(state.dirty){try{await applyDimensions();}catch{return;}}
  state.selected=id;viewer?.select(id);renderTree();renderInspector();
}
function numericField(key,label,value,unit,transform=false){
  const row=el('label',transform?'transform-field':'dimension-row');row.append(el('span',null,label));
  const box=el('div',transform?'':'dimension-input');
  const input=document.createElement(key==='hole_count'?'select':'input');input.id=(transform?'t-':'d-')+key;input.setAttribute('aria-label',label);
  if(key==='hole_count'){for(const v of [0,2,4]){const option=el('option',null,String(v));option.value=v;input.append(option);}input.value=value;}
  else{input.type='number';input.step='any';input.required=true;input.value=value;input.min=transform?(key.startsWith('r')?-360:-5000):(key==='flat_depth'||key==='bore_diameter'?0:.01);input.max=transform?(key.startsWith('r')?360:5000):2000;}
  box.append(input);if(!transform)box.append(el('span',null,unit));row.append(box);return row;
}
function renderInspector(){
  const p=selectedPart();if(!p)return;
  $('selected-title').textContent=p.name;$('selected-kind').textContent=p.geometry.kind.replaceAll('_',' ').toUpperCase();$('part-name').value=p.name;$('part-color').value=p.color;
  const fields=$('dimension-fields');fields.replaceChildren();
  for(const field of entry(p.geometry.kind).fields)fields.append(numericField(field.key,field.label,p.geometry[field.key],field.unit));
  const transforms=$('transform-fields');transforms.replaceChildren();for(const key of ['x','y','z','rx','ry','rz'])transforms.append(numericField(key,key.startsWith('r')?key.slice(1).toUpperCase()+' 회전 °':key.toUpperCase()+' mm',p.transform[key],'',true));
  $('sketch-fields').hidden=p.geometry.kind!=='extrusion'||p.geometry.sketch_mode==='entities';
  if(p.geometry.kind==='extrusion'){$('sketch-points').value=p.geometry.points.map(v=>`${v.x}, ${v.y}`).join('\n');$('sketch-holes').value=p.geometry.holes.map(v=>`${v.x}, ${v.y}, ${v.diameter}`).join('\n');}
  $('geometry-note').textContent=p.geometry.kind.includes('specimen')?'전이부는 3차 베지어 곡선입니다. 특정 시험 규격의 인증·물성 해석은 포함하지 않습니다.':p.geometry.kind==='extrusion'?'2D 편집기에서 도형과 치수·구속을 편집하세요. 닫힌 영역을 선택해 실제 솔리드로 돌출합니다.':'부품의 로컬 치수와 월드 위치를 편집합니다. 조립 구속으로 기준점과 관절을 연결할 수 있습니다. 부모 치수·각도 변경 시 자식 배치도 갱신됩니다.';
  renderConstraintsPanel(p);
  $('form-error').hidden=true;state.dirty=false;
  refreshControls();
}
function parseRows(text,count){
  return text.split(/\r?\n/).filter(line=>line.trim()).map((line,i)=>{const parts=line.trim().split(/\s*,\s*|\s+/).map(Number);if(parts.length!==count||parts.some(v=>!Number.isFinite(v)))throw new Error(`스케치 ${i+1}번째 줄에 ${count}개의 숫자를 입력하세요.`);return count===2?{x:parts[0],y:parts[1]}:{x:parts[0],y:parts[1],diameter:parts[2]};});
}
async function applyDimensions(){
  if(!state.design||state.pending)return;
  if(!$('dimension-form').reportValidity())throw new Error('입력한 치수와 이름을 확인하세요.');
  const design=clone(state.design),p=design.parts.find(p=>p.id===state.selected);p.name=$('part-name').value.trim();p.color=$('part-color').value;
  for(const field of entry(p.geometry.kind).fields)p.geometry[field.key]=Number($('d-'+field.key).value);
  for(const key of Object.keys(p.transform))p.transform[key]=Number($('t-'+key).value);
  try{
    if(p.geometry.kind==='extrusion'&&p.geometry.sketch_mode!=='entities'){p.geometry.points=parseRows($('sketch-points').value,2);p.geometry.holes=parseRows($('sketch-holes').value,3);}
    await build(design,`${p.name} 치수 수정`,{fit:false});$('form-error').hidden=true;
  }catch(error){$('form-error').textContent=error.message;$('form-error').hidden=false;throw error;}
}
async function ensureApplied(){if(state.dirty)await applyDimensions();}
function markDirty(){state.dirty=true;$('save-state').textContent='치수 적용 전';$('form-error').hidden=true;}
function renderTemplates(){
  document.querySelectorAll('[data-mode]').forEach(b=>b.classList.toggle('active',b.dataset.mode===state.mode));
  const list=$('templates');list.replaceChildren();
  for(const item of state.catalog.filter(x=>x.mode===state.mode)){
    const button=el('button','template-card');button.append(el('span','template-icon',symbols[item.kind]));const text=el('span',null,item.title);text.append(el('small',null,item.kind==='robot_arm'?'5개 부품 · 관절 구속 4개':item.kind==='extrusion'?'도형 · 치수 · 구속':'매개변수 형상'));button.append(text);button.onclick=()=>guard(()=>newDesign(item));list.append(button);
  }
}
async function newDesign(item){
  if(!requireReady())return;await ensureApplied();
  state.selected=null;state.projectId=null;state.hidden.clear();await build(clone(item.design),item.title+' 생성');toast('새 설계를 만들었습니다. 이전 설계는 작업 이력에서 복원할 수 있습니다.');
}
function uniqueId(design){let n=1;while(design.parts.some(p=>p.id===`part-${n}`))n++;return `part-${n}`;}
function renderLibrary(){
  const grid=$('library-grid');grid.replaceChildren();
  for(const item of state.catalog.filter(x=>x.kind!=='robot_arm')){const b=el('button','library-item');b.append(el('span','template-icon',symbols[item.kind]));const t=el('span');t.append(el('strong',null,item.title),el('small',null,item.mode==='specimen'?'시편 · 웨이퍼':'부품 · 기계 설계'));b.append(t);b.onclick=()=>guard(()=>addPart(item));grid.append(b);}
}
async function addPart(item){
  if(!requireReady())return;await ensureApplied();if(state.design.parts.length>=12)throw new Error('한 프로젝트에 최대 12개 부품을 사용할 수 있습니다.');
  const design=clone(state.design),part=clone(item.design.parts[0]);part.id=uniqueId(design);part.transform.x=Math.round(state.result.stats.max[0]+Math.max(...state.result.stats.bounds)*.2+30);design.parts.push(part);design.mode=state.mode;
  const result=await build(design,`${part.name} 추가`);state.selected=part.id;renderTree();renderInspector();viewer?.select(part.id);$('library-dialog').close();return result;
}
function renderTimeline(){
  const line=$('timeline');line.replaceChildren();state.history.forEach((item,i)=>{const b=el('button',(i===state.historyIndex?'current':'')+(i>state.historyIndex?' future':''),i===0?'◈':'◇');b.title=`${i+1}. ${item.label}`;b.setAttribute('aria-label',`이력 ${i+1}: ${item.label}`);b.onclick=()=>{if(requireReady())historyInspector.open(item.id);};line.append(b);});
  $('timeline-info').textContent=state.history[state.historyIndex]?.label||'';
}
async function checkoutHistory(id){if(!requireReady())return;await ensureApplied();const design=state.journal.at(id);await build(design,'',{record:false,historyCursor:id});}
async function goHistory(index){if(!requireReady()||index<0||index>=state.history.length)return;await checkoutHistory(state.history[index].id);}
async function save(){
  if(!requireReady())return;await ensureApplied();busy(true,'프로젝트 저장 중');
  try{const response=await api('/api/projects'+(state.projectId?'/'+state.projectId:''),project(),state.projectId?'PUT':'POST');state.projectId=response.id;persist();$('save-state').textContent='저장 완료';toast('로컬 프로젝트에 저장했습니다.');}finally{busy(false);}
}
function download(blob,filename){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=filename;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
function filename(ext){return state.design.name.replace(/[\\/:*?"<>|\x00-\x1f]/g,'_').slice(0,80)+'.'+ext;}
async function exportModel(fmt){
  if(!requireReady())return;await ensureApplied();busy(true,`${fmt.toUpperCase()} 파일 생성 중`);
  try{const r=await fetch('/api/export/'+fmt,{method:'POST',headers:{'Content-Type':'application/json','X-CAD-Request':'1'},body:JSON.stringify(fmt==='autodesk'?project():state.design)});if(!r.ok){const error=await r.json();throw new Error(error.detail||'내보내기에 실패했습니다.');}download(await r.blob(),filename(fmt==='autodesk'?'autodesk.zip':fmt));toast(`${fmt.toUpperCase()} 파일을 내보냈습니다.${fmt==='stl'?' 불러올 때 단위를 mm로 지정하세요.':''}`);}finally{busy(false);}
}
async function openProjects(){
  if(!requireReady())return;await ensureApplied();const list=$('project-list');list.replaceChildren();const projects=await api('/api/projects');
  if(!projects.length)list.append(el('p','field-help','저장된 프로젝트가 없습니다. 설계 파일을 가져오거나 현재 설계를 저장하세요.'));
  for(const p of projects){const b=el('button','project-entry');const text=el('span',null,p.name);text.append(el('small',null,`${p.parts}개 부품 · ${new Date(p.modified*1000).toLocaleString('ko-KR')}`));b.append(text,el('span',null,'↗'));b.onclick=()=>guard(async()=>{const project=await api('/api/projects/'+p.id);await restore(project,p.id);$('projects-dialog').close();});list.append(b);}
  $('projects-dialog').showModal();
}
async function restore(project,id=null){busy(true,'프로젝트 복원 중');try{const result=await api('/api/projects/validate',project);state.projectId=id;state.selected=null;state.hidden.clear();$('prompt').value=result.project.prompt;state.journal=new DesignJournal(result.project.design,'프로젝트 가져오기',result.project.history,{source:'import'});commit({design:result.project.design,...result},'프로젝트 복원',{reset:true,record:false});toast('프로젝트를 복원했습니다.');}finally{busy(false);}}
function providerNote(){
  const ai=$('provider').value==='openai';$('provider-note').textContent=ai?(state.status?.api_configured?`연결됨 · ${state.status.model}. 현재 설계와 요청을 OpenAI로 전송합니다. 검증 오류 수정 포함 최대 2회 API 호출.`:'API 키가 연결되지 않았습니다. 설정 안내에 따라 환경변수를 지정하고 앱을 재시작하세요.'):'형상 이름과 명시한 치수를 해석합니다. AI 모델은 사용하지 않습니다.';refreshControls();
}
async function generateDraft(){
  if(state.busy)return;if(state.pending)discardDraft();await ensureApplied();const prompt=$('prompt').value.trim();if(!prompt)throw new Error('설계 요청을 입력하세요.');
  busy(true,$('provider').value==='openai'?'AI가 설계를 작성하고 검증하는 중':'치수 명령을 해석하는 중');
  try{const result=await api('/api/draft',{prompt,mode:state.mode,provider:$('provider').value,current:state.design,selected_part:state.selected});
    state.pending=result;viewer?.load(result,true);updateMetadata(result);$('draft-banner').hidden=false;
    const output=$('ai-result');output.replaceChildren(el('strong',null,result.summary));const list=el('ul');for(const note of [...result.changes,...result.assumptions])list.append(el('li',null,note));output.append(list);
    toast('초안이 준비되었습니다. 미리보기를 확인하고 적용하세요.');
  }catch(error){$('ai-result').replaceChildren(el('p','inline-error',error.message));throw error;}finally{busy(false);}
}
function discardDraft(){if(!state.pending)return;state.pending=null;viewer?.load(state.result,true);viewer?.select(state.selected);state.hidden.forEach(id=>viewer?.setVisibility(id,false));updateMetadata(state.result);$('draft-banner').hidden=true;refreshControls();}
async function guard(fn){try{await fn();}catch(error){toast(error.message||'작업을 완료하지 못했습니다.',true);}}
function bind(id,fn){$(id).addEventListener('click',()=>guard(fn));}

async function boot(){
  initConstraintUI();
  historyInspector=new HistoryInspector(()=>state,checkoutHistory,selectPart);
  const historyButton=el('button',null,'기록 · 피처');historyButton.id='show-history';historyButton.onclick=()=>{if(requireReady())historyInspector.open();};document.querySelector('.timeline-label').after(historyButton);
  const native=el('button','tool');native.id='export-autodesk';native.append(el('span','tool-icon','⇄'),el('span',null,'F3D · IPT'));$('export-stl').after(native);native.onclick=()=>{if(requireReady())$('native-dialog').showModal();};
  bind('download-native',async()=>{await exportModel('autodesk');$('native-dialog').close();});
  try{viewer=new CADViewer($('viewport'),id=>guard(()=>selectPart(id)),(id,face)=>guard(()=>startFaceSketch(id,face)));}catch(error){$('viewport').append(el('div','webgl-error','3D 표시를 시작하지 못했습니다. WebGL을 지원하는 Chrome/Edge에서 하드웨어 가속을 켜고 다시 열어주세요. 치수 편집과 파일 내보내기는 사용할 수 있습니다.'));}
  sketchEditor=new SketchEditor(api,applySketch);
  [state.catalog,state.status]=await Promise.all([api('/api/catalog'),api('/api/status')]);
  $('kernel-status').textContent=state.status.kernel;$('api-status-help').textContent=state.status.api_configured?`연결됨 · ${state.status.model}`:'현재 API 키가 연결되지 않았습니다. 직접 설계와 로컬 명령은 바로 사용할 수 있습니다.';
  renderLibrary();providerNote();
  let recovered=false;try{const saved=await loadWorkspace();if(saved?.project){await restore(saved.project,saved.id);recovered=true;}}catch{toast('이전 자동 저장을 복원하지 못해 기본 시편을 엽니다.',true);}
  if(!recovered)await build(clone(entry('round_specimen').design),'시편 생성',{reset:true});

  $('dimension-form').addEventListener('input',markDirty);$('part-color').addEventListener('input',markDirty);
  $('dimension-form').addEventListener('submit',e=>{e.preventDefault();guard(()=>applyDimensions());});
  const renameProject=()=>guard(async()=>{const name=$('project-name').value.trim();if(!requireReady()||name===state.design.name)return;await ensureApplied();const d=clone(state.design);d.name=name;await build(d,'프로젝트 이름 변경',{fit:false});});$('project-name').addEventListener('blur',renameProject);$('project-name').addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();renameProject();}});
  document.querySelectorAll('[data-mode]').forEach(b=>b.onclick=()=>{if(requireReady()){state.mode=b.dataset.mode;renderTemplates();}});
  document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>{viewer?.setView(b.dataset.view);document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===b));});
  document.querySelectorAll('[data-close-dialog]').forEach(b=>b.onclick=()=>b.closest('dialog').close());
  document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{$('prompt').value=b.dataset.prompt;});
  bind('fit-view',()=>viewer?.fit());bind('toggle-edges',()=>$('toggle-edges').classList.toggle('active',viewer?.toggleEdges()));bind('toggle-grid',()=>$('toggle-grid').classList.toggle('active',viewer?.toggleGrid()));
  bind('new-part',()=>{if(requireReady())$('library-dialog').showModal();});bind('sketch-tool',async()=>{await addPart(entry('extrusion'));sketchEditor.open(selectedPart().geometry,{partId:state.selected,name:selectedPart().name});});
  bind('focus-transform',()=>{$('transform-details').open=true;$('t-x')?.focus();});
  bind('duplicate-part',async()=>{if(!requireReady())return;await ensureApplied();const d=clone(state.design),p=clone(selectedPart());if(d.parts.length>=12)throw new Error('최대 12개 부품을 사용할 수 있습니다.');p.id=uniqueId(d);p.fixed=false;p.name=p.name.slice(0,75)+' 복사';p.transform.y+=Math.max(state.result.stats.bounds[1],20)+10;d.parts.push(p);await build(d,'부품 복제');await selectPart(p.id);});
  bind('remove-part',async()=>{if(!requireReady()||state.design.parts.length<=1)return;const d=clone(state.design),name=selectedPart().name;d.parts=d.parts.filter(p=>p.id!==state.selected);d.mates=(d.mates||[]).filter(m=>m.child!==state.selected&&m.parent!==state.selected);await build(d,name+' 삭제');});
  bind('undo',()=>goHistory(state.historyIndex-1));bind('redo',()=>goHistory(state.historyIndex+1));
  bind('save-project',save);bind('open-project',openProjects);bind('export-step',()=>exportModel('step'));bind('export-stl',()=>exportModel('stl'));
  bind('download-project',async()=>{if(!requireReady())return;await ensureApplied();download(new Blob([JSON.stringify(project(),null,2)],{type:'application/json'}),filename('cad.json'));toast('설계 JSON 파일을 내보냈습니다.');});
  bind('settings',()=>$('settings-dialog').showModal());bind('toggle-ai',()=>{$('ai-panel').hidden=!$('ai-panel').hidden;});bind('close-ai',()=>$('ai-panel').hidden=true);
  const stopButton=el('button',null,'로컬 서버 종료');stopButton.id='stop-server';$('settings-dialog').querySelector('.help-body').append(stopButton);stopButton.onclick=()=>guard(async()=>{if(!requireReady())return;await ensureApplied();await api('/api/shutdown',{});$('settings-dialog').close();$('kernel-status').textContent='서버 종료됨 · 바로가기로 다시 실행';toast('로컬 서버를 종료했습니다. 바탕화면 바로가기로 다시 시작할 수 있습니다.');document.querySelectorAll('button,input,select,textarea').forEach(n=>n.disabled=true);});
  $('provider').addEventListener('change',providerNote);bind('generate-draft',generateDraft);bind('discard-draft',discardDraft);bind('apply-draft',()=>{if(!state.pending)return;const result=state.pending;commit(result,result.provider==='openai'?'AI 설계 적용':'치수 명령 적용',{context:{source:result.provider||'manual',prompt:$('prompt').value}});toast('설계 초안을 적용했습니다.');});
  $('import-file').addEventListener('change',()=>guard(async()=>{const file=$('import-file').files[0];if(!file)return;try{if(file.size>32_000_000)throw new Error('설계 파일은 32 MB 이하여야 합니다.');const data=JSON.parse(await file.text());await restore(data);$('projects-dialog').close();}finally{$('import-file').value='';}}));
  document.addEventListener('keydown',e=>{const editing=/INPUT|TEXTAREA|SELECT/.test(e.target.tagName);if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();guard(save);}else if(!editing&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='z'){e.preventDefault();guard(()=>goHistory(state.historyIndex+(e.shiftKey?1:-1)));}else if(!editing&&(e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='y'){e.preventDefault();guard(()=>goHistory(state.historyIndex+1));}else if(!editing&&e.key.toLowerCase()==='f')viewer?.fit();});
  window.addEventListener('beforeunload',e=>{if(state.dirty||state.pending||state.persisting){e.preventDefault();e.returnValue='';}});
}
function initConstraintUI(){
  const faceButton=el('button','tool');faceButton.id='face-sketch';faceButton.append(el('span','tool-icon','▱'),el('span',null,'면 스케치'));$('sketch-tool').after(faceButton);
  faceButton.onclick=()=>guard(async()=>{if(!requireReady())return;await ensureApplied();if(!viewer)throw new Error('면 선택에는 3D 표시가 필요합니다.');viewer.facePick=!viewer.facePick;faceButton.classList.toggle('active',viewer.facePick);toast(viewer.facePick?'3D 모델의 평평한 면을 클릭하세요. 다시 누르면 면 선택을 취소합니다.':'면 선택을 취소했습니다.');});
  const mateButton=el('button','tool');mateButton.id='assembly-mate';mateButton.append(el('span','tool-icon','⌘'),el('span',null,'조립 구속'));$('focus-transform').after(mateButton);mateButton.onclick=()=>guard(()=>openMate());
  const panel=el('div');panel.id='constraints-panel';$('dimension-form').after(panel);
  const dialog=document.createElement('dialog');dialog.id='mate-dialog';dialog.innerHTML=`<div class="dialog-head"><h2>조립 구속</h2><button id="mate-close" class="icon-btn" aria-label="조립 구속 닫기">×</button></div><p class="field-help">선택 부품을 부모 부품의 기준점에 연결합니다. 부모 치수가 바뀌면 기준점과 자식 위치를 다시 계산합니다.</p><div class="mate-grid"><label class="name-field">부모 부품<select id="mate-parent"></select></label><label class="name-field">자식 부품<select id="mate-child"></select></label><label class="name-field">부모 기준점<select id="mate-parent-anchor"></select></label><label class="name-field">자식 기준점<select id="mate-child-anchor"></select></label><label class="name-field">구속 종류<select id="mate-kind"><option value="rigid">강체 · 위치와 회전 고정</option><option value="revolute">회전 · Z축 각도 구동</option><option value="slider">슬라이더 · Z축 이동 구동</option><option value="cylindrical">원통 · Z축 이동과 회전 구동</option></select></label></div><div class="mate-grid" id="mate-offsets"></div><p class="field-help">기준점 축은 부품 로컬 XYZ입니다. 거리와 각도는 부모 기준점에 대한 상대 오프셋입니다. 자동 운동·동역학 해석은 포함하지 않습니다.</p><div id="mate-error" class="inline-error" hidden></div><button id="mate-apply" class="primary full-width">구속 적용</button>`;document.body.append(dialog);
  for(const key of ['x','y','z','rx','ry','rz']){const label=el('label','name-field',key.toUpperCase()+(key.startsWith('r')?' °':' mm'));const input=el('input');input.id='mate-'+key;input.type='number';input.step='any';input.value=0;label.append(input);$('mate-offsets').append(label);}
  $('mate-close').onclick=()=>dialog.close();$('mate-parent').onchange=()=>fillAnchors('parent');$('mate-child').onchange=()=>fillAnchors('child');$('mate-apply').onclick=()=>guard(async()=>{const d=clone(state.design),child=$('mate-child').value;const mate={id:dialog.dataset.mateId||`mate-${Date.now()}`,kind:$('mate-kind').value,parent:$('mate-parent').value,child,parent_anchor:$('mate-parent-anchor').value,child_anchor:$('mate-child-anchor').value};for(const key of ['x','y','z','rx','ry','rz'])mate[key]=Number($('mate-'+key).value);d.mates=(d.mates||[]).filter(m=>m.id!==mate.id);d.mates.push(mate);try{await build(d,'조립 구속 적용');dialog.close();}catch(e){$('mate-error').textContent=e.message;$('mate-error').hidden=false;throw e;}});
}
function renderConstraintsPanel(p){
  const panel=$('constraints-panel');if(!panel)return;panel.replaceChildren();const heading=el('div','section-label','구속 · 피처');panel.append(heading);
  const ground=el('button','full-width',p.fixed?'고정 해제':'부품 고정 (월드)');ground.id='ground-part';ground.onclick=()=>guard(async()=>{if(!requireReady())return;await ensureApplied();const d=clone(state.design),part=d.parts.find(x=>x.id===p.id);part.fixed=!part.fixed;await build(d,part.fixed?'부품 고정':'부품 고정 해제',{fit:false});});panel.append(ground);
  const linked=(state.design.mates||[]).find(m=>m.child===p.id);if(linked){const row=el('div','constraint-row');const edit=el('button',null,'조립 구속 편집');edit.onclick=()=>guard(()=>openMate(linked));const remove=el('button',null,'해제');remove.onclick=()=>guard(async()=>{const d=clone(state.design);d.mates=d.mates.filter(m=>m.id!==linked.id);await build(d,'조립 구속 해제',{fit:false});});row.append(edit,remove);panel.append(row);}
  if(linked&&linked.kind!=='rigid'){
    const drivers=[];if(['slider','cylindrical'].includes(linked.kind))drivers.push(['z','관절 이동 mm']);if(['revolute','cylindrical'].includes(linked.kind))drivers.push(['rz','관절 각도 °']);
    for(const [key,label] of drivers){const row=el('label','name-field',label),input=el('input');input.type='number';input.step='any';input.id='joint-drive-'+key;input.value=Number(linked[key].toFixed(6));row.append(input);panel.append(row);}
    const drive=el('button','full-width','관절 구동');drive.id='drive-joint';drive.onclick=()=>guard(async()=>{if(!requireReady())return;await ensureApplied();const d=clone(state.design),mate=d.mates.find(m=>m.id===linked.id);for(const [key] of drivers)mate[key]=Number($('joint-drive-'+key).value);await build(d,'관절 구동',{fit:false});});panel.append(drive);
  }
  const mesh=state.result.meshes.find(m=>m.id===p.id);if(mesh?.sketch_constraints){const s=mesh.sketch_constraints;panel.append(el('p','solver-status',`스케치 ${s.dof===0?'완전 구속':'자유도 '+s.dof} · 구속 ${s.constraints}개`));const edit=el('button','full-width','2D 스케치 · 구속 편집');edit.id='edit-sketch';edit.onclick=()=>guard(async()=>{await ensureApplied();sketchEditor.open(selectedPart().geometry,{partId:p.id,name:p.name});});panel.append(edit);}
  (p.features||[]).forEach((feature,i)=>{const row=el('div','constraint-row');row.append(el('span',null,`${i+1}. ${feature.name} · ${feature.operation==='add'?'돌출':'파내기'}`));const edit=el('button',null,'편집');edit.onclick=()=>guard(async()=>{if(!requireReady())return;await ensureApplied();const upstream=clone(state.design),source=upstream.parts.find(x=>x.id===p.id);source.features=source.features.slice(0,i);busy(true,'스케치 기준 면 확인 중');try{const result=await api('/api/build',upstream),face=result.meshes.find(m=>m.id===p.id)?.faces.find(f=>f.index===feature.face);sketchEditor.open(feature.sketch,{partId:p.id,name:feature.name,face,feature:clone(feature),featureIndex:i});}finally{busy(false);}});const remove=el('button',null,'제거');remove.onclick=()=>guard(async()=>{const d=clone(state.design);d.parts.find(x=>x.id===p.id).features.splice(i);await build(d,'면 피처 제거');toast('선택한 피처와 이후에 의존하는 피처를 제거했습니다.');});row.append(edit,remove);panel.append(row);});
  const assembly=state.result.stats.assembly_constraints;if(assembly)panel.append(el('p','field-help',`조립 구속 ${assembly.mates}개 · 고정 ${assembly.grounded}개 · 자유도 ${assembly.dof}`));
}
function anchorLabel(key){return {origin:'원점',top:'상면 중심',bottom:'하면 중심',left:'왼쪽 끝',right:'오른쪽 끝'}[key]||key.replace(/hole_(\d+)_top/,'구멍 $1 · 상면').replace(/hole_(\d+)_bottom/,'구멍 $1 · 하면');}
function fillAnchors(role,chosen){const id=$('mate-'+role).value,mesh=state.result.meshes.find(m=>m.id===id),select=$('mate-'+role+'-anchor');select.replaceChildren();for(const key of Object.keys(mesh?.anchors||{origin:[]})){const option=el('option',null,anchorLabel(key));option.value=key;select.append(option);}if(chosen)select.value=chosen;}
async function openMate(existing){if(!requireReady())return;await ensureApplied();if(state.design.parts.length<2)throw new Error('조립 구속에는 부품이 두 개 이상 필요합니다. 부품을 추가하세요.');for(const role of ['parent','child']){const select=$('mate-'+role);select.replaceChildren();for(const p of state.design.parts){const o=el('option',null,p.name);o.value=p.id;select.append(o);}}$('mate-child').value=existing?.child||state.selected;$('mate-parent').value=existing?.parent||state.design.parts.find(p=>p.id!==$('mate-child').value).id;fillAnchors('parent',existing?.parent_anchor);fillAnchors('child',existing?.child_anchor);$('mate-kind').value=existing?.kind||'rigid';for(const key of ['x','y','z','rx','ry','rz'])$('mate-'+key).value=existing?.[key]||0;$('mate-dialog').dataset.mateId=existing?.id||'';$('mate-error').hidden=true;$('mate-dialog').showModal();}
async function startFaceSketch(id,face){if(!requireReady())return;if(!face?.planar)throw new Error('곡면에는 직접 스케치를 만들 수 없습니다. 평평한 면을 선택하세요.');await ensureApplied();viewer.facePick=false;$('face-sketch').classList.remove('active');state.selected=id;renderTree();renderInspector();const part=selectedPart();if((part.features||[]).length>=8)throw new Error('부품당 면 스케치 피처는 최대 8개입니다.');const sketch={kind:'extrusion',thickness:5,points:[{x:-8,y:-8},{x:8,y:-8},{x:8,y:8},{x:-8,y:8}],holes:[],constraints:[]};const feature={id:`feature-${Date.now()}`,name:'면 스케치',face:face.index,support_face_count:face.face_count,support_feature:part.features?.at(-1)?.id||'base',origin:face.origin,x_direction:face.x_direction,normal:face.normal,operation:'add',sketch};sketchEditor.open(sketch,{partId:id,name:part.name,face,feature});}
async function applySketch(sketch,context,operation){const d=clone(state.design),part=d.parts.find(p=>p.id===context.partId);if(context.feature){const feature={...context.feature,sketch,operation};part.features??=[];if(context.featureIndex!==undefined)part.features[context.featureIndex]=feature;else part.features.push(feature);}else part.geometry=sketch;await build(d,context.feature?'면 스케치 피처 적용':'스케치 구속 적용',{context:{part_id:part.id,feature_id:context.feature?.id||'base',face:context.feature?{index:context.feature.face,parent:context.feature.support_feature||'base',origin:context.feature.origin||[],normal:context.feature.normal,x_direction:context.feature.x_direction||[]}:null,tool_actions:context.tool_actions||[]}});}

guard(boot);
