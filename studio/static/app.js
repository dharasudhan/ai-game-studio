/* AI Game Studio dashboard - plain JS, no framework, no build step. Every POST carries X-Studio: 1 (CSRF guard). */
const H = {'X-Studio': '1', 'Content-Type': 'application/json'};
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const ago = t => { if (!t) return '-'; const d = Date.now() / 1000 - t; if (d < 0) return 'in ' + dur(-d);
  return d < 60 ? Math.round(d) + 's ago' : d < 3600 ? Math.round(d / 60) + 'm ago' : d < 86400 ? Math.round(d / 3600) + 'h ago' : Math.round(d / 86400) + 'd ago'; };
const dur = s => s < 60 ? Math.round(s) + 's' : s < 3600 ? Math.round(s / 60) + 'm' : (s / 3600).toFixed(1) + 'h';
const human = s => String(s ?? '').replace(/_/g, ' ');
const stars = n => n ? '<span class=stars>' + '★'.repeat(n) + '<span style="opacity:.25">' + '★'.repeat(5 - n) + '</span></span>' : '';
const COLORS = {producer: '#8b7bff', designer: '#ff8fb1', engineer: '#4cc2ff', artist: '#ffb86b', qa: '#3ccf8e', marketing: '#f5d04a',
  analyst: '#9ad0ff', support: '#7ef0d0', bugfixer: '#ff6b78'};
const avatar = n => `<div class="avatar" style="background:${COLORS[n] || '#999'}">${esc((n || '?').slice(0, 2).toUpperCase())}</div>`;
const state = s => `<span class="state st-${esc(s)}"><span class="dot"></span>${esc(s)}</span>`;
const GATES = {1: 'New game concept', 2: 'Milestone plan', 3: 'Code/build change -> main', 4: 'Money spend', 5: 'Store release', 6: 'Anything public'};
const TITLES = {status: ['Status', 'Live agents, queue, engine backoff and what waits for you'], approvals: ['Approval Desk', 'Gates 1-6: nothing passes without your explicit yes'],
  board: ['Games', 'Games, milestones and the ticket board'], feedback: ['Feedback inbox', 'Player reviews, emails and in-game reports, triaged by Customer Support'],
  agents: ['Agents', 'Enable, pause, run now, engines, prompts and feedback memory'], docs: ['Docs & ledger', 'Agent documents, spend ledger, jobs and activity'],
  settings: ['Settings', 'Engines, schedule, limits, feedback sources, notifications']};

let ST = null, tab = 'status', busy = false, fbFilter = {status: '', category: '', severity: '', source: '', bug: '', q: '', game_id: ''};
const sig = {};

async function api(path, opt = {}) {
  const r = await fetch(path, {headers: H, ...opt});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { toast(j.detail ? (typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)) : r.statusText, true); throw j; }
  return j;
}
const post = (p, body) => api(p, {method: 'POST', body: JSON.stringify(body || {})});
function toast(msg, err) { const d = document.createElement('div'); d.className = err ? 'err' : ''; d.textContent = msg; $('toast').appendChild(d); setTimeout(() => d.remove(), 4200); }
function modal(h) { $('modalBody').innerHTML = h; $('modal').classList.add('on'); }
function closeModal() { $('modal').classList.remove('on'); }
$('modal').onclick = e => { if (e.target === $('modal')) closeModal(); };
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
const gameOpts = (sel, withAll, allLabel) => (withAll ? `<option value="">${allLabel || 'All games'}</option>` : '') +
  (ST?.games || []).map(g => `<option value="${g.id}" ${String(sel) === String(g.id) ? 'selected' : ''}>${esc(g.title)}</option>`).join('');
const gname = id => ((ST?.games || []).find(g => g.id === id) || {}).title || '';

/* ------------------------------------------------------------------ header + router */
function renderHeader() {
  const s = ST, q = s.queue || {};
  const p = $('qpill');
  if (s.paused) { p.className = 'pill bad'; p.textContent = 'Paused: ' + (s.pause_reason || '').slice(0, 70); }
  else if (s.hold_reason) { p.className = 'pill warn'; p.textContent = 'Holding: ' + s.hold_reason; }
  else { p.className = 'pill ok'; p.innerHTML = `<span class=dot></span> ${q.running || 0} running · ${q.queued || 0} queued` + (q.failed ? ` · ${q.failed} failed` : ''); }
  p.title = p.textContent;
  const narrow = window.innerWidth < 860;
  $('pauseBtn').textContent = s.paused ? (narrow ? 'Resume' : 'Resume queue') : (narrow ? 'Pause' : 'Pause queue');
  $('pauseBtn').className = 'sm ' + (s.paused ? 'ok' : '');
  $('cApprovals').textContent = s.approvals_total || '';
  $('cFeedback').textContent = s.feedback_new || '';
}
$('pauseBtn').onclick = async () => { await post(ST.paused ? '/api/resume' : '/api/pause'); refresh(true); };

function route() {
  tab = (location.hash || '#status').slice(1).split('?')[0];
  if (!TITLES[tab]) tab = 'status';
  document.querySelectorAll('.nav a').forEach(a => a.classList.toggle('on', a.dataset.tab === tab));
  $('title').textContent = TITLES[tab][0]; $('subtitle').textContent = TITLES[tab][1];
  Object.keys(sig).forEach(k => delete sig[k]);
  $('view').innerHTML = '<div class="empty">Loading...</div>';
  refresh(true);
}
window.addEventListener('hashchange', route);

async function refresh(force) {
  if (busy && !force) return;
  busy = true;
  try {
    ST = await (await fetch('/api/status')).json();
    renderHeader();
    await VIEWS[tab](force);
  } catch (e) { $('qpill').className = 'pill bad'; $('qpill').textContent = 'server offline'; }
  finally { busy = false; }
}
const editing = () => { const a = document.activeElement; return a && ['INPUT', 'TEXTAREA', 'SELECT'].includes(a.tagName) && $('view').contains(a); };

