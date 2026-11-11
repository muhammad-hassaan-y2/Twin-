/**
 * The audit firm's card: who is hired, on what numbers, and what the contract made
 * of what they agreed to.
 *
 * This panel is the only place the subsystem is reachable from the table, so it keeps
 * to the rule the rest of the app keeps: every figure on it was counted by the backend
 * and copied here, and a state that means "there is no contract" says so in words
 * instead of leaving an empty row where an agreement would have been.
 */

import { UIKit, createSystem, type UIKitMLAsset } from '@iwsdk/core';
import { twin } from './controller.js';
import type { FirmBrief, FirmHealth, FirmReview, OpenedAgreement } from './client.js';
import { FirmPanel } from './components.js';

type FirmState = 'contract' | 'none' | 'asking' | 'offline';

/** The same colourblind-safe set the other cards use; the chip always carries the word. */
const SKIN: Record<FirmState, { band: string; chip: string; edge: string }> = {
  contract: { band: '#12222f', chip: '#2e7dd1', edge: '#2e7dd1' },
  none: { band: '#1a222c', chip: '#9aa5b1', edge: '#33414f' },
  asking: { band: '#2b2412', chip: '#ffd166', edge: '#ffd166' },
  offline: { band: '#2a1813', chip: '#e4572e', edge: '#e4572e' },
};

const WORD: Record<FirmState, string> = {
  contract: 'on contract',
  none: 'no contract',
  asking: 'asking',
  offline: 'offline',
};

interface Paint {
  text?: string;
  color?: string;
  backgroundColor?: string;
  borderColor?: string;
  display?: 'none' | 'flex' | 'contents';
}

/**
 * Who wrote one judgement, in the few words a caption has. The backend's route is a whole
 * sentence about what happened ("rules (muse refused: ...)") because that is what a log
 * wants; a card wants the shorter thing - the model read the law, or the firm's own rule
 * stood in for it.
 */
function spoke(route: string): string {
  if (route.startsWith('rules (muse refused')) return 'rules, muse refused';
  if (route.startsWith('rules (muse did not answer')) return 'rules, muse did not answer';
  if (route.startsWith('rules (the harvested text')) return 'rules, no law text on this machine';
  if (route === 'rules') return 'rules';
  return route.includes(':') ? route.slice(0, route.indexOf(':')) : 'the model';
}

/** Whether the firm's own rule answered this judgement rather than an endpoint. */
function stoodIn(route: string): boolean {
  return route.startsWith('rules');
}

/** One way to write a field, so a missing element is a no-op rather than a thrown frame. */
function put(panel: UIKitMLAsset | undefined, id: string, props: Paint): void {
  panel?.getElementById<UIKit.Text>(id)?.setProperties(props);
}

function joined(parts: Array<string | undefined>): string {
  return parts.filter((part) => part !== undefined && part !== '').join('  -  ');
}

function stateOf(brief: FirmBrief | null, health: FirmHealth | null): FirmState {
  if (twin.offline) return 'offline';
  if (twin.firmBusy) return 'asking';
  return (health?.on_chain ?? brief?.chain.on_chain ?? false) ? 'contract' : 'none';
}

