(function () {
  var copyBtn = document.getElementById('copy-token-btn');
  var closeBtn = document.getElementById('close-token-modal');
  var tokenEl = document.getElementById('new-token-value');
  var modal = document.getElementById('token-modal');

  if (copyBtn && tokenEl) {
    copyBtn.addEventListener('click', function () {
      navigator.clipboard.writeText(tokenEl.textContent);
    });
  }
  if (closeBtn && modal) {
    closeBtn.addEventListener('click', function () {
      modal.style.display = 'none';
    });
  }
})();