/* ------------------------------------------------------------------ status */
async function vStatus() {
  const s = ST, q = s.queue || {}, u = s.usage_today || {};
  const eb = Object.entries(s.engine_backoff || {});
  const gates = Object.entries(s.approvals_waiting || {}).map(([g, n]) => `<span class="pill acc">G${g} · ${n}</span>`).join(' ') || '<span class=faint>none</span>';
  const caps = (s.caps.daily_run_cap && s.caps.daily_run_cap !== '0' ? ` / ${s.caps.daily_run_cap}` : '');
  const html = `
  <div class="grid g4">
    <div class="card kpi"><div class=k>Queue</div><div class=v>${q.queued || 0}<span class=faint style="font-size:14px"> waiting</span></div>
      <div class=d>${q.running || 0} running · ${q.failed || 0} failed · concurrency ${s.concurrency}</div></div>
    <div class="card kpi"><div class=k>Waiting for you</div><div class=v><a href="#approvals" style="color:inherit">${s.approvals_total || 0}</a></div><div class=d>${gates}</div></div>
    <div class="card kpi"><div class=k>Engine</div><div class=v style="font-size:20px">${esc(s.engine)}${s.chore_engine ? ` <span class=faint style="font-size:13px">+ ${esc(s.chore_engine)} chores</span>` : ''}</div>
      <div class=d>${eb.length ? eb.map(([e, b]) => `<span class="pill warn">${esc(e)} backoff ${dur(b.remaining)}</span>`).join(' ') : '<span class="pill ok">no rate-limit backoff</span>'}</div></div>
    <div class="card kpi"><div class=k>Today</div><div class=v>${u.runs || 0}<span class=faint style="font-size:14px"> runs${caps}</span></div>
      <div class=d>${(u.tokens || 0).toLocaleString()} tokens · Godot ${s.godot ? '<span style="color:var(--ok)">found</span>' : '<span style="color:var(--bad)">missing</span>'}</div></div>
  </div>
  ${s.paused || s.hold_reason ? `<div class="card" style="margin-top:14px;border-color:rgba(245,183,72,.35)"><b>${s.paused ? 'Queue paused' : 'Holding new runs'}:</b> ${esc(s.paused ? s.pause_reason : s.hold_reason)}
     ${s.paused ? '<button class="sm ok" style="margin-left:10px" onclick="post(\'/api/resume\').then(()=>refresh(true))">Resume</button>' : ''}</div>` : ''}
  ${eb.length ? `<div class="card" style="margin-top:14px"><h2>Engine rate limits</h2>${eb.map(([e, b]) => `<div class=row><span class="pill warn">${esc(e)}</span><span class=muted>retry in ${dur(b.remaining)} - ${esc(b.reason)}</span></div>`).join('')}</div>` : ''}
  <div class="card" style="margin-top:14px"><h2>Agents <span class=grow></span><span class=faint style="text-transform:none;letter-spacing:0">work hours ${esc(s.work_hours || 'always')} · quiet ${esc(s.quiet_hours || 'off')} · standup ${esc(s.standup_time || '-')}</span></h2>
    ${s.agents.map(a => `<div class="ag-row">
      <div class=who>${avatar(a.name)}<div><b>${esc(a.label)}</b><div class=faint>${esc(a.engine || s.engine)}${a.model ? ' · ' + esc(a.model) : ''}</div></div></div>
      <div>${state(a.state)}${a.backoff_jobs ? `<div class=faint>${a.backoff_jobs} in backoff</div>` : ''}</div>
      <div class=cur>${a.current ? `<div><b>${esc(a.current.kind)}</b>${a.current.ticket_id ? ' T#' + a.current.ticket_id : ''}</div><div class=faint>${esc(a.current.game || 'studio')} · started ${ago(a.current.since)}</div>`
        : a.queue_length ? `<div class=muted>${a.queue_length} queued${a.next_due && a.next_due > s.now ? ' · next ' + ago(a.next_due) : ''}</div>` : '<span class=faint>-</span>'}</div>
      <div class=last>${a.last_result ? `<div class=sum>${a.last_result.status === 'ok' ? '' : `<span class="pill bad">${esc(a.last_result.status)}</span> `}${esc(a.last_result.summary || a.last_result.task)}</div>
        <div class=faint>${ago(a.last_run_at)} · <a onclick="showRun(${a.last_result.run_id})">run #${a.last_result.run_id}</a></div>` : '<span class=faint>no runs yet</span>'}
        ${a.state === 'error' && a.last_error ? `<div class="faint lvl-error">${esc(a.last_error.split('\n')[0].slice(0, 140))}</div>` : ''}</div>
      <div class=q style="text-align:right"><a href="#agents" class=faint>manage</a></div></div>`).join('')}
  </div>
  <div class="grid g2" style="margin-top:14px">
    <div class=card><h2>Recent runs</h2><div class=tbl id="stRuns"></div></div>
    <div class=card><h2>Activity</h2><div class=tbl id="stEvents"></div></div>
  </div>`;
  const k = JSON.stringify([s.agents.map(a => [a.state, a.current, a.queue_length, a.last_result, a.backoff_jobs]), q, s.approvals_waiting, s.engine_backoff && Object.keys(s.engine_backoff), s.paused, s.hold_reason, u.runs]);
  if (sig.status !== k) { sig.status = k; $('view').innerHTML = html; }
  const full = await (await fetch('/api/state')).json();
  $('stRuns').innerHTML = full.runs.length ? `<table><tr><th>#</th><th>agent / task</th><th class=hide-m>engine</th><th>status</th><th>when</th></tr>${full.runs.slice(0, 12).map(r =>
    `<tr><td><a onclick="showRun(${r.id})">${r.id}</a></td><td>${esc(r.agent)} / ${esc(r.task)}</td><td class="hide-m faint">${esc(r.engine)} ${esc(r.model || '')}</td>
     <td class="${r.status === 'ok' ? '' : 'lvl-error'}">${esc(r.status)}</td><td class=faint>${ago(r.started_at)}</td></tr>`).join('')}</table>` : '<div class=empty>No runs yet.</div>';
  $('stEvents').innerHTML = full.events.length ? `<table>${full.events.slice(0, 14).map(e => `<tr class="lvl-${e.level}"><td class=faint style="white-space:nowrap">${ago(e.created_at)}</td><td>${esc(e.agent || '')}</td><td>${esc(e.message.slice(0, 220))}</td></tr>`).join('')}</table>` : '<div class=empty>Quiet so far.</div>';
}

