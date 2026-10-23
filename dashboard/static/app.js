/**
 * Shorts Studio - Client Application
 * Fluid routing, real-time job streaming, library browser & drawer.
 */

(function () {
  'use strict';

  // State
  const state = {
    currentView: 'overview',
    library: [],
    libFilter: 'all',
    libSearch: '',
    jobs: [],
    activeJobPolling: {}, // panelId -> { jobId, afterSeq, timer }
    selectedShort: null,
    publishPage: 1,
    publishPageSize: 12, // 4 columns x 3 rows = 12 cards max
    publishCategory: 'all', // 'all', 'live', 'stream', 'standard'
    activeUploads: {}, // shortId -> { jobId, accountId, handle, percent, text, status }
    accounts: null,
    editedVideos: [],
  };

  const VIEW_TITLES = {
    overview: { title: 'Overview', sub: 'Your pipeline at a glance.' },
    create: { title: 'Create Shorts', sub: 'Extract vertical clips with AI moment detection.' },
    live: { title: 'Live Agent', sub: 'Continuously watch a live stream and clip viral moments.' },
    publish: { title: 'Pending Uploads', sub: 'Review pending Shorts and publish them to YouTube.' },
    scheduled: { title: 'Scheduled Releases', sub: 'Shorts pre-uploaded to YouTube cloud servers and queued for automatic offline release.' },
    library: { title: 'Library', sub: 'Browse and inspect all generated Shorts and metadata.' },
    supabase: { title: 'Supabase Database', sub: 'Direct visual access to your PostgreSQL tables and cloud storage buckets.' },
    activity: { title: 'Activity', sub: 'Execution history, logs, and process states.' },
    system: { title: 'System', sub: 'Health checks, credentials, and disk cache maintenance.' },
  };

  // DOM Elements
  const el = {
    pageTitle: document.getElementById('page-title'),
    pageSub: document.getElementById('page-sub'),
    serverDot: document.getElementById('server-dot'),
    serverStatus: document.getElementById('server-status'),
    runningBadge: document.getElementById('running-badge'),
    topbarActivityBtn: document.getElementById('btn-topbar-activity'),
    activityDropdown: document.getElementById('activity-dropdown'),
    activityDropdownList: document.getElementById('activity-dropdown-list'),
    activityDropdownRefresh: document.getElementById('activity-dropdown-refresh'),
    activityDropdownClose: document.getElementById('activity-dropdown-close'),
    activityPulseDot: document.getElementById('activity-pulse-dot'),
    btnOpenTerminalFromActivity: document.getElementById('btn-open-terminal-from-activity'),
    scrim: document.getElementById('scrim'),
    drawer: document.getElementById('drawer'),
    drawerBody: document.getElementById('drawer-body'),
    drawerClose: document.getElementById('drawer-close'),
    toasts: document.getElementById('toasts'),
  };

  // ─────────────────────────────────────────────────────────────
  // Toast notifications
  // ─────────────────────────────────────────────────────────────
  function toast(msg, type = 'info') {
    const t = document.createElement('div');
    t.className = 'toast';
    t.innerHTML = `<span>${escapeHtml(msg)}</span>`;
    el.toasts.appendChild(t);
    setTimeout(() => {
      t.style.opacity = '0';
      t.style.transform = 'translateY(8px)';
      setTimeout(() => t.remove(), 250);
    }, 3200);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function formatDuration(sec) {
    if (!sec && sec !== 0) return '–';
    const m = Math.floor(sec / 60);
    const s = Math.floor(sec % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
  }

  function formatTimeAgo(ts) {
    if (!ts) return '';
    const now = Date.now() / 1000;
    const diff = Math.max(0, now - ts);
    if (diff < 60) return 'just now';
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
    return `${Math.floor(diff / 86400)}d ago`;
  }

  // ─────────────────────────────────────────────────────────────
  // Routing
  // ─────────────────────────────────────────────────────────────
  function navigate() {
    const hash = window.location.hash.replace(/^#\/?/, '') || 'overview';
    const viewName = VIEW_TITLES[hash] ? hash : 'overview';
    state.currentView = viewName;

    // Nav items
    document.querySelectorAll('.nav-item').forEach(item => {
      const active = item.dataset.view === viewName;
      item.classList.toggle('active', active);
    });

    // Views
    document.querySelectorAll('.view').forEach(v => {
      const active = v.dataset.view === viewName;
      v.hidden = !active;
    });

    const meta = VIEW_TITLES[viewName];
    if (el.pageTitle) el.pageTitle.textContent = meta.title;
    if (el.pageSub) el.pageSub.textContent = meta.sub;

    if (viewName === 'overview') refreshOverview();
    if (viewName === 'create') {
      updateCreateModeUI();
      apiGet('/api/jobs').then(jobs => {
        const running = (jobs || []).find(j => j.status === 'running' && (j.kind === 'process' || j.kind === 'monitor' || j.kind === 'longform'));
        if (!running) {
          resetCreateWorkflowToDefault();
        }
      });
    }
    if (viewName === 'live') refreshLiveAgentView();
    if (viewName === 'library') refreshLibrary();
    if (viewName === 'scheduled') refreshScheduledView();
    if (viewName === 'supabase') refreshSupabase();
    if (viewName === 'publish') refreshPublishQueue();
    if (viewName === 'activity') renderActivityList();
  }

  window.addEventListener('hashchange', navigate);

  // ─────────────────────────────────────────────────────────────
  // Interactive UI Controls (Segmented & Stepper)
  // ─────────────────────────────────────────────────────────────
  function initControls() {
    // Segmented radios
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('.segmented button');
      if (!btn) return;
      const group = btn.closest('.segmented');
      group.querySelectorAll('button').forEach(b => b.setAttribute('aria-checked', 'false'));
      btn.setAttribute('aria-checked', 'true');
    });

    const btnRefLongform = document.getElementById('btn-refresh-longform-list');
    if (btnRefLongform) {
      btnRefLongform.addEventListener('click', () => {
        refreshLongformVideos();
        toast('Refreshed feature videos list', 'ok');
      });
    }
    document.addEventListener('click', (e) => {
      const btn = e.target.closest('.stepper button[data-step]');
      if (!btn) return;
      const stepper = btn.closest('.stepper');
      const out = stepper.querySelector('output');
      const min = parseInt(stepper.dataset.min ?? '0', 10);
      const max = parseInt(stepper.dataset.max ?? '999', 10);
      const inc = parseInt(stepper.dataset.inc ?? '1', 10);
      const step = parseInt(btn.dataset.step, 10);
      let val = parseInt(out.textContent, 10) || 0;
      val = Math.max(min, Math.min(max, val + (step * inc)));
      out.textContent = val;
    });
  }

  function getSegmentedValue(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    const active = el.querySelector('button[aria-checked="true"]');
    return active ? active.dataset.value : null;
  }

  function getStepperValue(id) {
    const el = document.getElementById(id);
    if (!el) return 0;
    const out = el.querySelector('output');
    return out ? parseInt(out.textContent, 10) || 0 : 0;
  }

  // ─────────────────────────────────────────────────────────────
  // API Fetchers
  // ─────────────────────────────────────────────────────────────
  async function apiGet(endpoint) {
    try {
      const res = await fetch(endpoint);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      setServerConnected(true);
      return await res.json();
    } catch (err) {
      setServerConnected(false);
      return null;
    }
  }

  async function apiPost(endpoint, data) {
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
      setServerConnected(true);
      return json;
    } catch (err) {
      toast(err.message || 'Operation failed', 'error');
      throw err;
    }
  }

  function setServerConnected(ok) {
    if (!el.serverDot || !el.serverStatus) return;
    if (ok) {
      el.serverDot.className = 'dot ok';
      el.serverStatus.textContent = 'Connected';
    } else {
      el.serverDot.className = 'dot error';
      el.serverStatus.textContent = 'Offline';
    }
  }

  // ─────────────────────────────────────────────────────────────
  // Overview View
  // ─────────────────────────────────────────────────────────────
  async function refreshOverview() {
    const data = await apiGet('/api/overview');
    if (!data) return;

    // Stat cards
    document.getElementById('st-total').textContent = data.total ?? '0';
    document.getElementById('st-uploaded').textContent = data.uploaded ?? '0';
    document.getElementById('st-pending').textContent = data.pending ?? '0';
    document.getElementById('st-live').textContent = data.live ?? '0';

    // Quota & Daily Upload Goal (Minimum 6/day baseline, no hard stop)
    const quota = data.quota || {};
    const uploadsToday = quota.uploadsToday ?? Math.floor((quota.used || 0) / (quota.perUpload || 1600));
    const minGoal = quota.minGoal ?? 6;
    const targetMet = uploadsToday >= minGoal;
    const goalPct = Math.min(100, Math.round((uploadsToday / minGoal) * 100));

    // Overview Page elements
    const qUploadsToday = document.getElementById('q-uploads-today');
    const qTargetText = document.getElementById('q-target-text');
    const qFill = document.getElementById('q-fill');
    const qMetaText = document.getElementById('q-meta-text');

    if (qUploadsToday) qUploadsToday.textContent = String(uploadsToday);
    if (qTargetText) {
      qTargetText.textContent = targetMet ? `/ ${minGoal} target (met)` : `/ ${minGoal} target (min)`;
    }
    if (qFill) {
      qFill.style.width = `${goalPct}%`;
      qFill.classList.toggle('goal-met', targetMet);
    }
    if (qMetaText) {
      qMetaText.textContent = targetMet
        ? `${uploadsToday} uploads completed today · Target baseline of ${minGoal} met · Unlimited allowed · Resets daily at midnight`
        : `${uploadsToday} of ${minGoal} uploads completed today (${minGoal - uploadsToday} to target) · Resets daily at midnight`;
    }

    // Secondary quota on publish view
    const q2Left = document.getElementById('q2-left');
    const q2Fill = document.getElementById('q2-fill');
    if (q2Left) {
      if (targetMet) {
        q2Left.innerHTML = `<span style="color:#10b981; font-weight:600;">${uploadsToday} uploaded today</span> · Target met`;
      } else {
        q2Left.innerHTML = `<span>${uploadsToday}/${minGoal} uploaded</span> · <span class="muted">${minGoal - uploadsToday} to target</span>`;
      }
    }
    if (q2Fill) {
      q2Fill.style.width = `${goalPct}%`;
      q2Fill.classList.toggle('goal-met', targetMet);
    }

    // Recent items list
    renderRecentList(data.recent || []);

    // Active upload account
    if (data.accounts) {
      updateAccountUI(data.accounts);
    }
  }

  function renderRecentList(items) {
    const list = document.getElementById('recent-list');
    if (!list) return;
    if (!items.length) {
      list.innerHTML = `<li class="muted" style="padding:24px; text-align:center;">No Shorts generated yet.</li>`;
      return;
    }
    list.innerHTML = items.map(item => `
      <li data-id="${item.id}">
        <div class="row-main">
          <div class="row-title">${escapeHtml(item.title)}</div>
          <div class="row-meta">
            ${renderSourceBadge(item.source)}
            ${item.score ? `<span class="chip">Score: ${item.score}</span>` : ''}
            <span>${formatDuration(item.duration)}</span>
            <span>Part ${item.part}/${item.parts}</span>
            <span>${escapeHtml(item.created || '')}</span>
          </div>
        </div>
        <div class="row-actions">
          ${item.uploaded ? '<span class="chip chip-ok">Published</span>' : '<span class="chip chip-warn">In Queue</span>'}
        </div>
      </li>
    `).join('');
  }

  function renderSourceBadge(sourceOrItem) {
    const source = typeof sourceOrItem === 'object' && sourceOrItem !== null ? sourceOrItem.source : sourceOrItem;
    if (source === 'longform') {
      return '<span class="chip chip-scheduled" style="color:#38bdf8; border-color:rgba(56,189,248,0.3);">Longform Feature</span>';
    }
    if (source === 'live') {
      return '<span class="chip chip-quiet" style="color:#a78bfa; border-color:rgba(167,139,250,0.3);">Livestream Clip</span>';
    }
    if (source === 'post_live' || source === 'stream') {
      return '<span class="chip chip-quiet" style="color:#c084fc; border-color:rgba(192,132,252,0.3);">Post Livestream</span>';
    }
    return '<span class="chip chip-quiet">Standard Video</span>';
  }

  // ─────────────────────────────────────────────────────────────
  // Library View
  // ─────────────────────────────────────────────────────────────
  async function loadEditedVideos() {
    try {
      const data = await apiGet('/api/editor/list');
      state.editedVideos = Array.isArray(data) ? data : [];
      const countEl = document.getElementById('lib-edited-count');
      if (countEl) {
        countEl.textContent = state.editedVideos.length;
        countEl.style.display = state.editedVideos.length > 0 ? 'inline-block' : 'none';
      }
    } catch (e) {
      console.error('Failed to load edited videos:', e);
    }
  }

  async function refreshLibrary() {
    await Promise.all([
      apiGet('/api/library').then(data => {
        if (data) state.library = data;
      }),
      loadEditedVideos()
    ]);
    renderLibraryList();
    updateScheduledBadges();
  }

  function renderLibraryList() {
    const list = document.getElementById('lib-list');
    if (!list) return;

    // Dedicated filter for AI Edited Feature Videos
    if (state.libFilter === 'edited') {
      let edited = state.editedVideos || [];
      if (state.libSearch) {
        const q = state.libSearch.toLowerCase();
        edited = edited.filter(v =>
          (v.title && v.title.toLowerCase().includes(q)) ||
          (v.filename && v.filename.toLowerCase().includes(q)) ||
          (v.description && v.description.toLowerCase().includes(q))
        );
      }
      if (!edited.length) {
        list.innerHTML = `<li class="muted" style="padding:40px; text-align:center;">No edited feature videos found. Create one in the Video Edit tab!</li>`;
        return;
      }
      list.innerHTML = edited.map(v => `
        <li data-edited-filename="${escapeHtml(v.filename)}" style="cursor:pointer;">
          <div class="row-main">
            <div class="row-title" style="display:flex; align-items:center; gap:8px;">
              <span class="chip" style="background:rgba(255,0,51,0.12); color:var(--accent-light); font-weight:600; font-size:11px;">Longform Feature</span>
              <span>${escapeHtml(v.title)}</span>
            </div>
            <div class="row-meta">
              <span class="chip chip-quiet">${escapeHtml(v.duration || '8:00')}</span>
              <span>${v.chapters ? v.chapters.length : 0} Acts / Chapters</span>
              <span>${v.size_mb || 0} MB</span>
              ${v.storage_url ? `<span class="chip chip-ok" style="font-size:10.5px;">Cloud Synced (longform-videos)</span>` : '<span class="chip chip-quiet" style="font-size:10.5px;">Local File</span>'}
              <span>${formatScheduledDate(v.created_at)}</span>
            </div>
          </div>
          <div class="row-actions" style="display:flex; align-items:center; gap:8px;">
            <button type="button" class="btn btn-ghost btn-sm" data-play-edited="${escapeHtml(v.filename)}" title="Watch feature video">
              <svg class="icon"><use href="#i-play"/></svg>Watch
            </button>
            ${v.storage_url ? `
              <button type="button" class="btn btn-ghost btn-sm" data-copy-cdn="${escapeHtml(v.storage_url)}" title="Copy Supabase storage URL">
                <svg class="icon"><use href="#i-copy"/></svg>CDN Link
              </button>
            ` : ''}
            <svg class="icon chev"><use href="#i-chevron"/></svg>
          </div>
        </li>
      `).join('');
      return;
    }

    let items = state.library || [];

    // Filter
    if (state.libFilter === 'scheduled') {
      items = items.filter(i => !!i.isScheduledPending || (!!i.scheduledAt && isUpcomingSchedule(i.scheduledAt)));
    } else if (state.libFilter === 'standard') {
      items = items.filter(i => i.source === 'standard');
    } else if (state.libFilter === 'live') {
      items = items.filter(i => i.source === 'live' || i.source === 'stream');
    } else if (state.libFilter === 'pending') {
      items = items.filter(i => !i.uploaded && !i.isScheduledPending && !i.isScheduledReleased);
    } else if (state.libFilter === 'published') {
      items = items.filter(i => i.uploaded || i.isScheduledReleased);
    }

    // Search query
    if (state.libSearch) {
      const q = state.libSearch.toLowerCase();
      items = items.filter(i =>
        (i.title && i.title.toLowerCase().includes(q)) ||
        (i.sourceTitle && i.sourceTitle.toLowerCase().includes(q))
      );
    }

    if (!items.length) {
      list.innerHTML = `<li class="muted" style="padding:40px; text-align:center;">No matching Shorts found.</li>`;
      return;
    }

    list.innerHTML = items.map(item => {
      const isPendingSchedule = Boolean(item.isScheduledPending || (item.scheduledAt && isUpcomingSchedule(item.scheduledAt)));
      const isReleasedSchedule = Boolean(item.isScheduledReleased || (item.originalScheduledAt && !isUpcomingSchedule(item.originalScheduledAt)));

      let statusChip = '<span class="chip chip-warn">In Queue</span>';
      if (isPendingSchedule) {
        statusChip = `
          <span class="chip-scheduled" title="Scheduled on YouTube for automated release">
            <svg class="icon chip-icon"><use href="#i-clock"/></svg>
            <span class="chip-label">Scheduled</span>
            <span class="chip-divider">·</span>
            <span class="chip-date">${formatScheduledDate(item.scheduledAt)}</span>
          </span>
        `;
      } else if (item.uploaded || isReleasedSchedule) {
        statusChip = '<span class="chip chip-ok"><svg class="icon" style="width:12px; height:12px; margin-right:4px;"><use href="#i-check"/></svg>Published</span>';
      }

      return `
        <li data-id="${item.id}">
          <div class="row-main">
            <div class="row-title">${escapeHtml(item.title)}</div>
            <div class="row-meta">
              ${renderSourceBadge(item.source)}
              ${item.score ? `<span class="chip">Score: ${item.score}</span>` : ''}
              <span>${formatDuration(item.duration)}</span>
              <span>Part ${item.part}/${item.parts}</span>
              ${item.sourceTitle ? `<span>from "${escapeHtml(item.sourceTitle)}"</span>` : ''}
            </div>
          </div>
          <div class="row-actions">
            ${statusChip}
            <svg class="icon chev"><use href="#i-chevron"/></svg>
          </div>
        </li>
      `;
    }).join('');
  }

  function formatScheduledDate(isoStr) {
    if (!isoStr) return '';
    try {
      const dt = new Date(isoStr);
      return dt.toLocaleString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
        minute: '2-digit',
      });
    } catch (e) {
      return String(isoStr);
    }
  }

  function formatRelativeRelease(isoStr) {
    if (!isoStr) return '';
    try {
      const dt = new Date(isoStr);
      const diffMs = dt.getTime() - Date.now();
      if (diffMs <= 0) return 'Release time reached';
      const diffMin = Math.round(diffMs / (60 * 1000));
      if (diffMin < 60) return `Releases in ${diffMin} min`;
      const diffHrs = Math.floor(diffMin / 60);
      const remMin = diffMin % 60;
      if (diffHrs < 24) {
        return remMin > 0 ? `Releases in ~${diffHrs}h ${remMin}m` : `Releases in ~${diffHrs}h`;
      }
      const days = Math.round(diffHrs / 24);
      return `Releases in ~${days} day${days > 1 ? 's' : ''}`;
    } catch (e) {
      return '';
    }
  }

  function isUpcomingSchedule(scheduledAt) {
    if (!scheduledAt) return false;
    try {
      return new Date(scheduledAt).getTime() > Date.now();
    } catch (e) {
      return false;
    }
  }

  function updateScheduledBadges(count = null) {
    if (count === null && state.library) {
      count = state.library.filter(i => Boolean(i.isScheduledPending || (i.scheduledAt && isUpcomingSchedule(i.scheduledAt)))).length;
    }
    const c = count || 0;
    const navBadge = document.getElementById('scheduled-nav-badge');
    const viewCountText = document.getElementById('scheduled-count-text');

    if (navBadge) {
      navBadge.textContent = String(c);
      navBadge.style.display = c > 0 ? 'inline-flex' : 'none';
    }
    if (viewCountText) {
      viewCountText.textContent = `${c} Scheduled`;
    }
  }

  // ─────────────────────────────────────────────────────────────
  // Scheduled Releases View Manager
  // ─────────────────────────────────────────────────────────────
  async function refreshScheduledView() {
    if (!state.library || !state.library.length) {
      const data = await apiGet('/api/library');
      if (data) state.library = data;
    }

    const upcoming = (state.library || []).filter(i => Boolean(i.isScheduledPending || (i.scheduledAt && isUpcomingSchedule(i.scheduledAt))));
    const released = (state.library || []).filter(i => Boolean(i.isScheduledReleased || (i.originalScheduledAt && !isUpcomingSchedule(i.originalScheduledAt))));

    updateScheduledBadges(upcoming.length);

    const container = document.getElementById('scheduled-grid-container');
    if (!container) return;

    if (!upcoming.length) {
      container.innerHTML = `
        <div style="grid-column:1/-1; padding:36px 20px; text-align:center; max-width:540px; margin:20px auto; border:1px solid rgba(255,255,255,0.08); border-radius:var(--radius-lg); background:transparent;">
          <svg class="icon" style="width:36px; height:36px; color:var(--success); margin:0 auto 12px auto;"><use href="#i-check"/></svg>
          <h3 style="font-size:15px; font-weight:600; color:var(--text-primary);">No Pending Scheduled Releases</h3>
          <p class="muted small" style="max-width:420px; margin:6px auto 16px auto;">
            ${released.length ? `All scheduled Shorts (${released.length}) have reached their release time and have been published to YouTube!` : 'When you schedule a Short for later, it will appear here in the active queue until published.'}
          </p>
          <div style="display:flex; justify-content:center; gap:10px; flex-wrap:wrap;">
            <a href="#/library" class="btn btn-ghost btn-sm">
              <svg class="icon"><use href="#i-film"/></svg>View in Library
            </a>
            <a href="#/publish" class="btn btn-primary btn-sm">
              <svg class="icon"><use href="#i-send"/></svg>Schedule More Shorts
            </a>
          </div>
        </div>
        ${released.length ? `
          <div style="grid-column:1/-1; margin-top:24px;">
            <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px; padding:0 4px;">
              <span style="font-size:13px; font-weight:600; color:var(--text-secondary);">Recently Released on Schedule (${released.length})</span>
              <span class="muted small">Live on YouTube</span>
            </div>
            <div class="scheduled-grid">
              ${released.map(item => `
                <div class="scheduled-item-card" data-card-id="${item.id}">
                  <div class="scheduled-card-header">
                    <span class="scheduled-status-pill ready">
                      <svg class="icon"><use href="#i-check"/></svg>
                      <span>Published to YouTube · ${formatScheduledDate(item.originalScheduledAt || item.scheduledAt)}</span>
                    </span>
                    <div class="scheduled-card-tags">
                      ${item.parts > 1 ? `<span class="chip-part-badge">Part ${item.part}/${item.parts}</span>` : ''}
                      ${item.score ? `<span class="chip-score-badge">${item.score}/10</span>` : ''}
                    </div>
                  </div>

                  <div style="display:flex; flex-direction:column; gap:4px;">
                    <div class="scheduled-card-title">${escapeHtml(item.title)}</div>
                    ${item.sourceTitle ? `<div class="scheduled-card-source">from "${escapeHtml(item.sourceTitle)}"</div>` : ''}
                  </div>

                  <div class="scheduled-card-meta">
                    <span style="display:inline-flex; align-items:center; gap:4px; color:var(--success);">
                      <svg class="icon" style="width:12px; height:12px;"><use href="#i-check"/></svg>Live on Channel
                    </span>
                    <span>·</span>
                    <span>${formatDuration(item.duration)}</span>
                    <span>·</span>
                    <span>${item.source === 'live' || item.source === 'stream' ? 'Stream Cut' : 'Short'}</span>
                  </div>

                  <div class="scheduled-card-actions">
                    <div style="display:flex; align-items:center; gap:6px;">
                      <button type="button" class="btn btn-ghost btn-sm" data-preview-id="${item.id}">
                        <svg class="icon"><use href="#i-play"/></svg>Preview
                      </button>
                      <button type="button" class="btn btn-ghost btn-sm" data-drawer-id="${item.id}">Details</button>
                    </div>
                    ${item.youtubeId ? `
                      <a href="https://youtube.com/shorts/${escapeHtml(item.youtubeId)}" target="_blank" class="btn-youtube-subtle">
                        <svg class="icon" style="width:14px; height:14px;"><use href="#i-youtube"/></svg>View on YouTube
                      </a>
                    ` : ''}
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
        ` : ''}
      `;

      container.querySelectorAll('[data-preview-id]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const id = parseInt(btn.dataset.previewId, 10);
          const item = state.library.find(x => x.id === id);
          if (item) openVideoModal(item);
        });
      });
      container.querySelectorAll('[data-drawer-id]').forEach(btn => {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const id = parseInt(btn.dataset.drawerId, 10);
          const item = state.library.find(x => x.id === id);
          if (item) openDrawer(item);
        });
      });
      return;
    }

    container.innerHTML = upcoming.map(item => {
      const relTime = formatRelativeRelease(item.scheduledAt);
      return `
        <div class="scheduled-item-card" data-card-id="${item.id}">
          <div class="scheduled-card-header">
            <span class="scheduled-status-pill active">
              <svg class="icon"><use href="#i-clock"/></svg>
              <span>Scheduled · ${formatScheduledDate(item.scheduledAt)}</span>
              ${relTime ? `<span class="muted" style="margin-left:2px;">(${escapeHtml(relTime)})</span>` : ''}
            </span>
            <div class="scheduled-card-tags">
              ${item.parts > 1 ? `<span class="chip-part-badge">Part ${item.part}/${item.parts}</span>` : ''}
              ${item.score ? `<span class="chip-score-badge">${item.score}/10</span>` : ''}
            </div>
          </div>

          <div style="display:flex; flex-direction:column; gap:4px;">
            <div class="scheduled-card-title">${escapeHtml(item.title)}</div>
            ${item.sourceTitle ? `<div class="scheduled-card-source">from "${escapeHtml(item.sourceTitle)}"</div>` : ''}
          </div>

          <div class="scheduled-card-meta">
            <span style="display:inline-flex; align-items:center; gap:4px;">
              <svg class="icon" style="width:12px; height:12px;"><use href="#i-lock"/></svg>Private pre-release
            </span>
            <span>·</span>
            <span>${formatDuration(item.duration)}</span>
            <span>·</span>
            <span>${item.source === 'live' || item.source === 'stream' ? 'Stream Cut' : 'Short'}</span>
          </div>

          <div class="scheduled-card-actions">
            <div style="display:flex; align-items:center; gap:6px;">
              <button type="button" class="btn btn-ghost btn-sm" data-preview-id="${item.id}">
                <svg class="icon"><use href="#i-play"/></svg>Preview
              </button>
              <button type="button" class="btn btn-ghost btn-sm" data-drawer-id="${item.id}">Details</button>
            </div>
            ${item.youtubeId ? `
              <a href="https://youtube.com/shorts/${escapeHtml(item.youtubeId)}" target="_blank" class="btn-youtube-subtle">
                <svg class="icon" style="width:14px; height:14px;"><use href="#i-youtube"/></svg>View on YouTube
              </a>
            ` : ''}
          </div>
        </div>
      `;
    }).join('');

    container.querySelectorAll('[data-preview-id]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.previewId, 10);
        const item = state.library.find(x => x.id === id);
        if (item) openVideoModal(item);
      });
    });

    container.querySelectorAll('[data-drawer-id]').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(btn.dataset.drawerId, 10);
        const item = state.library.find(x => x.id === id);
        if (item) openDrawer(item);
      });
    });
  }

  function updateScheduledBadges(count = null) {
    if (count === null && state.library) {
      count = state.library.filter(i => !!i.scheduledAt).length;
    }
    const c = count || 0;
    const navBadge = document.getElementById('scheduled-nav-badge');
    const viewCountText = document.getElementById('scheduled-count-text');

    if (navBadge) {
      navBadge.textContent = String(c);
      navBadge.style.display = c > 0 ? 'inline-flex' : 'none';
    }
    if (viewCountText) {
      viewCountText.textContent = `${c} Scheduled`;
    }
  }

  // Tab & search listeners
  const libTabs = document.getElementById('lib-tabs');
  if (libTabs) {
    libTabs.addEventListener('click', (e) => {
      const btn = e.target.closest('button[data-filter]');
      if (!btn) return;
      libTabs.querySelectorAll('button').forEach(b => b.setAttribute('aria-selected', 'false'));
      btn.setAttribute('aria-selected', 'true');
      state.libFilter = btn.dataset.filter;
      renderLibraryList();
    });
  }

  const libSearch = document.getElementById('lib-search');
  if (libSearch) {
    libSearch.addEventListener('input', (e) => {
      state.libSearch = e.target.value.trim();
      renderLibraryList();
    });
  }

  // Row click delegation to open Drawer or play Edited Videos
  document.addEventListener('click', (e) => {
    const playBtn = e.target.closest('[data-play-edited]');
    const editedLi = e.target.closest('.rows li[data-edited-filename]');
    if (playBtn || editedLi) {
      const fname = playBtn ? playBtn.dataset.playEdited : editedLi.dataset.editedFilename;
      const v = (state.editedVideos || []).find(x => x.filename === fname);
      if (v) {
        openVideoModal({
          title: v.title,
          isLongform: true,
          videoSrc: v.storage_url || v.video_url,
          duration: v.duration,
          chapters: v.chapters,
        });
      }
      return;
    }

    const copyBtn = e.target.closest('[data-copy-cdn]');
    if (copyBtn) {
      e.stopPropagation();
      navigator.clipboard.writeText(copyBtn.dataset.copyCdn);
      toast('Supabase CDN link copied', 'ok');
      return;
    }

    const li = e.target.closest('.rows li[data-id]');
    if (!li) return;
    const id = parseInt(li.dataset.id, 10);
    const item = (state.library || []).find(x => x.id === id);
    if (item) openDrawer(item);
  });

  // ─────────────────────────────────────────────────────────────
  // Details Drawer
  // ─────────────────────────────────────────────────────────────
  function openDrawer(item) {
    state.selectedShort = item;
    el.scrim.hidden = false;
    el.drawer.setAttribute('aria-hidden', 'false');

    let storageHtml = item.storageUrl ? `
      <div class="detail-section">
        <label>Supabase Cloud Storage</label>
        <div style="display:flex; gap:8px; align-items:center;">
          <input type="text" class="input" value="${escapeHtml(item.storageUrl)}" readonly style="font-family:var(--font-mono); font-size:11px;">
          <a href="${escapeHtml(item.storageUrl)}" target="_blank" class="btn btn-ghost" style="padding:8px 12px;" title="Open video file in new tab">
            <svg class="icon"><use href="#i-external"/></svg>
          </a>
        </div>
      </div>
    ` : '';

    let ytHtml = '';
    if (item.scheduledAt) {
      ytHtml = `
        <div class="detail-section">
          <label>YouTube Scheduled Release</label>
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="chip-scheduled">
              <svg class="icon chip-icon"><use href="#i-clock"/></svg>
              <span class="chip-label">Scheduled</span>
            </span>
            <span style="font-size:13px; font-weight:600; color:#ffffff;">${formatScheduledDate(item.scheduledAt)}</span>
          </div>
          <p class="muted small" style="margin-top:6px;">Pre-uploaded to YouTube servers as Private. YouTube will automatically make it public at this time even if your computer is offline.</p>
          ${item.youtubeId ? `
            <a href="https://youtube.com/shorts/${escapeHtml(item.youtubeId)}" target="_blank" class="btn btn-ghost" style="margin-top:8px; align-self:flex-start;">
              <svg class="icon"><use href="#i-youtube"/></svg>View Scheduled Short on YouTube
            </a>
          ` : ''}
        </div>
      `;
    } else if (item.youtubeId) {
      ytHtml = `
        <div class="detail-section">
          <label>YouTube Link</label>
          <a href="https://youtube.com/shorts/${escapeHtml(item.youtubeId)}" target="_blank" class="btn btn-primary" style="align-self:flex-start;">
            <svg class="icon"><use href="#i-youtube"/></svg>View on YouTube
          </a>
        </div>
      `;
    } else {
      ytHtml = `
        <div class="detail-section">
          <label>YouTube Status</label>
          <p class="muted" style="margin-bottom:8px;">Not yet published or scheduled.</p>
          <button type="button" class="btn btn-primary" id="drawer-publish-btn" style="align-self:flex-start;">
            <svg class="icon"><use href="#i-youtube"/></svg>Publish / Schedule Upload
          </button>
        </div>
      `;
    }

    let videoSrc = item.videoUrl || item.storageUrl || `/api/video?id=${item.id}`;
    let videoPlayerHtml = `
      <div class="detail-section">
        <label>Video Player</label>
        <video id="drawer-video-player" src="${escapeHtml(videoSrc)}" controls preload="metadata" playsinline style="width:100%; max-height:360px; border-radius:var(--radius-md); background:#000; object-fit:contain; box-shadow:0 4px 18px rgba(0,0,0,0.6);"></video>
      </div>
    `;

    el.drawerBody.innerHTML = `
      <div class="detail-section">
        <label>Hook Title</label>
        <h3 style="font-size:16px; font-weight:600; color:var(--text-primary);">${escapeHtml(item.title)}</h3>
      </div>

      ${videoPlayerHtml}

      <div class="detail-section">
        <label>Properties</label>
        <div style="display:flex; flex-wrap:wrap; gap:8px;">
          ${renderSourceBadge(item.source)}
          <span class="chip">Duration: ${formatDuration(item.duration)}</span>
          <span class="chip">Part: ${item.part} of ${item.parts}</span>
          ${item.score ? `<span class="chip chip-ok">Viral Score: ${item.score}/10</span>` : ''}
          ${item.hasLocal ? '<span class="chip chip-quiet">Cached locally</span>' : '<span class="chip chip-quiet">Cloud only</span>'}
        </div>
      </div>

      ${item.reasoning ? `
        <div class="detail-section">
          <label>AI Viral Selection Reasoning</label>
          <p style="background:var(--bg-input); padding:12px; border-radius:var(--radius-md); border:1px solid var(--border-subtle); font-size:12px;">
            ${escapeHtml(item.reasoning)}
          </p>
        </div>
      ` : ''}

      ${item.description ? `
        <div class="detail-section">
          <label>Generated Description & Tags</label>
          <p style="background:var(--bg-input); padding:12px; border-radius:var(--radius-md); border:1px solid var(--border-subtle); font-size:12px; white-space:pre-wrap;">
            ${escapeHtml(item.description)}
          </p>
        </div>
      ` : ''}

      ${storageHtml}
      ${ytHtml}

      <div class="detail-section" style="margin-top:10px; padding-top:14px; border-top:1px solid var(--border-subtle);">
        <button class="btn btn-ghost" id="drawer-delete-btn" style="color:#ff4d4f; align-self:flex-start;">
          <svg class="icon"><use href="#i-trash"/></svg>Delete from Supabase & Database
        </button>
      </div>
    `;

    const drawerPub = document.getElementById('drawer-publish-btn');
    if (drawerPub) {
      drawerPub.addEventListener('click', () => {
        closeDrawer();
        openPublishAccountModal(item.id, item.title);
      });
    }

    const drawerDel = document.getElementById('drawer-delete-btn');
    if (drawerDel) {
      drawerDel.addEventListener('click', () => {
        closeDrawer();
        openDeleteModal(item);
      });
    }
  }

  function closeDrawer() {
    // Stop any playing video in the drawer immediately
    if (el.drawerBody) {
      const v = el.drawerBody.querySelector('video');
      if (v) {
        v.pause();
        v.removeAttribute('src');
        v.load();
      }
      el.drawerBody.innerHTML = '';
    }
    el.scrim.hidden = true;
    el.drawer.setAttribute('aria-hidden', 'true');
    state.selectedShort = null;
  }

  if (el.drawerClose) el.drawerClose.addEventListener('click', closeDrawer);
  if (el.scrim) el.scrim.addEventListener('click', closeDrawer);
  window.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && el.drawer && el.drawer.getAttribute('aria-hidden') === 'false') {
      closeDrawer();
    }
  });

  // ─────────────────────────────────────────────────────────────
  // Supabase Database & Cloud Storage Explorer
  // ─────────────────────────────────────────────────────────────
  state.sb = {
    mode: 'tables', // 'tables' or 'storage'
    table: 'shorts_metadata',
    filter: '',
    search: '',
    bucket: 'youtube-shorts',
    prefix: '',
  };

  function formatBytes(bytes) {
    if (!bytes && bytes !== 0) return '–';
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  async function refreshSupabase() {
    const status = await apiGet('/api/supabase/status');
    const statusTitle = document.getElementById('sb-status-title');
    const dot = document.getElementById('sb-dot');
    const urlEl = document.getElementById('sb-url');
    const badgeMeta = document.getElementById('badge-shorts-meta');
    const badgeSeries = document.getElementById('badge-video-series');

    if (!status || !status.connected) {
      if (statusTitle) statusTitle.textContent = 'Supabase Disconnected';
      if (dot) dot.className = 'dot error';
      if (urlEl) urlEl.textContent = status?.error || 'Missing credentials in .env';
      return;
    }

    if (statusTitle) statusTitle.textContent = 'Supabase Cloud Database';
    if (dot) dot.className = 'dot ok';
    if (urlEl) {
      try {
        const u = new URL(status.url);
        urlEl.textContent = u.host;
      } catch (e) {
        urlEl.textContent = status.url;
      }
    }

    if (status.tables) {
      if (badgeMeta) badgeMeta.textContent = status.tables.shorts_metadata ?? '0';
      if (badgeSeries) badgeSeries.textContent = status.tables.video_series ?? '0';
    }

    if (state.sb.mode === 'tables') {
      loadSupabaseTable();
    } else {
      loadSupabaseStorage();
    }
  }

  async function loadSupabaseTable() {
    const container = document.getElementById('sb-table-container');
    if (!container) return;

    container.innerHTML = '<div class="muted" style="padding:40px; text-align:center;">Loading Supabase rows...</div>';

    const url = `/api/supabase/table?name=${state.sb.table}&search=${encodeURIComponent(state.sb.search)}&filter=${state.sb.filter}`;
    const data = await apiGet(url);

    if (!data || data.error) {
      container.innerHTML = `<div class="muted" style="padding:40px; text-align:center; color:var(--danger);">${escapeHtml(data?.error || 'Failed to load table')}</div>`;
      return;
    }

    const rows = data.rows || [];
    if (!rows.length) {
      container.innerHTML = '<div class="muted" style="padding:40px; text-align:center;">No matching rows found in ' + escapeHtml(state.sb.table) + '.</div>';
      return;
    }

    if (state.sb.table === 'shorts_metadata') {
      container.innerHTML = `
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width:60px;">ID</th>
                <th>Hook Title</th>
                <th style="width:100px;">Duration</th>
                <th style="width:90px;">Viral Score</th>
                <th style="width:90px;">Part</th>
                <th style="width:110px;">Status</th>
                <th>Storage URL</th>
                <th style="width:130px;">Created</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(r => `
                <tr data-sb-row="${r.id}" title="Click to view full record">
                  <td style="font-family:var(--font-mono); color:var(--text-faint);">${r.id}</td>
                  <td><strong>${escapeHtml(r.hook_title || 'Untitled')}</strong></td>
                  <td style="font-family:var(--font-mono);">${formatDuration(r.duration)}</td>
                  <td>${r.hook_score ? `<span class="chip chip-ok">${r.hook_score}/10</span>` : '–'}</td>
                  <td>Part ${r.part_number || 1}/${r.total_parts || 1}</td>
                  <td>${r.youtube_id || r.is_confirmed_uploaded ? '<span class="chip chip-ok">Uploaded</span>' : '<span class="chip chip-warn">Pending</span>'}</td>
                  <td style="font-family:var(--font-mono); font-size:11px; color:var(--text-muted);">${r.storage_url ? `<a href="${escapeHtml(r.storage_url)}" target="_blank" class="link-btn" onclick="event.stopPropagation();">Open video</a>` : '–'}</td>
                  <td style="font-size:11px; color:var(--text-muted);">${escapeHtml((r.created_at || '').substring(0, 16).replace('T', ' '))}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    } else {
      // video_series table
      container.innerHTML = `
        <div class="table-wrap">
          <table class="data-table">
            <thead>
              <tr>
                <th style="width:60px;">ID</th>
                <th style="width:90px;">Part</th>
                <th>Short Title</th>
                <th>Source Title</th>
                <th style="width:100px;">Duration</th>
                <th style="width:110px;">Status</th>
                <th>YouTube URL</th>
                <th style="width:130px;">Created</th>
              </tr>
            </thead>
            <tbody>
              ${rows.map(r => `
                <tr data-sb-row="${r.id}" title="Click to view full record">
                  <td style="font-family:var(--font-mono); color:var(--text-faint);">${r.id}</td>
                  <td><span class="chip chip-quiet">Part ${r.part_number}/${r.total_parts}</span></td>
                  <td><strong>${escapeHtml(r.short_title || '')}</strong></td>
                  <td style="color:var(--text-muted);">${escapeHtml(r.source_title || '')}</td>
                  <td style="font-family:var(--font-mono);">${formatDuration(r.duration)}</td>
                  <td>${r.is_confirmed || r.youtube_id ? '<span class="chip chip-ok">Uploaded</span>' : '<span class="chip chip-warn">Pending</span>'}</td>
                  <td>${r.youtube_url ? `<a href="${escapeHtml(r.youtube_url)}" target="_blank" class="link-btn" onclick="event.stopPropagation();"><svg class="icon"><use href="#i-youtube"/></svg>View</a>` : '–'}</td>
                  <td style="font-size:11px; color:var(--text-muted);">${escapeHtml((r.created_at || '').substring(0, 16).replace('T', ' '))}</td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>
      `;
    }

    container.querySelectorAll('tr[data-sb-row]').forEach(tr => {
      tr.addEventListener('click', () => {
        const id = parseInt(tr.dataset.sbRow, 10);
        const row = rows.find(x => x.id === id);
        if (row) openSupabaseRowDrawer(row, state.sb.table);
      });
    });
  }

  function openSupabaseRowDrawer(row, tableName) {
    el.scrim.hidden = false;
    el.drawer.setAttribute('aria-hidden', 'false');

    let fieldsHtml = Object.entries(row).map(([k, v]) => {
      let valDisplay = v;
      if (v === null || v === undefined) valDisplay = '<span class="muted">null</span>';
      else if (typeof v === 'boolean') valDisplay = v ? '<span class="chip chip-ok">true</span>' : '<span class="chip chip-warn">false</span>';
      else if (typeof v === 'object') valDisplay = `<pre style="font-family:var(--font-mono); font-size:11px; background:var(--bg-input); padding:8px; border-radius:4px; overflow-x:auto;">${escapeHtml(JSON.stringify(v, null, 2))}</pre>`;
      else if (String(v).startsWith('http')) valDisplay = `<a href="${escapeHtml(String(v))}" target="_blank" class="link-btn" style="word-break:break-all;">${escapeHtml(String(v))} <svg class="icon"><use href="#i-external"/></svg></a>`;
      else valDisplay = `<span style="word-break:break-word;">${escapeHtml(String(v))}</span>`;

      return `
        <div class="detail-section" style="border-bottom:1px solid var(--border-subtle); padding-bottom:8px;">
          <label style="font-family:var(--font-mono); font-size:10.5px; color:var(--text-faint);">${escapeHtml(k)}</label>
          <div style="font-size:12.5px; color:var(--text-primary); margin-top:2px;">${valDisplay}</div>
        </div>
      `;
    }).join('');

    el.drawerBody.innerHTML = `
      <div class="detail-section">
        <label>Supabase Record (${escapeHtml(tableName)})</label>
        <h3 style="font-size:16px; font-weight:600; color:var(--text-primary);">Record #${row.id}</h3>
      </div>
      <div style="display:flex; flex-direction:column; gap:12px;">
        ${fieldsHtml}
      </div>
    `;
  }

  async function loadSupabaseStorage() {
    const list = document.getElementById('sb-storage-list');
    const breadcrumbs = document.getElementById('sb-breadcrumbs');
    if (!list) return;

    list.innerHTML = '<li class="muted" style="padding:40px; text-align:center;">Loading storage items...</li>';

    // Render breadcrumbs
    const parts = state.sb.prefix ? state.sb.prefix.split('/') : [];
    let breadcrumbHtml = `<span class="muted">Path:</span> <button class="breadcrumb-btn ${!parts.length ? 'active' : ''}" data-path="">${escapeHtml(state.sb.bucket)}</button>`;
    let accum = '';
    for (let i = 0; i < parts.length; i++) {
      accum = accum ? `${accum}/${parts[i]}` : parts[i];
      const isLast = i === parts.length - 1;
      breadcrumbHtml += ` <span class="muted">/</span> <button class="breadcrumb-btn ${isLast ? 'active' : ''}" data-path="${escapeHtml(accum)}">${escapeHtml(parts[i])}</button>`;
    }
    if (breadcrumbs) breadcrumbs.innerHTML = breadcrumbHtml;

    const data = await apiGet(`/api/supabase/storage?bucket=${state.sb.bucket}&prefix=${encodeURIComponent(state.sb.prefix)}`);
    if (!data || data.error) {
      list.innerHTML = `<li class="muted" style="padding:40px; text-align:center; color:var(--danger);">${escapeHtml(data?.error || 'Failed to list storage')}</li>`;
      return;
    }

    const items = data.items || [];
    if (!items.length) {
      list.innerHTML = '<li class="muted" style="padding:40px; text-align:center;">Folder is empty.</li>';
      return;
    }

    list.innerHTML = items.map(item => {
      if (item.isDir) {
        return `
          <li data-folder-path="${escapeHtml(item.path)}">
            <div class="row-main">
              <div class="row-title" style="display:flex; align-items:center; gap:8px;">
                <svg class="icon" style="color:var(--accent);"><use href="#i-folder"/></svg>
                <strong>${escapeHtml(item.name)}</strong>
              </div>
              <div class="row-meta">
                <span class="chip chip-quiet">Folder</span>
              </div>
            </div>
            <div class="row-actions">
              <svg class="icon chev"><use href="#i-chevron"/></svg>
            </div>
          </li>
        `;
      } else {
        return `
          <li data-file-path="${escapeHtml(item.path)}" data-file-url="${escapeHtml(item.public_url || '')}">
            <div class="row-main">
              <div class="row-title" style="display:flex; align-items:center; gap:8px;">
                <svg class="icon" style="color:var(--accent-light);"><use href="#i-film"/></svg>
                <span>${escapeHtml(item.name)}</span>
              </div>
              <div class="row-meta">
                <span class="chip">${formatBytes(item.size)}</span>
                ${item.created_at ? `<span>${escapeHtml(item.created_at.substring(0, 16).replace('T', ' '))}</span>` : ''}
              </div>
            </div>
            <div class="row-actions">
              ${item.public_url ? `
                <button class="btn btn-ghost" style="padding:4px 8px;" onclick="event.stopPropagation(); navigator.clipboard.writeText('${item.public_url}'); toast('Public URL copied', 'ok');" title="Copy public link">
                  <svg class="icon"><use href="#i-copy"/></svg>
                </button>
                <a href="${escapeHtml(item.public_url)}" target="_blank" class="btn btn-ghost" style="padding:4px 8px;" onclick="event.stopPropagation();" title="Open file in new tab">
                  <svg class="icon"><use href="#i-external"/></svg>
                </a>
              ` : ''}
            </div>
          </li>
        `;
      }
    }).join('');

    list.querySelectorAll('li[data-folder-path]').forEach(li => {
      li.addEventListener('click', () => {
        state.sb.prefix = li.dataset.folderPath;
        loadSupabaseStorage();
      });
    });

    list.querySelectorAll('li[data-file-url]').forEach(li => {
      li.addEventListener('click', () => {
        const url = li.dataset.fileUrl;
        const name = li.dataset.filePath;
        if (url) openFilePreviewDrawer(name, url);
      });
    });
  }

  function openFilePreviewDrawer(name, url) {
    el.scrim.hidden = false;
    el.drawer.setAttribute('aria-hidden', 'false');

    el.drawerBody.innerHTML = `
      <div class="detail-section">
        <label>Cloud Storage Object</label>
        <h3 style="font-size:14px; font-weight:600; color:var(--text-primary); word-break:break-all;">${escapeHtml(name)}</h3>
      </div>

      <div class="detail-section">
        <label>Video Player</label>
        <div style="background:#000; border-radius:var(--radius-md); overflow:hidden; border:1px solid var(--border-subtle); display:flex; justify-content:center;">
          <video src="${escapeHtml(url)}" controls autoplay style="max-height:420px; width:100%; object-fit:contain;"></video>
        </div>
      </div>

      <div class="detail-section">
        <label>Public Link</label>
        <div style="display:flex; gap:8px;">
          <input type="text" class="input" value="${escapeHtml(url)}" readonly style="font-family:var(--font-mono); font-size:11px;">
          <button class="btn btn-ghost" onclick="navigator.clipboard.writeText('${url}'); toast('URL copied', 'ok');">Copy</button>
        </div>
      </div>
    `;
  }

  function initSupabaseListeners() {
    const modeToggle = document.getElementById('sb-mode-toggle');
    if (modeToggle) {
      modeToggle.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-value]');
        if (!btn) return;
        state.sb.mode = btn.dataset.value;
        const tablesPanel = document.getElementById('sb-tables-panel');
        const storagePanel = document.getElementById('sb-storage-panel');
        if (tablesPanel && storagePanel) {
          tablesPanel.style.display = state.sb.mode === 'tables' ? 'flex' : 'none';
          storagePanel.style.display = state.sb.mode === 'storage' ? 'flex' : 'none';
        }
        if (state.sb.mode === 'tables') loadSupabaseTable();
        else loadSupabaseStorage();
      });
    }

    const tableTabs = document.getElementById('sb-table-tabs');
    if (tableTabs) {
      tableTabs.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-table]');
        if (!btn) return;
        tableTabs.querySelectorAll('button').forEach(b => b.setAttribute('aria-selected', 'false'));
        btn.setAttribute('aria-selected', 'true');
        state.sb.table = btn.dataset.table;
        loadSupabaseTable();
      });
    }

    const tableFilter = document.getElementById('sb-table-filter');
    if (tableFilter) {
      tableFilter.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-filter]');
        if (!btn) return;
        state.sb.filter = btn.dataset.filter;
        loadSupabaseTable();
      });
    }

    const tableSearch = document.getElementById('sb-table-search');
    if (tableSearch) {
      tableSearch.addEventListener('input', (e) => {
        state.sb.search = e.target.value.trim();
        loadSupabaseTable();
      });
    }

    const tableRefresh = document.getElementById('sb-table-refresh');
    if (tableRefresh) {
      tableRefresh.addEventListener('click', () => loadSupabaseTable());
    }

    const bucketTabs = document.getElementById('sb-bucket-tabs');
    if (bucketTabs) {
      bucketTabs.addEventListener('click', (e) => {
        const btn = e.target.closest('button[data-bucket]');
        if (!btn) return;
        bucketTabs.querySelectorAll('button').forEach(b => b.setAttribute('aria-selected', 'false'));
        btn.setAttribute('aria-selected', 'true');
        state.sb.bucket = btn.dataset.bucket;
        state.sb.prefix = '';
        loadSupabaseStorage();
      });
    }

    const breadcrumbs = document.getElementById('sb-breadcrumbs');
    if (breadcrumbs) {
      breadcrumbs.addEventListener('click', (e) => {
        const btn = e.target.closest('.breadcrumb-btn[data-path]');
        if (!btn) return;
        state.sb.prefix = btn.dataset.path;
        loadSupabaseStorage();
      });
    }

    const storageRefresh = document.getElementById('sb-storage-refresh');
    if (storageRefresh) {
      storageRefresh.addEventListener('click', () => loadSupabaseStorage());
    }
  }

  // ─────────────────────────────────────────────────────────────
  // Publish Queue View
  // ─────────────────────────────────────────────────────────────
  // ─────────────────────────────────────────────────────────────
  // Publish Queue View (4x3 Card Grid & One-Click Publish)
  // ─────────────────────────────────────────────────────────────
  async function refreshPublishQueue() {
    const data = await apiGet('/api/library');
    if (!data) return;
    state.library = data;
    const pending = data.filter(i => !i.uploaded);

    // Filter by selected category: 'all', 'live', 'stream', 'longform', 'standard'
    const cat = state.publishCategory || 'all';
    let filtered = pending;
    if (cat === 'live') {
      filtered = pending.filter(i => i.source === 'live');
    } else if (cat === 'stream') {
      filtered = pending.filter(i => i.source === 'stream' || i.source === 'post_live');
    } else if (cat === 'longform') {
      filtered = pending.filter(i => i.source === 'longform');
    } else if (cat === 'standard') {
      filtered = pending.filter(i => i.source !== 'live' && i.source !== 'stream' && i.source !== 'post_live' && i.source !== 'longform');
    }

    const qCount = document.getElementById('queue-count');
    if (qCount) qCount.textContent = `${filtered.length} ready`;

    const container = document.getElementById('publish-grid-container');
    if (!container) return;

    // Custom Category Dropdown controller & sync
    const catDropdown = document.getElementById('publish-category-dropdown');
    const catBtn = document.getElementById('category-dropdown-btn');
    const catLabel = document.getElementById('category-dropdown-label');
    const catMenu = document.getElementById('category-dropdown-menu');
    const catSelect = document.getElementById('publish-category-filter');

    if (catDropdown && !catDropdown.dataset.bound) {
      catDropdown.dataset.bound = 'true';

      if (catBtn) {
        catBtn.addEventListener('click', (e) => {
          e.stopPropagation();
          const isOpen = catDropdown.classList.toggle('open');
          catBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        });
      }

      if (catMenu) {
        catMenu.addEventListener('click', (e) => {
          const item = e.target.closest('.custom-dropdown-item');
          if (!item) return;
          e.stopPropagation();
          const val = item.dataset.value || 'all';
          state.publishCategory = val;
          state.publishPage = 1;

          // Update active states
          catMenu.querySelectorAll('.custom-dropdown-item').forEach(el => {
            const isMatch = el.dataset.value === val;
            el.classList.toggle('active', isMatch);
            el.setAttribute('aria-selected', isMatch ? 'true' : 'false');
          });

          // Update trigger label
          const labelSpan = item.querySelector('span');
          if (catLabel && labelSpan) {
            catLabel.textContent = labelSpan.textContent;
          }

          if (catSelect) catSelect.value = val;
          catDropdown.classList.remove('open');
          if (catBtn) catBtn.setAttribute('aria-expanded', 'false');

          refreshPublishQueue();
        });
      }

      // Close on outside click
      document.addEventListener('click', (e) => {
        if (!catDropdown.contains(e.target)) {
          catDropdown.classList.remove('open');
          if (catBtn) catBtn.setAttribute('aria-expanded', 'false');
        }
      });

      // Close on ESC
      document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && catDropdown.classList.contains('open')) {
          catDropdown.classList.remove('open');
          if (catBtn) catBtn.setAttribute('aria-expanded', 'false');
        }
      });
    }

    // Sync label & active highlight with state
    const currentCat = state.publishCategory || 'all';
    if (catMenu) {
      catMenu.querySelectorAll('.custom-dropdown-item').forEach(el => {
        const isMatch = el.dataset.value === currentCat;
        el.classList.toggle('active', isMatch);
        el.setAttribute('aria-selected', isMatch ? 'true' : 'false');
        if (isMatch && catLabel) {
          const s = el.querySelector('span');
          if (s) catLabel.textContent = s.textContent;
        }
      });
    }
    if (catSelect) catSelect.value = currentCat;

    if (!filtered.length) {
      container.innerHTML = `
        <div class="card" style="padding:48px 24px; text-align:center; grid-column:1/-1;">
          <div class="quick-icon" style="margin:0 auto 12px auto; width:44px; height:44px;"><svg class="icon" style="width:22px; height:22px;"><use href="#i-film"/></svg></div>
          <h3 style="font-size:15px; font-weight:600; color:var(--text-primary);">No Shorts in this Category</h3>
          <p class="muted" style="margin-top:4px; font-size:13px;">No pending clips found for the selected filter.</p>
        </div>
      `;
      // Update top pagination to 1/1 disabled
      const topPageNum = document.getElementById('top-page-num');
      const topPageTotal = document.getElementById('top-page-total');
      const topPrev = document.getElementById('top-prev-btn');
      const topNext = document.getElementById('top-next-btn');
      if (topPageNum) topPageNum.textContent = '1';
      if (topPageTotal) topPageTotal.textContent = '/ 1';
      if (topPrev) topPrev.disabled = true;
      if (topNext) topNext.disabled = true;
      return;
    }

    // 4x3 Pagination: 4 columns x 3 rows = 12 cards max per page
    const pageSize = state.publishPageSize || 12;
    const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
    if (state.publishPage > totalPages) state.publishPage = totalPages;
    if (state.publishPage < 1) state.publishPage = 1;

    const startIndex = (state.publishPage - 1) * pageSize;
    const pagedItems = filtered.slice(startIndex, startIndex + pageSize);

    container.innerHTML = pagedItems.map(item => `
      <div class="publish-card" data-card-id="${item.id}">
        <!-- Delete Button in Top-Left Corner -->
        <button class="publish-btn-delete" data-delete-id="${item.id}" title="Delete Short from Supabase & database">
          <svg class="icon"><use href="#i-trash"/></svg>
        </button>

        <!-- Preview with Play Button Overlay -->
        <div class="publish-card-preview" data-watch-id="${item.id}">
          ${item.storageUrl ? `
            <video src="${escapeHtml(item.storageUrl)}" preload="metadata" muted playsinline></video>
          ` : `
            <div class="preview-fallback">
              <svg class="icon" style="width:28px; height:28px;"><use href="#i-film"/></svg>
              <span style="font-size:12px;">Stored in Cloud</span>
            </div>
          `}
          <!-- Centered Play Button -->
          <button class="publish-play-btn" data-watch-id="${item.id}" title="Watch video">
            <svg class="icon"><use href="#i-play"/></svg>
          </button>
          <span class="publish-card-badge">${formatDuration(item.duration)}</span>
        </div>

        <!-- Body -->
        <div class="publish-card-body">
          <div class="publish-card-title">${escapeHtml(item.title)}</div>
          ${item.sourceTitle ? `<div class="publish-card-source">${escapeHtml(item.sourceTitle)}</div>` : ''}
          <div class="publish-card-meta">
            <span class="chip-part-badge">Part ${item.part}/${item.parts}</span>
            ${item.score ? `<span class="chip-score-badge">${item.score}/10</span>` : ''}
            ${renderSourceBadge(item.source)}
          </div>
          <!-- Action: Live Loading Progress Bar OR Publish Button -->
          ${(() => {
        const up = state.activeUploads && state.activeUploads[item.id];
        if (up) {
          const isSuccess = up.status === 'success';
          const isError = up.status === 'error';
          const cls = isSuccess ? 'publish-card-progress success' : (isError ? 'publish-card-progress error' : 'publish-card-progress');
          const spinnerCls = isSuccess ? 'card-progress-spinner done' : (isError ? 'card-progress-spinner fail' : 'card-progress-spinner');
          const spinnerText = isSuccess ? '✓' : (isError ? '✗' : '');
          return `
                <div class="${cls}" id="card-progress-${item.id}">
                  <div class="card-progress-top">
                    <div class="card-progress-status">
                      <span class="${spinnerCls}" id="card-spinner-${item.id}">${spinnerText}</span>
                      <span class="card-progress-text" id="card-text-${item.id}">${escapeHtml(up.text || 'Uploading...')}</span>
                    </div>
                    <span class="card-progress-num" id="card-num-${item.id}">${up.percent || 15}%</span>
                  </div>
                  <div class="card-progress-track">
                    <div class="card-progress-fill" id="card-fill-${item.id}" style="width: ${up.percent || 15}%;"></div>
                  </div>
                </div>
              `;
        }
        return `
              <button class="publish-btn-quick" data-publish-id="${item.id}" title="Publish this Short to YouTube">
                <svg class="icon"><use href="#i-youtube"/></svg>Publish to YouTube
              </button>
            `;
      })()}
        </div>
      </div>
    `).join('');

    // Update Top Compact < 1 > Pagination Controls
    const topPageNum = document.getElementById('top-page-num');
    const topPageTotal = document.getElementById('top-page-total');
    const topPrev = document.getElementById('top-prev-btn');
    const topNext = document.getElementById('top-next-btn');

    if (topPageNum) topPageNum.textContent = String(state.publishPage);
    if (topPageTotal) topPageTotal.textContent = `/ ${totalPages}`;
    if (topPrev) {
      topPrev.disabled = state.publishPage <= 1;
      if (!topPrev.dataset.bound) {
        topPrev.dataset.bound = 'true';
        topPrev.addEventListener('click', () => {
          if (state.publishPage > 1) {
            state.publishPage--;
            refreshPublishQueue();
          }
        });
      }
    }
    if (topNext) {
      topNext.disabled = state.publishPage >= totalPages;
      if (!topNext.dataset.bound) {
        topNext.dataset.bound = 'true';
        topNext.addEventListener('click', () => {
          if (state.publishPage < totalPages) {
            state.publishPage++;
            refreshPublishQueue();
          }
        });
      }
    }

    // Wire up Watch triggers
    container.querySelectorAll('[data-watch-id]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(el.dataset.watchId, 10);
        const item = state.library.find(x => x.id === id);
        if (item) openVideoModal(item);
      });
    });

    // Wire up Delete triggers
    container.querySelectorAll('[data-delete-id]').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        const id = parseInt(el.dataset.deleteId, 10);
        const item = state.library.find(x => x.id === id);
        if (item) openDeleteModal(item);
      });
    });

    // Wire up one-click publish buttons to open Account Selection Pop-up
    container.querySelectorAll('.publish-btn-quick').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const shortId = parseInt(btn.dataset.publishId, 10);
        const item = state.library.find(x => x.id === shortId);
        openPublishAccountModal(shortId, item ? item.title : `Short #${shortId}`);
      });
    });

    // Wire up clicking card body to open details drawer
    container.querySelectorAll('.publish-card-body').forEach(body => {
      body.addEventListener('click', (e) => {
        if (e.target.closest('[data-watch-id]') || e.target.closest('[data-delete-id]')) return;
        const card = body.closest('.publish-card');
        const id = parseInt(card.dataset.cardId, 10);
        const item = state.library.find(x => x.id === id);
        if (item) openDrawer(item);
      });
    });
  }

  const pubNext = document.getElementById('publish-next');
  if (pubNext) {
    pubNext.addEventListener('click', async () => {
      try {
        const job = await apiPost('/api/run', { kind: 'upload_next' });
        toast('Upload job started', 'ok');
        attachJobToPanel('run-publish', job.id);
        openTerminalDrawer();
      } catch (e) { }
    });
  }

  const pubAll = document.getElementById('publish-all');
  if (pubAll) {
    pubAll.addEventListener('click', async () => {
      try {
        const job = await apiPost('/api/run', { kind: 'upload_all' });
        toast('Bulk upload job started', 'ok');
        attachJobToPanel('run-publish', job.id);
        openTerminalDrawer();
      } catch (e) { }
    });
  }

  // ─────────────────────────────────────────────────────────────
  // Create Section: 3-Mode Pipeline Selector
  // ─────────────────────────────────────────────────────────────
  state.createMode = 'standard'; // 'standard' | 'stream' | 'live'

  function initCreateModes() {
    const selector = document.getElementById('create-mode-selector');
    if (!selector) return;

    selector.addEventListener('click', (e) => {
      const btn = e.target.closest('.mode-btn[data-mode]');
      if (!btn) return;

      selector.querySelectorAll('.mode-btn').forEach(b => b.setAttribute('aria-checked', 'false'));
      btn.setAttribute('aria-checked', 'true');
      state.createMode = btn.dataset.mode;
      updateCreateModeUI();
    });
  }

  function updateCreateModeUI() {
    const badge = document.getElementById('mode-badge');
    const urlLabel = document.getElementById('create-url-label');
    const urlHint = document.getElementById('create-url-hint');
    const startText = document.getElementById('create-start-text');
    const liveControls = document.getElementById('create-live-controls');
    const stdControls = document.getElementById('create-standard-controls');
    const advanced = document.getElementById('create-advanced');
    const longformControls = document.getElementById('create-longform-controls');
    const montageControls = document.getElementById('create-montage-controls');

    const previewBox = document.getElementById('create-live-preview-box');
    const previewIframe = document.getElementById('create-live-preview-iframe');
    const customSceneSection = document.getElementById('create-custom-scene-section');

    const showCustomScene = (state.createMode === 'stream' || state.createMode === 'longform' || state.createMode === 'montage');
    if (customSceneSection) {
      customSceneSection.style.display = showCustomScene ? 'flex' : 'none';
    }

    if (state.createMode === 'standard') {
      if (badge) badge.innerHTML = '<svg class="icon" style="width:14px; height:14px; color:var(--accent-light); margin-right:6px;"><use href="#i-film"/></svg><span>Standard Video Mode · Snaps to natural sentences & clauses</span>';
      if (urlLabel) urlLabel.textContent = 'YouTube Video URL';
      if (urlHint) urlHint.textContent = 'Enter the video URL of another YouTuber to analyze and extract viral Shorts.';
      if (startText) startText.textContent = 'Start Clipping Video';
      if (liveControls) liveControls.style.display = 'none';
      if (stdControls) stdControls.style.display = 'flex';
      if (advanced) advanced.style.display = 'block';
      if (longformControls) longformControls.style.display = 'none';
      if (montageControls) montageControls.style.display = 'none';
      if (previewBox) previewBox.style.display = 'none';
    } else if (state.createMode === 'stream') {
      if (badge) badge.innerHTML = '<svg class="icon" style="width:14px; height:14px; color:#c084fc; margin-right:6px;"><use href="#i-video"/></svg><span>Post Livestream Mode · Dynamic up-to-120s extension + profanity bleeping</span>';
      if (urlLabel) urlLabel.textContent = 'Post-Livestream / Stream VOD URL';
      if (urlHint) urlHint.textContent = 'Enter the URL of an already streamed / concluded broadcast to extract highlight clips.';
      if (startText) startText.textContent = 'Start Clipping Post Livestream';
      if (liveControls) liveControls.style.display = 'none';
      if (stdControls) stdControls.style.display = 'flex';
      if (advanced) advanced.style.display = 'block';
      if (longformControls) longformControls.style.display = 'none';
      if (montageControls) montageControls.style.display = 'none';
      if (previewBox) previewBox.style.display = 'none';
    } else if (state.createMode === 'live') {
      if (badge) badge.innerHTML = '<span class="live-dot" style="width:8px; height:8px; border-radius:50%; background:#ff0033; display:inline-block; margin-right:6px;"></span><span style="color:#ff335c;">Monitor Live Stream · Autonomous agent cuts clips into livestream-shorts bucket</span>';
      if (urlLabel) urlLabel.textContent = 'Live Channel or Stream URL';
      if (urlHint) urlHint.textContent = 'Enter the channel or active livestream URL. Agent monitors and clips continuously.';
      if (startText) startText.textContent = 'Start Live Monitoring';
      if (liveControls) liveControls.style.display = 'flex';
      if (stdControls) stdControls.style.display = 'none';
      if (advanced) advanced.style.display = 'none';
      if (longformControls) longformControls.style.display = 'none';
      if (montageControls) montageControls.style.display = 'none';

      const pUrl = document.getElementById('process-url');
      if (pUrl && previewBox && previewIframe) {
        const vid = extractYouTubeVideoId(pUrl.value.trim());
        if (vid) {
          previewIframe.src = `https://www.youtube.com/embed/${vid}?autoplay=1&mute=1&enablejsapi=1`;
          previewBox.style.display = 'block';
        } else {
          previewBox.style.display = 'none';
        }
      }
    } else if (state.createMode === 'longform') {
      if (badge) badge.innerHTML = '<svg class="icon" style="width:14px; height:14px; color:var(--accent-light); margin-right:6px;"><use href="#i-film"/></svg><span>Video Edit Mode · 7 to 9 Minute Narrative Feature from Stream VOD</span>';
      if (urlLabel) urlLabel.textContent = 'Livestream VOD URL';
      if (urlHint) urlHint.textContent = 'Enter your completed livestream broadcast to edit into a high-retention 7-9 min YouTube video.';
      if (startText) startText.textContent = 'Generate 7-9m Feature Video';
      if (liveControls) liveControls.style.display = 'none';
      if (stdControls) stdControls.style.display = 'none';
      if (advanced) advanced.style.display = 'none';
      if (longformControls) longformControls.style.display = 'flex';
      if (montageControls) montageControls.style.display = 'none';
      if (previewBox) previewBox.style.display = 'none';
    } else if (state.createMode === 'montage') {
      if (badge) badge.innerHTML = '<svg class="icon" style="width:14px; height:14px; color:var(--accent-light); margin-right:6px;"><use href="#i-activity"/></svg><span>Viral Montage Mode · Peak audio spikes, 1.18x punch-ins &amp; dynamic pacing</span>';
      if (urlLabel) urlLabel.textContent = 'YouTube Video or Livestream URL';
      if (urlHint) urlHint.textContent = 'Enter any YouTube livestream, VOD, or video to extract peak reaction moments into an automated montage.';
      if (startText) startText.textContent = 'Build Viral Montage';
      if (liveControls) liveControls.style.display = 'none';
      if (stdControls) stdControls.style.display = 'none';
      if (advanced) advanced.style.display = 'none';
      if (longformControls) longformControls.style.display = 'none';
      if (montageControls) montageControls.style.display = 'flex';
      if (previewBox) previewBox.style.display = 'none';
    }
  }

  // Connect live character counter for custom prompt
  const customPromptEl = document.getElementById('custom-prompt-input');
  const customPromptCounterEl = document.getElementById('custom-prompt-counter');
  if (customPromptEl && customPromptCounterEl) {
    customPromptEl.addEventListener('input', () => {
      customPromptCounterEl.textContent = `${customPromptEl.value.length} / 300`;
    });
  }

  // Connect Custom AI Search Engine Dropdown
  const engineDropdown = document.getElementById('custom-engine-dropdown');
  const engineBtn = document.getElementById('custom-engine-btn');
  const engineMenu = document.getElementById('custom-engine-menu');
  const engineLabel = document.getElementById('custom-engine-label');
  const engineHidden = document.getElementById('custom-search-engine');
  const engineHint = document.getElementById('custom-engine-hint');

  const engineHints = {
    both: 'Combines TwelveLabs spatio-temporal action embeddings with Whisper transcripts & audio peak energy.',
    hybrid: 'Option 1: Correlates Whisper transcripts, audio RMS energy spikes, and Gemini vision reasoning.',
    twelvelabs: 'Option 2: Deep physical motion vector and spatio-temporal action search via TwelveLabs video AI.'
  };

  if (engineBtn && engineDropdown) {
    engineBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isOpen = engineDropdown.classList.toggle('open');
      engineBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
    });

    if (engineMenu) {
      engineMenu.addEventListener('click', (e) => {
        const item = e.target.closest('.custom-dropdown-item');
        if (!item) return;
        e.stopPropagation();
        const val = item.dataset.value || 'both';

        if (engineHidden) engineHidden.value = val;

        engineMenu.querySelectorAll('.custom-dropdown-item').forEach(el => {
          const isMatch = el.dataset.value === val;
          el.classList.toggle('active', isMatch);
          el.setAttribute('aria-selected', isMatch ? 'true' : 'false');
        });

        const titleSpan = item.querySelector('span');
        if (engineLabel && titleSpan) {
          engineLabel.innerHTML = `<svg class="icon" style="width: 15px; height: 15px; color: var(--accent);"><use href="#i-sliders" /></svg><span>${titleSpan.textContent}</span>`;
        }

        if (engineHint && engineHints[val]) {
          engineHint.textContent = engineHints[val];
        }

        engineDropdown.classList.remove('open');
        engineBtn.setAttribute('aria-expanded', 'false');
      });
    }

    document.addEventListener('click', (e) => {
      if (engineDropdown && !engineDropdown.contains(e.target)) {
        engineDropdown.classList.remove('open');
        engineBtn.setAttribute('aria-expanded', 'false');
      }
    });
  }

  const formProcess = document.getElementById('form-process');
  if (formProcess) {
    formProcess.addEventListener('submit', async (e) => {
      e.preventDefault();
      const url = document.getElementById('process-url').value.trim();
      if (!url) {
        toast('Please enter a YouTube URL', 'error');
        return;
      }

      const customPrompt = document.getElementById('custom-prompt-input') ? document.getElementById('custom-prompt-input').value.trim() : '';
      const customSearchEngine = document.getElementById('custom-search-engine') ? document.getElementById('custom-search-engine').value : 'both';

      if (state.createMode === 'live') {
        const liveMode = getSegmentedValue('create-live-mode') || 'continuous';
        const options = {
          url,
          once: liveMode === 'once',
          chunk: getStepperValue('create-live-chunk') || 150,
          poll: getStepperValue('create-live-poll') || 45,
          maxClips: 0,
          crop: getSegmentedValue('process-crop') || 'blurred_background',
          autoUpload: document.getElementById('process-autoupload').checked,
          enableCaptions: document.getElementById('process-enable-captions') ? document.getElementById('process-enable-captions').checked : false,
          noBleep: document.getElementById('process-nobleep') ? document.getElementById('process-nobleep').checked : false,
        };

        try {
          const job = await apiPost('/api/run', { kind: 'monitor', options });
          toast('Live stream monitoring started', 'ok');
          attachJobToPanel('run-process', job.id);
        } catch (err) { }
      } else if (state.createMode === 'longform') {
        const targetRuntime = parseInt(getSegmentedValue('longform-runtime-selector') || '480', 10);
        let focusTimestamp = 4210.0;
        const focusInput = document.getElementById('longform-focus-ts');
        if (focusInput && focusInput.value.trim()) {
          const val = focusInput.value.trim();
          if (val.includes(':')) {
            const parts = val.split(':').map(Number);
            if (parts.length === 3) focusTimestamp = parts[0] * 3600 + parts[1] * 60 + parts[2];
            else if (parts.length === 2) focusTimestamp = parts[0] * 60 + parts[1];
          } else {
            focusTimestamp = parseFloat(val) || 0.0;
          }
        }
        const options = {
          url,
          targetRuntime,
          focusTimestamp,
          prompt: customPrompt,
          searchEngine: customSearchEngine,
        };
        try {
          const job = await apiPost('/api/run', { kind: 'longform', options });
          toast('7–9m Longform video editing started!', 'ok');
          attachJobToPanel('run-process', job.id);
        } catch (err) { }
      } else if (state.createMode === 'montage') {
        const creator = document.getElementById('montage-creator') ? document.getElementById('montage-creator').value : 'ishowspeed';
        const targetRuntime = parseInt(getSegmentedValue('montage-runtime-selector') || '720', 10);
        const clipCount = getStepperValue('montage-clip-count') || 12;
        const options = {
          url,
          creator,
          targetRuntime,
          clipCount,
          upload: false,
          prompt: customPrompt,
          searchEngine: customSearchEngine,
        };
        try {
          const job = await apiPost('/api/run', { kind: 'montage', options });
          toast('Viral Montage generation started!', 'ok');
          attachJobToPanel('run-process', job.id);
        } catch (err) { }
      } else {
        const isStreamMode = state.createMode === 'stream';
        const options = {
          url,
          crop: getSegmentedValue('process-crop') || 'blurred_background',
          clips: getStepperValue('process-clips') || 3,
          autoUpload: document.getElementById('process-autoupload').checked,
          streamMode: isStreamMode,
          enableCaptions: document.getElementById('process-enable-captions') ? document.getElementById('process-enable-captions').checked : false,
          noBleep: document.getElementById('process-nobleep').checked,
          keepRaw: document.getElementById('process-keepraw').checked,
          model: document.getElementById('process-model').value || 'base',
          prompt: customPrompt,
          searchEngine: customSearchEngine,
        };

        try {
          const job = await apiPost('/api/run', { kind: 'process', options });
          toast(`${isStreamMode ? 'Stream VOD' : 'Normal video'} clipping started`, 'ok');
          attachJobToPanel('run-process', job.id);
        } catch (err) { }
      }
    });
  }

  // ─────────────────────────────────────────────────────────────
  // Longform Feature Video Showcase & Playback
  // ─────────────────────────────────────────────────────────────
  async function refreshLongformVideos() {
    const list = document.getElementById('longform-video-list');
    if (!list) return;

    try {
      const items = await apiGet('/api/editor/list');
      if (!items || !items.length) {
        list.innerHTML = `
          <div class="muted" style="padding:32px; text-align:center;">
            <svg class="icon" style="width:28px; height:28px; opacity:0.3; margin-bottom:6px;"><use href="#i-film"/></svg>
            <div>No feature videos generated yet. Click "Generate 7-9m Feature Video" above to create your first video!</div>
          </div>
        `;
        return;
      }

      list.innerHTML = items.map(item => {
        const chaptersHtml = (item.chapters || []).map(ch => {
          const parts = ch.split(' - ');
          const time = parts[0] || '';
          const title = parts.slice(1).join(' - ') || '';
          return `
            <div class="longform-chapter-line">
              <span class="longform-chapter-time">${escapeHtml(time)}</span>
              <span>${escapeHtml(title)}</span>
            </div>
          `;
        }).join('');

        return `
          <div class="longform-video-card">
            <div class="longform-card-top">
              <div class="longform-card-title-wrap">
                <div class="longform-card-title">${escapeHtml(item.title)}</div>
                <div class="longform-card-chips">
                  <span class="chip chip-scheduled">
                    <svg class="icon chip-icon"><use href="#i-clock"/></svg>
                    <span>${escapeHtml(item.duration)}</span>
                  </span>
                  <span class="chip chip-quiet">${escapeHtml(item.size_mb)} MB</span>
                  <span class="chip chip-ok">YouTube -14 LUFS Mastered</span>
                  <span class="chip chip-quiet">1080p 16:9</span>
                </div>
              </div>
              <div class="longform-card-actions">
                <button type="button" class="btn btn-primary btn-sm" onclick="window.shortsAppPlayLongform('${escapeHtml(item.title)}', '${escapeHtml(item.video_url)}', '${escapeHtml(item.duration)}')">
                  <svg class="icon"><use href="#i-play"/></svg>Play Feature Video
                </button>
              </div>
            </div>

            ${chaptersHtml ? `
              <div class="longform-chapters-box">
                <div style="font-weight:600; font-size:11px; text-transform:uppercase; color:var(--text-primary); letter-spacing:0.05em; margin-bottom:2px;">
                  Narrative Acts & Chapters (AVD Optimized)
                </div>
                ${chaptersHtml}
              </div>
            ` : ''}
          </div>
        `;
      }).join('');
    } catch (e) {
      list.innerHTML = `<div class="muted" style="padding:20px; text-align:center;">Failed to load feature videos</div>`;
    }
  }

  window.shortsAppPlayLongform = function (title, url, dur) {
    const item = {
      title,
      isLongform: true,
      part: 1,
      parts: 1,
      score: 10,
      duration: dur || '8:00',
      videoSrc: url,
    };
    openVideoModal(item);
  };

  // System maintenance buttons
  document.querySelectorAll('button[data-run]').forEach(btn => {
    btn.addEventListener('click', async () => {
      const kind = btn.dataset.run;
      try {
        const job = await apiPost('/api/run', { kind });
        toast(`Started ${kind}`, 'ok');
        attachJobToPanel('run-system', job.id);
      } catch (err) { }
    });
  });

  // ─────────────────────────────────────────────────────────────
  // 3-Word Status Engine & Real-time Console Drawer
  // ─────────────────────────────────────────────────────────────
  function get3WordStatus(job) {
    if (!job) return 'Starting Pipeline Workflow...';
    const prog = job.clipProgress;
    if (job.status === 'done') {
      const tot = (prog && prog.total) ? ` (${prog.total}/${prog.total} Done)` : '';
      return `All Videos Completed${tot}!`;
    }
    if (job.status === 'failed') return 'Pipeline Execution Failed';
    if (job.status === 'stopped') return 'Pipeline Execution Stopped';

    const stages = job.stages || [];
    const current = stages.find(s => !s.done) || (stages.length ? stages[stages.length - 1] : null);

    // If multi-clip is active, show clip specific action
    if (prog && prog.total > 1 && current && current.num >= 3) {
      const cur = prog.current || (prog.done + 1);
      switch (current.num) {
        case 3: return `Transcribing Clip ${cur}/${prog.total}...`;
        case 4: return `Clipping Video ${cur}/${prog.total}...`;
        case 5: return `Reframing Clip ${cur}/${prog.total}...`;
        case 6: return `Subtitling Clip ${cur}/${prog.total}...`;
        case 7: return `Storing Clip ${cur}/${prog.total}...`;
        default: break;
      }
    }

    if (current) {
      switch (current.num) {
        case 1: return 'Ingesting Video Audio...';
        case 2: return 'Scanning Audio Peaks...';
        case 3: return 'Transcribing Speech Audio...';
        case 4: return 'Detecting Viral Moments...';
        case 5: return 'Reframing Vertical Video...';
        case 6: return 'Burning Word Captions...';
        case 7: return 'Syncing Cloud Storage...';
        default: break;
      }
    }

    const last = (job.lastLine || '').toLowerCase();
    if (last.includes('upload') || last.includes('publishing')) {
      return 'Publishing To YouTube...';
    }

    if (job.kind === 'monitor') {
      return 'Monitoring Live Stream...';
    }

    return 'Running Pipeline Workflow...';
  }

  function openTerminalDrawer() {
    const drawer = document.getElementById('terminal-drawer');
    const scrim = document.getElementById('terminal-drawer-scrim');
    if (drawer) drawer.classList.add('open');
    if (scrim) scrim.classList.add('open');
  }

  function closeTerminalDrawer() {
    const drawer = document.getElementById('terminal-drawer');
    const scrim = document.getElementById('terminal-drawer-scrim');
    if (drawer) drawer.classList.remove('open');
    if (scrim) scrim.classList.remove('open');
  }

  function initTerminalDrawer() {
    const btnToggle = document.getElementById('btn-toggle-terminal-drawer');
    if (btnToggle && !btnToggle.dataset.bound) {
      btnToggle.dataset.bound = 'true';
      btnToggle.addEventListener('click', (e) => {
        e.preventDefault();
        openTerminalDrawer();
      });
    }

    const btnClose = document.getElementById('terminal-drawer-close');
    if (btnClose && !btnClose.dataset.bound) {
      btnClose.dataset.bound = 'true';
      btnClose.addEventListener('click', () => closeTerminalDrawer());
    }

    const scrim = document.getElementById('terminal-drawer-scrim');
    if (scrim && !scrim.dataset.bound) {
      scrim.dataset.bound = 'true';
      scrim.addEventListener('click', () => closeTerminalDrawer());
    }

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeTerminalDrawer();
      }
    });

    const copyBtn = document.getElementById('terminal-drawer-copy');
    if (copyBtn && !copyBtn.dataset.bound) {
      copyBtn.dataset.bound = 'true';
      copyBtn.addEventListener('click', () => {
        const consoleEl = document.getElementById('terminal-drawer-console');
        if (!consoleEl) return;
        const text = Array.from(consoleEl.querySelectorAll('.log-text')).map(n => n.textContent).join('\n');
        navigator.clipboard.writeText(text).then(() => toast('Terminal logs copied to clipboard', 'ok'));
      });
    }

    const resetBtn = document.getElementById('btn-workflow-reset');
    if (resetBtn && !resetBtn.dataset.bound) {
      resetBtn.dataset.bound = 'true';
      resetBtn.addEventListener('click', () => {
        resetCreateWorkflowToDefault();
      });
    }
  }

  function resetCreateWorkflowToDefault() {
    if (state.activeJobPolling['run-process']) {
      if (state.activeJobPolling['run-process'].timer) {
        clearTimeout(state.activeJobPolling['run-process'].timer);
      }
      delete state.activeJobPolling['run-process'];
    }

    const activeProgress = document.getElementById('workflow-active-progress');
    const startBtn = document.getElementById('process-start');
    const completedActions = document.getElementById('workflow-completed-actions');
    const stopBtn = document.getElementById('btn-workflow-stop');
    const barFill = document.getElementById('workflow-bar-fill');
    const pulseRing = document.getElementById('workflow-pulse-ring');
    const statusText = document.getElementById('workflow-3word-status');
    const stageDetail = document.getElementById('workflow-stage-detail');
    const pctLabel = document.getElementById('workflow-pct-label');

    if (activeProgress) activeProgress.style.display = 'none';
    if (startBtn) {
      startBtn.style.display = 'flex';
      startBtn.disabled = false;
    }
    if (completedActions) completedActions.style.display = 'none';
    if (stopBtn) {
      stopBtn.style.display = 'none';
      stopBtn.disabled = false;
    }
    if (barFill) {
      barFill.className = 'workflow-bar-fill';
      barFill.style.width = '0%';
    }
    if (pulseRing) pulseRing.className = 'status-pulse-ring';
    if (statusText) statusText.textContent = 'Starting Pipeline Workflow...';
    if (stageDetail) stageDetail.textContent = 'Stage 1 of 7 · Ingesting Video Audio';
    if (pctLabel) pctLabel.textContent = '0%';

    const drawerStopBtn = document.getElementById('terminal-drawer-stop-btn');
    if (drawerStopBtn) drawerStopBtn.style.display = 'none';
  }

  function attachJobToPanel(panelId, jobId) {
    // Clear prior timer for this panel
    if (state.activeJobPolling[panelId]) {
      clearTimeout(state.activeJobPolling[panelId].timer);
    }

    state.activeJobPolling[panelId] = {
      jobId,
      afterSeq: 0,
      timer: null,
      autoScroll: true,
    };

    if (panelId === 'run-process') {
      const activeProgress = document.getElementById('workflow-active-progress');
      const startBtn = document.getElementById('process-start');
      const completedActions = document.getElementById('workflow-completed-actions');
      const stopBtn = document.getElementById('btn-workflow-stop');
      const drawerStopBtn = document.getElementById('terminal-drawer-stop-btn');

      if (activeProgress) activeProgress.style.display = 'block';
      if (startBtn) startBtn.style.display = 'none';
      if (completedActions) completedActions.style.display = 'none';
      if (stopBtn) {
        stopBtn.style.display = 'inline-flex';
        stopBtn.disabled = false;
        stopBtn.onclick = async () => {
          stopBtn.disabled = true;
          try {
            await apiPost(`/api/jobs/${jobId}/stop`, {});
          } catch (e) { }
          toast('Pipeline stopped', 'info');
          resetCreateWorkflowToDefault();
        };
      }
      if (drawerStopBtn) {
        drawerStopBtn.style.display = 'inline-flex';
        drawerStopBtn.disabled = false;
        drawerStopBtn.onclick = async () => {
          drawerStopBtn.disabled = true;
          try {
            await apiPost(`/api/jobs/${jobId}/stop`, {});
          } catch (e) { }
          toast('Pipeline stopped', 'info');
          resetCreateWorkflowToDefault();
        };
      }

      // Reset progress bar elements
      const barFill = document.getElementById('workflow-bar-fill');
      const pulseRing = document.getElementById('workflow-pulse-ring');
      const statusText = document.getElementById('workflow-3word-status');
      const stageDetail = document.getElementById('workflow-stage-detail');
      const pctLabel = document.getElementById('workflow-pct-label');

      if (barFill) {
        barFill.className = 'workflow-bar-fill';
        barFill.style.width = '8%';
      }
      if (pulseRing) pulseRing.className = 'status-pulse-ring';
      if (statusText) statusText.textContent = 'Starting Pipeline Workflow...';
      if (stageDetail) stageDetail.textContent = 'Initializing pipeline...';
      if (pctLabel) pctLabel.textContent = '8%';

      // Clear drawer elements
      const drawerConsole = document.getElementById('terminal-drawer-console');
      const drawerStages = document.getElementById('terminal-drawer-stages');
      const drawerTitle = document.getElementById('terminal-drawer-title');
      const drawerChip = document.getElementById('terminal-drawer-chip');
      const drawer3Words = document.getElementById('terminal-drawer-3words');
      const drawerPct = document.getElementById('terminal-drawer-pct');

      if (drawerConsole) drawerConsole.innerHTML = '';
      if (drawerStages) drawerStages.innerHTML = '';
      if (drawerTitle) drawerTitle.textContent = `Pipeline · ${jobId}`;
      if (drawerChip) {
        drawerChip.textContent = 'running';
        drawerChip.className = 'chip';
      }
      if (drawer3Words) drawer3Words.textContent = 'Starting Pipeline Workflow...';
      if (drawerPct) drawerPct.textContent = '8%';
    } else if (panelId === 'run-publish') {
      const drawerConsole = document.getElementById('terminal-drawer-console');
      const drawerStages = document.getElementById('terminal-drawer-stages');
      const drawerTitle = document.getElementById('terminal-drawer-title');
      const drawerChip = document.getElementById('terminal-drawer-chip');
      const drawerStopBtn = document.getElementById('terminal-drawer-stop-btn');

      if (drawerConsole) drawerConsole.innerHTML = '';
      if (drawerStages) drawerStages.innerHTML = '';
      if (drawerTitle) drawerTitle.textContent = `Upload Job · ${jobId}`;
      if (drawerChip) {
        drawerChip.textContent = 'running';
        drawerChip.className = 'chip';
      }
      if (drawerStopBtn) {
        drawerStopBtn.style.display = 'inline-flex';
        drawerStopBtn.disabled = false;
        drawerStopBtn.onclick = async () => {
          drawerStopBtn.disabled = true;
          await apiPost(`/api/jobs/${jobId}/stop`, {});
          toast('Upload job stopped', 'info');
        };
      }
    } else {
      const panel = document.getElementById(panelId);
      if (panel) renderJobSkeleton(panel, jobId);
    }

    pollJob(panelId);
  }

  function renderJobSkeleton(panel, jobId) {
    panel.innerHTML = `
      <div class="job-card" id="card-${jobId}">
        <div class="job-head">
          <div class="job-title">
            <svg class="icon"><use href="#i-activity"/></svg>
            <span id="job-label-${jobId}">Starting process...</span>
          </div>
          <div class="job-actions">
            <span class="chip" id="job-chip-${jobId}">running</span>
            <button class="btn btn-ghost" style="padding:4px 8px;" id="job-copy-${jobId}" title="Copy logs">
              <svg class="icon"><use href="#i-copy"/></svg>
            </button>
            <button class="btn btn-danger" style="padding:4px 8px;" id="job-stop-${jobId}" title="Stop process">
              <svg class="icon"><use href="#i-stop"/></svg>Stop
            </button>
          </div>
        </div>
        <div class="stages-flow" id="stages-${jobId}" style="display:none;"></div>
        <div class="console" id="console-${jobId}"></div>
      </div>
    `;

    // Stop button
    const stopBtn = document.getElementById(`job-stop-${jobId}`);
    if (stopBtn) {
      stopBtn.addEventListener('click', async () => {
        stopBtn.disabled = true;
        await apiPost(`/api/jobs/${jobId}/stop`, {});
        toast('Process stopping...', 'warn');
      });
    }

    // Copy logs button
    const copyBtn = document.getElementById(`job-copy-${jobId}`);
    if (copyBtn) {
      copyBtn.addEventListener('click', () => {
        const consoleEl = document.getElementById(`console-${jobId}`);
        if (!consoleEl) return;
        const text = Array.from(consoleEl.querySelectorAll('.log-text')).map(n => n.textContent).join('\n');
        navigator.clipboard.writeText(text).then(() => toast('Logs copied to clipboard', 'ok'));
      });
    }
  }

  async function pollJob(panelId) {
    const ctx = state.activeJobPolling[panelId];
    if (!ctx) return;

    const data = await apiGet(`/api/jobs/${ctx.jobId}/log?after=${ctx.afterSeq}`);
    if (!data || !data.job) {
      ctx.timer = setTimeout(() => pollJob(panelId), 1500);
      return;
    }

    const { job, lines } = data;

    if (panelId === 'run-process') {
      const words3 = get3WordStatus(job);
      const stages = job.stages || [];
      const current = stages.find(s => !s.done) || (stages.length ? stages[stages.length - 1] : null);
      const stageNum = current ? current.num : 1;
      const stageTitle = current ? current.title : 'Ingestion';

      const prog = job.clipProgress;

      let pct = 8;
      let pctLabel = '8%';
      let stageDetail = 'Initializing pipeline...';

      if (job.status === 'done') {
        pct = 100;
        pctLabel = '100%';
        const tot = (prog && prog.total) ? `${prog.total}/${prog.total} videos done` : 'All clips completed';
        stageDetail = `${tot} and stored in library.`;
      } else if (job.status === 'failed') {
        pctLabel = 'Failed';
        stageDetail = `Pipeline execution failed at stage ${stageNum}`;
      } else if (job.status === 'stopped') {
        resetCreateWorkflowToDefault();
        return;
      } else {
        // Multi-clip weighted progress calculation
        if (prog && prog.total > 0) {
          const totalClips = prog.total;
          const doneClips = prog.done || 0;
          let clipFraction = 0;
          if (stageNum <= 2) {
            clipFraction = (stageNum / 2) * 0.15;
          } else {
            clipFraction = ((stageNum - 2) / 5);
          }
          const overallFraction = (doneClips + Math.min(0.95, clipFraction)) / totalClips;
          pct = Math.min(98, Math.max(10, Math.round(overallFraction * 100)));
          pctLabel = `${pct}%`;

          const doneText = `${doneClips}/${totalClips} videos done`;
          stageDetail = `${doneText} · Stage ${stageNum} of 7 (${stageTitle})`;
        } else {
          pct = Math.min(95, Math.max(10, Math.round((stageNum / 7) * 100)));
          pctLabel = `${pct}%`;
          stageDetail = `Stage ${stageNum} of 7 · ${stageTitle}`;
        }
      }

      // Update in-div workflow progress bar
      const barFill = document.getElementById('workflow-bar-fill');
      const pulseRing = document.getElementById('workflow-pulse-ring');
      const statusText = document.getElementById('workflow-3word-status');
      const stageDetailEl = document.getElementById('workflow-stage-detail');
      const pctLabelEl = document.getElementById('workflow-pct-label');
      const stopBtn = document.getElementById('btn-workflow-stop');
      const completedActions = document.getElementById('workflow-completed-actions');
      const clipsCounterBadge = document.getElementById('workflow-clips-counter');

      if (statusText) statusText.textContent = words3;
      if (pctLabelEl) pctLabelEl.textContent = pctLabel;
      if (stageDetailEl) stageDetailEl.textContent = stageDetail;

      // Update clips counter badge
      if (clipsCounterBadge) {
        if (prog && prog.total > 0 && job.status === 'running') {
          clipsCounterBadge.style.display = 'inline-block';
          clipsCounterBadge.textContent = `${prog.done}/${prog.total} videos done`;
          clipsCounterBadge.className = prog.done > 0 ? 'chip chip-ok' : 'chip chip-warn';
        } else if (job.status === 'done' && prog && prog.total > 0) {
          clipsCounterBadge.style.display = 'inline-block';
          clipsCounterBadge.textContent = `${prog.total}/${prog.total} videos done`;
          clipsCounterBadge.className = 'chip chip-ok';
        } else {
          clipsCounterBadge.style.display = 'none';
        }
      }

      // Drawer clips counter badge
      const drawerClipsCounter = document.getElementById('terminal-drawer-clips-counter');
      if (drawerClipsCounter) {
        if (prog && prog.total > 0) {
          drawerClipsCounter.style.display = 'inline-block';
          drawerClipsCounter.textContent = `${prog.done}/${prog.total} videos done`;
          drawerClipsCounter.className = prog.done > 0 ? 'chip chip-ok chip-sm' : 'chip chip-warn chip-sm';
        } else {
          drawerClipsCounter.style.display = 'none';
        }
      }

      if (barFill) {
        barFill.style.width = `${pct}%`;
        if (job.status === 'done') barFill.className = 'workflow-bar-fill done';
        else if (job.status === 'failed' || job.status === 'stopped') barFill.className = 'workflow-bar-fill error';
        else barFill.className = 'workflow-bar-fill';
      }
      if (pulseRing) {
        if (job.status === 'done') pulseRing.className = 'status-pulse-ring done';
        else if (job.status === 'failed' || job.status === 'stopped') pulseRing.className = 'status-pulse-ring error';
        else pulseRing.className = 'status-pulse-ring';
      }
      if (job.status !== 'running') {
        if (stopBtn) stopBtn.style.display = 'none';
        if (completedActions) completedActions.style.display = 'flex';
      }

      // Update drawer elements
      const drawerTitle = document.getElementById('terminal-drawer-title');
      const drawerChip = document.getElementById('terminal-drawer-chip');
      const drawerStopBtn = document.getElementById('terminal-drawer-stop-btn');
      const drawer3Words = document.getElementById('terminal-drawer-3words');
      const drawerPct = document.getElementById('terminal-drawer-pct');
      const drawerPulseRing = document.getElementById('terminal-drawer-pulse-ring');

      if (drawerTitle) drawerTitle.textContent = `${job.label} · ${job.target || job.id}`;
      if (drawerChip) {
        drawerChip.textContent = job.status;
        if (job.status === 'running') drawerChip.className = 'chip';
        else if (job.status === 'done') drawerChip.className = 'chip chip-ok';
        else drawerChip.className = 'chip chip-error';
      }
      if (drawer3Words) drawer3Words.textContent = words3;
      if (drawerPct) drawerPct.textContent = pctLabel;
      if (drawerPulseRing) {
        if (job.status === 'done') drawerPulseRing.className = 'status-pulse-ring done';
        else if (job.status === 'failed' || job.status === 'stopped') drawerPulseRing.className = 'status-pulse-ring error';
        else drawerPulseRing.className = 'status-pulse-ring';
      }
      if (drawerStopBtn && job.status !== 'running') {
        drawerStopBtn.style.display = 'none';
      }

      // Render stages into drawer
      renderDrawerStages(job);

      // Append logs into drawer console
      if (lines && lines.length > 0) {
        appendDrawerLogs(lines, ctx);
      }
    } else if (panelId === 'run-publish') {
      const drawerTitle = document.getElementById('terminal-drawer-title');
      const drawerChip = document.getElementById('terminal-drawer-chip');
      const drawerStopBtn = document.getElementById('terminal-drawer-stop-btn');

      if (drawerTitle) drawerTitle.textContent = `${job.label} · ${job.target || job.id}`;
      if (drawerChip) {
        drawerChip.textContent = job.status;
        if (job.status === 'running') drawerChip.className = 'chip';
        else if (job.status === 'done') drawerChip.className = 'chip chip-ok';
        else drawerChip.className = 'chip chip-error';
      }
      if (drawerStopBtn && job.status !== 'running') {
        drawerStopBtn.style.display = 'none';
      }
      renderDrawerStages(job);
      if (lines && lines.length > 0) {
        appendDrawerLogs(lines, ctx);
      }
    } else {
      // Legacy panel (system view)
      const labelEl = document.getElementById(`job-label-${job.id}`);
      const chipEl = document.getElementById(`job-chip-${job.id}`);
      const stopBtn = document.getElementById(`job-stop-${job.id}`);

      if (labelEl) labelEl.textContent = `${job.label} · ${job.target || job.id}`;
      if (chipEl) {
        chipEl.textContent = job.status;
        if (job.status === 'running') chipEl.className = 'chip';
        else if (job.status === 'done') chipEl.className = 'chip chip-ok';
        else chipEl.className = 'chip chip-error';
      }
      if (stopBtn && job.status !== 'running') {
        stopBtn.style.display = 'none';
      }
      renderStages(job);
      if (lines && lines.length > 0) {
        appendLogs(job.id, lines, ctx);
      }
    }

    // Continue polling if still running
    if (job.status === 'running') {
      ctx.timer = setTimeout(() => pollJob(panelId), 800);
    } else {
      setTimeout(() => {
        refreshOverview();
        refreshLibrary();
        refreshPublishQueue();
      }, 1000);
    }
  }

  function renderDrawerStages(job) {
    const container = document.getElementById('terminal-drawer-stages');
    if (!container) return;
    if (!job.stages || !job.stages.length) {
      container.style.display = 'none';
      return;
    }
    container.style.display = 'flex';
    container.innerHTML = job.stages.map((st, idx) => {
      const isDone = st.done;
      const isCurrent = !isDone && (idx === job.stages.length - 1 && job.status === 'running');
      const cls = isDone ? 'stage-step done' : (isCurrent ? 'stage-step active' : 'stage-step');
      return `
        <div class="${cls}">
          <div class="stage-num">${isDone ? '✓' : st.num}</div>
          <div><strong>Stage ${st.num}: ${escapeHtml(st.title)}</strong> ${st.detail ? `<span class="muted">– ${escapeHtml(st.detail)}</span>` : ''}</div>
        </div>
      `;
    }).join('');
  }

  function appendDrawerLogs(lines, ctx) {
    const consoleEl = document.getElementById('terminal-drawer-console');
    if (!consoleEl) return;
    const isAtBottom = (consoleEl.scrollHeight - consoleEl.scrollTop) <= (consoleEl.clientHeight + 40);
    const frag = document.createDocumentFragment();
    for (const l of lines) {
      ctx.afterSeq = Math.max(ctx.afterSeq, l.n);
      const row = document.createElement('div');
      row.className = 'log-line';
      row.innerHTML = `<span class="log-num">${l.n}</span><span class="log-text ${l.l}">${escapeHtml(l.t)}</span>`;
      frag.appendChild(row);
    }
    consoleEl.appendChild(frag);
    if (isAtBottom) {
      consoleEl.scrollTop = consoleEl.scrollHeight;
    }
  }

  function renderStages(job) {
    const container = document.getElementById(`stages-${job.id}`);
    if (!container) return;
    if (!job.stages || !job.stages.length) {
      container.style.display = 'none';
      return;
    }
    container.style.display = 'flex';
    container.innerHTML = job.stages.map((st, idx) => {
      const isDone = st.done;
      const isCurrent = !isDone && (idx === job.stages.length - 1 && job.status === 'running');
      const cls = isDone ? 'stage-step done' : (isCurrent ? 'stage-step active' : 'stage-step');
      return `
        <div class="${cls}">
          <div class="stage-num">${isDone ? '✓' : st.num}</div>
          <div><strong>Stage ${st.num}: ${escapeHtml(st.title)}</strong> ${st.detail ? `<span class="muted">– ${escapeHtml(st.detail)}</span>` : ''}</div>
        </div>
      `;
    }).join('');
  }

  function appendLogs(jobId, lines, ctx) {
    const consoleEl = document.getElementById(`console-${jobId}`);
    if (!consoleEl) return;

    // Detect if user has scrolled up
    const isAtBottom = (consoleEl.scrollHeight - consoleEl.scrollTop) <= (consoleEl.clientHeight + 40);

    const frag = document.createDocumentFragment();
    for (const l of lines) {
      ctx.afterSeq = Math.max(ctx.afterSeq, l.n);
      const row = document.createElement('div');
      row.className = 'log-line';
      row.innerHTML = `<span class="log-num">${l.n}</span><span class="log-text ${l.l}">${escapeHtml(l.t)}</span>`;
      frag.appendChild(row);
    }
    consoleEl.appendChild(frag);

    if (isAtBottom) {
      consoleEl.scrollTop = consoleEl.scrollHeight;
    }
  }

  // ─────────────────────────────────────────────────────────────
  // ─────────────────────────────────────────────────────────────
  // Topbar Notification & Activity Dropdown
  // ─────────────────────────────────────────────────────────────
  function initNotificationsBar() {
    const btn = el.topbarActivityBtn;
    const dropdown = el.activityDropdown;
    const btnRefresh = el.activityDropdownRefresh;
    const btnClose = el.activityDropdownClose;
    const btnTerminal = el.btnOpenTerminalFromActivity;

    if (!btn || !dropdown) return;

    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const isHidden = dropdown.hidden;
      dropdown.hidden = !isHidden;
      btn.classList.toggle('active', !dropdown.hidden);
      if (!dropdown.hidden) {
        refreshActivityDropdown();
      }
    });

    if (btnRefresh) {
      btnRefresh.addEventListener('click', (e) => {
        e.stopPropagation();
        refreshActivityDropdown();
      });
    }

    if (btnClose) {
      btnClose.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdown.hidden = true;
        btn.classList.remove('active');
      });
    }

    if (btnTerminal) {
      btnTerminal.addEventListener('click', (e) => {
        e.stopPropagation();
        dropdown.hidden = true;
        btn.classList.remove('active');
        openTerminalDrawer();
      });
    }

    // Click outside to close
    document.addEventListener('click', (e) => {
      if (!dropdown.hidden && !dropdown.contains(e.target) && !btn.contains(e.target)) {
        dropdown.hidden = true;
        btn.classList.remove('active');
      }
    });

    // Escape to close
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !dropdown.hidden) {
        dropdown.hidden = true;
        btn.classList.remove('active');
      }
    });

    // Initial fetch to update badge and pulse dot
    refreshActivityDropdown(true);
  }

  async function refreshActivityDropdown(silent = false) {
    const list = el.activityDropdownList;
    try {
      const jobs = await apiGet('/api/jobs');
      if (!jobs || !Array.isArray(jobs)) return;

      state.jobs = jobs;

      const runningCount = jobs.filter(j => j.status === 'running').length;
      if (el.runningBadge) {
        if (runningCount > 0) {
          el.runningBadge.style.display = 'flex';
          el.runningBadge.textContent = runningCount;
        } else {
          el.runningBadge.style.display = 'none';
        }
      }

      if (el.activityPulseDot) {
        el.activityPulseDot.style.display = runningCount > 0 ? 'block' : 'none';
      }

      if (silent && list && list.children.length > 1) {
        return;
      }

      if (!list) return;

      if (jobs.length === 0) {
        list.innerHTML = `
          <div class="activity-empty-state">
            <svg class="icon" style="width:24px; height:24px; opacity:0.3;"><use href="#i-bell" /></svg>
            <span>No recent activity</span>
          </div>
        `;
        return;
      }

      list.innerHTML = jobs.map(job => {
        let chipClass = 'chip chip-sm';
        let statusIcon = '#i-check';
        if (job.status === 'done') {
          chipClass += ' chip-ok';
          statusIcon = '#i-check';
        } else if (job.status === 'running') {
          chipClass += ' chip-scheduled';
          statusIcon = '#i-clock';
        } else if (job.status === 'failed' || job.status === 'stopped') {
          chipClass += ' chip-error';
          statusIcon = '#i-x';
        }

        const title = job.label || 'Task';
        const target = job.target ? ` · ${job.target}` : '';
        const timeAgo = formatTimeAgo(job.started || job.created_at);

        return `
          <div class="activity-item">
            <div class="activity-item-header">
              <span class="activity-item-title" title="${escapeHtml(title + target)}">${escapeHtml(title + target)}</span>
              <span class="activity-item-time">${escapeHtml(timeAgo)}</span>
            </div>
            ${job.lastLine ? `<div class="activity-item-sub" title="${escapeHtml(job.lastLine)}">${escapeHtml(job.lastLine)}</div>` : ''}
            <div class="activity-item-footer">
              <span class="${chipClass}">
                <svg class="icon" style="width:11px; height:11px; margin-right:3px;"><use href="${statusIcon}" /></svg>
                ${escapeHtml(job.status)}
              </span>
              ${job.status === 'running' ? `
                <button type="button" class="btn btn-ghost btn-xs" onclick="window.shortsAppOpenTerminal()" title="Inspect live process in terminal">
                  <svg class="icon" style="width:11px; height:11px; margin-right:3px;"><use href="#i-terminal" /></svg>
                  <span>Inspect</span>
                </button>
              ` : ''}
            </div>
          </div>
        `;
      }).join('');
    } catch (e) {
      if (!silent && list) {
        list.innerHTML = `<div class="muted" style="padding:16px; text-align:center; font-size:12px;">Failed to load activity</div>`;
      }
    }
  }

  window.shortsAppOpenTerminal = function () {
    if (el.activityDropdown) el.activityDropdown.hidden = true;
    if (el.topbarActivityBtn) el.topbarActivityBtn.classList.remove('active');
    openTerminalDrawer();
  };

  async function renderActivityList() {
    refreshActivityDropdown();
  }

  // ─────────────────────────────────────────────────────────────
  // Periodic Background Polling
  // ─────────────────────────────────────────────────────────────
  async function pollOverviewBackground() {
    try {
      const data = await apiGet('/api/overview');
      refreshActivityDropdown(true);
    } catch (e) { }
  }

  // ─────────────────────────────────────────────────────────────
  // Theme Palette Switcher
  // ─────────────────────────────────────────────────────────────
  function initTheme() {
    const saved = localStorage.getItem('shorts_studio_theme') || 'youtube';
    applyTheme(saved);

    document.addEventListener('click', (e) => {
      const btn = e.target.closest('.theme-btn[data-set]');
      if (!btn) return;
      const theme = btn.dataset.set;
      applyTheme(theme);
      localStorage.setItem('shorts_studio_theme', theme);
      const name = theme === 'youtube' ? 'YouTube Red' : (theme === 'obsidian' ? 'Obsidian Studio' : 'Emerald Pro');
      toast(`Switched palette to ${name}`);
    });
  }

  function applyTheme(theme) {
    if (theme === 'youtube') {
      document.documentElement.removeAttribute('data-theme');
    } else {
      document.documentElement.setAttribute('data-theme', theme);
    }
  }

  // ─────────────────────────────────────────────────────────────
  // Resizable & Collapsible Sidebar Controls
  // ─────────────────────────────────────────────────────────────
  function initSidebarControls() {
    const sidebar = document.getElementById('sidebar');
    const resizer = document.getElementById('sidebar-resizer');
    const toggleBtn = document.getElementById('sidebar-toggle');

    if (!sidebar) return;

    // Restore saved width and collapse state
    try {
      const isCollapsed = localStorage.getItem('shorts_sidebar_collapsed') === 'true';
      if (isCollapsed) {
        sidebar.classList.add('collapsed');
        sidebar.style.width = '68px';
        sidebar.style.setProperty('--sidebar-width', '68px');
      } else {
        const savedWidth = localStorage.getItem('shorts_sidebar_width');
        if (savedWidth) {
          const w = Math.min(420, Math.max(180, parseInt(savedWidth, 10)));
          sidebar.style.setProperty('--sidebar-width', `${w}px`);
          sidebar.style.width = `${w}px`;
        }
      }
    } catch (e) { }

    const logoBtn = document.getElementById('sidebar-logo-btn');

    function setSidebarCollapsed(willCollapse) {
      sidebar.classList.toggle('collapsed', willCollapse);
      try {
        localStorage.setItem('shorts_sidebar_collapsed', willCollapse ? 'true' : 'false');
        if (willCollapse) {
          sidebar.style.width = '68px';
          sidebar.style.setProperty('--sidebar-width', '68px');
        } else {
          const w = localStorage.getItem('shorts_sidebar_width') || '240';
          sidebar.style.setProperty('--sidebar-width', `${w}px`);
          sidebar.style.width = `${w}px`;
        }
      } catch (err) { }
    }

    // Collapse button in expanded header
    if (toggleBtn) {
      toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        setSidebarCollapsed(!sidebar.classList.contains('collapsed'));
      });
    }

    // Morphing logo button in collapsed rail
    if (logoBtn) {
      logoBtn.addEventListener('click', (e) => {
        if (sidebar.classList.contains('collapsed')) {
          e.stopPropagation();
          setSidebarCollapsed(false);
        }
      });
    }

    // Drag-to-resize sidebar
    if (resizer) {
      let isDragging = false;
      let startX = 0;
      let startW = 240;

      resizer.addEventListener('mousedown', (e) => {
        if (sidebar.classList.contains('collapsed')) return;
        isDragging = true;
        startX = e.clientX;
        startW = sidebar.getBoundingClientRect().width;

        sidebar.classList.add('is-resizing');
        document.body.style.cursor = 'col-resize';
        document.body.style.userSelect = 'none';

        const onMouseMove = (ev) => {
          if (!isDragging) return;
          const delta = ev.clientX - startX;
          const newW = Math.min(420, Math.max(180, Math.round(startW + delta)));
          sidebar.style.setProperty('--sidebar-width', `${newW}px`);
          sidebar.style.width = `${newW}px`;
        };

        const onMouseUp = (ev) => {
          if (!isDragging) return;
          isDragging = false;
          sidebar.classList.remove('is-resizing');
          document.body.style.cursor = '';
          document.body.style.userSelect = '';

          const delta = ev.clientX - startX;
          const finalW = Math.min(420, Math.max(180, Math.round(startW + delta)));
          try {
            localStorage.setItem('shorts_sidebar_width', String(finalW));
          } catch (err) { }

          window.removeEventListener('mousemove', onMouseMove);
          window.removeEventListener('mouseup', onMouseUp);
        };

        window.addEventListener('mousemove', onMouseMove);
        window.addEventListener('mouseup', onMouseUp);
      });
    }
  }

  // ─────────────────────────────────────────────────────────────
  // Video Modal & Delete Modal Controllers
  // ─────────────────────────────────────────────────────────────
  let activeModalShort = null;
  let activeDeleteShort = null;

  function openVideoModal(item) {
    activeModalShort = item;
    const backdrop = document.getElementById('video-modal-backdrop');
    const player = document.getElementById('video-modal-player');
    const title = document.getElementById('video-modal-title');
    const part = document.getElementById('video-modal-part');
    const score = document.getElementById('video-modal-score');
    const duration = document.getElementById('video-modal-duration');
    const delBtn = document.getElementById('video-modal-delete-btn');
    const pubBtn = document.getElementById('video-modal-publish-btn');

    if (!backdrop || !player) return;

    const isLongform = item.isLongform || Boolean(item.videoSrc);
    if (title) title.textContent = item.title || (isLongform ? 'Watch Feature Video' : 'Watch Short');
    if (part) {
      if (isLongform) {
        part.textContent = 'Longform Feature';
        part.className = 'chip chip-scheduled';
      } else {
        part.textContent = `Part ${item.part || 1}/${item.parts || 1}`;
        part.className = 'chip chip-warn';
      }
    }
    if (score) score.textContent = isLongform ? 'Full Narrative Cut' : (item.score ? `${item.score}/10 Score` : 'Viral Clip');
    if (duration) {
      duration.textContent = typeof item.duration === 'string' && item.duration.includes(':')
        ? item.duration
        : formatDuration(item.duration);
    }
    if (delBtn) delBtn.style.display = isLongform ? 'none' : 'inline-flex';
    if (pubBtn) pubBtn.style.display = isLongform ? 'none' : 'inline-flex';

    const videoSrc = item.videoSrc || item.videoUrl || item.storageUrl || `/api/video?id=${item.id}`;
    player.src = videoSrc;
    player.currentTime = 0;
    backdrop.hidden = false;
    player.play().catch(() => { });
  }

  function closeVideoModal() {
    const backdrop = document.getElementById('video-modal-backdrop');
    const player = document.getElementById('video-modal-player');
    if (player) {
      player.pause();
      player.removeAttribute('src');
      player.load();
    }
    if (backdrop) backdrop.hidden = true;
    activeModalShort = null;
  }

  function openDeleteModal(item) {
    activeDeleteShort = item;
    const backdrop = document.getElementById('delete-modal-backdrop');
    const titleEl = document.getElementById('delete-modal-short-title');
    if (titleEl) titleEl.textContent = `"${item.title || 'this Short'}" (#${item.id})`;
    if (backdrop) backdrop.hidden = false;
  }

  function closeDeleteModal() {
    const backdrop = document.getElementById('delete-modal-backdrop');
    if (backdrop) backdrop.hidden = true;
    activeDeleteShort = null;
  }

  function initVideoModals() {
    const videoClose = document.getElementById('video-modal-close');
    const videoBackdrop = document.getElementById('video-modal-backdrop');
    if (videoClose) videoClose.addEventListener('click', closeVideoModal);
    if (videoBackdrop) {
      videoBackdrop.addEventListener('click', (e) => {
        if (e.target === videoBackdrop) closeVideoModal();
      });
    }

    const modalPublishBtn = document.getElementById('video-modal-publish-btn');
    if (modalPublishBtn) {
      modalPublishBtn.addEventListener('click', () => {
        if (!activeModalShort) return;
        const item = activeModalShort;
        closeVideoModal();
        openPublishAccountModal(item.id, item.title);
      });
    }

    const modalDeleteBtn = document.getElementById('video-modal-delete-btn');
    if (modalDeleteBtn) {
      modalDeleteBtn.addEventListener('click', () => {
        if (!activeModalShort) return;
        const item = activeModalShort;
        closeVideoModal();
        openDeleteModal(item);
      });
    }

    const deleteCancel = document.getElementById('delete-modal-cancel');
    const deleteClose = document.getElementById('delete-modal-close');
    const deleteBackdrop = document.getElementById('delete-modal-backdrop');
    const deleteConfirm = document.getElementById('delete-modal-confirm');

    if (deleteCancel) deleteCancel.addEventListener('click', closeDeleteModal);
    if (deleteClose) deleteClose.addEventListener('click', closeDeleteModal);
    if (deleteBackdrop) {
      deleteBackdrop.addEventListener('click', (e) => {
        if (e.target === deleteBackdrop) closeDeleteModal();
      });
    }

    if (deleteConfirm) {
      deleteConfirm.addEventListener('click', async () => {
        if (!activeDeleteShort) return;
        const short = activeDeleteShort;
        deleteConfirm.disabled = true;
        deleteConfirm.innerHTML = `<span class="dot warn"></span> Deleting...`;
        try {
          const res = await apiPost('/api/publish/delete', { id: short.id });
          if (res.error) throw new Error(res.error);
          toast(`Short #${short.id} deleted from Supabase & database`, 'ok');
          closeDeleteModal();
          state.library = state.library.filter(x => x.id !== short.id);
          refreshPublishQueue();
          refreshOverview();
        } catch (err) {
          toast(`Delete failed: ${err.message}`, 'error');
        } finally {
          deleteConfirm.disabled = false;
          deleteConfirm.innerHTML = `<svg class="icon"><use href="#i-trash" /></svg>Delete from Supabase`;
        }
      });
    }

    // Keyboard ESC to close modals
    window.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        closeVideoModal();
        closeDeleteModal();
        closePublishAccountModal();
      }
    });
  }

  // ─────────────────────────────────────────────────────────────
  // YouTube Upload Target Account Switcher
  // ─────────────────────────────────────────────────────────────
  state.accounts = null;

  function updateAccountUI(accountsData) {
    if (!accountsData) return;
    state.accounts = accountsData;
    const active = (accountsData.accounts || []).find(a => a.id === accountsData.active_id) || (accountsData.accounts || [])[0];
    if (!active) return;

    // Update Sidebar Brand Subtitle
    const sideHandle = document.getElementById('sidebar-account-handle');
    if (sideHandle) {
      sideHandle.textContent = active.handle || active.email;
    }

    // Update Sidebar Target Account Card in bottom of sidebar
    const sideAccName = document.getElementById('sidebar-account-name');
    const sideAccHandleBadge = document.getElementById('sidebar-account-handle-badge');
    const sideAccDot = document.getElementById('sidebar-account-dot');
    const sideAccCard = document.getElementById('sidebar-account-card');

    if (sideAccName) sideAccName.textContent = active.name || active.email;
    if (sideAccHandleBadge) sideAccHandleBadge.textContent = active.handle || '';
    if (sideAccDot) {
      sideAccDot.className = `sidebar-account-dot ${active.authenticated ? 'ok' : 'warn'}`;
    }
    if (sideAccCard) {
      sideAccCard.setAttribute('title', `Active: ${active.name} (${active.handle || active.email}) · Click to switch`);
    }

    // Update Sidebar Target Account Menu items
    const sideMenu = document.getElementById('sidebar-account-menu');
    if (sideMenu) {
      sideMenu.innerHTML = (accountsData.accounts || []).map(acc => {
        const isCurrent = acc.id === accountsData.active_id;
        return `
          <div class="sidebar-account-menu-item ${isCurrent ? 'active' : ''}" data-account-id="${acc.id}">
            <div class="sidebar-menu-item-info">
              <strong class="sidebar-menu-item-name">${escapeHtml(acc.name)}</strong>
              <span class="sidebar-menu-item-handle">${escapeHtml(acc.handle || '')}</span>
              <span class="sidebar-menu-item-email">${escapeHtml(acc.email)}</span>
            </div>
            <svg class="icon custom-dropdown-check"><use href="#i-check" /></svg>
          </div>
        `;
      }).join('');
    }

    // Update Publish queue banner
    const bannerTarget = document.getElementById('publish-banner-account');
    if (bannerTarget) {
      bannerTarget.textContent = active.handle || active.email;
    }

    // Update Account Switcher Button in Publish subbar
    const dot = document.getElementById('account-active-dot');
    const nameEl = document.getElementById('account-active-name');
    const emailEl = document.getElementById('account-active-email');
    if (dot) {
      dot.className = `account-dot ${active.authenticated ? 'ok' : 'warn'}`;
    }
    if (nameEl) nameEl.textContent = active.name || active.email;
    if (emailEl) emailEl.textContent = active.email;

    // Render Dropdown Menu Items
    const menu = document.getElementById('account-switch-menu');
    if (menu) {
      menu.innerHTML = (accountsData.accounts || []).map(acc => {
        const isCurrent = acc.id === accountsData.active_id;
        const statusText = acc.authenticated ? '● Connected' : '○ Needs Auth';
        const statusClass = acc.authenticated ? 'ok' : 'warn';
        return `
          <li class="custom-dropdown-item account-menu-item ${isCurrent ? 'active' : ''}" data-account-id="${acc.id}">
            <div class="account-item-main">
              <div class="account-item-name">
                ${escapeHtml(acc.name)}
                <span class="chip chip-quiet" style="font-size:10px; padding:2px 6px;">${escapeHtml(acc.handle || '')}</span>
              </div>
              <div class="account-item-email muted">${escapeHtml(acc.email)}</div>
            </div>
            <div class="account-item-right">
              <span class="account-status-tag ${statusClass}">${statusText}</span>
              ${!acc.authenticated ? `
                <button type="button" class="btn-auth-account" data-auth-id="${acc.id}" title="Connect and authenticate this Google account">Connect</button>
              ` : `
                <svg class="icon custom-dropdown-check"><use href="#i-check" /></svg>
              `}
            </div>
          </li>
        `;
      }).join('');
    }
  }

  // ─────────────────────────────────────────────────────────────
  // Target Account Selection Modal & Card Loading Bar Flow
  // ─────────────────────────────────────────────────────────────
  let pendingPublishShortId = null;

  function formatLocalDateTimeInput(d) {
    const pad = n => String(n).padStart(2, '0');
    const year = d.getFullYear();
    const month = pad(d.getMonth() + 1);
    const day = pad(d.getDate());
    const hours = pad(d.getHours());
    const mins = pad(d.getMinutes());
    return `${year}-${month}-${day}T${hours}:${mins}`;
  }

  function openPublishAccountModal(shortId, shortTitle) {
    pendingPublishShortId = shortId;
    const modal = document.getElementById('account-publish-modal-backdrop');
    const titleEl = document.getElementById('account-publish-short-title');
    const optionsList = document.getElementById('account-publish-options');
    if (!modal || !optionsList) return;

    if (titleEl) titleEl.textContent = shortTitle || `Short #${shortId}`;

    // Reset timing mode to "now"
    const btnNow = document.getElementById('timing-btn-now');
    const btnSchedule = document.getElementById('timing-btn-schedule');
    const scheduleDetails = document.getElementById('publish-schedule-details');
    const publishNowDetails = document.getElementById('publish-now-details');
    const confirmText = document.getElementById('account-publish-confirm-text');
    const confirmIcon = document.getElementById('account-publish-confirm-icon');

    if (btnNow) btnNow.classList.add('active');
    if (btnSchedule) btnSchedule.classList.remove('active');
    if (scheduleDetails) scheduleDetails.style.display = 'none';
    if (publishNowDetails) publishNowDetails.style.display = 'flex';
    if (confirmText) confirmText.textContent = 'Confirm & Upload';
    if (confirmIcon) {
      const useEl = confirmIcon.querySelector('use');
      if (useEl) useEl.setAttribute('href', '#i-send');
    }

    // Default scheduled time to 2 hours in future, minimum 15 minutes ahead
    const dtInput = document.getElementById('account-publish-datetime');
    const wrapper = document.getElementById('studio-datetime-wrapper');
    const box = document.getElementById('schedule-input-box');
    if (wrapper) wrapper.classList.remove('open');
    if (box) box.setAttribute('aria-expanded', 'false');

    if (dtInput) {
      const now = new Date();
      const minDate = new Date(now.getTime() + 15 * 60 * 1000);
      const defaultDate = new Date(now.getTime() + 2 * 3600 * 1000);
      dtInput.min = formatLocalDateTimeInput(minDate);
      dtInput.value = formatLocalDateTimeInput(defaultDate);
      dtInput.dispatchEvent(new Event('change'));
    }

    // Reset preset buttons highlight
    const presetPills = document.querySelectorAll('#schedule-preset-buttons .preset-pill');
    presetPills.forEach(p => p.classList.remove('active'));

    const accounts = (state.accounts && state.accounts.accounts && state.accounts.accounts.length)
      ? state.accounts.accounts
      : [
        { id: 'alternate', name: 'Eiji Shorts', email: 'mhrznsuzan.alternate@gmail.com', handle: '@eijishorts', authenticated: true },
        { id: 'official', name: 'Suzzane', email: 'maharjansujan.official@gmail.com', handle: '@MR.EIJI05', authenticated: true }
      ];

    const currentActiveId = (state.accounts && state.accounts.active_id) || 'alternate';

    optionsList.innerHTML = accounts.map(acc => {
      const isSelected = acc.id === currentActiveId;
      const statusText = acc.authenticated ? 'Ready' : 'Needs Auth';
      const statusClass = acc.authenticated ? 'ok' : 'warn';
      return `
        <div class="account-option-card ${isSelected ? 'selected' : ''}" data-account-id="${acc.id}">
          <div class="account-option-radio">
            <div class="account-radio-circle"></div>
          </div>
          <div class="account-option-avatar">
            <svg class="icon"><use href="#i-youtube"/></svg>
          </div>
          <div class="account-option-info">
            <div class="account-option-top">
              <strong class="account-option-name">${escapeHtml(acc.name)}</strong>
              <span class="account-option-handle">${escapeHtml(acc.handle || '')}</span>
            </div>
            <div class="account-option-email">${escapeHtml(acc.email)}</div>
          </div>
          <div class="account-option-status">
            <span class="account-dot ${statusClass}"></span>
            <span class="account-status-label">${statusText}</span>
          </div>
        </div>
      `;
    }).join('');

    // Handle clicks on cards to select
    optionsList.querySelectorAll('.account-option-card').forEach(card => {
      card.addEventListener('click', () => {
        optionsList.querySelectorAll('.account-option-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
      });
      // Double click to confirm immediately
      card.addEventListener('dblclick', () => {
        optionsList.querySelectorAll('.account-option-card').forEach(c => c.classList.remove('selected'));
        card.classList.add('selected');
        confirmAccountAndPublish();
      });
    });

    // Populate and sync beautified custom dropdown
    const dropdownWrap = document.getElementById('account-modal-dropdown');
    const dropdownBtn = document.getElementById('account-modal-dropdown-btn');
    const dropdownMenu = document.getElementById('account-modal-dropdown-menu');
    const selectedNameEl = document.getElementById('account-modal-selected-name');
    const selectedHandleEl = document.getElementById('account-modal-selected-handle');
    const selectedDotEl = document.getElementById('account-modal-selected-dot');

    const updateSelectedDropdownAccount = (accId) => {
      const targetAcc = accounts.find(a => a.id === accId) || accounts[0];
      if (!targetAcc) return;

      if (selectedNameEl) selectedNameEl.textContent = targetAcc.name;
      if (selectedHandleEl) selectedHandleEl.textContent = targetAcc.handle || targetAcc.email;
      if (selectedDotEl) {
        selectedDotEl.className = `account-dot ${targetAcc.authenticated ? 'ok' : 'warn'}`;
      }

      // Sync hidden options cards for confirmAccountAndPublish
      optionsList.querySelectorAll('.account-option-card').forEach(card => {
        if (card.dataset.accountId === targetAcc.id) {
          card.classList.add('selected');
        } else {
          card.classList.remove('selected');
        }
      });

      // Update menu items active state
      if (dropdownMenu) {
        dropdownMenu.querySelectorAll('.account-modal-menu-item').forEach(item => {
          const isItemActive = item.dataset.accountId === targetAcc.id;
          item.classList.toggle('active', isItemActive);
          item.setAttribute('aria-selected', isItemActive ? 'true' : 'false');
          const checkIcon = item.querySelector('.account-modal-check');
          if (checkIcon) checkIcon.style.display = isItemActive ? 'block' : 'none';
        });
      }
    };

    if (dropdownMenu) {
      dropdownMenu.innerHTML = accounts.map(acc => {
        const isSelected = acc.id === currentActiveId;
        const statusText = acc.authenticated ? 'Ready' : 'Needs Auth';
        const statusClass = acc.authenticated ? 'ok' : 'warn';
        return `
          <li class="account-modal-menu-item ${isSelected ? 'active' : ''}" data-account-id="${escapeHtml(acc.id)}" role="option" aria-selected="${isSelected ? 'true' : 'false'}">
            <div class="account-modal-item-left">
              <div class="account-modal-avatar">
                <svg class="icon"><use href="#i-youtube"/></svg>
              </div>
              <div class="account-modal-item-info">
                <div class="account-modal-item-name">${escapeHtml(acc.name)}</div>
                <div class="account-modal-item-handle">${escapeHtml(acc.handle || acc.email)}</div>
              </div>
            </div>
            <div class="account-modal-item-right">
              <span class="account-dot ${statusClass}"></span>
              <span class="account-status-label">${statusText}</span>
              <svg class="icon account-modal-check" style="${isSelected ? 'display:block;' : 'display:none;'}"><use href="#i-check"/></svg>
            </div>
          </li>
        `;
      }).join('');

      dropdownMenu.querySelectorAll('.account-modal-menu-item').forEach(item => {
        item.addEventListener('click', (e) => {
          e.stopPropagation();
          const accId = item.dataset.accountId;
          updateSelectedDropdownAccount(accId);
          if (dropdownWrap) dropdownWrap.classList.remove('open');
          if (dropdownBtn) dropdownBtn.setAttribute('aria-expanded', 'false');
        });
      });
    }

    updateSelectedDropdownAccount(currentActiveId);
    if (dropdownWrap) dropdownWrap.classList.remove('open');
    if (dropdownBtn) dropdownBtn.setAttribute('aria-expanded', 'false');

    modal.hidden = false;
  }

  function closePublishAccountModal() {
    const modal = document.getElementById('account-publish-modal-backdrop');
    if (modal) modal.hidden = true;
    pendingPublishShortId = null;
  }

  async function confirmAccountAndPublish() {
    if (!pendingPublishShortId) return;
    const shortId = pendingPublishShortId;
    const selectedCard = document.querySelector('#account-publish-options .account-option-card.selected');
    const chosenId = selectedCard ? selectedCard.dataset.accountId : ((state.accounts && state.accounts.active_id) || 'alternate');

    const accounts = (state.accounts && state.accounts.accounts) || [];
    const chosenAccount = accounts.find(a => a.id === chosenId) || {
      id: chosenId,
      name: chosenId === 'official' ? 'Suzzane' : 'Eiji Shorts',
      email: chosenId === 'official' ? 'maharjansujan.official@gmail.com' : 'mhrznsuzan.alternate@gmail.com',
      handle: chosenId === 'official' ? '@MR.EIJI05' : '@eijishorts'
    };

    // Check if Schedule timing mode is active
    const btnSchedule = document.getElementById('timing-btn-schedule');
    const isSchedule = btnSchedule && btnSchedule.classList.contains('active');
    let publishAt = null;

    if (isSchedule) {
      const dtInput = document.getElementById('account-publish-datetime');
      const val = dtInput ? dtInput.value : '';
      if (!val) {
        toast('Please pick a release date and time for the schedule', 'warn');
        return;
      }
      const schedDate = new Date(val);
      if (isNaN(schedDate.getTime())) {
        toast('Invalid date & time format', 'warn');
        return;
      }
      // YouTube requires schedule to be at least 15 minutes into the future
      if (schedDate.getTime() < Date.now() + 14 * 60 * 1000) {
        toast('YouTube requires scheduled release to be at least 15 minutes in the future', 'warn');
        return;
      }
      publishAt = schedDate.toISOString();
    }

    const rememberDefault = document.getElementById('account-publish-set-active')?.checked ?? true;

    closePublishAccountModal();

    if (rememberDefault && chosenId !== state.accounts?.active_id) {
      try {
        const res = await apiPost('/api/accounts/switch', { id: chosenId });
        updateAccountUI(res);
      } catch (err) { }
    }

    startCardUpload(shortId, chosenAccount, publishAt);
  }

  function initStudioDateTimeInput() {
    const wrapper = document.getElementById('studio-datetime-wrapper');
    const box = document.getElementById('schedule-input-box');
    const displayEl = document.getElementById('studio-datetime-display');
    const dtInput = document.getElementById('account-publish-datetime');
    const popover = document.getElementById('studio-dt-popover');
    const monthTitle = document.getElementById('sdt-month-title');
    const daysGrid = document.getElementById('sdt-days-grid');
    const prevMonthBtn = document.getElementById('sdt-prev-month');
    const nextMonthBtn = document.getElementById('sdt-next-month');
    const hoursCol = document.getElementById('sdt-hours-col');
    const minutesCol = document.getElementById('sdt-minutes-col');
    const ampmCol = document.getElementById('sdt-ampm-col');
    const clearBtn = document.getElementById('sdt-clear-btn');
    const todayBtn = document.getElementById('sdt-today-btn');
    const prevEl = document.getElementById('schedule-relative-preview');

    if (!wrapper || !box || !dtInput || !popover || !displayEl) return;

    let selectedDate = new Date();
    if (dtInput.value) {
      const p = new Date(dtInput.value);
      if (!isNaN(p.getTime())) selectedDate = p;
    } else {
      selectedDate = new Date(Date.now() + 2 * 3600 * 1000);
      dtInput.value = formatLocalDateTimeInput(selectedDate);
    }

    let viewMonth = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1);
    const monthNames = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];

    function syncDisplayAndStorage() {
      dtInput.value = formatLocalDateTimeInput(selectedDate);
      const mm = String(selectedDate.getMonth() + 1).padStart(2, '0');
      const dd = String(selectedDate.getDate()).padStart(2, '0');
      const yyyy = selectedDate.getFullYear();

      let h = selectedDate.getHours();
      const isPM = h >= 12;
      let displayH = h % 12;
      if (displayH === 0) displayH = 12;
      const hStr = String(displayH).padStart(2, '0');
      const mStr = String(selectedDate.getMinutes()).padStart(2, '0');
      const ampm = isPM ? 'PM' : 'AM';

      displayEl.textContent = `${mm}/${dd}/${yyyy} ${hStr}:${mStr} ${ampm}`;
      if (prevEl) prevEl.textContent = formatRelativeRelease(selectedDate.toISOString());
    }

    function renderCalendar() {
      if (!monthTitle || !daysGrid) return;
      monthTitle.textContent = `${monthNames[viewMonth.getMonth()]} ${viewMonth.getFullYear()}`;
      daysGrid.innerHTML = '';

      const year = viewMonth.getFullYear();
      const month = viewMonth.getMonth();
      const firstDayIndex = new Date(year, month, 1).getDay();
      const daysInMonth = new Date(year, month + 1, 0).getDate();
      const daysInPrevMonth = new Date(year, month, 0).getDate();

      const today = new Date();
      today.setHours(0, 0, 0, 0);

      // Trailing days from prev month
      for (let i = firstDayIndex - 1; i >= 0; i--) {
        const d = daysInPrevMonth - i;
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'sdt-day-btn other-month disabled';
        btn.textContent = d;
        daysGrid.appendChild(btn);
      }

      // Days of current month
      for (let day = 1; day <= daysInMonth; day++) {
        const cellDate = new Date(year, month, day);
        cellDate.setHours(0, 0, 0, 0);

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'sdt-day-btn';
        btn.textContent = day;

        const isPast = cellDate.getTime() < today.getTime();
        const isToday = cellDate.getTime() === today.getTime();
        const isSelected = selectedDate.getFullYear() === year && selectedDate.getMonth() === month && selectedDate.getDate() === day;

        if (isPast) btn.classList.add('disabled');
        if (isToday) btn.classList.add('today');
        if (isSelected) btn.classList.add('active');

        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          selectedDate.setFullYear(year, month, day);
          syncDisplayAndStorage();
          renderCalendar();
        });

        daysGrid.appendChild(btn);
      }

      // Leading days of next month
      const totalCells = firstDayIndex + daysInMonth;
      const remaining = (7 - (totalCells % 7)) % 7;
      for (let j = 1; j <= remaining; j++) {
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'sdt-day-btn other-month disabled';
        btn.textContent = j;
        daysGrid.appendChild(btn);
      }
    }

    function renderTimeColumns() {
      if (!hoursCol || !minutesCol || !ampmCol) return;

      let curH = selectedDate.getHours();
      const isPM = curH >= 12;
      let displayH = curH % 12;
      if (displayH === 0) displayH = 12;
      const activeHStr = String(displayH).padStart(2, '0');
      const activeMStr = String(selectedDate.getMinutes()).padStart(2, '0');

      // Populate Hours (01-12)
      hoursCol.innerHTML = '';
      for (let h = 1; h <= 12; h++) {
        const hStr = String(h).padStart(2, '0');
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `sdt-time-opt ${hStr === activeHStr ? 'active' : ''}`;
        btn.textContent = hStr;
        btn.dataset.hour = hStr;
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          let targetH = parseInt(hStr, 10);
          const currentPM = selectedDate.getHours() >= 12;
          if (currentPM && targetH < 12) targetH += 12;
          if (!currentPM && targetH === 12) targetH = 0;
          selectedDate.setHours(targetH);
          syncDisplayAndStorage();
          renderTimeColumns();
        });
        hoursCol.appendChild(btn);
      }

      // Populate Minutes (00-59)
      minutesCol.innerHTML = '';
      for (let m = 0; m < 60; m++) {
        const mStr = String(m).padStart(2, '0');
        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = `sdt-time-opt ${mStr === activeMStr ? 'active' : ''}`;
        btn.textContent = mStr;
        btn.dataset.min = mStr;
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          selectedDate.setMinutes(parseInt(mStr, 10));
          syncDisplayAndStorage();
          renderTimeColumns();
        });
        minutesCol.appendChild(btn);
      }

      // AM/PM column
      ampmCol.querySelectorAll('.sdt-time-opt').forEach(btn => {
        const isMatch = btn.dataset.val === (isPM ? 'PM' : 'AM');
        btn.classList.toggle('active', isMatch);
        btn.onclick = (e) => {
          e.stopPropagation();
          const targetIsPM = btn.dataset.val === 'PM';
          let h = selectedDate.getHours();
          if (targetIsPM && h < 12) h += 12;
          if (!targetIsPM && h >= 12) h -= 12;
          selectedDate.setHours(h);
          syncDisplayAndStorage();
          renderTimeColumns();
        };
      });

      // Auto-scroll active time options into view
      setTimeout(() => {
        const actH = hoursCol.querySelector('.sdt-time-opt.active');
        if (actH) actH.scrollIntoView({ block: 'center' });
        const actM = minutesCol.querySelector('.sdt-time-opt.active');
        if (actM) actM.scrollIntoView({ block: 'center' });
      }, 10);
    }

    // Toggle popover
    box.onclick = (e) => {
      e.stopPropagation();
      const isOpen = wrapper.classList.toggle('open');
      box.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      if (isOpen) {
        renderCalendar();
        renderTimeColumns();
      }
    };

    // Close on outside click
    if (!wrapper._outsideBound) {
      document.addEventListener('click', (e) => {
        if (wrapper && !wrapper.contains(e.target)) {
          wrapper.classList.remove('open');
          box.setAttribute('aria-expanded', 'false');
        }
      });
      wrapper._outsideBound = true;
    }

    if (prevMonthBtn) {
      prevMonthBtn.onclick = (e) => {
        e.stopPropagation();
        viewMonth.setMonth(viewMonth.getMonth() - 1);
        renderCalendar();
      };
    }

    if (nextMonthBtn) {
      nextMonthBtn.onclick = (e) => {
        e.stopPropagation();
        viewMonth.setMonth(viewMonth.getMonth() + 1);
        renderCalendar();
      };
    }

    if (todayBtn) {
      todayBtn.onclick = (e) => {
        e.stopPropagation();
        const now = new Date();
        selectedDate.setFullYear(now.getFullYear(), now.getMonth(), now.getDate());
        viewMonth = new Date(now.getFullYear(), now.getMonth(), 1);
        syncDisplayAndStorage();
        renderCalendar();
      };
    }

    if (clearBtn) {
      clearBtn.onclick = (e) => {
        e.stopPropagation();
        selectedDate = new Date(Date.now() + 2 * 3600 * 1000);
        viewMonth = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1);
        syncDisplayAndStorage();
        renderCalendar();
        renderTimeColumns();
      };
    }

    dtInput.onchange = () => {
      const p = new Date(dtInput.value);
      if (!isNaN(p.getTime())) {
        selectedDate = p;
        viewMonth = new Date(selectedDate.getFullYear(), selectedDate.getMonth(), 1);
        syncDisplayAndStorage();
        renderCalendar();
        renderTimeColumns();
      }
    };

    syncDisplayAndStorage();
    renderCalendar();
    renderTimeColumns();
  }

  function initPublishAccountModal() {
    const modal = document.getElementById('account-publish-modal-backdrop');
    const closeBtn = document.getElementById('account-publish-modal-close');
    const cancelBtn = document.getElementById('account-publish-cancel');
    const confirmBtn = document.getElementById('account-publish-confirm');

    if (closeBtn) closeBtn.addEventListener('click', closePublishAccountModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closePublishAccountModal);
    if (confirmBtn) confirmBtn.addEventListener('click', confirmAccountAndPublish);

    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) closePublishAccountModal();
      });
    }

    // Release timing tabs: Now vs Schedule
    const btnNow = document.getElementById('timing-btn-now');
    const btnSchedule = document.getElementById('timing-btn-schedule');
    const scheduleDetails = document.getElementById('publish-schedule-details');
    const confirmText = document.getElementById('account-publish-confirm-text');
    const confirmIcon = document.getElementById('account-publish-confirm-icon');

    if (btnNow) {
      btnNow.addEventListener('click', () => {
        btnNow.classList.add('active');
        if (btnSchedule) btnSchedule.classList.remove('active');
        if (scheduleDetails) scheduleDetails.style.display = 'none';
        const publishNowDetails = document.getElementById('publish-now-details');
        if (publishNowDetails) publishNowDetails.style.display = 'flex';
        if (confirmText) confirmText.textContent = 'Confirm & Upload';
        if (confirmIcon) {
          const useEl = confirmIcon.querySelector('use');
          if (useEl) useEl.setAttribute('href', '#i-send');
        }
      });
    }

    if (btnSchedule) {
      btnSchedule.addEventListener('click', () => {
        btnSchedule.classList.add('active');
        if (btnNow) btnNow.classList.remove('active');
        if (scheduleDetails) scheduleDetails.style.display = 'flex';
        const publishNowDetails = document.getElementById('publish-now-details');
        if (publishNowDetails) publishNowDetails.style.display = 'none';
        if (confirmText) confirmText.textContent = 'Schedule Upload';
        if (confirmIcon) {
          const useEl = confirmIcon.querySelector('use');
          if (useEl) useEl.setAttribute('href', '#i-clock');
        }
        initStudioDateTimeInput();
      });
    }

    // Custom Account Selection Dropdown toggle & outside-click close
    const dropdownWrap = document.getElementById('account-modal-dropdown');
    const dropdownBtn = document.getElementById('account-modal-dropdown-btn');

    if (dropdownBtn && dropdownWrap) {
      dropdownBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = dropdownWrap.classList.toggle('open');
        dropdownBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      });
    }

    document.addEventListener('click', (e) => {
      if (dropdownWrap && dropdownWrap.classList.contains('open')) {
        if (!dropdownWrap.contains(e.target)) {
          dropdownWrap.classList.remove('open');
          if (dropdownBtn) dropdownBtn.setAttribute('aria-expanded', 'false');
        }
      }
    });

    // Schedule preset pills (+1 Hour, +3 Hours, Tomorrow 9 AM, Tomorrow 6 PM)
    const presetPills = document.querySelectorAll('#schedule-preset-buttons .preset-pill');
    const dtInput = document.getElementById('account-publish-datetime');
    const prevEl = document.getElementById('schedule-relative-preview');

    const updateSchedulePreview = () => {
      if (!prevEl || !dtInput || !dtInput.value) {
        if (prevEl) prevEl.textContent = '';
        return;
      }
      try {
        const d = new Date(dtInput.value);
        if (!isNaN(d.getTime())) {
          prevEl.textContent = formatRelativeRelease(d.toISOString());
        }
      } catch (e) { }
    };

    if (dtInput) {
      dtInput.addEventListener('input', updateSchedulePreview);
      dtInput.addEventListener('change', updateSchedulePreview);
    }

    presetPills.forEach(pill => {
      pill.addEventListener('click', () => {
        presetPills.forEach(p => p.classList.remove('active'));
        pill.classList.add('active');

        const now = new Date();
        let target = new Date();

        if (pill.dataset.hours) {
          const hrs = parseInt(pill.dataset.hours, 10);
          target = new Date(now.getTime() + hrs * 3600 * 1000);
        } else if (pill.dataset.preset === 'tomorrow-9am') {
          target.setDate(target.getDate() + 1);
          target.setHours(9, 0, 0, 0);
        } else if (pill.dataset.preset === 'tomorrow-6pm') {
          target.setDate(target.getDate() + 1);
          target.setHours(18, 0, 0, 0);
        }

        if (dtInput) {
          dtInput.value = formatLocalDateTimeInput(target);
          updateSchedulePreview();
          dtInput.dispatchEvent(new Event('change'));
        }
      });
    });

    initStudioDateTimeInput();
  }

  // ─────────────────────────────────────────────────────────────
  // Autonomous Peak-Hour Auto-Scheduler Modal
  // ─────────────────────────────────────────────────────────────
  function initAutoSchedulerModal() {
    const btnOpen = document.getElementById('auto-schedule-btn');
    const modal = document.getElementById('auto-scheduler-modal-backdrop');
    const closeBtn = document.getElementById('auto-scheduler-close');
    const cancelBtn = document.getElementById('auto-sched-cancel-btn');
    const dryRunBtn = document.getElementById('auto-sched-dry-run-btn');
    const confirmBtn = document.getElementById('auto-sched-confirm-btn');
    const confirmText = document.getElementById('auto-sched-confirm-text');
    const cadenceSelect = document.getElementById('auto-sched-cadence');
    const countSelect = document.getElementById('auto-sched-count');
    const previewList = document.getElementById('auto-sched-preview-list');
    const previewCountEl = document.getElementById('auto-sched-preview-count');
    const accountNameEl = document.getElementById('auto-sched-account-name');
    const quotaSummaryEl = document.getElementById('auto-sched-quota-summary');
    const quotaChipEl = document.getElementById('auto-sched-quota-chip');

    let currentPreview = [];

    const closeModal = () => {
      if (modal) modal.hidden = true;
    };

    const openModal = async () => {
      if (!modal) return;
      modal.hidden = false;

      // Update target account label
      const activeAccount = (state.accounts && state.accounts.accounts && state.accounts.accounts.find(a => a.id === state.accounts.active_id)) || {
        name: 'EIJI Shorts',
        handle: '@eijishorts'
      };
      if (accountNameEl) {
        accountNameEl.textContent = `Target: ${activeAccount.name} (${activeAccount.handle || '@YouTube'})`;
      }

      await refreshSchedulerPreview();
    };

    const refreshSchedulerPreview = async () => {
      if (!previewList) return;
      previewList.innerHTML = '<div style="padding:16px; text-align:center;" class="muted small"><div class="spinner" style="margin:0 auto 8px;"></div>Calculating peak viewership slots...</div>';

      const count = parseInt(countSelect?.value || '6', 10);
      const cadence = parseInt(cadenceSelect?.value || '2', 10);

      try {
        const data = await apiGet(`/api/scheduler/preview?count=${count}&slots_per_day=${cadence}`);
        if (!data || !data.preview) {
          previewList.innerHTML = '<div class="muted small" style="padding:14px; text-align:center;">No unuploaded Shorts available to schedule.</div>';
          if (confirmBtn) confirmBtn.disabled = true;
          return;
        }

        currentPreview = data.preview;

        // Quota / upload progress indicators (Minimum 6/day baseline, no hard stop)
        const quota = data.quota || {};
        const uploadsToday = quota.uploads_today ?? Math.floor((quota.units_used || 0) / 1600);
        const minGoal = 6;
        const targetMet = uploadsToday >= minGoal;
        if (quotaSummaryEl) {
          quotaSummaryEl.textContent = `Daily Uploads: ${uploadsToday} completed today (Minimum daily baseline: ${minGoal})`;
        }
        if (quotaChipEl) {
          quotaChipEl.className = 'chip chip-ok';
          quotaChipEl.textContent = targetMet ? `Baseline Met (${uploadsToday}/${minGoal}+)` : `${uploadsToday}/${minGoal} to Baseline`;
        }

        if (previewCountEl) {
          previewCountEl.textContent = `${data.preview.length} Shorts ready to schedule`;
        }
        if (confirmText) {
          confirmText.textContent = `Pre-Upload & Schedule (${data.preview.length})`;
        }
        if (confirmBtn) {
          confirmBtn.disabled = (data.preview.length === 0);
        }

        if (data.preview.length === 0) {
          previewList.innerHTML = '<div class="muted small" style="padding:16px; text-align:center; background:rgba(255,255,255,0.02); border-radius:8px;">All created Shorts have already been uploaded or scheduled.</div>';
          return;
        }

        previewList.innerHTML = data.preview.map((item, idx) => `
          <div class="auto-sched-row">
            <div class="auto-sched-left">
              <span class="auto-sched-idx">#${idx + 1}</span>
              <div class="auto-sched-info">
                <span class="auto-sched-title" title="${escapeHtml(item.title)}">Part ${item.part}: ${escapeHtml(item.title)}</span>
                <span class="auto-sched-meta">${item.duration ? `${Number(item.duration).toFixed(1)}s` : ''} &bull; ${escapeHtml(item.window_name)}</span>
              </div>
            </div>
            <div class="auto-sched-right">
              <span class="auto-sched-date">${escapeHtml(item.day_rel)} &bull; ${escapeHtml((item.local_formatted.split(' at ')[1]) || item.local_formatted)}</span>
              <span class="auto-sched-window">${escapeHtml((item.local_formatted.split(' at ')[0]) || '')}</span>
            </div>
          </div>
        `).join('');

      } catch (err) {
        previewList.innerHTML = `<div class="error small" style="padding:14px; text-align:center;">Failed to load preview: ${escapeHtml(err.message)}</div>`;
      }
    };

    if (btnOpen) btnOpen.addEventListener('click', openModal);
    if (closeBtn) closeBtn.addEventListener('click', closeModal);
    if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

    if (modal) {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal();
      });
    }

    if (cadenceSelect) cadenceSelect.addEventListener('change', refreshSchedulerPreview);
    if (countSelect) countSelect.addEventListener('change', refreshSchedulerPreview);

    // Dry Run Action
    if (dryRunBtn) {
      dryRunBtn.addEventListener('click', async () => {
        const count = parseInt(countSelect?.value || '6', 10);
        const cadence = parseInt(cadenceSelect?.value || '2', 10);
        closeModal();
        try {
          toast('Starting Auto-Scheduler simulation in terminal drawer...', 'ok');
          const job = await apiPost('/api/run', {
            kind: 'auto_schedule',
            options: { count, slots_per_day: cadence, dry_run: true }
          });
          openTerminalDrawer();
          attachJobToPanel('run-publish', job.id);
        } catch (err) {
          toast(`Simulation error: ${err.message}`, 'error');
        }
      });
    }

    // Live Execution Action
    if (confirmBtn) {
      confirmBtn.addEventListener('click', async () => {
        const count = parseInt(countSelect?.value || '6', 10);
        const cadence = parseInt(cadenceSelect?.value || '2', 10);
        const schedCount = currentPreview.length || count;
        closeModal();

        try {
          toast(`Auto-scheduling ${schedCount} Shorts to YouTube cloud for 100% offline release...`, 'ok');
          const job = await apiPost('/api/run', {
            kind: 'auto_schedule',
            options: { count, slots_per_day: cadence, dry_run: false }
          });

          // Open terminal drawer to display real-time upload progress
          openTerminalDrawer();
          attachJobToPanel('run-publish', job.id);

          // Poll job completion to automatically refresh views & toast success
          const pollFinished = setInterval(async () => {
            const runningJobs = await apiGet('/api/jobs');
            if (runningJobs && Array.isArray(runningJobs)) {
              const active = runningJobs.find(j => j.id === job.id);
              if (!active || active.status !== 'running') {
                clearInterval(pollFinished);
                await refreshLibrary();
                await refreshPublishQueue();
                updateScheduledBadges();
                toast('Auto-scheduling complete. All videos safely pre-uploaded to YouTube cloud.', 'ok');
              }
            }
          }, 2500);

        } catch (err) {
          toast(`Auto-scheduler error: ${err.message}`, 'error');
        }
      });
    }
  }

  window.shortsAppOpenUploadTerminal = function (shortId) {
    const upload = state.activeUploads && state.activeUploads[shortId];
    if (upload && upload.jobId) {
      const drawerTitle = document.getElementById('terminal-drawer-title');
      if (drawerTitle) drawerTitle.textContent = `Upload · Short #${shortId} (${upload.handle})`;
    }
    openTerminalDrawer();
  };

  async function startCardUpload(shortId, account, publishAt = null) {
    state.activeUploads = state.activeUploads || {};
    const handleText = account.handle || account.name || '@YouTube';
    const isScheduled = !!publishAt;

    state.activeUploads[shortId] = {
      jobId: null,
      accountId: account.id,
      handle: handleText,
      percent: 15,
      isScheduled: isScheduled,
      publishAt: publishAt,
      text: isScheduled ? `Scheduling for ${formatScheduledDate(publishAt)}...` : `Connecting to ${handleText}...`,
      status: 'running'
    };

    // Update specific card in DOM immediately without re-rendering entire grid
    const card = document.querySelector(`.publish-card[data-card-id="${shortId}"]`);
    if (card) {
      const btn = card.querySelector('.publish-btn-quick');
      if (btn) {
        btn.outerHTML = `
          <div class="publish-card-progress" id="card-progress-${shortId}">
            <div class="card-progress-top">
              <div class="card-progress-status">
                <span class="card-progress-spinner" id="card-spinner-${shortId}"></span>
                <span class="card-progress-text" id="card-text-${shortId}">${escapeHtml(state.activeUploads[shortId].text)}</span>
              </div>
              <div style="display:flex; align-items:center; gap:6px;">
                <span class="card-progress-num" id="card-num-${shortId}">15%</span>
                <button type="button" class="btn-card-terminal" onclick="window.shortsAppOpenUploadTerminal(${shortId})" title="Inspect live upload in Terminal Drawer">
                  <svg class="icon"><use href="#i-terminal"/></svg>
                  <span>Terminal</span>
                </button>
              </div>
            </div>
            <div class="card-progress-track">
              <div class="card-progress-fill" id="card-fill-${shortId}" style="width: 15%;"></div>
            </div>
          </div>
        `;
      }
    }

    try {
      const options = { id: shortId, account_id: account.id };
      if (publishAt) {
        options.publish_at = publishAt;
      }
      const job = await apiPost('/api/run', {
        kind: 'upload_single',
        options
      });

      state.activeUploads[shortId].jobId = job.id;
      if (isScheduled) {
        toast(`Scheduling Short #${shortId} to ${handleText} for offline release...`, 'ok');
      } else {
        toast(`Publishing Short #${shortId} to ${handleText}...`, 'ok');
      }
      attachJobToPanel('run-publish', job.id);

      pollCardUpload(shortId, job.id, account, publishAt);
    } catch (err) {
      toast(`Upload error: ${err.message}`, 'error');
      const progressEl = document.getElementById(`card-progress-${shortId}`);
      if (progressEl) {
        progressEl.classList.add('error');
        const textEl = document.getElementById(`card-text-${shortId}`);
        const spinnerEl = document.getElementById(`card-spinner-${shortId}`);
        if (textEl) textEl.textContent = 'Upload failed';
        if (spinnerEl) {
          spinnerEl.className = 'card-progress-spinner fail';
          spinnerEl.textContent = '✗';
        }
      }
      setTimeout(() => {
        delete state.activeUploads[shortId];
        refreshPublishQueue();
      }, 3000);
    }
  }

  async function pollCardUpload(shortId, jobId, account, publishAt = null) {
    let afterSeq = 0;
    let currentPercent = 15;
    const handleText = account.handle || account.name || '@YouTube';
    const isScheduled = !!publishAt;

    const checkJob = async () => {
      // Check if still tracked
      if (!state.activeUploads || !state.activeUploads[shortId]) return;

      try {
        const data = await apiGet(`/api/jobs/${jobId}/log?after=${afterSeq}`);
        if (!data || !data.job) {
          setTimeout(checkJob, 750);
          return;
        }

        const { job, lines } = data;
        if (lines && lines.length > 0) {
          afterSeq = lines[lines.length - 1].n || (afterSeq + lines.length);

          // Parse log lines for progress stages
          for (const l of lines) {
            const t = l.t || '';
            if (t.includes('Checking quota') || t.includes('Preparing')) {
              currentPercent = Math.max(currentPercent, 25);
              updateCardProgressUI(shortId, currentPercent, isScheduled ? 'Preparing scheduled upload...' : 'Preparing upload...');
            } else if (t.includes('Fetching video') || t.includes('download_from_storage') || t.includes('CLOUD-FIRST') || t.includes('LOCAL FALLBACK')) {
              currentPercent = Math.max(currentPercent, 50);
              updateCardProgressUI(shortId, currentPercent, 'Fetching video file...');
            } else if (t.includes('Uploading to YouTube') || t.includes('upload_short')) {
              currentPercent = Math.max(currentPercent, 75);
              updateCardProgressUI(shortId, currentPercent, isScheduled ? `Pre-uploading to ${handleText} (Private)...` : `Uploading to ${handleText}...`);
            } else if (t.includes('Successfully scheduled') || t.includes('status.publishAt') || t.includes('Scheduled for offline release')) {
              currentPercent = 100;
              updateCardProgressUI(shortId, 100, `Scheduled for ${formatScheduledDate(publishAt)}!`);
            } else if (t.includes('Successfully published') || t.includes('Duplicate detected') || t.includes('Marked existing Short')) {
              currentPercent = 100;
              updateCardProgressUI(shortId, 100, isScheduled ? `Scheduled for ${formatScheduledDate(publishAt)}!` : `Published to ${handleText}!`);
            } else if (t.includes('Quota Limit Reached')) {
              handleCardUploadError(shortId, 'Quota limit reached');
              return;
            } else if (t.includes('[X] Upload failed') || t.includes('Error:')) {
              handleCardUploadError(shortId, 'Upload failed');
              return;
            }
          }
        }

        if (job.status === 'running') {
          // Incrementally advance progress indicator smoothly
          if (currentPercent < 75 && currentPercent >= 25) {
            currentPercent = Math.min(70, currentPercent + 3);
            updateCardProgressUI(shortId, currentPercent, isScheduled ? `Pre-uploading to ${handleText}...` : `Uploading to ${handleText}...`);
          } else if (currentPercent >= 75 && currentPercent < 95) {
            currentPercent = Math.min(94, currentPercent + 2);
            updateCardProgressUI(shortId, currentPercent, isScheduled ? `Configuring offline schedule on YouTube...` : `Finalizing on YouTube...`);
          }
          setTimeout(checkJob, 750);
        } else if (job.status === 'done' || job.exitCode === 0) {
          // Success!
          const successMsg = isScheduled ? `Scheduled for ${formatScheduledDate(publishAt)}!` : `Published to ${handleText}!`;
          updateCardProgressSuccess(shortId, successMsg, isScheduled);
        } else {
          // Failed
          handleCardUploadError(shortId, 'Upload failed');
        }
      } catch (err) {
        setTimeout(checkJob, 1000);
      }
    };

    setTimeout(checkJob, 600);
  }

  function updateCardProgressUI(shortId, percent, text) {
    if (state.activeUploads && state.activeUploads[shortId]) {
      state.activeUploads[shortId].percent = percent;
      state.activeUploads[shortId].text = text;
    }
    const fill = document.getElementById(`card-fill-${shortId}`);
    const num = document.getElementById(`card-num-${shortId}`);
    const txt = document.getElementById(`card-text-${shortId}`);
    if (fill) fill.style.width = `${percent}%`;
    if (num) num.textContent = `${percent}%`;
    if (txt) txt.textContent = text;
  }

  function updateCardProgressSuccess(shortId, text, isScheduled = false) {
    if (state.activeUploads && state.activeUploads[shortId]) {
      state.activeUploads[shortId].status = 'success';
      state.activeUploads[shortId].percent = 100;
      state.activeUploads[shortId].text = text;
    }
    const progressEl = document.getElementById(`card-progress-${shortId}`);
    const fill = document.getElementById(`card-fill-${shortId}`);
    const num = document.getElementById(`card-num-${shortId}`);
    const txt = document.getElementById(`card-text-${shortId}`);
    const spinner = document.getElementById(`card-spinner-${shortId}`);

    if (progressEl) progressEl.classList.add('success');
    if (fill) fill.style.width = '100%';
    if (num) num.textContent = '100%';
    if (txt) txt.textContent = text;
    if (spinner) {
      spinner.className = 'card-progress-spinner done';
      spinner.textContent = '✓';
    }

    if (isScheduled) {
      toast(`Short #${shortId} scheduled on YouTube! Offline release guaranteed.`, 'ok');
    } else {
      toast(`Successfully published Short #${shortId} to YouTube!`, 'ok');
    }

    setTimeout(() => {
      delete state.activeUploads[shortId];
      refreshPublishQueue();
      refreshOverview();
      refreshLibrary();
    }, 2400);
  }

  function handleCardUploadError(shortId, errorMsg) {
    if (state.activeUploads && state.activeUploads[shortId]) {
      state.activeUploads[shortId].status = 'error';
      state.activeUploads[shortId].text = errorMsg;
    }
    const progressEl = document.getElementById(`card-progress-${shortId}`);
    const txt = document.getElementById(`card-text-${shortId}`);
    const spinner = document.getElementById(`card-spinner-${shortId}`);

    if (progressEl) progressEl.classList.add('error');
    if (txt) txt.textContent = errorMsg;
    if (spinner) {
      spinner.className = 'card-progress-spinner fail';
      spinner.textContent = '✗';
    }

    toast(`Upload failed for Short #${shortId}`, 'error');

    setTimeout(() => {
      delete state.activeUploads[shortId];
      refreshPublishQueue();
    }, 3200);
  }

  function initAccountSwitcher() {
    const dropdown = document.getElementById('account-switch-dropdown');
    const btn = document.getElementById('account-switch-btn');
    const menu = document.getElementById('account-switch-menu');

    // Sidebar Target Account Elements
    const sideBox = document.getElementById('sidebar-account-box');
    const sideCard = document.getElementById('sidebar-account-card');
    const sideToggleBtn = document.getElementById('sidebar-account-toggle-btn');
    const sideMenu = document.getElementById('sidebar-account-menu');

    async function switchAccount(targetId) {
      try {
        const res = await apiPost('/api/accounts/switch', { id: targetId });
        updateAccountUI(res);
        const active = (res.accounts || []).find(a => a.id === res.active_id);
        toast(`Switched target account to ${active ? (active.handle || active.name) : targetId}`, 'ok');
      } catch (err) {
        toast(`Failed to switch account: ${err.message}`, 'error');
      }
    }

    async function toggleNextAccount() {
      if (!state.accounts || !state.accounts.accounts || state.accounts.accounts.length < 2) return;
      const currentId = state.accounts.active_id;
      const other = state.accounts.accounts.find(a => a.id !== currentId) || state.accounts.accounts[0];
      if (other) {
        await switchAccount(other.id);
      }
    }

    // Sidebar 1-click swap button
    if (sideToggleBtn && !sideToggleBtn.dataset.bound) {
      sideToggleBtn.dataset.bound = 'true';
      sideToggleBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await toggleNextAccount();
      });
    }

    // Sidebar Account Card click
    if (sideCard && !sideCard.dataset.bound) {
      sideCard.dataset.bound = 'true';
      sideCard.addEventListener('click', async (e) => {
        e.stopPropagation();
        const sidebar = document.getElementById('sidebar');
        const isCollapsed = sidebar && sidebar.classList.contains('collapsed');
        if (isCollapsed) {
          // When collapsed, clicking the avatar circle directly switches to the other account
          await toggleNextAccount();
        } else {
          // When expanded, toggle the target account menu
          if (sideBox) sideBox.classList.toggle('open');
        }
      });
    }

    // Sidebar Account Menu click
    if (sideMenu && !sideMenu.dataset.bound) {
      sideMenu.dataset.bound = 'true';
      sideMenu.addEventListener('click', async (e) => {
        const item = e.target.closest('.sidebar-account-menu-item');
        if (!item) return;
        e.stopPropagation();
        const targetId = item.dataset.accountId;
        if (sideBox) sideBox.classList.remove('open');
        await switchAccount(targetId);
      });
    }

    if (dropdown && !dropdown.dataset.bound) {
      dropdown.dataset.bound = 'true';

      if (btn) {
        btn.addEventListener('click', (e) => {
          e.stopPropagation();
          const isOpen = dropdown.classList.toggle('open');
          btn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
        });
      }

      if (menu) {
        menu.addEventListener('click', async (e) => {
          const authBtn = e.target.closest('.btn-auth-account');
          if (authBtn) {
            e.stopPropagation();
            const authId = authBtn.dataset.authId;
            dropdown.classList.remove('open');
            if (btn) btn.setAttribute('aria-expanded', 'false');
            try {
              toast('Launching YouTube OAuth consent... Check terminal or browser!', 'ok');
              const job = await apiPost('/api/accounts/auth', { id: authId });
              attachJobToPanel('run-system', job.id);
              navigate('system');
            } catch (err) {
              toast(`Auth failed: ${err.message}`, 'error');
            }
            return;
          }

          const item = e.target.closest('.account-menu-item');
          if (!item) return;
          e.stopPropagation();
          const targetId = item.dataset.accountId;
          dropdown.classList.remove('open');
          if (btn) btn.setAttribute('aria-expanded', 'false');

          await switchAccount(targetId);
        });
      }
    }

    // Close menus on outside click
    document.addEventListener('click', (e) => {
      if (dropdown && !dropdown.contains(e.target)) {
        dropdown.classList.remove('open');
        if (btn) btn.setAttribute('aria-expanded', 'false');
      }
      if (sideBox && !sideBox.contains(e.target)) {
        sideBox.classList.remove('open');
      }
    });

    // Close menus on Escape
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        if (dropdown && dropdown.classList.contains('open')) {
          dropdown.classList.remove('open');
          if (btn) btn.setAttribute('aria-expanded', 'false');
        }
        if (sideBox && sideBox.classList.contains('open')) {
          sideBox.classList.remove('open');
        }
      }
    });

    apiGet('/api/accounts').then(res => {
      if (res) updateAccountUI(res);
    });
  }

  // ─────────────────────────────────────────────────────────────
  // Live Stream Player & Live Agent Workspace
  // ─────────────────────────────────────────────────────────────
  function extractYouTubeVideoId(url) {
    if (!url) return null;
    const str = String(url).trim();
    const m = str.match(/(?:youtu\.be\/|youtube\.com\/(?:embed\/|v\/|watch\?v=|live\/|shorts\/))([\w-]{11})/i);
    if (m) return m[1];
    if (/^[\w-]{11}$/.test(str)) return str;
    return null;
  }

  function setLivePlayerSource(url) {
    const videoId = extractYouTubeVideoId(url);
    const iframe = document.getElementById('live-stream-iframe');
    const placeholder = document.getElementById('live-player-placeholder');
    const extYt = document.getElementById('btn-live-external-yt');
    const chatIframe = document.getElementById('live-chat-iframe');
    const streamTitle = document.getElementById('live-player-stream-title');
    const streamSub = document.getElementById('live-player-stream-sub');
    const statusText = document.getElementById('live-agent-status-text');
    const statusDot = document.getElementById('live-agent-status-dot');

    if (!videoId) {
      state.activeLiveStreamUrl = '';
      state.activeLiveVideoId = '';
      if (iframe) iframe.src = '';
      if (chatIframe) chatIframe.src = '';
      if (placeholder) placeholder.style.display = 'flex';
      if (extYt) extYt.style.display = 'none';
      if (streamTitle) streamTitle.textContent = 'No Live Stream Selected';
      if (streamSub) streamSub.textContent = 'Enter any active YouTube livestream link above to begin monitoring.';
      if (statusText) statusText.textContent = 'Ready to Watch';
      if (statusDot) statusDot.style.background = '#888';
      return;
    }

    state.activeLiveStreamUrl = url;
    state.activeLiveVideoId = videoId;

    if (iframe) {
      iframe.src = `https://www.youtube.com/embed/${videoId}?autoplay=1&mute=1&enablejsapi=1`;
    }
    if (placeholder) placeholder.style.display = 'none';

    if (extYt) {
      extYt.href = `https://www.youtube.com/watch?v=${videoId}`;
      extYt.style.display = 'inline-flex';
    }

    if (chatIframe) {
      chatIframe.src = `https://www.youtube.com/live_chat?v=${videoId}&embed_domain=${window.location.hostname}`;
    }

    if (streamTitle) streamTitle.textContent = `Live Stream (${videoId})`;
    if (streamSub) streamSub.textContent = `Streaming Live · Click speaker icon on player to unmute`;
    if (statusText) statusText.textContent = 'STREAMING LIVE';
    if (statusDot) statusDot.style.background = '#ff0033';
  }

  let liveAgentPollTimer = null;
  let liveAgentAfterSeq = 0;
  let currentLiveAgentJobId = null;

  window.shortsAppOpenLiveTerminal = function (jobId) {
    const drawerTitle = document.getElementById('terminal-drawer-title');
    const drawerChip = document.getElementById('terminal-drawer-chip');
    const drawerStopBtn = document.getElementById('terminal-drawer-stop-btn');
    if (drawerTitle) drawerTitle.textContent = `Autonomous Live Clipper · ${jobId || ''}`;
    if (drawerChip) {
      drawerChip.textContent = 'running';
      drawerChip.className = 'chip';
    }
    if (drawerStopBtn) {
      drawerStopBtn.style.display = 'inline-flex';
      drawerStopBtn.disabled = false;
      drawerStopBtn.onclick = async () => {
        drawerStopBtn.disabled = true;
        if (currentLiveAgentJobId) {
          await apiPost(`/api/jobs/${currentLiveAgentJobId}/stop`, {});
          toast('Live stream monitoring stopped', 'info');
          stopLiveAgentPolling();
          refreshLiveAgentView();
        }
      };
    }
    openTerminalDrawer();
  };

  function stopLiveAgentPolling() {
    if (liveAgentPollTimer) {
      clearTimeout(liveAgentPollTimer);
      liveAgentPollTimer = null;
    }
    currentLiveAgentJobId = null;
    liveAgentAfterSeq = 0;
  }

  function startLiveAgentPolling(jobId) {
    if (currentLiveAgentJobId === jobId && liveAgentPollTimer) return;
    stopLiveAgentPolling();
    currentLiveAgentJobId = jobId;
    liveAgentAfterSeq = 0;
    pollLiveAgentLoop();
  }

  async function pollLiveAgentLoop() {
    if (!currentLiveAgentJobId) return;
    try {
      const data = await apiGet(`/api/jobs/${currentLiveAgentJobId}/log?after=${liveAgentAfterSeq}`);
      if (data && data.job) {
        const { job, lines } = data;
        if (lines && lines.length > 0) {
          liveAgentAfterSeq = lines[lines.length - 1].n;
          const drawerConsole = document.getElementById('terminal-drawer-console');
          if (drawerConsole && document.getElementById('terminal-drawer')?.classList.contains('open')) {
            appendDrawerLogs(lines, { jobId: currentLiveAgentJobId, afterSeq: liveAgentAfterSeq });
          }
        }
        updateLiveAgentProgressUI(job, lines);

        if (job.status === 'running') {
          liveAgentPollTimer = setTimeout(pollLiveAgentLoop, 1200);
        } else {
          handleLiveAgentJobEnd(job);
        }
      } else {
        liveAgentPollTimer = setTimeout(pollLiveAgentLoop, 1500);
      }
    } catch (err) {
      liveAgentPollTimer = setTimeout(pollLiveAgentLoop, 2000);
    }
  }

  function updateLiveAgentProgressUI(job, lines) {
    const progressBox = document.getElementById('live-agent-progress-box');
    const startRow = document.getElementById('live-agent-start-row');
    const activeChip = document.getElementById('live-agent-active-chip');
    if (!progressBox) return;

    progressBox.style.display = 'flex';
    if (startRow) startRow.style.display = 'none';
    if (activeChip) activeChip.style.display = 'inline-flex';

    const pulseRing = document.getElementById('live-agent-pulse-ring');
    const statusText = document.getElementById('live-agent-status-text');
    const pctLabel = document.getElementById('live-agent-pct-label');
    const barFill = document.getElementById('live-agent-bar-fill');
    const stageDetail = document.getElementById('live-agent-stage-detail');
    const cycleBadge = document.getElementById('live-agent-cycle-badge');
    const logTicker = document.getElementById('live-agent-log-ticker');

    const lastLine = (lines && lines.length ? lines[lines.length - 1].t : (job.lastLine || '')).trim();

    let pct = 15;
    let statusTitle = 'Monitoring Stream...';
    let detailMsg = 'Autonomous agent watching for broadcast...';
    let pulseClass = 'status-pulse-ring';
    let barClass = 'workflow-bar-fill';
    let cycleStr = 'Cycle #1';

    const cycleMatch = lastLine.match(/\[Cycle #(\d+)\]/i);
    if (cycleMatch) {
      cycleStr = `Cycle #${cycleMatch[1]}`;
    } else if (state.lastLiveCycleStr) {
      cycleStr = state.lastLiveCycleStr;
    }
    state.lastLiveCycleStr = cycleStr;

    const lower = lastLine.toLowerCase();

    if (lower.includes('checking if stream is live')) {
      pct = 20;
      statusTitle = 'Checking Stream Liveness';
      detailMsg = 'Querying YouTube for active broadcast...';
    } else if (lower.includes('stream is currently offline') || lower.includes('stream is offline') || lower.includes('offline')) {
      pct = 12;
      statusTitle = 'Stream Offline (Polling)';
      detailMsg = 'Broadcaster offline · Retrying in 30s...';
      pulseClass = 'status-pulse-ring waiting';
      barClass = 'workflow-bar-fill waiting';
    } else if (lower.includes('event has ended') || lower.includes('live event has ended')) {
      pct = 100;
      statusTitle = 'Broadcast Has Ended';
      detailMsg = 'Stream finished. Use Create section for VODs.';
      pulseClass = 'status-pulse-ring error';
      barClass = 'workflow-bar-fill error';
    } else if (lower.includes('active broadcast detected') || lower.includes('active broadcast')) {
      pct = 32;
      statusTitle = 'Broadcast Detected!';
      detailMsg = 'Connected to active live stream...';
      pulseClass = 'status-pulse-ring';
    } else if (lower.includes('capturing') && lower.includes('rolling buffer')) {
      pct = 45;
      statusTitle = 'Capturing Live Buffer';
      detailMsg = 'Recording live rolling chunk via FFmpeg...';
    } else if (lower.includes('captured') && lower.includes('live buffer')) {
      pct = 55;
      statusTitle = 'Live Buffer Captured';
      detailMsg = 'Buffer extracted · Preparing audio stream...';
    } else if (lower.includes('transcribing') || lower.includes('whisper')) {
      pct = 68;
      statusTitle = 'Transcribing Speech';
      detailMsg = 'Word-level transcription via faster-whisper...';
    } else if (lower.includes('viral') || lower.includes('peak') || lower.includes('scoring')) {
      pct = 78;
      statusTitle = 'Detecting Viral Moments';
      detailMsg = 'Scoring hook and sentence-snapping clip...';
    } else if (lower.includes('reframing') || lower.includes('9:16') || lower.includes('crop')) {
      pct = 85;
      statusTitle = 'Reframing 9:16 Short';
      detailMsg = 'Applying vertical crop with background blur...';
    } else if (lower.includes('subtitles') || lower.includes('burning') || lower.includes('karaoke')) {
      pct = 92;
      statusTitle = 'Burning Kinetic Captions';
      detailMsg = 'Rendering word-highlight karaoke subtitles...';
    } else if (lower.includes('bleep') || lower.includes('censor')) {
      pct = 94;
      statusTitle = 'Filtering Profanity';
      detailMsg = 'Applying 1000Hz censor bleeps...';
    } else if (lower.includes('uploading') || lower.includes('supabase') || lower.includes('livestream-shorts')) {
      pct = 97;
      statusTitle = 'Uploading to Cloud';
      detailMsg = 'Saving to isolated livestream-shorts bucket...';
    } else if (lower.includes('live short created') || lower.includes('created & uploaded')) {
      pct = 100;
      statusTitle = 'Short Created & Stored!';
      detailMsg = 'Saved to isolated livestream-shorts bucket!';
      pulseClass = 'status-pulse-ring done';
      barClass = 'workflow-bar-fill done';
    }

    if (pulseRing) pulseRing.className = pulseClass;
    if (statusText) statusText.textContent = statusTitle;
    if (pctLabel) pctLabel.textContent = `${pct}%`;
    if (barFill) {
      barFill.style.width = `${pct}%`;
      barFill.className = barClass;
    }
    if (stageDetail) stageDetail.textContent = detailMsg;
    if (cycleBadge) cycleBadge.textContent = cycleStr;
    if (logTicker && lastLine) {
      logTicker.textContent = `> ${lastLine}`;
    }
  }

  function handleLiveAgentJobEnd(job) {
    stopLiveAgentPolling();
    const progressBox = document.getElementById('live-agent-progress-box');
    const startRow = document.getElementById('live-agent-start-row');
    const activeChip = document.getElementById('live-agent-active-chip');
    const statusText = document.getElementById('live-agent-status-text');
    const barFill = document.getElementById('live-agent-bar-fill');
    const pulseRing = document.getElementById('live-agent-pulse-ring');
    const stopBtn = document.getElementById('btn-live-stop-agent');

    if (activeChip) activeChip.style.display = 'none';

    if (job.status === 'stopped') {
      if (progressBox) progressBox.style.display = 'none';
      if (startRow) startRow.style.display = 'flex';
      toast('Live stream monitoring stopped', 'info');
    } else if (job.status === 'done') {
      if (statusText) statusText.textContent = 'Agent Monitoring Finished';
      if (barFill) {
        barFill.style.width = '100%';
        barFill.className = 'workflow-bar-fill done';
      }
      if (pulseRing) pulseRing.className = 'status-pulse-ring done';
      if (stopBtn) {
        stopBtn.innerHTML = '<svg class="icon" style="width:12px; height:12px;"><use href="#i-refresh"/></svg><span>Reset</span>';
        stopBtn.className = 'btn btn-ghost btn-xs';
        stopBtn.onclick = () => {
          if (progressBox) progressBox.style.display = 'none';
          if (startRow) startRow.style.display = 'flex';
          stopBtn.innerHTML = '<svg class="icon" style="width:12px; height:12px;"><use href="#i-stop"/></svg><span>Stop Agent</span>';
          stopBtn.className = 'btn btn-danger btn-xs';
        };
      }
    } else if (job.status === 'failed') {
      if (statusText) statusText.textContent = 'Agent Halted';
      if (barFill) barFill.className = 'workflow-bar-fill error';
      if (pulseRing) pulseRing.className = 'status-pulse-ring error';
      if (stopBtn) {
        stopBtn.innerHTML = '<svg class="icon" style="width:12px; height:12px;"><use href="#i-x"/></svg><span>Dismiss</span>';
        stopBtn.className = 'btn btn-ghost btn-xs';
        stopBtn.onclick = () => {
          if (progressBox) progressBox.style.display = 'none';
          if (startRow) startRow.style.display = 'flex';
          stopBtn.innerHTML = '<svg class="icon" style="width:12px; height:12px;"><use href="#i-stop"/></svg><span>Stop Agent</span>';
          stopBtn.className = 'btn btn-danger btn-xs';
        };
      }
    }
  }

  async function refreshLiveAgentView() {
    // Check if an active monitor job is running
    const jobs = await apiGet('/api/jobs');
    const activeMonitor = (jobs || []).find(j => j.kind === 'monitor' && j.status === 'running');

    const streamUrlInput = document.getElementById('live-agent-stream-url');
    const activeChip = document.getElementById('live-agent-active-chip');
    const progressBox = document.getElementById('live-agent-progress-box');
    const startRow = document.getElementById('live-agent-start-row');
    const stopBtn = document.getElementById('btn-live-stop-agent');
    const viewTerminalBtn = document.getElementById('btn-live-view-terminal');

    if (viewTerminalBtn) {
      viewTerminalBtn.onclick = () => {
        window.shortsAppOpenLiveTerminal(activeMonitor ? activeMonitor.id : '');
      };
    }

    if (activeMonitor) {
      if (activeChip) activeChip.style.display = 'inline-flex';
      if (startRow) startRow.style.display = 'none';
      if (progressBox) progressBox.style.display = 'flex';

      if (stopBtn) {
        stopBtn.disabled = false;
        stopBtn.onclick = async () => {
          stopBtn.disabled = true;
          try {
            await apiPost(`/api/jobs/${activeMonitor.id}/stop`, {});
          } catch (e) { }
          toast('Live stream monitoring stopped', 'info');
          stopLiveAgentPolling();
          if (progressBox) progressBox.style.display = 'none';
          if (startRow) startRow.style.display = 'flex';
          if (activeChip) activeChip.style.display = 'none';
          refreshLiveAgentView();
        };
      }

      startLiveAgentPolling(activeMonitor.id);

      if (activeMonitor.target && (!state.activeLiveStreamUrl || (streamUrlInput && streamUrlInput.value !== activeMonitor.target))) {
        if (streamUrlInput) streamUrlInput.value = activeMonitor.target;
        setLivePlayerSource(activeMonitor.target);
      }
    } else {
      stopLiveAgentPolling();
      if (activeChip) activeChip.style.display = 'none';
      if (progressBox) progressBox.style.display = 'none';
      if (startRow) startRow.style.display = 'flex';

      // If input already has a URL but player is empty
      if (streamUrlInput && streamUrlInput.value.trim() && !state.activeLiveStreamUrl) {
        setLivePlayerSource(streamUrlInput.value.trim());
      }
    }

    // Populate recent live clips
    const clipsList = document.getElementById('live-session-clips-list');
    const clipsBadge = document.getElementById('live-clips-count-badge');
    const library = state.library || [];
    const liveClips = library.filter(i => i.source === 'live' || i.source === 'stream' || i.source === 'post_live');

    if (clipsBadge) clipsBadge.textContent = `${liveClips.length} clips`;

    if (clipsList && liveClips.length > 0) {
      clipsList.innerHTML = liveClips.slice(0, 6).map(clip => `
        <div class="live-clip-item" style="padding:10px 12px; border-radius:var(--radius-md); background:rgba(255,255,255,0.03); border:1px solid rgba(255,255,255,0.06); display:flex; align-items:center; justify-content:space-between; gap:10px;">
          <div style="overflow:hidden;">
            <div style="font-size:12px; font-weight:600; color:var(--text-primary); text-overflow:ellipsis; overflow:hidden; white-space:nowrap;">${escapeHtml(clip.title)}</div>
            <div class="muted small" style="font-size:11px;">${formatDuration(clip.duration)} · Viral Score ${clip.score || 9}/10</div>
          </div>
          <button type="button" class="btn btn-ghost btn-xs" data-preview-id="${clip.id}" style="padding:4px 8px; flex-shrink:0;">
            <svg class="icon" style="width:12px; height:12px;"><use href="#i-play"/></svg>Preview
          </button>
        </div>
      `).join('');
    }
  }

  function initLiveAgentListeners() {
    const btnLoad = document.getElementById('btn-live-load-player');
    const inputUrl = document.getElementById('live-agent-stream-url');
    const btnClearUrl = document.getElementById('btn-live-clear-url');
    const btnDemo = document.getElementById('btn-live-load-demo');
    const btnReload = document.getElementById('btn-live-reload-stream');
    const btnToggleChat = document.getElementById('btn-live-toggle-chat');
    const btnCloseChat = document.getElementById('btn-close-live-chat');
    const chatCard = document.getElementById('live-chat-card');
    const chatToggleText = document.getElementById('live-chat-toggle-text');
    const btnStartAgent = document.getElementById('btn-live-start-agent');

    if (inputUrl && btnClearUrl) {
      const syncClearBtn = () => {
        const hasText = Boolean(inputUrl.value && inputUrl.value.trim().length > 0);
        btnClearUrl.style.display = hasText ? 'flex' : 'none';
      };

      inputUrl.addEventListener('input', () => {
        syncClearBtn();
        if (!inputUrl.value.trim() && state.activeLiveStreamUrl) {
          setLivePlayerSource('');
          toast('Live stream cleared', 'info');
        }
      });

      btnClearUrl.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        inputUrl.value = '';
        syncClearBtn();
        setLivePlayerSource('');
        toast('Live stream monitor cleared', 'info');
        inputUrl.focus();
      });

      syncClearBtn();
    }

    if (btnLoad && inputUrl) {
      btnLoad.addEventListener('click', () => {
        const val = inputUrl.value.trim();
        if (!val) {
          toast('Please enter a YouTube livestream URL', 'error');
          return;
        }
        setLivePlayerSource(val);
        if (btnClearUrl) btnClearUrl.style.display = 'flex';
        toast('Loaded live stream player', 'ok');
      });
      inputUrl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          e.preventDefault();
          btnLoad.click();
        }
      });
    }



    if (btnReload) {
      btnReload.addEventListener('click', () => {
        if (state.activeLiveStreamUrl) {
          setLivePlayerSource(state.activeLiveStreamUrl);
          toast('Live stream feed refreshed', 'info');
        }
      });
    }

    if (btnToggleChat && chatCard) {
      btnToggleChat.addEventListener('click', () => {
        const isHidden = chatCard.style.display === 'none';
        chatCard.style.display = isHidden ? 'block' : 'none';
        if (chatToggleText) chatToggleText.textContent = isHidden ? 'Hide Live Chat' : 'Show Live Chat';
        btnToggleChat.classList.toggle('active', isHidden);
      });
    }

    if (btnCloseChat && chatCard) {
      btnCloseChat.addEventListener('click', () => {
        chatCard.style.display = 'none';
        if (chatToggleText) chatToggleText.textContent = 'Show Live Chat';
        if (btnToggleChat) btnToggleChat.classList.remove('active');
      });
    }

    if (btnStartAgent) {
      btnStartAgent.addEventListener('click', async () => {
        const url = (inputUrl ? inputUrl.value.trim() : '') || state.activeLiveStreamUrl;
        if (!url) {
          toast('Enter a livestream URL first', 'error');
          return;
        }
        const chunk = parseInt(getSegmentedValue('live-buffer-segmented') || '150', 10);
        const poll = parseInt(getSegmentedValue('live-interval-segmented') || '45', 10);
        const autoUpload = document.getElementById('live-auto-publish-toggle') ? document.getElementById('live-auto-publish-toggle').checked : false;
        const enableCaptions = document.getElementById('live-enable-captions-toggle') ? document.getElementById('live-enable-captions-toggle').checked : false;

        const options = {
          url,
          once: false,
          chunk,
          poll,
          maxClips: 0,
          crop: 'blurred_background',
          autoUpload,
          enableCaptions
        };

        try {
          const job = await apiPost('/api/run', { kind: 'monitor', options });
          toast('Autonomous live stream monitoring started!', 'ok');
          const progressBox = document.getElementById('live-agent-progress-box');
          const startRow = document.getElementById('live-agent-start-row');
          const activeChip = document.getElementById('live-agent-active-chip');
          if (progressBox) progressBox.style.display = 'flex';
          if (startRow) startRow.style.display = 'none';
          if (activeChip) activeChip.style.display = 'inline-flex';
          startLiveAgentPolling(job.id);
          refreshLiveAgentView();
        } catch (err) {
          toast('Failed to start live monitor', 'error');
        }
      });
    }

    // Live preview sync inside Create section (#/create)
    const processUrlInput = document.getElementById('process-url');
    const btnProcessClear = document.getElementById('btn-process-clear-url');
    if (processUrlInput) {
      const syncProcessClearBtn = () => {
        if (btnProcessClear) {
          btnProcessClear.style.display = processUrlInput.value && processUrlInput.value.trim().length > 0 ? 'flex' : 'none';
        }
      };

      const updateCreatePreview = () => {
        syncProcessClearBtn();
        const previewBox = document.getElementById('create-live-preview-box');
        const previewIframe = document.getElementById('create-live-preview-iframe');
        if (!previewBox || !previewIframe) return;

        if (state.createMode === 'live') {
          const val = processUrlInput.value.trim();
          const vid = extractYouTubeVideoId(val);
          if (vid) {
            previewIframe.src = `https://www.youtube.com/embed/${vid}?autoplay=1&mute=1&enablejsapi=1`;
            previewBox.style.display = 'block';
          } else {
            previewBox.style.display = 'none';
            previewIframe.src = '';
          }
        } else {
          previewBox.style.display = 'none';
        }
      };

      processUrlInput.addEventListener('input', updateCreatePreview);
      processUrlInput.addEventListener('change', updateCreatePreview);

      if (btnProcessClear) {
        btnProcessClear.addEventListener('click', (e) => {
          e.preventDefault();
          e.stopPropagation();
          processUrlInput.value = '';
          syncProcessClearBtn();
          updateCreatePreview();
          toast('URL input cleared', 'info');
          processUrlInput.focus();
        });
      }

      syncProcessClearBtn();
    }
  }

  // ─────────────────────────────────────────────────────────────
  // Initialization
  // ─────────────────────────────────────────────────────────────
  document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    initNotificationsBar();
    initSidebarControls();
    initAccountSwitcher();
    initPublishAccountModal();
    initAutoSchedulerModal();
    initVideoModals();
    initControls();
    initCreateModes();
    initLiveAgentListeners();
    initTerminalDrawer();
    initSupabaseListeners();
    navigate();
    refreshOverview();
    refreshLongformVideos();

    // Check if any process/monitor/longform pipeline job is actively running on server
    apiGet('/api/jobs').then(jobs => {
      if (jobs && Array.isArray(jobs)) {
        const running = jobs.find(j => j.status === 'running' && (j.kind === 'process' || j.kind === 'monitor' || j.kind === 'longform'));
        if (running) {
          attachJobToPanel('run-process', running.id);
        } else {
          resetCreateWorkflowToDefault();
        }
      }
    });

    // Background poller
    setInterval(pollOverviewBackground, 3500);
  });

})();
