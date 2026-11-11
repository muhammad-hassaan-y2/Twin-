// Runs the agent contracts and reports what the bytecode refused.
//
// Every guard here is checked twice: once that it refuses, and once that the same call
// succeeds when the condition it guards is satisfied. A guard with no passing counterpart is
// not a guard, it is a outage, and a guard with no failing counterpart is a comment.
//
// The non-audit fee cap is read from the priors the corpus produced, not typed in. If
// backend/twin/audit/data/priors.json is missing this stops rather than inventing a number.
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { TwinChain, GENESIS_AT, loadRoster, sha3 } from './node.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const JOURNAL = path.join(here, '.verify.journal.jsonl');

function readCap() {
  const file = process.env.TWIN_PRIORS || path.join(here, '..', 'backend', 'twin', 'audit', 'data', 'priors.json');
  if (!fs.existsSync(file)) {
    console.error(`no priors at ${file}`);
    console.error('run: python -m twin.audit.calibrate   (the cap has to come from the corpus, not from here)');
    process.exit(2);
  }
  const prior = JSON.parse(fs.readFileSync(file, 'utf8')).priors.non_audit_fee_cap_percent;
  if (prior.state !== 'calibrated') {
    console.error(`non_audit_fee_cap_percent is ${prior.state}, refusing to deploy a cap that was not derived`);
    process.exit(2);
  }
  return { bps: Math.round(prior.value * 100), prior };
}

const results = [];
function check(label, pass, detail) {
  results.push({ label, pass: !!pass, detail });
  console.log(`${pass ? 'ok  ' : 'FAIL'}  ${label.padEnd(52)} ${detail}`);
}

async function refusal(chain, label, run, name) {
  const r = await run();
  const got = r.error ? `${r.error.name}${r.error.args?.length ? `(${r.error.args.join(', ')})` : ''}` : 'no revert';
  check(label, r.status === 0 && (!name || r.error?.name === name), `${got}, ${r.gasUsed} gas burned`);
  return r;
}

async function passage(label, run, detail) {
  const r = await run();
  check(label, r.status === 1, r.status === 1 ? `${detail ?? 'accepted'}, ${r.gasUsed} gas` : `reverted: ${r.error?.name}`);
  return r;
}

const { bps, prior } = readCap();
fs.rmSync(JOURNAL, { force: true });
console.log(`cap: ${prior.value}% non-audit fees = ${bps} basis points, from ${prior.celex} article ${prior.article}`);
console.log(`journal: ${JOURNAL}\n`);

const roster = loadRoster();
const chain = await TwinChain.open({ capBasisPoints: bps, roster, journalPath: JOURNAL });
check('deployed two contracts from artifacts', Boolean(chain.registryAddress && chain.agreementAddress),
  `registry ${chain.registryAddress.slice(0, 10)} agreement ${chain.agreementAddress.slice(0, 10)}`);

// --- who is allowed to speak ----------------------------------------------------
await refusal(chain, 'an agent key cannot register itself', () =>
  chain.write({ contract: 'AgentRegistry', actor: 'engagement-partner', fn: 'register', args: [
    '0x' + 'ab'.repeat(32), chain.keyFor('engagement-partner').hex, chain.keyFor('engagement-partner').hex, 'Self-appointed',
  ] }), 'NotOwner');

for (const agent of roster.agents) {
  await chain.register(agent);
}
check(`${roster.agents.length} roles registered`, (await chain.registeredCount()) === roster.agents.length, `registry holds ${await chain.registeredCount()} of ${roster.agents.length}`);
check('a role the roster never named is unknown', (await chain.known('review-partner')) === false, 'known() is false');

await refusal(chain, 'duplicate registration is refused', () => chain.register(roster.agents[0]), 'AlreadyRegistered');
await refusal(chain, 'a proposal with no terms is refused', () =>
  chain.write({ actor: 'engagement-partner', fn: 'propose', args: [
    sha3('engagement-partner'), sha3('materiality-reviewer'), '0x' + '00'.repeat(32), 1n, 0n, BigInt(GENESIS_AT + chain.tick + 3600),
  ] }), 'EmptyTerms');

