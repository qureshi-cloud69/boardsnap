const API = ''; // same origin — backend serves frontend
// cache-bust 20241002-v3-wildcard
let currentTiles = [];
let currentImageFile = null;
let currentImageBase64 = null;
let currentResults = null;
let currentCommonOnly = false;
let currentUseWildcards = true;

// DOM
const dropzone = document.getElementById('dropzone');
const fileInput = document.getElementById('fileInput');
const browseBtn = document.getElementById('browseBtn');
const processing = document.getElementById('processing');
const procSub = document.getElementById('procSub');
const detectSection = document.getElementById('detect-section');
const resultsSection = document.getElementById('results-section');
const uploadSection = document.getElementById('upload-section');
const examplesSection = document.getElementById('examples');
const errorSection = document.getElementById('error-section');
const errorMsg = document.getElementById('errorMsg');
const tileGrid = document.getElementById('tileGrid');
const detectedCountEl = document.getElementById('detectedCount');
const emptyCountLabel = document.getElementById('emptyCountLabel');
const wildcardCountLabel = document.getElementById('wildcardCountLabel');
const originalPreview = document.getElementById('originalPreview');
const heroWord = document.getElementById('heroWord');
const heroScore = document.getElementById('heroScore');
const heroLen = document.getElementById('heroLen');
const heroPathLen = document.getElementById('heroPathLen');
const heroImage = document.getElementById('heroImage');
const heroDownload = document.getElementById('heroDownload');
const heroWildcard = document.getElementById('heroWildcard');
const trapWarning = document.getElementById('trapWarning');
const wildcardExplain = document.getElementById('wildcardExplain');
const commonToggle = document.getElementById('commonToggle');
const commonToggleDetect = document.getElementById('commonToggleDetect');
const wildcardToggle = document.getElementById('wildcardToggle');
const wildcardToggleDetect = document.getElementById('wildcardToggleDetect');
const wildcardToggleHero = document.getElementById('wildcardToggleHero');
const searchAll = document.getElementById('searchAll');

// Sync wildcard toggles
function getUseWildcards(){
  // priority: detect toggle if visible, else hero, else main
  if (wildcardToggleDetect && !detectSection.classList.contains('hidden')) return wildcardToggleDetect.checked;
  if (wildcardToggle && !resultsSection.classList.contains('hidden')) return wildcardToggle.checked;
  if (wildcardToggleHero) return wildcardToggleHero.checked;
  return wildcardToggle ? wildcardToggle.checked : true;
}
function syncWildcardToggles(val){
  if(wildcardToggle) wildcardToggle.checked = val;
  if(wildcardToggleDetect) wildcardToggleDetect.checked = val;
  if(wildcardToggleHero) wildcardToggleHero.checked = val;
}
if(wildcardToggle) wildcardToggle.addEventListener('change', e=> syncWildcardToggles(e.target.checked));
if(wildcardToggleDetect) wildcardToggleDetect.addEventListener('change', e=> syncWildcardToggles(e.target.checked));
if(wildcardToggleHero) wildcardToggleHero.addEventListener('change', e=> syncWildcardToggles(e.target.checked));

// browse
browseBtn.addEventListener('click', e=>{ e.stopPropagation(); fileInput.click(); });
dropzone.addEventListener('click', ()=> fileInput.click());
fileInput.addEventListener('change', e=>{
  if(e.target.files[0]) handleFile(e.target.files[0]);
});
['dragenter','dragover'].forEach(ev=>{
  dropzone.addEventListener(ev, e=>{ e.preventDefault(); dropzone.classList.add('drag'); });
});
['dragleave','drop'].forEach(ev=>{
  dropzone.addEventListener(ev, e=>{ e.preventDefault(); dropzone.classList.remove('drag'); });
});
dropzone.addEventListener('drop', e=>{
  const f = e.dataTransfer.files[0];
  if(f) handleFile(f);
});

