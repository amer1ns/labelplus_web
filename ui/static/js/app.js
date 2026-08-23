const { images, mode: INIT_MODE, initial_img: INIT_IMG, initial_dpi: INIT_DPI, initial_scale: INIT_SCALE } = window.__INIT__;
// image quality selection (stored in localStorage)
const QUALITY_MAP = {low:1000, med:2000, orig:'orig'};
let quality = localStorage.getItem('img_quality') || 'med';
let preferred_scale = localStorage.getItem('preferred_scale') || (INIT_SCALE||null);
// marker size in pixels (primary). null means use legacy markerScale multiplier.
let markerScale = 0.66; // legacy multiplier fallback
let markerPx = null; // explicit pixel size

function computeBaseMarkerSize(){ const base = Math.min(vw(), vh()); return clamp(84 + base * 0.09, 84, 168); }
// marker size is perceptual (pixel size): use a log/geometric slider so equal drag = equal ratio change (15→30 = 2x, 60 = 4x)
const SIZE_MIN = 6, SIZE_MAX = 500, SIZE_LOG_RATIO = Math.log(SIZE_MAX / SIZE_MIN);
function sizeToSlider(px){ return Math.log(px / SIZE_MIN) / SIZE_LOG_RATIO; } // 0..1 (left half covers small sizes)
function sliderToSize(t){ return SIZE_MIN * Math.exp(t * SIZE_LOG_RATIO); }    // SIZE_MIN..SIZE_MAX

function setMarkerPx(px, persist=true){
  markerPx = Math.max(4, Math.min(2000, Number(px)));
  updateMarkerScale();
  renderMarkers();
  if(persist){
    fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({marker_px: markerPx})}).then(r=>r.json()).catch(()=>{});
  }
}

// update UI elements for marker px (label + range)
function refreshMarkerUi(){
  try{ if(markerPx!=null) document.getElementById('markerRange').value = Math.round(sizeToSlider(markerPx)*1000); }catch(_){ }
}

function setMarkerScale(s, persist=true){
  markerScale = Math.max(0.2, Math.min(3.0, Number(s)));
  // switching to scale mode clears explicit px
  markerPx = null;
  updateMarkerScale();
  renderMarkers();
  if(persist){
    fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({marker_scale: markerScale})}).then(r=>r.json()).catch(()=>{});
  }
}

// speed re-test interval (days)
const SPEED_RETEST_DAYS = 7;

function refreshQualityButtons(){ try{ document.querySelectorAll('button.cq').forEach(b=>b.classList.toggle('active', b.dataset.q===quality)); }catch(_){ } }
function setQuality(q){ quality = q; localStorage.setItem('img_quality', q); const b=document.getElementById('bQuality'); if(b) b.textContent=q; refreshQualityButtons(); loadPage(); }
function setPreferredScale(s){ preferred_scale = s; localStorage.setItem('preferred_scale', s); }
function getImageUrl(name){ if(!name) return '/image/'+encodeURIComponent(name); if(quality==='orig') return '/image/'+encodeURIComponent(name); return '/image_variant/'+QUALITY_MAP[quality]+'/'+encodeURIComponent(name); }
function runSpeedTestOnce(force=false){
  const last = localStorage.getItem('net_speed_last');
  if(!force && last){
    try{
      const lastTs = Number(last);
      const days = (Date.now()-lastTs)/(1000*60*60*24);
      if(days < SPEED_RETEST_DAYS && localStorage.getItem('net_speed_kbps')) return;
    }catch(_){ }
  }
  const t0=performance.now();
  fetch('/api/speed_test?rand='+Math.random()).then(r=>r.blob()).then(b=>{
    const t1=performance.now(); const kb=b.size/1024; const sec=Math.max(0.001,(t1-t0)/1000); const kbps=kb/sec;
    localStorage.setItem('net_speed_kbps', kbps);
    localStorage.setItem('net_speed_last', String(Date.now()));
    if(kbps<1000) setQuality('low'); else if(kbps<5000) setQuality('med'); else setQuality('orig');
  }).catch(()=>{});
}
// 設定初始模式
document.body.classList.add(INIT_MODE==='input'?'input':'label');
if(INIT_MODE==='input'){
  document.getElementById('mInput').classList.add('on');
  document.getElementById('mLabel').classList.remove('on');
}
// 自動替換輸入字符
const CHAR_MAP = {'⋯':'…','@':'♪','...':'…','€':'♥','¥':'♡','～':'~'};
let mode='label', cur=0, scale=1, tx=0, ty=0;
// 最後一次指標（滑鼠／手指）停在 viewport 的位置，縮放按鈕以它為錨點，文字才不會跑掉
let lastPx=null, lastPy=null;
let imgW=0, imgH=0;
let markers=[];
let selId=null;
let curM=null, editorOpen=false, dirty=false;
let placing=false, placeInside=1;
let dragMk=null; // marker id currently in free-drag mode
let kbH=0;
let pageLoadToken = 0; // latest page request; stale async responses are ignored
let ocrSel=null; // pending OCR box-select {mode:'marker', id}; Ctrl+drag is a one-shot new-marker
let boxSel=null; // active box being drawn {x0,y0,x1,y1}
let ocrOriginals={}; // marker_id -> original text for current page
let ocrToast=null;
let ocrReady=false, ocrLoading=false; // OCR 預熱狀態
const MIN=0.2, MAX=6;
const viewport=document.getElementById('viewport');
const view=document.getElementById('view');
const img=document.getElementById('pageImg');
const ocrBox=document.getElementById('ocrBox');
function clamp(v,min,max){ return Math.min(max, Math.max(min, v)); }
function updateMarkerScale(){
  const base = Math.min(vw(), vh());
  const baseSize = clamp(84 + base * 0.09, 84, 168);
  const size = markerPx!=null ? markerPx : (baseSize * markerScale);
  const visualScale = scale > 0 ? Math.max(0.8, Math.min(1.6, 1 / Math.max(scale, 0.7))) : 1;
  const fontSize = Math.max(11, size * 0.34);
  document.documentElement.style.setProperty('--marker-size', `${size}px`);
  document.documentElement.style.setProperty('--marker-font-size', `${fontSize}px`);
  document.documentElement.style.setProperty('--marker-visual-scale', `${visualScale}`);
}
const markersDiv=document.getElementById('markers');
const editor=document.getElementById('editor');
const ta=document.getElementById('eText');
const eOriginal=document.getElementById('eOriginal');
const vv=window.visualViewport;
function vw(){ return vv?vv.width:window.innerWidth; }
function vh(){ return vv?vv.height:window.innerHeight; }
function vtop(){ return vv?vv.offsetTop:0; }
function barHeight(){ return editorOpen?editor.offsetHeight:64; }
function visibleArea(){
  const top=vtop();
  let h=vh();
  if(editorOpen){ h=Math.max(140, h-barHeight()-10); }
  return {w:vw(), h:h, top:top};
}
function updateKb(){
  kbH = vv?Math.max(0, window.innerHeight - vv.height):0;
  editor.style.bottom=(kbH+10)+'px';
  if(editorOpen && curM){ setTimeout(()=>aimMarker(curM),0); }
}
if(vv){ vv.addEventListener('resize', updateKb); }
function apply(){ view.style.transform=`translate(${tx}px, ${ty}px) scale(${scale})`; updateMarkerScale(); }
function fitView(){
  if(!imgW) return;
  const a=visibleArea();
  scale=Math.min(a.w/imgW, a.h/imgH)*0.985;
  tx=(a.w-imgW*scale)/2; ty=(a.h-imgH*scale)/2; apply();
  // save precise scale after fitting
  persistScale();
}
function clampPan(){
  if(!imgW) return;
  // 不做任何邊界夾制：讓圖片能在任何時候自由拖動、自由放置。
  apply();
}
function zoomAt(px,py,f){
  const vx=(px-tx)/scale, vy=(py-ty)/scale;
  const ns=Math.max(MIN,Math.min(MAX,scale*f));
  tx=px-vx*ns; ty=py-vy*ns; scale=ns; clampPan();
  // persist precise scale after any programmatic zoom
  persistScale();
}

