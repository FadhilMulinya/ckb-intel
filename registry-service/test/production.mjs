import assert from 'node:assert/strict';
import { test, afterEach, mock } from 'node:test';
import axios from 'axios';
import { buildApp } from '../dist/server.js';
import { environments, allowedOrigins, positiveInteger } from '../dist/environments.js';
import { Wallet } from '../dist/db/models/Wallet.js';

const address = 'ckb1qzda0cr08m85hc8jlnfp3zer7xulejywt49kt2rr0vthywaa50xwsqg239ffgrtl3mf4m6s02eweangtpe0gy9cph6u05';
const families = ['temporal', 'periodicity', 'topology', 'lifecycle', 'templates', 'scripts', 'typed_assets', 'capacity', 'lineage'];
const features = Object.fromEntries(families.map(family => [family, {
  feature_family: family, support_state: 'SUPPORTED', requirements: {}, sample_count: 1,
  coverage: {}, values: {}, evidence: {}, feature_schema_version: 'x', dataset_version: 'x', observation_contract_version: 'x',
}]));
const profile = { version: 'wallet-behaviour-v2', address, network: 'mainnet', observation: {}, evidence: {},
  feature_support: Object.fromEntries(families.map(f => [f, 'SUPPORTED'])), features, behaviors: [], limitations: [] };
const original = { ...environments };
const apps = [];
function app(overrides = {}) {
  Object.assign(environments, original, { analyzeRateLimit: 2, readRateLimit: 2, trustedProxies: [] }, overrides);
  mock.method(Wallet, 'findOne', async () => ({ ...profile, analysisVersion: profile.version, featureSupport: profile.feature_support }));
  mock.method(Wallet, 'find', () => ({ sort: () => ({ skip: () => ({ limit: async () => [] }) }) }));
  mock.method(Wallet, 'countDocuments', async () => 0);
  mock.method(Wallet, 'findOneAndUpdate', async () => ({ createdAt: 'test', updatedAt: 'test' }));
  mock.method(axios, 'post', async () => ({ data: profile }));
  const server = buildApp();
  apps.push(server);
  return server;
}
const read = (server, ip = '198.51.100.1', headers = {}, path = '') => server.inject({
  method: 'GET', url: `/api/v1/wallets${path}`, remoteAddress: ip, headers,
});
const analyze = (server, ip = '198.51.100.1', headers = {}) => server.inject({
  method: 'POST', url: '/api/v1/wallets/analyze', payload: { address, mode: 'live' }, remoteAddress: ip, headers,
});
afterEach(async () => {
  await Promise.all(apps.splice(0).map(server => server.close()));
  mock.restoreAll();
  Object.assign(environments, original);
});

test('production origins receive CORS on successful GET and POST, without credentials', async () => {
  const server = app({ readRateLimit: 10, analyzeRateLimit: 10 });
  for (const origin of ['https://demo.afriai.xyz', 'https://afriai.xyz']) {
    for (const response of [await read(server, undefined, { origin }), await analyze(server, undefined, { origin })]) {
      assert.equal(response.statusCode, 200);
      assert.equal(response.headers['access-control-allow-origin'], origin);
      assert.equal(response.headers['access-control-allow-credentials'], undefined);
      assert.match(response.headers.vary, /Origin/);
    }
  }
});

test('arbitrary origins receive no CORS permission; non-browser requests work', async () => {
  const server = app({ readRateLimit: 10 });
  for (const origin of ['https://evil.example', 'https://demo.afriai.xyz.evil.example', 'null']) {
    const response = await read(server, undefined, { origin });
    assert.equal(response.statusCode, 200); // CORS is a browser policy, not authentication.
    assert.equal(response.headers['access-control-allow-origin'], undefined);
  }
  assert.equal((await read(server)).statusCode, 200);
});

test('preflight permits JSON GET/POST, rejects no-origin preflight, and uses no analysis quota', async () => {
  const server = app();
  for (const method of ['GET', 'POST']) {
    const response = await server.inject({ method: 'OPTIONS', url: '/api/v1/wallets/analyze', headers: {
      origin: 'https://demo.afriai.xyz', 'access-control-request-method': method,
      'access-control-request-headers': 'content-type,accept',
    } });
    assert.equal(response.statusCode, 204);
    assert.equal(response.headers['access-control-allow-origin'], 'https://demo.afriai.xyz');
    assert.equal(response.headers['access-control-allow-methods'], 'GET, POST, OPTIONS');
    assert.equal(response.headers['access-control-allow-headers'], 'Content-Type, Accept');
  }
  const denied = await server.inject({ method: 'OPTIONS', url: '/api/v1/wallets/analyze', headers: {
    origin: 'https://evil.example', 'access-control-request-method': 'POST',
  } });
  assert.equal(denied.headers['access-control-allow-origin'], undefined);
  assert.equal((await server.inject({ method: 'OPTIONS', url: '/api/v1/wallets/analyze' })).statusCode, 400);
  assert.equal((await analyze(server)).statusCode, 200);
  assert.equal(axios.post.mock.calls[0].arguments[2].timeout, environments.classifierTimeoutMs);
});

