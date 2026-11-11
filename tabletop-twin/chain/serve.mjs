// Serves the agent chain to the Python backend over 127.0.0.1.
//
// The backend cannot run an EVM, so this process holds the one real instance of it and the
// backend talks to it the way it would talk to any other local service. Nothing here is
// reachable from outside the machine, and the keys it signs with are derived from role names
// rather than kept secret, so the sidecar is a bridge, not a vault. If TWIN_CHAIN_TOKEN is
// set, writes additionally require it in x-twin-chain-token - which matters the moment
// somebody points this at a non-loopback interface.
//
// Writes are queued, not overlapped: two transactions signed from the same account at the
// same nonce would be the same transaction twice, and a queue is cheaper than explaining it.
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { TwinChain, loadRoster } from './node.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const PORT = Number(process.env.TWIN_CHAIN_PORT || 8791);
const HOST = '127.0.0.1';
// A test wants a chain of its own; the app wants the one it can find again tomorrow.
const JOURNAL = process.env.TWIN_CHAIN_JOURNAL || path.join(here, '.journal.jsonl');
const TOKEN = process.env.TWIN_CHAIN_TOKEN || '';

function readCap() {
  const file = process.env.TWIN_PRIORS || path.join(here, '..', 'backend', 'twin', 'audit', 'data', 'priors.json');
  const prior = JSON.parse(fs.readFileSync(file, 'utf8')).priors.non_audit_fee_cap_percent;
  if (prior.state !== 'calibrated') throw new Error(`non_audit_fee_cap_percent is ${prior.state}, not calibrated`);
  return { bps: Math.round(prior.value * 100), percent: prior.value, celex: prior.celex, article: prior.article };
}

const cap = readCap();
if (process.argv.includes('--reset')) fs.rmSync(JOURNAL, { force: true });
const chain = await TwinChain.open({ capBasisPoints: cap.bps, roster: loadRoster(), journalPath: JOURNAL });
if (chain.replayed) console.log(`replayed ${chain.replayed} journal entries, state root matches`);

let queue = Promise.resolve();
const serial = (task) => {
  const run = queue.then(task, task);
  queue = run.then(() => undefined, () => undefined);
  return run;
};

/// The backend writes Python; the contracts read Solidity-shaped names. One translation here
/// keeps snake_case on the wire and camelCase in the chain code.
const camelize = (body) => Object.fromEntries(
  Object.entries(body).map(([k, v]) => [k.replace(/_([a-z0-9])/g, (_m, c) => c.toUpperCase()), v]),
);

const OPS = {
  register: (b) => chain.register(b),
  withdraw: (b) => chain.withdraw(b),
  set_principal: (b) => chain.setPrincipal(b),
  propose: (b) => chain.propose(b),
  accept: (b) => chain.accept(b),
  attest: (b) => chain.attest(b),
  countersign: (b) => chain.countersign(b),
  settle: (b) => chain.settle(b),
  reject: (b) => chain.reject(b),
  dispute: (b) => chain.dispute(b),
  advance: (b) => chain.advance(Number(b.seconds ?? 1)),
};

function send(res, code, body) {
  const text = JSON.stringify(body);
  res.writeHead(code, { 'content-type': 'application/json', 'content-length': Buffer.byteLength(text) });
  res.end(text);
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://${HOST}:${PORT}`);
  const respond = async () => {
    if (req.method === 'GET') {
      if (url.pathname === '/status') return send(res, 200, { ...(await chain.status()), cap_percent: cap.percent, source: `${cap.celex} art ${cap.article}` });
      if (url.pathname === '/agreements') return send(res, 200, { agreements: await chain.agreements() });
      if (url.pathname === '/agreement') {
        const id = url.searchParams.get('id');
        if (!id) return send(res, 400, { error: 'id required' });
        return send(res, 200, await chain.agreement(id));
      }
      if (url.pathname === '/roles') {
        const out = [];
        for (const agent of chain.roster.agents) {
          out.push({ ...agent, known: await chain.known(agent.role), address: chain.keyFor(agent.role).hex });
        }
        return send(res, 200, { owner: chain.roster.owner, agents: out, count: await chain.registeredCount() });
      }
      if (url.pathname === '/inbox') {
        const role = url.searchParams.get('role') || '*';
        const after = Number(url.searchParams.get('after') || 0);
        // The cursor counts transactions, not events, because a refused write takes a
        // transaction and emits nothing. events.length would sit behind the log forever.
        return send(res, 200, { role, cursor: chain.entries, events: chain.inbox(role, after) });
      }
      return send(res, 404, { error: `no route ${url.pathname}` });
    }
    if (req.method !== 'POST') return send(res, 405, { error: 'GET or POST' });
    if (TOKEN && req.headers['x-twin-chain-token'] !== TOKEN) return send(res, 401, { error: 'bad token' });
    const body = await new Promise((resolve, reject) => {
      let raw = '';
      req.on('data', (chunk) => {
        raw += chunk;
        if (raw.length > 1_000_000) reject(new Error('body too large'));
      });
      req.on('end', () => {
        try {
          resolve(raw ? JSON.parse(raw) : {});
        } catch (e) {
          reject(e);
        }
      });
      req.on('error', reject);
    });
    const op = OPS[body.op];
    if (!op) return send(res, 400, { error: `unknown op ${body.op}`, ops: Object.keys(OPS) });
    const result = await op(camelize(body));
    if (typeof result === 'number') return send(res, 200, { ok: true, tick: result, state_root: await chain.stateRoot() });
    return send(res, 200, {
      ok: result.status === 1,
      status: result.status,
      id: result.id ?? null,
      gas_used: result.gasUsed ?? null,
      wei_spent: result.weiSpent ?? null,
      tick: result.tick,
      // The log cursor this write's events were stamped with, so a mirror row can be read
      // back in chain order instead of by the wall clock it happened to arrive at.
      seq: chain.entries,
      error: result.error ?? null,
      events: result.events ?? [],
      terms_hash: result.terms_hash ?? null,
      evidence_hash: result.evidence_hash ?? null,
      state_root: await chain.stateRoot(),
    });
  };
  serial(respond).catch((e) => send(res, 500, { error: String(e?.message ?? e) }));
});

server.listen(PORT, HOST, async () => {
  const status = await chain.status();
  console.log(`chain: ${HOST}:${PORT}  registry ${status.registry}  agreement ${status.agreement}`);
  console.log(`cap: ${cap.percent}% = ${cap.bps} bps, derived from ${cap.celex} article ${cap.article}`);
  console.log(`journal: ${JOURNAL} (${status.entries} entries, ${status.roles} roles, ${status.agreements} agreements)`);
  console.log(`replay on boot: ${chain.replayed ? `${chain.replayed} entries, roots matched` : 'fresh chain'}`);
});
