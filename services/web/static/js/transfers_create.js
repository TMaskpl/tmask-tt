(function () {
  const protocolsEl = document.getElementById('connection-protocols');
  const select = document.getElementById('id_connection');
  const btn = document.getElementById('dry-run-btn');
  if (!protocolsEl || !select || !btn) return;
  const protocols = JSON.parse(protocolsEl.textContent);
  function sync() {
    const proto = protocols[select.value];
    btn.style.display = (proto === 'rsync') ? 'inline-block' : 'none';
  }
  select.addEventListener('change', sync);
  sync();
})();
