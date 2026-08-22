/**
 * BioDelta - Frontend Client Application
 * Gestión de estado, navegación temporal, sincronización Garmin con 2FA y visor interactivo.
 */

(function () {
  'use strict';

  // Estado global de la aplicación
  const state = {
    currentStart: null,
    currentEnd: null,
    isDemo: false,
    weeks: [],
    status: null,
    glossary: {},
    mfaSessionId: null,
    theme: localStorage.getItem('biodelta-theme') || 'light',
  };

  // Elementos DOM
  const dom = {
    html: document.documentElement,
    themeBtn: document.getElementById('theme-btn'),
    rangeSelect: document.getElementById('range-select'),
    btnPrev: document.getElementById('btn-prev-week'),
    btnNext: document.getElementById('btn-next-week'),
    mainContent: document.getElementById('main-content'),
    loadingView: document.getElementById('loading-view'),
    loadingMsg: document.getElementById('loading-msg'),
    onboardingView: document.getElementById('onboarding-view'),
    reportView: document.getElementById('report-view'),
    reportContainer: document.getElementById('report-container'),
    toastContainer: document.getElementById('toast-container'),

    // Modales
    modalSync: document.getElementById('modal-sync'),
    modalUpload: document.getElementById('modal-upload'),
    modalGlossary: document.getElementById('modal-glossary'),
    modalSettings: document.getElementById('modal-settings'),

    // Botones de Cabecera
    btnBrand: document.getElementById('brand-home'),
    btnOpenSync: document.getElementById('btn-open-sync'),
    btnOpenUpload: document.getElementById('btn-open-upload'),
    btnOpenDemo: document.getElementById('btn-open-demo'),
    btnOpenGlossary: document.getElementById('btn-open-glossary'),
    btnOpenSettings: document.getElementById('btn-open-settings'),
    btnPrint: document.getElementById('btn-print'),

    // Elementos de Sincronización / Auth
    syncAuthStatus: document.getElementById('sync-auth-status'),
    syncAuthText: document.getElementById('sync-auth-text'),
    syncStartDate: document.getElementById('sync-start-date'),
    syncEndDate: document.getElementById('sync-end-date'),
    btnStartSync: document.getElementById('btn-start-sync'),
    syncProgress: document.getElementById('sync-progress'),
    syncProgressMsg: document.getElementById('sync-progress-msg'),
    formLogin: document.getElementById('form-garmin-login'),
    loginEmail: document.getElementById('login-email'),
    loginPass: document.getElementById('login-password'),
    mfaBox: document.getElementById('sync-mfa-box'),
    mfaCode: document.getElementById('mfa-code'),
    btnSubmitMfa: document.getElementById('btn-submit-mfa'),

    // Upload
    dropZone: document.getElementById('drop-zone'),
    fileInput: document.getElementById('file-input'),
    btnBrowse: document.getElementById('btn-browse-file'),
    uploadStatus: document.getElementById('upload-status'),

    // Glosario
    glossarySearch: document.getElementById('modal-glossary-search'),
    glossaryCats: document.getElementById('glossary-cats'),
    glossaryContainer: document.getElementById('glossary-cards-container'),

    // Ajustes
    formSettings: document.getElementById('form-settings'),
    setSleep: document.getElementById('set-sleep'),
    setSteps: document.getElementById('set-steps'),
    setIntensity: document.getElementById('set-intensity'),
  };

  // ========================================================================
  // Inicialización
  // ========================================================================

  async function init() {
    initTheme();
    setupEventListeners();
    await checkAppStatus();
  }

  function initTheme() {
    dom.html.dataset.theme = state.theme;
    dom.themeBtn.textContent = state.theme === 'dark' ? '☀ Claro' : '☾ Oscuro';
    dom.themeBtn.setAttribute('aria-pressed', state.theme === 'dark');
  }

  function toggleTheme() {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    dom.html.dataset.theme = state.theme;
    dom.themeBtn.textContent = state.theme === 'dark' ? '☀ Claro' : '☾ Oscuro';
    dom.themeBtn.setAttribute('aria-pressed', state.theme === 'dark');
    try {
      localStorage.setItem('biodelta-theme', state.theme);
    } catch (e) {}
  }

  // ========================================================================
  // Estado del Sistema y Carga de Datos
  // ========================================================================

  async function checkAppStatus() {
    try {
      const res = await fetch('/api/status');
      const data = await res.json();
      state.status = data;

      updateAuthStatusUI(data.has_tokens);

      if (data.has_db && data.date_range.max) {
        await loadAvailableWeeks();
        await loadReport({ start: null, end: null, demo: false });
      } else {
        showOnboarding();
      }
    } catch (err) {
      console.error('Error al comprobar estado:', err);
      showToast('Error conectando con el servidor BioDelta local', 'error');
    }
  }

  function updateAuthStatusUI(hasTokens) {
    const indicator = dom.syncAuthStatus.querySelector('.status-indicator');
    if (hasTokens) {
      indicator.classList.add('ready');
      dom.syncAuthText.textContent = 'Sesión de Garmin Connect activa y lista';
    } else {
      indicator.classList.remove('ready');
      dom.syncAuthText.textContent = 'Sin sesión activa. Ve a la pestaña Cuenta para iniciar sesión.';
    }
  }

  async function loadAvailableWeeks() {
    try {
      const res = await fetch('/api/weeks');
      const data = await res.json();
      state.weeks = data.weeks || [];

      dom.rangeSelect.innerHTML = '';
      if (state.weeks.length === 0) {
        dom.rangeSelect.innerHTML = '<option value="">Sin semanas registradas</option>';
        return;
      }

      state.weeks.forEach((w, idx) => {
        const opt = document.createElement('option');
        opt.value = `${w.start}:${w.end}`;
        opt.textContent = w.label;
        if (idx === 0) opt.selected = true;
        dom.rangeSelect.appendChild(opt);
      });
    } catch (e) {
      console.error('Error cargando semanas:', e);
    }
  }

  async function loadReport({ start, end, demo = false }) {
    showLoading(demo ? 'Generando entorno de demostración...' : 'Cargando métricas de salud...');
    state.isDemo = demo;

    try {
      let url = '/api/report';
      const params = new URLSearchParams();
      if (demo) params.set('demo', '1');
      if (start) params.set('start', start);
      if (end) params.set('end', end);

      const qs = params.toString();
      if (qs) url += '?' + qs;

      const res = await fetch(url);
      const data = await res.json();

      if (data.status !== 'ok') {
        throw new Error(data.message || 'Error al cargar informe');
      }

      state.currentStart = data.start;
      state.currentEnd = data.end;

      // Inyectar HTML del informe
      dom.reportContainer.innerHTML = data.html;

      // Actualizar select de semanas si coincide
      const curKey = `${data.start}:${data.end}`;
      if (dom.rangeSelect.querySelector(`option[value="${curKey}"]`)) {
        dom.rangeSelect.value = curKey;
      }

      updateNavButtonsState(data.prev_week, data.next_week);
      showReport();
    } catch (err) {
      console.error('Error cargando reporte:', err);
      showToast(err.message, 'error');
      showOnboarding();
    }
  }

  function updateNavButtonsState(prevWeek, nextWeek) {
    if (!prevWeek || !state.weeks.length) {
      dom.btnPrev.disabled = false;
    }
    // Habilitar / deshabilitar según rango
    dom.btnPrev.dataset.start = prevWeek ? prevWeek.start : '';
    dom.btnPrev.dataset.end = prevWeek ? prevWeek.end : '';
    dom.btnNext.dataset.start = nextWeek ? nextWeek.start : '';
    dom.btnNext.dataset.end = nextWeek ? nextWeek.end : '';
  }

  // ========================================================================
  // Control de Vistas (Loading, Onboarding, Report)
  // ========================================================================

  function showLoading(msg = 'Cargando...') {
    dom.loadingMsg.textContent = msg;
    dom.loadingView.style.display = 'flex';
    dom.onboardingView.style.display = 'none';
    dom.reportView.style.display = 'none';
  }

  function showOnboarding() {
    dom.loadingView.style.display = 'none';
    dom.onboardingView.style.display = 'flex';
    dom.reportView.style.display = 'none';
  }

  function showReport() {
    dom.loadingView.style.display = 'none';
    dom.onboardingView.style.display = 'none';
    dom.reportView.style.display = 'block';
  }

  // ========================================================================
  // Sincronización Garmin y Autenticación 2FA
  // ========================================================================

  async function handleStartSync() {
    const startVal = dom.syncStartDate.value;
    const endVal = dom.syncEndDate.value;

    dom.btnStartSync.disabled = true;
    dom.syncProgress.style.display = 'block';
    dom.syncProgressMsg.textContent = 'Iniciando conexión con Garmin Connect...';

    try {
      const res = await fetch('/api/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_date: startVal || null, end_date: endVal || null }),
      });
      const data = await res.json();

      if (data.status === 'already_running') {
        showToast('Ya hay una sincronización en curso', 'warning');
      }

      pollSyncProgress();
    } catch (e) {
      dom.btnStartSync.disabled = false;
      dom.syncProgress.style.display = 'none';
      showToast('Error al iniciar sincronización: ' + e.message, 'error');
    }
  }

  function pollSyncProgress() {
    const timer = setInterval(async () => {
      try {
        const res = await fetch('/api/sync/status');
        const data = await res.json();

        dom.syncProgressMsg.textContent = data.message || 'Sincronizando...';

        if (data.status === 'completed') {
          clearInterval(timer);
          dom.btnStartSync.disabled = false;
          dom.syncProgress.style.display = 'none';
          closeModal('modal-sync');
          showToast('🎉 ¡Sincronización completada con éxito!', 'success');
          await loadAvailableWeeks();
          await loadReport({ start: null, end: null, demo: false });
        } else if (data.status === 'error') {
          clearInterval(timer);
          dom.btnStartSync.disabled = false;
          dom.syncProgress.style.display = 'none';
          showToast(`❌ ${data.message || 'Error en la sincronización'}`, 'error');
        }
      } catch (e) {
        clearInterval(timer);
        dom.btnStartSync.disabled = false;
        dom.syncProgress.style.display = 'none';
      }
    }, 1500);
  }

  async function handleGarminLogin(e) {
    e.preventDefault();
    const email = dom.loginEmail.value.trim();
    const password = dom.loginPass.value.trim();

    if (!email || !password) return;

    const btn = document.getElementById('btn-submit-login');
    btn.disabled = true;
    btn.textContent = 'Conectando con Garmin...';

    try {
      const res = await fetch('/api/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      btn.disabled = false;
      btn.textContent = 'Conectar y Autenticar';

      if (data.status === 'needs_mfa') {
        state.mfaSessionId = data.session_id;
        dom.formLogin.style.display = 'none';
        dom.mfaBox.style.display = 'block';
        dom.mfaCode.value = '';
        dom.mfaCode.focus();
        showToast('Garmin ha solicitado código 2FA', 'info');
      } else if (data.status === 'ok') {
        showToast('✅ ' + data.message, 'success');
        updateAuthStatusUI(true);
        switchTab('sync-tab-auto');
      } else {
        showToast('❌ ' + (data.message || 'Error de autenticación'), 'error');
      }
    } catch (err) {
      btn.disabled = false;
      btn.textContent = 'Conectar y Autenticar';
      showToast('Error conectando: ' + err.message, 'error');
    }
  }

  async function handleMfaSubmit() {
    const code = dom.mfaCode.value.trim();
    if (!code || !state.mfaSessionId) {
      showToast('Introduce el código 2FA', 'error');
      return;
    }

    dom.btnSubmitMfa.disabled = true;
    dom.btnSubmitMfa.textContent = 'Verificando...';

    try {
      const res = await fetch('/api/auth/mfa', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: state.mfaSessionId, code }),
      });
      const data = await res.json();
      dom.btnSubmitMfa.disabled = false;
      dom.btnSubmitMfa.textContent = 'Verificar';

      if (data.status === 'ok') {
        dom.mfaBox.style.display = 'none';
        dom.formLogin.style.display = 'block';
        dom.formLogin.reset();
        state.mfaSessionId = null;
        showToast('🎉 ¡2FA verificado con éxito!', 'success');
        updateAuthStatusUI(true);
        switchTab('sync-tab-auto');
      } else {
        showToast('❌ ' + (data.message || 'Código incorrecto'), 'error');
      }
    } catch (e) {
      dom.btnSubmitMfa.disabled = false;
      dom.btnSubmitMfa.textContent = 'Verificar';
      showToast('Error al verificar 2FA: ' + e.message, 'error');
    }
  }

  // ========================================================================
  // Drag & Drop / Carga de Archivo SQLite
  // ========================================================================

  async function handleFileUpload(file) {
    if (!file) return;
    dom.uploadStatus.style.display = 'block';
    dom.uploadStatus.className = 'upload-status-box';
    dom.uploadStatus.textContent = `Subiendo y validando ${file.name}...`;

    const formData = new FormData();
    formData.append('file', file);

    try {
      const res = await fetch('/api/upload', {
        method: 'POST',
        body: formData,
      });
      const data = await res.json();

      if (data.status === 'ok') {
        dom.uploadStatus.className = 'upload-status-box success';
        dom.uploadStatus.textContent = '✅ ' + data.message;
        setTimeout(async () => {
          closeModal('modal-upload');
          showToast('Base de datos cargada correctamente', 'success');
          await loadAvailableWeeks();
          await loadReport({ start: null, end: null, demo: false });
        }, 800);
      } else {
        dom.uploadStatus.className = 'upload-status-box error';
        dom.uploadStatus.textContent = '❌ ' + (data.message || 'Archivo inválido');
      }
    } catch (e) {
      dom.uploadStatus.className = 'upload-status-box error';
      dom.uploadStatus.textContent = 'Error subiendo archivo: ' + e.message;
    }
  }

  // ========================================================================
  // Glosario Interactivo
  // ========================================================================

  async function loadGlossaryData() {
    if (Object.keys(state.glossary).length > 0) return;
    try {
      const res = await fetch('/api/glossary');
      const data = await res.json();
      state.glossary = data.glossary || {};
      renderGlossaryCards();
    } catch (e) {
      console.error('Error cargando glosario:', e);
    }
  }

  function renderGlossaryCards() {
    dom.glossaryContainer.innerHTML = '';
    for (const [key, item] of Object.entries(state.glossary)) {
      const card = document.createElement('article');
      card.className = 'glossary-card';
      card.dataset.category = item.category;
      card.innerHTML = `
        <div class="glossary-card-header">
          <h4>${escapeHtml(item.title)}</h4>
          <span class="glossary-badge">${escapeHtml(item.category)}</span>
        </div>
        <p><strong>¿Qué es?</strong> ${escapeHtml(item.what)}</p>
        <p><strong>¿Por qué importa?</strong> ${escapeHtml(item.why)}</p>
        <p class="glossary-range"><strong>Rango orientativo:</strong> ${escapeHtml(item.range)}</p>
      `;
      dom.glossaryContainer.appendChild(card);
    }
  }

  function filterGlossary() {
    const q = (dom.glossarySearch.value || '').toLowerCase().trim();
    const activePill = dom.glossaryCats.querySelector('.cat-pill.active');
    const selectedCat = activePill ? activePill.dataset.cat : 'all';

    dom.glossaryContainer.querySelectorAll('.glossary-card').forEach(card => {
      const cat = card.dataset.category;
      const matchCat = (selectedCat === 'all' || cat === selectedCat);
      const matchText = !q || card.textContent.toLowerCase().includes(q);
      card.style.display = (matchCat && matchText) ? 'flex' : 'none';
    });
  }

  // ========================================================================
  // Event Listeners y Modales
  // ========================================================================

  function setupEventListeners() {
    dom.themeBtn.addEventListener('click', toggleTheme);
    dom.btnPrint.addEventListener('click', () => window.print());

    // Logo click -> Volver a portada / refrescar
    dom.btnBrand.addEventListener('click', () => {
      loadReport({ start: null, end: null, demo: false });
    });

    // Selector de rango de fechas
    dom.rangeSelect.addEventListener('change', (e) => {
      const val = e.target.value;
      if (!val) return;
      const [s, end] = val.split(':');
      loadReport({ start: s, end: end, demo: state.isDemo });
    });

    // Botones Time Travel
    dom.btnPrev.addEventListener('click', () => {
      if (dom.btnPrev.dataset.start && dom.btnPrev.dataset.end) {
        loadReport({ start: dom.btnPrev.dataset.start, end: dom.btnPrev.dataset.end, demo: state.isDemo });
      }
    });

    dom.btnNext.addEventListener('click', () => {
      if (dom.btnNext.dataset.start && dom.btnNext.dataset.end) {
        loadReport({ start: dom.btnNext.dataset.start, end: dom.btnNext.dataset.end, demo: state.isDemo });
      }
    });

    // Abrir Modales
    dom.btnOpenSync.addEventListener('click', () => openModal('modal-sync'));
    dom.btnOpenUpload.addEventListener('click', () => openModal('modal-upload'));
    dom.btnOpenDemo.addEventListener('click', () => loadReport({ start: null, end: null, demo: true }));
    dom.btnOpenGlossary.addEventListener('click', async () => {
      await loadGlossaryData();
      openModal('modal-glossary');
    });
    dom.btnOpenSettings.addEventListener('click', () => openModal('modal-settings'));

    // Tarjetas de Onboarding
    const cardGarmin = document.getElementById('card-connect-garmin');
    const cardUpload = document.getElementById('card-upload-file');
    const cardDemo = document.getElementById('card-demo-mode');
    if (cardGarmin) cardGarmin.addEventListener('click', () => openModal('modal-sync'));
    if (cardUpload) cardUpload.addEventListener('click', () => openModal('modal-upload'));
    if (cardDemo) cardDemo.addEventListener('click', () => loadReport({ start: null, end: null, demo: true }));

    // Cerrar Modales
    document.querySelectorAll('[data-close]').forEach(el => {
      el.addEventListener('click', () => closeModal(el.dataset.close));
    });

    document.querySelectorAll('.modal-overlay').forEach(modal => {
      modal.addEventListener('click', (e) => {
        if (e.target === modal) closeModal(modal.id);
      });
    });

    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        document.querySelectorAll('.modal-overlay.is-open').forEach(m => closeModal(m.id));
      }
    });

    // Tabs del Modal Sync
    document.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });

    // Sincronización y Auth
    dom.btnStartSync.addEventListener('click', handleStartSync);
    dom.formLogin.addEventListener('submit', handleGarminLogin);
    dom.btnSubmitMfa.addEventListener('click', handleMfaSubmit);

    // Drag & Drop
    dom.btnBrowse.addEventListener('click', () => dom.fileInput.click());
    dom.fileInput.addEventListener('change', (e) => {
      if (e.target.files.length) handleFileUpload(e.target.files[0]);
    });

    dom.dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dom.dropZone.classList.add('dragover');
    });

    dom.dropZone.addEventListener('dragleave', () => {
      dom.dropZone.classList.remove('dragover');
    });

    dom.dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dom.dropZone.classList.remove('dragover');
      if (e.dataTransfer.files.length) {
        handleFileUpload(e.dataTransfer.files[0]);
      }
    });

    // Glosario Búsqueda y Filtros
    dom.glossarySearch.addEventListener('input', filterGlossary);
    dom.glossaryCats.querySelectorAll('.cat-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        dom.glossaryCats.querySelectorAll('.cat-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        filterGlossary();
      });
    });

    // Guardar Ajustes
    dom.formSettings.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const res = await fetch('/api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            sleep_target_hours: parseFloat(dom.setSleep.value),
            steps_daily_goal: parseInt(dom.setSteps.value, 10),
            intensity_weekly_goal: parseInt(dom.setIntensity.value, 10),
          }),
        });
        const data = await res.json();
        closeModal('modal-settings');
        showToast('Ajustes guardados con éxito', 'success');
        if (state.currentStart && state.currentEnd) {
          loadReport({ start: state.currentStart, end: state.currentEnd, demo: state.isDemo });
        }
      } catch (err) {
        showToast('Error guardando ajustes: ' + err.message, 'error');
      }
    });
  }

  function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
      modal.classList.add('is-open');
      modal.setAttribute('aria-hidden', 'false');
    }
  }

  function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) {
      modal.classList.remove('is-open');
      modal.setAttribute('aria-hidden', 'true');
    }
  }

  function switchTab(tabId) {
    document.querySelectorAll('.tab-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.tab === tabId);
    });
    document.querySelectorAll('.tab-content').forEach(c => {
      c.classList.toggle('active', c.id === tabId);
    });
  }

  // ========================================================================
  // Notificaciones Toast
  // ========================================================================

  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    dom.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateY(10px)';
      setTimeout(() => toast.remove(), 250);
    }, 4000);
  }

  function escapeHtml(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // Arrancar app al cargar DOM
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
