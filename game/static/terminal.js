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
    bindDefenseAlerts();
    autoResumePendingAction();
    bindActivePlayers();
    bindClassSelection();
    bindLevelUpSelection();
    scrollTerminalToLatest();
});

/**
 * Offline PvP results deserve attention, but must not permanently occupy the
 * play surface. Players may dismiss them explicitly; starting any new action
 * also dismisses the already-seen panel before its result is rendered.
 */
function bindDefenseAlerts() {
    const panel = document.querySelector('.defense-alerts');
    if (!panel) return;
    const dismiss = panel.querySelector('.defense-alert-dismiss');
    if (dismiss) dismiss.addEventListener('click', dismissDefenseAlerts);
}

function dismissDefenseAlerts() {
    const panel = document.querySelector('.defense-alerts');
    if (!panel) return;
    panel.classList.add('defense-alerts-dismissed');
    panel.setAttribute('aria-hidden', 'true');
    window.setTimeout(() => panel.remove(), 180);
}

function bindActivePlayers() {
    const toggle = document.getElementById('active-players-toggle');
    const dialog = document.getElementById('active-players-dialog');
    const close = document.getElementById('active-players-close');
    const list = document.getElementById('active-players-list');
    const count = document.getElementById('active-player-count');
    if (!toggle || !dialog || !list) return;

    const refresh = async () => {
        try {
            const response = await fetch(toggle.dataset.url, {cache: 'no-store'});
            if (!response.ok) throw new Error('request failed');
            const data = await response.json();
            count.textContent = data.count;
            list.replaceChildren();
            if (!data.players.length) {
                const empty = document.createElement('p');
                empty.className = 'active-players-empty';
                empty.textContent = 'No characters have acted in the last five minutes.';
                list.appendChild(empty);
                return;
            }
            data.players.forEach(player => {
                const row = document.createElement('div');
                row.className = 'active-player-row';
                const name = document.createElement('strong');
                name.textContent = player.character_name;
                const ago = document.createElement('span');
                const seconds = Math.max(0, Number(player.seconds_ago || 0));
                ago.textContent = seconds < 60 ? 'active moments ago' :
                    `active ${Math.floor(seconds / 60)} minute${Math.floor(seconds / 60) === 1 ? '' : 's'} ago`;
                row.append(name, ago);
                list.appendChild(row);
            });
        } catch (error) {
            list.textContent = 'Active-player information is temporarily unavailable.';
        }
    };

    toggle.addEventListener('click', async () => {
        await refresh();
        if (typeof dialog.showModal === 'function') dialog.showModal();
        else dialog.setAttribute('open', '');
    });
    if (close) close.addEventListener('click', () => dialog.close());
    dialog.addEventListener('click', event => {
        if (event.target === dialog) dialog.close();
    });
    setInterval(refresh, 60000);
}

/**
 * Open a pre-rendered daily transcript at its newest entry. Live actions and
 * feed polling already scroll after appending; this covers a normal reload.
 * Chronological order remains oldest-to-newest for readable combat playback.
 */
function scrollTerminalToLatest() {
    const terminal = document.getElementById('terminal');
    if (!terminal) return;
    const priorBehavior = terminal.style.scrollBehavior;
    terminal.style.scrollBehavior = 'auto';
    terminal.scrollTop = terminal.scrollHeight;
    // Run once more after the browser completes its first layout pass.
    requestAnimationFrame(() => {
        terminal.scrollTop = terminal.scrollHeight;
        terminal.style.scrollBehavior = priorBehavior;
    });
}

function bindLevelUpSelection() {
    const choices = document.querySelectorAll('.stat-choice');
    if (!choices.length) return;
    const update = () => choices.forEach(choice => {
        const radio = choice.querySelector('input[type="radio"]');
        choice.classList.toggle('selected', Boolean(radio && radio.checked));
        choice.setAttribute('aria-selected', String(Boolean(radio && radio.checked)));
    });
    choices.forEach(choice => choice.addEventListener('change', update));
    update();
}

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
            dismissDefenseAlerts();
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
            if (response.redirected) {
                window.location.assign(response.url);
                return;
            }
            const html = await response.text();
            if (!response.ok) {
                appendToTerminal(`<div class="term-line term-error">Action failed (${response.status}). Please try again or check the server log.</div>`);
                return;
            }
            const sourceFragment = form.closest('.fragment');
            if (sourceFragment) {
                sourceFragment.querySelectorAll('button').forEach(button => { button.disabled = true; });
                sourceFragment.classList.add('combat-history');
            }
            appendToTerminal(html);
            // Rebind any new terminal-action forms inside the fragment
            bindTerminalForms();
            autoResumePendingAction();
        });
    });
}

