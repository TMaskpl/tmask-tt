(function () {
  const form = document.getElementById('db-transfer-form');
  const sourceSel = document.getElementById('id_source_connection');
  let tableField = document.getElementById('id_table_name');
  if (!form || !sourceSel || !tableField) return;
  const tablesUrl = form.dataset.dbTablesUrl;

  function loadTables() {
    if (!sourceSel.value) return;
    fetch(tablesUrl + '?source_connection=' + encodeURIComponent(sourceSel.value))
      .then(function (r) { return r.text(); })
      .then(function (html) {
        const wrapper = document.createElement('div');
        wrapper.innerHTML = html.trim();
        const newSelect = wrapper.firstChild;
        tableField.parentNode.replaceChild(newSelect, tableField);
        tableField = newSelect;
      });
  }
  sourceSel.addEventListener('change', loadTables);

  const engineInputs = document.querySelectorAll('input[name="engine"]');
  engineInputs.forEach(function (input) {
    input.addEventListener('change', function () {
      window.location.href = window.location.pathname + '?engine=' + encodeURIComponent(input.value);
    });
  });

  form.addEventListener('submit', function (e) {
    const destSel = document.getElementById('id_dest_connection');
    const scopeInput = document.querySelector('input[name="scope"]:checked');
    const sourceName = sourceSel.options[sourceSel.selectedIndex] ? sourceSel.options[sourceSel.selectedIndex].text : '';
    const destName = destSel.options[destSel.selectedIndex] ? destSel.options[destSel.selectedIndex].text : '';
    let msg;
    if (scopeInput?.value === 'table') {
      const tableName = tableField ? tableField.value : '';
      msg = 'Czy na pewno? Nadpisze tabelę "' + tableName + '" w "' + destName + '" danymi z "' + sourceName + '".';
    } else {
      msg = 'Czy na pewno? Nadpisze WSZYSTKIE tabele w bazie docelowej ("' + destName + '") danymi z "' + sourceName + '".';
    }
    if (!confirm(msg)) {
      e.preventDefault();
    }
  });
})();