// persist precise scale
function persistScale(){
  try{ setPreferredScale(Number(scale).toFixed(3)); }catch(_){ }
}
function zoomStep(f){
  const cx=(lastPx!=null)?lastPx:vw()/2;
  const cy=(lastPy!=null)?lastPy:vtop()+vh()/2;
  zoomAt(cx, cy, f);
}
function aimMarker(m){
  if(!imgW) return;
  const a=visibleArea();
  const cx=a.w/2, cy=a.top+a.h/2;
  const fitS=Math.min(a.w/imgW, a.h/imgH);
  scale=Math.max(scale, Math.min(MAX, fitS*1.6));
  tx=cx-m.x*imgW*scale; ty=cy-m.y*imgH*scale;
  clampPan();
}
function focusMarker(m){
  const a=visibleArea();
  scale=Math.max(scale, Math.min(a.w/imgW,a.h/imgH)*1.6);
  tx=a.w/2-m.x*imgW*scale; ty=a.h/2-m.y*imgH*scale; clampPan();
}
function fmtLen(t){ if(!t) return 0; let n=0; for(const ch of t){ if(/\s/.test(ch))continue; n+=ch.charCodeAt(0)<=127?0.5:1; } n=Math.round(n*10)/10; return Number.isInteger(n)?n:n.toFixed(1); }
function applyChars(t){ if(!t) return t; let r=t; Object.keys(CHAR_MAP).sort((a,b)=>b.length-a.length).forEach(k=>{ r=r.split(k).join(CHAR_MAP[k]); }); return r; }
function curMarkers(){ return markers; }
function markerAt(sx,sy){
  if(!imgW) return null;
  return markers.find(m=>{
    const mx=tx+m.x*imgW*scale, my=ty+m.y*imgH*scale;
    return Math.hypot(sx-mx,sy-my)<=32;
  })||null;
}
function setSel(id){ selId=id; document.querySelectorAll('.mk').forEach(el=>el.classList.toggle('sel',Number(el.dataset.id)===id)); renderList(); }
function renderMarkers(){
  markersDiv.innerHTML='';
  if(!images.length){ markersDiv.innerHTML='<div class="empty">⚠️ 沒有找到圖片，請檢查 TXT 檔和圖片目錄</div>'; return; }
  if(!markers.length){ markersDiv.innerHTML='<div class="empty">📭 此頁尚無標號 · 長按空白或按「＋」新增</div>'; renderList(); return; }
  markers.slice().sort((a,b)=>a.id-b.id).forEach(m=>{
    const el=document.createElement('div');
    el.className='mk '+(m.inside===1?'in':'out');
    el.dataset.id=m.id;
    if(m.id===selId) el.classList.add('sel');
    if(dragMk===m.id) el.classList.add('drag');
    el.style.left=(m.x*100)+'%'; el.style.top=(m.y*100)+'%';
    // 標號顯示編號＋編輯框內容的字數
    const mt=(m.text||'').trim();
    el.innerHTML=`<span class="num">${m.id}</span>`+(mt?`<span class="txt">${mt.length}</span>`:'');
    el.addEventListener('pointerdown',e=>{
      if(e.button && e.button!==0) return; // ignore right/middle click
      if(dragMk===m.id){
        e.stopPropagation();
        e.preventDefault();
        try{ el.setPointerCapture(e.pointerId); }catch(_){ }
        m._drag=true;
        return;
      }
      // 一般按壓不攔截：點擊開編輯、長按選單、拖動平移都由 viewport 統一處理，
      // 這樣放大後想拖動圖片看標號內容時，起點在標號上也會平移。
    });
    el.addEventListener('pointermove',e=>{
      if(m._drag){
        e.stopPropagation();
        e.preventDefault();
        const r=view.getBoundingClientRect();
        if(r.width&&r.height){
          let x=(e.clientX-r.left)/r.width, y=(e.clientY-r.top)/r.height;
          x=Math.max(0,Math.min(1,x)); y=Math.max(0,Math.min(1,y));
          m.x=x; m.y=y;
          el.style.left=(x*100)+'%'; el.style.top=(y*100)+'%';
        }
      }
    });
    el.addEventListener('pointerup',e=>{
      if(m._drag){
        e.stopPropagation();
        m._drag=false; dragMk=null; persist(); renderMarkers(); return;
      }
    });
    markersDiv.appendChild(el);
  });
  renderList();
}
function renderList(){
  const list=document.getElementById('list');
  document.getElementById('listCount').textContent=markers.length;
  list.innerHTML='';
  if(!markers.length){ list.innerHTML='<div style="color:#667;text-align:center;padding:14px;">此頁沒有標號</div>'; return; }
  markers.slice().sort((a,b)=>a.id-b.id).forEach(m=>{
    const row=document.createElement('div');
    row.className='row'+(m.id===selId?' sel':'');
    const t=m.text||'';
    row.innerHTML=`<div class="rid ${m.inside===1?'in':'out'}">${m.id}</div>
      <div class="rbody"><div class="rtxt">${t?escapeHtml(t):'<span class="ph2">（空白）</span>'}</div>
      <div class="rmeta">${m.inside===1?'框內':'框外'}</div></div>
      <div class="rlen">${fmtLen(t)}</div>`;
    row.onclick=()=>{ setSel(m.id); focusMarker(m); openEditor(m); };
    list.appendChild(row);
  });
  const sr=list.querySelector('.row.sel');
  if(sr) sr.scrollIntoView({block:'nearest'});
}
function escapeHtml(s){ return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
function addMarkerAt(px,py,inside){
  const r=view.getBoundingClientRect();
  if(!r.width||!r.height) return;
  let x=(px-r.left)/r.width, y=(py-r.top)/r.height;
  x=Math.max(0,Math.min(1,x)); y=Math.max(0,Math.min(1,y));
  const id=(markers.length?Math.max(...markers.map(m=>m.id)):0)+1;
  markers.push({id,x,y,inside,text:''});
  setSel(id); renderMarkers(); persist();
}
function buildRail(){
  const rail=document.getElementById('rail');
  rail.innerHTML='';
  images.forEach((name,i)=>{
    const d=document.createElement('div');
    d.className='pthumb'+(i===cur?' active':'');
    const im=document.createElement('img');
    im.src=getImageUrl(name); im.loading='lazy';
    d.appendChild(im);
    const n=document.createElement('div'); n.className='pname'; n.textContent=name; d.appendChild(n);
    d.onclick=()=>{ changePage(i, false); };
    rail.appendChild(d);
  });
}
const radial=document.getElementById('radial');
function showRadial(x,y,items){
  radial.innerHTML='';
  items.forEach(it=>{ const b=document.createElement('button'); b.textContent=it.label; if(it.warn)b.className='warn'; b.onclick=()=>{ radial.style.display='none'; it.run(); }; radial.appendChild(b); });
  radial.style.display='flex';
  const rw=radial.offsetWidth||156, rh=radial.offsetHeight||120;
  radial.style.left=Math.min(window.innerWidth-rw-10, Math.max(10,x+6))+'px';
  radial.style.top=Math.min(window.innerHeight-rh-10, Math.max(10,y+6))+'px';
}
function startDragMarker(m){
  if(editorOpen){ closeEditor(); }
  setSel(m.id);
  if(imgW){
    const mx=tx+m.x*imgW*scale, my=ty+m.y*imgH*scale;
    zoomAt(mx, my, 2);
  }
  dragMk=m.id;
  renderMarkers();
}
function markerItems(m){ return [
  {label:'✏️ 編輯文字', run:()=>{ setSel(m.id); openEditor(m); }},
  {label:(reviewKnown.has(images[cur]+'|'+m.id)?'⭐ 已在復習帳（查看/新增考點）':'⭐ 加入復習帳'), run:()=>{ openHardModal(m); }},
  {label:'✋ 拖曳位置', run:()=>{ startDragMarker(m); }},
  {label:'🖼 框選OCR并翻譯', run:()=>{ enterOcrSelect(m); }},
  {label:m.inside===1?'↔ 切換為框外':'↔ 切換為框內', run:()=>{ m.inside=m.inside===1?2:1; renderMarkers(); persist(); }},
  {label:'🗑 刪除標號', warn:true, run:()=>{ const i=markers.indexOf(m); const delId=m?m.id:null; if(i>=0) markers.splice(i,1); if(curM===m) closeEditor(); renumberMarkers(delId==null?[]:[delId]); renderMarkers(); persist(); }},
];}
function openEditor(m){
  if(editorOpen && curM && curM!==m){ persistText(); saveOriginalText(); flush(); }
  curM=m; editorOpen=true; dirty=false;
  document.body.classList.add('editing');
  editor.style.display='block';
  fillEditor(m);
  updateKb();
  setTimeout(()=>{ aimMarker(m); },30);
  setTimeout(()=>ta.focus(),120);
}
function fillEditor(m){
  document.getElementById('eId').textContent=m.id;
  const b=document.getElementById('eBadge');
  b.textContent=m.inside===1?'框內':'框外';
  b.className='badge '+(m.inside===1?'in':'out');
  document.getElementById('eCoord').textContent=m.x.toFixed(2)+', '+m.y.toFixed(2);
  ta.value=m.text||'';
  ta.style.height='auto'; ta.style.height=Math.min(ta.scrollHeight,0.34*window.innerHeight)+'px';
  const orig=ocrOriginals[m.id]||'';
  eOriginal.textContent=orig;
  eOriginal.style.display=orig?'':'none';
  updateCount();
  refreshHardBtn();
}
function updateCount(){ document.getElementById('eCount').textContent=fmtLen(ta.value)+' 字'; }
function persistText(){ if(!curM) return; curM.text=applyChars(ta.value); updateMarkerBadge(curM.id); }
function updateMarkerBadge(id){
  const el=document.querySelector(`.mk[data-id="${id}"]`);
  if(!el) return;
  const v=applyChars(ta.value||'').trim();
  let txt=el.querySelector('.txt');
  if(v){
    if(!txt){ txt=document.createElement('span'); txt.className='txt'; el.appendChild(txt); }
    txt.textContent=v.length;
  } else if(txt){
    txt.remove();
  }
}
function persist(cb){
  fetch('/api/save_dialogues',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img:images[cur],dialogues:markers})})
    .then(r=>r.json()).then(d=>{
      if(d.status==='ok'){
        // 後端已按「標註順序」重排 id；同步回前端，保證前後端編號一致
        if(d.dialogues&&Array.isArray(d.dialogues)){
          d.dialogues.forEach((dd,i)=>{ if(markers[i]) markers[i].id=dd.id; });
        }
        if(cb)cb();
      } else { alert('保存失敗: '+d.error); }
    })
    .catch(err=>alert('網路錯誤: '+err));
}
function renumberMarkers(deletedIds){
  // 刪除標號後把編號前移為連續（保持標註順序，id 即順序）。
  // 例：12345 刪除 3 → 12 不變、4→3、5→4。
  // 真正的標號識別靠 id，前端/txt 只顯示連續編號，保持原文譯文對應。
  deletedIds=deletedIds||[];
  if(!markers.length) return;
  const dels = new Set(deletedIds);
  const idMap = {};
  markers.forEach(mk=>{
    let shift=0;
    for(const d of dels){ if(d < mk.id) shift++; }
    const newId = mk.id - shift;
    if(newId !== mk.id) idMap[mk.id] = newId;
    mk.id = newId;
  });
  // 原文快取依新 id 重映射
  const no={};
  for(const k in ocrOriginals){ if(idMap[k]) no[idMap[k]]=ocrOriginals[k]; }
  ocrOriginals=no;
  // 更新選中/編輯中的標號
  if(selId) selId=idMap[selId]||null;
  if(curM && idMap[curM.id]) curM.id=idMap[curM.id];
  syncOriginals();
  // 遷移復習帳考點的標號關聯（重排後 marker_id 變了）；被刪標號的考點 → orphan
  const mapping={};
  for(const k in idMap){ if(Number(k)!==idMap[k]) mapping[k]=idMap[k]; }
  if(Object.keys(mapping).length || deletedIds.length){
    fetch('/api/review/migrate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img:images[cur],mapping,deleted:deletedIds})})
      .then(r=>r.json()).then(d=>{
        if(d.status==='ok' && d.orphan && d.orphan.length){
          toast(`⚠ 已刪除標號有 ${d.orphan.length} 個考點，仍保留在復習帳（無對應標號）`);
        }
      }).catch(()=>{});
  }
}
function syncOriginals(){
  // 重排後同步後端原文快取（清空該頁重建，避免舊 id 殘留）
  const img=images[cur];
  fetch('/api/originals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img, clear:true})})
    .catch(()=>{});
  for(const id in ocrOriginals){
    fetch('/api/originals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img, id:Number(id), original:ocrOriginals[id]})})
      .catch(()=>{});
  }
}
function flush(){ if(dirty){ dirty=false; persist(); } }
function switchEditorMarker(d){
  if(!curM || !markers.length) return;
  persistText(); saveOriginalText(); flush();
  const ms=markers.slice().sort((a,b)=>a.id-b.id);
  const i=ms.findIndex(m=>m.id===curM.id);
  const next=ms[(i+d+ms.length)%ms.length];
  setSel(next.id);
  fillEditor(next);
  curM=next; dirty=false;
  updateKb(); ta.focus();
  setTimeout(()=>aimMarker(next),30);
}
function toggleEditorInside(){
  if(!curM) return;
  curM.inside=curM.inside===1?2:1; dirty=true;
  renderMarkers(); fillEditor(curM);
}
function saveOriginalText(){
  if(!curM) return;
  const val=(eOriginal.innerText||'').trim();  // innerText 保留換行
  if(val) ocrOriginals[curM.id]=val; else delete ocrOriginals[curM.id];
  persistOriginal(curM.id, val);
}
function saveEditor(){ persistText(); saveOriginalText(); flush(); updateMarkerBadge(curM?curM.id:null); }
function closeEditor(){
  if(!editorOpen) return;
  persistText();
  saveOriginalText();
  flush();
  editor.style.display='none';
  editorOpen=false; curM=null; dirty=false;
  document.body.classList.remove('editing');
  renderMarkers();
}
ta.addEventListener('input',()=>{
  if(ta.dataset._mappingLock === '1') return;
  const v=applyChars(ta.value);
  if(v!==ta.value){ const p=ta.selectionStart; ta.value=v; try{ta.setSelectionRange(p,p);}catch(_){} }
  dirty=true;
  ta.style.height='auto'; ta.style.height=Math.min(ta.scrollHeight,0.34*window.innerHeight)+'px';
  updateCount();
  updateMarkerBadge(curM?curM.id:null);
});
// 攔截單字元插入：在原生插入前完成替換，避免行動瀏覽器重複寫入造成雙字符
ta.addEventListener('beforeinput', (e) => {
  if(!e || e.inputType !== 'insertText' || !e.data) return;
  if(!Object.prototype.hasOwnProperty.call(CHAR_MAP, e.data)) return;
  e.preventDefault();
  const start = ta.selectionStart, end = ta.selectionEnd;
  const mapped = CHAR_MAP[e.data];
  ta.value = ta.value.slice(0, start) + mapped + ta.value.slice(end);
  ta.setSelectionRange(start + mapped.length, start + mapped.length);
  ta.dispatchEvent(new Event('input'));
});
document.getElementById('eSave').onclick=saveEditor;
document.getElementById('eClose').onclick=closeEditor;
document.getElementById('eToggle').onclick=toggleEditorInside;
document.getElementById('ePrev').onclick=()=>switchEditorMarker(-1);
document.getElementById('eNext').onclick=()=>switchEditorMarker(1);
// ⭐ 困難標記 → 復習帳（一句可含多個考點，每個考點一張複習卡）
const hardBtn=document.getElementById('hardBtn');
const hardModal=document.getElementById('hardModal');
// 已加入復習帳的提示：reviewKnown = Set('img|marker_id')，reviewCounts = Map(key -> 考點數)
let reviewKnown=new Set();
let reviewCounts=new Map();
function refreshReviewKnown(){
  return fetch('/api/review/items').then(r=>r.json()).then(d=>{
    reviewKnown=new Set(); reviewCounts=new Map();
    (d.items||[]).forEach(it=>{
      const k=(it.img||'')+'|'+it.marker_id;
      if(k==='|') return;
      reviewKnown.add(k);
      reviewCounts.set(k,(reviewCounts.get(k)||0)+1);
    });
    refreshHardBtn();
  }).catch(()=>{});
}
function refreshHardBtn(){
  if(!hardBtn) return;
  if(!curM){ hardBtn.classList.remove('on'); hardBtn.title='標記為難點，加入復習帳'; return; }
  const k=images[cur]+'|'+curM.id;
  if(reviewKnown.has(k)){
    hardBtn.classList.add('on');
    hardBtn.title='已在復習帳（'+(reviewCounts.get(k)||1)+' 個考點），點擊查看／新增';
  } else {
    hardBtn.classList.remove('on');
    hardBtn.title='標記為難點，加入復習帳';
  }
}
let hmMarker=null, hmExisting=[], hmRemoved=new Set(), hmDiffMode=null, hmPending=null;
// ---- 考點比對：與同標號已記錄的考點做對比（正規化＋模糊相似度）----
function normPt(s){
  return String(s||'').trim().replace(/^[〜～~]/,'').replace(/[\s\u3000（）()：:、。・]/g,'').toLowerCase();
}
function ptSim(a,b){
  const A=[], B=[];
  for(let i=0;i<a.length-1;i++) A.push(a.slice(i,i+2));
  for(let i=0;i<b.length-1;i++) B.push(b.slice(i,i+2));
  if(!A.length||!B.length) return 0;
  const setB=new Set(B); let inter=0;
  A.forEach(g=>{ if(setB.has(g)){ inter++; setB.delete(g); } });
  return inter/(A.length+B.length-inter||1);
}
function chSim(a,b){
  // 單字元 Jaccard：抓「單一假名錯字」這類 OCR 級差異
  const A=new Set(a), B=new Set(b);
  if(!A.size||!B.size) return 0;
  let inter=0;
  A.forEach(c=>{ if(B.has(c)) inter++; });
  return inter/(A.size+B.size-inter||1);
}
function matchPt(title, items, claimedIds){
  const t=normPt(title);
  if(!t) return null;
  let best=null, bestSim=0;
  items.forEach(it=>{
    if(claimedIds.has(it.id)) return;
    const p=normPt(it.point||'');
    if(!p) return;
    if(p===t){ best=it; bestSim=1; return; }
    const s=ptSim(p,t), c=chSim(p,t);
    if((s>=0.6) || (c>=0.7 && s>=0.45)){
      if(Math.max(s,c)>bestSim){ best=it; bestSim=Math.max(s,c); }
    }
  });
  return best;
}
function addPointRow(pt){
  pt=pt||{};
  const box=document.getElementById('hmPoints');
  const row=document.createElement('div');
  row.className='hm-pt';
  if(pt.item_id) row.dataset.itemId=pt.item_id;
  row.innerHTML='<div class="hm-pt-top"><input class="hm-pt-title" placeholder="考點標題，如：〜わけにはいかない"><span class="hm-pt-flag"></span><button class="hm-pt-del" title="移除這個考點">✕</button></div>'+
    '<textarea class="hm-pt-grammar" rows="2" placeholder="語法說明（複習時顯示在卡片背面，可留白）"></textarea>'+
    '<textarea class="hm-pt-note" rows="1" placeholder="我的筆記（可留白）"></textarea>';
  row.querySelector('.hm-pt-title').value=pt.title||'';
  row.querySelector('.hm-pt-grammar').value=pt.grammar||'';
  row.querySelector('.hm-pt-note').value=pt.note||'';
  row.querySelector('.hm-pt-title').addEventListener('input',refreshPtFlags);
  row.querySelector('.hm-pt-del').onclick=()=>{
    if(box.children.length>1){
      if(row.dataset.itemId) hmRemoved.add(row.dataset.itemId);
      row.remove();
      refreshPtFlags();
    } else toast('至少保留一個考點');
  };
  box.appendChild(row);
  refreshPtFlags();
  return row;
}
// 每列標示「已記錄／新考點」，並更新摘要
function refreshPtFlags(){
  const box=document.getElementById('hmPoints');
  const rows=[...box.querySelectorAll('.hm-pt')];
  const claimed=new Set(rows.map(r=>r.dataset.itemId).filter(Boolean));
  let dup=0, fresh=0;
  rows.forEach(r=>{
    const flag=r.querySelector('.hm-pt-flag');
    if(r.dataset.itemId){
      flag.textContent='已記錄'; flag.className='hm-pt-flag dup'; dup++;
      return;
    }
    const m=matchPt(r.querySelector('.hm-pt-title').value, hmExisting, claimed);
    if(m){ flag.textContent='已記錄'; flag.className='hm-pt-flag dup'; dup++; }
    else { flag.textContent='新考點'; flag.className='hm-pt-flag new'; fresh++; }
  });
  const sum=document.getElementById('hmPtSummary');
  if(sum) sum.textContent=(fresh||dup)?('新考點 '+fresh+' 個 · 已記錄 '+dup+' 個（可點「存入」比對處理）'):'';
}
function openHardModal(m){
  m=m||curM;
  if(!m) return;
  if(m===curM) persistText();
  hmMarker=m;
  document.getElementById('hmOrig').textContent=(ocrOriginals[m.id]||'').trim()||'（無原文，只存譯文）';
  document.getElementById('hmTran').textContent=(m.text||'').trim()||'（無譯文）';
  document.getElementById('hmMeaning').value='';
  document.getElementById('hmExample').value='';
  document.getElementById('hmConfusion').value='';
  document.getElementById('hmCorrBox').style.display='none';
  document.getElementById('hmCorrApply').checked=true;
  const box=document.getElementById('hmPoints');
  box.innerHTML='';
  hmExisting=[]; hmRemoved=new Set(); hmDiffMode=null; hmPending=null;
  document.getElementById('hmPtSummary').textContent='';
  const exEl=document.getElementById('hmExisting');
  exEl.style.display='none';
  // 預填既有考點（同標號），並記住清單供比對
  fetch('/api/review/items').then(r=>r.json()).then(d=>{
    const exs=(d.items||[]).filter(it=>it.img===images[cur]&&it.marker_id===m.id);
    hmExisting=exs;
    if(exs.length){
      exEl.style.display=''; exEl.textContent='此標號已有 '+exs.length+' 個考點，將更新並新增。';
      const last=exs[exs.length-1];
      document.getElementById('hmMeaning').value=last.meaning||'';
      document.getElementById('hmExample').value=last.example||'';
      document.getElementById('hmConfusion').value=last.confusion||'';
      exs.forEach(it=>addPointRow({item_id:it.id, title:it.point||'', grammar:it.grammar||'', note:it.note||''}));
    } else {
      exEl.style.display=''; exEl.textContent='此標號尚無考點數據，可手動新增或按「🤖 AI 拆解」生成。';
      addPointRow({});
    }
  }).catch(()=>{ addPointRow({}); });
  document.getElementById('hmAi').disabled=false;
  document.getElementById('hmAi').textContent='🤖 AI 拆解';
  hardModal.style.display='flex';
}
function closeHardModal(){ hardModal.style.display='none'; }
if(hardBtn){ hardBtn.onclick=()=>openHardModal(); }
document.getElementById('hmAddPt').onclick=()=>addPointRow({});
document.getElementById('hmX').onclick=closeHardModal;
document.getElementById('hmClose').onclick=closeHardModal;
hardModal.addEventListener('click',e=>{ if(e.target===hardModal) closeHardModal(); });
document.getElementById('hmAi').onclick=()=>{
  const btn=document.getElementById('hmAi');
  if(!hmMarker) return;
  const payload={original:(ocrOriginals[hmMarker.id]||''), translation:(hmMarker.text||'')};
  if(!payload.original && !payload.translation){ alert('沒有可拆解的內容'); return; }
  btn.disabled=true; btn.textContent='拆解中…';
  fetch('/api/review/breakdown',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(r=>r.json())
    .then(d=>{
      if(d.error){ alert('AI 拆解失敗: '+d.error); return; }
      const b=d.breakdown||{};
      document.getElementById('hmMeaning').value=b.meaning||'';
      document.getElementById('hmExample').value=b.example||'';
      document.getElementById('hmConfusion').value=b.confusion||'';
      // AI 依譯文修正 OCR 原文 → 顯示可套用
      const corr=(b.corrected_original||'').trim();
      const curOrig=(ocrOriginals[hmMarker.id]||'').trim();
      const corrBox=document.getElementById('hmCorrBox');
      if(corr && corr!==curOrig){
        document.getElementById('hmCorr').value=corr;
        corrBox.style.display='';
      } else {
        corrBox.style.display='none';
      }
      // 語法點每一條 → 一個考點（自動打散）
      const bullets=(b.grammar||'').split('\n').map(s=>s.replace(/^[-*•\s]+/,'').trim()).filter(Boolean);
      const box=document.getElementById('hmPoints');
      if(bullets.length){
        box.innerHTML='';
        bullets.forEach(bul=>{
          let point='';
          const mm=bul.match(/^(.{1,40}?)[：:](.*)$/s);
          if(mm && String(mm[2]||'').trim()) point=mm[1].trim();
          addPointRow({title:point, grammar:bul});
        });
      } else if(box.children.length===0){
        addPointRow({});
      }
    })
    .catch(err=>alert('AI 拆解網路錯誤: '+err))
    .finally(()=>{ btn.disabled=false; btn.textContent='🤖 AI 拆解'; });
};
// 比對對話框
function closeDiff(){ document.getElementById('hmDiff').style.display='none'; hmPending=null; }
function showDiff(matched, fresh, withId){
  hmPending={matched, fresh, withId};
  const dupEl=document.getElementById('hmdDup'), newEl=document.getElementById('hmdNew');
  dupEl.innerHTML=''; newEl.innerHTML='';
  const dupG=document.getElementById('hmdDupG');
  if(matched.length){
    dupG.style.display='';
    matched.forEach(x=>{ const li=document.createElement('li'); li.textContent=(x.entry.point||x.item.point||'（未命名）'); dupEl.appendChild(li); });
  } else dupG.style.display='none';
  fresh.forEach(e=>{ const li=document.createElement('li'); li.textContent=e.point||'（未命名）'; newEl.appendChild(li); });
  document.getElementById('hmdMsg').textContent='與此標號既有的考點比對完成'+
    (withId.length?('（另有 '+withId.length+' 個既有考點的修改會照常更新）'):'')+'：';
  document.getElementById('hmDiff').style.display='flex';
}
document.getElementById('hmdSkip').onclick=()=>{ hmDiffMode='skip'; closeDiff(); requestSave(); };
document.getElementById('hmdOverwrite').onclick=()=>{ hmDiffMode='overwrite'; closeDiff(); requestSave(); };
document.getElementById('hmdCancel').onclick=closeDiff;
document.getElementById('hmDiff').addEventListener('click',e=>{ if(e.target==document.getElementById('hmDiff')) closeDiff(); });

function doSave(entries, removedIds){
  // 套用 AI 修正後的原文（同步更新標號的原文快取與編輯框）
  let orig=ocrOriginals[hmMarker.id]||'';
  const corrApply=document.getElementById('hmCorrApply').checked;
  const corrVal=document.getElementById('hmCorr').value.trim();
  if(corrApply && corrVal && corrVal!==orig){
    orig=corrVal;
    ocrOriginals[hmMarker.id]=corrVal;
    persistOriginal(hmMarker.id, corrVal);
    eOriginal.textContent=corrVal;
    eOriginal.style.display='';
  }
  const payload={
    img:images[cur],
    marker_id:hmMarker.id,
    original:orig,
    translation:hmMarker.text||'',
    entries:entries,
    meaning:document.getElementById('hmMeaning').value,
    example:document.getElementById('hmExample').value,
    confusion:document.getElementById('hmConfusion').value,
    removed_ids:removedIds,
    // 來源快照：標號位置（漫畫名由後端從目前漫畫目錄自動取得）
    marker_x: hmMarker.x,
    marker_y: hmMarker.y,
  };
  fetch('/api/review/items',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(r=>r.json())
    .then(d=>{
      if(d.status!=='ok'){ alert('保存失敗: '+(d.error||'')); return; }
      const n=(d.items||[]).length;
      const key=images[cur]+'|'+hmMarker.id;
      reviewKnown.add(key); reviewCounts.set(key,n);
      refreshHardBtn();
      hmDiffMode=null; hmRemoved=new Set();
      closeHardModal();
      toast('⭐ 已存入復習帳（'+n+' 個考點）');
    })
    .catch(err=>alert('網路錯誤: '+err));
}

function requestSave(){
  if(!hmMarker) return;
  const rows=[...document.querySelectorAll('#hmPoints .hm-pt')];
  if(!rows.length){ alert('請至少新增一個考點'); return; }
  const entries=rows.map(row=>({
    item_id: row.dataset.itemId||null,
    point: row.querySelector('.hm-pt-title').value,
    grammar: row.querySelector('.hm-pt-grammar').value,
    note: row.querySelector('.hm-pt-note').value,
  }));
  const withId=entries.filter(e=>e.item_id);
  const noId=entries.filter(e=>!e.item_id);
  const claimed=new Set(withId.map(e=>e.item_id));
  const matched=[], fresh=[];
  noId.forEach(e=>{
    const m=matchPt(e.point, hmExisting, claimed);
    if(m) matched.push({entry:e, item:m}); else fresh.push(e);
  });
  const removedIds=[...hmRemoved];
  // 有「新輸入但已記錄」的考點 → 先問用戶：略過 or 覆蓋
  if(matched.length && !hmDiffMode){
    showDiff(matched, fresh, withId);
    return;
  }
  const finalEntries = hmDiffMode==='overwrite'
    ? [...withId, ...matched.map(x=>({...x.entry, item_id:x.item.id})), ...fresh]
    : [...withId, ...fresh];
  doSave(finalEntries, removedIds);
}
document.getElementById('hmSave').onclick=requestSave;
const SYMBOLS = ['♡','♥','❤','♪','♫','♯','★','☆','✦','✧','…','〜','✕','✓','☺','※','◉','◎','●','○','◇','◆','□','■','△','▲','▽','▼','→','←','↑','↓','「','」','『','』','【','】','‼','⁉','⁈','。'];
const symPicker = document.getElementById('symPicker');
const symBtn = document.getElementById('symBtn');
function buildSymPicker(){
  symPicker.innerHTML = '';
  SYMBOLS.forEach(s => {
    const b = document.createElement('button');
    b.textContent = s;
    b.onclick = (e) => {
      e.preventDefault(); e.stopPropagation();
      insertSym(s);
    };
    symPicker.appendChild(b);
  });
}
buildSymPicker();
function insertSym(s){
  const start = ta.selectionStart, end = ta.selectionEnd;
  const v = ta.value;
  if(start > 0 && v[start-1] === '/'){
    ta.value = v.slice(0, start-1) + s + v.slice(end);
    ta.setSelectionRange(start-1 + s.length, start-1 + s.length);
  } else {
    ta.value = v.slice(0, start) + s + v.slice(end);
    ta.setSelectionRange(start + s.length, start + s.length);
  }
  ta.focus();
  ta.dispatchEvent(new Event('input'));
  positionSymPicker();
}
function positionSymPicker(){
  const r = ta.getBoundingClientRect();
  symPicker.style.left = Math.max(6, Math.min(window.innerWidth - symPicker.offsetWidth - 6, r.left)) + 'px';
  symPicker.style.bottom = (window.innerHeight - r.top + 8) + 'px';
}
function toggleSymPicker(){
  const show = !symPicker.classList.contains('show');
  if(show){ positionSymPicker(); symPicker.classList.add('show'); symBtn.classList.add('on'); }
  else { symPicker.classList.remove('show'); symBtn.classList.remove('on'); }
}
symBtn.onclick = (e) => { e.preventDefault(); toggleSymPicker(); };
ta.addEventListener('keydown', (e) => {
  if(e.key === '/' && !e.ctrlKey && !e.metaKey && !e.altKey){
    const start = ta.selectionStart;
    if(start === 0 || /[\s\n]$/.test(ta.value.slice(0, start))){
      e.preventDefault();
      const v = ta.value, s = ta.selectionStart, en = ta.selectionEnd;
      ta.value = v.slice(0, s) + '/' + v.slice(en);
      ta.setSelectionRange(s + 1, s + 1);
      ta.dispatchEvent(new Event('input'));
      if(!symPicker.classList.contains('show')) toggleSymPicker();
    }
  }
  if(e.key === 'Escape' && symPicker.classList.contains('show')){
    symPicker.classList.remove('show'); symBtn.classList.remove('on');
  }
});
document.addEventListener('click', (e) => {
  if(symPicker.classList.contains('show') && !symPicker.contains(e.target) && e.target !== symBtn && e.target !== ta){
    symPicker.classList.remove('show'); symBtn.classList.remove('on');
  }
});
let dimmed = false;
function toggleDim(){
  dimmed = !dimmed;
  document.body.classList.toggle('dim', dimmed);
  document.getElementById('bDim').textContent = dimmed ? '◑' : '◐';
}
function setMode(m){
  if(m===mode) return;
  mode=m; updateURL();
  document.body.classList.toggle('label',m==='label');
  document.body.classList.toggle('input',m==='input');
  document.getElementById('mLabel').classList.toggle('on',m==='label');
  document.getElementById('mInput').classList.toggle('on',m==='input');
  const cx=vw()/2, cy=vtop()+vh()/2;
  const vx=(cx-tx)/scale, vy=(cy-ty)/scale;
  requestAnimationFrame(()=>{
    tx=cx-vx*scale; ty=cy-vy*scale; clampPan();
    if(m==='input'){ buildRail(); renderList(); }
    else { renderList(); }
  });
}
document.getElementById('mLabel').onclick=()=>setMode('label');
document.getElementById('mInput').onclick=()=>setMode('input');
function updateURL(){
  let url;
  const img = (images.length && cur>=0) ? '/'+encodeURIComponent(images[cur]) : '';
  if(mode==='input'){ url='/input'+img; }
  else { url='/mark'+img; }
  // append dpi info if present
  if(preferred_scale){ url += '/scale-'+preferred_scale; }
  history.replaceState(null,'',url);
}
if(INIT_IMG){
  const i=images.indexOf(INIT_IMG);
  if(i>=0){ cur=i; }
}
updateURL();
function makeDraggable(el){
  const grip=el.querySelector('.grip');
  grip.addEventListener('pointerdown',e=>{
    e.preventDefault();
    if(editorOpen) return;
    const sx=e.clientX,sy=e.clientY;
    const l=el.offsetLeft,t=el.offsetTop;
    function onMove(ev){
      const nl=Math.max(0,Math.min(window.innerWidth-el.offsetWidth,l+ev.clientX-sx));
      const nt=Math.max(0,Math.min(window.innerHeight-el.offsetHeight,t+ev.clientY-sy));
      el.style.left=nl+'px'; el.style.top=nt+'px';
    }
    function onUp(){ window.removeEventListener('pointermove',onMove); window.removeEventListener('pointerup',onUp); }
    window.addEventListener('pointermove',onMove);
    window.addEventListener('pointerup',onUp);
  });
}
['iNav','iMenu','iAdd','iZoom'].forEach(id=>makeDraggable(document.getElementById(id)));
const bAdd=document.getElementById('bAdd'), bInOut=document.getElementById('bInOut'), bAddI=document.getElementById('bAddI');
function setPlace(v){
  placing=v;
  bAdd.style.background=v?'rgba(81,119,255,.6)':'rgba(233,69,96,.82)';
  bAddI.classList.toggle('active',v);
}
function updateInOut(){
  const isIn=placeInside===1;
  bInOut.textContent=isIn?'內':'外';
  document.getElementById('bInOutI').textContent=isIn?'內':'外';
  document.getElementById('addLbl').innerHTML='<small>新增標號 · '+(isIn?'框內':'框外')+'</small>';
  document.getElementById('bAddILbl').textContent='放置·'+(isIn?'框內':'框外');
  bInOut.style.background=isIn?'rgba(233,69,96,.5)':'rgba(56,116,255,.5)';
  document.getElementById('bInOutI').style.background=isIn?'rgba(233,69,96,.4)':'rgba(56,116,255,.4)';
}
bAdd.onclick=()=>setPlace(!placing);
bInOut.onclick=()=>{ placeInside=placeInside===1?2:1; updateInOut(); };
bAddI.onclick=()=>setPlace(!placing);
document.getElementById('bInOutI').onclick=()=>{ placeInside=placeInside===1?2:1; updateInOut(); };
document.getElementById('bZIn').onclick=()=>zoomStep(1.35);
document.getElementById('bZOut').onclick=()=>zoomStep(1/1.35);
document.getElementById('bRail').onclick=()=>document.getElementById('rail').classList.toggle('hidden');
document.getElementById('bHelp').onclick=()=>openHint();
function openPgModal(){
  const grid=document.getElementById('pgGrid');
  grid.innerHTML='';
  images.forEach((name,i)=>{
    const d=document.createElement('div');
    d.className='pthumb'+(i===cur?' active':'');
    const im=document.createElement('img');
    im.src=getImageUrl(name); im.loading='lazy';
    d.appendChild(im);
    const n=document.createElement('div'); n.className='pname'; n.textContent=name; d.appendChild(n);
    d.onclick=()=>{ closePgModal(); changePage(i, false); };
    grid.appendChild(d);
  });
  document.getElementById('pgModal').style.display='flex';
}
function closePgModal(){ document.getElementById('pgModal').style.display='none'; }
let pointers=new Map(), gesture=null;
let downT=0,downX=0,downY=0,moved=false,lpTimer=null,lpFired=false,suppressTap=false,lastTap={x:0,y:0,t:0};
function armLP(e){
  clearTimeout(lpTimer); lpFired=false;
  lpTimer=setTimeout(()=>{
    if(editorOpen||!gesture||gesture.type!=='pan'||pointers.size!==1) return;
    lpFired=true; suppressTap=true; moved=true;
    const m=markerAt(downX,downY);
    if(m){ showRadial(downX,downY,markerItems(m)); }
    else { addMarkerAt(downX,downY,placeInside); }
  },450);
}
function disarmLP(){ clearTimeout(lpTimer); lpFired=false; }
function showOcrBusy(){
  hideOcrBusy();
  ocrToast=document.createElement('div');
  ocrToast.textContent='🅾 OCR 辨識中…';
  ocrToast.style.cssText='position:fixed;left:50%;top:14px;transform:translateX(-50%);z-index:9999;background:rgba(15,17,33,.96);color:#fff;padding:10px 18px;border-radius:999px;font-size:14px;font-weight:700;border:1px solid rgba(233,69,96,.6);box-shadow:0 8px 24px rgba(0,0,0,.5);';
  document.body.appendChild(ocrToast);
}
function hideOcrBusy(){ if(ocrToast){ ocrToast.remove(); ocrToast=null; } }
function toast(msg, ms=1600){
  const t=document.createElement('div');
  t.textContent=msg;
  t.style.cssText='position:fixed;left:50%;top:14px;transform:translateX(-50%);z-index:9999;background:rgba(15,17,33,.96);color:#fff;padding:10px 18px;border-radius:999px;font-size:14px;font-weight:700;border:1px solid rgba(255,255,255,.3);box-shadow:0 8px 24px rgba(0,0,0,.5);';
  document.body.appendChild(t);
  setTimeout(()=>t.remove(), ms);
}
function drawOcrBox(x0,y0,x1,y1){
  const l=Math.min(x0,x1), t=Math.min(y0,y1);
  ocrBox.style.left=l+'px'; ocrBox.style.top=t+'px';
  ocrBox.style.width=Math.abs(x1-x0)+'px'; ocrBox.style.height=Math.abs(y1-y0)+'px';
  ocrBox.style.display='block';
}
function normalizeBoxFromScreen(x0,y0,x1,y1){
  const r=view.getBoundingClientRect();
  if(!r.width||!r.height) return null;
  let nx0=(Math.min(x0,x1)-r.left)/r.width, nx1=(Math.max(x0,x1)-r.left)/r.width;
  let ny0=(Math.min(y0,y1)-r.top)/r.height, ny1=(Math.max(y0,y1)-r.top)/r.height;
  nx0=Math.max(0,Math.min(1,nx0)); nx1=Math.max(0,Math.min(1,nx1));
  ny0=Math.max(0,Math.min(1,ny0)); ny1=Math.max(0,Math.min(1,ny1));
  return {x:nx0, y:ny0, w:nx1-nx0, h:ny1-ny0};
}
function enterOcrSelect(m){
  radial.style.display='none';
  ocrSel={mode:'marker', id:m.id};
  toast('請框選要 OCR 的範圍');
}
function finishOcrSelect(){ ocrSel=null; boxSel=null; ocrBox.style.display='none'; }
function persistOriginal(id, text){
  fetch('/api/originals',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img:images[cur], id:id, original:text||''})})
    .then(r=>r.json()).catch(()=>{});
}
function doOcr(box, targetId){
  if(!images.length){ finishOcrSelect(); return; }
  const imgName=images[cur];
  showOcrBusy();
  fetch('/api/ocr',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({img:imgName, x:box.x, y:box.y, w:box.w, h:box.h})})
    .then(r=>r.json())
    .then(d=>{
      hideOcrBusy();
      if(d.error){ alert('OCR 失敗: '+d.error); finishOcrSelect(); return; }
      ocrReady=true; refreshOcrWarm();
      const original=d.original||'';
      const failed=!!d.translate_error;
      const text=failed ? original : (d.translated||'');
      let id=targetId;
      if(id==null){
        id=(markers.length?Math.max(...markers.map(m=>m.id)):0)+1;
        // 標號掛在框線上：橫排掛上方中間、竪排掛左邊中間
        const vertical = d.layout==='vertical';
        const mx = vertical ? box.x : box.x+box.w/2;
        const my = vertical ? box.y+box.h/2 : box.y;
        markers.push({id, x:mx, y:my, inside:placeInside, text});
      } else {
        const m=markers.find(mm=>mm.id===id);
        if(!m){ finishOcrSelect(); return; }
        m.text=text;
      }
      if(original) ocrOriginals[id]=original; else delete ocrOriginals[id];
      setSel(id); renderMarkers(); persist();
      persistOriginal(id, original);
      finishOcrSelect();
      if(failed){ alert('翻譯失敗: '+d.translate_error+'（已回填原文）'); }
    })
    .catch(err=>{ hideOcrBusy(); alert('OCR 網路錯誤: '+err); finishOcrSelect(); });
}
viewport.addEventListener('pointerdown',e=>{
  if(e.target.closest('#radial')) return;
  if(e.button && e.button!==0) return;
  e.preventDefault();
  lastPx=e.clientX; lastPy=e.clientY;
  try{ viewport.setPointerCapture(e.pointerId); }catch(_){ }
  pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
  if((e.ctrlKey || ocrSel) && !editorOpen && pointers.size===1){
    gesture={type:'ocr', targetId: ocrSel?ocrSel.id:null};
    boxSel={x0:e.clientX, y0:e.clientY, x1:e.clientX, y1:e.clientY};
    drawOcrBox(boxSel.x0, boxSel.y0, boxSel.x1, boxSel.y1);
    return;
  }
  if(pointers.size===2){ disarmLP(); suppressTap=true; moved=true; const [a,b]=[...pointers.values()]; gesture={type:'pinch',d0:Math.hypot(a.x-b.x,a.y-b.y),s0:scale}; }
  else {
    gesture={type:'pan',sx:e.clientX,sy:e.clientY,stx:tx,sty:ty};
    downT=Date.now(); downX=e.clientX; downY=e.clientY; moved=false; suppressTap=false;
    if(!editorOpen) armLP(e);
  }
});
viewport.addEventListener('pointermove',e=>{
  if(!pointers.has(e.pointerId)) return;
  pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
  lastPx=e.clientX; lastPy=e.clientY;  // 拖動／點擊中的最後位置，縮放按鈕以它為錨點
  if(!gesture) return;
  if(gesture.type==='ocr'){
    boxSel.x1=e.clientX; boxSel.y1=e.clientY;
    drawOcrBox(boxSel.x0, boxSel.y0, boxSel.x1, boxSel.y1);
    return;
  }
  if(gesture.type==='pinch'){
    const [a,b]=[...pointers.values()];
    const d=Math.hypot(a.x-b.x,a.y-b.y);
    const ns=Math.max(MIN,Math.min(MAX,gesture.s0*d/(gesture.d0||1)));
    const mx=(a.x+b.x)/2, my=(a.y+b.y)/2;
    const vx=(mx-tx)/scale, vy=(my-ty)/scale;
    tx=mx-vx*ns; ty=my-vy*ns; scale=ns; clampPan();
  }else{
    const dx=e.clientX-gesture.sx, dy=e.clientY-gesture.sy;
    if(!moved&&Math.hypot(dx,dy)>5){ moved=true; disarmLP(); }
    if(moved){ tx=gesture.stx+dx; ty=gesture.sty+dy; apply(); }
  }
});
window.addEventListener('pointerup',e=>onEnd(e));
window.addEventListener('pointercancel',e=>onEnd(e));
function onEnd(e){
  if(!pointers.has(e.pointerId)) return;
  const up={x:e.clientX,y:e.clientY};
  const wasPinch=gesture&&gesture.type==='pinch';
  const wasOcr=gesture&&gesture.type==='ocr';
  const ocrTargetId=wasOcr?gesture.targetId:null;
  pointers.delete(e.pointerId);
  if(pointers.size===0){
    clearTimeout(lpTimer);
    if(wasOcr){
      const box=normalizeBoxFromScreen(boxSel.x0, boxSel.y0, up.x, up.y);
      ocrBox.style.display='none'; boxSel=null; gesture=null;
      suppressTap=false; moved=false;
      if(box && box.w>0.01 && box.h>0.01){ doOcr(box, ocrTargetId); }
      else { finishOcrSelect(); }
      return;
    }
    gesture=null; clampPan();
    if(wasPinch){ persistScale(); }
    if(!moved&&!suppressTap&&!lpFired){
      const m=markerAt(up.x,up.y);
      if(m){ setSel(m.id); openEditor(m); }
      else if(placing&&!editorOpen){ addMarkerAt(up.x,up.y,placeInside); }
      else if(dragMk){ dragMk=null; renderMarkers(); }
    }
    if(!moved&&!lpFired){
      const now=Date.now();
      if(now-lastTap.t<300&&Math.hypot(up.x-lastTap.x,up.y-lastTap.y)<48){ doDoubleTap(up.x,up.y); lastTap.t=0; }
      else lastTap={x:up.x,y:up.y,t:now};
    }
    suppressTap=false; moved=false;
  }else if(gesture&&gesture.type==='pan'){
    gesture={type:'pan',sx:up.x,sy:up.y,stx:tx,sty:ty};
  }
}
function doDoubleTap(x,y){
  const a=visibleArea();
  const atFit=Math.abs(scale-(Math.min(a.w/imgW,a.h/imgH)*0.985))<0.05;
  if(atFit){ zoomAt(x,y,2.2); } else { fitView(); }
}
viewport.addEventListener('wheel', function(e){
  // wheel: scroll image vertically
  e.preventDefault();
  if(!imgW) return;
  ty -= e.deltaY;
  clampPan();
}, {passive:false});
viewport.addEventListener('contextmenu', function(e){
  e.preventDefault();
  const m = markerAt(e.clientX, e.clientY);
  if(m){ showRadial(e.clientX, e.clientY, markerItems(m)); }
  else { showRadial(e.clientX, e.clientY, [
    {label:'🟥 新增「框內」標號', run:()=>addMarkerAt(e.clientX,e.clientY,1)},
    {label:'🟦 新增「框外」標號', run:()=>addMarkerAt(e.clientX,e.clientY,2)},
    {label:'取消', warn:true, run:()=>{}},
  ]); }
});
function navMarker(d){
  if(!markers.length) return;
  if(editorOpen){ switchEditorMarker(d); return; }
  const ms=markers.slice().sort((a,b)=>a.id-b.id);
  let i=ms.findIndex(m=>m.id===selId);
  if(i<0) i = d>0 ? -1 : 0;
  const next=ms[(i+d+ms.length)%ms.length];
  setSel(next.id); focusMarker(next);
}
document.addEventListener('keydown', function(e){
  if(e.key==='Enter' && (e.ctrlKey||e.metaKey)){
    if(editorOpen){ e.preventDefault(); saveEditor(); }
    return;
  }
  if(e.ctrlKey && (e.key==='ArrowUp'||e.key==='ArrowDown')){
    e.preventDefault();
    if(markers.length){ navMarker(e.key==='ArrowUp'?-1:1); }
    return;
  }
  if(e.key==='Escape'){
    if(document.getElementById('hardModal').style.display==='flex'){ closeHardModal(); }
    else if(editorOpen){ closeEditor(); }
    else if(dragMk){ dragMk=null; renderMarkers(); }
    else if(ocrSel||boxSel){ finishOcrSelect(); }
    else if(document.getElementById('ocrPanel').style.display==='flex'){ closeOcrPanel(); }
    else if(document.getElementById('pgModal').style.display==='flex'){ closePgModal(); }
    else if(document.getElementById('hint').style.display==='flex'){ closeHint(); }
    else if(radial.style.display==='flex'){ radial.style.display='none'; }
    return;
  }
  const ae=document.activeElement;
  const tag=(ae&&ae.tagName.toLowerCase());
  const inText=tag==='textarea'||tag==='input'||(ae&&ae.isContentEditable); // 含 contenteditable 原文
  if(inText){
    if(e.key==='PageUp'||e.key==='PageDown'){ e.preventDefault(); flip(e.key==='PageUp'?-1:1); }
    else if((e.ctrlKey||e.metaKey) && e.key==='ArrowLeft'){ e.preventDefault(); flip(-1); }
    else if((e.ctrlKey||e.metaKey) && e.key==='ArrowRight'){ e.preventDefault(); flip(1); }
    return;
  }
  if(e.key==='ArrowLeft'){ flip(-1); }
  else if(e.key==='ArrowRight'){ flip(1); }
  else if(e.key==='ArrowUp'){ navMarker(-1); }
  else if(e.key==='ArrowDown'){ navMarker(1); }
  else if(e.key==='PageUp'){ flip(-1); }
  else if(e.key==='PageDown'){ flip(1); }
  else if(e.key==='Home'){ if(images.length){changePage(0, !!editorOpen);} }
  else if(e.key==='End'){ if(images.length){changePage(images.length-1, !!editorOpen);} }
  else if((e.ctrlKey||e.metaKey) && (e.key===']'||e.key==='】')){ zoomStep(1.35); }
  else if((e.ctrlKey||e.metaKey) && (e.key==='['||e.key==='【')){ zoomStep(1/1.35); }
  else if(e.key==='0'){ fitView(); }
});
function changePage(index, openFirstMarker=false){
  if(editorOpen && curM){ persistText(); flush(); }
  cur=index;
  updateURL();
  loadPage(openFirstMarker);
}
function flip(d){ if(!images.length) return; changePage((cur+d+images.length)%images.length, !!editorOpen); }
function loadPage(openFirstMarker=false){
  const token = ++pageLoadToken;
  selId=null;
  ocrSel=null; boxSel=null; ocrBox.style.display='none';
  ocrOriginals={};
  // 立即清空上一頁的標號與編輯框，避免切頁時殘影跨頁顯示
  const reopenEditor=openFirstMarker;
  closeEditor();
  if(!images.length){ markers=[]; renderMarkers(); return; }
  markers=[];
  renderMarkers();
  const imgName = images[cur];
  img.src=getImageUrl(imgName);
  fetch('/api/originals?img='+encodeURIComponent(imgName))
    .then(r=>r.json())
    .then(d=>{
      if(token !== pageLoadToken) return;
      ocrOriginals=(d&&d.originals)||{};
    })
    .catch(()=>{
      if(token !== pageLoadToken) return;
      ocrOriginals={};
    });
  fetch('/api/get_dialogues?img='+encodeURIComponent(imgName))
    .then(r=>r.json())
    .then(data=>{
      if(token !== pageLoadToken) return;
      if(data.error){ markers=[]; renderMarkers(); }
      else { markers=data.dialogues||[]; renderMarkers(); }
      if(reopenEditor && markers.length){
        const first=markers.slice().sort((a,b)=>a.id-b.id)[0];
        if(first){ setSel(first.id); openEditor(first); }
      }
    })
    .catch(()=>{
      if(token !== pageLoadToken) return;
      markers=[]; renderMarkers();
    });
  document.getElementById('navLbl').innerHTML=(cur+1)+'/'+images.length;
  buildRail();
}
img.onload=()=>{ imgW=img.naturalWidth; imgH=img.naturalHeight; // clear retry flag
  try{ delete img.dataset._tried_orig; }catch(_){ }
  fitView(); if(preferred_scale){ try{ scale = Number(preferred_scale); }catch(_){ } clampPan(); apply(); } renderMarkers(); };
img.onerror=()=>{
  markersDiv.innerHTML='<div class="empty">❌ 圖片載入失敗，正在回退至原圖…</div>';
  try{
    const tried = img.dataset._tried_orig;
    if(!tried && img.src && img.src.indexOf('/image_variant/')!==-1){
      img.dataset._tried_orig = '1';
      const name = images[cur];
      // report to server
      fetch('/api/log',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({msg:'variant_load_failed',level:'warn',img:name,src:img.src})}).catch(()=>{});
      img.src = '/image/'+encodeURIComponent(name)+'?rand='+Math.random();
      return;
    }
  }catch(_){ }
  // final failure, log and show message
  try{ fetch('/api/log',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({msg:'image_load_failed',level:'error',img:images[cur],src:img.src})}).catch(()=>{}); }catch(_){ }
};
window.addEventListener('resize',()=>{ updateKb(); if(!editorOpen) fitView(); updateMarkerScale(); });
function closeHint(){ document.getElementById('hint').style.display='none'; }
function openHint(){ document.getElementById('hint').style.display='flex'; }
mode=INIT_MODE; document.getElementById(INIT_MODE==='input'?'mInput':'mLabel').classList.add('on');
// initialize quality button and speed test
const bq=document.getElementById('bQuality'); if(bq){ bq.textContent=quality; bq.onclick=()=>{ const opts=['low','med','orig']; const idx=(opts.indexOf(quality)+1)%opts.length; setQuality(opts[idx]); }; }
refreshQualityButtons();
const br=document.getElementById('bRetest'); if(br){ br.onclick=()=>{ br.textContent='測試中…'; runSpeedTestOnce(true); setTimeout(()=>{ br.textContent='重測'; },3000); }
}
// load server config for marker scale
fetch('/api/config').then(r=>r.json()).then(d=>{
  try{
    const cfg = d.config||{};
    if(typeof cfg.marker_px !== 'undefined'){
      setMarkerPx(cfg.marker_px, false);
    } else if(typeof cfg.marker_scale !== 'undefined'){
      setMarkerScale(cfg.marker_scale, false);
    } else {
      // default to 66% of base
      setMarkerScale(0.66, false);
    }
    const oc=cfg.ocr||{};
    if(oc.lang) document.getElementById('ocrLang').value=oc.lang;
    if(oc.reading_order) document.getElementById('ocrOrder').value=oc.reading_order;
    const tr=oc.translate||{};
    if(tr.provider) document.getElementById('ocrProvider').value=tr.provider;
    const ocrPreset=OCR_PROVIDERS[document.getElementById('ocrProvider').value]||{};
    document.getElementById('ocrBase').value=tr.base_url||ocrPreset.base_url||'';
    document.getElementById('ocrModel').value=tr.model||ocrPreset.model||'';
    if(tr.api_key) document.getElementById('ocrKey').value=tr.api_key;
    document.getElementById('ocrPrompt').value=tr.prompt||'將以下日文翻譯成台灣繁體中文，只輸出譯文，不要解釋。';
  }catch(_){ setMarkerScale(0.66, false); }
}).catch(()=>{ setMarkerScale(0.66, false); });
if(!localStorage.getItem('preferred_scale') && INIT_SCALE) { preferred_scale = INIT_SCALE; localStorage.setItem('preferred_scale', INIT_SCALE); }

