/**
 * Fulfillment Hub — Client-side JavaScript
 * - Instant page transitions & hover prefetching (SPA feel)
 * - Fetch-based interactions: status advance, pick toggles, transfers, issues
 */

// =========================================================================
// Instant Navigation & Hover Prefetching
// =========================================================================

const pageCache = new Map();

function startProgress() {
    let bar = document.getElementById('route-progress-bar');
    if (!bar) {
        bar = document.createElement('div');
        bar.id = 'route-progress-bar';
        document.body.appendChild(bar);
    }
    bar.style.width = '35%';
    bar.style.opacity = '1';
    setTimeout(() => {
        if (bar.style.opacity === '1') bar.style.width = '75%';
    }, 120);
}

function endProgress() {
    const bar = document.getElementById('route-progress-bar');
    if (bar) {
        bar.style.width = '100%';
        setTimeout(() => {
            bar.style.opacity = '0';
            setTimeout(() => { bar.style.width = '0%'; }, 200);
        }, 150);
    }
}

async function fetchPage(url) {
    if (pageCache.has(url)) {
        return pageCache.get(url);
    }
    const res = await fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const html = await res.text();
    pageCache.set(url, html);
    setTimeout(() => pageCache.delete(url), 45000);
    return html;
}

function prefetch(url) {
    if (!url || pageCache.has(url) || url.startsWith('/api') || url.includes('#')) return;
    fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
        .then(res => res.ok ? res.text() : null)
        .then(html => {
            if (html) {
                pageCache.set(url, html);
                setTimeout(() => pageCache.delete(url), 45000);
            }
        })
        .catch(() => {});
}

async function navigateTo(url, push = true) {
    startProgress();
    try {
        const html = await fetchPage(url);
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, 'text/html');

        const newMain = doc.querySelector('.main-content');
        const currentMain = document.querySelector('.main-content');
        if (newMain && currentMain) {
            currentMain.className = newMain.className;
            currentMain.innerHTML = newMain.innerHTML;
        }

        if (doc.title) {
            document.title = doc.title;
        }

        const currentPath = new URL(url, window.location.origin).pathname;
        document.querySelectorAll('.top-bar__nav a').forEach(a => {
            if (a.getAttribute('href') === currentPath) {
                a.classList.add('active');
            } else {
                a.classList.remove('active');
            }
        });

        if (push) {
            window.history.pushState({ url }, '', url);
        }
        window.scrollTo(0, 0);
        endProgress();
    } catch (err) {
        endProgress();
        window.location.href = url;
    }
}

// Prefetch on hover and touch
document.addEventListener('mouseover', function(e) {
    const anchor = e.target.closest('a');
    if (anchor && anchor.href && anchor.origin === window.location.origin && !anchor.href.includes('/api/')) {
        prefetch(anchor.pathname + anchor.search);
    }
}, { passive: true });

document.addEventListener('touchstart', function(e) {
    const anchor = e.target.closest('a');
    if (anchor && anchor.href && anchor.origin === window.location.origin && !anchor.href.includes('/api/')) {
        prefetch(anchor.pathname + anchor.search);
    }
}, { passive: true });

// Intercept internal link clicks for instant swap
document.addEventListener('click', function(e) {
    const anchor = e.target.closest('a');
    if (!anchor || !anchor.href) return;
    if (anchor.origin !== window.location.origin) return;
    if (anchor.target && anchor.target !== '_self') return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    if (anchor.pathname.startsWith('/api/')) return;
    if (anchor.getAttribute('href').startsWith('#')) return;

    e.preventDefault();
    const dest = anchor.pathname + anchor.search;
    if (dest === window.location.pathname + window.location.search) return;
    navigateTo(dest, true);
});

// Handle Back/Forward browser history
window.addEventListener('popstate', function() {
    navigateTo(window.location.pathname + window.location.search, false);
});


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
        pageCache.clear();
        setTimeout(() => navigateTo(window.location.pathname, false), 400);
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

        const row = checkbox.closest('tr');
        if (row) {
            row.style.opacity = picked ? '0.6' : '1';
        }

        const advBtn = document.getElementById('advance-btn');
        const blockBanner = document.getElementById('block-banner');
        if (data.all_picked) {
            if (advBtn) advBtn.disabled = false;
            if (blockBanner) blockBanner.style.display = 'none';
        } else {
            if (advBtn) advBtn.disabled = true;
            if (blockBanner) blockBanner.style.display = 'flex';
        }

        pageCache.delete(window.location.pathname);
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
        pageCache.clear();
        setTimeout(() => navigateTo(window.location.pathname, false), 400);
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
        pageCache.clear();
        setTimeout(() => navigateTo(window.location.pathname, false), 400);
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
            pageCache.delete(window.location.pathname);
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
        pageCache.clear();
        setTimeout(() => navigateTo(window.location.pathname, false), 400);
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
        pageCache.clear();
    } catch (err) {
        showToast('Network error', 'error');
        checkbox.checked = !resolved;
    }
}


// =========================================================================
// Dashboard search (filters cards by order number or customer name)
// =========================================================================

document.addEventListener('input', function(e) {
    if (e.target.id !== 'order-search') return;

    const query = e.target.value.trim().toLowerCase();
    const board = document.getElementById('order-board');
    const noResults = document.getElementById('no-results');
    if (!board) return;

    const cards = board.querySelectorAll('.order-card');
    let anyVisible = false;

    if (!query) {
        // Reset: remove search classes, restore default visibility
        cards.forEach(card => {
            card.classList.remove('order-card--search-match', 'order-card--search-miss');
        });
        if (noResults) noResults.style.display = 'none';
        board.style.display = '';
        return;
    }

    cards.forEach(card => {
        const orderNum = (card.dataset.orderNumber || '').toLowerCase();
        const customer = (card.dataset.customer || '').toLowerCase();
        const matches = orderNum.includes(query) || customer.includes(query);

        if (matches) {
            card.classList.add('order-card--search-match');
            card.classList.remove('order-card--search-miss');
            anyVisible = true;
        } else {
            card.classList.add('order-card--search-miss');
            card.classList.remove('order-card--search-match');
        }
    });

    if (noResults) {
        noResults.style.display = anyVisible ? 'none' : 'block';
        board.style.display = anyVisible ? '' : 'none';
    }
});

