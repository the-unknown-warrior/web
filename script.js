const SUPPORTED_LANGS = ['en', 'ru', 'de', 'es', 'fr', 'it'];
const DEFAULT_LANG = 'en';
const LANG_STORAGE_KEY = 'glazniLang';

// Each language's own name, shown as-is regardless of the current UI
// language (the normal convention — "Deutsch" isn't translated to "German"
// just because the page is in English).
const LANG_NAMES = {
  en: 'English',
  ru: 'Русский',
  de: 'Deutsch',
  es: 'Español',
  fr: 'Français',
  it: 'Italiano'
};

function dataFileFor(lang) {
  return `locale/data_${lang}.json`;
}

// Reads a previously-picked language out of localStorage, if any. Wrapped in
// try/catch because localStorage can throw in some privacy modes / sandboxed
// iframes — we just fall back to the default language in that case.
function getStoredLang() {
  try {
    const stored = localStorage.getItem(LANG_STORAGE_KEY);
    if (SUPPORTED_LANGS.includes(stored)) return stored;
  } catch (err) {
    /* localStorage unavailable — ignore and use the default */
  }
  return null;
}

function storeLang(lang) {
  try {
    localStorage.setItem(LANG_STORAGE_KEY, lang);
  } catch (err) {
    /* localStorage unavailable — the toggle still works for this page load */
  }
}

let currentLang = getStoredLang() || DEFAULT_LANG;

function getI18nValue(dict, key) {
  return key.split('.').reduce((obj, part) => (obj && obj[part] !== undefined ? obj[part] : undefined), dict);
}

function applyI18n(dict) {
  // Plain text nodes
  document.querySelectorAll('[data-i18n]').forEach(el => {
    const value = getI18nValue(dict, el.getAttribute('data-i18n'));
    if (value !== undefined) el.textContent = value;
  });

  // Nodes that need real markup inside them (e.g. a <br> or <span>)
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    const value = getI18nValue(dict, el.getAttribute('data-i18n-html'));
    if (value !== undefined) el.innerHTML = value;
  });

  // Attributes, e.g. data-i18n-attr="alt:build.imgAlt" or "aria-label:nav.toggleLabel"
  // (comma-separate multiple: "alt:key1,title:key2")
  document.querySelectorAll('[data-i18n-attr]').forEach(el => {
    el.getAttribute('data-i18n-attr').split(',').forEach(pair => {
      const [attr, key] = pair.split(':').map(s => s.trim());
      const value = key ? getI18nValue(dict, key) : undefined;
      if (attr && value !== undefined) el.setAttribute(attr, value);
    });
  });

  // <title> and meta description aren't in the DOM query above since they live in <head>
  if (dict.meta) {
    if (dict.meta.title) document.title = dict.meta.title;
    if (dict.meta.description) {
      const metaDesc = document.querySelector('meta[name="description"]');
      if (metaDesc) metaDesc.setAttribute('content', dict.meta.description);
    }
  }
}

// Duplicates ticker content for a seamless loop. Runs whether or not the JSON
// fetch below succeeds — if it fails, the ticker still duplicates whatever
// text is already sitting in the HTML.
function initTicker() {
  document.querySelectorAll('.ticker-track').forEach(track => {
    if (track.dataset.duplicated) return;
    track.innerHTML += track.innerHTML;
    track.dataset.duplicated = 'true';
  });
}

// data-page attributes are hyphenated (e.g. "background-changer") but the
// JSON dictionaries key their per-page strings in camelCase (e.g.
// "backgroundChanger"), matching normal JS property naming. Convert before
// looking the page up, or hyphenated multi-word pages silently get no
// translations and fall back to the hardcoded English in the HTML.
function toCamelCase(slug) {
  return slug.replace(/-([a-z0-9])/g, (_, c) => c.toUpperCase());
}

async function loadI18n(lang) {
  const page = document.body.dataset.page;
  if (page) {
    const dataFile = dataFileFor(lang);
    try {
      const res = await fetch(dataFile);
      if (!res.ok) throw new Error(`${dataFile} responded with ${res.status}`);
      const data = await res.json();
      // Merge page-agnostic strings (nav, footer) with this page's own strings.
      const dict = Object.assign({}, data.shared, data[toCamelCase(page)]);
      applyI18n(dict);
      document.documentElement.setAttribute('lang', lang);
    } catch (err) {
      console.warn(`Could not load ${dataFile}, keeping the current page text.`, err);
    }
  }
  initTicker();
}

