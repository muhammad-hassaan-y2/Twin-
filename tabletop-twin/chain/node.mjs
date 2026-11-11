// The EVM the agent agreements live on, and the journal that lets it survive a restart.
//
// There is no network and no faucet. This is an @ethereumjs/vm in this process, the balances
// are minted at boot, and every call pays real gas that the EVM computes and charges. Gas is
// not the interesting part; what it buys is. A requirement that lives in bytecode cannot be
// talked around by the agent that finds it inconvenient, which is the only sense in which a
// firm run by agents can be read by somebody who is not one.
//
// Keys are derived from names, so they are not secrets: the firm's agents, their human
// principals and the firm key all rebuild from the journal after a crash. That is the trade
// being made on purpose. The chain is a durable, checkable record of who agreed to what, not
// a custody system. The keys that do carry weight are the humans', and `countersign()` only
// accepts the address the registry holds for a role, so a machine cannot invent the signature
// that makes an opinion signable.
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { createVM, runTx } from '@ethereumjs/vm';
import { createLegacyTx } from '@ethereumjs/tx';
import { Account, bytesToHex, createAddressFromPrivateKey, createAddressFromString, hexToBytes } from '@ethereumjs/util';
import { createBlock } from '@ethereumjs/block';
import { AbiCoder, Interface, keccak256, toUtf8Bytes } from 'ethers';

const require = createRequire(import.meta.url);
const here = path.dirname(new URL(import.meta.url).pathname.replace(/^\/(\w:)/, '$1'));

export const GENESIS_AT = 1_735_689_600; // 2025-01-01T00:00:00Z, fixed so a replay matches
export const START_BALANCE = 10n ** 20n; // 100 ETH minted locally, so gas is paid for real
const GAS_PRICE = 7n;
const DEPLOY_GAS = 6_000_000n;
const CALL_GAS = 900_000n;
const KEY_SALT = 'twin-audit-v1:';
const ROSTER = path.join(here, 'roster.json');
const JOURNAL = path.join(here, '.journal.jsonl');
const STATES = ['None', 'Proposed', 'Accepted', 'Attested', 'Settled', 'Rejected', 'Disputed'];

const jsonSafe = (_k, v) => (typeof v === 'bigint' ? v.toString() : v);
const hexOf = (v) => (typeof v === 'string' ? v : bytesToHex(v));

function normalise(value) {
  if (Array.isArray(value)) return value.map(normalise);
  if (typeof value === 'bigint') return value.toString();
  if (value instanceof Uint8Array) return bytesToHex(value);
  return value;
}

function logParts(log) {
  if (Array.isArray(log)) {
    return { address: bytesToHex(log[0]), topics: log[1].map(bytesToHex), data: bytesToHex(log[2]) };
  }
  return { address: bytesToHex(log.address), topics: log.topics.map(bytesToHex), data: bytesToHex(log.data) };
}

export function loadRoster(file = ROSTER) {
  return JSON.parse(fs.readFileSync(file, 'utf8'));
}

/// The hash the chain holds for a piece of text. Anyone with the same text can recompute it,
/// which is what makes "these were the terms" answerable rather than merely logged.
export function sha3(text) {
  return keccak256(toUtf8Bytes(text));
}

export class TwinChain {
  constructor({ vm, capBasisPoints, roster, journalPath }) {
    this.vm = vm;
    this.capBasisPoints = capBasisPoints;
    this.roster = roster;
    this.journalPath = journalPath;
    this.tick = 0;
    this.entries = 0;
    this.events = [];
    this.registryAddress = null;
    this.agreementAddress = null;
    this._keys = new Map();
    this._artifacts = new Map();
    this._interfaces = {};
    this._handleMap = null;
  }

  /// Bring the chain up: mint the balances, then either deploy a fresh chain or rebuild the
  /// one in the journal. Rebuild is not a best-effort reload - every replayed transaction has
  /// to land on the recorded addresses, status and state root or this throws and says so.
  static async open({ capBasisPoints = 7000, roster = loadRoster(), journalPath = JOURNAL, reset = false } = {}) {
    if (reset && fs.existsSync(journalPath)) fs.rmSync(journalPath);
    const vm = await createVM();
    const chain = new TwinChain({ vm, capBasisPoints, roster, journalPath });
    chain._interfaces.AgentRegistry = new Interface(chain.artifact('AgentRegistry').abi);
    chain._interfaces.EngagementAgreement = new Interface(chain.artifact('EngagementAgreement').abi);
    if (fs.existsSync(journalPath)) return await chain._replay();
    await chain._genesis();
    return chain;
  }

