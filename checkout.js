/* ==========================================================================
   VoltCraft Checkout & Payment JavaScript (checkout.js)
   Handles payment selector, live card preview, auto-formatting, and UPI shortcuts
   ========================================================================== */

function selectPaymentMethod(method) {
    // Update radio buttons
    document.querySelectorAll('input[name="payment_selector"]').forEach(r => {
        r.checked = (r.value === method);
    });

    // Update active class on card containers
    document.querySelectorAll('.payment-option-card').forEach(card => {
        if (card.getAttribute('data-method') === method) {
            card.classList.add('active');
        } else {
            card.classList.remove('active');
        }
    });

    // Sync with hidden Django select input
    const djangoSelect = document.getElementById('id_payment_method');
    if (djangoSelect) {
        djangoSelect.value = method;
    }

    // Toggle panels
    const panels = {
        'RAZORPAY': document.getElementById('razorpayPanel'),
        'UPI': document.getElementById('upiPanel'),
        'CARD': document.getElementById('cardPanel'),
        'NETBANKING': document.getElementById('netbankingPanel'),
        'COD': document.getElementById('codPanel')
    };

    for (let key in panels) {
        if (panels[key]) {
            if (key === method) {
                panels[key].classList.remove('d-none');
            } else {
                panels[key].classList.add('d-none');
            }
        }
    }

    // Dynamic submit button text
    const submitBtn = document.getElementById('checkoutSubmitBtn');
    if (submitBtn) {
        if (method === 'RAZORPAY') {
            submitBtn.innerHTML = '<i class="bi bi-qr-code-scan me-1"></i> Pay Online / Scan QR Code <i class="bi bi-arrow-right-circle ms-1"></i>';
        } else if (method === 'COD') {
            submitBtn.innerHTML = '<i class="bi bi-cash-stack me-1"></i> Place Order (Cash on Delivery) <i class="bi bi-arrow-right-circle ms-1"></i>';
        } else {
            submitBtn.innerHTML = 'Place Appliance Order <i class="bi bi-arrow-right-circle ms-1"></i>';
        }
    }
}

function setUpiSuffix(suffix) {
    const upiInput = document.getElementById('id_upi_id');
    if (!upiInput) return;
    let val = upiInput.value.trim();
    if (val.includes('@')) {
        val = val.split('@')[0];
    }
    if (!val) {
        val = 'myaccount';
    }
    upiInput.value = val + suffix;
}

document.addEventListener('DOMContentLoaded', function () {
    // Interactive Card Number auto-formatting (adds spaces every 4 digits)
    const cardInput = document.getElementById('cardNumberInput');
    const previewNum = document.getElementById('cardPreviewNumber');
    if (cardInput) {
        cardInput.addEventListener('input', function (e) {
            let val = e.target.value.replace(/\D/g, '').substring(0, 16);
            let formatted = val.match(/.{1,4}/g)?.join(' ') || val;
            e.target.value = formatted;
            if (previewNum) {
                previewNum.textContent = formatted || '•••• •••• •••• ••••';
            }
        });
    }

    // Card Name preview
    const nameInput = document.getElementById('cardNameInput');
    const previewName = document.getElementById('cardPreviewName');
    if (nameInput) {
        nameInput.addEventListener('input', function(e) {
            if (previewName) {
                previewName.textContent = e.target.value.toUpperCase() || 'YOUR NAME';
            }
        });
    }

    // Card Expiry preview
    const expiryInput = document.getElementById('cardExpiryInput');
    const previewExpiry = document.getElementById('cardPreviewExpiry');
    if (expiryInput) {
        expiryInput.addEventListener('input', function(e) {
            let val = e.target.value.replace(/\D/g, '').substring(0, 4);
            if (val.length >= 2) {
                val = val.substring(0, 2) + '/' + val.substring(2);
            }
            e.target.value = val;
            if (previewExpiry) {
                previewExpiry.textContent = val || 'MM/YY';
            }
        });
    }
});