// ---------- language switch ----------
// The switcher is a single trigger button (showing the current language
// code) that opens a dropdown list of every supported language. Using a
// dropdown instead of a flat row of buttons means adding more languages
// later never risks overflowing the nav bar on small screens.
const langSwitch = document.getElementById('langSwitch');
const langTrigger = document.getElementById('langTrigger');
const langTriggerCode = langTrigger ? langTrigger.querySelector('[data-lang-code]') : null;
const langMenu = document.getElementById('langMenu');

function closeLangMenu() {
  if (!langSwitch || !langMenu) return;
  langSwitch.classList.remove('open');
  langMenu.hidden = true;
  langTrigger.setAttribute('aria-expanded', 'false');
}

function openLangMenu() {
  if (!langSwitch || !langMenu) return;
  langSwitch.classList.add('open');
  langMenu.hidden = false;
  langTrigger.setAttribute('aria-expanded', 'true');
  // Don't let the mobile full-screen nav sit open behind the dropdown.
  if (typeof closeNavMenu === 'function') closeNavMenu();
}

// Reflects `lang` on the trigger label and the option list (.active class +
// aria-selected), persists the choice, and re-fetches/applies the matching
// dictionary. Pass persist:false for the very first call so simply loading
// a page doesn't overwrite a saved preference with the same value pointlessly.
function setLanguage(lang, { persist = true } = {}) {
  if (!SUPPORTED_LANGS.includes(lang)) return;
  currentLang = lang;
  if (persist) storeLang(lang);
  if (langTriggerCode) langTriggerCode.textContent = lang.toUpperCase();
  document.querySelectorAll('.lang-option').forEach(opt => {
    const isActive = opt.dataset.lang === lang;
    opt.classList.toggle('active', isActive);
    opt.setAttribute('aria-selected', String(isActive));
  });
  loadI18n(lang);
}

if (langTrigger && langMenu) {
  langTrigger.addEventListener('click', (e) => {
    e.stopPropagation();
    if (langMenu.hidden) openLangMenu(); else closeLangMenu();
  });

  document.querySelectorAll('.lang-option').forEach(opt => {
    opt.addEventListener('click', () => {
      const lang = opt.dataset.lang;
      closeLangMenu();
      if (lang === currentLang) return;
      setLanguage(lang);
    });
  });

  document.addEventListener('click', (e) => {
    if (langMenu.hidden) return;
    if (langSwitch.contains(e.target)) return;
    closeLangMenu();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !langMenu.hidden) {
      closeLangMenu();
      langTrigger.focus();
    }
  });
}

setLanguage(currentLang, { persist: false });

// ---------- nav ----------
const nav = document.querySelector('.nav');
const navToggle = document.querySelector('.nav-toggle');
const navLinks = document.querySelector('.nav-links');

window.addEventListener('scroll', () => {
  if (window.scrollY > 12) nav.classList.add('is-scrolled');
  else nav.classList.remove('is-scrolled');
}, { passive: true });

function closeNavMenu() {
  navLinks.classList.remove('open');
  nav.classList.remove('menu-open');
  navToggle.setAttribute('aria-expanded', 'false');
}

if (navToggle) {
  navToggle.addEventListener('click', (e) => {
    e.stopPropagation();
    const isOpen = navLinks.classList.toggle('open');
    nav.classList.toggle('menu-open', isOpen);
    navToggle.setAttribute('aria-expanded', String(isOpen));
    if (isOpen) closeLangMenu();
  });
  navLinks.querySelectorAll('a').forEach(a => a.addEventListener('click', closeNavMenu));

  // Close the menu on a click/tap outside of it.
  document.addEventListener('click', (e) => {
    if (!navLinks.classList.contains('open')) return;
    if (navLinks.contains(e.target) || navToggle.contains(e.target)) return;
    closeNavMenu();
  });
}

// ---------- scroll reveal ----------
const revealEls = document.querySelectorAll('.reveal');
if ('IntersectionObserver' in window) {
  const io = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        io.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  revealEls.forEach(el => io.observe(el));
} else {
  revealEls.forEach(el => el.classList.add('visible'));
}