  artifact(name) {
    if (!this._artifacts.has(name)) {
      const raw = JSON.parse(fs.readFileSync(path.join(here, 'artifacts', `${name}.json`), 'utf8'));
      this._artifacts.set(name, raw);
    }
    return this._artifacts.get(name);
  }

  keyFor(name) {
    if (!this._keys.has(name)) {
      const privateKey = hexToBytes(keccak256(toUtf8Bytes(KEY_SALT + name)));
      const address = createAddressFromPrivateKey(privateKey);
      this._keys.set(name, { name, privateKey, address, hex: address.toString() });
    }
    return this._keys.get(name);
  }

  /// Every name that ever signs gets a genesis balance. Balances are minted rather than
  /// fetched, so there is no faucet to run out of and no operator to beg.
  async fund(name) {
    const key = this.keyFor(name);
    await this.vm.stateManager.putAccount(key.address, new Account(0n, START_BALANCE));
    return key;
  }

  keys() {
    return [...this._keys.keys()];
  }

  async block() {
    return createBlock({ header: { number: BigInt(this.tick + 1), timestamp: BigInt(GENESIS_AT + this.tick) } });
  }

  async stateRoot() {
    return bytesToHex(await this.vm.stateManager.getStateRoot());
  }

  async _genesis() {
    const names = [this.roster.owner, ...this.roster.agents.flatMap((a) => [a.role, a.principal])];
    for (const name of names) await this.fund(name);
    const owner = this.keyFor(this.roster.owner);
    this.registryAddress = (await this._send(owner, undefined, this.artifact('AgentRegistry').bytecode, DEPLOY_GAS)).created;
    const encoded = this.artifact('EngagementAgreement').bytecode
      + this._interfaces.EngagementAgreement.encodeDeploy([this.registryAddress, BigInt(this.capBasisPoints)]).slice(2);
    this.agreementAddress = (await this._send(owner, undefined, encoded, DEPLOY_GAS)).created;
    const genesis = {
      kind: 'genesis',
      tick: 0,
      cap_bps: String(this.capBasisPoints),
      keys: names,
      registry: this.registryAddress,
      agreement: this.agreementAddress,
      roster: this.roster,
      state_root: await this.stateRoot(),
    };
    this._append(genesis);
  }

  async _replay() {
    const lines = fs
      .readFileSync(this.journalPath, 'utf8')
      .split('\n')
      .filter((l) => l.trim())
      .map((l) => JSON.parse(l));
    const genesis = lines[0];
    if (genesis?.kind !== 'genesis') throw new Error('journal does not start with a genesis line');
    this.roster = genesis.roster;
    this.capBasisPoints = Number(genesis.cap_bps);
    for (const name of genesis.keys) await this.fund(name);
    const owner = this.keyFor(this.roster.owner);
    const registry = await this._send(owner, undefined, this.artifact('AgentRegistry').bytecode, DEPLOY_GAS);
    if (registry.created !== genesis.registry) {
      throw new Error(`registry rebuilt at ${registry.created}, journal says ${genesis.registry}`);
    }
    this.registryAddress = registry.created;
    const encoded = this.artifact('EngagementAgreement').bytecode
      + this._interfaces.EngagementAgreement.encodeDeploy([genesis.registry, BigInt(this.capBasisPoints)]).slice(2);
    const agreement = await this._send(owner, undefined, encoded, DEPLOY_GAS);
    if (agreement.created !== genesis.agreement) {
      throw new Error(`agreement contract rebuilt at ${agreement.created}, journal says ${genesis.agreement}`);
    }
    this.agreementAddress = agreement.created;
    const root = await this.stateRoot();
    if (root !== genesis.state_root) throw new Error(`genesis state root ${root} != journal ${genesis.state_root}`);
    this.replayed = lines.length - 1;
    for (const entry of lines.slice(1)) {
      if (entry.kind === 'time') {
        this.tick = entry.tick;
        continue;
      }
      const iface = this._interfaces[entry.contract];
      // The recorded tick is the block time this entry was written under. Rebuilding at a
      // different time would change every deadline check, so the journal has to be exact.
      this.tick = entry.tick;
      const result = await this._send(this.keyFor(entry.actor), entry.target, iface.encodeFunctionData(entry.fn, entry.args), CALL_GAS);
      const status = result.receipt.status === undefined ? 1 : Number(result.receipt.status);
      const after = await this.stateRoot();
      if (status !== entry.status) throw new Error(`${entry.fn} replayed with status ${status}, journal says ${entry.status}`);
      if (after !== entry.state_root) throw new Error(`${entry.fn} replayed to root ${after}, journal says ${entry.state_root}`);
      this.entries += 1;
      this.events.push(...result.events.map((e) => ({ ...e, seq: this.entries })));
    }
    this.replayed = lines.length - 1;
    return this;
  }