test('read quota is shared across read routes, separated by IP and from analysis', async () => {
  const server = app();
  assert.equal((await read(server)).statusCode, 200);
  assert.equal((await read(server, undefined, {}, `/${address}`)).statusCode, 200);
  for (const suffix of [`/${address}/features`, `/${address}/behaviors`]) {
    const response = await read(server, undefined, { origin: 'https://demo.afriai.xyz' }, suffix);
    assert.equal(response.statusCode, 429);
    assert.equal(response.headers['x-ratelimit-limit'], '2');
    assert.ok(Number(response.headers['retry-after']) > 0);
    assert.equal(response.headers['access-control-allow-origin'], 'https://demo.afriai.xyz');
  }
  assert.equal((await read(server, '198.51.100.2')).statusCode, 200);
  assert.equal((await analyze(server)).statusCode, 200);
  assert.equal((await analyze(server)).statusCode, 200);
  assert.equal((await analyze(server)).statusCode, 429);
  assert.equal((await analyze(server, '198.51.100.2')).statusCode, 200);
  for (const url of ['/api/v1/health', '/api/v1/docs', '/api/v1/openapi.json']) {
    assert.equal((await server.inject({ url, remoteAddress: '198.51.100.1' })).statusCode, 200);
  }
});

test('fixed-window quota becomes available after expiry', async () => {
  const server = app({ readRateWindowMs: 30, readRateLimit: 1 });
  assert.equal((await read(server)).statusCode, 200);
  assert.equal((await read(server)).statusCode, 429);
  await new Promise(resolve => setTimeout(resolve, 45));
  assert.equal((await read(server)).statusCode, 200);
});

test('untrusted direct clients cannot rotate forwarded headers to evade limits', async () => {
  const server = app({ trustedProxies: ['172.30.0.1/32'] });
  for (let i = 1; i <= 3; i++) {
    const response = await read(server, '198.51.100.1', {
      'x-forwarded-for': `203.0.113.${i}`, 'cf-connecting-ip': `203.0.113.${i}`,
    });
    assert.equal(response.statusCode, i <= 2 ? 200 : 429);
  }
});

test('trusted immediate proxy separates clients and ignores spoofed leftmost hops', async () => {
  const server = app({ trustedProxies: ['172.30.0.1/32'] });
  for (let i = 1; i <= 3; i++) {
    const response = await read(server, '172.30.0.1', { 'x-forwarded-for': `192.0.2.${i}, 198.51.100.1` });
    assert.equal(response.statusCode, i <= 2 ? 200 : 429);
  }
  assert.equal((await read(server, '172.30.0.1', { 'x-forwarded-for': '198.51.100.2' })).statusCode, 200);
});

test('invalid inputs are rejected, internal failures sanitized, and busy classifier returns 503', async () => {
  const server = app({ readRateLimit: 10, analyzeRateLimit: 10 });
  assert.equal((await read(server, undefined, {}, '/ckb1invalid')).statusCode, 400);
  assert.equal((await read(server, undefined, {}, '?page=NaN')).statusCode, 400);
  for (const payload of [{ address: 'ckb1invalid' }, { address, mode: 'other' }, {}]) {
    assert.equal((await server.inject({ method: 'POST', url: '/api/v1/wallets/analyze', payload })).statusCode, 400);
  }
  assert.equal((await server.inject({ method: 'POST', url: '/api/v1/wallets/analyze', payload: { address: 'x'.repeat(17000) } })).statusCode, 413);
  axios.post.mock.mockImplementation(async () => { throw { isAxiosError: true, response: { status: 503, data: { detail: { status: 'ANALYSIS_BUSY' } } } }; });
  const busy = await analyze(server);
  assert.equal(busy.statusCode, 503);
  assert.equal(busy.json().status, 'ANALYSIS_BUSY');
  assert.equal(busy.headers['retry-after'], '5');
  Wallet.countDocuments.mock.mockImplementation(async () => { throw new Error('mongodb+srv://secret'); });
  const failure = await read(server);
  assert.equal(failure.statusCode, 500);
  assert.ok(!failure.body.includes('secret'));
  assert.equal((await server.inject({ url: '/api/v1/health' })).statusCode, 200);
});

test('CORS and numeric configuration fail closed on invalid values', () => {
  assert.deepEqual(allowedOrigins(' https://demo.afriai.xyz,https://afriai.xyz, '), ['https://demo.afriai.xyz', 'https://afriai.xyz']);
  for (const value of ['*', 'https://*', 'null', 'https://demo.afriai.xyz/path', 'https://user:pass@demo.afriai.xyz']) assert.throws(() => allowedOrigins(value));
  process.env.TEST_PRODUCTION_NUMBER = '0';
  assert.throws(() => positiveInteger('TEST_PRODUCTION_NUMBER', 2));
  delete process.env.TEST_PRODUCTION_NUMBER;
});
