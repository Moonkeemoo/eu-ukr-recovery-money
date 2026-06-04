"use strict";

const esc = (s) => (s ?? "").toString()
  .replace(/&/g, "&amp;").replace(/</g, "&lt;")
  .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const fmt = (n) => new Intl.NumberFormat("uk-UA").format(Math.round(n ?? 0));
const pct = (a, b) => (b > 0 ? Math.round((a / b) * 100) : 0);

const state = { sector: "", region: "", contractYear: "", paymentYear: "",
  gaps: [], gapSort: { key: "contract_amount_uah", dir: -1 } };

function q() {
  const p = new URLSearchParams();
  if (state.sector) p.set("sector", state.sector);
  if (state.region) p.set("region", state.region);
  if (state.contractYear) p.set("contract_year", state.contractYear);
  if (state.paymentYear) p.set("payment_year", state.paymentYear);
  const s = p.toString();
  return s ? `?${s}` : "";
}

async function getJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} -> ${r.status}`);
  return r.json();
}

function debounce(fn, ms) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

function skeleton(el, lines = 3) {
  el.innerHTML = Array.from({ length: lines })
    .map(() => `<div class="skeleton" style="height:1.2rem;margin:.3rem 0"></div>`).join("");
}

// ---- section renderers ----

function renderKpi(k) {
  const el = document.getElementById("kpi");
  const share = pct(k.paid_uah, k.contracted_uah);
  el.innerHTML = `
    <div class="kpi"><div class="label">Оголошено (TED), €</div>
      <div class="value">${fmt(k.announced_eur)}</div></div>
    <div class="kpi"><div class="label">Законтрактовано, грн</div>
      <div class="value">${fmt(k.contracted_uah)}</div></div>
    <div class="kpi"><div class="label">Виплачено, грн</div>
      <div class="value">${fmt(k.paid_uah)}</div>
      <div class="sub">${share}% від законтрактованого</div></div>
    <div class="kpi break"><div class="label">Обриви (контракт без виплати)</div>
      <div class="value">${fmt(k.breaks)}</div></div>`;
}

function bar(label, value, max, cls, right) {
  const w = max > 0 ? Math.max(2, Math.round((value / max) * 100)) : 0;
  return `<div class="bar-row"><span>${esc(label)}</span>
    <span class="bar-track"><span class="bar-fill ${cls}" style="width:${w}%"></span></span>
    <span class="num">${esc(right)}</span></div>`;
}

function renderFunnel(rows) {
  const el = document.getElementById("funnel");
  if (!rows.length) { el.innerHTML = `<div class="empty">Немає даних.</div>`; return; }
  const labels = { contracts: "Контракти", with_payment: "З виплатами", with_ted_overlay: "З TED" };
  const max = Math.max(...rows.map((r) => r.count), 1);
  el.innerHTML = rows.map((r) =>
    bar(labels[r.step] ?? r.step, r.count, max, "funnel", fmt(r.count))).join("");
}

function renderStateBars(rows) {
  const el = document.getElementById("state-bars");
  if (!rows.length) { el.innerHTML = `<div class="empty">Немає даних.</div>`; return; }
  const labels = {
    full: "Повний ланцюг", payment_no_ted: "Виплата без TED",
    contract_no_payment: "Контракт без виплати",
  };
  const max = Math.max(...rows.map((r) => r.count), 1);
  el.innerHTML = rows.map((r) =>
    bar(labels[r.state] ?? r.state, r.count, max, r.state, `${r.count} · ${fmt(r.contracted_uah)} грн`))
    .join("");
}

function renderSankey(data) {
  const svg = d3.select("#sankey");
  svg.selectAll("*").remove();
  const note = document.getElementById("sankey-note");
  note.textContent = data.announced_eur
    ? `Ліва частина (TED) показана для довідки: оголошено €${fmt(data.announced_eur)}. Потік масштабується в грн.`
    : "TED-сторона порожня для цього зрізу — типово для бюджетної підтримки (див. README).";
  const total = (data.links || []).reduce((s, l) => s + l.value, 0);
  if (!total) { return; }
  const width = document.getElementById("sankey").clientWidth || 880;
  const height = 320;
  const { nodes, links } = d3.sankey()
    .nodeWidth(18).nodePadding(20)
    .extent([[1, 1], [width - 1, height - 20]])({
      nodes: data.nodes.map((d) => ({ ...d })),
      links: data.links.map((d) => ({ ...d })),
    });
  svg.attr("viewBox", `0 0 ${width} ${height}`);
  svg.append("g").selectAll("rect").data(nodes).join("rect")
    .attr("x", (d) => d.x0).attr("y", (d) => d.y0)
    .attr("height", (d) => Math.max(1, d.y1 - d.y0))
    .attr("width", (d) => d.x1 - d.x0).attr("fill", "#2563eb")
    .append("title").text((d) => d.name);
  svg.append("g").attr("fill", "none").selectAll("path").data(links).join("path")
    .attr("d", d3.sankeyLinkHorizontal())
    .attr("stroke", "#93c5fd").attr("stroke-width", (d) => Math.max(1, d.width))
    .attr("opacity", .6)
    .append("title").text((d) => `${fmt(d.value)} грн`);
  svg.append("g").selectAll("text").data(nodes).join("text")
    .attr("x", (d) => (d.x0 < width / 2 ? d.x1 + 6 : d.x0 - 6))
    .attr("y", (d) => (d.y1 + d.y0) / 2).attr("dy", "0.35em")
    .attr("text-anchor", (d) => (d.x0 < width / 2 ? "start" : "end"))
    .text((d) => d.name).style("font-size", "12px");
}

function renderTopSuppliers(rows) {
  const el = document.getElementById("top-suppliers");
  if (!rows.length) { el.innerHTML = `<div class="empty">Немає даних.</div>`; return; }
  el.innerHTML = `<table><tbody>${rows.map((r) => `<tr data-edrpou="${esc(r.edrpou)}">
    <td>${esc(r.supplier_name)}</td>
    <td class="num">${fmt(r.contracted_uah)} грн</td></tr>`).join("")}</tbody></table>`;
  el.querySelectorAll("tr[data-edrpou]").forEach((tr) =>
    tr.addEventListener("click", () => openSupplier(tr.dataset.edrpou)));
}

function renderTopRegions(rows) {
  const el = document.getElementById("top-regions");
  if (!rows.length) { el.innerHTML = `<div class="empty">Немає даних.</div>`; return; }
  el.innerHTML = `<table><tbody>${rows.map((r) => `<tr>
    <td>${esc(r.region)}</td>
    <td class="num">${fmt(r.contracted_uah)} грн</td></tr>`).join("")}</tbody></table>`;
}

function renderGaps(rows) {
  state.gaps = rows;
  const tbody = document.querySelector("#gaps tbody");
  const empty = document.getElementById("gaps-empty");
  if (!rows.length) {
    tbody.innerHTML = "";
    empty.textContent = "Обривів немає для цього зрізу.";
    return;
  }
  empty.textContent = "";
  const { key, dir } = state.gapSort;
  const sorted = [...rows].sort((a, b) => {
    const av = a[key], bv = b[key];
    if (typeof av === "number") return (av - bv) * dir;
    return String(av ?? "").localeCompare(String(bv ?? "")) * dir;
  });
  tbody.innerHTML = sorted.map((g) => `<tr data-edrpou="${esc(g.supplier_edrpou)}">
    <td>${esc(g.contract_id)}</td><td>${esc(g.supplier_name)}</td>
    <td>${esc(g.cpv_div)}</td><td>${esc(g.region)}</td>
    <td class="num">${fmt(g.contract_amount_uah)}</td></tr>`).join("");
  tbody.querySelectorAll("tr[data-edrpou]").forEach((tr) =>
    tr.addEventListener("click", () => openSupplier(tr.dataset.edrpou)));
}

async function openSupplier(edrpou) {
  if (!edrpou) return;
  const body = document.getElementById("modal-body");
  body.innerHTML = `<div class="skeleton" style="height:6rem"></div>`;
  document.getElementById("modal-backdrop").classList.add("open");
  try {
    const d = await getJSON(`/api/supplier/${encodeURIComponent(edrpou)}`);
    const rows = (d.contracts || []).map((c) => `<tr>
      <td>${esc(c.contract_id)}</td><td>${esc(c.cpv_div)}</td><td>${esc(c.region)}</td>
      <td class="num">${fmt(c.contract_amount_uah)}</td>
      <td class="num">${fmt(c.paid_amount_uah)}</td>
      <td>${c.ted_id ? esc(c.ted_id) : "—"}${c.ted_match_confidence != null ? '<span class="tag">слабкий TED-збіг</span>' : ""}</td>
      <td>${esc(c.state)}</td></tr>`).join("");
    body.innerHTML = `<h3>Виконавець ЄДРПОУ ${esc(edrpou)}</h3>
      <table><thead><tr><th>Контракт</th><th>CPV</th><th>Регіон</th>
        <th class="num">Контракт, грн</th><th class="num">Виплачено, грн</th>
        <th>TED</th><th>Стан</th></tr></thead>
        <tbody>${rows || '<tr><td colspan="7" class="empty">Немає контрактів.</td></tr>'}</tbody></table>`;
  } catch (e) {
    body.innerHTML = `<div class="error">Не вдалося завантажити: ${esc(e.message)}</div>`;
  }
}

// ---- orchestration ----

async function refresh() {
  ["funnel", "state-bars", "top-suppliers", "top-regions"].forEach((id) =>
    skeleton(document.getElementById(id)));
  try {
    const qs = q();
    const [kpi, funnel, brk, sankey, sup, reg, gaps] = await Promise.all([
      getJSON(`/api/kpi${qs}`),
      getJSON(`/api/funnel`),  // funnel is unfiltered by design (whole-pipeline feasibility)
      getJSON(`/api/breakdown${qs}`),
      getJSON(`/api/sankey${qs}`),
      getJSON(`/api/top?by=supplier${qs ? "&" + qs.slice(1) : ""}`),
      getJSON(`/api/top?by=region${qs ? "&" + qs.slice(1) : ""}`),
      getJSON(`/api/gaps?type=contract_no_payment${qs ? "&" + qs.slice(1) : ""}`),
    ]);
    renderKpi(kpi);
    renderFunnel(funnel);
    renderStateBars(brk);
    renderSankey(sankey);
    renderTopSuppliers(sup);
    renderTopRegions(reg);
    renderGaps(gaps);
  } catch (e) {
    document.getElementById("kpi").innerHTML =
      `<div class="kpi break"><div class="label">Помилка</div>
       <div class="value" style="font-size:.95rem">Дані ще не згенеровано — запустіть пайплайн (python run.py) або scripts/seed_demo.py</div></div>`;
    console.error(e);
  }
}

async function initRegions() {
  try {
    const regions = await getJSON("/api/regions");
    const sel = document.getElementById("region");
    regions.forEach((r) => {
      const o = document.createElement("option");
      o.value = r; o.textContent = r; sel.appendChild(o);
    });
  } catch (e) { console.error(e); }
}

async function initYears() {
  try {
    const y = await getJSON("/api/years");
    const fill = (id, vals) => {
      const sel = document.getElementById(id);
      (vals || []).forEach((v) => {
        const o = document.createElement("option");
        o.value = v; o.textContent = v; sel.appendChild(o);
      });
    };
    fill("contract-year", y.contract_years);
    fill("payment-year", y.payment_years);
  } catch (e) { console.error(e); }
}

function wire() {
  const onFilter = debounce(refresh, 150);
  document.getElementById("sector").addEventListener("change", (e) => {
    state.sector = e.target.value; onFilter();
  });
  document.getElementById("region").addEventListener("change", (e) => {
    state.region = e.target.value; onFilter();
  });
  document.getElementById("contract-year").addEventListener("change", (e) => {
    state.contractYear = e.target.value; onFilter();
  });
  document.getElementById("payment-year").addEventListener("change", (e) => {
    state.paymentYear = e.target.value; onFilter();
  });
  document.querySelectorAll("#gaps th[data-key]").forEach((th) =>
    th.addEventListener("click", () => {
      const key = th.dataset.key;
      state.gapSort = { key, dir: state.gapSort.key === key ? -state.gapSort.dir : -1 };
      renderGaps(state.gaps);
    }));
  const close = () => document.getElementById("modal-backdrop").classList.remove("open");
  document.getElementById("modal-close").addEventListener("click", close);
  document.getElementById("modal-backdrop").addEventListener("click", (e) => {
    if (e.target.id === "modal-backdrop") close();
  });
  let rt;
  let sankeyObserved = false;
  new ResizeObserver(() => {
    if (!sankeyObserved) { sankeyObserved = true; return; }  // skip initial fire; refresh() does first render
    clearTimeout(rt);
    rt = setTimeout(() => getJSON(`/api/sankey${q()}`).then(renderSankey).catch(() => {}), 120);
  }).observe(document.getElementById("sankey"));
}

initRegions();
initYears();
wire();
refresh();