/* ------------------------------------------------------------------ approvals */
function diffHtml(d) { return esc(d).split('\n').map(l => l.startsWith('+') && !l.startsWith('+++') ? `<span class=add>${l}</span>` : l.startsWith('-') && !l.startsWith('---') ? `<span class=del>${l}</span>` : l.startsWith('@@') ? `<span class=hunk>${l}</span>` : l).join('\n'); }
function payloadHtml(a, S) {
  const p = a.payload || {};
  if (a.kind === 'concept') return `<b>${esc(p.title)}</b> <span class=muted>${esc(p.logline)}</span><pre>${esc(p.markdown)}</pre>`;
  if (a.kind === 'plan') return `<pre>${esc(a.summary)}</pre>` + (p.source === 'analyst' ? '<div class=muted>Proposed by the Analyst from your data.</div>' : '');
  if (a.kind === 'change') return `<div class=row>${p.kind === 'bug' ? '<span class="pill bad">player bug fix</span>' : ''}<span class=muted>${esc(a.summary)} · commit <span class=mono>${esc((p.sha || '').slice(0, 10))}</span></span>
      ${p.qa_passed ? '<span class="pill ok">QA passed</span>' : '<span class="pill bad">QA FAILED (loops exhausted)</span>'}</div>
     ${p.kind === 'bug' ? `<div class=muted style="margin-top:6px">Root cause: ${esc(p.root_cause || '-')} · regression test: <span class=mono>${esc(p.regression_test || 'none')}</span> · fixes ${(p.feedback_items || []).length} player report(s)</div>` : ''}
     <details><summary>QA report</summary><pre>${esc(p.qa_markdown)}</pre></details><details open><summary>Diff (${(p.files || []).length} files)</summary><pre>${diffHtml(p.diff || '')}</pre></details>`;
  if (a.kind === 'spend') { const b = S.budget; return `<div><b>${esc(p.amount)} ${esc(p.currency || b.currency)}</b> at ${esc(p.vendor)}: ${esc(p.reason)}</div><div class=muted>Committed this month: ${b.committed_this_month} / budget ${b.monthly || 'not set'} ${esc(b.currency)}. Approving only records it; you make the purchase.</div>`; }
  if (a.kind === 'release') return `<div class=muted>Approving marks it releasable; you upload in Play Console yourself.</div><details open><summary>Store listing</summary><pre>${esc(p.store_listing)}</pre></details><details><summary>Build + QA</summary><pre>${esc(p.build)}\n\n${esc(p.qa)}</pre></details>`;
  if (a.kind === 'public') return `<div class=muted>Channel: ${esc(p.channel)} - approving does not post; you copy it.</div><pre>${esc(p.content)}</pre>`;
  if (a.kind === 'reply') return `<div class=row><span class="pill acc">${esc(p.channel)}</span>${stars(p.rating)}<span class="tag c-${esc(p.category)}">${esc(p.category || '')}</span>${p.followup ? '<span class="pill ok">fixed follow-up</span>' : ''}
       ${p.review_link ? `<a href="${esc(p.review_link)}" target=_blank rel=noopener class=faint>open review</a>` : ''}</div>
     <div class=quote>${esc(p.player_text)}</div>
     <label class=f>Reply draft (edit before approving; approving does not post - you paste it yourself)</label>
     <textarea id="rep${a.id}" data-item="${p.item_id}">${esc(p.content)}</textarea>
     <div class=row style="margin-top:6px"><button class=sm onclick="saveReply(${a.id})">Save edit</button><button class=sm onclick="copyText('rep${a.id}')">Copy</button></div>`;
  return `<pre>${esc(JSON.stringify(p, null, 1))}</pre>`;
}
async function vApprovals() {
  const S = await (await fetch('/api/state')).json();
  const k = JSON.stringify(S.approvals.map(a => a.id));
  if (sig.ap === k && editing()) return;
  if (sig.ap === k) return;
  sig.ap = k;
  const byGate = [1, 2, 3, 4, 5, 6].map(g => [g, S.approvals.filter(a => a.gate === g).length]);
  $('view').innerHTML = `<div class="chips" style="margin-bottom:14px">${byGate.map(([g, n]) => `<span class="chip ${n ? 'on' : ''}">Gate ${g} · ${GATES[g]} · ${n}</span>`).join('')}</div>
   ${S.approvals.length ? S.approvals.map(a => `<div class="card appr">
     <div class=row><span class=gate>Gate ${a.gate} · ${esc(GATES[a.gate])}</span><span class=grow></span><span class=faint>${esc(gname(a.game_id) || 'studio')} · by ${esc(a.agent)} · ${ago(a.created_at)}</span></div>
     <div class=title>${esc(a.title)}</div>${payloadHtml(a, S)}
     <textarea id="note${a.id}" placeholder="Rejection note (required to reject; it goes back to the agent and into its feedback memory)" style="margin-top:10px;min-height:48px"></textarea>
     <div class=row style="margin-top:8px"><button class=ok onclick="decide(${a.id},'approve')">Approve</button><button class=bad onclick="decide(${a.id},'reject')">Reject with note</button></div></div>`).join('')
     : '<div class=empty>Nothing waiting for you. Enjoy the quiet.</div>'}
   <div class=card style="margin-top:14px"><h2>Recently decided</h2><div class=tbl><table>${S.decided.map(d => `<tr><td>G${d.gate}</td><td>${esc(d.title)}</td><td><span class="pill ${d.status === 'approved' ? 'ok' : 'bad'}">${esc(d.status)}</span></td><td class=muted>${esc(d.note || '')}</td><td class=faint>${ago(d.decided_at)}</td></tr>`).join('') || '<tr><td class=faint>none yet</td></tr>'}</table></div></div>`;
}
async function decide(id, what) {
  const note = $('note' + id).value.trim();
  if (what === 'reject' && !note) return toast('Write a note: the agent uses it to redo the work.', true);
  const r = $('rep' + id); if (r && what === 'approve') await post(`/api/feedback/${r.dataset.item}/draft`, {text: r.value});
  await post(`/api/approvals/${id}/${what}`, {note}); toast(what === 'approve' ? 'Approved' : 'Sent back with your note'); sig.ap = null; refresh(true);
}
async function saveReply(aid) { const r = $('rep' + aid); await post(`/api/feedback/${r.dataset.item}/draft`, {text: r.value}); toast('Draft saved'); }
function copyText(id) { const el = $(id); navigator.clipboard?.writeText(el.value || el.textContent).then(() => toast('Copied')); }