function autoResumePendingAction() {
    const form = document.querySelector('.pending-action-resume[data-auto-submit="true"]:not([data-auto-started])');
    if (!form) return;
    form.dataset.autoStarted = 'true';
    setTimeout(() => form.requestSubmit(), 250);
}

function appendToTerminal(html) {
    const terminal = document.getElementById('terminal');
    if (!terminal) return;
    const div = document.createElement('div');
    div.innerHTML = html;
    terminal.appendChild(div);
    terminal.scrollTop = terminal.scrollHeight;
    // The dashboard may itself be the scrolling surface. Bring the newly
    // requested action into view instead of leaving it below feed notices.
    requestAnimationFrame(() => {
        div.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    // Extract and apply any status updates embedded in the fragment
    updateStatusFromFragment(div);
    const extensionPrompt = div.querySelector('[data-extension-timeout]');
    if (extensionPrompt) {
        startExtensionTimer(Number(extensionPrompt.dataset.extensionTimeout),
            extensionPrompt.dataset.resolveUrl, extensionPrompt);
    }
    if (div.querySelector('[data-combat-resumed]')) cancelExtensionTimer();
}


// ─────────────────────────────────────────────────────────────────────────────
// 2. FEED POLLING
// Polls personal and global feed endpoints every 5 seconds.
// Appends new personal entries to #terminal; updates ticker with global entries.
// Timestamps injected by dashboard.html into initialTimestamp.
// ─────────────────────────────────────────────────────────────────────────────

let lastPersonalTs = (typeof initialTimestamp !== 'undefined') ? initialTimestamp : new Date().toISOString();
let lastGlobalTs   = new Date(0).toISOString();
const POLL_INTERVAL = 5000;

function pollFeeds() {
    // Personal feed → terminal
    if (window.personalFeedUrl) {
        fetch(`${window.personalFeedUrl}?since=${encodeURIComponent(lastPersonalTs)}`)
            .then(r => r.json())
            .then(entries => {
                entries.forEach(entry => {
                    if (document.getElementById('terminal')) appendFeedEntry(entry);
                    showLivePlayerAlert(entry);
                    lastPersonalTs = entry.occurred_at;
                });
            })
            .catch(() => {});  // silent fail — server may be momentarily busy
    }

    // Global feed → ticker
    if (window.globalFeedUrl) {
        fetch(`${window.globalFeedUrl}?since=${encodeURIComponent(lastGlobalTs)}`)
            .then(r => r.json())
            .then(entries => {
                const ticker = document.getElementById('ticker-content');
                if (!entries.length && ticker && ticker.textContent === 'Loading global feed...') {
                    ticker.textContent = 'No world announcements yet.';
                }
                entries.forEach(entry => {
                    appendToTicker(entry.flavor_text);
                    lastGlobalTs = entry.occurred_at;
                });
            })
            .catch(() => {});
    }
}

let livePlayerAlertTimer = null;
function showLivePlayerAlert(entry) {
    const alert = document.getElementById('live-player-alert');
    if (!alert) return;
    const againstYou = (entry.event_category || '').toUpperCase() === 'PVP_DEFENSE';
    document.getElementById('live-player-alert-label').textContent =
        againstYou ? 'ACTION AGAINST YOU' : 'LIVE CHARACTER UPDATE';
    document.getElementById('live-player-alert-message').textContent = entry.flavor_text;
    alert.classList.toggle('live-alert-danger', againstYou);
    alert.hidden = false;
    clearTimeout(livePlayerAlertTimer);
    livePlayerAlertTimer = setTimeout(() => { alert.hidden = true; }, 15000);
}

function appendFeedEntry(entry) {
    const terminal = document.getElementById('terminal');
    if (!terminal) return;
    const div = document.createElement('div');
    const category = (entry.event_category || 'system').toLowerCase();
    const scope = (entry.feed_scope || 'personal').toLowerCase();
    div.className = `term-line feed-entry term-${category}`;
    div.dataset.feedCategory = category;
    div.dataset.feedScope = scope;
    div.dataset.important = [
        'pvp_defense', 'combat', 'level_up', 'reward', 'contract', 'auction',
        'world_boss_reward', 'interruption_friendly', 'interruption_hostile'
    ].includes(category) ? 'true' : 'false';
    const ts = entry.occurred_at ? entry.occurred_at.substring(11, 16) : '';
    const categoryLabel = scope === 'global' ? 'WORLD' :
        category === 'pvp_defense' ? 'AGAINST YOU' :
        category === 'system' ? 'SYSTEM' :
        category === 'interruption_friendly' ? 'FRIENDLY INTERRUPTION' :
        category === 'interruption_hostile' ? 'HOSTILE INTERRUPTION' :
        category === 'random_event' ? 'YOU · EVENT' :
        category === 'combat' ? 'YOU · COMBAT' : 'YOU';
    const scopeClass = scope === 'global' ? 'feed-world' :
        category === 'pvp_defense' ? 'feed-against-you' :
        category.startsWith('interruption_') ? `feed-interruption ${category.endsWith('friendly') ? 'friendly' : 'hostile'}` :
        category === 'system' ? 'feed-system' : 'feed-you';
    div.innerHTML = `<span class="term-ts">[${ts}]</span>` +
        `<span class="feed-entry-scope"><span class="feed-scope ${scopeClass}">${categoryLabel}</span></span>` +
        `<span class="feed-message"></span>`;
    div.querySelector('.feed-message').textContent = entry.flavor_text;
    terminal.appendChild(div);
    applyFeedFilter();
    terminal.scrollTop = terminal.scrollHeight;
}

let activeFeedFilter = 'all';
function feedEntryMatches(entry, filter) {
    const category = entry.dataset.feedCategory || '';
    const scope = entry.dataset.feedScope || '';
    if (filter === 'all') return true;
    if (filter === 'important') return entry.dataset.important === 'true';
    if (filter === 'against') return category === 'pvp_defense';
    if (filter === 'system') return category === 'system' || scope === 'system';
    if (filter === 'combat') {
        return ['combat', 'combat_turn', 'pvp_defense', 'world_boss'].includes(category);
    }
    if (filter === 'rewards') {
        return ['level_up', 'contract', 'reward', 'world_boss_reward', 'item',
                'interruption_friendly'].includes(category);
    }
    if (filter === 'interruptions') return category.startsWith('interruption_');
    return true;
}

function applyFeedFilter() {
    document.querySelectorAll('#terminal .feed-entry').forEach(entry => {
        entry.hidden = !feedEntryMatches(entry, activeFeedFilter);
    });
    document.querySelectorAll('#terminal .feed-new-divider').forEach(divider => {
        divider.hidden = activeFeedFilter !== 'all';
    });
}

document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('.feed-filter').forEach(button => {
        button.addEventListener('click', () => {
            activeFeedFilter = button.dataset.feedFilter || 'all';
            document.querySelectorAll('.feed-filter').forEach(candidate => {
                const selected = candidate === button;
                candidate.classList.toggle('active', selected);
                candidate.setAttribute('aria-pressed', String(selected));
            });
            applyFeedFilter();
        });
    });
});

