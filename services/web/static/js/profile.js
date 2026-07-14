(function () {
  const copyBtn = document.getElementById('copy-token-btn');
  const closeBtn = document.getElementById('close-token-modal');
  const tokenEl = document.getElementById('new-token-value');
  const modal = document.getElementById('token-modal');

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
