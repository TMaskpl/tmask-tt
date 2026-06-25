(function () {
  const el = document.getElementById('dashboard-data');
  if (!el) return;
  const data = JSON.parse(el.textContent);

  // paleta CRT (tokeny z crt.css)
  const GREEN = '#00ff41', RED = '#ff3333', AMBER = '#ffb000';
  const GRID = 'rgba(51, 255, 51, 0.08)', TICK = '#7fae7f';

  if (!data.success || data.success.total === 0) {
    const empty = document.getElementById('dashboard-empty');
    if (empty) empty.style.display = 'block';
    return;
  }

  Chart.defaults.color = TICK;
  Chart.defaults.font.family = "'JetBrains Mono', monospace";
  Chart.defaults.font.size = 11;
  Chart.defaults.animation.duration = 700;
  Chart.defaults.animation.easing = 'easeOutQuart';
  Chart.defaults.maintainAspectRatio = false;
  Chart.defaults.plugins.legend.labels.boxWidth = 12;
  Chart.defaults.plugins.legend.labels.usePointStyle = true;

  const glow = { shadowColor: 'rgba(0, 255, 65, 0.35)', shadowBlur: 8 };

  new Chart(document.getElementById('chart-per-day'), {
    type: 'bar',
    data: {
      labels: data.per_day.labels,
      datasets: [
        { label: 'DONE', data: data.per_day.done, backgroundColor: GREEN, borderRadius: 2, maxBarThickness: 22 },
        { label: 'FAILED', data: data.per_day.failed, backgroundColor: RED, borderRadius: 2, maxBarThickness: 22 },
      ],
    },
    options: {
      scales: {
        x: { stacked: true, grid: { color: GRID }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 10 } },
        y: { stacked: true, beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } },
      },
      plugins: { legend: { position: 'bottom' } },
    },
  });

  new Chart(document.getElementById('chart-success'), {
    type: 'doughnut',
    data: {
      labels: ['DONE', 'FAILED', 'OTHER'],
      datasets: [{
        data: [data.success.done, data.success.failed, data.success.other],
        backgroundColor: [GREEN, RED, AMBER],
        borderColor: '#0a0a0a',
        borderWidth: 2,
        hoverOffset: 8,
      }],
    },
    options: {
      cutout: '64%',
      plugins: { legend: { position: 'bottom' } },
    },
  });

  new Chart(document.getElementById('chart-top'), {
    type: 'bar',
    data: {
      labels: data.top.labels,
      datasets: [{ label: 'JOBS', data: data.top.counts, backgroundColor: GREEN, borderRadius: 2, maxBarThickness: 18 }],
    },
    options: {
      indexAxis: 'y',
      scales: {
        x: { beginAtZero: true, grid: { color: GRID }, ticks: { precision: 0 } },
        y: { grid: { display: false } },
      },
      plugins: { legend: { display: false } },
    },
  });
})();
