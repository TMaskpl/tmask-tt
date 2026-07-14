(function () {
  const input = document.getElementById('id_cron_expr');
  if (!input) return;
  document.querySelectorAll('.cron-ex').forEach(function (el) {
    el.addEventListener('click', function () {
      input.value = el.dataset.cron;
      input.focus();
    });
  });
})();
