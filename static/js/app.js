// ===================== Theme =====================
(function () {
  const saved = localStorage.getItem("hr-theme");
  if (saved) document.documentElement.setAttribute("data-theme", saved);
})();
function toggleTheme() {
  const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", cur);
  localStorage.setItem("hr-theme", cur);
}

// ===================== Sidebar (mobile) =====================
function toggleSidebar() {
  document.querySelector(".sidebar").classList.toggle("open");
  document.querySelector(".overlay").classList.toggle("show");
}

// ===================== Dropdowns =====================
document.addEventListener("click", function (e) {
  const clickedToggle = e.target.closest("[data-dropdown-toggle]");
  document.querySelectorAll(".dropdown.open").forEach((dd) => {
    if (!clickedToggle || dd !== clickedToggle.closest(".dropdown")) dd.classList.remove("open");
  });
  if (clickedToggle) {
    clickedToggle.closest(".dropdown").classList.toggle("open");
  }
});

// ===================== Nav groups (collapsible sidebar sections) =====================
function toggleNavGroup(el) {
  el.closest(".nav-group").classList.toggle("open");
}

// ===================== Confirm modal for deletes / destructive actions =====================
let pendingForm = null;
function confirmDelete(form, message) {
  pendingForm = form;
  document.getElementById("confirm-message").textContent = message || "This action cannot be undone.";
  document.getElementById("confirm-modal").classList.add("show");
  return false;
}
function closeConfirm() {
  document.getElementById("confirm-modal").classList.remove("show");
  pendingForm = null;
}
function proceedConfirm() {
  if (pendingForm) pendingForm.submit();
  closeConfirm();
}

// ===================== Line items builder (salary structure / offer components) =====================
function addLineItem(tableBodyId, template) {
  const tbody = document.getElementById(tableBodyId);
  const idx = tbody.querySelectorAll("tr").length;
  const html = template.replaceAll("__IDX__", idx);
  const tr = document.createElement("tr");
  tr.innerHTML = html;
  tbody.appendChild(tr);
}
function removeLineItem(btn) {
  const tr = btn.closest("tr");
  tr.remove();
}

// ===================== Simple SVG charts (no external libs) =====================
function drawBarChart(svgId, data, opts = {}) {
  const svg = document.getElementById(svgId);
  if (!svg) return;
  const W = svg.clientWidth || 500, H = svg.clientHeight || 220;
  const pad = { top: 14, right: 10, bottom: 28, left: 40 };
  const max = Math.max(1, ...data.map((d) => d.value)) * 1.15;
  const barW = (W - pad.left - pad.right) / data.length;
  const color = opts.color || "#245b96";
  let svgHtml = "";
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + ((H - pad.top - pad.bottom) * i) / 4;
    svgHtml += `<line x1="${pad.left}" y1="${y}" x2="${W - pad.right}" y2="${y}" stroke="currentColor" stroke-opacity="0.08"/>`;
  }
  data.forEach((d, i) => {
    const h = ((H - pad.top - pad.bottom) * d.value) / max;
    const x = pad.left + i * barW + barW * 0.2;
    const y = H - pad.bottom - h;
    const w = barW * 0.6;
    svgHtml += `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="4" fill="${color}" opacity="0.9"><title>${d.label}: ${d.value}</title></rect>`;
    svgHtml += `<text x="${x + w / 2}" y="${H - pad.bottom + 16}" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.6">${d.label}</text>`;
  });
  svg.innerHTML = svgHtml;
}

function drawLineChart(svgId, data, opts = {}) {
  const svg = document.getElementById(svgId);
  if (!svg) return;
  const W = svg.clientWidth || 500, H = svg.clientHeight || 220;
  const pad = { top: 14, right: 26, bottom: 28, left: 44 };
  const max = Math.max(1, ...data.map((d) => d.value)) * 1.15;
  const stepX = (W - pad.left - pad.right) / Math.max(1, data.length - 1);
  const color = opts.color || "#245b96";
  let points = data.map((d, i) => {
    const x = pad.left + i * stepX;
    const y = H - pad.bottom - ((H - pad.top - pad.bottom) * d.value) / max;
    return [x, y];
  });
  let svgHtml = "";
  for (let i = 0; i <= 4; i++) {
    const y = pad.top + ((H - pad.top - pad.bottom) * i) / 4;
    svgHtml += `<line x1="${pad.left}" y1="${y}" x2="${W - pad.right}" y2="${y}" stroke="currentColor" stroke-opacity="0.08"/>`;
  }
  const path = points.map((p, i) => (i === 0 ? "M" : "L") + p[0].toFixed(1) + "," + p[1].toFixed(1)).join(" ");
  const areaPath = path + ` L${points[points.length - 1][0]},${H - pad.bottom} L${points[0][0]},${H - pad.bottom} Z`;
  svgHtml += `<path d="${areaPath}" fill="${color}" opacity="0.08"/>`;
  svgHtml += `<path d="${path}" fill="none" stroke="${color}" stroke-width="2.2"/>`;
  points.forEach((p, i) => {
    svgHtml += `<circle cx="${p[0]}" cy="${p[1]}" r="3.2" fill="${color}"><title>${data[i].label}: ${data[i].value}</title></circle>`;
    svgHtml += `<text x="${p[0]}" y="${H - pad.bottom + 16}" text-anchor="middle" font-size="10.5" fill="currentColor" opacity="0.6">${data[i].label}</text>`;
  });
  svg.innerHTML = svgHtml;
}

