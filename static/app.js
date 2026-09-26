/**
 * Fulfillment Hub — Client-side JavaScript
 * All fetch()-based interactions: status advance, pick toggles, transfers, issues
 */

// =========================================================================
// Toast notifications
// =========================================================================

function showToast(message, type = 'success') {
    let container = document.querySelector('.toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'toast-container';
        document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'toast-out 0.2s ease-in forwards';
        setTimeout(() => toast.remove(), 200);
    }, 3000);
}

// =========================================================================
// Order status advance
// =========================================================================

async function advanceOrder(orderId) {
    try {
        const res = await fetch(`/api/order/${orderId}/advance`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'Failed to advance order', 'error');
            return;
        }
        showToast(`Order advanced to: ${data.status.toUpperCase()}`);
        // Reload after short delay so user sees the toast
        setTimeout(() => location.reload(), 600);
    } catch (err) {
        showToast('Network error', 'error');
    }
}

// =========================================================================
// Pick/pack checkbox toggle
// =========================================================================

async function togglePick(orderId, itemId, checkbox) {
    const picked = checkbox.checked;
    try {
        const res = await fetch(`/api/order/${orderId}/item/${itemId}/pick`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ picked })
        });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'Failed to update', 'error');
            checkbox.checked = !picked;
            return;
        }

        // Update row visual
        const row = checkbox.closest('tr');
        if (picked) {
            row.style.opacity = '0.6';
        } else {
            row.style.opacity = '1';
        }

        // Update advance button state
        const advBtn = document.getElementById('advance-btn');
        const blockBanner = document.getElementById('block-banner');
        if (data.all_picked) {
            if (advBtn) {
                advBtn.disabled = false;
            }
            if (blockBanner) {
                blockBanner.style.display = 'none';
            }
        } else {
            if (advBtn) {
                advBtn.disabled = true;
            }
            if (blockBanner) {
                blockBanner.style.display = 'flex';
            }
        }

        showToast(picked ? 'Item verified ✓' : 'Item unchecked');
    } catch (err) {
        showToast('Network error', 'error');
        checkbox.checked = !picked;
    }
}

// =========================================================================
// Transfer request
// =========================================================================

async function requestTransfer(productId, quantity) {
    try {
        const res = await fetch('/api/transfer/request', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ product_id: productId, quantity: quantity })
        });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'Failed to request transfer', 'error');
            return;
        }
        showToast('Transfer requested');
        setTimeout(() => location.reload(), 600);
    } catch (err) {
        showToast('Network error', 'error');
    }
}

// =========================================================================
// Transfer advance
// =========================================================================

async function advanceTransfer(transferId) {
    try {
        const res = await fetch(`/api/transfer/${transferId}/advance`, { method: 'POST' });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'Failed to advance transfer', 'error');
            return;
        }
        showToast(`Transfer → ${data.status.replace('_', ' ').toUpperCase()}`);
        setTimeout(() => location.reload(), 600);
    } catch (err) {
        showToast('Network error', 'error');
    }
}

// =========================================================================
// Courier update
// =========================================================================

async function updateCourier(orderId, selectEl) {
    const courier = selectEl.value;
    try {
        const res = await fetch(`/api/order/${orderId}/courier`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ courier })
        });
        if (res.ok) {
            showToast('Courier updated');
        }
    } catch (err) {
        showToast('Network error', 'error');
    }
}

// =========================================================================
// Issue flagging
// =========================================================================

async function submitIssue(orderId, event) {
    event.preventDefault();
    const form = event.target;
    const textarea = form.querySelector('textarea');
    const note = textarea.value.trim();
    if (!note) {
        showToast('Please enter a note', 'error');
        return;
    }
    try {
        const res = await fetch(`/api/order/${orderId}/issue`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note })
        });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'Failed to create issue', 'error');
            return;
        }
        showToast('Issue flagged');
        setTimeout(() => location.reload(), 600);
    } catch (err) {
        showToast('Network error', 'error');
    }
}

// =========================================================================
// Issue resolve/unresolve
// =========================================================================

async function toggleIssue(issueId, checkbox) {
    const resolved = checkbox.checked;
    try {
        const res = await fetch(`/api/issue/${issueId}/resolve`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ resolved })
        });
        const data = await res.json();
        if (!res.ok) {
            showToast(data.error || 'Failed to update issue', 'error');
            checkbox.checked = !resolved;
            return;
        }
        const noteEl = checkbox.closest('.issue-item').querySelector('.issue-item__note');
        if (resolved) {
            noteEl.classList.add('issue-item__note--resolved');
            showToast('Issue resolved ✓');
        } else {
            noteEl.classList.remove('issue-item__note--resolved');
            showToast('Issue reopened');
        }
    } catch (err) {
        showToast('Network error', 'error');
        checkbox.checked = !resolved;
    }
}