/* ------------------------------------------------------------------ games + board */
let boardGame = '';
async function vBoard() {
  const S = await (await fetch('/api/state' + (boardGame ? '?game_id=' + boardGame : ''))).json();
  const k = JSON.stringify([S.games, S.tickets.map(t => [t.id, t.status]), S.milestones.map(m => m.status)]);
  if (sig.board === k || editing()) return; sig.board = k;
  const cols = [['To do', ['todo', 'queued']], ['In progress', ['in_progress', 'qa', 'changes_requested']], ['Needs you', ['awaiting_approval', 'needs_attention']], ['Done', ['done']]];
  const ms = Object.fromEntries(S.milestones.map(m => [m.id, m]));
  $('view').innerHTML = `<div class="grid g2">
   <div class=card><h2>Start a new game</h2><input id=ngTitle placeholder="Working title (optional)">
     <textarea id=ngGoal placeholder="Goal, e.g. 'A cozy one-thumb puzzle game for Android, 3-minute sessions, ad-free premium'" style="margin-top:8px"></textarea>
     <div class=row style="margin-top:8px"><button class=primary onclick="newGame()">Designer pitches a concept (Gate 1)</button></div></div>
   <div class=card><h2>Games</h2>${S.games.map(g => `<div class=row style="padding:8px 0;border-bottom:1px solid var(--line)">
      <div class=grow><b>${esc(g.title)}</b> <span class=pill>${esc(human(g.status))}</span>${g.version ? ` <span class="pill acc">v${esc(g.version)}</span>` : ''}
      <div class=faint>${g.repo_path ? 'games/' + esc(g.slug) + (g.package ? ' · ' + esc(g.package) : '') : 'no repo yet (after Gate 1)'}</div></div>
      <button class=sm onclick="gameMenu(${g.id})">Actions</button></div>`).join('') || '<div class=empty>No games yet.</div>'}</div></div>
   <div class=card style="margin-top:14px"><h2>Board <span class=grow></span><select id=boardSel onchange="boardGame=this.value;sig.board=null;refresh(true)">${gameOpts(boardGame, true)}</select></h2>
     <div class=board>${cols.map(([n, sts]) => { const ts = S.tickets.filter(t => sts.includes(t.status)); return `<div class=col><h3>${n}<span>${ts.length}</span></h3>${ts.map(t => `<div class=t>
       <div class=row><span class=tag style="background:${COLORS[t.agent]}22;color:${COLORS[t.agent]}">${esc(t.agent)}</span>${t.kind === 'bug' ? `<span class="tag c-bug">bug ${esc(t.severity || '')}</span>` : ''}</div>
       <div style="margin-top:5px"><b>T#${t.id}</b> ${esc(t.title)}</div><div class=faint>${esc(human(t.status))} · ${esc((ms[t.milestone_id] || {}).title || (t.kind === 'bug' ? 'from player reports' : ''))}${S.games.length > 1 && !boardGame ? ' · ' + esc(gname(t.game_id)) : ''}</div></div>`).join('')}</div>`; }).join('')}</div></div>`;
}
async function newGame() { const goal = $('ngGoal').value.trim(); if (!goal) return toast('Describe the game goal', true);
  await post('/api/games', {goal, title: $('ngTitle').value}); toast('Designer is on it'); sig.board = null; refresh(true); }
function gameMenu(id) {
  const g = ST.games.find(x => x.id === id) || {};
  modal(`<h3>${esc(g.title)}</h3><div class=sp></div>
   <div class=field><label class=f>Current version (used for "fixed in vX" replies)</label><div class=row><input id=gVer value="${esc(g.version || '')}" placeholder="1.0.3" style="max-width:160px"><button onclick="setVersion(${id})">Save</button></div></div>
   <div class=row><button onclick="post('/api/games/${id}/standup').then(()=>{toast('Standup queued');closeModal()})">Standup now</button>
   <button onclick="post('/api/games/${id}/fixed_replies',{version:$('gVer').value}).then(()=>{toast('Support drafts follow-ups');closeModal()})">Draft "fixed in vX" replies</button></div>
   <div class=sp></div><label class=f>Analyst inbox (reviews/crash/revenue exports)</label><input type=file onchange="upload(${id},this)">
   <div class=row style="margin-top:14px"><span class=grow></span><button class=ghost onclick="closeModal()">Close</button></div>`);
}
async function setVersion(id) { await post(`/api/games/${id}/version`, {version: $('gVer').value}); toast('Version saved'); sig.board = null; refresh(true); }
async function upload(id, el) { const f = el.files[0]; if (!f) return; const fd = new FormData(); fd.append('file', f);
  const r = await fetch(`/api/games/${id}/inbox`, {method: 'POST', headers: {'X-Studio': '1'}, body: fd}); toast(r.ok ? 'Analyst queued' : 'Upload failed', !r.ok); closeModal(); }