function appendToTicker(text) {
    const ticker = document.getElementById('ticker-content');
    if (!ticker) return;
    if (ticker.textContent === 'Loading global feed...') {
        ticker.textContent = '';
    }
    ticker.textContent += '  ·  ' + text;
}

// The world ticker is shared by every authenticated page; the personal feed
// is appended only when the dashboard terminal is present.
if (document.getElementById('terminal') || document.getElementById('ticker-content')) {
    pollFeeds();
    setInterval(pollFeeds, POLL_INTERVAL);
}

async function pollPlayerStatus() {
    if (!window.playerStatusUrl) return;
    try {
        const response = await fetch(window.playerStatusUrl, {cache: 'no-store'});
        if (!response.ok) return;
        const state = await response.json();
        setEl('status-hp', state.hp); setEl('status-maxhp', state.max_hp);
        setEl('status-ap', state.ap); setEl('status-maxap', state.max_ap);
        setEl('status-inventory-count', state.inventory_count);
        setEl('status-inventory-limit', state.inventory_limit);
        setEl('status-ac', state.ac);
        setEl('status-damage-min', state.damage_min);
        setEl('status-damage-max', state.damage_max);
        setEl('status-damage-types', (state.damage_types || []).join('/'));
        setEl('mobile-status-hp', state.hp); setEl('mobile-status-maxhp', state.max_hp);
        setEl('mobile-status-ap', state.ap); setEl('mobile-status-maxap', state.max_ap);
        setEl('status-level', state.level); setEl('status-xp', state.xp);
        setEl('status-xp-threshold', state.xp_threshold == null ? '' : `/${state.xp_threshold}`);
        setEl('status-xp-next', state.xp_next == null ? 'MAX' :
            state.xp_next <= 0 ? 'LEVEL UP' : `${state.xp_next} XP`);
        setEl('status-credits', state.credits);
        const block = document.getElementById('status-block');
        if (!block) return;
        let combat = block.querySelector('.status-combat');
        if (state.in_combat && !combat) {
            combat = document.createElement('div');
            combat.className = 'status-combat'; combat.textContent = '⚔ IN COMBAT';
            block.appendChild(combat);
        } else if (!state.in_combat && combat) combat.remove();
    } catch (error) {}
}

