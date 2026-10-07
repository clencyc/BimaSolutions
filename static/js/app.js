document.addEventListener('DOMContentLoaded', function () {
  const menuToggle = document.getElementById('menuToggle');
  if (menuToggle) {
    menuToggle.addEventListener('click', function () {
      const sidebar = document.getElementById('sidebar');
      if (sidebar) sidebar.classList.toggle('open');
    });
  }

  const passwordToggle = document.querySelector('.toggle-password');
  const passwordInput = document.getElementById('password');
  if (passwordToggle && passwordInput) {
    passwordToggle.addEventListener('click', function () {
      const isHidden = passwordInput.type === 'password';
      passwordInput.type = isHidden ? 'text' : 'password';
      passwordToggle.textContent = isHidden ? 'Hide' : 'Show';
      passwordToggle.setAttribute('aria-label', isHidden ? 'Hide password' : 'Show password');
    });
  }

  const overviewCanvas = document.getElementById('overviewCurveChart');
  const curveCanvas = document.getElementById('epCurveChart');
  const classCanvas = document.getElementById('classBreakdownChart');
  if (window.Chart && overviewCanvas) {
    const renderChart = (selector, data, type) => {
      const ctx = selector.getContext('2d');
      if (!ctx) return;
      new Chart(ctx, {
        type,
        data: {
          labels: data.labels || data.map(row => row.return_period ? `${row.return_period}-yr` : row),
          datasets: [{
            label: data.label || 'Loss (KES)',
            data: data.datasets ? data.datasets[0].data : data.map(d => d.loss || d),
            borderColor: '#0057a8',
            backgroundColor: 'rgba(0,87,168,0.25)',
            fill: type === 'line',
            tension: 0.25
          }]
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } }
        }
      });
    };

    const overviewData = JSON.parse(overviewCanvas.dataset.chart || '[]');
    renderChart(overviewCanvas, overviewData, 'line');

    const epData = JSON.parse(curveCanvas.dataset.chart || '[]');
    if (epData && epData.length) {
      renderChart(curveCanvas, epData.map(d => ({ return_period: d.return_period, loss: d.loss })), 'line');
    }

    const classData = JSON.parse(classCanvas.dataset.chart || '{}');
    if (classData && classData.labels) {
      new Chart(classCanvas.getContext('2d'), {
        type: 'bar',
        data: {
          labels: classData.labels,
          datasets: [
            { label: 'Exposure', data: classData.exposure, backgroundColor: '#7aa6ff' },
            { label: 'Loss 100y', data: classData.loss_100, backgroundColor: '#ffb74d' },
            { label: 'Loss 250y', data: classData.loss_250, backgroundColor: '#4db6ac' }
          ]
        },
        options: { responsive: true, maintainAspectRatio: false, scales: { x: { stacked: true }, y: { stacked: true } } }
      });
    }
  }

  const filterHotspots = () => {
    const filterValue = document.getElementById('hotspotFilter')?.value || 'all';
    const searchValue = (document.getElementById('hotspotSearch')?.value || '').toLowerCase();
    const rows = document.querySelectorAll('#hotspotTableBody tr');
    rows.forEach(row => {
      const status = row.dataset.status;
      const name = (row.dataset.name || '').toLowerCase();
      const matchesFilter = filterValue === 'all' || status === filterValue;
      const matchesSearch = !searchValue || name.includes(searchValue);
      row.style.display = matchesFilter && matchesSearch ? '' : 'none';
    });
  };

  const hotspotFilter = document.getElementById('hotspotFilter');
  if (hotspotFilter) hotspotFilter.addEventListener('change', filterHotspots);
  const hotspotSearch = document.getElementById('hotspotSearch');
  if (hotspotSearch) hotspotSearch.addEventListener('input', filterHotspots);

  const mapNode = document.getElementById('hotspotMap');
  if (mapNode && window.L) {
    const map = L.map('hotspotMap').setView([-1.28, 36.82], 11);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors'
    }).addTo(map);

    const hotspotData = window.hotspotData || [];
    hotspotData.forEach(item => {
      const markerColor = item.flagged ? 'green' : 'red';
      L.circleMarker([item.lat, item.lon], {
        radius: 8,
        color: markerColor,
        fillColor: markerColor,
        fillOpacity: 0.9,
        weight: 1
      }).addTo(map).bindPopup(`<strong>${item.name}</strong><br>${item.flagged ? 'Flagged' : 'Missed'} by proxy<br>AI reason: ${item.ai_reason || 'n/a'}`);
    });
  }

  const reportFilter = document.getElementById('neighbourhoodFilter');
  const reportDate = document.getElementById('dateFilter');
  const reportSearch = document.getElementById('reportSearch');
  const filterReports = () => {
    const neighbourhood = reportFilter ? reportFilter.value : 'All';
    const date = reportDate ? reportDate.value : '';
    const query = (reportSearch ? reportSearch.value : '').toLowerCase();
    document.querySelectorAll('.report-card').forEach(card => {
      const cardNeighbourhood = card.dataset.neighbourhood || '';
      const cardDate = card.dataset.date || '';
      const cardText = card.textContent.toLowerCase();
      const matchesNeighbourhood = neighbourhood === 'All' || cardNeighbourhood === neighbourhood;
      const matchesDate = !date || cardDate === date;
      const matchesQuery = !query || cardText.includes(query);
      card.style.display = matchesNeighbourhood && matchesDate && matchesQuery ? 'block' : 'none';
    });
  };

  if (reportFilter) reportFilter.addEventListener('change', filterReports);
  if (reportDate) reportDate.addEventListener('change', filterReports);
  if (reportSearch) reportSearch.addEventListener('input', filterReports);
});
