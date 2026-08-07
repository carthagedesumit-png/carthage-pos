async function fetchJson(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Request failed: ${url}`);
    return await response.json();
}

function setDashboardLoading(visible) {
    const el = document.getElementById("dashboardLoading");
    if (!el) return;
    el.classList.toggle("visible", visible);
}

function formatMoney(value) {
    return `NGN ${Number(value || 0).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    })}`;
}

function renderSalesTrend(trend) {
    const container = document.getElementById("salesTrendChart");
    if (!container) return;

    container.innerHTML = "";

    if (!trend.length) {
        container.innerHTML = `<p class="empty-state">No sales trend data yet.</p>`;
        return;
    }

    const max = Math.max(...trend.map(item => item.sales), 1);

    trend.forEach(item => {
        const bar = document.createElement("div");
        bar.className = "dynamic-bar";
        bar.style.height = `${Math.max((item.sales / max) * 180, 12)}px`;
        bar.title = `${item.date}: ${formatMoney(item.sales)}`;
        container.appendChild(bar);
    });
}

function renderTopProducts(products) {
    const container = document.getElementById("topProductsList");
    if (!container) return;

    if (!products.length) {
        container.innerHTML = `<p class="empty-state">No product sales yet.</p>`;
        return;
    }

    container.innerHTML = products.map(product => `
        <div class="ranking-item">
            <span>${product.name}</span>
            <strong>${product.quantity} sold</strong>
            <small>${product.revenue}</small>
        </div>
    `).join("");
}

function renderInsights(insights) {
    const container = document.getElementById("businessInsights");
    if (!container) return;

    if (!insights.length) {
        container.innerHTML = `<p class="empty-state">No insights available yet.</p>`;
        return;
    }

    container.innerHTML = insights.map(item => `
        <div class="notification-item">
            <strong>Insight</strong>
            <span>${item}</span>
        </div>
    `).join("");
}

async function loadBusinessIntelligence() {
    setDashboardLoading(true);
    try {
        const trend = await fetchJson("/dashboard/api/sales-trend");
        renderSalesTrend(trend.trend || []);

        const products = await fetchJson("/dashboard/api/top-products");
        renderTopProducts(Array.isArray(products) ? products : products.products || []);

        const insights = await fetchJson("/dashboard/api/insights");
        renderInsights(insights.insights || []);
    } catch (error) {
        console.error("Dashboard BI load failed", error);
    } finally {
        setDashboardLoading(false);
    }
}

function updateClock() {
    const el = document.getElementById("dashboardClock");
    if (!el) return;

    const now = new Date();
    el.textContent = now.toLocaleTimeString();
}

document.addEventListener("DOMContentLoaded", () => {
    document.addEventListener("keydown", event => {
        if (event.key === "F2" && document.getElementById("barcodeInput")) {
            event.preventDefault(); document.getElementById("barcodeInput").focus();
        }
        if (event.key === "F4" && document.getElementById("completeSale")) {
            event.preventDefault(); document.getElementById("completeSale").focus();
        }
    });
    document.querySelectorAll("form[method='post']").forEach(form => {
        form.addEventListener("submit", () => {
            window.setTimeout(() => {
                form.querySelectorAll("button[type='submit']").forEach(button => {
                    button.disabled = true;
                    button.setAttribute("aria-busy", "true");
                });
            }, 0);
        }, { once: true });
    });
    loadBusinessIntelligence();
    updateClock();

    setInterval(updateClock, 1000);
    setInterval(loadBusinessIntelligence, 60000);
});
