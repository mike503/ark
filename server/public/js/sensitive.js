/**
 * Sensitive content PIN lock (page mask, keypad modal, idle bump).
 * Activates when window.SENSITIVE_PAGE is true.
 * Optional hook: window.initEmpImageFetch(grid) after unlock.
 */

/**
 * Initialize sensitive content lock (page mask, PIN modal, localStorage).
 * Call on DOMContentLoaded when window.SENSITIVE_PAGE === true.
 * Requires window.SENSITIVE_LOCK_TIME (default 300).
 */
function initSensitiveLock() {
  if (!window.SENSITIVE_PAGE) return;
  const STORAGE_KEY = 'sensitive_unlock_expires';
  const lockTime = window.SENSITIVE_LOCK_TIME || 300;
  let countdownInterval = null;
  let currentExpiresAt = 0;
  let pageMaskEl = null;

  const lockIconSvg = '<path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M5 13a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v6a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2v-6z"/><path d="M11 16a1 1 0 1 0 2 0a1 1 0 0 0 -2 0"/><path d="M8 11v-4a4 4 0 1 1 8 0v4"/>';
  const unlockIconSvg = '<path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M5 11m0 1a1 1 0 0 1 1 -1h12a1 1 0 0 1 1 1v3a1 1 0 0 1 -1 1h-12a1 1 0 0 1 -1 -1z"/><path d="M12 16m-1 0a1 1 0 1 0 2 0a1 1 0 1 0 -2 0"/><path d="M8 11v-5a4 4 0 0 1 8 0"/>';

  function formatCountdown(sec) {
    if (sec <= 0) return '—';
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function ensurePageMask() {
    if (pageMaskEl) return pageMaskEl;
    const wrapper = document.querySelector('.page-wrapper');
    if (!wrapper) return null;
    wrapper.style.position = 'relative';
    pageMaskEl = document.createElement('div');
    pageMaskEl.id = 'sensitive-page-mask';
    pageMaskEl.style.cssText = 'position:absolute;inset:0;z-index:50;background:var(--tblr-bg-surface);pointer-events:auto;';
    pageMaskEl.innerHTML = `
      <div class="sensitive-mask-lock d-flex justify-content-center" style="position:absolute;top:200px;left:0;right:0;cursor:pointer;z-index:1;color:var(--tblr-muted)">
        <svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor" fill="none">
          <path stroke="none" d="M0 0h24v24H0z" fill="none"/>
          <path d="M5 13a2 2 0 0 1 2 -2h10a2 2 0 0 1 2 2v6a2 2 0 0 1 -2 2h-10a2 2 0 0 1 -2 -2v-6z"/>
          <path d="M11 16a1 1 0 1 0 2 0a1 1 0 0 0 -2 0"/>
          <path d="M8 11v-4a4 4 0 1 1 8 0v4"/>
        </svg>
      </div>`;
    wrapper.appendChild(pageMaskEl);
    pageMaskEl.querySelector('.sensitive-mask-lock')?.addEventListener('click', () => {
      document.querySelector('.sensitive-lock-trigger')?.click();
    });
    return pageMaskEl;
  }

  function showPageMask() {
    const el = ensurePageMask();
    if (el) el.style.display = '';
  }

  function hidePageMask() {
    if (pageMaskEl) pageMaskEl.style.display = 'none';
  }

  function setLockedUI() {
    if (countdownInterval) {
      clearInterval(countdownInterval);
      countdownInterval = null;
    }
    try { localStorage.removeItem(STORAGE_KEY); } catch (_) {}
    currentExpiresAt = 0;
    window.SENSITIVE_UNLOCKED = false;
    const icon = document.getElementById('sensitive-lock-icon');
    const timer = document.getElementById('sensitive-lock-timer');
    if (icon) icon.innerHTML = lockIconSvg;
    if (timer) timer.textContent = '—';
    showPageMask();
  }

  function setUnlockedUI(expiresAt) {
    currentExpiresAt = expiresAt;
    try { localStorage.setItem(STORAGE_KEY, String(expiresAt)); } catch (_) {}
    window.SENSITIVE_UNLOCKED = true;
    hidePageMask();
    const icon = document.getElementById('sensitive-lock-icon');
    if (icon) icon.innerHTML = unlockIconSvg;
    if (typeof window.initEmpImageFetch === 'function') {
      const grid = document.getElementById('filtered-grid') || document.getElementById('freeleech-grid');
      if (grid) window.initEmpImageFetch(grid);
    }
    if (countdownInterval) clearInterval(countdownInterval);
    const tick = () => {
      const sec = Math.max(0, currentExpiresAt - Math.floor(Date.now() / 1000));
      const timer = document.getElementById('sensitive-lock-timer');
      if (timer) timer.textContent = formatCountdown(sec);
      if (sec <= 0) setLockedUI();
    };
    tick();
    countdownInterval = setInterval(tick, 1000);
  }

  function clientBump() {
    if (!window.SENSITIVE_UNLOCKED) return;
    setUnlockedUI(Math.floor(Date.now() / 1000) + lockTime);
  }

  let bumpTimeout = null;
  function scheduleBump() {
    if (!window.SENSITIVE_UNLOCKED) return;
    if (bumpTimeout) clearTimeout(bumpTimeout);
    bumpTimeout = setTimeout(() => {
      bumpTimeout = null;
      clientBump();
    }, 800);
  }
  ['click', 'keydown'].forEach((ev) => {
    document.addEventListener(ev, scheduleBump, { passive: true });
  });

  (function createPinModal() {
    const el = document.createElement('div');
    el.innerHTML = `
      <div class="modal modal-blur fade" id="sensitive-pin-modal" tabindex="-1">
        <div class="modal-dialog modal-sm modal-dialog-centered">
          <div class="modal-content">
            <div class="modal-header">
              <h5 class="modal-title">Unlock</h5>
              <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
            </div>
            <div class="modal-body">
              <div class="sensitive-pin-dots d-flex justify-content-center gap-2 mb-4" style="letter-spacing:0.5rem;font-size:1.25rem">
                <span class="sensitive-pin-dot">•</span><span class="sensitive-pin-dot">•</span><span class="sensitive-pin-dot">•</span><span class="sensitive-pin-dot">•</span>
              </div>
              <div id="sensitive-pin-error" class="text-danger small text-center mb-3" style="display:none"></div>
              <style>
                .sensitive-pin-keypad{display:grid;grid-template-columns:repeat(3,1fr);gap:0.75rem;max-width:14rem;margin:0 auto}
                .sensitive-pin-keypad .sensitive-pin-key{aspect-ratio:1;border-radius:50%;border:1px solid var(--tblr-border-color);background:var(--tblr-bg-surface-secondary);font-size:1.25rem;font-weight:500;color:var(--tblr-body-color);padding:0;display:flex;align-items:center;justify-content:center}
                .sensitive-pin-keypad .sensitive-pin-key:hover{background:var(--tblr-bg-surface-tertiary)}
                .sensitive-pin-keypad .sensitive-pin-key[data-key="ok"]{background:var(--tblr-primary);color:var(--tblr-primary-fg);border-color:var(--tblr-primary)}
                .sensitive-pin-keypad .sensitive-pin-key[data-key="ok"]:hover{opacity:0.9}
              </style>
              <div class="sensitive-pin-keypad">
                <button type="button" class="sensitive-pin-key" data-key="1">1</button>
                <button type="button" class="sensitive-pin-key" data-key="2">2</button>
                <button type="button" class="sensitive-pin-key" data-key="3">3</button>
                <button type="button" class="sensitive-pin-key" data-key="4">4</button>
                <button type="button" class="sensitive-pin-key" data-key="5">5</button>
                <button type="button" class="sensitive-pin-key" data-key="6">6</button>
                <button type="button" class="sensitive-pin-key" data-key="7">7</button>
                <button type="button" class="sensitive-pin-key" data-key="8">8</button>
                <button type="button" class="sensitive-pin-key" data-key="9">9</button>
                <button type="button" class="sensitive-pin-key" data-key="b">⌫</button>
                <button type="button" class="sensitive-pin-key" data-key="0">0</button>
                <button type="button" class="sensitive-pin-key" data-key="ok">✓</button>
              </div>
            </div>
          </div>
        </div>
      </div>`;
    document.body.appendChild(el.firstElementChild);

    let pinDigits = '';
    const modal = document.getElementById('sensitive-pin-modal');
    const dots = modal?.querySelectorAll('.sensitive-pin-dot');
    const errEl = document.getElementById('sensitive-pin-error');
    const keys = modal?.querySelectorAll('.sensitive-pin-key');

    function updateDisplay() {
      if (dots) dots.forEach((dot, i) => { dot.style.opacity = i < pinDigits.length ? '1' : '0.3'; });
    }

    function openModal() {
      pinDigits = '';
      if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
      updateDisplay();
      if (window.bootstrap?.Modal) {
        bootstrap.Modal.getOrCreateInstance(modal).show();
      }
    }

    function handleKey(k) {
      if (k === 'b') {
        pinDigits = pinDigits.slice(0, -1);
        updateDisplay();
      } else if (k === 'ok') {
        if (!pinDigits) return;
        fetch('/api/sensitive/unlock', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pin: pinDigits }),
          credentials: 'same-origin'
        })
          .then((r) => r.json())
          .then((data) => {
            if (data.ok) {
              bootstrap.Modal.getOrCreateInstance(modal).hide();
              setUnlockedUI(Math.floor(Date.now() / 1000) + lockTime);
            } else {
              if (errEl) { errEl.textContent = data.error || 'Invalid PIN'; errEl.style.display = 'block'; }
              pinDigits = '';
              updateDisplay();
            }
          })
          .catch(() => {
            if (errEl) { errEl.textContent = 'Request failed'; errEl.style.display = 'block'; }
          });
      } else {
        pinDigits += k;
        updateDisplay();
        if (errEl) errEl.style.display = 'none';
      }
    }

    document.addEventListener('keydown', (e) => {
      if (!modal?.classList.contains('show')) return;
      const active = document.activeElement;
      if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.isContentEditable)) return;
      let k = null;
      if (e.key >= '0' && e.key <= '9') k = e.key;
      else if (e.key === 'Backspace') k = 'b';
      else if (e.key === 'Enter') k = 'ok';
      if (k) { e.preventDefault(); handleKey(k); }
    });

    if (keys) {
      keys.forEach((btn) => {
        btn.onclick = () => handleKey(btn.dataset.key);
      });
    }

    document.querySelector('.sensitive-lock-trigger')?.addEventListener('click', (e) => {
      e.preventDefault();
      if (window.SENSITIVE_UNLOCKED) { setLockedUI(); return; }
      openModal();
    });
  })();

  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (!stored) { setLockedUI(); return; }
    const expires = parseInt(stored, 10);
    const now = Math.floor(Date.now() / 1000);
    if (!isNaN(expires) && expires > now) setUnlockedUI(expires);
    else setLockedUI();
  } catch (_) {
    setLockedUI();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initSensitiveLock);
} else {
  initSensitiveLock();
}

if (typeof window !== 'undefined') {
  window.initSensitiveLock = initSensitiveLock;
}