/* ------------------------------------------------------------------ feedback */
async function vFeedback(force) {
  const qs = new URLSearchParams(Object.entries(fbFilter).filter(([k, v]) => v !== '')).toString();
  const F = await (await fetch('/api/feedback' + (qs ? '?' + qs : ''))).json();
  const k = JSON.stringify([qs, F.items.map(i => [i.id, i.status, i.category, i.reply_draft, i.bug_ticket_id, i.ticket_status, i.fixed_sha, i.game_id]), F.groups.map(g => [g.id, g.count])]);
  if (!force && (sig.fb === k || editing())) return; sig.fb = k;
  const sel = (key, opts, label) => `<select onchange="fbFilter.${key}=this.value;refresh(true)"><option value="">${label}</option>${opts.map(o => `<option ${fbFilter[key] === o ? 'selected' : ''}>${o}</option>`).join('')}</select>`;
  const c = F.counts;
  $('view').innerHTML = `
  <div class="grid g4">
    <div class="card kpi"><div class=k>All feedback</div><div class=v>${c.total}</div><div class=d>${Object.entries(c.source).map(([s, n]) => `${esc(s)} ${n}`).join(' · ') || 'no sources yet'}</div></div>
    <div class="card kpi"><div class=k>Bugs & crashes</div><div class=v>${(c.category.bug || 0) + (c.category.crash || 0)}</div><div class=d>${c.category.crash || 0} crash · ${c.category.bug || 0} bug</div></div>
    <div class="card kpi"><div class=k>Replies at Gate 6</div><div class=v>${c.status.awaiting_approval || 0}</div><div class=d>${c.status.reply_approved || 0} approved, not posted yet</div></div>
    <div class="card kpi"><div class=k>Sources</div><div class=v style="font-size:15px;margin-top:8px">Inbox ${F.imap.enabled ? '+ IMAP' : ''}</div><div class=d>last scan ${ago(F.last_scan)} ${F.imap.enabled && !F.imap.configured ? '<span class="pill bad">IMAP creds missing in .env</span>' : ''}</div></div>
  </div>
  <div class=card style="margin-top:14px">
    <div class=filters>
      <input type=search placeholder="Search text, summary, author" value="${esc(fbFilter.q)}" onchange="fbFilter.q=this.value;refresh(true)">
      <select onchange="fbFilter.game_id=this.value;refresh(true)"><option value="">All games</option><option value="0" ${fbFilter.game_id === '0' ? 'selected' : ''}>Not linked</option>${gameOpts(fbFilter.game_id, false)}</select>
      ${sel('status', F.statuses, 'Any status')}${sel('category', [...F.categories, 'untriaged'], 'Any category')}${sel('severity', F.severities, 'Any severity')}${sel('source', F.sources, 'Any source')}
      <select onchange="fbFilter.bug=this.value;refresh(true)"><option value="">Bug link: any</option><option value=linked ${fbFilter.bug === 'linked' ? 'selected' : ''}>linked, not fixed</option><option value=fixed ${fbFilter.bug === 'fixed' ? 'selected' : ''}>fix merged</option></select>
      <span class=grow></span>
      <label class="btn sm" style="display:inline-block">Upload file<input type=file accept=".csv,.json,.txt" style="display:none" onchange="fbUpload(this)"></label>
      <button class="sm primary" onclick="post('/api/feedback/scan').then(()=>toast('Scan queued'))">Scan sources now</button>
    </div>
    <div class=faint style="margin-top:8px">Drop Play Console review CSVs, .txt, .json or .csv into <span class=mono>${esc(F.inbox_dir)}</span> (sub-folder = game slug). Replies are drafts; each needs Gate 6 and you post it yourself.</div>
  </div>
  <div class="fb-layout" style="margin-top:14px">
    <div id=fbList>${F.items.length ? F.items.map(fbCard).join('') : '<div class=empty>No feedback matches. Drop a file in the inbox or upload one.</div>'}</div>
    <div class=card><h2>Top issues (grouped)</h2>${F.groups.length ? F.groups.map(g => `<div class=grp><span class=n>${g.count}</span><div class=grow><div><span class="tag c-${esc(g.category)}">${esc(human(g.category))}</span> <span class="sev-${esc(g.severity)}">${esc(g.severity || '')}</span></div>
      <div>${esc(g.title)}</div><div class=faint>${esc(g.game_title || 'not linked')}${g.bug_ticket_id > 0 ? ` · bug T#${g.bug_ticket_id} ${esc(human(g.ticket_status))}` : g.bug_ticket_id === 0 ? ' · Bug Fixer intake queued' : ''}</div></div></div>`).join('') : '<div class=faint>Groups appear after triage.</div>'}</div>
  </div>`;
}
function fbCard(i) {
  const bug = i.bug_ticket_id ? `<span class="pill ${i.fixed_sha ? 'ok' : 'bad'}">${i.fixed_sha ? (i.fixed_in_version ? 'fixed in v' + esc(i.fixed_in_version) : 'fix merged') : 'bug T#' + i.bug_ticket_id + ' ' + esc(human(i.ticket_status))}</span>` : '';
  const replyable = i.reply_draft && !['replied', 'closed', 'ignored'].includes(i.status);
  return `<div class="card fb">
   <div class=meta>${stars(i.rating)}<span class=tag>${esc(i.source)}</span>${i.category ? `<span class="tag c-${esc(i.category)}">${esc(human(i.category))}</span>` : '<span class="pill warn">untriaged</span>'}
     ${i.severity ? `<span class="sev-${esc(i.severity)}">${esc(i.severity)}</span>` : ''}${i.sentiment ? `<span>${esc(i.sentiment)}</span>` : ''}
     <span class=grow></span><span class="pill">${esc(human(i.status))}</span>${bug}${i.owner_flag ? '<span class="pill acc">flagged by you</span>' : ''}</div>
   <div class=txt>${i.title ? `<b>${esc(i.title)}</b>\n` : ''}${esc(i.text.slice(0, 1200))}</div>
   <div class=meta><span>${esc(i.game_title || 'not linked')}</span>${i.app_version ? `<span>v${esc(i.app_version)}</span>` : ''}${i.device ? `<span>${esc(i.device)}</span>` : ''}${i.author ? `<span>${esc(i.author)}</span>` : ''}
     ${i.duplicates ? `<span>+${i.duplicates} duplicate(s)</span>` : ''}${i.group_title ? `<span>group: ${esc(i.group_title)} (${i.group_count})</span>` : ''}<span>${ago(i.ingested_at)}</span></div>
   ${i.reply_draft ? `<div class=reply><label>Reply draft${i.status === 'reply_approved' ? ' · approved: post it yourself, then mark posted' : i.status === 'awaiting_approval' ? ' · waiting at Gate 6' : ''}</label>
     <textarea id="fbr${i.id}" ${replyable ? '' : 'readonly'}>${esc(i.reply_draft)}</textarea></div>` : ''}
   <div class=row style="margin-top:8px">
     ${replyable ? `<button class=sm onclick="fbDraft(${i.id})">Save draft</button>` : ''}
     ${i.reply_draft && ['reply_drafted', 'triaged'].includes(i.status) ? `<button class="sm primary" onclick="fbAct(${i.id},'request_approval')">Send to Gate 6</button>` : ''}
     ${i.status === 'awaiting_approval' ? `<a class="btn sm" href="#approvals">Open at Gate 6</a>` : ''}
     ${i.status === 'reply_approved' ? `<button class=sm onclick="copyText('fbr${i.id}')">Copy reply</button><button class="sm ok" onclick="fbStatus(${i.id},'replied')">Mark posted</button>` : ''}
     ${!i.bug_ticket_id ? `<button class=sm onclick="fbAct(${i.id},'flag_bug')">Send to Bug Fixer</button>` : ''}
     <select onchange="fbGame(${i.id},this.value)" style="font-size:12px;padding:4px 8px"><option value="">${i.game_id ? 'Move to game...' : 'Link to game...'}</option>${gameOpts('', false)}</select>
     <span class=grow></span>
     ${!['ignored', 'closed'].includes(i.status) ? `<button class="sm ghost" onclick="fbStatus(${i.id},'ignored')">Ignore</button><button class="sm ghost" onclick="fbStatus(${i.id},'closed')">Close</button>` : `<button class="sm ghost" onclick="fbStatus(${i.id},'triaged')">Reopen</button>`}
   </div></div>`;
}
async function fbDraft(id) { await post(`/api/feedback/${id}/draft`, {text: $('fbr' + id).value}); toast('Draft saved'); sig.fb = null; refresh(true); }
async function fbAct(id, act) { await post(`/api/feedback/${id}/${act}`); toast(act === 'flag_bug' ? 'Sent to the Bug Fixer' : 'Waiting at Gate 6'); sig.fb = null; refresh(true); }
async function fbStatus(id, s) { await post(`/api/feedback/${id}/status`, {status: s}); sig.fb = null; refresh(true); }
async function fbGame(id, g) { if (!g) return; await post(`/api/feedback/${id}/game`, {game_id: +g}); toast('Linked'); sig.fb = null; refresh(true); }
async function fbUpload(el) { const f = el.files[0]; if (!f) return; const fd = new FormData(); fd.append('file', f);
  const r = await fetch('/api/feedback/upload', {method: 'POST', headers: {'X-Studio': '1'}, body: fd}); const j = await r.json().catch(() => ({}));
  toast(r.ok ? 'Saved to the inbox; Support is ingesting it' : (j.detail || 'Upload failed'), !r.ok); el.value = ''; refresh(true); }