// ---------- orbit node placement ----------
document.querySelectorAll('.orbit-nodes').forEach(ring => {
  const nodes = ring.querySelectorAll('.orbit-node .pin');
  const radius = ring.dataset.radius || 46; // percent-ish, resolved via px below
  const stage = ring.closest('.orbit-stage');
  const size = stage ? stage.getBoundingClientRect().width : 480;
  const r = size * 0.46;
  const count = nodes.length;
  nodes.forEach((pin, i) => {
    const angle = (360 / count) * i;
    pin.style.transform = `rotate(${angle}deg) translate(${r}px)`;
    const badge = pin.querySelector('.badge');
    if (badge) badge.style.transform = `translate(-50%,-50%) rotate(${-angle}deg)`;
  });
});

// ---------- careers: role filters ----------
const filterBtns = document.querySelectorAll('.filter-btn');
const roleEntries = document.querySelectorAll('.role-entry');
if (filterBtns.length) {
  filterBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      filterBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const dept = btn.dataset.filter;
      roleEntries.forEach(entry => {
        const show = dept === 'all' || entry.dataset.dept === dept;
        entry.classList.toggle('show', show);
        if (!show) closeRoleEntry(entry);
      });
    });
  });
}

// ---------- careers: expand/collapse job descriptions ----------
function closeRoleEntry(entry) {
  const toggle = entry.querySelector('.registry-toggle');
  const panel = entry.querySelector('.role-detail');
  if (!toggle || !panel) return;
  toggle.setAttribute('aria-expanded', 'false');
  panel.hidden = true;
  entry.classList.remove('is-open');
}

document.querySelectorAll('.registry-toggle').forEach(toggle => {
  toggle.addEventListener('click', () => {
    const entry = toggle.closest('.role-entry');
    const panel = document.getElementById(toggle.getAttribute('aria-controls'));
    if (!entry || !panel) return;
    const expanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!expanded));
    panel.hidden = expanded;
    entry.classList.toggle('is-open', !expanded);
  });
});

// ---------- contact form (posts straight to a Discord webhook) ----------
// Paste your webhook URL below — Discord → Server Settings → Integrations →
// Webhooks → New Webhook → Copy Webhook URL. Anyone with this URL can post
// to the channel, so keep it out of any public repo (e.g. load it from a
// server-side proxy instead) if that matters to you.
const DISCORD_WEBHOOK_URL = 'https://discord.com/api/webhooks/1355795922856181901/17Cl93WNtsJVhE1GeLoIreKicxMTEIpc5FGIvnXHAlfxvMoX1-c2tcnSZ_KyVsaWC8bO';

const contactForm = document.getElementById('contact-form');
if (contactForm) {
  const submitBtn = contactForm.querySelector('button[type="submit"]');
  const formNote = contactForm.querySelector('.form-note');
  const submitBtnDefaultText = submitBtn ? submitBtn.textContent : '';

  function setFormNote(text, state) {
    if (!formNote) return;
    formNote.textContent = text;
    formNote.classList.remove('form-note-error', 'form-note-success');
    if (state) formNote.classList.add(`form-note-${state}`);
  }

  contactForm.addEventListener('submit', async (e) => {
    e.preventDefault();

    if (!DISCORD_WEBHOOK_URL || DISCORD_WEBHOOK_URL.includes('PASTE_YOUR')) {
      setFormNote("This form isn't connected yet — add a Discord webhook URL in script.js.", 'error');
      return;
    }

    const name = contactForm.querySelector('#c-name').value.trim();
    const email = contactForm.querySelector('#c-email').value.trim();
    const msg = contactForm.querySelector('#c-message').value.trim();

    if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Sending…'; }
    setFormNote('Sending your message…');

    try {
      const res = await fetch(DISCORD_WEBHOOK_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content: `📩 **New Contact Form Submission**\n👤 **Name:** ${name || '—'}\n✉️ **Email:** ${email || '—'}\n📝 **Message:**\n${msg || '—'}`
        })
      });

      // Discord webhooks return 204 No Content on success.
      if (!res.ok) throw new Error(`Discord responded with ${res.status}`);

      contactForm.reset();
      setFormNote('Message sent — we usually reply within a business day.', 'success');
    } catch (err) {
      console.warn('Could not send message to Discord:', err);
      setFormNote('Something went wrong sending your message — please email hello@glazni.com instead.', 'error');
    } finally {
      if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = submitBtnDefaultText; }
    }
  });
}

// ---------- current year ----------
document.querySelectorAll('.js-year').forEach(el => { el.textContent = new Date().getFullYear(); });
