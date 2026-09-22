import * as THREE from './vendor/three.module.js';
import { OrbitControls } from './vendor/OrbitControls.js';

export class CADViewer {
  constructor(element, onSelect, onFace) {
    this.element = element; this.onSelect = onSelect; this.onFace=onFace;this.facePick=false;this.meshes = []; this.edges = true; this.gridVisible = true;
    this.scene = new THREE.Scene(); this.scene.background = new THREE.Color('#edf1f3');
    this.camera = new THREE.OrthographicCamera(-100, 100, 100, -100, .01, 50000);
    this.camera.up.set(0, 0, 1);
    this.renderer = new THREE.WebGLRenderer({antialias:true, alpha:false});
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace; this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.15;
    this.renderer.domElement.setAttribute('aria-label', '회전과 확대가 가능한 CAD 3D 미리보기');
    this.renderer.domElement.setAttribute('tabindex','0');
    element.appendChild(this.renderer.domElement);
    this.controls = new OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true; this.controls.dampingFactor = .12; this.controls.minZoom = .03; this.controls.maxZoom = 100;
    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x667783, 2.2));
    const light = new THREE.DirectionalLight(0xffffff, 3.4); light.position.set(80, -110, 160); this.scene.add(light);
    const fill = new THREE.DirectionalLight(0xc9e5ed, 1.8); fill.position.set(-60, 40, 50); this.scene.add(fill);
    this.group = new THREE.Group(); this.scene.add(this.group);
    this.center = new THREE.Vector3(); this.radius = 70; this.view = 'iso';
    this.raycaster = new THREE.Raycaster(); this.pointer = new THREE.Vector2();
    this.renderer.domElement.addEventListener('pointerdown', e => {this.down = [e.clientX, e.clientY];});
    this.renderer.domElement.addEventListener('pointerup', e => {
      if (!this.down || Math.hypot(e.clientX-this.down[0],e.clientY-this.down[1])>4 || e.button!==0) return;
      const r = this.renderer.domElement.getBoundingClientRect();
      this.pointer.set((e.clientX-r.left)/r.width*2-1, -(e.clientY-r.top)/r.height*2+1);
      this.raycaster.setFromCamera(this.pointer,this.camera);
      const hit = this.raycaster.intersectObjects(this.meshes.filter(m=>m.visible),false)[0];
      if(hit){
        if(this.facePick){const data=hit.object.userData;const index=data.triangle_faces[hit.faceIndex];this.onFace(data.id,data.faces[index]);}
        else this.onSelect(hit.object.userData.id);
      }
    });
    this.observer = new ResizeObserver(()=>this.resize()); this.observer.observe(element);
    this.resize(); this.setView('iso');
    this.renderer.setAnimationLoop(()=>{this.controls.update();this.renderer.render(this.scene,this.camera);});
  }
  resize() {
    const width = this.element.clientWidth, height = this.element.clientHeight;
    if(!width||!height)return;
    this.renderer.setSize(width,height,false);
    const aspect=width/height, half=this.radius*1.23*Math.max(1,1/aspect);
    this.camera.left=-half*aspect; this.camera.right=half*aspect; this.camera.top=half; this.camera.bottom=-half;
    this.camera.updateProjectionMatrix();
  }
  disposeObject(obj) {
    obj.traverse(child=>{child.geometry?.dispose();if(child.material){for(const m of (Array.isArray(child.material)?child.material:[child.material]))m.dispose();}});
  }
  load(result, fit=true) {
    this.disposeObject(this.group);this.group.clear();this.meshes=[];
    for(const item of result.meshes){
      const geometry=new THREE.BufferGeometry();geometry.setAttribute('position',new THREE.Float32BufferAttribute(item.vertices,3));geometry.setIndex(item.triangles);geometry.computeVertexNormals();
      const material=new THREE.MeshStandardMaterial({color:item.color,metalness:.3,roughness:.35,side:THREE.FrontSide});
      const mesh=new THREE.Mesh(geometry,material);mesh.userData={id:item.id,color:item.color,faces:item.faces,triangle_faces:item.triangle_faces};
      const edges=new THREE.LineSegments(new THREE.EdgesGeometry(geometry,28),new THREE.LineBasicMaterial({color:'#456774',transparent:true,opacity:.38}));
      edges.visible=this.edges;mesh.add(edges);this.group.add(mesh);this.meshes.push(mesh);
    }
    const min=new THREE.Vector3(...result.stats.min),max=new THREE.Vector3(...result.stats.max);
    this.center.copy(min).add(max).multiplyScalar(.5);this.radius=Math.max(min.distanceTo(max)/2,1);
    if(this.grid){this.scene.remove(this.grid);this.disposeObject(this.grid);}
    const size=Math.pow(10,Math.floor(Math.log10(this.radius)))*10;
    this.grid=new THREE.GridHelper(size,50,0xc1cdd1,0xd8e0e3);this.grid.rotateX(Math.PI/2);
    this.grid.position.set(this.center.x,this.center.y,min.z-Math.max(.04,this.radius*.004));
    this.grid.material.transparent=true;this.grid.material.opacity=.52;this.grid.visible=this.gridVisible;this.scene.add(this.grid);
    if(fit)this.fit();
  }
  setView(view) {
    this.view=view;const vectors={iso:[1,-1.4,1.1],top:[0,0,1],front:[0,-1,0],side:[1,0,0]};
    const direction=new THREE.Vector3(...vectors[view]).normalize();
    this.camera.up.set(...(view==='top'?[0,1,0]:[0,0,1]));
    this.camera.position.copy(this.center).addScaledVector(direction,this.radius*6+100);
    this.controls.target.copy(this.center);this.camera.lookAt(this.center);this.controls.update();
  }
  fit(){this.camera.zoom=1;this.resize();this.setView(this.view);}
  select(id){for(const mesh of this.meshes){const selected=mesh.userData.id===id;mesh.material.emissive.set(selected?'#0e292b':'#000000');mesh.material.emissiveIntensity=.16;mesh.children[0].material.color.set(selected?'#306c75':'#506775');mesh.children[0].material.opacity=selected?.58:.32;}}
  setVisibility(id,visible){const mesh=this.meshes.find(m=>m.userData.id===id);if(mesh)mesh.visible=visible;}
  toggleEdges(){this.edges=!this.edges;for(const m of this.meshes)m.children[0].visible=this.edges;return this.edges;}
  toggleGrid(){this.gridVisible=!this.gridVisible;if(this.grid)this.grid.visible=this.gridVisible;return this.gridVisible;}
}