/* ------------------------------------------------------------------ agents */
let AG = null;
async function vAgents(force) {
  AG = await (await fetch('/api/agents')).json();
  if (!force && sig.ag) { // live parts only, never wipe a form the owner is editing
    AG.agents.forEach(a => { const el = $('ags_' + a.name); if (el) el.innerHTML = agLive(a); });
    return;
  }
  sig.ag = 1;
  $('view').innerHTML = `<div class=row style="margin-bottom:14px"><button class=sm onclick="post('/api/agents-all/pause').then(()=>refresh(true))">Pause all agents</button>
     <button class=sm onclick="post('/api/agents-all/resume').then(()=>refresh(true))">Resume all</button>
     <button class=sm onclick="editPrompt('_common')">Edit shared rules (_common.md)</button><span class=grow></span>
     <span class=faint>Engine/model left empty = the default from Settings (${esc(ST.engine)}).</span></div>
   <div class=agents>${AG.agents.map(a => `<div class="card agent">
     <div class=hd>${avatar(a.name)}<div class=grow><h3>${esc(a.label)}</h3><div class=blurb>${esc(a.blurb)}</div></div>
       <div style="text-align:right"><label class=switch title="Enabled"><input type=checkbox ${a.enabled ? 'checked' : ''} onchange="agSet('${a.name}',{enabled:this.checked})"><span></span></label><div class=faint>enabled</div></div></div>
     <div id="ags_${a.name}">${agLive(a)}</div>
     <div class=ctl>
       <div><label class=f>Engine</label><select id="age_${a.name}">${AG.engines.map(e => `<option value="${e}" ${a.engine === e ? 'selected' : ''}>${e || 'default'}</option>`).join('')}</select></div>
       <div><label class=f>Model</label><input id="agm_${a.name}" value="${esc(a.model)}" placeholder="default"></div>
       <div><label class=f>Effort (agy)</label><select id="agf_${a.name}">${AG.efforts.map(e => `<option value="${e}" ${a.effort === e ? 'selected' : ''}>${e || 'default'}</option>`).join('')}</select></div>
     </div>
     <div class=row><button class=sm onclick="agSave('${a.name}')">Save engine</button>
       <button class=sm onclick="agSet('${a.name}',{paused:${!a.paused}})">${a.paused ? 'Resume' : 'Pause'}</button>
       <button class=sm onclick="editPrompt('${a.name}')">Prompt</button>
       <button class=sm onclick="showMemory('${a.name}')">Feedback memory (${a.feedback_notes})</button></div>
     <div class=row style="border-top:1px solid var(--line);padding-top:10px">
       ${a.name === 'support' ? '' : `<select id="agg_${a.name}" style="flex:1 1 140px">${gameOpts('', false) || '<option value="">no games yet</option>'}</select>`}
       <button class="sm primary" onclick="runNow('${a.name}')" title="${esc(a.run_now)}">Run now</button><span class=faint style="flex:1 1 100%">${esc(a.run_now)}</span></div>
   </div>`).join('')}</div>`;
}
function agLive(a) {
  return `<dl class=kv><dt>State</dt><dd>${state(a.state)}${a.paused ? ' <span class=pill>paused</span>' : ''}</dd>
   <dt>Current</dt><dd>${a.current ? esc(a.current.kind) + ' · ' + esc(a.current.game || 'studio') : '-'}</dd>
   <dt>Queue</dt><dd>${a.queue_length}${a.backoff_jobs ? ` (${a.backoff_jobs} in backoff)` : ''}</dd>
   <dt>Last run</dt><dd>${a.last_result ? `${ago(a.last_run_at)} · <a onclick="showRun(${a.last_result.run_id})">#${a.last_result.run_id}</a> ${esc((a.last_result.summary || '').slice(0, 90))}` : '-'}</dd></dl>
   ${a.recent_runs.length > 1 ? `<details><summary class=faint>Recent runs</summary><div class=runs>${a.recent_runs.map(r => `<a onclick="showRun(${r.id})"><b>#${r.id}</b>${esc(r.task)} · ${esc(r.status)} · ${ago(r.started_at)}</a>`).join('')}</div></details>` : ''}`;
}
async function agSet(n, body) { await post('/api/agents/' + n, body); toast('Saved'); sig.ag = 0; refresh(true); }
async function agSave(n) { await agSet(n, {engine: $('age_' + n).value, model: $('agm_' + n).value, effort: $('agf_' + n).value}); }
async function runNow(n) { const g = $('agg_' + n); const r = await post(`/api/agents/${n}/run`, {game_id: g && g.value ? +g.value : null}); toast(`Queued job #${r.job_id} at the front`); refresh(true); }
async function editPrompt(n) {
  const p = await api(`/api/agents/${n}/prompt`);
  modal(`<div class=row><h3>${esc(n)}.md</h3>${p.customized ? '<span class="pill warn">customized</span>' : '<span class="pill ok">default</span>'}<span class=grow></span><span class="faint mono">${esc(p.path)}</span></div>
   <div class=faint style="margin:6px 0 10px">Re-read on every run. The JSON output contract each task must return lives in code (studio/prompts.py) and is appended automatically.</div>
   <textarea id=promptTxt class=code>${esc(p.content)}</textarea>
   <div class=row style="margin-top:10px"><button class=primary onclick="savePrompt('${n}')">Save</button><button class=bad onclick="resetPrompt('${n}')">Reset to default</button>
     <details style="flex:1"><summary class=faint>Show default</summary><pre>${esc(p.default)}</pre></details><button class=ghost onclick="closeModal()">Close</button></div>`);
}
async function savePrompt(n) { await post(`/api/agents/${n}/prompt`, {content: $('promptTxt').value}); toast('Prompt saved'); closeModal(); }
async function resetPrompt(n) { if (!confirm('Replace your edits with the shipped default?')) return; await post(`/api/agents/${n}/prompt/reset`); toast('Reset to default'); editPrompt(n); }
async function showMemory(n) {
  const r = await api(`/api/agents/${n}/feedback`);
  modal(`<h3>Feedback memory: ${esc(n)}</h3><div class=faint style="margin:4px 0 12px">Your rejection notes. The 6 newest for a game are included in every later prompt for this agent on that game.</div>
   ${r.notes.length ? `<table><tr><th>gate</th><th>game</th><th>note</th><th>when</th><th></th></tr>${r.notes.map(f => `<tr><td>G${f.gate}</td><td>${esc(f.game_title || '-')}</td><td>${esc(f.note)}</td><td class=faint>${ago(f.created_at)}</td>
     <td><button class="sm ghost" onclick="delMemory(${f.id},'${n}')">Forget</button></td></tr>`).join('')}</table>` : '<div class=empty>No rejection notes yet.</div>'}
   <div class=row style="margin-top:12px"><span class=grow></span><button class=ghost onclick="closeModal()">Close</button></div>`);
}
async function delMemory(id, n) { await api('/api/agent-feedback/' + id, {method: 'DELETE'}); showMemory(n); sig.ag = 0; }

/* ------------------------------------------------------------------ docs, ledger, jobs */
async function vDocs() {
  const S = await (await fetch('/api/state')).json();
  const k = JSON.stringify([S.docs.length, S.ledger.map(l => l.status), S.jobs.map(j => [j.id, j.status]), S.events[0]?.id]);
  if (sig.docs === k) return; sig.docs = k;
  const b = S.budget;
  $('view').innerHTML = `<div class="grid g2">
   <div class=card><h2>Docs</h2><div class=tbl><table>${S.docs.map(d => `<tr><td><a onclick="showDoc(${d.id})">${esc(d.title)}</a></td><td class=faint>${esc(d.kind)}</td><td class="faint hide-m">${esc(d.agent)}</td><td class=faint>${ago(d.created_at)}</td></tr>`).join('') || '<tr><td class=faint>No docs yet.</td></tr>'}</table></div></div>
   <div><div class=card><h2>Budget / spend ledger</h2><div class=muted style="margin-bottom:8px">This month: ${b.committed_this_month} ${esc(b.currency)} committed of ${b.monthly || 'no'} budget. Every spend needs Gate 4; the studio never pays.</div>
     <div class=tbl><table>${S.ledger.map(l => `<tr><td>${esc(l.amount)} ${esc(l.currency)}</td><td>${esc(l.vendor)}<div class=faint>${esc(l.description)}</div></td><td><span class=pill>${esc(l.status)}</span></td><td>${l.status === 'approved' ? `<button class=sm onclick="post('/api/ledger/${l.id}/spent').then(()=>{sig.docs=null;refresh(true)})">Mark spent</button>` : ''}</td></tr>`).join('') || '<tr><td class=faint>No spend requests.</td></tr>'}</table></div></div>
   <div class=card><h2>Jobs</h2><div class=tbl><table>${S.jobs.map(j => `<tr><td>#${j.id}</td><td>${esc(j.kind)}${j.ticket_id ? ' T#' + j.ticket_id : ''}<div class="faint lvl-error">${esc((j.last_error || '').split('\n')[0].slice(0, 140))}</div></td>
     <td>${esc(j.status)} ${j.attempts}/${j.max_attempts}${j.status === 'queued' && j.next_run_at > S.now ? '<div class=faint>in ' + dur(j.next_run_at - S.now) + '</div>' : ''}</td>
     <td>${['failed', 'queued'].includes(j.status) ? `<button class=sm onclick="post('/api/jobs/${j.id}/retry').then(()=>{sig.docs=null;refresh(true)})">Retry now</button>` : ''}</td></tr>`).join('')}</table></div></div></div></div>
   <div class=card style="margin-top:14px"><h2>Activity</h2><div class=tbl><table>${S.events.map(e => `<tr class="lvl-${e.level}"><td class=faint style="white-space:nowrap">${ago(e.created_at)}</td><td>${esc(e.agent || '')}</td><td>${esc(e.message)}</td></tr>`).join('')}</table></div></div>`;
}
async function showDoc(id) { const d = await api('/api/docs/' + id); modal(`<h3>${esc(d.title)}</h3><div class=faint>${esc(d.kind)} by ${esc(d.agent)}</div><pre style="max-height:65vh">${esc(d.content)}</pre><div class=row><button onclick="copyText('docPre')">Copy</button><span class=grow></span><button class=ghost onclick="closeModal()">Close</button></div><textarea id=docPre style="display:none">${esc(d.content)}</textarea>`); }
async function showRun(id) { const r = await api('/api/runs/' + id); modal(`<div class=row><h3>Run #${r.id}: ${esc(r.agent)} / ${esc(r.task)}</h3><span class=grow></span><span class="pill ${r.status === 'ok' ? 'ok' : 'bad'}">${esc(r.status)}</span></div>
  <div class=faint>${esc(r.engine)} ${esc(r.model || '')} · ${r.tokens || 0} tokens · ${ago(r.started_at)}${r.finished_at ? ' · took ' + dur(r.finished_at - r.started_at) : ''}</div>
  ${r.summary ? `<div class=quote>${esc(r.summary)}</div>` : ''}${r.error ? `<pre class=lvl-error>${esc(r.error)}</pre>` : ''}
  <details open><summary>Output</summary><pre>${esc(r.output)}</pre></details><details><summary>Prompt</summary><pre>${esc(r.prompt)}</pre></details>
  <div class=row><span class=grow></span><button class=ghost onclick="closeModal()">Close</button></div>`); }

/* ------------------------------------------------------------------ settings */
let SET = null;
async function vSettings(force) {
  if (sig.set && !force) return; sig.set = 1;
  SET = await api('/api/settings');
  const groups = {};
  Object.entries(SET.schema).forEach(([k, s]) => (groups[s.group] = groups[s.group] || []).push([k, s]));
  const input = (k, s) => { const v = SET.values[k] ?? '';
    if (s.type === 'bool') return `<label class=switch><input type=checkbox data-k="${k}" ${v === '1' ? 'checked' : ''}><span></span></label>`;
    if (s.type === 'choice') return `<select data-k="${k}">${s.choices.map(c => `<option value="${esc(c)}" ${c === v ? 'selected' : ''}>${esc(c || '(none)')}</option>`).join('')}</select>`;
    if (s.type === 'json') return `<textarea data-k="${k}" class=mono style="min-height:54px">${esc(v)}</textarea>`;
    if (s.type === 'int') return `<input type=number min=0 data-k="${k}" value="${esc(v)}">`;
    if (s.type === 'time') return `<input type=time data-k="${k}" value="${esc(v)}">`;
    return `<input data-k="${k}" value="${esc(v)}" placeholder="${s.type === 'range' ? 'HH:MM-HH:MM (empty = off)' : ''}">`; };
  $('view').innerHTML = `<div class=set-grid>${Object.entries(groups).map(([g, rows]) => `<div class=card><h2>${esc(g)}</h2>
     ${rows.map(([k, s]) => `<div class=set-row><div><div class=n>${esc(k)}</div><div class=h>${esc(s.help)}</div></div><div>${input(k, s)}</div></div>`).join('')}</div>`).join('')}
    <div class=card><h2>Secrets (.env only)</h2><div class=faint style="margin-bottom:8px">Never stored in the database or shown here. Edit <span class=mono>.env</span> and restart.</div>
     ${Object.entries(SET.secrets).map(([k, v]) => `<div class=sec-row><span class=mono>${esc(k)}</span><span class="pill ${v === 'set' ? 'ok' : ''}">${v}</span></div>`).join('')}
     <div class=sp></div><div class=faint>Home: <span class=mono>${esc(SET.home)}</span><br>Feedback inbox: <span class=mono>${esc(SET.feedback_dir)}</span><br>Prompts: <span class=mono>${esc(SET.prompts_dir)}</span></div></div></div>
   <div class=savebar><span class=faint id=dirty>No changes</span><button onclick="sig.set=0;refresh(true)">Discard</button><button class=primary onclick="saveSettings()">Save settings</button></div>`;
  $('view').querySelectorAll('[data-k]').forEach(el => el.addEventListener('change', () => { $('dirty').textContent = 'Unsaved changes'; }));
}
async function saveSettings() {
  const body = {};
  $('view').querySelectorAll('[data-k]').forEach(el => { const k = el.dataset.k; const v = el.type === 'checkbox' ? (el.checked ? '1' : '0') : el.value;
    if (String(SET.values[k] ?? '') !== v) body[k] = v; });
  if (!Object.keys(body).length) return toast('Nothing changed');
  await post('/api/settings', body); toast('Saved ' + Object.keys(body).length + ' setting(s)'); sig.set = 0; refresh(true);
}

const VIEWS = {status: vStatus, approvals: vApprovals, board: vBoard, feedback: vFeedback, agents: vAgents, docs: vDocs, settings: vSettings};
route();
setInterval(() => refresh(false), 4000);
