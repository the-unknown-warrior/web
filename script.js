// ---------- i18n: load all page text from data_en.json ----------
// The HTML that ships in the repo already contains the English copy, so if this
// fetch fails (e.g. opened straight from disk, where fetch() of local files is
// blocked by the browser) the page still reads fine — the JSON is the source of
// truth, the inline HTML text is just the fallback.
//
// To ship another language later: copy data_en.json to e.g. data_ru.json,
// translate the values (keep the keys as-is), and change DATA_FILE below
// (or make it a query param / <html lang> switch) to point at it.
const DATA_FILE = 'data_en.json';

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

async function loadI18n() {
  const page = document.body.dataset.page;
  if (page) {
    try {
      const res = await fetch(DATA_FILE);
      if (!res.ok) throw new Error(`${DATA_FILE} responded with ${res.status}`);
      const data = await res.json();
      // Merge page-agnostic strings (nav, footer) with this page's own strings.
      const dict = Object.assign({}, data.shared, data[page]);
      applyI18n(dict);
    } catch (err) {
      console.warn(`Could not load ${DATA_FILE}, keeping the built-in page text.`, err);
    }
  }
  initTicker();
}

loadI18n();

// ---------- nav ----------
const nav = document.querySelector('.nav');
const navToggle = document.querySelector('.nav-toggle');
const navLinks = document.querySelector('.nav-links');

window.addEventListener('scroll', () => {
  if (window.scrollY > 12) nav.classList.add('is-scrolled');
  else nav.classList.remove('is-scrolled');
}, { passive: true });

if (navToggle) {
  navToggle.addEventListener('click', () => {
    navLinks.classList.toggle('open');
    navToggle.setAttribute('aria-expanded', navLinks.classList.contains('open'));
  });
  navLinks.querySelectorAll('a').forEach(a => a.addEventListener('click', () => navLinks.classList.remove('open')));
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

// ---------- contact form (no backend — mailto handoff) ----------
const contactForm = document.getElementById('contact-form');
if (contactForm) {
  contactForm.addEventListener('submit', (e) => {
    e.preventDefault();
    const name = contactForm.querySelector('#c-name').value.trim();
    const email = contactForm.querySelector('#c-email').value.trim();
    const msg = contactForm.querySelector('#c-message').value.trim();
    const subject = encodeURIComponent(`Website inquiry from ${name || 'a visitor'}`);
    const body = encodeURIComponent(`${msg}\n\n— ${name} (${email})`);
    window.location.href = `mailto:hello@glazni.com?subject=${subject}&body=${body}`;
  });
}

// ---------- current year ----------
document.querySelectorAll('.js-year').forEach(el => { el.textContent = new Date().getFullYear(); });