// marker controls
const bDec=document.getElementById('bMarkerDec'); if(bDec){ bDec.onclick=()=>{
  if(markerPx==null){ setMarkerPx(computeBaseMarkerSize()*markerScale); }
  setMarkerPx(Math.max(4, markerPx - 4));
} }
const bInc=document.getElementById('bMarkerInc'); if(bInc){ bInc.onclick=()=>{
  if(markerPx==null){ setMarkerPx(computeBaseMarkerSize()*markerScale); }
  setMarkerPx(markerPx + 4);
} }
// marker island hooks
const bMarkerToggle = document.getElementById('bMarkerToggle'); if(bMarkerToggle){ bMarkerToggle.onclick=()=>{
  const isl = document.getElementById('markerIsland'); isl.style.display = (isl.style.display==='flex' || isl.style.display==='block') ? 'none' : 'block';
  if(isl.style.display!=='none'){ refreshMarkerUi(); }
} }
makeDraggable(document.getElementById('markerIsland'));
const mDec = document.getElementById('mDec'); if(mDec){ mDec.onclick=()=>{ if(markerPx==null){ setMarkerPx(computeBaseMarkerSize()*markerScale); } setMarkerPx(Math.max(SIZE_MIN, Math.round(markerPx/1.2))); refreshMarkerUi(); } }
const mInc = document.getElementById('mInc'); if(mInc){ mInc.onclick=()=>{ if(markerPx==null){ setMarkerPx(computeBaseMarkerSize()*markerScale); } setMarkerPx(Math.min(SIZE_MAX, Math.round(markerPx*1.2))); refreshMarkerUi(); } }
const mRange = document.getElementById('markerRange'); if(mRange){ mRange.oninput=(e)=>{ setMarkerPx(Math.round(sliderToSize(e.target.value/1000))); refreshMarkerUi(); } }
// OCR settings panel
const bOcrSet=document.getElementById('bOcrSet');
const ocrPanel=document.getElementById('ocrPanel');
if(bOcrSet){ bOcrSet.onclick=()=>{
  ocrPanel.style.display='flex';
  fetch('/api/config').then(r=>r.json()).then(d=>{
    const oc=(d.config||{}).ocr||{};
    if(oc.lang) document.getElementById('ocrLang').value=oc.lang;
    if(oc.reading_order) document.getElementById('ocrOrder').value=oc.reading_order;
    const tr=oc.translate||{};
    if(tr.provider) document.getElementById('ocrProvider').value=tr.provider;
    const preset=OCR_PROVIDERS[document.getElementById('ocrProvider').value]||{};
    document.getElementById('ocrBase').value=tr.base_url||preset.base_url||'';
    document.getElementById('ocrModel').value=tr.model||preset.model||'';
    if(tr.api_key) document.getElementById('ocrKey').value=tr.api_key;
    document.getElementById('ocrPrompt').value=tr.prompt||'將以下日文翻譯成台灣繁體中文，只輸出譯文，不要解釋。';
  }).catch(()=>{});
}; }
function closeOcrPanel(){ ocrPanel.style.display='none'; }
document.getElementById('ocrClose').onclick=closeOcrPanel;
ocrPanel.addEventListener('click', e=>{ if(e.target===ocrPanel) closeOcrPanel(); });
// OpenAI-compatible translation providers (kept in sync with ui/services/translate.py)
const OCR_PROVIDERS={
  deepseek:   {base_url:'https://api.deepseek.com',       model:'deepseek-chat'},
  openai:     {base_url:'https://api.openai.com/v1',      model:'gpt-4o-mini'},
  moonshot:   {base_url:'https://api.moonshot.cn/v1',     model:'moonshot-v1-8k'},
  openrouter: {base_url:'https://openrouter.ai/api/v1',   model:'openai/gpt-4o-mini'},
  groq:       {base_url:'https://api.groq.com/openai/v1', model:'llama-3.3-70b-versatile'},
  ollama:     {base_url:'http://localhost:11434/v1',      model:'qwen2.5:7b'},
  tencent:    {base_url:'https://tokenhub.tencentmaas.com/v1', model:'hy3'},
};
const ocrProvider=document.getElementById('ocrProvider');
const ocrBase=document.getElementById('ocrBase');
const ocrModel=document.getElementById('ocrModel');
function fillOcrProvider(){
  const p=OCR_PROVIDERS[ocrProvider.value];
  if(p){ ocrBase.value=p.base_url; ocrModel.value=p.model; }
}
if(ocrProvider){ ocrProvider.addEventListener('change', fillOcrProvider); }
document.getElementById('ocrSave').onclick=()=>{
  const ocr={
    lang: (document.getElementById('ocrLang').value||'japan').trim(),
    reading_order: document.getElementById('ocrOrder').value||'auto',
    translate: {
      provider: (ocrProvider?ocrProvider.value:'deepseek')||'deepseek',
      api_key: document.getElementById('ocrKey').value.trim(),
      base_url: (ocrBase?ocrBase.value:'').trim(),
      model: (ocrModel?ocrModel.value:'').trim(),
      prompt: document.getElementById('ocrPrompt').value.trim() || '將以下日文翻譯成台灣繁體中文，只輸出譯文，不要解釋。'
    }
  };
  fetch('/api/config',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ocr})})
    .then(r=>r.json()).then(d=>{ if(d.status==='ok'){ closeOcrPanel(); toast('OCR 設定已保存'); } else { alert('保存失敗: '+(d.error||'')); } })
    .catch(err=>alert('網路錯誤: '+err));
};
// OCR 預熱（常駐待命）
const bOcrWarm=document.getElementById('bOcrWarm');
function refreshOcrWarm(){
  if(!bOcrWarm) return;
  bOcrWarm.classList.toggle('on', ocrReady);
  bOcrWarm.textContent = ocrLoading ? '…' : '⚡';
  bOcrWarm.style.opacity = ocrReady ? '1' : (ocrLoading ? '.8' : '.5');
  bOcrWarm.title = ocrReady ? 'OCR 已就緒（點擊停止待命）' : '預熱 OCR（常駐待命）';
}
function pollOcrStatus(){
  fetch('/api/ocr/status').then(r=>r.json()).then(d=>{
    const s=d.ocr||{};
    if(s.status==='ready'){ ocrReady=true; ocrLoading=false; refreshOcrWarm(); toast('OCR 已就緒，可即時辨識'); }
    else if(s.status==='error'){ ocrLoading=false; refreshOcrWarm(); alert('OCR 預熱失敗: '+(s.error||'')); }
    else { setTimeout(pollOcrStatus, 800); }
  }).catch(()=>{ ocrLoading=false; refreshOcrWarm(); });
}
if(bOcrWarm){ bOcrWarm.onclick=()=>{
  if(ocrReady){
    fetch('/api/ocr/unload',{method:'POST'}).then(r=>r.json()).then(()=>{ ocrReady=false; refreshOcrWarm(); toast('OCR 已停止待命'); }).catch(()=>{});
    return;
  }
  if(ocrLoading) return;
  ocrLoading=true; refreshOcrWarm(); toast('正在預熱 OCR…');
  fetch('/api/ocr/preload',{method:'POST'}).then(r=>r.json()).then(d=>{
    if(d.status==='error'){ ocrLoading=false; refreshOcrWarm(); alert('預熱失敗: '+(d.error||'')); return; }
    pollOcrStatus();
  }).catch(err=>{ ocrLoading=false; refreshOcrWarm(); alert('預熱失敗: '+err); });
}; }
// 自動 OCR：整頁偵測標號＋逐框翻譯（串流進度）
let autoOcrRunning=false, autoProgEl=null;
function showAutoProgress(txt){
  if(!autoProgEl){
    autoProgEl=document.createElement('div');
    autoProgEl.style.cssText='position:fixed;left:50%;top:14px;transform:translateX(-50%);z-index:9999;background:rgba(15,17,33,.96);color:#fff;padding:10px 18px;border-radius:999px;font-size:14px;font-weight:700;border:1px solid rgba(81,119,255,.7);box-shadow:0 8px 24px rgba(0,0,0,.5);';
    document.body.appendChild(autoProgEl);
  }
  autoProgEl.textContent='🤖 自動 OCR：'+txt;
  autoProgEl.style.display='block';
}
function hideAutoProgress(){ if(autoProgEl){ autoProgEl.remove(); autoProgEl=null; } }
async function startAutoOcr(){
  if(autoOcrRunning || !images.length) return;
  // 兩步確認，避免誤觸
  if(!confirm('是否要開始自動 OCR？\n（將偵測所有頁面文字、自動標號並翻譯）')) return;
  if(markers.length){
    if(!confirm(`檢測到現有標號 ${markers.length} 個，是否繼續自動 OCR？\n（會取代所有頁面的現有標號）`)) return;
  }
  autoOcrRunning=true;
  showAutoProgress('準備中…');
  try{
    // 處理所有頁面：不傳 img，後端走 stream_auto_ocr_all
    const resp=await fetch('/api/ocr/auto',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({all:true})});
    if(!resp.ok){
      let msg='HTTP '+resp.status;
      try{ msg=(await resp.json()).error||msg; }catch(_){}
      hideAutoProgress(); alert('自動 OCR 失敗: '+msg); return;
    }
    const reader=resp.body.getReader();
    const decoder=new TextDecoder();
    let buf='';
    let totalPages=0, curPage=0, pageTotal=0, pageDone=0;
    let totalMarkers=0, errors=[];
    while(true){
      const {value, done:rd}=await reader.read();
      if(rd) break;
      buf+=decoder.decode(value,{stream:true});
      let nl;
      while((nl=buf.indexOf('\n'))!==-1){
        const line=buf.slice(0,nl).trim(); buf=buf.slice(nl+1);
        if(!line) continue;
        let ev; try{ ev=JSON.parse(line); }catch(_){ continue; }
        if(ev.type==='info'){ totalPages=ev.total_pages||0; showAutoProgress(`0/${totalPages} 頁`); }
        else if(ev.type==='page_start'){ curPage=ev.page||0; showAutoProgress(`第 ${curPage}/${totalPages} 頁：${ev.img||''}`); }
        else if(ev.type==='start'){ pageTotal=ev.total||0; pageDone=0; showAutoProgress(`第 ${curPage}/${totalPages} 頁 ${pageDone}/${pageTotal}`); }
        else if(ev.type==='progress'){ pageDone=ev.done||0; showAutoProgress(`第 ${curPage}/${totalPages} 頁 ${pageDone}/${pageTotal}`); }
        else if(ev.type==='page_done'){ totalMarkers+=(ev.count||0); if(ev.img===images[cur]){ /* 當前頁稍後重載 */ } }
        else if(ev.type==='log'){ /* 進度訊息，已由 page_start/progress 顯示 */ }
        else if(ev.type==='done'){ /* 全部完成 */ if(ev.errors) errors=ev.errors; }
        else if(ev.type==='error'){ hideAutoProgress(); alert('自動 OCR 失敗: '+(ev.error||'')); return; }
      }
    }
    hideAutoProgress();
    // 後端已逐頁寫入 TXT + originals 快取，前端只需重新載入當前頁
    await loadPage(false);
    const errMsg = errors.length ? `，${errors.length} 頁失敗` : '';
    toast(`🤖 自動 OCR 完成，共 ${totalMarkers} 個標號${errMsg}`);
  }catch(err){
    hideAutoProgress();
    alert('自動 OCR 網路錯誤: '+err);
  }finally{
    autoOcrRunning=false;
  }
}
const bAutoOcr=document.getElementById('bAutoOcr');
if(bAutoOcr){ bAutoOcr.onclick=()=>{ startAutoOcr(); }; }
// 🔍 OCR 調試模式
const bDebug=document.getElementById('bDebug');
let _debugOcr=false;
function _applyDebugStyle(){
  if(bDebug) bDebug.style.background=_debugOcr?'rgba(233,69,96,.55)':'';
}
fetch('/api/debug').then(r=>r.json()).then(d=>{ _debugOcr=!!d.debug_ocr; _applyDebugStyle(); }).catch(()=>{});
if(bDebug){
  bDebug.onclick=()=>{
    fetch('/api/debug/toggle',{method:'POST'}).then(r=>r.json()).then(d=>{
      _debugOcr=!!d.debug_ocr; _applyDebugStyle();
      toast('🔍 調試模式：'+(_debugOcr?'已開啟（輸出到 _debug/）':'已關閉'));
    }).catch(e=>{ toast('切換失敗: '+e); });
  };
}
// 📚 復習帳入口
const bReview=document.getElementById('bReview');
if(bReview){ bReview.onclick=()=>{ location.href='/review'; }; }
// 每天啟動：若今天有該複習的考點，顯示提示列
function maybeShowReviewBanner(){
  const el=document.getElementById('reviewBanner');
  if(!el) return;
  fetch('/api/review/dashboard').then(r=>r.json()).then(d=>{
    const db=(d&&d.dashboard)||{};
    const due=db.due_count||0;
    if(!due) return;
    const today=db.date||new Date().toISOString().slice(0,10);
    if(localStorage.getItem('review_banner_'+today)) return;
    el.innerHTML='📚 今天有 '+due+' 個考點該複習，點此前往 →<span class="x">✕</span>';
    el.style.display='';
    el.onclick=(e)=>{
      if(e.target.classList.contains('x')){ localStorage.setItem('review_banner_'+today,'1'); el.style.display='none'; return; }
      location.href='/review';
    };
  }).catch(()=>{});
}
// 開機同步 OCR 待命狀態
fetch('/api/ocr/status').then(r=>r.json()).then(d=>{
  const s=d.ocr||{};
  ocrReady = s.status==='ready';
  ocrLoading = s.status==='loading';
  refreshOcrWarm();
}).catch(()=>{});

