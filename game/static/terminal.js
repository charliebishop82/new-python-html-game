// terminal.js
// Four responsibilities:
//   1. Terminal action form interception (POST → append fragment)
//   2. Feed polling every 5 seconds
//   3. Left column status block updates
//   4. Round-4 PvP extension countdown timer

'use strict';

// Persistent light/dark color theme.
document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('theme-toggle');
    if (!toggle) return;

    const updateToggle = () => {
        const isLight = document.documentElement.dataset.theme === 'light';
        toggle.textContent = isLight ? 'DARK MODE' : 'LIGHT MODE';
        toggle.setAttribute('aria-pressed', String(isLight));
    };

    updateToggle();
    toggle.addEventListener('click', () => {
        const nextTheme = document.documentElement.dataset.theme === 'light' ? 'dark' : 'light';
        document.documentElement.dataset.theme = nextTheme;
        try {
            localStorage.setItem('movie-multiverse-theme', nextTheme);
        } catch (error) {
            // The theme still changes for this page if storage is unavailable.
        }
        updateToggle();
    });
});

// Classic BBS and Cinematic are presentation layers over the same screens.
document.addEventListener('DOMContentLoaded', () => {
    const toggle = document.getElementById('interface-toggle');
    if (!toggle) return;
    const refreshLabel = () => {
        const cinematic = document.documentElement.dataset.interface === 'cinematic';
        toggle.textContent = cinematic ? 'CLASSIC BBS' : 'CINEMATIC UI';
        toggle.setAttribute('aria-pressed', cinematic ? 'true' : 'false');
    };
    refreshLabel();
    toggle.addEventListener('click', () => {
        const next = document.documentElement.dataset.interface === 'cinematic' ? 'classic' : 'cinematic';
        document.documentElement.dataset.interface = next;
        try { localStorage.setItem('movie-multiverse-interface', next); } catch (error) {}
        refreshLabel();
    });
});

// ─────────────────────────────────────────────────────────────────────────────
// 1. TERMINAL ACTION FORM INTERCEPTION
// All forms with class="terminal-action" are intercepted.
// Result HTML fragment is appended to #terminal instead of navigating away.
// ─────────────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    bindTerminalForms();
    bindClassSelection();
});

function bindClassSelection() {
    const options = document.querySelectorAll('.class-option');
    if (!options.length) return;

    const updateSelection = () => {
        options.forEach(option => {
            const radio = option.querySelector('input[type="radio"]');
            const selected = Boolean(radio && radio.checked);
            option.classList.toggle('selected', selected);
            option.setAttribute('aria-selected', String(selected));
        });
    };

    options.forEach(option => {
        const radio = option.querySelector('input[type="radio"]');
        if (radio) radio.addEventListener('change', updateSelection);
    });
    updateSelection();
}

function bindTerminalForms() {
    document.querySelectorAll('.terminal-action').forEach(form => {
        if (form.dataset.terminalBound === 'true') return;
        form.dataset.terminalBound = 'true';

        form.addEventListener('submit', async (e) => {
            e.preventDefault();
            const actionUrl = form.getAttribute('action');
            if (!actionUrl) {
                appendToTerminal('<div class="term-line term-error">This action is unavailable because its destination is missing.</div>');
                return;
            }

            const response = await fetch(actionUrl, {
                method: 'POST',
                body: new FormData(form),
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            });
            const html = await response.text();
            if (!response.ok) {
                appendToTerminal(`<div class="term-line term-error">Action failed (${response.status}). Please try again or check the server log.</div>`);
                return;
            }
            appendToTerminal(html);
            // Rebind any new terminal-action forms inside the fragment
            bindTerminalForms();
        });
    });
}

function appendToTerminal(html) {
    const terminal = document.getElementById('terminal');
    if (!terminal) return;
    const div = document.createElement('div');
    div.innerHTML = html;
    terminal.appendChild(div);
    terminal.scrollTop = terminal.scrollHeight;
    // Extract and apply any status updates embedded in the fragment
    updateStatusFromFragment(div);
}


// ─────────────────────────────────────────────────────────────────────────────
// 2. FEED POLLING
// Polls personal and global feed endpoints every 5 seconds.
// Appends new personal entries to #terminal; updates ticker with global entries.
// Timestamps injected by dashboard.html into initialTimestamp.
// ─────────────────────────────────────────────────────────────────────────────

let lastPersonalTs = (typeof initialTimestamp !== 'undefined') ? initialTimestamp : new Date(0).toISOString();
let lastGlobalTs   = new Date(0).toISOString();
const POLL_INTERVAL = 5000;

