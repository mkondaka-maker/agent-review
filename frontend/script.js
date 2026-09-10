// Dynamic API Base: Automatically uses relative path if on web/localhost server, fallback to remote
const API_BASE = window.location.protocol.startsWith("http") ? "" : "https://agent-review-1.onrender.com";

// DOM Elements - Screen 1 Setup
const screenSetup = document.getElementById("screenSetup");
const companySelect = document.getElementById("companySelect");
const yearSelect = document.getElementById("yearSelect");
const questionInput = document.getElementById("questionInput");
const analyzeBtn = document.getElementById("analyzeBtn");
const statusMessage = document.getElementById("statusMessage");

// DOM Elements - Screen 2 Results
const screenResults = document.getElementById("screenResults");
const editQueryBtn = document.getElementById("editQueryBtn");
const headerTitleBadge = document.getElementById("headerTitleBadge");
const headerQuestionBadge = document.getElementById("headerQuestionBadge");

// Chart instances store
const charts = {};

// Color Tokens (Clean Modern Theme)
const COLOR_UP = "#1E5642";       // Forest Pine Green
const COLOR_DOWN = "#B84A39";     // Brick Red
const COLOR_ACCENT = "#1E5642";   // Primary Accent
const COLOR_GOLD = "#C49A45";     // Warm Ochre Sand
const COLOR_NEUTRAL = "#2C3E50";  // Slate Navy
const COLOR_BORDER = "#EAE5DD";   // Soft light border

init();

async function init() {
  // Quick-action chips event listener
  document.querySelectorAll(".chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      questionInput.value = chip.dataset.question;
      questionInput.focus();
    });
  });

  // Allow pressing Enter in question input to trigger analysis immediately
  if (questionInput) {
    questionInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        onAnalyze();
      }
    });
  }

  // Setup form event listeners
  companySelect.addEventListener("change", onCompanyChange);
  analyzeBtn.addEventListener("click", onAnalyze);

  // Results screen navigation event listeners
  editQueryBtn.addEventListener("click", showSetupScreen);

  // Tab jump scroll highlighting
  setupTabNavigation();

  // Load initial companies and all available years
  try {
    setStatus("Loading data…", "loading");
    const [compRes, yearRes] = await Promise.all([
      fetch(`${API_BASE}/api/companies`),
      fetch(`${API_BASE}/api/years`),
    ]);

    const compData = await compRes.json();
    if (compData.companies) {
      companySelect.innerHTML = `<option value="">Select company (optional)</option>`;
      compData.companies.forEach((c) => {
        const opt = document.createElement("option");
        opt.value = c;
        opt.textContent = c;
        companySelect.appendChild(opt);
      });
    }

    const yearData = await yearRes.json();
    if (yearData.years) {
      yearSelect.innerHTML = `<option value="">Select year (optional)</option>`;
      yearData.years.forEach((y) => {
        const opt = document.createElement("option");
        opt.value = y;
        opt.textContent = y;
        yearSelect.appendChild(opt);
      });
      yearSelect.disabled = false;
    }

    setStatus("");
  } catch (err) {
    setStatus(`Note: Offline or loading error: ${err.message}`);
  }
}

async function onCompanyChange() {
  const company = companySelect.value;
  yearSelect.innerHTML = `<option value="">Select year (optional)</option>`;

  if (!company) {
    try {
      const res = await fetch(`${API_BASE}/api/years`);
      const data = await res.json();
      if (data.years) {
        data.years.forEach((y) => {
          const opt = document.createElement("option");
          opt.value = y;
          opt.textContent = y;
          yearSelect.appendChild(opt);
        });
      }
    } catch (e) {}
    return;
  }

  try {
    const res = await fetch(`${API_BASE}/api/years?company=${encodeURIComponent(company)}`);
    const data = await res.json();
    if (data.error) throw new Error(data.error);

    if (data.years && data.years.length > 0) {
      data.years.forEach((y) => {
        const opt = document.createElement("option");
        opt.value = y;
        opt.textContent = y;
        yearSelect.appendChild(opt);
      });
      // Auto-select the latest year by default
      yearSelect.value = data.years[0];
      yearSelect.disabled = false;
    }
  } catch (err) {
    setStatus(`Could not load years: ${err.message}`);
  }
}

