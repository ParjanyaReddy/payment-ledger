import http from 'k6/http';
import { check, sleep } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

export const options = {
  scenarios: {
    constant_load: {
      executor: 'constant-vus',
      vus: 20,
      duration: '10s',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'], // < 1% failures
    http_req_duration: ['p(95)<100'], // 95% of requests must complete below 100ms
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';

export function setup() {
  // Create two dedicated accounts for load testing
  const payloadFrom = JSON.stringify({ currency: 'USD', initial_balance: '1000000.00' });
  const payloadTo = JSON.stringify({ currency: 'USD', initial_balance: '1000000.00' });
  const params = { headers: { 'Content-Type': 'application/json' } };

  const resFrom = http.post(`${BASE_URL}/api/v1/accounts`, payloadFrom, params);
  const resTo = http.post(`${BASE_URL}/api/v1/accounts`, payloadTo, params);

  check(resFrom, { 'Source account created': (r) => r.status === 201 });
  check(resTo, { 'Target account created': (r) => r.status === 201 });

  return {
    fromAccountId: resFrom.json('id'),
    toAccountId: resTo.json('id'),
  };
}

export default function (data) {
  const idempotencyKey = uuidv4();
  const payload = JSON.stringify({
    from_account_id: data.fromAccountId,
    to_account_id: data.toAccountId,
    amount: '1.00',
    currency: 'USD',
    memo: 'k6 load test transfer',
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
    },
  };

  const res = http.post(`${BASE_URL}/api/v1/transfers`, payload, params);

  check(res, {
    'status is 201': (r) => r.status === 201,
    'has transaction id': (r) => r.json('transaction_id') !== undefined,
  });
}

export function teardown(data) {
  // Trigger reconciliation to verify zero drift after load test
  const recRes = http.post(`${BASE_URL}/api/v1/reconciliation/run`);
  check(recRes, {
    'reconciliation status is HEALTHY': (r) => r.json('status') === 'HEALTHY',
    'drifts detected is 0': (r) => r.json('drifts_detected') === 0,
  });
}