function pollFeeds() {
    // Personal feed → terminal
    if (typeof personalFeedUrl !== 'undefined') {
        fetch(`${personalFeedUrl}?since=${encodeURIComponent(lastPersonalTs)}`)
            .then(r => r.json())
            .then(entries => {
                entries.forEach(entry => {
                    appendFeedEntry(entry);
                    lastPersonalTs = entry.occurred_at;
                });
            })
            .catch(() => {});  // silent fail — server may be momentarily busy
    }

    // Global feed → ticker
    if (typeof globalFeedUrl !== 'undefined') {
        fetch(`${globalFeedUrl}?since=${encodeURIComponent(lastGlobalTs)}`)
            .then(r => r.json())
            .then(entries => {
                entries.forEach(entry => {
                    appendToTicker(entry.flavor_text);
                    lastGlobalTs = entry.occurred_at;
                });
            })
            .catch(() => {});
    }
}

function appendFeedEntry(entry) {
    const terminal = document.getElementById('terminal');
    if (!terminal) return;
    const div = document.createElement('div');
    const category = (entry.event_category || 'system').toLowerCase();
    div.className = `term-line feed-entry term-${category}`;
    const ts = entry.occurred_at ? entry.occurred_at.substring(11, 16) : '';
    const categoryLabel = category === 'system' ? 'SYSTEM' :
        category === 'random_event' ? 'YOU · EVENT' :
        category === 'combat' ? 'YOU · COMBAT' : 'YOU';
    const scopeClass = category === 'system' ? 'feed-system' : 'feed-you';
    div.innerHTML = `<span class="term-ts">[${ts}]</span>` +
        `<span class="feed-entry-scope"><span class="feed-scope ${scopeClass}">${categoryLabel}</span></span>` +
        `<span class="feed-message"></span>`;
    div.querySelector('.feed-message').textContent = entry.flavor_text;
    terminal.appendChild(div);
    terminal.scrollTop = terminal.scrollHeight;
}

function appendToTicker(text) {
    const ticker = document.getElementById('ticker-content');
    if (!ticker) return;
    if (ticker.textContent === 'Loading global feed...') {
        ticker.textContent = '';
    }
    ticker.textContent += '  ·  ' + text;
}

// Start polling if on dashboard
if (document.getElementById('terminal')) {
    pollFeeds();
    setInterval(pollFeeds, POLL_INTERVAL);
}


// ─────────────────────────────────────────────────────────────────────────────
// 3. LEFT COLUMN STATUS UPDATES
// Terminal fragments include data-hp, data-ap, data-credits attributes
// on a wrapper element. Read and push to the status block after every action.
// ─────────────────────────────────────────────────────────────────────────────

function updateStatusFromFragment(container) {
    const el = container.querySelector('[data-hp]');
    if (!el) return;

    const hp    = el.dataset.hp;
    const maxHp = el.dataset.maxHp;
    const ap    = el.dataset.ap;
    const maxAp = el.dataset.maxAp;
    const level = el.dataset.level;
    const xp    = el.dataset.xp;
    const xpNext = el.dataset.xpNext;
    const cr    = el.dataset.credits;

    if (hp    !== undefined) setEl('status-hp',      hp);
    if (maxHp !== undefined) setEl('status-maxhp',   maxHp);
    if (ap    !== undefined) setEl('status-ap',       ap);
    if (maxAp !== undefined) setEl('status-maxap',    maxAp);
    if (level !== undefined) setEl('status-level',    level);
    if (xp !== undefined) setEl('status-xp',          xp);
    if (xpNext !== undefined) setEl('status-xp-next', xpNext);
    if (cr    !== undefined) setEl('status-credits',  cr);
}

function setEl(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}


// ─────────────────────────────────────────────────────────────────────────────
// 4. ROUND-4 PVP EXTENSION COUNTDOWN TIMER
// Called by combat_extend.html fragment when it's injected into the terminal.
// Counts down COMBAT_EXTENSION_TIMEOUT seconds. On expiry, auto-POSTs to
// /combat/resolve so the score formula runs even if the player doesn't respond.
// ─────────────────────────────────────────────────────────────────────────────

let _extensionTimer = null;

function startExtensionTimer(seconds, resolveUrl) {
    // Clear any existing timer (safety)
    if (_extensionTimer) clearInterval(_extensionTimer);

    let remaining = seconds;
    const timerEl = document.getElementById('extend-timer');

    _extensionTimer = setInterval(() => {
        remaining--;
        if (timerEl) timerEl.textContent = remaining;

        if (remaining <= 0) {
            clearInterval(_extensionTimer);
            _extensionTimer = null;
            // Auto-resolve: POST to /combat/resolve
            fetch(resolveUrl, {
                method: 'POST',
                headers: { 'X-Requested-With': 'XMLHttpRequest' }
            })
            .then(r => r.text())
            .then(html => appendToTerminal(html))
            .catch(() => {});
        }
    }, 1000);
}

// Expose so combat fragments can call it after injection
window.startExtensionTimer = startExtensionTimer;