async function onAnalyze() {
  const company = companySelect.value;
  const year = yearSelect.value;
  const question = questionInput.value.trim();

  // If no input question and no company selected, notify user
  if (!question && !company) {
    return setStatus("Please enter your financial question or select a company.");
  }

  const payload = {
    question: question || (company ? `Give me a complete financial review for ${company} in ${year || 'latest year'}.` : "Give me a complete financial review."),
  };
  if (company) payload.company = company;
  if (year) payload.year = Number(year);

  setStatus("Groq AI is analyzing query & querying Supabase database…", "loading");
  setLoadingState(true);

  try {
    const res = await fetch(`${API_BASE}/api/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      throw new Error(data.error || `Server error (${res.status})`);
    }

    // Auto-sync company and year dropdowns to what Groq identified from messy query
    if (data.company && companySelect) {
      companySelect.value = data.company;
      await onCompanyChange();
      if (data.year && yearSelect) {
        yearSelect.value = data.year;
      }
    }

    // Switch view to Screen 2
    renderReport(data);
    showResultsScreen();
    setStatus("");
  } catch (err) {
    setStatus(`Analysis failed: ${err.message}`);
  } finally {
    setLoadingState(false);
  }
}

function setLoadingState(isLoading) {
  analyzeBtn.disabled = isLoading;
  const btnText = analyzeBtn.querySelector(".btn-text");
  const spinner = analyzeBtn.querySelector(".btn-spinner");
  if (isLoading) {
    btnText.textContent = "Analyzing...";
    if (spinner) spinner.classList.remove("hidden");
  } else {
    btnText.textContent = "Analyze Financials";
    if (spinner) spinner.classList.add("hidden");
  }
}

function setStatus(message, mode) {
  statusMessage.textContent = message;
  statusMessage.className = "status-message" + (mode === "loading" ? " loading" : "");
}

function showSetupScreen() {
  screenResults.classList.add("hidden");
  screenSetup.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showResultsScreen() {
  screenSetup.classList.add("hidden");
  screenResults.classList.remove("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ---------------------------------------------------------------- RENDER REPORT */

function renderReport(data) {
  const compStr = `${data.company} — FY${data.year}` + (data.previous_year ? ` (vs FY${data.previous_year})` : "");
  headerTitleBadge.textContent = compStr;
  
  const queryDisplay = data.interpreted_query || data.evidence.question || "Financial Analysis";
  headerQuestionBadge.textContent = `"${queryDisplay}"`;
  headerQuestionBadge.title = `Interpreted intent: ${queryDisplay}`;

  // 1. Dynamic Section & Tab Visibility
  const sectionsToShow = data.sections_to_show || ["hero", "supporting", "trends", "variances", "ai", "evidence"];
  
  document.querySelectorAll(".results-section").forEach((sec) => {
    const secKey = sec.dataset.section;
    if (sectionsToShow.includes(secKey)) {
      sec.classList.remove("hidden");
    } else {
      sec.classList.add("hidden");
    }
  });

  document.querySelectorAll(".nav-tab").forEach((tab) => {
    const tabKey = tab.dataset.section;
    if (sectionsToShow.includes(tabKey)) {
      tab.classList.remove("hidden");
    } else {
      tab.classList.add("hidden");
    }
  });

  // Ensure first visible tab is active
  const firstVisibleTab = document.querySelector(".nav-tab:not(.hidden)");
  if (firstVisibleTab) {
    document.querySelectorAll(".nav-tab").forEach((t) => t.classList.remove("active"));
    firstVisibleTab.classList.add("active");
  }

  // 2. Render Metric Cards (Hero vs Supporting)
  renderStructuredMetricCards(data);

  // 3. Render Visualizations conditionally
  renderTrendChart("revenueTrendChart", "revenue_trend", data.charts.revenue_trend, COLOR_UP);
  renderTrendChart("netIncomeTrendChart", "net_income_trend", data.charts.net_income_trend, COLOR_GOLD);
  renderCurrentVsPrevious(data.charts.current_vs_previous_revenue);
  renderGroupedBar(data.charts.grouped_comparison);
  renderYoyChart(data.charts.yoy_percent_change);
  renderProfitabilityChart(data.charts.profitability);

  // 4. Render Text & Analysis Sections
  renderVariances(data.variances);
  renderAiReview(data.ai_review, data.ai_error);
  renderObservations(data.key_observations);

  // 5. Evidence Block (Collapsed by default)
  const evidenceDetails = document.getElementById("evidenceDetails");
  if (evidenceDetails) evidenceDetails.open = false;
  
  document.getElementById("evidenceBlock").textContent = JSON.stringify(data.evidence, null, 2);
  const dataSourceLabel = data.data_source === "postgresql" ? "Supabase PostgreSQL Database" : "Financial Statements Dataset";
  document.getElementById("dataSourceInfo").textContent =
    `Source: ${dataSourceLabel} · ${data.company} · Fiscal Year ${data.year}` + (data.year_fallback_note ? ` (${data.year_fallback_note})` : "");
}

/* ---------------------------------------------------------------- METRIC CARDS HIERARCHY */

function renderStructuredMetricCards(data) {
  const heroRow = document.getElementById("heroRow");
  const supportingGrid = document.getElementById("supportingGrid");

  heroRow.innerHTML = "";
  supportingGrid.innerHTML = "";

  const kpiCards = data.kpi_cards || [];
  const comparison = data.comparison || {};

  // Build metric objects from filtered kpi_cards
  const allMetrics = kpiCards.map((card) => {
    const key = card.metric;
    const value = card.value;
    const compData = comparison[key] || {};
    return {
      key: key,
      name: formatMetricName(key),
      value: value,
      percentChange: compData.percent_change,
    };
  });

  const heroTargetNames = ["Revenue", "Net Income", "EPS", "Earning Per Share", "Market Cap", "Market Cap (B USD)", "Gross Profit", "EBITDA"];
  const heroMetrics = [];
  const supportingMetrics = [];

  // Separate into Hero vs Supporting metrics
  allMetrics.forEach((m) => {
    const isHeroTarget = heroTargetNames.some((t) => m.key.toLowerCase() === t.toLowerCase() || m.key.toLowerCase().includes(t.toLowerCase()));
    if (isHeroTarget && heroMetrics.length < 4) {
      heroMetrics.push(m);
    } else {
      supportingMetrics.push(m);
    }
  });

  // Render Hero Cards
  if (heroMetrics.length > 0) {
    heroMetrics.forEach((m) => {
      const card = document.createElement("div");
      card.className = "hero-card";

      const changeHtml = m.percentChange !== null && m.percentChange !== undefined
        ? `<div class="hero-change ${m.percentChange >= 0 ? 'pos' : 'neg'}">${m.percentChange >= 0 ? '▲ +' : '▼ '}${m.percentChange}% YoY</div>`
        : "";

      card.innerHTML = `
        <div class="hero-label">${m.name}</div>
        <div class="hero-value">${formatMetricValue(m.key, m.value)}</div>
        ${changeHtml}
      `;
      heroRow.appendChild(card);
    });
  }

  // Render Supporting Cards
  if (supportingMetrics.length > 0) {
    supportingMetrics.forEach((m) => {
      const card = document.createElement("div");
      card.className = "supporting-card";

      const changeHtml = m.percentChange !== null && m.percentChange !== undefined
        ? `<span class="supporting-change ${m.percentChange >= 0 ? 'pos' : 'neg'}">${m.percentChange >= 0 ? '+' : ''}${m.percentChange}%</span>`
        : "";

      card.innerHTML = `
        <div class="supporting-label">${m.name}</div>
        <div class="supporting-value-row">
          <span class="supporting-value">${formatMetricValue(m.key, m.value)}</span>
          ${changeHtml}
        </div>
      `;
      supportingGrid.appendChild(card);
    });
  }
}

function formatMetricName(key) {
  if (key === "Market Cap (B USD)") return "Market Cap";
  if (key === "Earning Per Share") return "Earning Per Share";
  return key;
}

function formatMetricValue(key, value) {
  if (value === null || value === undefined) return "—";

  const num = Number(value);
  if (isNaN(num)) return value;

  const keyLower = key.toLowerCase();
  
  // Format percentages/ratios
  if (keyLower.includes("margin") || keyLower.includes("roe") || keyLower.includes("roa") || keyLower.includes("roi")) {
    if (Math.abs(num) <= 1 && num !== 0) {
      return (num * 100).toFixed(2) + "%";
    }
    return num.toFixed(2) + "%";
  }

  if (keyLower.includes("current ratio") || keyLower.includes("debt equity") || keyLower.includes("ratio")) {
    return num.toFixed(2);
  }

  if (keyLower.includes("eps") || keyLower.includes("per share")) {
    return "$" + num.toFixed(2);
  }

  if (Math.abs(num) >= 1000) {
    return "$" + num.toLocaleString(undefined, { maximumFractionDigits: 2 });
  }

  return num.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

/* ---------------------------------------------------------------- CHARTS */

function destroyChart(id) {
  if (charts[id]) {
    charts[id].destroy();
    delete charts[id];
  }
}

function toggleChartCardVisibility(chartAttrKey, isAvailable) {
  const card = document.querySelector(`.chart-card[data-chart="${chartAttrKey}"]`);
  if (card) {
    if (isAvailable) {
      card.style.display = "";
    } else {
      card.style.display = "none";
    }
  }
}

function renderTrendChart(canvasId, chartAttrKey, chartData, color) {
  destroyChart(canvasId);
  const isAvailable = chartData && chartData.available;
  toggleChartCardVisibility(chartAttrKey, isAvailable);

  if (!isAvailable) return;

  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  charts[canvasId] = new Chart(ctx, {
    type: "line",
    data: {
      labels: chartData.labels,
      datasets: [{
        label: chartData.metric,
        data: chartData.values,
        borderColor: color,
        backgroundColor: color === COLOR_UP ? "rgba(30, 86, 66, 0.1)" : "rgba(196, 154, 69, 0.1)",
        borderWidth: 2.2,
        tension: 0.3,
        fill: true,
        pointBackgroundColor: color,
        pointRadius: 3.5,
      }],
    },
    options: lightChartOptions(),
  });
}

function renderCurrentVsPrevious(chartData) {
  const canvasId = "currentVsPreviousChart";
  const chartAttrKey = "current_vs_previous_revenue";
  destroyChart(canvasId);
  const isAvailable = chartData && chartData.available;
  toggleChartCardVisibility(chartAttrKey, isAvailable);

  if (!isAvailable) return;

  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  charts[canvasId] = new Chart(ctx, {
    type: "bar",
    data: {
      labels: chartData.labels,
      datasets: [{
        label: chartData.metric,
        data: chartData.values,
        backgroundColor: [COLOR_NEUTRAL, COLOR_UP],
        borderRadius: 3,
      }],
    },
    options: lightChartOptions(),
  });
}

function renderGroupedBar(chartData) {
  const canvasId = "groupedBarChart";
  const chartAttrKey = "grouped_comparison";
  destroyChart(canvasId);
  const isAvailable = chartData && chartData.labels && chartData.labels.length > 0;
  toggleChartCardVisibility(chartAttrKey, isAvailable);

  if (!isAvailable) return;

  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  const colors = [COLOR_NEUTRAL, COLOR_UP];
  charts[canvasId] = new Chart(ctx, {
    type: "bar",
    data: {
      labels: chartData.labels,
      datasets: chartData.series.map((s, i) => ({
        label: s.name,
        data: s.values,
        backgroundColor: colors[i % colors.length],
        borderRadius: 3,
      })),
    },
    options: lightChartOptions(),
  });
}

function renderYoyChart(chartData) {
  const canvasId = "yoyChart";
  const chartAttrKey = "yoy_percent_change";
  destroyChart(canvasId);
  const isAvailable = chartData && chartData.labels && chartData.labels.length > 0;
  toggleChartCardVisibility(chartAttrKey, isAvailable);

  if (!isAvailable) return;

  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  charts[canvasId] = new Chart(ctx, {
    type: "bar",
    data: {
      labels: chartData.labels,
      datasets: [{
        label: "% Change",
        data: chartData.values,
        backgroundColor: chartData.values.map((v) => (v >= 0 ? COLOR_UP : COLOR_DOWN)),
        borderRadius: 3,
      }],
    },
    options: { ...lightChartOptions(), indexAxis: "y" },
  });
}

function renderProfitabilityChart(chartData) {
  const canvasId = "profitabilityChart";
  const chartAttrKey = "profitability";
  destroyChart(canvasId);
  const isAvailable = chartData && chartData.available;
  toggleChartCardVisibility(chartAttrKey, isAvailable);

  if (!isAvailable) return;

  const ctx = document.getElementById(canvasId);
  if (!ctx) return;

  const palette = [COLOR_UP, COLOR_GOLD, COLOR_NEUTRAL];
  charts[canvasId] = new Chart(ctx, {
    type: "line",
    data: {
      labels: chartData.labels,
      datasets: chartData.series.map((s, i) => ({
        label: s.name,
        data: s.values,
        borderColor: palette[i % palette.length],
        backgroundColor: "transparent",
        borderWidth: 2,
        tension: 0.3,
      })),
    },
    options: lightChartOptions(),
  });
}

function lightChartOptions() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    plugins: {
      legend: {
        display: true,
        position: "top",
        labels: { color: "#52616B", font: { family: "IBM Plex Sans", size: 12 } },
      },
      tooltip: {
        backgroundColor: "#1A253C",
        titleColor: "#FFFFFF",
        bodyColor: "#E2E8F0",
        borderColor: "#EAE5DD",
        borderWidth: 1,
      },
    },
    scales: {
      x: {
        grid: { color: "#EAE5DD", drawBorder: false },
        ticks: { color: "#64748B", font: { family: "IBM Plex Sans", size: 11 } },
      },
      y: {
        grid: { color: "#EAE5DD", drawBorder: false },
        ticks: { color: "#64748B", font: { family: "IBM Plex Sans", size: 11 } },
      },
    },
  };
}

/* ---------------------------------------------------------------- MARKDOWN PARSER FOR AI REVIEW */

function parseMarkdownToHtml(markdown) {
  if (!markdown) return "";
  
  let lines = markdown.split("\n");
  let html = [];
  let inTable = false;
  let tableHeaderParsed = false;
  let inList = false;

  for (let i = 0; i < lines.length; i++) {
    let line = lines[i].trim();

    // Table detection
    if (line.startsWith("|") && line.endsWith("|")) {
      // Separator row e.g. |---|---|
      if (/^\|[-:\s|]+\|$/.test(line)) {
        tableHeaderParsed = true;
        continue;
      }

      const cells = line.slice(1, -1).split("|").map((c) => c.trim());
      if (!inTable) {
        if (inList) { html.push("</ul>"); inList = false; }
        html.push('<div class="ai-table-wrapper"><table class="ai-markdown-table">');
        inTable = true;
        tableHeaderParsed = false;
      }

      if (!tableHeaderParsed) {
        html.push("<thead><tr>");
        cells.forEach((c) => html.push(`<th>${formatInlineMarkdown(c)}</th>`));
        html.push("</tr></thead><tbody>");
      } else {
        html.push("<tr>");
        cells.forEach((c) => html.push(`<td>${formatInlineMarkdown(c)}</td>`));
        html.push("</tr>");
      }
      continue;
    } else {
      if (inTable) {
        html.push("</tbody></table></div>");
        inTable = false;
        tableHeaderParsed = false;
      }
    }

    // Horizontal Rule
    if (/^(\*\*\*|---|___)$/.test(line)) {
      if (inList) { html.push("</ul>"); inList = false; }
      html.push('<hr class="ai-hr" />');
      continue;
    }

    // Headings
    if (line.startsWith("### ")) {
      if (inList) { html.push("</ul>"); inList = false; }
      html.push(`<h4>${formatInlineMarkdown(line.slice(4))}</h4>`);
      continue;
    }
    if (line.startsWith("## ")) {
      if (inList) { html.push("</ul>"); inList = false; }
      html.push(`<h3>${formatInlineMarkdown(line.slice(3))}</h3>`);
      continue;
    }
    if (line.startsWith("# ")) {
      if (inList) { html.push("</ul>"); inList = false; }
      html.push(`<h2>${formatInlineMarkdown(line.slice(2))}</h2>`);
      continue;
    }

    // Bullet Lists
    if (line.startsWith("- ") || line.startsWith("* ")) {
      if (!inList) {
        html.push('<ul class="ai-bullet-list">');
        inList = true;
      }
      html.push(`<li>${formatInlineMarkdown(line.slice(2))}</li>`);
      continue;
    } else {
      if (inList) {
        html.push("</ul>");
        inList = false;
      }
    }

    // Empty lines
    if (!line) {
      continue;
    }

    // Regular paragraphs
    html.push(`<p>${formatInlineMarkdown(line)}</p>`);
  }

  if (inTable) html.push("</tbody></table></div>");
  if (inList) html.push("</ul>");

  return html.join("\n");
}

function formatInlineMarkdown(text) {
  if (!text) return "";
  let s = text;
  // Bold **text** or __text__
  s = s.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/__(.*?)__/g, "<strong>$1</strong>");
  // Italic *text* or _text_
  s = s.replace(/\*(.*?)\*/g, "<em>$1</em>");
  s = s.replace(/_(.*?)_/g, "<em>$1</em>");
  // Code `text`
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  return s;
}

/* ---------------------------------------------------------------- VARIANCES & AI REVIEW */

function renderVariances(variances) {
  const list = document.getElementById("varianceList");
  list.innerHTML = "";
  if (!variances || variances.length === 0) {
    list.innerHTML = `<p class="empty-msg">No significant variances detected above threshold.</p>`;
    return;
  }
  variances.forEach((v) => {
    const div = document.createElement("div");
    const isUp = v.direction === "increase";
    div.className = `variance-item ${isUp ? "variance-up" : "variance-down"}`;
    div.innerHTML = `
      <span class="variance-metric">${v.metric}</span>
      <span class="variance-val">${isUp ? "+" : ""}${v.percent_change}%</span>
    `;
    list.appendChild(div);
  });
}

function renderAiReview(review, error) {
  const body = document.getElementById("aiReviewBody");
  if (review) {
    body.innerHTML = parseMarkdownToHtml(review);
    body.classList.remove("error");
  } else {
    body.innerHTML = `<p class="error-msg">AI narrative is temporarily unavailable (${error || "unknown error"}). Calculated values and charts remain accurate.</p>`;
    body.classList.add("error");
  }
}

function renderObservations(observations) {
  const list = document.getElementById("observationsList");
  list.innerHTML = "";
  if (!observations || observations.length === 0) {
    list.innerHTML = `<p class="empty-msg">No observations derived from data.</p>`;
    return;
  }
  observations.forEach((obs) => {
    const div = document.createElement("div");
    div.className = "observation-card";
    div.innerHTML = `<div class="obs-text">${obs}</div>`;
    list.appendChild(div);
  });
}

/* ---------------------------------------------------------------- TAB NAV SCROLL */

function setupTabNavigation() {
  const tabs = document.querySelectorAll(".nav-tab");
  tabs.forEach((tab) => {
    tab.addEventListener("click", (e) => {
      e.preventDefault();
      const targetId = tab.getAttribute("href").substring(1);
      const targetEl = document.getElementById(targetId);
      if (targetEl) {
        tabs.forEach((t) => t.classList.remove("active"));
        tab.classList.add("active");
        const headerOffset = 80;
        const elementPosition = targetEl.getBoundingClientRect().top;
        const offsetPosition = elementPosition + window.pageYOffset - headerOffset;
        window.scrollTo({ top: offsetPosition, behavior: "smooth" });
      }
    });
  });
}