export class TwinFirmSystem extends createSystem({
  boards: { required: [FirmPanel] },
}) {
  private panel?: UIKitMLAsset;
  private stopping: Array<() => void> = [];

  init(): void {
    this.panel = this.world.getSceneObject<UIKitMLAsset>('firm');
    const ask = this.panel?.getElementById<UIKit.Text>('Btn-firm');
    if (ask) {
      const onClick = () => {
        if (!twin.firmBusy) void twin.askFirm();
      };
      ask.addEventListener('click', onClick);
      this.stopping.push(() => ask.removeEventListener('click', onClick));
    }
    this.stopping.push(twin.subscribe(() => this.redraw()));
    this.redraw();
  }

  dispose(): void {
    for (const stop of this.stopping) stop();
  }

  /**
   * One redraw path. The counts go onto the component and the sentences are written
   * from the same values in the same frame, so the card and anything else reading
   * `FirmPanel` cannot disagree about how many agreements there were.
   */
  private redraw(): void {
    const brief = twin.firm;
    const review = twin.firmReview;
    const health = twin.firmHealth;
    const state = stateOf(brief, health);
    const opened = review?.agreements ?? [];
    const attested = opened.filter((agreement) => agreement.state === 'Attested');
    const refused = opened.filter((agreement) => agreement.state === 'refused');
    const onChain = state === 'contract';

    for (const entity of this.queries.boards.entities) {
      entity.setValue(FirmPanel, 'onChain', onChain);
      entity.setValue(FirmPanel, 'hired', health?.hired ?? 0);
      entity.setValue(FirmPanel, 'refusedRoles', health?.refused ?? 0);
      entity.setValue(FirmPanel, 'derived', brief ? brief.thresholds.filter((card) => card.state === 'calibrated').length : 0);
      entity.setValue(FirmPanel, 'figures', brief?.thresholds.length ?? 0);
      entity.setValue(FirmPanel, 'engagement', twin.firmAsked);
      entity.setValue(FirmPanel, 'engagements', brief?.engagements ?? 0);
      entity.setValue(FirmPanel, 'opened', attested.length);
      entity.setValue(FirmPanel, 'refusedWrites', refused.length);
      entity.setValue(FirmPanel, 'waiting', review?.waiting_on_humans.length ?? 0);
    }

    const skin = SKIN[state];
    const reason = this.reason(refused, review, brief, state);
    put(this.panel, 'FirmCard', { borderColor: skin.edge });
    put(this.panel, 'FirmState', { text: WORD[state], backgroundColor: skin.chip });
    put(this.panel, 'FirmRoles', { text: this.roles(brief, health, state) });
    put(this.panel, 'FirmCorpus', { text: this.corpus(brief) });
    put(this.panel, 'FirmClient', {
      text: review
        ? joined([review.client, `engagement ${twin.firmAsked + 1} of ${brief?.engagements ?? 0}`])
        : 'Nothing has been put to the firm yet.',
    });
    put(this.panel, 'FirmTally', { text: this.tally(review), display: review ? 'flex' : 'none' });
    put(this.panel, 'FirmHeadline', { text: this.headline(review) });
    put(this.panel, 'FirmAgreements', { text: this.agreements(attested, refused, review), display: review ? 'flex' : 'none' });
    put(this.panel, 'FirmReason', { text: reason, display: reason ? 'flex' : 'none' });
    put(this.panel, 'FirmNote', { text: this.who(review) });
    put(this.panel, 'Btn-firm', { text: twin.firmBusy ? 'Asking the firm...' : 'Put the next engagement to the firm' });
  }

  /** The roster is a fact about a chain, so it is only claimed as hired once one answered. */
  private roles(brief: FirmBrief | null, health: FirmHealth | null, state: FirmState): string {
    const named = brief?.roles.length ?? 0;
    if (state === 'offline') return 'the twin is not answering';
    if (state === 'none' || !named) return `${named} roles named, none hired - no contract was reached`;
    const refusedRoles = health?.refused ?? 0;
    return joined([
      `${health?.hired ?? 0} of ${named} roles hired`,
      refusedRoles > 0 ? `${refusedRoles} refused` : '',
    ]);
  }

  /**
   * What the firm is quoting, and how far away it read it from. The article and
   * statute counts come out of the harvest manifest, so this line is provenance
   * rather than a claim that the numbers look official.
   */
  private corpus(brief: FirmBrief | null): string {
    if (!brief) return 'no corpus read yet';
    const derived = brief.thresholds.filter((card) => card.state === 'calibrated').length;
    const from = brief.provenance.derived_from as { articles?: number; statutes?: number };
    const source = from.articles
      ? `out of ${from.articles} articles in ${from.statutes ?? 0} statutes`
      : 'out of a corpus that does not say how big it is';
    return joined([
      `${derived} of ${brief.thresholds.length} figures derived ${source}`,
      brief.uncalibrated.length > 0 ? `${brief.uncalibrated.length} left uncalibrated` : '',
    ]);
  }

  private tally(review: FirmReview | null): string {
    if (!review) return '';
    return joined([
      `clear ${review.counts.clear ?? 0}`,
      `hold ${review.counts.hold ?? 0}`,
      `breach ${review.counts.breach ?? 0}`,
      `silent ${review.counts.silent ?? 0}`,
    ]);
  }

  /**
   * One sentence, chosen by what it would cost to leave it out: a finding that binds
   * somebody is the one a person has to sign, so it leads. A breach leads when nothing
   * binds, and a silent answer leads when there is neither.
   *
   * The byline names who wrote it, because nobody reading a sentence can tell a model's
   * finding from one the firm always knew, and the person in front of the card is being
   * asked to trust one of the two.
   */
  private headline(review: FirmReview | null): string {
    if (!review) return 'Nothing has been put to the firm.';
    const first = review.findings.find((finding) => finding.binding)
      ?? review.findings.find((finding) => finding.verdict === 'breach')
      ?? review.findings.find((finding) => finding.verdict === 'silent')
      ?? review.findings[0];
    return `${first.role} (${spoke(first.route)}): ${first.sentence}`;
  }

  /**
   * How the answers divide between the model and the rules, counted from each
   * finding's own route rather than from one route for the engagement - one ask can be
   * refused and the next accepted, and a card that said "muse" over both would be
   * reporting the last request rather than the eighteen answers.
   */
  private who(review: FirmReview | null): string {
    if (!review) return '';
    const decided = review.findings.filter((finding) => !stoodIn(finding.route)).length;
    if (!decided) return 'the words above came from the rules route';
    const fellBack = review.findings.filter((finding) => finding.route.startsWith('rules (')).length;
    return joined([
      `${decided} of ${review.findings.length} judgements the model read out of the law text`,
      fellBack ? `${fellBack} fell back to the rules` : '',
    ]);
  }

  private agreements(attested: OpenedAgreement[], refused: OpenedAgreement[], review: FirmReview | null): string {
    if (!review) return '';
    return joined([
      `${attested.length} agreement(s) on the contract`,
      `${review.waiting_on_humans.length} waiting on a signature`,
      refused.length > 0 ? `${refused.length} refused` : '',
    ]);
  }

  /**
   * Why the number above is the number it is. Off a chain that is this app's own
   * reason; on one, it is the name the bytecode gave when it said no, which is the
   * only account of a refusal that is not this program's opinion of itself.
   */
  private reason(refused: OpenedAgreement[], review: FirmReview | null, brief: FirmBrief | null,
    state: FirmState): string {
    if (state === 'offline' && !brief) return 'the firm was never reached';
    if (refused.length > 0) {
      return joined([
        `${refused.length} offer(s) the contract would not record`,
        refused[0].steps.find((step) => !step.ok)?.refused ?? 'no reason came back',
      ]);
    }
    if (review?.why_no_agreements) return review.why_no_agreements;
    if (state !== 'none') return '';
    return `no contract: ${review?.chain.why || brief?.chain.why || 'nobody said where to look'}`;
  }
}
