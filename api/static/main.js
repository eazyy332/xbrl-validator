/* Minimal client for live workflow */
const defaultInstance = '/Users/omarfrix/Desktop/untitled folder 12/extra_data/sample_instances_architecture_1.0/xBRL_XML/DUMMYLEI123456789012.CON_FR_DORA010000_DORA_2025-01-31_20240625161151000.xbrl';

const steps = [
  'Inputs','Taxonomy load (DTS)','Parse data','Core checks','Formula checks','Filing rules','DPM mapping','Results','Exports'
];

const state = {
  positions: {},
  nodes: {},
  messagesByStep: {},
  events: [],
  jobId: null,
  settings: {
    instance: defaultInstance,
    taxonomy: [],
    dpm: '/Users/omarfrix/Desktop/untitled folder 12/assets/dpm.sqlite',
    failOnWarnings: false,
    offline: false,
  },
  mappingSample: [],
};

function savePositions(){ localStorage.setItem('nodePos', JSON.stringify(state.positions)); }
function loadPositions(){ try{ state.positions = JSON.parse(localStorage.getItem('nodePos')||'{}') }catch{ state.positions = {} } }

function colorFor(status){
  switch(status){
    case 'not_started': return 'grey';
    case 'running': return 'blue';
    case 'succeeded': return 'green';
    case 'warning': return 'orange';
    case 'failed': return 'red';
    default: return 'grey';
  }
}

function createNode(name, x, y){
  const el = document.createElement('div');
  el.className = 'node grey';
  el.style.left = (x||20)+'px';
  el.style.top = (y||20)+'px';
  el.draggable = true;
  el.innerHTML = `<h4>${name}</h4><div class="status" data-status>-</div>`;
  el.addEventListener('dragstart', ev => {
    ev.dataTransfer.setData('text/plain', name);
    ev.dataTransfer.setDragImage(new Image(), 0, 0);
    el.classList.add('dragging');
  });
  el.addEventListener('dragend', ev => {
    el.classList.remove('dragging');
    const rect = el.getBoundingClientRect();
    const root = document.getElementById('flow').getBoundingClientRect();
    state.positions[name] = {x: rect.left - root.left + document.getElementById('flow').scrollLeft, y: rect.top - root.top + document.getElementById('flow').scrollTop};
    savePositions();
  });
  el.addEventListener('click', () => openPanel(name));
  return el;
}

function renderFlow(){
  const flow = document.getElementById('flow');
  flow.innerHTML = '';
  // Simple arrows SVG
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', '4000');
  svg.setAttribute('height', '1000');
  flow.appendChild(svg);
  steps.forEach((s, i) => {
    const pos = state.positions[s] || {x: 40 + i*170, y: 40};
    const node = createNode(s, pos.x, pos.y);
    node.style.position = 'absolute';
    flow.appendChild(node);
    state.nodes[s] = node;
  });
  // Draw arrows left->right based on default order
  for(let i=0;i<steps.length-1;i++){
    const a = state.nodes[steps[i]]; const b = state.nodes[steps[i+1]];
    if(!a||!b) continue;
    const ar = a.getBoundingClientRect();
    const br = b.getBoundingClientRect();
    const fr = flow.getBoundingClientRect();
    const x1 = ar.left - fr.left + ar.width; const y1 = ar.top - fr.top + ar.height/2;
    const x2 = br.left - fr.left; const y2 = br.top - fr.top + br.height/2;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    const dx = Math.max(40, (x2 - x1)/2);
    line.setAttribute('d', `M ${x1} ${y1} C ${x1+dx} ${y1}, ${x2-dx} ${y2}, ${x2} ${y2}`);
    line.setAttribute('class', 'arrow');
    svg.appendChild(line);
    // Highlight on hover
    a.addEventListener('mouseenter', ()=> line.classList.add('highlight'));
    a.addEventListener('mouseleave', ()=> line.classList.remove('highlight'));
    b.addEventListener('mouseenter', ()=> line.classList.add('highlight'));
    b.addEventListener('mouseleave', ()=> line.classList.remove('highlight'));
  }
}

function setStepStatus(step, status, message){
  const node = state.nodes[step];
  if(!node) return;
  node.className = 'node ' + colorFor(status);
  node.querySelector('[data-status]').textContent = message || status;
  if(message){
    state.messagesByStep[step] = state.messagesByStep[step] || [];
    state.messagesByStep[step].push({level: status==='warning'?'WARNING': (status==='failed'?'ERROR':'INFO'), message});
  }
}