// 📤 導出原文
const bExport=document.getElementById('bExport');
const exportModal=document.getElementById('exportModal');
if(bExport){ bExport.onclick=()=>{
  exportModal.style.display='flex';
  // 從後端讀取預設提示詞
  fetch('/api/markdown/defaults').then(r=>r.json()).then(d=>{
    if(d.system) document.getElementById('exportSystem').value=d.system;
    if(d.instruction) document.getElementById('exportInstruction').value=d.instruction;
    if(d.output_format) document.getElementById('exportOutputFormat').value=d.output_format;
  }).catch(()=>{});
}; }
document.getElementById('exportClose').onclick=()=>{ exportModal.style.display='none'; };
document.getElementById('exportCancel').onclick=()=>{ exportModal.style.display='none'; };
exportModal.addEventListener('click',e=>{ if(e.target===exportModal) exportModal.style.display='none'; });

document.getElementById('exportBtn').onclick=()=>{
  const scope=document.querySelector('input[name="exportScope"]:checked').value;
  const payload={
    system:document.getElementById('exportSystem').value.trim(),
    instruction:document.getElementById('exportInstruction').value.trim(),
    output_format:document.getElementById('exportOutputFormat').value.trim()
  };
  if(scope==='page'){
    if(!images.length){ alert('沒有圖片'); return; }
    payload.img=images[cur];
  }
  fetch('/api/markdown/export',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(r=>r.json())
    .then(d=>{
      if(d.error){ alert('導出失敗: '+d.error); return; }
      // 下載文件
      const blob=new Blob([d.markdown],{type:'text/markdown;charset=utf-8'});
      const url=URL.createObjectURL(blob);
      const a=document.createElement('a');
      a.href=url; a.download=d.filename||'translation.md';
      document.body.appendChild(a); a.click(); document.body.removeChild(a);
      URL.revokeObjectURL(url);
      exportModal.style.display='none';
      toast('📤 導出成功');
    })
    .catch(err=>alert('導出失敗: '+err));
};

// 📥 導入譯文
const bImport=document.getElementById('bImport');
const importModal=document.getElementById('importModal');
if(bImport){ bImport.onclick=()=>{ importModal.style.display='flex'; }; }
document.getElementById('importClose').onclick=()=>{ importModal.style.display='none'; };
document.getElementById('importCancel').onclick=()=>{ importModal.style.display='none'; };
importModal.addEventListener('click',e=>{ if(e.target===importModal) importModal.style.display='none'; });

document.getElementById('importBtn').onclick=()=>{
  const scope=document.querySelector('input[name="importScope"]:checked').value;
  const content=document.getElementById('importContent').value.trim();
  if(!content){ alert('請粘貼 Markdown 內容'); return; }
  
  const endpoint=scope==='all' ? '/api/markdown/import_all' : '/api/markdown/import';
  const payload={markdown:content};
  if(scope==='page'){
    if(!images.length){ alert('沒有圖片'); return; }
    payload.img=images[cur];
  }
  
  fetch(endpoint,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})
    .then(r=>r.json())
    .then(d=>{
      if(d.error){ alert('導入失敗: '+d.error); return; }
      importModal.style.display='none';
      document.getElementById('importContent').value='';
      // 重新載入頁面
      loadPage();
      const msg=scope==='all'
        ? `📥 導入完成：${d.total_pages} 頁，${d.total_updated} 個標號`
        : `📥 導入完成：${d.updated} 個標號`;
      toast(msg);
    })
    .catch(err=>alert('導入失敗: '+err));
};

// 🗑 清空當前頁標號
const bClearPage=document.getElementById('bClearPage');
if(bClearPage){ bClearPage.onclick=()=>{
  if(!markers.length){ toast('此頁沒有標號'); return; }
  if(!confirm(`確定要清空當前頁全部 ${markers.length} 個標號？\n此操作不可撤銷。`)) return;
  markers=[];
  persist(()=>{ renderMarkers(); toast('已清空當前頁標號'); });
}; }

// Esc 關閉導出/導入模態框
document.addEventListener('keydown',e=>{
  if(e.key==='Escape'){
    if(exportModal.style.display==='flex'){ exportModal.style.display='none'; }
    if(importModal.style.display==='flex'){ importModal.style.display='none'; }
  }
});

loadPage(); updateInOut(); updateKb(); updateURL(); runSpeedTestOnce(); maybeShowReviewBanner(); refreshReviewKnown();
