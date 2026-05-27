var _browserTargetField = null;

function openBrowser(fieldId, connPk, path) {
  if (!connPk) {
    alert('Wybierz najpierw połączenie.');
    return;
  }
  path = path || '/';
  _browserTargetField = fieldId;
  var url = '/connections/' + connPk + '/browse/?path=' + encodeURIComponent(path)
          + '&field_id=' + encodeURIComponent(fieldId);
  var content = document.getElementById('file-browser-content');
  content.innerHTML = '<p style="color:var(--amber)">[ ŁADOWANIE... ]</p>';
  document.getElementById('file-browser-overlay').style.display = 'flex';
  htmx.ajax('GET', url, {target: '#file-browser-content', swap: 'innerHTML'});
}

function selectPath(path) {
  document.getElementById(_browserTargetField).value = path;
  closeBrowser();
}

function closeBrowser() {
  document.getElementById('file-browser-overlay').style.display = 'none';
  document.getElementById('file-browser-content').innerHTML = '';
}

document.addEventListener('click', function (e) {
  var el = e.target.closest('[data-browse-open]');
  if (el) {
    e.preventDefault();
    var connPk = el.dataset.browseConnSel
      ? document.querySelector(el.dataset.browseConnSel).value
      : el.dataset.browseConn;
    openBrowser(el.dataset.browseField, connPk, el.dataset.browsePath || '/');
    return;
  }
  el = e.target.closest('[data-browse-select]');
  if (el) {
    e.preventDefault();
    selectPath(el.dataset.browseSelect);
    return;
  }
  el = e.target.closest('[data-browse-close]');
  if (el) {
    closeBrowser();
    return;
  }
});