function openPanel(step){
  const panel = document.getElementById('sidepanel');
  panel.classList.add('open');
  document.getElementById('panelTitle').textContent = step;
  const msgs = state.messagesByStep[step] || [];
  const box = document.getElementById('panelMessages');
  let extra = '';
  if(step === 'DPM mapping' && state.mappingSample.length){
    extra = '<div class="msg info"><strong>Sample mapped cells</strong><div style="font-family:ui-monospace,monospace;font-size:12px">' +
      state.mappingSample.map(r=>`${r.concept||''} → ${r.template||''} / ${r.table||''} / ${r.cell||''}`).join('<br/>') + '</div></div>';
  }
  box.innerHTML = extra + msgs.map(m => `<div class="msg ${m.level?.toLowerCase()||'info'}"><strong>${m.level||'INFO'}</strong> ${m.message||''}</div>`).join('');
}

function updateLogView(){
  const lv = document.getElementById('logView');
  const showInfo = document.getElementById('filterInfo').checked;
  const showWarn = document.getElementById('filterWarn').checked;
  const showErr = document.getElementById('filterErr').checked;
  const q = (document.getElementById('logSearch').value || '').toLowerCase();
  const lines = [];
  for(const entry of state.events){
    const sev = (entry.entry?.level || entry.level || '').toUpperCase();
    if(sev==='INFO' && !showInfo) continue;
    if(sev==='WARNING' && !showWarn) continue;
    if((sev==='ERROR'||sev==='FATAL') && !showErr) continue;
    const msg = entry.entry?.message || entry.message || JSON.stringify(entry);
    const code = entry.entry?.code || entry.code || '';
    let text = `[${sev}] ${code?code+': ':''}${msg}`;
    if(q && !text.toLowerCase().includes(q)) continue;
    lines.push(text);
  }
  lv.textContent = lines.join('\n') + (lines.length?'\n':'');
  lv.scrollTop = lv.scrollHeight;
}

function appendLog(entry){
  state.events.push(entry);
  updateLogView();
}

