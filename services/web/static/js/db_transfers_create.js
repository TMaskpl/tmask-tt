(function () {
  var form = document.getElementById('pg-transfer-form');
  var sourceSel = document.getElementById('id_source_connection');
  var tableField = document.getElementById('id_table_name');
  if (!form || !sourceSel || !tableField) return;
  var tablesUrl = form.dataset.pgTablesUrl;

  function loadTables() {
    if (!sourceSel.value) return;
    fetch(tablesUrl + '?source_connection=' + encodeURIComponent(sourceSel.value))
      .then(function (r) { return r.text(); })
      .then(function (html) {
        var wrapper = document.createElement('div');
        wrapper.innerHTML = html.trim();
        var newSelect = wrapper.firstChild;
        tableField.parentNode.replaceChild(newSelect, tableField);
        tableField = newSelect;
      });
  }
  sourceSel.addEventListener('change', loadTables);

  form.addEventListener('submit', function (e) {
    var destSel = document.getElementById('id_dest_connection');
    var scopeInput = document.querySelector('input[name="scope"]:checked');
    var sourceName = sourceSel.options[sourceSel.selectedIndex] ? sourceSel.options[sourceSel.selectedIndex].text : '';
    var destName = destSel.options[destSel.selectedIndex] ? destSel.options[destSel.selectedIndex].text : '';
    var msg;
    if (scopeInput && scopeInput.value === 'table') {
      var tableName = tableField ? tableField.value : '';
      msg = 'Czy na pewno? Nadpisze tabelę "' + tableName + '" w "' + destName + '" danymi z "' + sourceName + '".';
    } else {
      msg = 'Czy na pewno? Nadpisze WSZYSTKIE tabele w bazie docelowej ("' + destName + '") danymi z "' + sourceName + '".';
    }
    if (!confirm(msg)) {
      e.preventDefault();
    }
  });
})();