  _append(entry) {
    fs.appendFileSync(this.journalPath, JSON.stringify(entry, jsonSafe) + '\n');
  }

  async _send(key, to, data, gasLimit) {
    const block = await this.block();
    const nonce = (await this.vm.stateManager.getAccount(key.address))?.nonce ?? 0n;
    const tx = createLegacyTx({
      nonce,
      gasLimit,
      gasPrice: GAS_PRICE,
      to: to === undefined ? undefined : createAddressFromString(to),
      data: hexToBytes(typeof data === 'string' ? data : bytesToHex(data)),
      value: 0n,
      chainId: 1n,
    }).sign(key.privateKey);
    const result = await runTx(this.vm, { tx, block });
    const logs = (result.execResult.logs ?? result.receipt.logs ?? []).map((log) => {
      const parts = logParts(log);
      for (const [contract, candidate] of Object.entries(this._interfaces)) {
        try {
          const decoded = candidate.parseLog(parts);
          return { contract, name: decoded.name, args: normalise(Array.from(decoded.args)) };
        } catch {
          /* the log belongs to the other contract */
        }
      }
      return { contract: 'unknown', name: null, raw: parts };
    });
    let error = null;
    if (result.receipt.status === 0) error = this._decodeRevert(bytesToHex(result.execResult.returnValue ?? new Uint8Array()));
    return {
      result,
      created: result.createdAddress ? result.createdAddress.toString() : null,
      receipt: result.receipt,
      status: result.receipt.status === undefined ? 1 : Number(result.receipt.status),
      gasUsed: result.totalGasSpent.toString(),
      weiSpent: result.amountSpent.toString(),
      events: logs.filter((l) => l.name),
      error,
      returnValue: bytesToHex(result.execResult.returnValue ?? new Uint8Array()),
    };
  }

  /// A revert is an answer, so it is reported as one: which custom error, with what arguments.
  /// `require(..., "text")` comes back under the standard Error selector and keeps its text.
  _decodeRevert(returned) {
    const selector = returned.slice(0, 10);
    if (returned === '0x') return { selector, name: 'reverted without data', args: [] };
    if (selector === '0x08c379a0') {
      try {
        return { selector, name: 'require', args: [new AbiCoder().decode(['string'], `0x${returned.slice(10)}`)[0]] };
      } catch {
        return { selector, name: 'require', args: [] };
      }
    }
    for (const iface of Object.values(this._interfaces)) {
      const parsed = iface.parseError(returned);
      if (parsed) return { selector, name: parsed.name, args: normalise(Array.from(parsed.args)) };
    }
    return { selector, name: `unknown(${selector})`, args: [] };
  }

  /// One state change: sign it, run it, journal it, and hand back what the chain said.
  /// The clock moves one second per transaction so a deadline means the same thing on
  /// replay that it meant the first time.
  async write({ contract = 'EngagementAgreement', actor, fn, args }) {
    this.tick += 1;
    const iface = this._interfaces[contract];
    const target = contract === 'AgentRegistry' ? this.registryAddress : this.agreementAddress;
    const sent = await this._send(this.keyFor(actor), target, iface.encodeFunctionData(fn, args), CALL_GAS);
    const entry = {
      kind: 'write',
      tick: this.tick,
      actor,
      contract,
      target,
      fn,
      args: normalise(args),
      status: sent.status,
      gas: sent.gasUsed,
      error: sent.error,
      state_root: await this.stateRoot(),
    };
    this._append(entry);
    this.entries += 1;
    this.events.push(...sent.events.map((e) => ({ ...e, actor, tick: this.tick, seq: this.entries })));
    return { ...sent, tick: this.tick, id: this._idFrom(sent) };
  }

  _idFrom(sent) {
    for (const event of sent.events) {
      const index = event.args?.findIndex?.((a) => typeof a === 'string' && /^0x[0-9a-f]{64}$/.test(a));
      if (index !== undefined && index >= 0) return event.args[index];
    }
    return null;
  }

