/**
 * Payment Ledger API Client
 * Centralized, typed HTTP client communicating with the FastAPI backend.
 */

const API_BASE = '/api/v1';

export class LedgerAPI {
  /**
   * Helper method for executing fetch with standard JSON headers and error unwrapping.
   */
  static async request(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const headers = {
      'Content-Type': 'application/json',
      ...options.headers,
    };

    const config = {
      ...options,
      headers,
    };

    try {
      const response = await fetch(url, config);
      const isReplay = response.headers.get('X-Idempotent-Replay') === 'true';
      
      let data = null;
      const text = await response.text();
      if (text) {
        try {
          data = JSON.parse(text);
        } catch {
          data = { message: text };
        }
      }

      if (!response.ok) {
        const errorMsg = data?.detail || data?.message || `HTTP ${response.status}: ${response.statusText}`;
        const error = new Error(errorMsg);
        error.status = response.status;
        error.data = data;
        throw error;
      }

      return {
        status: response.status,
        data,
        isReplay,
      };
    } catch (err) {
      console.error(`[API Error] ${options.method || 'GET'} ${url}`, err);
      throw err;
    }
  }

  // --- Account Endpoints ---
  static async getAccounts(limit = 100) {
    return this.request(`/accounts?limit=${limit}`);
  }

  static async getAccount(accountId) {
    return this.request(`/accounts/${accountId}`);
  }

  static async createAccount(currency, initialBalance) {
    return this.request('/accounts', {
      method: 'POST',
      body: JSON.stringify({
        currency,
        initial_balance: initialBalance,
      }),
    });
  }

  // --- Transfer & Ledger Endpoints ---
  static async executeTransfer({ fromAccountId, toAccountId, amount, currency, memo, idempotencyKey }) {
    return this.request('/transfers', {
      method: 'POST',
      headers: {
        'Idempotency-Key': idempotencyKey,
      },
      body: JSON.stringify({
        from_account_id: fromAccountId,
        to_account_id: toAccountId,
        amount,
        currency,
        memo,
      }),
    });
  }

  static async getTransactions(limit = 50) {
    return this.request(`/transfers?limit=${limit}`);
  }

  static async getLedgerEntries(limit = 50) {
    return this.request(`/transfers/entries?limit=${limit}`);
  }

  // --- Card Lifecycle Endpoints ---
  static async authorizeCard({ accountId, merchantId, amount, currency, memo, holdDurationHours = 168, idempotencyKey = null }) {
    const headers = {};
    if (idempotencyKey) {
      headers['Idempotency-Key'] = idempotencyKey;
    }
    return this.request('/cards/authorize', {
      method: 'POST',
      headers,
      body: JSON.stringify({
        account_id: accountId,
        merchant_id: merchantId,
        amount,
        currency,
        memo,
        hold_duration_hours: holdDurationHours,
      }),
    });
  }

  static async captureCard(authId, amount = null) {
    return this.request(`/cards/${authId}/capture`, {
      method: 'POST',
      body: JSON.stringify(amount ? { amount } : {}),
    });
  }

  static async voidCard(authId, reason = null) {
    return this.request(`/cards/${authId}/void`, {
      method: 'POST',
      body: JSON.stringify(reason ? { reason } : {}),
    });
  }

  static async refundCard(authId, amount = null, reason = null) {
    const body = {};
    if (amount) body.amount = amount;
    if (reason) body.reason = reason;
    return this.request(`/cards/${authId}/refund`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  }

  static async getAccountCards(accountId) {
    return this.request(`/cards/account/${accountId}`);
  }

  // --- Reconciliation & Integrity Endpoints ---
  static async runReconciliation() {
    return this.request('/reconciliation/run', {
      method: 'POST',
    });
  }

  static async getReconciliationStatus() {
    return this.request('/reconciliation/status');
  }

  static async tamperDrill(accountId = null, driftAmount = '100.00') {
    return this.request('/reconciliation/drill/tamper', {
      method: 'POST',
      body: JSON.stringify({
        account_id: accountId,
        drift_amount: driftAmount,
      }),
    });
  }

  static async healDrill() {
    return this.request('/reconciliation/drill/heal', {
      method: 'POST',
    });
  }
}