if (window.playerStatusUrl) {
    pollPlayerStatus();
    setInterval(pollPlayerStatus, POLL_INTERVAL);
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
    const xpThreshold = el.dataset.xpThreshold;
    const xpNext = el.dataset.xpNext;
    const cr    = el.dataset.credits;

    if (hp    !== undefined) setEl('status-hp',      hp);
    if (maxHp !== undefined) setEl('status-maxhp',   maxHp);
    if (ap    !== undefined) setEl('status-ap',       ap);
    if (maxAp !== undefined) setEl('status-maxap',    maxAp);
    if (hp    !== undefined) setEl('mobile-status-hp', hp);
    if (maxHp !== undefined) setEl('mobile-status-maxhp', maxHp);
    if (ap    !== undefined) setEl('mobile-status-ap', ap);
    if (maxAp !== undefined) setEl('mobile-status-maxap', maxAp);
    if (level !== undefined) setEl('status-level',    level);
    if (xp !== undefined) setEl('status-xp',          xp);
    if (xpThreshold !== undefined) setEl('status-xp-threshold', xpThreshold);
    if (xpNext !== undefined) setEl('status-xp-next', xpNext);
    if (cr    !== undefined) setEl('status-credits',  cr);

    if (el.dataset.combatEnded === 'true') {
        // The combat result is appended asynchronously, while the sidebar was
        // rendered before the final round. Clear the stale warning immediately
        // and fetch authoritative button/status markup without losing the
        // combat transcript currently visible in the terminal.
        const combatFlag = document.querySelector('#status-block .status-combat');
        if (combatFlag) combatFlag.remove();
        refreshSidebarState();
    }
}

async function refreshSidebarState() {
    try {
        const response = await fetch(window.location.href, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
            cache: 'no-store'
        });
        if (!response.ok) return;
        const page = new DOMParser().parseFromString(await response.text(), 'text/html');
        for (const id of ['status-block', 'action-buttons']) {
            const current = document.getElementById(id);
            const fresh = page.getElementById(id);
            if (current && fresh) current.innerHTML = fresh.innerHTML;
        }
        bindTerminalForms();
    } catch (error) {
        // Status numbers were already updated from the combat fragment. A
        // normal refresh remains a safe fallback if the sidebar request fails.
    }
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

function cancelExtensionTimer() {
    if (_extensionTimer) clearInterval(_extensionTimer);
    _extensionTimer = null;
}

function startExtensionTimer(seconds, resolveUrl, container) {
    // Clear any existing timer (safety)
    cancelExtensionTimer();

    let remaining = seconds;
    const timerEl = container ? container.querySelector('#extend-timer') : null;

    _extensionTimer = setInterval(() => {
        remaining--;
        if (timerEl) timerEl.textContent = remaining;

        if (remaining <= 0) {
            cancelExtensionTimer();
            if (container) container.querySelectorAll('button').forEach(button => { button.disabled = true; });
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

// Mobile uses the same authoritative sidebar in an off-canvas drawer. Keeping
// one navigation tree prevents mobile and desktop game actions from drifting.
(() => {
    const toggle = document.getElementById('mobile-menu-toggle');
    const sidebar = document.getElementById('left-col');
    const scrim = document.getElementById('mobile-nav-scrim');
    if (!toggle || !sidebar || !scrim) return;
    const setOpen = open => {
        document.body.classList.toggle('mobile-nav-open', open);
        toggle.setAttribute('aria-expanded', String(open));
        if (open) sidebar.querySelector('a,button')?.focus({preventScroll:true});
        else toggle.focus({preventScroll:true});
    };
    toggle.addEventListener('click', () => setOpen(!document.body.classList.contains('mobile-nav-open')));
    scrim.addEventListener('click', () => setOpen(false));
    sidebar.addEventListener('click', event => {
        if (window.matchMedia('(max-width: 720px)').matches &&
                event.target.closest('a,button[type="submit"]')) setOpen(false);
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape' && document.body.classList.contains('mobile-nav-open')) setOpen(false);
    });
})();