async function startRun(){
  document.getElementById('startBtn').disabled = true;
  document.getElementById('cancelBtn').disabled = false;
  document.getElementById('rerunBtn').disabled = true;

  // Reset
  steps.forEach(s => setStepStatus(s, 'not_started'));
  state.messagesByStep = {};
  document.getElementById('logView').textContent = '';
  document.getElementById('summary').innerHTML = '';

  const payload = {
    instance_file: state.settings.instance,
    taxonomy_packages: state.settings.taxonomy,
    dpm_sqlite: state.settings.dpm,
    dpm_schema: 'dpm35_10',
    fail_on_warnings: state.settings.failOnWarnings,
    offline: state.settings.offline,
  };
  const r = await fetch('/workflow/run', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  const {job_id} = await r.json();
  state.jobId = job_id;

  const es = new EventSource(`/workflow/${job_id}/events`);
  es.addEventListener('message', e => {
    try {
      const ev = JSON.parse(e.data);
      if(ev.step && ev.status){
        setStepStatus(ev.step, ev.status, ev.message);
        if(ev.status === 'warning' || ev.status === 'failed'){
          // Summarize current visible messages into a short explanation
          summarizeVisible().catch(()=>{});
        }
      }
      if(ev.event === 'log'){ appendLog(ev); }
      if(ev.event === 'mapping'){ state.mappingSample = ev.rows || []; }
      if(ev.event === 'counters'){
        document.getElementById('panelCounters').innerHTML = `<div class="kv"><span>Facts</span><strong>${ev.facts||0}</strong></div><div class="kv"><span>Contexts</span><strong>${ev.contexts||0}</strong></div><div class="kv"><span>Units</span><strong>${ev.units||0}</strong></div>`;
      }
      if(ev.summary){
        const s = ev.summary;
        document.getElementById('summary').innerHTML = [
          ['Facts', s.facts??'-'], ['Contexts', s.contexts??'-'], ['Units', s.units??'-'], ['Errors', s.errors||0], ['Warnings', s.warnings||0]
        ].map(([k,v])=>`<span class="chip"><strong>${k}</strong> ${v}</span>`).join('');
      }
      if(ev.event === 'exports' && ev.dir){
        const dir = ev.dir.replace(/^.*\/exports\//,'');
        document.getElementById('downloadCsv').href = `/exports/${dir}/validation_messages.csv`;
        document.getElementById('downloadCsv').download = `validation_messages.csv`;
        document.getElementById('downloadJson').href = `/exports/${dir}/results_by_file.json`;
        document.getElementById('downloadJson').download = `results_by_file.json`;
      }
    } catch {}
  });
  es.addEventListener('ping', ()=>{});
  es.onerror = ()=>{ es.close(); document.getElementById('rerunBtn').disabled = false; document.getElementById('cancelBtn').disabled = true; document.getElementById('startBtn').disabled = false; };
}

function openSettings(){
  const d = document.getElementById('settingsDialog');
  document.getElementById('instancePath').value = state.settings.instance;
  document.getElementById('taxPackages').value = (state.settings.taxonomy||[]).join('\n');
  document.getElementById('dpmPath').value = state.settings.dpm;
  document.getElementById('failOnWarnings').checked = !!state.settings.failOnWarnings;
  document.getElementById('offlineMode').checked = !!state.settings.offline;
  d.showModal();
}

function bind(){
  loadPositions();
  renderFlow();
  const flow = document.getElementById('flow');
  flow.addEventListener('dragover', ev => ev.preventDefault());
  document.getElementById('startBtn').onclick = startRun;
  document.getElementById('rerunBtn').onclick = startRun;
  document.getElementById('cancelBtn').onclick = async ()=>{ if(state.jobId){ await fetch(`/workflow/${state.jobId}/cancel`, {method:'POST'}); } };
  document.getElementById('settingsBtn').onclick = openSettings;
  document.getElementById('closePanel').onclick = ()=> document.getElementById('sidepanel').classList.remove('open');
  document.getElementById('settingsForm').onsubmit = (e)=>{
    e.preventDefault();
    state.settings.instance = document.getElementById('instancePath').value;
    state.settings.taxonomy = document.getElementById('taxPackages').value.split('\n').map(s=>s.trim()).filter(Boolean);
    state.settings.dpm = document.getElementById('dpmPath').value;
    state.settings.failOnWarnings = document.getElementById('failOnWarnings').checked;
    state.settings.offline = document.getElementById('offlineMode').checked;
    document.getElementById('settingsDialog').close();
  };
  document.getElementById('cancelSettings').onclick = ()=> document.getElementById('settingsDialog').close();
  document.getElementById('filterInfo').onchange = updateLogView;
  document.getElementById('filterWarn').onchange = updateLogView;
  document.getElementById('filterErr').onchange = updateLogView;
  document.getElementById('logSearch').oninput = updateLogView;
  document.getElementById('summarizeBtn').onclick = summarizeVisible;

  // Load/persist API key locally if user opts in
  const apiInput = document.getElementById('apiKey');
  const remember = document.getElementById('rememberKey');
  try{
    const saved = localStorage.getItem('openai_api_key') || '';
    if(saved){ apiInput.value = saved; remember.checked = true; }
  }catch{}
  apiInput.addEventListener('change', ()=>{
    try{
      if(remember.checked){ localStorage.setItem('openai_api_key', apiInput.value||''); }
      else { localStorage.removeItem('openai_api_key'); }
    }catch{}
  });
  remember.addEventListener('change', ()=>{
    try{
      if(remember.checked){ localStorage.setItem('openai_api_key', apiInput.value||''); }
      else { localStorage.removeItem('openai_api_key'); }
    }catch{}
  });

  // Prefill default paths
  state.settings.instance = defaultInstance;
}

window.addEventListener('DOMContentLoaded', bind);

// Fetch version info for header
fetch('/about').then(r=>r.json()).then(info=>{
  const ver = document.getElementById('ver');
  if(!ver) return;
  const parts = [];
  if(info?.apiVersion) parts.push('API '+info.apiVersion);
  if(info?.python) parts.push('Py '+info.python);
  if(info?.arelleMeta?.version) parts.push('Arelle '+info.arelleMeta.version);
  ver.textContent = parts.join(' · ');
}).catch(()=>{});

function toast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(()=> t.classList.remove('show'), 4000);
}

async function summarizeVisible(){
  try{
    const showInfo = document.getElementById('filterInfo').checked;
    const showWarn = document.getElementById('filterWarn').checked;
    const showErr = document.getElementById('filterErr').checked;
    const q = (document.getElementById('logSearch').value || '').toLowerCase();
    const texts = [];
    for(const entry of state.events){
      const sev = (entry.entry?.level || entry.level || '').toUpperCase();
      if(sev==='INFO' && !showInfo) continue;
      if(sev==='WARNING' && !showWarn) continue;
      if((sev==='ERROR'||sev==='FATAL') && !showErr) continue;
      const msg = entry.entry?.message || entry.message || '';
      const code = entry.entry?.code || entry.code || '';
      const line = `[${sev}] ${code?code+': ':''}${msg}`;
      if(q && !line.toLowerCase().includes(q)) continue;
      texts.push(line);
      if(texts.length >= 20) break;
    }
    if(!texts.length){ toast('No messages to summarize.'); return; }
    const api_key = document.getElementById('apiKey')?.value || '';
    const r = await fetch('/summarize', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({texts, api_key})});
    const data = await r.json();
    if(!r.ok){ throw new Error(data?.detail || 'Summarization failed'); }
    const s = data.summary || '';
    state.messagesByStep['Results'] = state.messagesByStep['Results'] || [];
    state.messagesByStep['Results'].push({level:'INFO', message: s});
    openPanel('Results');
  }catch(e){ toast(String(e)); }
}


