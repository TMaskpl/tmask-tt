(function () {
  function toggleKnownHost() {
    var strict = document.getElementById('id_strict_host_key_checking');
    var section = document.getElementById('known-host-section');
    var kind = document.getElementById('id_kind');
    if (strict && section && kind && kind.value === 'ssh') {
      section.style.display = strict.checked ? 'block' : 'none';
    }
  }

  function toggleKind() {
    var kind = document.getElementById('id_kind');
    if (!kind) return;
    var sshFields = document.querySelectorAll('.ssh-only-field');
    var pgFields = document.querySelectorAll('.postgres-only-field');
    sshFields.forEach(function (el) { el.style.display = (kind.value === 'ssh') ? '' : 'none'; });
    pgFields.forEach(function (el) { el.style.display = (kind.value === 'postgres') ? '' : 'none'; });
    if (kind.value === 'ssh') {
      toggleKnownHost();
    }
  }

  function scanHostKey(url) {
    var btn = document.getElementById('scan-btn');
    var result = document.getElementById('scan-result');
    btn.disabled = true;
    result.textContent = 'SCANNING...';
    result.style.color = '';
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.success) {
          document.getElementById('id_known_host_key').value = data.known_host_key;
          result.textContent = 'KEY SCANNED — VERIFY AND SAVE';
          result.style.color = 'var(--green)';
        } else {
          result.textContent = data.message;
          result.style.color = 'var(--red)';
        }
      })
      .catch(function () {
        result.textContent = 'SCAN ERROR';
        result.style.color = 'var(--red)';
      })
      .finally(function () { btn.disabled = false; });
  }

  document.addEventListener('DOMContentLoaded', function () {
    var strict = document.getElementById('id_strict_host_key_checking');
    var kind = document.getElementById('id_kind');
    var scanBtn = document.getElementById('scan-btn');
    if (strict) {
      strict.addEventListener('change', toggleKnownHost);
    }
    if (kind) {
      kind.addEventListener('change', toggleKind);
      toggleKind();
    }
    if (scanBtn) {
      scanBtn.addEventListener('click', function () {
        scanHostKey(scanBtn.dataset.scanUrl);
      });
    }
  });
})();
