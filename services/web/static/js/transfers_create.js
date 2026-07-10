(function () {
  var protocolsEl = document.getElementById('connection-protocols');
  var select = document.getElementById('id_connection');
  var btn = document.getElementById('dry-run-btn');
  if (!protocolsEl || !select || !btn) return;
  var protocols = JSON.parse(protocolsEl.textContent);
  function sync() {
    var proto = protocols[select.value];
    btn.style.display = (proto === 'rsync') ? 'inline-block' : 'none';
  }
  select.addEventListener('change', sync);
  sync();
})();