async function loadExamples(){
  const grid = document.getElementById('exampleGrid');
  try{
    const res = await fetch('/api/examples');
    const data = await res.json();
    const examples = data.examples || [];
    grid.innerHTML = '';
    examples.forEach(ex=>{
      const card = document.createElement('div');
      card.className='example-card';
      const imgUrl = ex.image_url || `/api/example/${ex.id}/image`;
      const blanks = (ex.hole_indices ? ex.hole_indices.length : 0);
      card.innerHTML = `<img src="${imgUrl}" alt="Sample ${ex.id}"><div class="example-card-body"><strong>Sample ${ex.id} — ${ex.target_word||''}</strong><div>${ex.letters? ex.letters.length+' tiles' : 'Demo board'} • ${blanks} ★ blank${blanks!==1?'s':''} • try wildcards!</div></div>`;
      card.addEventListener('click', ()=> solveExample(ex.id));
      grid.appendChild(card);
    });
    if(examples.length===0){
      grid.innerHTML = '<div style="color:var(--muted)">No samples found.</div>';
    }
  }catch(e){
    grid.innerHTML = '<div style="color:var(--muted)">Could not load samples.</div>';
  }
}
loadExamples();

function showProcessing(msg){
  processing.classList.remove('hidden');
  procSub.textContent = msg || 'Detecting bubbles & reading letters';
  detectSection.classList.add('hidden');
  resultsSection.classList.add('hidden');
  errorSection.classList.add('hidden');
  window.scrollTo({top: processing.offsetTop - 80, behavior:'smooth'});
}
function hideProcessing(){
  processing.classList.add('hidden');
}
function showError(msg){
  hideProcessing();
  errorSection.classList.remove('hidden');
  errorMsg.textContent = msg;
  errorSection.scrollIntoView({behavior:'smooth', block:'center'});
}
document.getElementById('errorDismiss').addEventListener('click', ()=> errorSection.classList.add('hidden'));

async function handleFile(file){
  if(!file.type.startsWith('image/')){
    showError('Please upload an image file (PNG/JPG/WEBP).');
    return;
  }
  currentImageFile = file;
  currentImageBase64 = await fileToBase64(file);
  originalPreview.src = currentImageBase64;
  showProcessing('Detecting bubbles & reading letters…');
  try{
    const form = new FormData();
    form.append('file', file);
    const res = await fetch('/api/detect', {method:'POST', body: form});
    const data = await res.json();
    if(!res.ok){
      if(data.tiles){
        hideProcessing();
        renderDetect(data);
        showError(data.error || 'Low tile count — please try a clearer, centered screenshot or fix tiles manually below.');
        return;
      }
      throw new Error(data.detail || data.error || 'Detection failed');
    }
    hideProcessing();
    renderDetect(data);
  }catch(err){
    hideProcessing();
    showError(err.message || 'Detection failed');
  }
}

function fileToBase64(file){
  return new Promise((res, rej)=>{
    const r=new FileReader();
    r.onload=()=>res(r.result);
    r.onerror=rej;
    r.readAsDataURL(file);
  });
}

