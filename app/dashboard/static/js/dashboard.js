async function fetchJson(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Request failed: ${url}`);
    return await response.json();
}

function formatMoney(value) {
    return `₦${Number(value || 0).toLocaleString(undefined, {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2
    })}`;
}

function renderSalesTrend(trend) {
    const container = document.getElementById("salesTrendChart");
    if (!container) return;

    container.innerHTML = "";

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

    container.innerHTML = insights.map(item => `
        <div class="notification-item">
            <strong>💡 Insight</strong>
            <span>${item}</span>
        </div>
    `).join("");
}

async function loadBusinessIntelligence() {
    try {
        const trend = await fetchJson("/dashboard/api/sales-trend");
        renderSalesTrend(trend.trend || []);

        const products = await fetchJson("/dashboard/api/top-products");
        renderTopProducts(products.products || []);

        const insights = await fetchJson("/dashboard/api/insights");
        renderInsights(insights.insights || []);
    } catch (error) {
        console.error("Dashboard BI load failed", error);
    }
}

function updateClock() {
    const el = document.getElementById("dashboardClock");
    if (!el) return;

    const now = new Date();
    el.textContent = now.toLocaleTimeString();
}

document.addEventListener("DOMContentLoaded", () => {
    loadBusinessIntelligence();
    updateClock();

    setInterval(updateClock, 1000);
    setInterval(loadBusinessIntelligence, 60000);
});
