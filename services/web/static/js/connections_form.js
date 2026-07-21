(function () {
  function toggleKnownHost() {
    const strict = document.getElementById('id_strict_host_key_checking');
    const section = document.getElementById('known-host-section');
    const kind = document.getElementById('id_kind');
    if (strict && section && kind?.value === 'ssh') {
      section.style.display = strict.checked ? 'block' : 'none';
    }
  }

  const DB_KINDS = ['postgres', 'mysql', 'mssql'];
  const DEFAULT_PORTS = { postgres: 5432, mysql: 3306, mssql: 1433, ssh: 22 };

  function toggleKind() {
    const kind = document.getElementById('id_kind');
    if (!kind) return;
    const sshFields = document.querySelectorAll('.ssh-only-field');
    const dbFields = document.querySelectorAll('.db-kind-field');
    sshFields.forEach(function (el) { el.style.display = (kind.value === 'ssh') ? '' : 'none'; });
    dbFields.forEach(function (el) { el.style.display = DB_KINDS.includes(kind.value) ? '' : 'none'; });
    if (kind.value === 'ssh') toggleKnownHost();
  }

  function suggestPort() {
    const kind = document.getElementById('id_kind');
    const port = document.getElementById('id_port');
    if (!kind || !port) return;
    // Only overwrite an empty/default-looking port — never clobber a value the user already typed.
    if (!port.dataset.touched) port.value = DEFAULT_PORTS[kind.value] || '';
  }

  function scanHostKey(url) {
    const btn = document.getElementById('scan-btn');
    const result = document.getElementById('scan-result');
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
    const strict = document.getElementById('id_strict_host_key_checking');
    const kind = document.getElementById('id_kind');
    const port = document.getElementById('id_port');
    const scanBtn = document.getElementById('scan-btn');
    if (strict) {
      strict.addEventListener('change', toggleKnownHost);
    }
    if (kind) {
      kind.addEventListener('change', function () { toggleKind(); suggestPort(); });
      toggleKind();
    }
    if (port) {
      port.addEventListener('input', function () { port.dataset.touched = 'true'; });
    }
    if (scanBtn) {
      scanBtn.addEventListener('click', function () {
        scanHostKey(scanBtn.dataset.scanUrl);
      });
    }
  });
})();
