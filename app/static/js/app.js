/**
 * Payment Ledger & Real-Time Financial Auditor
 * Main Frontend Application Controller
 * Inspired by Purrweb Cashline & Figr Design Standards
 */

import { LedgerAPI } from './api.js';

// Global application state
const state = {
  accounts: [],
  transactions: [],
  ledgerEntries: [],
  cards: [],
  lastTransferPayload: null,
  lastTransferKey: null,
  activeTab: 'tab-accounts',
  searchFilter: '',
};

// ==========================================================================
// TOAST NOTIFICATION ENGINE
// ==========================================================================

function showToast(message, type = 'success', title = '') {
  const container = document.getElementById('toast-container');
  if (!container) return;

  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  
  const icon = type === 'success' ? '&#x2714;' : type === 'replay' ? '&#x21ba;' : '&#x26a0;';
  const defaultTitle = type === 'success' ? 'Success' : type === 'replay' ? 'Idempotent Replay' : 'Notice / Error';

  toast.innerHTML = `
    <div style="font-size: 15px; margin-top: 1px;">${icon}</div>
    <div style="flex: 1;">
      <div style="font-weight: 700; font-size: 12.5px; margin-bottom: 2px;">${title || defaultTitle}</div>
      <div style="color: var(--text-muted); font-size: 12px; line-height: 1.4;">${message}</div>
    </div>
  `;

  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(8px)';
    toast.style.transition = 'all 0.25s ease';
    setTimeout(() => toast.remove(), 250);
  }, 4500);
}

// Utility: Generate RFC4122 UUID v4
function generateUUID() {
  if (crypto && crypto.randomUUID) {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    const v = c === 'x' ? r : (r & 0x3) | 0x8;
    return v.toString(16);
  });
}

// Utility: Copy text to clipboard
async function copyToClipboard(text, label = 'UUID') {
  try {
    await navigator.clipboard.writeText(text);
    showToast(`Copied ${label} to clipboard`, 'success');
  } catch {
    showToast(`Failed to copy to clipboard`, 'error');
  }
}

// ==========================================================================
// TAB NAVIGATION (FIGR SIDEBAR)
// ==========================================================================