  /// A view call runs against a copy of the VM, so it cannot leave state behind, and no
  /// signature or nonce is spent on it.
  async read({ contract = 'EngagementAgreement', actor, fn, args = [] }) {
    const vm = await this.vm.shallowCopy();
    const block = await this.block();
    const iface = this._interfaces[contract];
    const target = contract === 'AgentRegistry' ? this.registryAddress : this.agreementAddress;
    const r = await vm.evm.runCall({
      block,
      caller: this.keyFor(actor).address,
      to: createAddressFromString(target),
      data: hexToBytes(iface.encodeFunctionData(fn, args)),
      gasLimit: CALL_GAS,
      gasPrice: 0n,
      value: 0n,
    });
    if (r.execResult.exceptionError) throw new Error(`${fn} failed: ${r.execResult.exceptionError.error}`);
    const out = iface.decodeFunctionResult(fn, r.execResult.returnValue);
    return out.length === 1 ? normalise(out[0]) : normalise(Array.from(out));
  }

  // --- registry ---------------------------------------------------------------

  async register({ role, title, principal }) {
    return await this.write({
      contract: 'AgentRegistry',
      actor: this.roster.owner,
      fn: 'register',
      args: [sha3(role), this.keyFor(role).hex, this.keyFor(principal).hex, title],
    });
  }

  async setPrincipal({ role, principal }) {
    return await this.write({
      contract: 'AgentRegistry',
      actor: this.roster.owner,
      fn: 'setPrincipal',
      args: [sha3(role), this.keyFor(principal).hex],
    });
  }

  async withdraw({ role }) {
    return await this.write({ contract: 'AgentRegistry', actor: this.roster.owner, fn: 'withdraw', args: [sha3(role)] });
  }

  async agent(role) {
    return await this.read({ contract: 'AgentRegistry', actor: this.roster.owner, fn: 'agent', args: [sha3(role)] });
  }

  async known(role) {
    return await this.read({ contract: 'AgentRegistry', actor: this.roster.owner, fn: 'known', args: [sha3(role)] });
  }

  async registeredCount() {
    return Number(await this.read({ contract: 'AgentRegistry', actor: this.roster.owner, fn: 'size' }));
  }

  /// Roles in the registry that the roster does not name. A live registry with an agent
  /// nobody hired is the failure mode this whole layer exists to make visible.
  async rogueRoles() {
    const listed = await this.read({ contract: 'AgentRegistry', actor: this.roster.owner, fn: 'size' });
    const names = new Set(this.roster.agents.map((a) => sha3(a.role)));
    const rogues = [];
    for (let i = 0n; i < listed; i += 1n) {
      const role = await this.read({ contract: 'AgentRegistry', actor: this.roster.owner, fn: 'roleAt', args: [i] });
      if (!names.has(role)) rogues.push(role);
    }
    return rogues;
  }

  // --- agreements -------------------------------------------------------------

  /// The proposer signs for itself and names the counterparty, so neither is implied later.
  async propose({ from, to, terms, amountCents, nonAuditCents, horizonSec = 3600 }) {
    const deadline = GENESIS_AT + this.tick + horizonSec;
    const termsHash = terms.startsWith('0x') && terms.length === 66 ? terms : sha3(terms);
    const sent = await this.write({
      actor: from,
      fn: 'propose',
      args: [sha3(from), sha3(to), termsHash, BigInt(amountCents), BigInt(nonAuditCents), BigInt(deadline)],
    });
    // The hash goes back to the caller because the caller has to mirror the same one. Handing
    // it the text and letting it re-hash would put two implementations of one fact in the app.
    return { ...sent, terms_hash: termsHash, deadline };
  }

  async accept({ id, byRole }) {
    return await this.write({ actor: byRole, fn: 'accept', args: [id, sha3(byRole)] });
  }

  async attest({ id, byRole, evidence }) {
    if (!evidence) throw new Error('attest needs evidence to hash');
    const hash = evidence.startsWith('0x') && evidence.length === 66 ? evidence : sha3(evidence);
    const sent = await this.write({ actor: byRole, fn: 'attest', args: [id, sha3(byRole), hash] });
    return { ...sent, evidence_hash: hash };
  }

  /// Sent by the human key the registry holds for the counterparty role, never by the agent.
  /// That is the whole of the difference between a record and a signature.
  async countersign({ id, role }) {
    const agent = this.roster.agents.find((a) => a.role === role);
    if (!agent) throw new Error(`no principal on file for ${role}`);
    return await this.write({ actor: agent.principal, fn: 'countersign', args: [id] });
  }

  async settle({ id, byRole }) {
    return await this.write({ actor: byRole, fn: 'settle', args: [id, sha3(byRole)] });
  }

