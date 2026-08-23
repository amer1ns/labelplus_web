/* 📚 復習帳 — 間隔複習小程式 */
(function(){
'use strict';
let DASH={queue:[],due_count:0,new_count:0,review_count:0,mastered_count:0,date:''};
let ITEMS=[];
let QUEUE=[], qi=0, revealed=false, tab='due', editingId=null;

const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/\n/g,'<br>');

function toast(msg,ms=1800){
  const t=document.createElement('div');
  t.className='toast';
  t.innerHTML=esc(msg);
  document.body.appendChild(t);
  setTimeout(()=>t.remove(),ms);
}
async function api(path,opts){
  const r=await fetch(path,opts);
  const d=await r.json().catch(()=>({}));
  if(!r.ok && d.error) throw new Error(d.error);
  return d;
}

function fmtDate(ds){
  if(!ds) return '';
  const t=new Date(ds+'T00:00:00');
  const today=new Date(); today.setHours(0,0,0,0);
  const diff=Math.round((t-today)/86400000);
  if(diff===0) return '今天';
  if(diff===1) return '明天';
  if(diff===-1) return '昨天';
  if(diff>1 && diff<8) return diff+' 天後';
  if(diff<-1 && diff>-8) return (-diff)+' 天前';
  return ds;
}
const STATUS_LABEL={new:'新學',learning:'複習中',review:'複習中',mastered:'已掌握'};

// ---------------- 載入 ----------------
async function loadAll(){
  try{
    const [d1,d2]=await Promise.all([api('/api/review/dashboard'),api('/api/review/items')]);
    DASH=d1.dashboard||DASH;
    ITEMS=d2.items||[];
  }catch(e){ toast('載入失敗: '+e.message); }
  renderStats();
  QUEUE=(DASH.queue||[]).slice(); qi=0; revealed=false;
  renderTabs(); renderList(); nextCard();
}

function renderStats(){
  $('stDue').querySelector('b').textContent=DASH.due_count||0;
  $('stNew').querySelector('b').textContent=DASH.new_count||0;
  $('stReview').querySelector('b').textContent=DASH.review_count||0;
  $('stMastered').querySelector('b').textContent=DASH.mastered_count||0;
  $('rvDate').textContent=(DASH.date||'')+' · 每天自動標記：學了／該複習／已掌握';
}

// ---------------- 卡片 ----------------
function currentItem(){ return QUEUE[qi]||null; }

function renderCardMeta(it){
  const parts=[];
  const src=[it.manga_name, it.page_name||it.img].filter(Boolean).join(' / ');
  if(src){
    let s='來源：'+src;
    if(it.marker_id!=null && it.marker_id!==-1) s+=' #'+it.marker_id;
    if(it.marker_x!=null && it.marker_y!=null) s+=' ('+Number(it.marker_x).toFixed(2)+','+Number(it.marker_y).toFixed(2)+')';
    parts.push(s);
  }
  parts.push('狀態：'+(STATUS_LABEL[it.status]||it.status));
  parts.push('下次複習：'+fmtDate(it.due));
  if(it.reps) parts.push('已複習 '+it.reps+' 次');
  if(it.lapses) parts.push('忘記 '+it.lapses+' 次');
  return parts.join(' · ');
}

function nextCard(){
  revealed=false;
  const it=currentItem();
  $('gradeRow').hidden=true;
  $('cReveal').style.display='';
  $('queueEmpty').hidden=true;
  $('card').style.display='flex';
  if(!it){
    $('card').style.display='none';
    $('queueEmpty').hidden=false;
    return;
  }
  $('cOrig').textContent=it.original||'（無原文）';
  const pt=(it.point||'').trim();
  const cPoint=$('cPoint'), cCtx=$('cCtx');
  if(pt){
    cPoint.style.display=''; cPoint.textContent=pt;
    cCtx.style.display=''; cCtx.textContent='原文：'+(it.original||'（無原文）');
  }else{
    cPoint.style.display='none';
    cCtx.style.display='none';
  }
  const pts=(it.grammar||'').split('\n').filter(l=>l.trim()).length;
  const tranHint=it.translation?' 譯文已就緒':'';
  $('cHint').innerHTML='點卡片或按空白鍵顯示答案'+(pts?(' · 語法點 '+pts+' 條'):'')+tranHint;
  $('cBack').hidden=true;
  $('card').classList.remove('flipped');
}

function reveal(){
  const it=currentItem();
  if(!it||revealed) return;
  revealed=true;
  $('cBack').hidden=false;
  $('card').classList.add('flipped');
  $('cReveal').style.display='none';
  $('gradeRow').hidden=false;
  $('cTran').textContent=it.translation||'（無譯文）';
  setSec('cGrammar','語法點',it.grammar);
  setSec('cMeaning','含義解析',it.meaning);
  setSec('cExample','例句',it.example);
  setSec('cConfusion','易混淆',it.confusion);
  $('cMeta').textContent=renderCardMeta(it);
}
function setSec(id,title,val){
  const el=$(id);
  if(val&&String(val).trim()){ el.innerHTML='<span class="t">'+title+'</span><div class="v">'+esc(val)+'</div>'; el.style.display=''; }
  else el.style.display='none';
}

async function grade(g){
  const it=currentItem();
  if(!it) return;
  try{
    if(g==='skip'){
      await api('/api/review/items/'+encodeURIComponent(it.id)+'/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'skip'})});
      toast('⏭ 已跳過，明天再來');
    }else{
      await api('/api/review/items/'+encodeURIComponent(it.id)+'/grade',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({grade:g})});
      const label={again:'😵 忘了，重新學',hard:'🤔 困難，縮短間隔',good:'🙂 記得！',easy:'😎 很熟！'}[g]||'';
      toast(label);
    }
    const d=await api('/api/review/dashboard');
    DASH=d.dashboard||DASH;
    renderStats();
    QUEUE=(DASH.queue||[]).slice();
    qi=Math.min(qi,QUEUE.length-1);
    renderList();
    nextCard();
  }catch(e){ toast('評分失敗: '+e.message); }
}

// ---------------- 清單 ----------------
function filtered(){
  const statusMap={new:['new'],learning:['review','learning'],mastered:['mastered'],all:null,due:null};
  const keys=statusMap[tab]||statusMap.all;
  let list=ITEMS.slice();
  if(keys) list=list.filter(it=>keys.includes(it.status));
  if(tab==='due'){
    const dueSet=new Set((DASH.queue||[]).map(it=>it.id));
    list=list.filter(it=>dueSet.has(it.id));
  }
  return list;
}

function renderList(){
  const list=filtered();
  $('listHead').textContent=tab==='due'
    ?('今日待複習 '+list.length+' 個'+(DASH.due_count>list.length?('（含逾期 '+DASH.due_count+' 個）'):''))
    :('共 '+list.length+' 個考點');
  const ul=$('itemList');
  ul.innerHTML='';
  if(!list.length){ ul.innerHTML='<li style="color:#667;text-align:center;padding:18px;font-size:13px;">（空）</li>'; return; }
  list.forEach(it=>{
    const li=document.createElement('li');
    li.className='row';
    const badgeClass=it.status==='mastered'?'mastered':(it.status==='new'?'new':'review');
    li.innerHTML=
      '<div class="rid '+(it.img?'in':'out')+'">'+(it.marker_id==null||it.marker_id===-1?'?':esc(it.marker_id))+'</div>'+
      '<div class="rbody"><div class="rorig">'+esc((it.point?it.point+' ｜ ':'')+(it.original||'（無原文）'))+'</div>'+
      '<div class="rtran">'+esc(it.translation||'')+'</div>'+
      '<div class="rsrc">'+esc([it.manga_name,it.page_name||it.img].filter(Boolean).join(' / '))+
        (it.marker_x!=null&&it.marker_y!=null?' ('+Number(it.marker_x).toFixed(2)+','+Number(it.marker_y).toFixed(2)+')':'')+'</div></div>'+
      '<div class="rmeta"><span class="badge '+badgeClass+'">'+(STATUS_LABEL[it.status]||it.status)+'</span>'+
      '<span>'+(it.status==='mastered'?'偶爾複習 · '+fmtDate(it.due):fmtDate(it.due))+'</span>'+
      (it.page_name||it.img?'<a class="golink" href="/mark/'+encodeURIComponent(it.page_name||it.img)+'" onclick="event.stopPropagation()">↗ 原文</a>':'')+
      '</div>';
    li.onclick=()=>openModal(it);
    ul.appendChild(li);
  });
}

function renderTabs(){
  document.querySelectorAll('#tabs button').forEach(b=>b.classList.toggle('on',b.dataset.f===tab));
}

// ---------------- 詳情 modal ----------------
function openModal(it){
  editingId=it.id;
  const src=[it.manga_name, it.page_name||it.img].filter(Boolean).join(' / ');
  $('imTitle').textContent='考點詳情'+(src?' · '+src:'')+(it.marker_id!=null&&it.marker_id!==-1?' #'+it.marker_id:'');
  $('imPoint').value=it.point||'';
  $('imOrig').value=it.original||'';
  $('imTran').value=it.translation||'';
  $('imNote').value=it.note||'';
  $('imGrammar').value=it.grammar||'';
  $('imMeaning').value=it.meaning||'';
  $('imExample').value=it.example||'';
  $('imConfusion').value=it.confusion||'';
  $('imStatus').textContent='狀態：'+(STATUS_LABEL[it.status]||it.status)+' · 間隔 '+it.interval_days+' 天 · 下次複習 '+fmtDate(it.due)+' · 已複習 '+it.reps+' 次 · 忘記 '+it.lapses+' 次';
  $('itemModal').style.display='flex';
}
function closeModal(){ $('itemModal').style.display='none'; editingId=null; }

async function saveModal(){
  if(!editingId) return;
  const body={
    point:$('imPoint').value, original:$('imOrig').value, translation:$('imTran').value, note:$('imNote').value,
    grammar:$('imGrammar').value, meaning:$('imMeaning').value,
    example:$('imExample').value, confusion:$('imConfusion').value,
  };
  try{
    await api('/api/review/items/'+encodeURIComponent(editingId),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    toast('💾 已保存');
    closeModal();
    await loadAll();
  }catch(e){ toast('保存失敗: '+e.message); }
}

async function aiModal(){
  if(!editingId) return;
  const btn=$('imAi');
  btn.disabled=true; btn.textContent='拆解中…';
  try{
    const preOrig=($('imOrig').value||'').trim();
    const d=await api('/api/review/items/'+encodeURIComponent(editingId)+'/ai',{method:'POST'});
    const it=d.item;
    $('imGrammar').value=it.grammar||'';
    $('imMeaning').value=it.meaning||'';
    $('imExample').value=it.example||'';
    $('imConfusion').value=it.confusion||'';
    const corr=(d.corrected||'').trim();
    if(corr && corr!==preOrig){
      $('imOrig').value=corr;
      toast('🤖 拆解完成；原文已依譯文修正，可再編輯');
    } else {
      toast('🤖 拆解完成，可再編輯');
    }
  }catch(e){ toast('AI 拆解失敗: '+e.message); }
  finally{ btn.disabled=false; btn.textContent='🤖 AI 拆解'; }
}

async function stateModal(action){
  if(!editingId) return;
  try{
    await api('/api/review/items/'+encodeURIComponent(editingId)+'/state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
    toast(action==='master'?'✔ 已標記為「已掌握」，偶爾複習即可':'🔄 已重新學習');
    closeModal();
    await loadAll();
  }catch(e){ toast('操作失敗: '+e.message); }
}

async function delModal(){
  if(!editingId) return;
  if(!confirm('確定刪除這個考點？')) return;
  try{
    await api('/api/review/items/'+encodeURIComponent(editingId),{method:'DELETE'});
    toast('🗑 已刪除');
    closeModal();
    await loadAll();
  }catch(e){ toast('刪除失敗: '+e.message); }
}

async function randomMastered(){
  const list=ITEMS.filter(it=>it.status==='mastered');
  if(!list.length){ toast('還沒有已掌握的考點'); return; }
  const it=list[Math.floor(Math.random()*list.length)];
  openModal(it);
}

// ---------------- 事件 ----------------
$('cReveal').onclick=reveal;
$('card').onclick=reveal;
document.querySelectorAll('#gradeRow .g').forEach(b=>{
  b.onclick=e=>{ e.stopPropagation(); grade(b.dataset.g); };
});
document.querySelectorAll('#tabs button').forEach(b=>{
  b.onclick=()=>{ tab=b.dataset.f; renderTabs(); renderList(); };
});
$('btnRandom').onclick=randomMastered;
$('imX').onclick=closeModal;
$('imClose').onclick=closeModal;
$('imSave').onclick=saveModal;
$('imAi').onclick=aiModal;
$('imMaster').onclick=()=>stateModal('master');
$('imRelearn').onclick=()=>stateModal('relearn');
$('imDel').onclick=delModal;
$('itemModal').addEventListener('click',e=>{ if(e.target===$('itemModal')) closeModal(); });

document.addEventListener('keydown',e=>{
  if($('itemModal').style.display==='flex'){
    if(e.key==='Escape') closeModal();
    else if((e.ctrlKey||e.metaKey)&&e.key==='Enter') saveModal();
    return;
  }
  const tag=(document.activeElement&&document.activeElement.tagName||'').toLowerCase();
  if(tag==='textarea'||tag==='input') return;
  if(e.key===' '||e.key==='Enter'){ e.preventDefault(); reveal(); }
  else if(revealed){
    const map={'1':'again','2':'hard','3':'good','4':'easy','5':'skip'};
    if(map[e.key]) grade(map[e.key]);
  }
});

loadAll();
})();
