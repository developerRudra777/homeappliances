// VoltCraft Appliances Store - Interactive Frontend JavaScript

document.addEventListener('DOMContentLoaded', () => {
    // 1. Auto-dismiss Bootstrap alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert:not(.alert-permanent)');
    alerts.forEach(alert => {
        setTimeout(() => {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            if (bsAlert) {
                bsAlert.close();
            }
        }, 5000);
    });

    // 2. Quantity adjuster (+ and - buttons)
    document.querySelectorAll('.btn-qty-plus').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const input = btn.closest('.input-group').querySelector('.input-qty');
            if (input) {
                const max = parseInt(input.getAttribute('max')) || 99;
                let val = parseInt(input.value) || 1;
                if (val < max) {
                    input.value = val + 1;
                    triggerChange(input);
                }
            }
        });
    });

    document.querySelectorAll('.btn-qty-minus').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const input = btn.closest('.input-group').querySelector('.input-qty');
            if (input) {
                const min = parseInt(input.getAttribute('min')) || 1;
                let val = parseInt(input.value) || 1;
                if (val > min) {
                    input.value = val - 1;
                    triggerChange(input);
                }
            }
        });
    });

    function triggerChange(element) {
        const event = new Event('change', { bubbles: true });
        element.dispatchEvent(event);
    }

    // 3. Confirm prompt before removing item from cart
    document.querySelectorAll('.btn-remove-item').forEach(btn => {
        btn.addEventListener('click', (e) => {
            if (!confirm('Are you sure you want to remove this appliance from your shopping cart?')) {
                e.preventDefault();
            }
        });
});

