(function () {
  const el = document.getElementById('dashboard-data');
  if (!el) return;
  const data = JSON.parse(el.textContent);

  const GREEN = '#33ff33', RED = '#ff3333', OTHER = '#557755';
  const GRID = 'rgba(51,255,51,0.12)', TICK = '#8fdf8f';

  if (!data.success || data.success.total === 0) {
    const empty = document.getElementById('dashboard-empty');
    if (empty) empty.style.display = 'block';
    return;
  }

  Chart.defaults.color = TICK;
  Chart.defaults.font.family = 'monospace';

  new Chart(document.getElementById('chart-per-day'), {
    type: 'bar',
    data: {
      labels: data.per_day.labels,
      datasets: [
        { label: 'DONE', data: data.per_day.done, backgroundColor: GREEN },
        { label: 'FAILED', data: data.per_day.failed, backgroundColor: RED },
      ],
    },
    options: {
      responsive: true,
      scales: {
        x: { stacked: true, grid: { color: GRID } },
        y: { stacked: true, beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } },
      },
    },
  });

  new Chart(document.getElementById('chart-success'), {
    type: 'doughnut',
    data: {
      labels: ['DONE', 'FAILED', 'OTHER'],
      datasets: [{
        data: [data.success.done, data.success.failed, data.success.other],
        backgroundColor: [GREEN, RED, OTHER],
      }],
    },
    options: {
      responsive: true,
      plugins: { title: { display: true, text: 'SUCCESS RATE: ' + data.success.rate_pct + '%' } },
    },
  });

  new Chart(document.getElementById('chart-top'), {
    type: 'bar',
    data: {
      labels: data.top.labels,
      datasets: [{ label: 'JOBS', data: data.top.counts, backgroundColor: GREEN }],
    },
    options: {
      indexAxis: 'y',
      responsive: true,
      scales: {
        x: { beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } },
        y: { grid: { color: GRID } },
      },
    },
  });
})();