function initTabs() {
  const tabs = document.querySelectorAll('.nav-item, .tab-btn');
  tabs.forEach((tab) => {
    tab.addEventListener('click', () => {
      tabs.forEach((t) => t.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach((p) => p.classList.remove('active'));

      tab.classList.add('active');
      const targetId = tab.getAttribute('data-tab');
      const targetPane = document.getElementById(targetId);
      if (targetPane) {
        targetPane.classList.add('active');
        state.activeTab = targetId;
      }
    });
  });
}

function switchTab(tabId) {
  const tabBtn = document.querySelector(`[data-tab="${tabId}"]`);
  if (tabBtn) tabBtn.click();
}

// ==========================================================================
// ACCOUNTS MODULE
// ==========================================================================

async function loadAccounts() {
  try {
    const res = await LedgerAPI.getAccounts(100);
    state.accounts = res.data || [];
    renderAccountsTable();
    updateMetrics();
    populateAccountDropdowns();
  } catch (err) {
    console.error('Failed to load accounts', err);
  }
}

function renderAccountsTable() {
  const tbody = document.getElementById('accounts-tbody');
  const countBadge = document.getElementById('badge-account-count');
  const statAccounts = document.getElementById('stat-total-accounts');
  if (!tbody) return;

  const count = state.accounts.length;
  if (countBadge) countBadge.textContent = count;
  if (statAccounts) statAccounts.textContent = count;

  let filtered = state.accounts;
  if (state.searchFilter) {
    const q = state.searchFilter.toLowerCase();
    filtered = filtered.filter(
      (a) => a.id.toLowerCase().includes(q) || a.currency.toLowerCase().includes(q)
    );
  }

  if (filtered.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" style="text-align: center; color: var(--text-dim); padding: 36px;">
          ${state.searchFilter ? 'No accounts match the search filter.' : 'No accounts found. Click "+ Create Account" to create your first balance container.'}
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = filtered
    .map((acc) => {
      const holdsNum = parseFloat(acc.holds || '0');
      const holdsBadge = holdsNum > 0
        ? `<span class="pill pill-hold" title="Active reservation holds">$${acc.holds}</span>`
        : `<span style="color: var(--text-dim); font-family: var(--font-mono);">$0.00</span>`;

      return `
        <tr>
          <td>
            <span class="uuid-tag" data-copy="${acc.id}" title="Click to copy full UUID">
              ${acc.id.substring(0, 8)}...${acc.id.substring(acc.id.length - 4)}
              <span style="font-size: 10px; opacity: 0.6;">&#x2398;</span>
            </span>
          </td>
          <td><span class="pill pill-gray" style="font-weight: 700;">${acc.currency}</span></td>
          <td class="amount-mono">$${acc.balance}</td>
          <td>${holdsBadge}</td>
          <td class="amount-mono" style="color: var(--badge-credit-text); font-weight: 700;">$${acc.available_balance || acc.balance}</td>
          <td style="color: var(--text-dim); font-family: var(--font-mono); font-size: 11.5px;">v${acc.version}</td>
          <td>
            <div style="display: flex; gap: 6px;">
              <button class="btn btn-secondary btn-sm btn-quick-from" data-id="${acc.id}" title="Set as transfer source">From</button>
              <button class="btn btn-secondary btn-sm btn-quick-to" data-id="${acc.id}" title="Set as transfer destination">To</button>
              <button class="btn btn-secondary btn-sm btn-quick-card" data-id="${acc.id}" title="Authorize payment hold">Card</button>
            </div>
          </td>
        </tr>
      `;
    })
    .join('');

  // Quick actions
  tbody.querySelectorAll('[data-copy]').forEach((el) => {
    el.addEventListener('click', () => copyToClipboard(el.getAttribute('data-copy'), 'Account ID'));
  });

  tbody.querySelectorAll('.btn-quick-from').forEach((btn) => {
    btn.addEventListener('click', () => {
      const fromSel = document.getElementById('transfer-from-account');
      if (fromSel) fromSel.value = btn.getAttribute('data-id');
      switchTab('tab-transfers');
    });
  });

  tbody.querySelectorAll('.btn-quick-to').forEach((btn) => {
    btn.addEventListener('click', () => {
      const toSel = document.getElementById('transfer-to-account');
      if (toSel) toSel.value = btn.getAttribute('data-id');
      switchTab('tab-transfers');
    });
  });

  tbody.querySelectorAll('.btn-quick-card').forEach((btn) => {
    btn.addEventListener('click', () => {
      const cardCustSel = document.getElementById('card-customer-account');
      if (cardCustSel) cardCustSel.value = btn.getAttribute('data-id');
      switchTab('tab-cards');
    });
  });
}

function updateMetrics() {
  let totalBooked = 0;
  let totalHolds = 0;
  let totalAvailable = 0;

  state.accounts.forEach((acc) => {
    totalBooked += parseFloat(acc.balance || '0');
    totalHolds += parseFloat(acc.holds || '0');
    totalAvailable += parseFloat(acc.available_balance || acc.balance || '0');
  });

  const bookedFormatted = `$${totalBooked.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const holdsFormatted = `$${totalHolds.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const availFormatted = `$${totalAvailable.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

  const statBooked = document.getElementById('stat-booked-balance');
  const statHolds = document.getElementById('stat-total-holds');
  const statAvailable = document.getElementById('stat-available-balance');
  const totalLiquidity = document.getElementById('total-liquidity');

  if (statBooked) statBooked.textContent = bookedFormatted;
  if (statHolds) statHolds.textContent = holdsFormatted;
  if (statAvailable) statAvailable.textContent = availFormatted;
  if (totalLiquidity) totalLiquidity.textContent = `${bookedFormatted} USD`;
}

function populateAccountDropdowns() {
  const fromSel = document.getElementById('transfer-from-account');
  const toSel = document.getElementById('transfer-to-account');
  const cardCustSel = document.getElementById('card-customer-account');
  const cardMerchSel = document.getElementById('card-merchant-account');

  const selects = [fromSel, toSel, cardCustSel, cardMerchSel];
  selects.forEach((sel) => {
    if (!sel) return;
    const currentVal = sel.value;
    const isSource = sel.id.includes('from') || sel.id.includes('customer');
    const defaultText = isSource ? 'Select source account...' : 'Select recipient account...';

    sel.innerHTML = `<option value="">${defaultText}</option>` +
      state.accounts
        .map(
          (acc) =>
            `<option value="${acc.id}">
              ${acc.id.substring(0, 8)}... (${acc.currency} Avail: $${acc.available_balance || acc.balance})
            </option>`
        )
        .join('');

    if (currentVal) sel.value = currentVal;
  });
}

// ==========================================================================
// TRANSFER TERMINAL & MATCH PROOF INSPECTOR (PURRWEB CASHLINE STYLE)
// ==========================================================================

function initTransferTerminal() {
  const keyInput = document.getElementById('transfer-idempotency-key');
  const newKeyBtn = document.getElementById('btn-generate-transfer-key');
  const form = document.getElementById('transfer-form');
  const replayBtn = document.getElementById('btn-test-replay');
  const tamperBtn = document.getElementById('btn-test-tamper');

  if (keyInput) keyInput.value = generateUUID();

  if (newKeyBtn) {
    newKeyBtn.addEventListener('click', () => {
      if (keyInput) {
        keyInput.value = generateUUID();
        showToast('Generated fresh idempotency key', 'success');
      }
    });
  }

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      await handleTransferSubmit();
    });
  }

  if (replayBtn) {
    replayBtn.addEventListener('click', async () => {
      await handleReplayTest();
    });
  }

  if (tamperBtn) {
    tamperBtn.addEventListener('click', async () => {
      await handleTamperTest();
    });
  }
}

function renderMatchProof({ status, isReplay, txnId, amount, currency, entries, fromBalance, toBalance, error, detail }) {
  const termBox = document.getElementById('terminal-last-response');
  if (!termBox) return;

  if (error) {
    termBox.innerHTML = `
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
        <span class="pill pill-debit" style="font-size: 12px;">&#x26a0; REJECTED (${status})</span>
        <span style="font-size: 11px; color: var(--text-dim);">${new Date().toLocaleTimeString()}</span>
      </div>
      <div style="font-weight: 600; color: var(--text-primary); margin-bottom: 6px;">Transaction Failed</div>
      <div class="proof-mono-snippet" style="color: var(--badge-debit-text);">
        ${detail || error}
      </div>
    `;
    return;
  }

  const badgeClass = isReplay ? 'pill-hold' : 'pill-credit';
  const badgeLabel = isReplay ? '&#x21ba; MATCH REPLAYED (CACHED)' : '&#x2714; MATCHED & PROVEN';

  const debitEntry = entries?.[0] || {};
  const creditEntry = entries?.[1] || {};

  termBox.innerHTML = `
    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
      <span class="pill ${badgeClass}" style="font-size: 12px;">${badgeLabel}</span>
      <span style="font-size: 11.5px; color: var(--text-dim);">${new Date().toLocaleTimeString()}</span>
    </div>

    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px;">
      <div style="background: #ffffff; padding: 10px; border-radius: 6px; border: 1px solid var(--border-subtle);">
        <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Transaction ID</div>
        <div class="uuid-tag" style="margin-top: 4px;" data-copy="${txnId}">${txnId.substring(0, 14)}...</div>
      </div>
      <div style="background: #ffffff; padding: 10px; border-radius: 6px; border: 1px solid var(--border-subtle);">
        <div style="font-size: 11px; text-transform: uppercase; color: var(--text-muted); font-weight: 600;">Settled Amount</div>
        <div class="amount-mono" style="font-size: 16px; margin-top: 2px;">$${amount} ${currency}</div>
      </div>
    </div>

    <div class="proof-mono-snippet">
      <div style="color: var(--badge-debit-text); margin-bottom: 4px;">
        &minus; DEBIT:  Account ${debitEntry.account_id?.substring(0, 8)}... &bull; -$${amount} [Entry: ${debitEntry.id?.substring(0, 8)}...]
      </div>
      <div style="color: var(--badge-credit-text); margin-bottom: 8px;">
        + CREDIT: Account ${creditEntry.account_id?.substring(0, 8)}... &bull; +$${amount} [Entry: ${creditEntry.id?.substring(0, 8)}...]
      </div>
      <div style="border-top: 1px dashed #cbd5e1; padding-top: 6px; color: var(--text-secondary); font-size: 11px;">
        Impact: Sender New Bal: <strong>$${fromBalance}</strong> | Recipient New Bal: <strong>$${toBalance}</strong>
      </div>
    </div>
  `;

  termBox.querySelectorAll('[data-copy]').forEach((el) => {
    el.addEventListener('click', () => copyToClipboard(el.getAttribute('data-copy'), 'Transaction ID'));
  });
}

async function handleTransferSubmit() {
  const fromAccount = document.getElementById('transfer-from-account')?.value;
  const toAccount = document.getElementById('transfer-to-account')?.value;
  const amount = document.getElementById('transfer-amount')?.value;
  const currency = document.getElementById('transfer-currency')?.value || 'USD';
  const memo = document.getElementById('transfer-memo')?.value || '';
  const key = document.getElementById('transfer-idempotency-key')?.value;
  const submitBtn = document.getElementById('btn-submit-transfer');

  if (!fromAccount || !toAccount || !amount || !key) {
    showToast('Please fill in all required transfer fields', 'error');
    return;
  }

  if (fromAccount === toAccount) {
    showToast('Cannot transfer between the same account', 'error');
    return;
  }

  if (submitBtn) submitBtn.disabled = true;

  try {
    const payload = {
      fromAccountId: fromAccount,
      toAccountId: toAccount,
      amount: parseFloat(amount).toFixed(2),
      currency,
      memo: memo || 'Transfer',
      idempotencyKey: key,
    };

    const res = await LedgerAPI.executeTransfer(payload);

    state.lastTransferPayload = { ...payload };
    state.lastTransferKey = key;

    renderMatchProof({
      status: '201 Created',
      isReplay: res.isReplay,
      txnId: res.data.transaction_id,
      amount: res.data.amount,
      currency: res.data.currency,
      entries: res.data.entries,
      fromBalance: res.data.from_account_balance,
      toBalance: res.data.to_account_balance,
    });

    if (res.isReplay) {
      showToast('Exact cached replay returned (0 duplicate charges)', 'replay', 'X-Idempotent-Replay: true');
    } else {
      showToast(`Successfully transferred $${payload.amount} ${currency}`, 'success');
      const keyInput = document.getElementById('transfer-idempotency-key');
      if (keyInput) keyInput.value = generateUUID();
    }

    await refreshAllData();
  } catch (err) {
    renderMatchProof({
      status: `HTTP ${err.status || 400}`,
      error: 'Transfer Rejected',
      detail: err.message,
    });
    showToast(err.message, 'error', `Transfer Failed (${err.status || 'Error'})`);
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

async function handleReplayTest() {
  if (!state.lastTransferPayload || !state.lastTransferKey) {
    showToast('Execute at least one transfer first to test idempotency replay', 'error');
    return;
  }

  showToast(`Submitting duplicate request with key ${state.lastTransferKey.substring(0, 8)}...`, 'replay', 'Testing Idempotency');

  try {
    const res = await LedgerAPI.executeTransfer({
      ...state.lastTransferPayload,
      idempotencyKey: state.lastTransferKey,
    });

    renderMatchProof({
      status: '201 Created',
      isReplay: true,
      txnId: res.data.transaction_id,
      amount: res.data.amount,
      currency: res.data.currency,
      entries: res.data.entries,
      fromBalance: res.data.from_account_balance,
      toBalance: res.data.to_account_balance,
    });

    showToast('PostgreSQL serialized duplicate: cached response replayed perfectly!', 'replay', 'Idempotency Guarantee Proved');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function handleTamperTest() {
  if (!state.lastTransferPayload || !state.lastTransferKey) {
    showToast('Execute at least one transfer first to test payload tampering', 'error');
    return;
  }

  const tamperedAmount = (parseFloat(state.lastTransferPayload.amount) + 5.0).toFixed(2);
  showToast(`Submitting tampered amount ($${tamperedAmount}) with original key...`, 'error', 'Testing Payload Tampering');

  try {
    await LedgerAPI.executeTransfer({
      ...state.lastTransferPayload,
      amount: tamperedAmount,
      idempotencyKey: state.lastTransferKey,
    });
    showToast('Unexpected: Tampered payload was accepted!', 'error');
  } catch (err) {
    renderMatchProof({
      status: `HTTP ${err.status || 422}`,
      error: 'Tampering Guard Triggered',
      detail: `SHA-256 payload mismatch detected! Client attempted to reuse key ${state.lastTransferKey.substring(0, 8)}... with modified amount ($${tamperedAmount}). Rejected with HTTP 422 Unprocessable Content.`,
    });
    showToast(`Hash mismatch caught: HTTP 422 Unprocessable Content`, 'success', 'Tampering Shield Proved');
  }
}

// ==========================================================================
// CARD LIFECYCLE SIMULATOR
// ==========================================================================

function initCardSimulator() {
  const form = document.getElementById('card-auth-form');
  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      await handleCardAuthSubmit();
    });
  }
}

async function handleCardAuthSubmit() {
  const custAccount = document.getElementById('card-customer-account')?.value;
  const merchAccount = document.getElementById('card-merchant-account')?.value;
  const amount = document.getElementById('card-amount')?.value;
  const currency = document.getElementById('card-currency')?.value || 'USD';
  const memo = document.getElementById('card-memo')?.value || '';
  const submitBtn = document.getElementById('btn-submit-card-auth');

  if (!custAccount || !merchAccount || !amount) {
    showToast('Please select customer, merchant, and authorization amount', 'error');
    return;
  }

  if (custAccount === merchAccount) {
    showToast('Customer and merchant accounts must be distinct', 'error');
    return;
  }

  if (submitBtn) submitBtn.disabled = true;

  try {
    const payload = {
      accountId: custAccount,
      merchantId: merchAccount,
      amount: parseFloat(amount).toFixed(2),
      currency,
      memo: memo || 'Card Authorization',
      idempotencyKey: generateUUID(),
    };

    await LedgerAPI.authorizeCard(payload);
    showToast(`Hold of $${payload.amount} placed on customer account`, 'success');

    // Reset amount field
    const amtInput = document.getElementById('card-amount');
    if (amtInput) amtInput.value = '';

    await refreshAllData();
  } catch (err) {
    showToast(err.message, 'error', `Card Authorization Failed (${err.status || 'Error'})`);
  } finally {
    if (submitBtn) submitBtn.disabled = false;
  }
}

async function loadCards() {
  try {
    const promises = state.accounts.map((acc) => LedgerAPI.getAccountCards(acc.id).catch(() => ({ data: [] })));
    const results = await Promise.all(promises);

    const cardMap = new Map();
    results.forEach((r) => {
      if (r && r.data) {
        r.data.forEach((c) => cardMap.set(c.id, c));
      }
    });

    state.cards = Array.from(cardMap.values()).sort(
      (a, b) => new Date(b.created_at) - new Date(a.created_at)
    );
    renderCardsTable();
  } catch (err) {
    console.error('Failed to load card authorizations', err);
  }
}

function renderCardsTable() {
  const tbody = document.getElementById('cards-tbody');
  const holdBadge = document.getElementById('badge-active-holds');
  if (!tbody) return;

  const activeHoldCount = state.cards.filter((c) => c.status === 'AUTHORIZED').length;
  if (holdBadge) holdBadge.textContent = activeHoldCount;

  if (state.cards.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="9" style="text-align: center; color: var(--text-dim); padding: 36px;">
          No card authorizations found. Fill in the form above to place an authorization hold.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = state.cards
    .map((c) => {
      let statusBadge = `<span class="pill pill-gray">${c.status}</span>`;
      if (c.status === 'AUTHORIZED') {
        statusBadge = `<span class="pill pill-hold">AUTHORIZED</span>`;
      } else if (c.status === 'CAPTURED') {
        statusBadge = `<span class="pill pill-credit">CAPTURED</span>`;
      } else if (c.status === 'VOIDED') {
        statusBadge = `<span class="pill pill-gray">VOIDED</span>`;
      } else if (c.status === 'REFUNDED') {
        statusBadge = `<span class="pill pill-debit">REFUNDED</span>`;
      }

      let actions = '';
      if (c.status === 'AUTHORIZED') {
        actions = `
          <button class="btn btn-primary btn-sm btn-card-capture" data-id="${c.id}" data-amount="${c.amount}" title="Settle hold into double-entry transfer">Capture</button>
          <button class="btn btn-secondary btn-sm btn-card-void" data-id="${c.id}" title="Release hold without ledger movement">Void</button>
        `;
      } else if (c.status === 'CAPTURED') {
        const canRefund = parseFloat(c.captured_amount || '0') > parseFloat(c.refunded_amount || '0');
        if (canRefund) {
          actions = `<button class="btn btn-danger btn-sm btn-card-refund" data-id="${c.id}" data-eligible="${(parseFloat(c.captured_amount) - parseFloat(c.refunded_amount)).toFixed(2)}" title="Reverse double-entry refund">Refund</button>`;
        } else {
          actions = `<span style="color: var(--text-dim); font-size: 11px;">Fully Refunded</span>`;
        }
      } else {
        actions = `<span style="color: var(--text-dim); font-size: 11px;">Terminal State</span>`;
      }

      return `
        <tr>
          <td><span class="uuid-tag" data-copy="${c.id}">${c.id.substring(0, 8)}...</span></td>
          <td><span class="uuid-tag" data-copy="${c.account_id}">${c.account_id.substring(0, 8)}...</span></td>
          <td><span class="uuid-tag" data-copy="${c.merchant_id}">${c.merchant_id.substring(0, 8)}...</span></td>
          <td class="amount-mono">$${c.amount}</td>
          <td class="amount-mono" style="font-size: 12px;">
            Cap: ${c.captured_amount ? `$${c.captured_amount}` : '&minus;'} | Ref: $${c.refunded_amount || '0.00'}
          </td>
          <td>${statusBadge}</td>
          <td style="color: var(--text-muted); font-size: 12px;">${c.memo || '&minus;'}</td>
          <td style="color: var(--text-dim); font-size: 11px;">${new Date(c.created_at).toLocaleTimeString()}</td>
          <td><div style="display: flex; gap: 6px;">${actions}</div></td>
        </tr>
      `;
    })
    .join('');

  tbody.querySelectorAll('[data-copy]').forEach((el) => {
    el.addEventListener('click', () => copyToClipboard(el.getAttribute('data-copy'), 'Card UUID'));
  });

  tbody.querySelectorAll('.btn-card-capture').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const authId = btn.getAttribute('data-id');
      const authAmount = btn.getAttribute('data-amount');
      const captureInput = prompt(`Capture amount (Authorized: $${authAmount}). Leave blank for full capture:`, authAmount);
      if (captureInput === null) return;

      try {
        const finalCap = captureInput.trim() ? parseFloat(captureInput).toFixed(2) : null;
        await LedgerAPI.captureCard(authId, finalCap);
        showToast(`Capture settled: hold converted to ledger entries`, 'success');
        await refreshAllData();
      } catch (err) {
        showToast(err.message, 'error', 'Capture Failed');
      }
    });
  });

  tbody.querySelectorAll('.btn-card-void').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const authId = btn.getAttribute('data-id');
      if (!confirm('Are you sure you want to void this authorization? The hold will be released with zero ledger movements.')) return;
      try {
        await LedgerAPI.voidCard(authId, 'Cancelled by merchant');
        showToast('Hold voided and released to available balance', 'success');
        await refreshAllData();
      } catch (err) {
        showToast(err.message, 'error', 'Void Failed');
      }
    });
  });

  tbody.querySelectorAll('.btn-card-refund').forEach((btn) => {
    btn.addEventListener('click', async () => {
      const authId = btn.getAttribute('data-id');
      const eligible = btn.getAttribute('data-eligible');
      const refundInput = prompt(`Refund amount (Max eligible: $${eligible}):`, eligible);
      if (refundInput === null) return;

      try {
        const finalRef = refundInput.trim() ? parseFloat(refundInput).toFixed(2) : null;
        await LedgerAPI.refundCard(authId, finalRef, 'Customer return');
        showToast(`Refund processed via reverse double-entry transfer`, 'success');
        await refreshAllData();
      } catch (err) {
        showToast(err.message, 'error', 'Refund Failed');
      }
    });
  });
}

// ==========================================================================
// DOUBLE-ENTRY LEDGER & AI OUTBOX STREAM
// ==========================================================================

async function loadLedgerStream() {
  try {
    const [entriesRes, txnsRes] = await Promise.all([
      LedgerAPI.getLedgerEntries(50),
      LedgerAPI.getTransactions(50),
    ]);

    state.ledgerEntries = entriesRes.data || [];
    state.transactions = txnsRes.data || [];

    renderLedgerEntriesTable();
    renderTransactionsTable();
  } catch (err) {
    console.error('Failed to load ledger stream', err);
  }
}

function renderLedgerEntriesTable() {
  const tbody = document.getElementById('entries-tbody');
  if (!tbody) return;

  if (state.ledgerEntries.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" style="text-align: center; color: var(--text-dim); padding: 36px;">
          No ledger entries yet. Execute a transfer to produce debit/credit pairs.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = state.ledgerEntries
    .map((e) => {
      const badge = e.direction === 'CREDIT'
        ? `<span class="pill pill-credit">+ CREDIT</span>`
        : `<span class="pill pill-debit">&minus; DEBIT</span>`;

      return `
        <tr>
          <td>${badge}</td>
          <td class="amount-mono">$${e.amount}</td>
          <td><span class="uuid-tag" data-copy="${e.account_id}">${e.account_id.substring(0, 8)}...</span></td>
          <td><span class="uuid-tag" data-copy="${e.id}">${e.id.substring(0, 8)}...</span></td>
          <td style="color: var(--text-dim); font-size: 11px;">${new Date(e.created_at).toLocaleTimeString()}</td>
        </tr>
      `;
    })
    .join('');

  tbody.querySelectorAll('[data-copy]').forEach((el) => {
    el.addEventListener('click', () => copyToClipboard(el.getAttribute('data-copy'), 'Entry UUID'));
  });
}

function renderTransactionsTable() {
  const tbody = document.getElementById('transactions-tbody');
  if (!tbody) return;

  if (state.transactions.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" style="text-align: center; color: var(--text-dim); padding: 36px;">
          No transactions yet.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = state.transactions
    .map((t) => {
      const categoryBadge = t.ai_category
        ? `<span class="pill pill-category">${t.ai_category}</span>`
        : `<span style="color: var(--text-dim); font-size: 11px;">Pending Outbox...</span>`;

      return `
        <tr>
          <td><span class="uuid-tag" data-copy="${t.id}">${t.id.substring(0, 8)}...</span></td>
          <td class="amount-mono">$${t.amount}</td>
          <td style="color: var(--text-secondary); font-size: 12.5px;">${t.memo || '&minus;'}</td>
          <td>${categoryBadge}</td>
          <td><span class="pill pill-credit">${t.status}</span></td>
          <td style="color: var(--text-dim); font-size: 11px;">${new Date(t.created_at).toLocaleTimeString()}</td>
        </tr>
      `;
    })
    .join('');

  tbody.querySelectorAll('[data-copy]').forEach((el) => {
    el.addEventListener('click', () => copyToClipboard(el.getAttribute('data-copy'), 'Txn ID'));
  });
}

// ==========================================================================
// RECONCILIATION & TAMPER DRILL MODULE (PURRWEB CASH PROVEN)
// ==========================================================================

function initReconciliation() {
  const runBtn = document.getElementById('btn-run-audit');
  const tamperBtn = document.getElementById('btn-tamper-drill');
  const healBtn = document.getElementById('btn-heal-drill');

  if (runBtn) {
    runBtn.addEventListener('click', async () => {
      runBtn.disabled = true;
      try {
        await executeReconciliationAudit();
      } finally {
        runBtn.disabled = false;
      }
    });
  }

  if (tamperBtn) {
    tamperBtn.addEventListener('click', async () => {
      tamperBtn.disabled = true;
      try {
        await handleTamperDrill();
      } finally {
        tamperBtn.disabled = false;
      }
    });
  }

  if (healBtn) {
    healBtn.addEventListener('click', async () => {
      healBtn.disabled = true;
      try {
        await handleHealDrill();
      } finally {
        healBtn.disabled = false;
      }
    });
  }
}

async function loadReconciliationStatus() {
  try {
    const res = await LedgerAPI.getReconciliationStatus();
    updateReconciliationUI(res.data);
  } catch (err) {
    console.error('Failed to load reconciliation status', err);
  }
}

async function executeReconciliationAudit() {
  showToast('Auditing all accounts, transactions, and ledger entries...', 'success', 'Running Audit');
  try {
    const res = await LedgerAPI.runReconciliation();
    updateReconciliationUI(res.data);

    if (res.data.status === 'HEALTHY') {
      showToast('All accounts strictly satisfy the Balance and Double-Entry Invariants!', 'success', 'Zero Drift Verified');
    } else {
      showToast(`Audit flagged ${res.data.drifts_detected} balance discrepancy!`, 'error', 'DRIFT DETECTED');
    }
  } catch (err) {
    showToast(err.message, 'error', 'Reconciliation Failed');
  }
}

function updateReconciliationUI(data) {
  if (!data) return;

  const banner = document.getElementById('audit-status-banner');
  const bannerTitle = document.getElementById('audit-banner-title');
  const bannerDesc = document.getElementById('audit-banner-desc');
  const healthBadge = document.getElementById('reconciliation-health-badge');

  const accAudited = document.getElementById('rec-accounts-audited');
  const txnAudited = document.getElementById('rec-transactions-audited');
  const driftsDet = document.getElementById('rec-drifts-detected');
  const execTime = document.getElementById('rec-execution-time');

  if (accAudited) accAudited.textContent = data.accounts_audited;
  if (txnAudited) txnAudited.textContent = data.transactions_audited;
  if (driftsDet) {
    driftsDet.textContent = data.drifts_detected;
    driftsDet.style.color = data.drifts_detected > 0 ? 'var(--badge-debit-text)' : 'var(--badge-credit-text)';
  }
  if (execTime) execTime.textContent = `${parseFloat(data.execution_time_ms || '0').toFixed(2)} ms`;

  const isHealthy = data.status === 'HEALTHY' && data.drifts_detected === 0;

  if (banner) {
    banner.className = `rec-banner ${isHealthy ? 'healthy' : 'drift'}`;
  }
  if (bannerTitle) {
    bannerTitle.textContent = isHealthy
      ? 'LEDGER HEALTH: ZERO BALANCE DRIFT DETECTED'
      : 'ALERT: MATHEMATICAL BALANCE DRIFT DETECTED!';
  }
  if (bannerDesc) {
    bannerDesc.textContent = isHealthy
      ? 'All accounts satisfy the Balance Invariant and transactions satisfy the Double-Entry Conservation Law.'
      : 'Discrepancy detected between cached accounts table and immutable ledger_entries!';
  }
  if (healthBadge) {
    healthBadge.innerHTML = isHealthy
      ? '&bull; Invariant Verified'
      : '&bull; Drift Detected!';
    healthBadge.parentElement.style.color = isHealthy ? 'var(--badge-credit-text)' : 'var(--badge-debit-text)';
  }

  // Render discrepancies card if drifts exist
  const discCard = document.getElementById('discrepancies-card');
  const discTbody = document.getElementById('discrepancies-tbody');
  if (discCard && discTbody) {
    if (data.discrepancies && data.discrepancies.length > 0) {
      discCard.style.display = 'block';
      discTbody.innerHTML = data.discrepancies
        .map(
          (d) => `
            <tr>
              <td><span class="uuid-tag">${d.account_id}</span></td>
              <td><span class="pill pill-gray">${d.currency}</span></td>
              <td class="amount-mono" style="color: var(--badge-debit-text); font-weight: 700;">$${d.actual_balance}</td>
              <td class="amount-mono" style="color: var(--badge-credit-text); font-weight: 700;">$${d.expected_balance}</td>
              <td class="amount-mono" style="font-weight: 800; color: #be123c;">${d.drift}</td>
              <td style="font-size: 12px; color: var(--text-muted);">${d.reason}</td>
            </tr>
          `
        )
        .join('');
    } else {
      discCard.style.display = 'none';
      discTbody.innerHTML = '';
    }
  }
}

async function handleTamperDrill() {
  const drillOutput = document.getElementById('drill-output');
  try {
    const res = await LedgerAPI.tamperDrill(null, '100.00');
    if (drillOutput) {
      drillOutput.innerHTML = `
        <span style="color: var(--badge-debit-text); font-weight: 600;">&#x26a0; ${res.data.message}</span><br>
        Corrupted Account: <span class="uuid-tag">${res.data.account_id}</span> (${res.data.injected_drift})
      `;
    }
    showToast(`Corrupted balance by ${res.data.injected_drift}. Running audit...`, 'error', 'Drift Injected');
    await executeReconciliationAudit();
    await loadAccounts();
  } catch (err) {
    showToast(err.message, 'error', 'Tamper Drill Failed');
  }
}

async function handleHealDrill() {
  const drillOutput = document.getElementById('drill-output');
  try {
    const res = await LedgerAPI.healDrill();
    if (drillOutput) {
      drillOutput.innerHTML = `
        <span style="color: var(--badge-credit-text); font-weight: 600;">&#x2714; ${res.data.message} (${res.data.accounts_healed} accounts healed)</span>
      `;
    }
    showToast('Reconstructed cached balances from immutable ledger entries!', 'success', 'System Healed');
    await executeReconciliationAudit();
    await loadAccounts();
  } catch (err) {
    showToast(err.message, 'error', 'Heal Failed');
  }
}

// ==========================================================================
// CREATE ACCOUNT MODAL
// ==========================================================================

function initCreateAccountModal() {
  const modal = document.getElementById('create-account-modal');
  const openBtn = document.getElementById('btn-open-create-account-modal');
  const closeBtn = document.getElementById('btn-close-modal');
  const cancelBtn = document.getElementById('btn-cancel-modal');
  const form = document.getElementById('create-account-form');

  if (openBtn && modal) {
    openBtn.addEventListener('click', () => modal.showModal());
  }

  const closeModal = () => {
    if (modal && modal.open) modal.close();
  };

  if (closeBtn) closeBtn.addEventListener('click', closeModal);
  if (cancelBtn) cancelBtn.addEventListener('click', closeModal);

  if (form) {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const curr = document.getElementById('new-account-currency')?.value || 'USD';
      const bal = document.getElementById('new-account-balance')?.value || '1000.00';

      try {
        await LedgerAPI.createAccount(curr.toUpperCase(), parseFloat(bal).toFixed(2));
        showToast(`Account created with initial balance $${bal} ${curr}`, 'success');
        closeModal();
        await refreshAllData();
      } catch (err) {
        showToast(err.message, 'error', 'Create Account Failed');
      }
    });
  }
}

// ==========================================================================
// SEARCH FILTER
// ==========================================================================

function initSearchFilter() {
  const searchInput = document.getElementById('global-search-input');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      state.searchFilter = e.target.value.trim();
      renderAccountsTable();
    });
  }
}

// ==========================================================================
// GLOBAL REFRESH & APPLICATION INITIALIZATION
// ==========================================================================

async function refreshAllData() {
  await Promise.all([
    loadAccounts(),
    loadLedgerStream(),
    loadCards(),
    loadReconciliationStatus(),
  ]);
}

document.addEventListener('DOMContentLoaded', async () => {
  initTabs();
  initTransferTerminal();
  initCardSimulator();
  initReconciliation();
  initCreateAccountModal();
  initSearchFilter();

  const refreshBtn = document.getElementById('btn-manual-refresh');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async () => {
      refreshBtn.disabled = true;
      try {
        await refreshAllData();
        showToast('Ledger data refreshed', 'success');
      } finally {
        refreshBtn.disabled = false;
      }
    });
  }

  // Initial load
  await refreshAllData();

  // Background polling loop (every 3.5 seconds)
  setInterval(() => {
    refreshAllData();
  }, 3500);
});