function drawDonutChart(svgId, data, opts = {}) {
  const svg = document.getElementById(svgId);
  if (!svg) return;
  const W = svg.clientWidth || 200, H = svg.clientHeight || 200;
  const cx = W / 2, cy = H / 2, r = Math.min(W, H) / 2 - 6, thickness = opts.thickness || 18;
  const total = data.reduce((a, d) => a + d.value, 0) || 1;
  const colors = opts.colors || ["#245b96", "#1d8f5e", "#e08327", "#cf4444", "#5b4fc4", "#6b7488"];
  let angle = -Math.PI / 2;
  let svgHtml = "";
  data.forEach((d, i) => {
    const frac = d.value / total;
    const a2 = angle + frac * Math.PI * 2;
    const x1 = cx + r * Math.cos(angle), y1 = cy + r * Math.sin(angle);
    const x2 = cx + r * Math.cos(a2), y2 = cy + r * Math.sin(a2);
    const large = frac > 0.5 ? 1 : 0;
    if (frac > 0) {
      svgHtml += `<path d="M${x1},${y1} A${r},${r} 0 ${large} 1 ${x2},${y2}" fill="none" stroke="${colors[i % colors.length]}" stroke-width="${thickness}"><title>${d.label}: ${d.value}</title></path>`;
    }
    angle = a2;
  });
  svg.innerHTML = svgHtml;
}

// ===================== Global search =====================
let searchTimer;
function onGlobalSearch(input) {
  clearTimeout(searchTimer);
  const q = input.value.trim();
  const resultsBox = document.getElementById("global-search-results");
  if (q.length < 2) { resultsBox.classList.remove("show"); return; }
  searchTimer = setTimeout(() => {
    fetch("/search/api?q=" + encodeURIComponent(q))
      .then((r) => r.json())
      .then((data) => {
        let html = "";
        if (data.length === 0) html = '<div class="dd-title">No results</div>';
        data.forEach((item) => {
          html += `<a href="${item.url}"><span class="ic">${item.icon}</span> <div><div>${item.title}</div><div class="text-muted" style="font-size:11px">${item.subtitle}</div></div></a>`;
        });
        resultsBox.innerHTML = html;
        resultsBox.classList.add("show");
      });
  }, 220);
}
document.addEventListener("click", function (e) {
  const box = document.getElementById("global-search-results");
  if (box && !e.target.closest(".search-box")) box.classList.remove("show");
});

// ===================== Photo preview on file input =====================
function previewFiles(inputEl, previewContainerId) {
  const container = document.getElementById(previewContainerId);
  if (!container || !inputEl.files) return;
  container.innerHTML = "";
  Array.from(inputEl.files).forEach(function (file) {
    if (!file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = function (e) {
      const div = document.createElement("div");
      div.className = "media-card";
      div.innerHTML = '<img src="' + e.target.result + '">';
      container.appendChild(div);
    };
    reader.readAsDataURL(file);
  });
}

// ===================== Single photo preview (e.g. employee photo, single file input) =====================
function previewSingleFile(inputEl, imgId) {
  const img = document.getElementById(imgId);
  if (!img || !inputEl.files || !inputEl.files[0]) return;
  const reader = new FileReader();
  reader.onload = function (e) { img.src = e.target.result; };
  reader.readAsDataURL(inputEl.files[0]);
}

// ===================== Kanban drag & drop (recruitment / CRM pipeline) =====================
function initKanbanDnD(onDropUrlTemplate) {
  document.querySelectorAll(".kanban-card[draggable]").forEach(function (card) {
    card.addEventListener("dragstart", function (e) {
      e.dataTransfer.setData("text/plain", card.dataset.id);
      setTimeout(() => card.classList.add("dragging"), 0);
    });
    card.addEventListener("dragend", function () { card.classList.remove("dragging"); });
  });
  document.querySelectorAll(".kanban-col").forEach(function (col) {
    col.addEventListener("dragover", function (e) { e.preventDefault(); col.style.background = "var(--brand-100)"; });
    col.addEventListener("dragleave", function () { col.style.background = ""; });
    col.addEventListener("drop", function (e) {
      e.preventDefault();
      col.style.background = "";
      const id = e.dataTransfer.getData("text/plain");
      const stage = col.dataset.stage;
      if (!id || !stage) return;
      const url = onDropUrlTemplate.replace("__ID__", id);
      const fd = new FormData();
      fd.append("stage", stage);
      fetch(url, { method: "POST", body: fd }).then(() => location.reload());
    });
  });
}