function renderDetect(data){
  currentTiles = data.tiles || [];
  detectedCountEl.textContent = data.detected_count || currentTiles.length;
  emptyCountLabel.textContent = data.empty_count ? `· ${data.empty_count} holes` : '';
  const wcCount = data.wildcard_count || currentTiles.filter(t=>t.is_wildcard || t.is_blank).length;
  if(wildcardCountLabel) wildcardCountLabel.textContent = wcCount ? `★ ${wcCount} blank wildcard${wcCount!==1?'s':''}` : '';
  originalPreview.src = currentImageBase64;
  tileGrid.innerHTML='';
  currentTiles.forEach((t, idx)=>{
    const div=document.createElement('div');
    const isWildcard = !!(t.is_wildcard || t.is_blank);
    const isEmpty = !!t.is_empty && !isWildcard;
    const low = !isEmpty && !isWildcard && (t.confidence < 0.6 || t.letter==='?' || !t.letter);
    div.className='tile'+(isEmpty?' empty':'')+(isWildcard?' wildcard':'')+(low?' low':'');
    if(isWildcard) div.style.borderColor = 'rgba(212,169,106,0.55)';
    div.dataset.idx=idx;
    const letterDisplay = isWildcard ? '★' : (isEmpty ? '·' : (t.letter||'?'));
    const valueDisplay = isWildcard ? '0★' : (isEmpty ? '' : (t.value||0));
    const wcBadge = isWildcard ? `<div style="position:absolute;bottom:4px;left:6px;font-size:9px;background:rgba(212,169,106,0.18);color:#e8c99a;padding:1px 4px;border-radius:999px;border:1px solid rgba(212,169,106,0.28)">BLANK</div>` : '';
    div.innerHTML=`
      <div class="tile-coord">${t.row>=0? t.row+1: '?'}-${t.col>=0? t.col+1:'?'}</div>
      ${!isEmpty && !isWildcard && t.confidence<0.9 ? `<div class="tile-conf">${Math.round(t.confidence*100)}%</div>`:''}
      ${isWildcard ? `<div class="tile-conf" style="color:#e8c99a;background:rgba(212,169,106,0.14);border-color:rgba(212,169,106,0.22)">★</div>` : ''}
      <div class="tile-letter" style="${isWildcard ? 'color:#e8c99a' : ''}">${letterDisplay}</div>
      <div class="tile-value">${valueDisplay}</div>
      ${wcBadge}
    `;
    div.title = isWildcard ? 'Blank wildcard — can be any letter A-Z for 0 pts' : (isEmpty ? 'Hole (skipped)' : `${t.letter} = ${t.value} pts`);
    div.addEventListener('click', ()=> openEdit(idx));
    tileGrid.appendChild(div);
  });
  detectSection.classList.remove('hidden');
  detectSection.scrollIntoView({behavior:'smooth', block:'start'});
  // sync wildcard toggle to current detection
  if (typeof data.wildcard_count !== 'undefined' && data.wildcard_count>0) {
    // if blanks found, ensure wildcard toggle is ON per game logic
    // don't force if user explicitly turned off
  }
}

// Tile edit modal
let editIdx=null;
const editModal=document.getElementById('editModal');
const editInput=document.getElementById('editInput');
const editEmpty=document.getElementById('editEmpty');
const editWildcard=document.getElementById('editWildcard');
function openEdit(idx){
  editIdx=idx;
  const t=currentTiles[idx];
  const isWc = !!(t.is_wildcard || t.is_blank);
  const isHole = !!t.is_empty && !isWc;
  editInput.value = (isWc || isHole) ? '' : (t.letter||'');
  if(editWildcard) editWildcard.checked = isWc;
  editEmpty.checked = isHole;
  // wildcard and hole are mutually exclusive
  editModal.classList.remove('hidden');
  editInput.focus();
  editInput.select();
}
document.getElementById('editCancel').addEventListener('click', ()=> {editModal.classList.add('hidden');});
editModal.addEventListener('click', e=>{ if(e.target===editModal) editModal.classList.add('hidden');});
editInput.addEventListener('input', ()=>{
  editInput.value = editInput.value.toUpperCase().replace(/[^A-Z]/g,'');
  if(editInput.value) {
    if(editWildcard) editWildcard.checked = false;
    editEmpty.checked = false;
  }
});
if(editWildcard) editWildcard.addEventListener('change', ()=>{
  if(editWildcard.checked) {
    editEmpty.checked = false;
    editInput.value='';
  }
});
editEmpty.addEventListener('change', ()=>{
  if(editEmpty.checked) {
    if(editWildcard) editWildcard.checked = false;
    editInput.value='';
  }
});
document.getElementById('editSave').addEventListener('click', ()=>{
  if(editIdx===null) return;
  const t=currentTiles[editIdx];
  const isHole=editEmpty.checked;
  const isWc = editWildcard ? editWildcard.checked : false;
  let letter=editInput.value.trim().toUpperCase();
  if(isWc){
    t.letter=''; t.is_wildcard=true; t.is_blank=true; t.is_empty=false; t.value=0; t.confidence=1.0;
  } else if(isHole){
    t.letter=''; t.is_empty=true; t.is_wildcard=false; t.is_blank=false; t.value=0; t.confidence=1.0;
  } else {
    if(letter.length===0) letter='?';
    if(letter.length>1) letter=letter[0];
    if(!/^[A-Z]$/.test(letter)) letter='?';
    t.letter=letter; t.is_empty=false; t.is_wildcard=false; t.is_blank=false;
    const vals={A:1,B:3,C:3,D:2,E:1,F:4,G:2,H:4,I:1,J:8,K:5,L:1,M:3,N:1,O:1,P:3,Q:10,R:1,S:1,T:1,U:1,V:4,W:4,X:8,Y:4,Z:10};
    t.value=vals[letter]||1;
    t.confidence=0.99;
  }
  editModal.classList.add('hidden');
  const wcCount = currentTiles.filter(x=>x.is_wildcard||x.is_blank).length;
  const holeCount = currentTiles.filter(x=>x.is_empty).length;
  renderDetect({tiles:currentTiles, detected_count: currentTiles.length, empty_count: holeCount, wildcard_count: wcCount});
});

