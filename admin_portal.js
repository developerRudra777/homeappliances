/**
 * VoltCraft Custom Admin Portal - Dedicated JavaScript (admin_portal.js)
 * Handles interactive sidebar, live table filters, modals, and quick actions.
 */

document.addEventListener('DOMContentLoaded', () => {
    // 1. Mobile Sidebar Toggle & Backdrop
    const sidebar = document.querySelector('.portal-sidebar');
    const backdrop = document.createElement('div');
    backdrop.className = 'portal-sidebar-backdrop';
    document.body.appendChild(backdrop);

    window.togglePortalSidebar = function() {
        if (sidebar) {
            sidebar.classList.toggle('show');
            backdrop.classList.toggle('show');
        }
    };

    backdrop.addEventListener('click', () => {
        if (sidebar) {
            sidebar.classList.remove('show');
            backdrop.classList.remove('show');
        }
    });

    // 2. Real-time Live Table Filter (Instant client-side filter for tables)
    const liveFilterInput = document.getElementById('liveTableSearch');
    if (liveFilterInput) {
        liveFilterInput.addEventListener('input', (e) => {
            const query = e.target.value.toLowerCase().trim();
            const rows = document.querySelectorAll('.portal-table tbody tr');
            rows.forEach(row => {
                const text = row.textContent.toLowerCase();
                if (text.includes(query)) {
                    row.style.display = '';
                } else {
                    row.style.display = 'none';
                }
            });
        });
    }

    // 3. Auto Dismiss Alerts
    const alerts = document.querySelectorAll('.portal-main-content .alert');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            if (bsAlert) bsAlert.close();
        }, 5000);
    });

    // 4. Quick Stock Adjusters (+ / -) in Inventory
    document.querySelectorAll('.btn-stock-adjust').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const delta = parseInt(btn.dataset.delta) || 1;
            const input = btn.closest('form').querySelector('input[name="stock"]');
            if (input) {
                let current = parseInt(input.value) || 0;
                input.value = Math.max(0, current + delta);
            }
        });
    });

    // 5. Delete Action Confirmations
    document.querySelectorAll('.btn-portal-delete').forEach(btn => {
        btn.addEventListener('click', (e) => {
            const itemType = btn.dataset.itemType || 'item';
            if (!confirm(`Are you sure you want to permanently delete this ${itemType}? This action cannot be undone.`)) {
                e.preventDefault();
            }
        });
    });
});
