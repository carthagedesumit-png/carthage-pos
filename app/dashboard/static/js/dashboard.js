let salesChart = null;

async function fetchJson(url) {
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`Request failed: ${url}`);
    }
    return await response.json();
}

function money(value) {
    const number = Number(value || 0);
    return `₦${number.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

async function loadSalesChart() {
    const data = await fetchJson("/dashboard/api/sales-chart");
    const ctx = document.getElementById("salesChart");

    if (!ctx) return;

    if (salesChart) {
        salesChart.destroy();
    }

    salesChart = new Chart(ctx, {
        type: "line",
        data: {
            labels: data.labels,
            datasets: [{
                label: "Sales",
                data: data.values,
                tension: 0.35
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: { display: true }
            }
        }
    });
}

async function loadRecentSales() {
    const rows = await fetchJson("/dashboard/api/recent-sales");
    const body = document.getElementById("recentSalesBody");
    if (!body) return;

    body.innerHTML = rows.length
        ? rows.map(row => `
            <tr>
                <td>${row.sale_reference ?? "-"}</td>
                <td>${row.cashier_name ?? "-"}</td>
                <td>${money(row.total_amount)}</td>
            </tr>
        `).join("")
        : `<tr><td colspan="3">No recent sales</td></tr>`;
}

async function loadTopProducts() {
    const rows = await fetchJson("/dashboard/api/top-products");
    const body = document.getElementById("topProductsBody");
    if (!body) return;

    body.innerHTML = rows.length
        ? rows.map(row => `
            <tr>
                <td>${row.product_name ?? "-"}</td>
                <td>${row.qty ?? 0}</td>
            </tr>
        `).join("")
        : `<tr><td colspan="2">No product sales yet</td></tr>`;
}

async function loadLowStock() {
    const rows = await fetchJson("/dashboard/api/low-stock");
    const body = document.getElementById("lowStockBody");
    if (!body) return;

    body.innerHTML = rows.length
        ? rows.map(row => `
            <tr>
                <td>${row.quantity_on_hand}</td>
                <td>${row.reorder_level}</td>
            </tr>
        `).join("")
        : `<tr><td colspan="2">No low-stock alerts</td></tr>`;
}

async function loadDashboardWidgets() {
    try {
        await Promise.all([
            loadSalesChart(),
            loadRecentSales(),
            loadTopProducts(),
            loadLowStock()
        ]);
    } catch (error) {
        console.error("Dashboard refresh failed", error);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    loadDashboardWidgets();
    setInterval(loadDashboardWidgets, 30000);
});

function updateClock(){

    const clock=document.getElementById("liveClock");

    if(!clock) return;

    clock.textContent=new Date().toLocaleTimeString();

}

updateClock();

setInterval(updateClock,1000);

