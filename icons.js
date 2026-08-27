/*
 * Centralized app-icon loader for Glazni Apps.
 *
 * Any element marked with data-icon="slug" will try to load
 * /icons/{slug}.png. If that file exists, it replaces the two-letter
 * "mono" initials with the real icon. If it 404s, the initials that
 * are already sitting in the markup are left exactly as they are —
 * so pages look right whether or not an icon has been designed yet.
 *
 * Icon slugs match the APK filenames already used for downloads, e.g.
 * downloads/photo-journal.apk  ->  icons/photo-journal.png
 *
 * To ship a new icon: drop the PNG into /icons/ with the matching
 * slug name. No HTML changes needed anywhere.
 */
(function () {
  var EXTENSION = 'svg';
  var ICON_PATH = 'icons/';

  // Inject sizing rules once so any dropped-in icon fills its badge
  // cleanly, without needing to touch style.css.
  var style = document.createElement('style');
  style.textContent =
    '.app-icon.has-icon, .app-icon-lg.has-icon { padding: 0; overflow: hidden; }' +
    '.app-icon.has-icon img, .app-icon-lg.has-icon img { width: 100%; height: 100%; object-fit: cover; display: block; }';
  document.head.appendChild(style);

  document.querySelectorAll('[data-icon]').forEach(function (el) {
    var slug = el.getAttribute('data-icon');
    if (!slug) return;

    var initials = el.textContent.trim();
    var img = new Image();
    img.alt = el.getAttribute('data-alt') || initials;

    img.onload = function () {
      el.textContent = '';
      el.classList.remove('mono');
      el.classList.add('has-icon');
      el.appendChild(img);
    };
    img.onerror = function () {
      // Icon not available yet — keep the existing initials as-is.
    };

    img.src = ICON_PATH + slug + '.' + EXTENSION;
  });
})();
