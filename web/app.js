/**
 * BioDelta - Frontend Client Application
 * State management, time travel, Garmin 2FA synchronization, and interactive health dashboard.
 * Full bilingual support (English as default with real-time Spanish switching).
 */

(function () {
  'use strict';

  // ========================================================================
  // Diccionario de Traducción de la Interfaz (UI i18n)
  // ========================================================================

  const I18N_UI = {
    en: {
      page_title: 'BioDelta · Health & Performance Log',
      brand_tooltip: 'BioDelta - Health & Longevity Dashboard',
      prev_week_title: 'Previous week (◀)',
      next_week_title: 'Next week (▶)',
      select_placeholder: 'Select week or date range',
      loading_dates: 'Loading dates...',
      no_weeks_recorded: 'No recorded weeks',
      btn_lang_title: 'Switch to Spanish',
      lbl_sync: 'Sync',
      lbl_upload: 'Upload',
      lbl_demo: 'Demo',
      lbl_glossary: 'Glossary',
      lbl_settings: 'Settings',
      theme_light: '☀ Light',
      theme_dark: '☾ Dark',

      loading_report: 'Generating health report...',
      loading_demo: 'Generating demo environment...',
      loading_generic: 'Loading health metrics...',

      onboarding_badge: '👋 Welcome to BioDelta!',
      onboarding_title: 'Your Garmin health metrics, clear and private',
      onboarding_subtitle: '100% local on your device, no external servers. Choose how to start:',
      card_garmin_title: 'Connect with Garmin',
      card_garmin_desc: 'Sign in with your Garmin Connect account to sync automatically with 2FA support.',
      card_garmin_btn: 'Connect Garmin',
      card_upload_title: 'Load Database',
      card_upload_desc: 'Drag and drop your existing garmin_data.db file to visualize it instantly.',
      card_upload_btn: 'Upload File',
      card_demo_title: 'Demo Mode',
      card_demo_desc: 'Explore a full report with synthetic demo data without needing a watch.',
      card_demo_btn: 'View Demo',

      sync_modal_title: '🔄 Sync with Garmin Connect',
      sync_tab_sync: 'Synchronization',
      sync_tab_login: 'Account / Login',
      sync_checking_session: 'Checking Garmin session...',
      sync_session_ready: 'Garmin Connect session active and ready',
      sync_session_missing: 'No active session. Go to Account tab to sign in.',
      sync_range_label: 'Date range to extract (optional):',
      sync_to: 'to',
      sync_help: 'If left blank, Garmin will incrementally fetch the most recent data.',
      btn_start_sync: 'Start Synchronization',
      sync_connecting: 'Connecting with Garmin Connect...',
      login_email_label: 'Garmin Connect Email:',
      login_pass_label: 'Password:',
      privacy_note: '🔒 Your credentials are used exclusively to obtain the Garmin session locally and are never sent to third parties.',
      btn_submit_login: 'Connect and Authenticate',
      btn_logging_in: 'Connecting to Garmin...',
      mfa_title: 'Two-Step Verification (2FA)',
      mfa_instructions: 'Enter the security code Garmin sent to your phone or email:',
      btn_submit_mfa: 'Verify',
      btn_verifying_mfa: 'Verifying...',

      upload_modal_title: '📁 Load Database',
      upload_drop_title: 'Drag your garmin_data.db file here',
      upload_drop_subtitle: 'or click to browse your computer',
      upload_browse_btn: 'Select file',
      uploading_validating: 'Uploading and validating',
      upload_success: 'Database loaded successfully',

      glossary_modal_title: '📖 Health & Metric Glossary',
      glossary_search_ph: '🔍 Search metric or concept (e.g. SRI, HRV, ACWR)...',
      cat_all: 'All',
      cat_sleep: 'Sleep',
      cat_cardio: 'Cardiovascular',
      cat_load: 'Load',
      cat_wellness: 'Wellness',
      glossary_what: 'What is it?',
      glossary_why: 'Why it matters:',
      glossary_range: 'Reference range:',

      settings_modal_title: '⚙️ Target Settings',
      settings_sleep_label: 'Sleep goal per night:',
      settings_steps_label: 'Daily steps goal:',
      settings_intensity_label: 'Weekly intensity minutes goal (WHO):',
      settings_save_btn: 'Save Preferences',
      settings_saved_toast: 'Target settings saved successfully',

      toast_sync_running: 'A synchronization is already in progress',
      toast_sync_success: '🎉 Synchronization completed successfully!',
      toast_sync_error: 'Error during synchronization',
      toast_mfa_prompt: 'Garmin requested a 2FA security code',
      toast_mfa_success: '🎉 2FA verified successfully!',
      toast_mfa_invalid: 'Invalid 2FA code',
      toast_server_error: 'Error connecting to local BioDelta server',
    },
    es: {
      page_title: 'BioDelta · Visor de Salud y Rendimiento',
      brand_tooltip: 'BioDelta - Panel de Salud y Longevidad',
      prev_week_title: 'Semana anterior (◀)',
      next_week_title: 'Semana siguiente (▶)',
      select_placeholder: 'Seleccionar semana o periodo',
      loading_dates: 'Cargando fechas...',
      no_weeks_recorded: 'Sin semanas registradas',
      btn_lang_title: 'Cambiar a inglés',
      lbl_sync: 'Sincronizar',
      lbl_upload: 'Cargar',
      lbl_demo: 'Demo',
      lbl_glossary: 'Glosario',
      lbl_settings: 'Ajustes',
      theme_light: '☀ Claro',
      theme_dark: '☾ Oscuro',

      loading_report: 'Generando informe de salud...',
      loading_demo: 'Generando entorno de demostración...',
      loading_generic: 'Cargando métricas de salud...',

      onboarding_badge: '👋 ¡Bienvenido a BioDelta!',
      onboarding_title: 'Tus métricas de salud de Garmin, claras y privadas',
      onboarding_subtitle: '100% local en tu dispositivo, sin servidores externos. Elige cómo empezar:',
      card_garmin_title: 'Conectar con Garmin',
      card_garmin_desc: 'Introduce tu cuenta de Garmin Connect para sincronizar automáticamente con soporte 2FA.',
      card_garmin_btn: 'Conectar Garmin',
      card_upload_title: 'Cargar Base de Datos',
      card_upload_desc: 'Arrastra tu archivo garmin_data.db existente para visualizarlo al instante.',
      card_upload_btn: 'Subir Archivo',
      card_demo_title: 'Modo Demostración',
      card_demo_desc: 'Explora un informe completo con datos sintéticos de prueba sin necesidad de reloj.',
      card_demo_btn: 'Ver Demo',

      sync_modal_title: '🔄 Sincronizar con Garmin Connect',
      sync_tab_sync: 'Sincronización',
      sync_tab_login: 'Cuenta / Login',
      sync_checking_session: 'Comprobando sesión de Garmin...',
      sync_session_ready: 'Sesión de Garmin Connect activa y lista',
      sync_session_missing: 'Sin sesión activa. Ve a la pestaña Cuenta para iniciar sesión.',
      sync_range_label: 'Rango de fechas a extraer (opcional):',
      sync_to: 'hasta',
      sync_help: 'Si lo dejas en blanco, Garmin traerá de forma incremental los datos más recientes.',
      btn_start_sync: 'Iniciar Sincronización',
      sync_connecting: 'Conectando con Garmin Connect...',
      login_email_label: 'Email de Garmin Connect:',
      login_pass_label: 'Contraseña:',
      privacy_note: '🔒 Tus credenciales se utilizan exclusivamente para obtener la sesión de Garmin localmente y nunca se envían a terceros.',
      btn_submit_login: 'Conectar y Autenticar',
      btn_logging_in: 'Conectando con Garmin...',
      mfa_title: 'Verificación en Dos Pasos (2FA)',
      mfa_instructions: 'Introduce el código de seguridad que Garmin ha enviado a tu teléfono o correo electrónico:',
      btn_submit_mfa: 'Verificar',
      btn_verifying_mfa: 'Verificando...',

      upload_modal_title: '📁 Cargar Base de Datos',
      upload_drop_title: 'Arrastra aquí tu archivo garmin_data.db',
      upload_drop_subtitle: 'o haz clic para buscarlo en tu ordenador',
      upload_browse_btn: 'Seleccionar archivo',
      uploading_validating: 'Subiendo y validando',
      upload_success: 'Base de datos cargada correctamente',

      glossary_modal_title: '📖 Glosario de Métricas y Salud',
      glossary_search_ph: '🔍 Buscar métrica o concepto (ej. SRI, HRV, ACWR)...',
      cat_all: 'Todos',
      cat_sleep: 'Sueño',
      cat_cardio: 'Cardiovascular',
      cat_load: 'Carga',
      cat_wellness: 'Bienestar',
      glossary_what: '¿Qué es?',
      glossary_why: '¿Por qué importa?',
      glossary_range: 'Rango orientativo:',

      settings_modal_title: '⚙️ Ajustes y Objetivos',
      settings_sleep_label: 'Objetivo de sueño por noche:',
      settings_steps_label: 'Objetivo de pasos diarios:',
      settings_intensity_label: 'Objetivo semanal de intensidad (OMS):',
      settings_save_btn: 'Guardar Preferencias',
      settings_saved_toast: 'Ajustes guardados con éxito',

      toast_sync_running: 'Ya hay una sincronización en curso',
      toast_sync_success: '🎉 ¡Sincronización completada con éxito!',
      toast_sync_error: 'Error en la sincronización',
      toast_mfa_prompt: 'Garmin ha solicitado código 2FA',
      toast_mfa_success: '🎉 ¡2FA verificado con éxito!',
      toast_mfa_invalid: 'Código 2FA incorrecto',
      toast_server_error: 'Error conectando con el servidor BioDelta local',
    }
  };

  // ========================================================================
  // Estado global de la aplicación
  // ========================================================================

  const state = {
    currentStart: null,
    currentEnd: null,
    isDemo: false,
    weeks: [],
    status: null,
    glossary: {},
    mfaSessionId: null,
    theme: localStorage.getItem('biodelta-theme') || 'light',
    lang: localStorage.getItem('biodelta-lang') || 'en',
  };

  // Elementos DOM
  const dom = {
    html: document.documentElement,
    themeBtn: document.getElementById('theme-btn'),
    btnLang: document.getElementById('btn-lang'),
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
  // Inicialización e Internacionalización (i18n)
  // ========================================================================

  async function init() {
    initTheme();
    applyLanguage(state.lang);
    setupEventListeners();
    await checkAppStatus();
  }

  function initTheme() {
    dom.html.dataset.theme = state.theme;
    updateThemeButtonText();
  }

  function updateThemeButtonText() {
    const t = I18N_UI[state.lang] || I18N_UI.en;
    dom.themeBtn.textContent = state.theme === 'dark' ? t.theme_light : t.theme_dark;
    dom.themeBtn.setAttribute('aria-pressed', state.theme === 'dark');
  }

  function toggleTheme() {
    state.theme = state.theme === 'dark' ? 'light' : 'dark';
    dom.html.dataset.theme = state.theme;
    updateThemeButtonText();
    try {
      localStorage.setItem('biodelta-theme', state.theme);
    } catch (e) {}
  }

  function applyLanguage(lang) {
    state.lang = lang;
    try {
      localStorage.setItem('biodelta-lang', lang);
    } catch (e) {}
    dom.html.lang = lang;

    const t = I18N_UI[lang] || I18N_UI.en;
    document.title = t.page_title;

    // Actualizar botón de bandera
    if (dom.btnLang) {
      dom.btnLang.textContent = lang === 'es' ? '🇪🇸 ES' : '🇬🇧 EN';
      dom.btnLang.title = t.btn_lang_title;
      dom.btnLang.setAttribute('aria-label', t.btn_lang_title);
    }

    // Actualizar textos en el DOM marcados con data-i18n
    document.querySelectorAll('[data-i18n]').forEach(el => {
      const key = el.getAttribute('data-i18n');
      if (t[key] !== undefined) {
        el.textContent = t[key];
      }
    });

    // Actualizar placeholders
    if (dom.glossarySearch) {
      dom.glossarySearch.placeholder = t.glossary_search_ph;
    }

    // Actualizar textos de botones de navegación
    if (dom.btnPrev) dom.btnPrev.title = t.prev_week_title;
    if (dom.btnNext) dom.btnNext.title = t.next_week_title;

    updateThemeButtonText();
    updateSettingsOptions(lang);
  }

  function updateSettingsOptions(lang) {
    const isEs = lang === 'es';
    if (dom.setSleep) {
      dom.setSleep.innerHTML = `
        <option value="7.0">${isEs ? '7 horas' : '7 hours'}</option>
        <option value="7.5">${isEs ? '7 horas 30 min' : '7 hours 30 min'}</option>
        <option value="8.0" selected>${isEs ? '8 horas (Recomendado)' : '8 hours (Recommended)'}</option>
        <option value="8.5">${isEs ? '8 horas 30 min' : '8 hours 30 min'}</option>
        <option value="9.0">${isEs ? '9 horas' : '9 hours'}</option>
      `;
    }
    if (dom.setSteps) {
      dom.setSteps.innerHTML = `
        <option value="6000">${isEs ? '6.000 pasos' : '6,000 steps'}</option>
        <option value="8000">${isEs ? '8.000 pasos' : '8,000 steps'}</option>
        <option value="10000" selected>${isEs ? '10.000 pasos (Recomendado)' : '10,000 steps (Recommended)'}</option>
        <option value="12000">${isEs ? '12.000 pasos' : '12,000 steps'}</option>
        <option value="15000">${isEs ? '15.000 pasos' : '15,000 steps'}</option>
      `;
    }
    if (dom.setIntensity) {
      dom.setIntensity.innerHTML = `
        <option value="150" selected>${isEs ? '150 min / semana (Mínimo OMS)' : '150 min / week (WHO Minimum)'}</option>
        <option value="225">${isEs ? '225 min / semana' : '225 min / week'}</option>
        <option value="300">${isEs ? '300 min / semana (Deportista)' : '300 min / week (Athlete)'}</option>
        <option value="450">${isEs ? '450 min / semana (Alto rendimiento)' : '450 min / week (High performance)'}</option>
      `;
    }
  }

  async function toggleLanguage() {
    const nextLang = state.lang === 'en' ? 'es' : 'en';
    applyLanguage(nextLang);
    state.glossary = {}; // Invalidar caché de glosario para recargar en el nuevo idioma
    await loadAvailableWeeks();
    if (state.currentStart && state.currentEnd) {
      await loadReport({ start: state.currentStart, end: state.currentEnd, demo: state.isDemo });
    } else {
      await loadReport({ start: null, end: null, demo: state.isDemo });
    }
  }

  // ========================================================================
  // Estado del Sistema y Carga de Datos
  // ========================================================================

  async function checkAppStatus() {
    try {
      const res = await fetch(`/api/status?lang=${state.lang}`);
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
      console.error('Error checking status:', err);
      const t = I18N_UI[state.lang] || I18N_UI.en;
      showToast(t.toast_server_error, 'error');
    }
  }

  function updateAuthStatusUI(hasTokens) {
    const indicator = dom.syncAuthStatus.querySelector('.status-indicator');
    const t = I18N_UI[state.lang] || I18N_UI.en;
    if (hasTokens) {
      indicator.classList.add('ready');
      dom.syncAuthText.textContent = t.sync_session_ready;
    } else {
      indicator.classList.remove('ready');
      dom.syncAuthText.textContent = t.sync_session_missing;
    }
  }

  async function loadAvailableWeeks() {
    try {
      const res = await fetch(`/api/weeks?lang=${state.lang}`);
      const data = await res.json();
      state.weeks = data.weeks || [];

      dom.rangeSelect.innerHTML = '';
      const t = I18N_UI[state.lang] || I18N_UI.en;
      if (state.weeks.length === 0) {
        dom.rangeSelect.innerHTML = `<option value="">${t.no_weeks_recorded}</option>`;
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
      console.error('Error loading weeks:', e);
    }
  }

  async function loadReport({ start, end, demo = false }) {
    const t = I18N_UI[state.lang] || I18N_UI.en;
    showLoading(demo ? t.loading_demo : t.loading_report);
    state.isDemo = demo;

    try {
      let url = '/api/report';
      const params = new URLSearchParams();
      params.set('lang', state.lang);
      if (demo) params.set('demo', '1');
      if (start) params.set('start', start);
      if (end) params.set('end', end);

      const qs = params.toString();
      if (qs) url += '?' + qs;

      const res = await fetch(url);
      const data = await res.json();

      if (data.status !== 'ok') {
        throw new Error(data.message || 'Error loading report');
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
      console.error('Error loading report:', err);
      showToast(err.message, 'error');
      showOnboarding();
    }
  }

  function updateNavButtonsState(prevWeek, nextWeek) {
    if (!prevWeek || !state.weeks.length) {
      dom.btnPrev.disabled = false;
    }
    dom.btnPrev.dataset.start = prevWeek ? prevWeek.start : '';
    dom.btnPrev.dataset.end = prevWeek ? prevWeek.end : '';
    dom.btnNext.dataset.start = nextWeek ? nextWeek.start : '';
    dom.btnNext.dataset.end = nextWeek ? nextWeek.end : '';
  }

  // ========================================================================
  // Control de Vistas (Loading, Onboarding, Report)
  // ========================================================================

  function showLoading(msg) {
    const t = I18N_UI[state.lang] || I18N_UI.en;
    dom.loadingMsg.textContent = msg || t.loading_generic;
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
    const t = I18N_UI[state.lang] || I18N_UI.en;
    const startVal = dom.syncStartDate.value;
    const endVal = dom.syncEndDate.value;

    dom.btnStartSync.disabled = true;
    dom.syncProgress.style.display = 'block';
    dom.syncProgressMsg.textContent = t.sync_connecting;

    try {
      const res = await fetch('/api/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ start_date: startVal || null, end_date: endVal || null }),
      });
      const data = await res.json();

      if (data.status === 'already_running') {
        showToast(t.toast_sync_running, 'warning');
      }

      pollSyncProgress();
    } catch (e) {
      dom.btnStartSync.disabled = false;
      dom.syncProgress.style.display = 'none';
      showToast(`${t.toast_sync_error}: ${e.message}`, 'error');
    }
  }

  function pollSyncProgress() {
    const t = I18N_UI[state.lang] || I18N_UI.en;
    const timer = setInterval(async () => {
      try {
        const res = await fetch('/api/sync/status');
        const data = await res.json();

        dom.syncProgressMsg.textContent = data.message || t.sync_connecting;

        if (data.status === 'completed') {
          clearInterval(timer);
          dom.btnStartSync.disabled = false;
          dom.syncProgress.style.display = 'none';
          closeModal('modal-sync');
          showToast(t.toast_sync_success, 'success');
          await loadAvailableWeeks();
          await loadReport({ start: null, end: null, demo: false });
        } else if (data.status === 'error') {
          clearInterval(timer);
          dom.btnStartSync.disabled = false;
          dom.syncProgress.style.display = 'none';
          showToast(`❌ ${data.message || t.toast_sync_error}`, 'error');
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
    const t = I18N_UI[state.lang] || I18N_UI.en;
    const email = dom.loginEmail.value.trim();
    const password = dom.loginPass.value.trim();

    if (!email || !password) return;

    const btn = document.getElementById('btn-submit-login');
    btn.disabled = true;
    btn.textContent = t.btn_logging_in;

    try {
      const res = await fetch('/api/auth', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      const data = await res.json();
      btn.disabled = false;
      btn.textContent = t.btn_submit_login;

      if (data.status === 'needs_mfa') {
        state.mfaSessionId = data.session_id;
        dom.formLogin.style.display = 'none';
        dom.mfaBox.style.display = 'block';
        dom.mfaCode.value = '';
        dom.mfaCode.focus();
        showToast(t.toast_mfa_prompt, 'info');
      } else if (data.status === 'ok') {
        showToast('✅ ' + data.message, 'success');
        updateAuthStatusUI(true);
        switchTab('sync-tab-auto');
      } else {
        showToast('❌ ' + (data.message || 'Authentication error'), 'error');
      }
    } catch (err) {
      btn.disabled = false;
      btn.textContent = t.btn_submit_login;
      showToast('Error connecting: ' + err.message, 'error');
    }
  }

  async function handleMfaSubmit() {
    const t = I18N_UI[state.lang] || I18N_UI.en;
    const code = dom.mfaCode.value.trim();
    if (!code || !state.mfaSessionId) {
      showToast('Enter the 2FA code', 'error');
      return;
    }

    dom.btnSubmitMfa.disabled = true;
    dom.btnSubmitMfa.textContent = t.btn_verifying_mfa;

    try {
      const res = await fetch('/api/auth/mfa', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: state.mfaSessionId, code }),
      });
      const data = await res.json();
      dom.btnSubmitMfa.disabled = false;
      dom.btnSubmitMfa.textContent = t.btn_submit_mfa;

      if (data.status === 'ok') {
        dom.mfaBox.style.display = 'none';
        dom.formLogin.style.display = 'block';
        dom.formLogin.reset();
        state.mfaSessionId = null;
        showToast(t.toast_mfa_success, 'success');
        updateAuthStatusUI(true);
        switchTab('sync-tab-auto');
      } else {
        showToast(`❌ ${data.message || t.toast_mfa_invalid}`, 'error');
      }
    } catch (e) {
      dom.btnSubmitMfa.disabled = false;
      dom.btnSubmitMfa.textContent = t.btn_submit_mfa;
      showToast('Error verifying 2FA: ' + e.message, 'error');
    }
  }

  // ========================================================================
  // Drag & Drop / Carga de Archivo SQLite
  // ========================================================================

  async function handleFileUpload(file) {
    if (!file) return;
    const t = I18N_UI[state.lang] || I18N_UI.en;
    dom.uploadStatus.style.display = 'block';
    dom.uploadStatus.className = 'upload-status-box';
    dom.uploadStatus.textContent = `${t.uploading_validating} ${file.name}...`;

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
          showToast(t.upload_success, 'success');
          await loadAvailableWeeks();
          await loadReport({ start: null, end: null, demo: false });
        }, 800);
      } else {
        dom.uploadStatus.className = 'upload-status-box error';
        dom.uploadStatus.textContent = '❌ ' + (data.message || 'Invalid file');
      }
    } catch (e) {
      dom.uploadStatus.className = 'upload-status-box error';
      dom.uploadStatus.textContent = 'Error uploading file: ' + e.message;
    }
  }

  // ========================================================================
  // Glosario Interactivo
  // ========================================================================

  async function loadGlossaryData() {
    if (Object.keys(state.glossary).length > 0) return;
    try {
      const res = await fetch(`/api/glossary?lang=${state.lang}`);
      const data = await res.json();
      state.glossary = data.glossary || {};
      renderGlossaryCards();
    } catch (e) {
      console.error('Error loading glossary:', e);
    }
  }

  function renderGlossaryCards() {
    dom.glossaryContainer.innerHTML = '';
    const t = I18N_UI[state.lang] || I18N_UI.en;
    for (const [key, item] of Object.entries(state.glossary)) {
      const card = document.createElement('article');
      card.className = 'glossary-card';
      card.dataset.category = item.category;
      card.innerHTML = `
        <div class="glossary-card-header">
          <h4>${escapeHtml(item.title)}</h4>
          <span class="glossary-badge">${escapeHtml(item.category)}</span>
        </div>
        <p><strong>${t.glossary_what}</strong> ${escapeHtml(item.what)}</p>
        <p><strong>${t.glossary_why}</strong> ${escapeHtml(item.why)}</p>
        <p class="glossary-range"><strong>${t.glossary_range}</strong> ${escapeHtml(item.range)}</p>
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
    if (dom.btnLang) dom.btnLang.addEventListener('click', toggleLanguage);
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
      const t = I18N_UI[state.lang] || I18N_UI.en;
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
        showToast(t.settings_saved_toast, 'success');
        if (state.currentStart && state.currentEnd) {
          loadReport({ start: state.currentStart, end: state.currentEnd, demo: state.isDemo });
        }
      } catch (err) {
        showToast('Error saving settings: ' + err.message, 'error');
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