async function solveWithTiles(){
  if(currentTiles.length<10){
    showError('Need at least 10 playable tiles. Please fix detection.');
    return;
  }
  const common = commonToggleDetect.checked || commonToggle.checked;
  const useWildcards = getUseWildcards();
  currentUseWildcards = useWildcards;
  showProcessing(useWildcards ? 'Solving — trying A-Z for each ★ blank (wildcard)…' : 'Solving board — trie DFS…');
  try{
    const payload = {
      tiles: currentTiles,
      common_only: common,
      use_wildcards: useWildcards,
      image_base64: currentImageBase64
    };
    const res = await fetch('/api/solve-tiles', {
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if(!res.ok){
      throw new Error(data.detail || JSON.stringify(data));
    }
    hideProcessing();
    renderResults(data);
  }catch(e){
    hideProcessing();
    showError(e.message || 'Solve failed');
  }
}

document.getElementById('solveBtn').addEventListener('click', solveWithTiles);
document.getElementById('solveBtn2').addEventListener('click', solveWithTiles);
document.getElementById('rescanBtn').addEventListener('click', ()=>{
  if(currentImageFile) handleFile(currentImageFile);
});
document.getElementById('editTilesBtn').addEventListener('click', ()=>{
  resultsSection.classList.add('hidden');
  detectSection.classList.remove('hidden');
  detectSection.scrollIntoView({behavior:'smooth'});
});
document.getElementById('newUploadBtn').addEventListener('click', ()=>{
  resultsSection.classList.add('hidden');
  detectSection.classList.add('hidden');
  uploadSection.scrollIntoView({behavior:'smooth'});
});

async function solveExample(id){
  showProcessing('Solving demo board — wildcards A-Z…');
  const common = commonToggle.checked || commonToggleDetect.checked;
  const useWildcards = getUseWildcards();
  try{
    const res = await fetch(`/api/example/${id}/solve?common_only=${common}&use_wildcards=${useWildcards}`);
    const data = await res.json();
    if(!res.ok) throw new Error(data.detail || 'Failed to solve example');
    const imgRes = await fetch(`/api/example/${id}/image`);
    const blob = await imgRes.blob();
    currentImageFile = new File([blob], `sample_${id}.png`, {type:'image/png'});
    currentImageBase64 = await fileToBase64(currentImageFile);
    currentTiles = data.tiles || [];
    originalPreview.src = currentImageBase64;
    hideProcessing();
    renderResults(data);
  }catch(e){
    hideProcessing();
    showError(e.message);
  }
}

// Results rendering — with wildcard highlighting
function formatWordWithWildcards(word, wildcardMap, path, tiles){
  // wildcardMap is {tileIndex: letter} or null
  // Also tiles may have is_wildcard flag; we need to know which positions in word are from wildcards.
  // Build a reverse map: position in word -> is wildcard?
  if(!wildcardMap || Object.keys(wildcardMap).length===0) return word;
  // Need to map path order to word positions
  // path is tile indices in order; word[i] corresponds to path[i]
  // So if path[i] tile is in wildcardMap, that letter is wildcard
  let out = '';
  for(let i=0;i<word.length;i++){
    const tileIdx = path[i];
    const isWc = wildcardMap[tileIdx] !== undefined || (tiles && tiles[tileIdx] && tiles[tileIdx].is_wildcard);
    // wildcard letters are shown as ★ + letter or with different style
    if(isWc){
      out += `<span style="color:#d4a96a;font-weight:900;text-decoration:underline;text-decoration-color:rgba(212,169,106,0.5);text-underline-offset:3px" title="★ blank used as ${word[i]} (0 pts)">${word[i]}<sup style="font-size:0.6em;color:#d4a96a">★</sup></span>`;
    } else {
      out += word[i];
    }
  }
  return out;
}

function renderResults(data){
  currentResults = data;
  const topScore = data.results?.top_by_score || [];
  const topLength = data.results?.top_by_length || [];
  const all = data.results?.all || [];
  currentCommonOnly = data.common_filter;
  currentUseWildcards = data.use_wildcards !== undefined ? data.use_wildcards : getUseWildcards();

  if(topScore.length===0){
    showError('No valid words found on this board. Try checking for misread letters, toggle ★ Wildcards off, or toggle Common Only off.');
    return;
  }
  const best = topScore[0];
  // Build wildcard-aware word display
  const wcMapBest = best.wildcard_map || {};
  const wcCountBest = best.wildcard_count || Object.keys(wcMapBest).length;
  // For hero, show word with wildcard highlights if needed
  heroWord.innerHTML = formatWordWithWildcards(best.word, wcMapBest, best.path, data.tiles);
  heroScore.textContent = `${best.score} pts` + (wcCountBest ? ` (★x${wcCountBest} = 0)` : '');
  heroLen.textContent = `${best.length} letters`;
  heroPathLen.textContent = `${best.path.length} tiles`;
  if(heroWildcard){
    if(wcCountBest){
      heroWildcard.style.display='inline-block';
      heroWildcard.textContent = `★ ${wcCountBest} blank${wcCountBest>1?'s':''}`;
      heroWildcard.title = `Blank tiles used as ${Object.values(wcMapBest).join(', ')} (each 0 pts) — game randomly assigns letter`;
    } else {
      heroWildcard.style.display='none';
    }
  }
  if(data.hero_image){
    heroImage.src = data.hero_image;
    heroDownload.href = data.hero_image;
    heroDownload.download = `boardsnap-${best.word}-${best.score}pts${wcCountBest?'_wildcards':''}.png`;
  } else if(best.preview){
    heroImage.src = best.preview;
    heroDownload.href = best.preview;
  }
  document.getElementById('shareBtn').onclick = ()=>{
    navigator.clipboard.writeText(best.word);
    document.getElementById('shareBtn').textContent='Copied!';
    setTimeout(()=>document.getElementById('shareBtn').textContent='Copy word',1500);
  };
  // traps
  if(data.traps && data.traps.length>0){
    trapWarning.classList.remove('hidden');
    const vals = data.traps.map(t=> `${t.letter}(${t.value})`).join(', ');
    trapWarning.innerHTML = `⚠️ Trap tiles — 8/10-point tiles with <b>no</b> valid words: ${vals}. Consider ignoring them.`;
  }else{
    trapWarning.classList.add('hidden');
  }
  // wildcard explain
  if(wildcardExplain){
    const wcCountTotal = data.wildcard_count || (data.tiles ? data.tiles.filter(t=>t.is_wildcard||t.is_blank).length : 0);
    const totalFound = data.results?.total_found || 0;
    if(currentUseWildcards && wcCountTotal>0){
      wildcardExplain.classList.remove('hidden');
      // Show how many blanks and that solver tries A-Z
      const blankWordCount = topScore.filter(r=> (r.wildcard_count||0)>0).length;
      wildcardExplain.innerHTML = `★ <strong>Blanks are wildcards</strong> — ${wcCountTotal} blank bubble${wcCountTotal!==1?'s':''} on board. Solver tried <strong>every A-Z for each blank (0 pts)</strong> — like the game's backend (not skipped like the old wizgames site). <strong>${totalFound} words</strong> found, <strong>${blankWordCount}</strong> use blanks. Blank tiles are gold in the image and underlined in word.`;
    } else if(!currentUseWildcards && wcCountTotal>0){
      wildcardExplain.classList.remove('hidden');
      wildcardExplain.innerHTML = `★ Wildcards <strong>OFF</strong> — ${wcCountTotal} blank(s) treated as <strong>holes (skipped)</strong>, like the old site. Toggle ★ on to let them be any letter.`;
      wildcardExplain.style.background='rgba(212,169,106,0.08)';
    } else {
      wildcardExplain.classList.add('hidden');
    }
  }

  // update toggles
  commonToggle.checked = currentCommonOnly;
  commonToggleDetect.checked = currentCommonOnly;
  syncWildcardToggles(currentUseWildcards);

  // render lists
  renderList('list-score', topScore, data.tiles);
  renderList('list-length', topLength, data.tiles);
  renderAllList(all, data.tiles);

  // Show results
  detectSection.classList.add('hidden');
  resultsSection.classList.remove('hidden');
  resultsSection.scrollIntoView({behavior:'smooth', block:'start'});
  switchTab('score');
}

function renderList(containerId, list, tiles){
  const el=document.getElementById(containerId);
  el.innerHTML='';
  if(list.length===0){
    el.innerHTML='<div style="color:var(--muted);text-align:center;padding:20px">No words in this category.</div>';
    return;
  }
  list.forEach((r, idx)=>{
    const row=document.createElement('div');
    row.className='word-row'+(idx===0?' best':'');
    const rankClass = idx<3 ? 'word-rank top' : 'word-rank';
    const wcCount = r.wildcard_count || (r.wildcard_map ? Object.keys(r.wildcard_map).length : 0);
    const wcBadge = wcCount ? `<span style="margin-left:6px;background:rgba(212,169,106,0.14);color:#d4a96a;padding:2px 6px;border-radius:999px;font-size:10px;border:1px solid rgba(212,169,106,0.22)">★x${wcCount}</span>` : '';
    const wordHtml = formatWordWithWildcards(r.word, r.wildcard_map, r.path, tiles);
    row.innerHTML=`
      <div class="${rankClass}">#${idx+1}</div>
      <div class="word-main">
        <div class="word-text">${wordHtml} ${wcBadge} <small>${r.is_common? 'common' : 'SOWPODS'}</small></div>
        <div class="word-sub">
          <span class="word-pill score">${r.score} pts${wcCount ? ' <span style="color:#d4a96a">★0</span>' : ''}</span>
          <span class="word-pill">${r.length} letters</span>
          <span class="word-pill">${r.path.length} tiles</span>
          ${wcCount ? `<span class="word-pill" style="background:rgba(212,169,106,0.12);color:#d4a96a">blanks: ${Object.values(r.wildcard_map||{}).join(',') || wcCount+'★'}</span>` : ''}
        </div>
      </div>
      <div class="word-actions">
        <button class="btn btn-ghost btn-small" data-word="${r.word}">Copy</button>
      </div>
      <div class="word-thumb"><img src="${r.preview||''}" alt="${r.word} path" loading="lazy"></div>
    `;
    const img=row.querySelector('.word-thumb img');
    if(img){
      img.addEventListener('click', ()=>{
        heroWord.innerHTML = formatWordWithWildcards(r.word, r.wildcard_map, r.path, tiles);
        heroScore.textContent=`${r.score} pts` + (wcCount ? ` (★x${wcCount}=0)` : '');
        heroLen.textContent=`${r.length} letters`;
        heroPathLen.textContent=`${r.path.length} tiles`;
        if(heroWildcard){
          if(wcCount){
            heroWildcard.style.display='inline-block';
            heroWildcard.textContent=`★ ${wcCount} blank${wcCount>1?'s':''}`;
          } else heroWildcard.style.display='none';
        }
        heroImage.src=r.preview;
        heroDownload.href=r.preview;
        heroDownload.download=`boardsnap-${r.word}-${r.score}pts.png`;
        window.scrollTo({top: document.getElementById('heroCard').offsetTop - 80, behavior:'smooth'});
      });
    }
    const copyBtn=row.querySelector('button');
    if(copyBtn){
      copyBtn.addEventListener('click', ()=>{
        navigator.clipboard.writeText(r.word);
        copyBtn.textContent='Copied';
        setTimeout(()=>copyBtn.textContent='Copy',1200);
      });
    }
    el.appendChild(row);
  });
}

function renderAllList(all, tiles){
  const el=document.getElementById('allList');
  const meta=document.getElementById('allMeta');
  const filter = searchAll.value.trim().toUpperCase();
  let filtered = all;
  if(filter){
    // support * wildcard in search
    const re = new RegExp('^' + filter.replace(/\*/g, '.*') + '$');
    filtered = all.filter(r=> re.test(r.word) || r.word.includes(filter.replace(/\*/g,'')));
  }
  el.innerHTML='';
  const show = filtered.slice(0,100);
  show.forEach((r, idx)=>{
    const row=document.createElement('div');
    row.className='word-row';
    row.style.padding='8px 12px';
    const wcCount = r.wildcard_count || 0;
    const wordHtml = formatWordWithWildcards(r.word, r.wildcard_map, r.path, tiles);
    row.innerHTML=`
      <div class="word-rank" style="width:36px;height:36px;font-size:12px">${idx+1}</div>
      <div class="word-main">
        <div class="word-text" style="font-size:14px">${wordHtml} ${wcCount?`<span style="background:rgba(212,169,106,0.14);color:#d4a96a;padding:1px 4px;border-radius:999px;font-size:10px">★${wcCount}</span>`:''} <small style="color:${r.is_common?'#10b981':'#9aa3b8'}">${r.is_common?'common':'rare'}</small></div>
        <div class="word-sub"><span class="word-pill score">${r.score} pts${wcCount?' ★0':''}</span><span class="word-pill">${r.length} letters</span></div>
      </div>
      <div class="word-actions"><button class="btn btn-ghost btn-small">Copy</button></div>
      <div class="word-thumb" style="width:84px;height:52px"><img src="${r.preview||''}" alt="" loading="lazy" style="display:${r.preview?'block':'none'}"></div>
    `;
    const btn=row.querySelector('button');
    btn.addEventListener('click', ()=> {
      navigator.clipboard.writeText(r.word);
      btn.textContent='Copied'; setTimeout(()=>btn.textContent='Copy',1000);
    });
    el.appendChild(row);
  });
  meta.textContent = `Showing ${show.length} of ${filtered.length} words` + (filtered.length!==all.length? ` (filtered from ${all.length})` : ` • Total found: ${all.length}`) + (filtered.length>100? ' — refine search to see more' : '');
}

// tabs
document.querySelectorAll('.tab').forEach(tab=>{
  tab.addEventListener('click', ()=> switchTab(tab.dataset.tab));
});
function switchTab(name){
  document.querySelectorAll('.tab').forEach(t=> t.classList.toggle('active', t.dataset.tab===name));
  document.getElementById('list-score').classList.toggle('hidden', name!=='score');
  document.getElementById('list-length').classList.toggle('hidden', name!=='length');
  document.getElementById('list-all').classList.toggle('hidden', name!=='all');
}
searchAll.addEventListener('input', ()=>{
  if(currentResults){
    renderAllList(currentResults.results.all, currentResults.tiles);
  }
});
commonToggle.addEventListener('change', async ()=>{
  if(currentTiles.length>0){
    await solveWithTiles();
  }
});
commonToggleDetect.addEventListener('change', ()=>{
  commonToggle.checked = commonToggleDetect.checked;
});
wildcardToggle.addEventListener('change', async ()=>{
  if(currentResults || currentTiles.length>0){
    // if we are in results, re-solve from tiles; if in detect, just update flag
    if(!resultsSection.classList.contains('hidden')){
      await solveWithTiles();
    }
  }
});
wildcardToggleDetect.addEventListener('change', async ()=>{
  // keep in sync, but not auto re-solve until user clicks Solve — to avoid surprise
});
wildcardToggleHero.addEventListener('change', async ()=>{
  syncWildcardToggles(wildcardToggleHero.checked);
  if(!resultsSection.classList.contains('hidden')){
    await solveWithTiles();
  }
});

// Keyboard for modal
document.addEventListener('keydown', e=>{
  if(e.key==='Escape' && !editModal.classList.contains('hidden')){
    editModal.classList.add('hidden');
  }
  if(e.key==='Enter' && !editModal.classList.contains('hidden')){
    document.getElementById('editSave').click();
  }
});