// --- the cap the corpus derived -------------------------------------------------
const audit = 200_000n; // cents
const atCap = (audit * BigInt(bps)) / 10_000n;
await refusal(chain, 'non-audit work one cent over the derived cap', () =>
  chain.propose({ from: 'non-audit-assessor', to: 'engagement-partner', terms: 'tax compliance work alongside the statutory audit',
    amountCents: audit, nonAuditCents: atCap + 1n }), 'FeeCapBreached');
await passage('the same offer at exactly the cap', () =>
  chain.propose({ from: 'non-audit-assessor', to: 'engagement-partner', terms: 'tax compliance work alongside the statutory audit',
    amountCents: audit, nonAuditCents: atCap }), 'the cap is arithmetic, not a mood');

// Negative control for the cap itself: the identical transaction that was just refused goes
// through when the deployed constant is raised. That proves the refusal came from the number
// in the contract rather than from anything the caller did.
const loose = await TwinChain.open({
  capBasisPoints: 10_000, roster, journalPath: path.join(here, '.verify-loose.journal.jsonl'), reset: true,
});
for (const agent of roster.agents) await loose.register(agent);
const looseTry = await loose.propose({ from: 'non-audit-assessor', to: 'engagement-partner',
  terms: 'tax compliance work alongside the statutory audit', amountCents: audit, nonAuditCents: atCap + 1n });
check('control: a 100% cap lets the refused offer through', looseTry.status === 1,
  `same call, ${looseTry.status === 1 ? 'settled as Proposed' : 'still refused'}`);

// --- deadlines ------------------------------------------------------------------
await refusal(chain, 'a deadline already in the past', () =>
  chain.propose({ from: 'engagement-partner', to: 'materiality-reviewer', terms: 'review the materiality note',
    amountCents: 4_000n, nonAuditCents: 0n, horizonSec: -60 }), 'Expired');

const ticking = await chain.propose({ from: 'engagement-partner', to: 'materiality-reviewer',
  terms: 'review the materiality note', amountCents: 4_000n, nonAuditCents: 0n, horizonSec: 30 });
await chain.advance(120);
await refusal(chain, 'acceptance after the window closed', () =>
  chain.accept({ id: ticking.id, byRole: 'materiality-reviewer' }), 'Expired');

// --- the lifecycle --------------------------------------------------------------
const live = await chain.propose({ from: 'engagement-partner', to: 'quality-review-partner',
  terms: 'quality management review of the file before the opinion is signed', amountCents: 60_000n, nonAuditCents: 12_000n });
check('proposal recorded as Proposed', (await chain.agreement(live.id)).state === 'Proposed', `id ${live.id.slice(0, 14)}`);

await refusal(chain, 'settle before anyone accepted', () => chain.settle({ id: live.id, byRole: 'quality-review-partner' }), 'WrongState');
await refusal(chain, 'a stranger cannot accept for the counterparty', () =>
  chain.accept({ id: live.id, byRole: 'fraud-risk-assessor' }), 'NotCounterparty');
await refusal(chain, 'the proposer cannot accept on the other side', () =>
  chain.accept({ id: live.id, byRole: 'engagement-partner' }), 'NotCounterparty');
await passage('the named counterparty accepts', () => chain.accept({ id: live.id, byRole: 'quality-review-partner' }), 'Accepted');

await refusal(chain, 'attest before the review exists', () =>
  chain.attest({ id: live.id, byRole: 'quality-review-partner', evidence: 'the reviewer signs off first' }), 'NotProposer');
await refusal(chain, 'countersign before anything is attested', () =>
  chain.countersign({ id: live.id, role: 'quality-review-partner' }), 'WrongState');
await passage('the proposer attests the evidence hash', () =>
  chain.attest({ id: live.id, byRole: 'engagement-partner', evidence: 'audit file 2025, section 4, paragraph 12' }), 'Attested');

await refusal(chain, 'an agent cannot countersign for its own human', () =>
  chain.write({ actor: 'quality-review-partner', fn: 'countersign', args: [live.id] }), 'HumanRequired');
