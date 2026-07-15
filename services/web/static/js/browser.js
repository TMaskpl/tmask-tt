let _browserTargetField = null;

function openBrowser(fieldId, connPk, path) {
  if (!connPk) {
    alert('Wybierz najpierw połączenie.');
    return;
  }
  path = path || '/';
  _browserTargetField = fieldId;
  const url = '/connections/' + connPk + '/browse/?path=' + encodeURIComponent(path)
          + '&field_id=' + encodeURIComponent(fieldId);
  const content = document.getElementById('file-browser-content');
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

// Stylizowany file input — pokaż nazwę wybranego pliku w polu tekstowym
document.addEventListener('change', function (e) {
  const input = e.target.closest('input[type="file"][data-file-display]');
  if (!input) return;
  const display = document.getElementById(input.dataset.fileDisplay);
  if (display) {
    display.value = input.files?.length ? input.files[0].name : '';
  }
});

document.addEventListener('click', function (e) {
  let el = e.target.closest('[data-browse-open]');
  if (el) {
    e.preventDefault();
    const connPk = el.dataset.browseConnSel
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
  }
});
