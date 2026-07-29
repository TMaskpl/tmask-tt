(function () {
  const form = document.getElementById('masking-rule-form');
  if (!form) return;
  const connSel = document.getElementById('id_connection');
  const tablePicker = document.getElementById('id_table_name_picker');
  const tableHidden = document.getElementById('id_table_name');
  const columnPicker = document.getElementById('id_column_name_picker');
  const columnHidden = document.getElementById('id_column_name');
  const providerSel = document.getElementById('id_faker_provider');
  const tablesUrl = form.dataset.dbTablesUrl;
  const columnsUrl = form.dataset.columnsUrl;

  function loadTables() {
    if (!connSel.value) return;
    fetch(tablesUrl + '?source_connection=' + encodeURIComponent(connSel.value))
      .then(function (r) { return r.text(); })
      .then(function (html) {
        const wrapper = document.createElement('div');
        wrapper.innerHTML = html.trim();
        const newSelect = wrapper.firstChild;
        newSelect.id = 'id_table_name_picker';
        newSelect.removeAttribute('name');
        tablePicker.parentNode.replaceChild(newSelect, tablePicker);
        newSelect.addEventListener('change', loadColumns);
      });
  }

  function loadColumns() {
    const picker = document.getElementById('id_table_name_picker');
    tableHidden.value = picker.value;
    if (!connSel.value || !picker.value) return;
    fetch(columnsUrl + '?connection=' + encodeURIComponent(connSel.value) + '&table_name=' + encodeURIComponent(picker.value))
      .then(function (r) { return r.text(); })
      .then(function (html) {
        const wrapper = document.createElement('div');
        wrapper.innerHTML = html.trim();
        const newSelect = wrapper.firstChild;
        newSelect.id = 'id_column_name_picker';
        newSelect.removeAttribute('name');
        columnPicker.parentNode.replaceChild(newSelect, columnPicker);
        newSelect.addEventListener('change', function () {
          columnHidden.value = newSelect.value;
          const opt = newSelect.options[newSelect.selectedIndex];
          const suggested = opt ? opt.dataset.suggested : '';
          if (suggested && providerSel) providerSel.value = suggested;
        });
      });
  }

  connSel.addEventListener('change', loadTables);
})();