await refusal(chain, "another role's human cannot countersign either", () =>
  chain.write({ actor: 'human-engagement-partner', fn: 'countersign', args: [live.id] }), 'HumanRequired');
await refusal(chain, 'settle while the human signature is missing', () =>
  chain.settle({ id: live.id, byRole: 'quality-review-partner' }), 'HumanRequired');

// Negative control for the human gate: the same settle that was refused one line above goes
// through once the registered principal has countersigned.
const signedBy = await chain.countersign({ id: live.id, role: 'quality-review-partner' });
check('the registered principal countersigns', signedBy.status === 1,
  `signedBy ${(await chain.agreement(live.id)).signedBy?.slice(0, 14)}`);
await passage('control: the refused settle now passes', () => chain.settle({ id: live.id, byRole: 'quality-review-partner' }), 'Settled');
await refusal(chain, 'a settled agreement cannot be settled again', () =>
  chain.settle({ id: live.id, byRole: 'quality-review-partner' }), 'WrongState');

const settled = await chain.agreement(live.id);
check('evidence hash survived settlement', settled.evidenceHash?.length === 66, `${settled.evidenceHash?.slice(0, 18)}...`);

// --- refusals are kept, not deleted ---------------------------------------------
const doomed = await chain.propose({ from: 'fraud-risk-assessor', to: 'engagement-partner',
  terms: 'extend the fraud procedures without re-scoping', amountCents: 10_000n, nonAuditCents: 0n });
await refusal(chain, 'an unrelated role cannot dispute it', () =>
  chain.dispute({ id: doomed.id, byRole: 'tender-administrator', reason: 'not my engagement' }), 'NotCounterparty');
await passage('the counterparty rejects with a reason', () =>
  chain.reject({ id: doomed.id, byRole: 'engagement-partner', reason: 'scope creep without a re-let' }), 'Rejected');
const kept = await chain.agreement(doomed.id);
check('the rejection is still readable', kept.state === 'Rejected' && kept.reason.length > 0, `reason: ${kept.reason}`);

// --- a withdrawn role can be explained but cannot act ---------------------------
await passage('the firm withdraws a role', () => chain.withdraw({ role: 'tender-administrator' }), 'withdrawn');
check('a withdrawn role is no longer known', (await chain.known('tender-administrator')) === false, 'known() is false');
await refusal(chain, 'a withdrawn role cannot open a new agreement', () =>
  chain.propose({ from: 'tender-administrator', to: 'engagement-partner', terms: 're-let the tender', amountCents: 1n, nonAuditCents: 0n }),
  null);

// --- gas was really paid --------------------------------------------------------
const spent = BigInt(await chain.balanceOf('engagement-partner'));
const ceiling = 10n ** 20n;
check('an agent that transacted spent gas', spent < ceiling,
  `${(ceiling - spent).toString()} wei paid at 7 wei per gas`);

// --- the journal rebuilds the chain ---------------------------------------------
const before = await chain.agreements();
const rootBefore = await chain.stateRoot();
const reopened = await TwinChain.open({ capBasisPoints: bps, roster, journalPath: JOURNAL });
const after = await reopened.agreements();
check('replay rebuilt every agreement', before.length === after.length && after.length > 0,
  `${after.length} agreements, states ${[...new Set(after.map((a) => a.state))].join('/')}`);
check('replay reached the same state root', (await reopened.stateRoot()) === rootBefore, rootBefore.slice(0, 22));
check('replay rebuilt the same addresses', reopened.agreementAddress === chain.agreementAddress,
  reopened.agreementAddress.slice(0, 14));
const cursor = reopened.events.length;
check('the inbox replays as a message bus', reopened.inbox('quality-review-partner').length > 0,
  `${reopened.inbox('quality-review-partner').length} events for the reviewer, ${cursor} total`);

const failed = results.filter((r) => !r.pass);
console.log(`\n${results.length - failed.length}/${results.length} checks passed`);
if (failed.length) {
  for (const f of failed) console.log(`  failed: ${f.label} (${f.detail})`);
  process.exit(1);
}
console.log(`journal: ${fs.readFileSync(JOURNAL, 'utf8').split('\n').filter(Boolean).length} lines, replayed clean`);
