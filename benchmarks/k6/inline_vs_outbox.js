import http from 'k6/http';
import { check } from 'k6';
import { uuidv4 } from 'https://jslib.k6.io/k6-utils/1.4.0/index.js';

export const options = {
  scenarios: {
    outbox_transfers: {
      executor: 'constant-vus',
      vus: 10,
      duration: '5s',
      exec: 'outboxTransfer',
    },
  },
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<50'], // Outbox ensures fast transfer commits
  },
};

const BASE_URL = __ENV.BASE_URL || 'http://127.0.0.1:8000';

export function setup() {
  const params = { headers: { 'Content-Type': 'application/json' } };
  const resA = http.post(`${BASE_URL}/api/v1/accounts`, JSON.stringify({ currency: 'USD', initial_balance: '1000000.00' }), params);
  const resB = http.post(`${BASE_URL}/api/v1/accounts`, JSON.stringify({ currency: 'USD', initial_balance: '1000000.00' }), params);

  return {
    accA: resA.json('id'),
    accB: resB.json('id'),
  };
}

export function outboxTransfer(data) {
  const key = uuidv4();
  const payload = JSON.stringify({
    from_account_id: data.accA,
    to_account_id: data.accB,
    amount: '10.00',
    currency: 'USD',
    memo: 'Decoupled outbox transfer with AI categorization',
  });

  const params = {
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': key,
    },
  };

  const res = http.post(`${BASE_URL}/api/v1/transfers`, payload, params);

  check(res, {
    'status is 201': (r) => r.status === 201,
  });
}