  async reject({ id, byRole, reason = '' }) {
    return await this.write({ actor: byRole, fn: 'reject', args: [id, sha3(byRole), reason] });
  }

  async dispute({ id, byRole, reason = '' }) {
    return await this.write({ actor: byRole, fn: 'dispute', args: [id, sha3(byRole), reason] });
  }

  async agreement(id) {
    const raw = await this.read({ actor: this.roster.owner, fn: 'get', args: [id] });
    const handles = this._handles();
    return {
      id: raw[0],
      fromRole: raw[1],
      toRole: raw[2],
      from_role: handles.get(String(raw[1]).toLowerCase()) ?? null,
      to_role: handles.get(String(raw[2]).toLowerCase()) ?? null,
      termsHash: raw[3],
      amountCents: raw[4],
      nonAuditCents: raw[5],
      state: STATES[Number(raw[6])] ?? `State(${raw[6]})`,
      deadline: Number(raw[7]),
      proposedAt: Number(raw[8]),
      evidenceHash: raw[9],
      signedBy: raw[10],
      reason: raw[12],
    };
  }

  async agreements() {
    const count = Number(await this.read({ actor: this.roster.owner, fn: 'count' }));
    const out = [];
    for (let i = 0; i < count; i += 1) {
      const id = await this.read({ actor: this.roster.owner, fn: 'idAt', args: [BigInt(i)] });
      out.push(await this.agreement(id));
    }
    return out;
  }

  /// The receive side of agent-to-agent traffic: everything the chain emitted for one role,
  /// behind a cursor the reader stores. Events carry a seq, so a reader can ask for what it
  /// has not seen yet instead of re-reading the log from the beginning every turn.
  /// Every handle a role is known by on the log, mapped back to the name the roster gave it.
  /// Bytes32 hashes cannot be inverted, so the reader that has the roster does the naming and
  /// the backend never needs a hash function of its own to know who a message was for.
  /// A principal's address names its role rather than the person, because the question an
  /// inbox answers is which work moved, and whose signature closed it is in the arguments.
  _handles() {
    if (!this._handleMap) {
      const map = new Map();
      for (const agent of this.roster.agents) {
        map.set(sha3(agent.role), agent.role);
        map.set(sha3(agent.principal), agent.principal);
        map.set(this.keyFor(agent.role).hex.toLowerCase(), agent.role);
        map.set(this.keyFor(agent.principal).hex.toLowerCase(), agent.role);
      }
      map.set(this.keyFor(this.roster.owner).hex.toLowerCase(), this.roster.owner);
      this._handleMap = map;
    }
    return this._handleMap;
  }

  inbox(role, after = 0) {
    const map = this._handles();
    const named = (event) => ({
      seq: event.seq,
      tick: event.tick,
      contract: event.contract,
      name: event.name,
      args: event.args,
      roles: [...new Set((event.args ?? []).filter((a) => typeof a === 'string').map((a) => map.get(a.toLowerCase())).filter(Boolean))],
    });
    if (role === '*') return this.events.filter((e) => e.seq > after).map(named);
    // A role is addressed two ways on the log: as its bytes32 name and, for the human step,
    // as the address of the principal the registry holds for it. Both belong in its inbox.
    const agent = this.roster.agents.find((a) => a.role === role);
    const handles = [sha3(role), agent ? this.keyFor(agent.principal).hex.toLowerCase() : null].filter(Boolean);
    return this.events
      .filter((e) => e.seq > after)
      .filter((e) => (e.args ?? []).some((a) => typeof a === 'string' && handles.includes(a.toLowerCase())))
      .map(named);
  }

  async advance(seconds) {
    this.tick += Math.max(1, Math.round(seconds));
    this._append({ kind: 'time', tick: this.tick });
    return this.tick;
  }

  async balanceOf(name) {
    return (await this.vm.stateManager.getAccount(this.keyFor(name).address))?.balance ?? 0n;
  }

  async nonceOf(name) {
    return (await this.vm.stateManager.getAccount(this.keyFor(name).address))?.nonce ?? 0n;
  }

  async status() {
    return {
      tick: this.tick,
      at: GENESIS_AT + this.tick,
      cap_basis_points: this.capBasisPoints,
      registry: this.registryAddress,
      agreement: this.agreementAddress,
      entries: this.entries,
      events: this.events.length,
      roles: await this.registeredCount(),
      agreements: Number(await this.read({ actor: this.roster.owner, fn: 'count' })),
      seq: Number(await this.read({ actor: this.roster.owner, fn: 'seq' })),
      keys: this.keys().length,
      journal: this.journalPath,
    };
  }
}
