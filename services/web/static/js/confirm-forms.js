// Generic confirm-before-submit gate for any <form data-confirm="message">.
// Needed because CSP (script-src 'self') blocks inline onsubmit="return confirm(...)"
// attributes app-wide — this delegated listener replaces all of them at once.
document.addEventListener('submit', function (e) {
  var form = e.target;
  if (form.matches && form.matches('[data-confirm]') && !confirm(form.dataset.confirm)) {
    e.preventDefault();
  }
});
