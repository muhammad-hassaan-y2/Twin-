/**
 * The only place the client talks to the twin.
 *
 * Every number that reaches the table comes from here. The client never does
 * cash arithmetic: it asks, it receives a scene description, it draws.
 */

export interface Stone {
  id: string;
  event_id: string;
  label: string;
  kind: string;
  day: number;
  country: string;
  amount_dollars: number;
  height: number;
  below_surface: boolean;
  cancellable: boolean;
}

export interface Boat {
  id: string;
  label: string;
  day: number;
  amount_dollars: number;
  fog: number;
  worst_lag_days: number;
  stuck: boolean;
}

export interface ReliabilityBin {
  bin: string;
  n: number;
  predicted: number;
  observed: number;
  gap: number;
}

export interface Branch {
  key: string;
  label: string;
  min_balance_dollars: number;
  min_balance_change_dollars: number;
  cost_change_dollars: number;
  dry_probability_change: number;
  shortfall_day_change: number | null;
  verdict: string;
}

/** What a forked world cost or bought, beside the one already on the table. */
export interface Fork {
  branch: string;
  label: string;
  delta: {
    key: string;
    label: string;
    min_balance_change_dollars: number;
    cost_change_dollars: number;
    dry_probability_change: number;
    shortfall_day_change: number | null;
    verdict: string;
  };
}

export interface Payment {
  action_id: string;
  state: string;
  recipient: string;
  country: string;
  amount_dollars: number;
  currency: string;
  rail: string;
  fee_dollars: number;
  attempt: number;
  idempotency_key: string;
  verified: boolean;
}

/**
 * The twin's own week, folded from the trail of decisions it has already made.
 *
 * Every figure here is a count of ledger rows, not a model's recollection, so the
 * panel can say "3 asks this week" and mean it. A `said` sentence is included
 * because the same fold is what the summary endpoint reads.
 */
export interface Memory {
  window_days: number;
  asks_this_week: number;
  moves_this_week: number;
  settled_cents_this_week: number;
  refused_this_week: number;
  held_gestures_refused_this_week: number;
  unresolved_payments: number;
  asks_today: number;
  moves_today: number;
  top_denied_rule: string;
  said: string;
}

export interface ScenePayload {
  meta: {
    persona: string;
    day: number;
    horizon_days: number;
    runs: number;
    seed: number;
    currency: string;
    country: string;
    rail: string;
    generated_by: string;
  };
  palette: Record<string, string>;
  river: {
    p10_dollars: number[];
    p50_dollars: number[];
    p90_dollars: number[];
    dry_probability: number[];
    pinch_day: number;
  };
  stones: Stone[];
  boats: Boat[];
  lake: { feed_event_ids: string[]; depth_dollars: number };
  garden: {
    stage: number;
    accuracy_pct: number;
    brier: number;
    resolved: number;
    open: number;
    reliability: ReliabilityBin[];
  };
  branches: Branch[];
  payments: Payment[];
  memory: Memory;
  focus: string;
  twin: { look_at: string; speak: string };
}

export interface Caption {
  step: string;
  text: string;
  target: string;
}

export interface Verdict {
  action_id: string;
  verb: string;
  amount_cents: number;
  amount_dollars: number;
  recipient: string;
  country: string;
  currency: string;
  rail: string;
  fee_dollars: number;
  verdict: 'allow' | 'require_approval' | 'deny';
  reason: string;
  rule: string;
  state: string;
  idempotency_key?: string;
  error?: string;
}

/**
 * What the table shows while it waits for a hand: enough to say what would move,
 * where it would go, and which rule stopped it. Filled from a verdict when this
 * browser proposed the action, and from an open payment record when the twin did.
 */
export interface Held {
  action_id: string;
  verb: string;
  recipient: string;
  country: string;
  currency: string;
  amount_dollars: number;
  rail: string;
  fee_dollars: number;
  rule: string;
  reason: string;
}

/**
 * One model endpoint, described from the environment alone — no request was made
 * to produce this. `supplied_by` names the variables the operator set and
 * `assumed` the fields that fell back to a published default, which is how a table
 * tells an endpoint it was configured with from one it is guessing at.
 */
export interface ModelRoute {
  provider: string;
  model: string;
  host: string;
  endpoint: string;
  timeout_sec: number;
  supplied_by: Record<string, string>;
  assumed: string[];
  preferred: boolean;
}

/**
 * The audit firm, as the backend describes it.
 *
 * Every figure on these two types is one the corpus was read out of or a review
 * computed, so the panel has nothing to round, add up or work out for itself —
 * least of all the number of roles it hired, which is a fact about a chain.
 */
export interface FirmRoute {
  route: string;
  why: string;
}

export interface FirmChain {
  on_chain: boolean;
  why: string;
}

export interface FirmBrief {
  roles: { role: string; title: string; principal: string }[];
  engagements: number;
  thresholds: { name: string; value: number | null; state: string; celex: string; article: string }[];
  uncalibrated: string[];
  provenance: { derived_from: Record<string, unknown>; corpus_dir: string };
  model_route: FirmRoute;
  chain: FirmChain;
}

/** One agent's answer, in the shape the review endpoint returns it. */
export interface Finding {
  role: string;
  to_role: string;
  asks: string;
  verdict: string;
  sentence: string;
  numbers: Record<string, unknown>;
  cite: Record<string, string>;
  route: string;
  binding: boolean;
}

/** What the contract made of one attempt to send a message. */
export interface OpenedAgreement {
  role: string;
  to_role: string;
  verdict: string;
  agreement: string;
  state: string;
  steps: { verb: string; ok: boolean; state: string; refused: string }[];
}

export interface FirmReview {
  client: string;
  route: FirmRoute;
  findings: Finding[];
  counts: Record<string, number>;
  agreements: OpenedAgreement[];
  waiting_on_humans: unknown[];
  chain: FirmChain;
  why_no_agreements?: string;
}

/** How the boot probe found the firm, said without asking the sidecar again. */
export interface FirmHealth {
  on_chain: boolean;
  why: string;
  hired: number;
  refused: number;
}

const BASE = (import.meta.env.VITE_TWIN_API ?? 'http://localhost:8000').replace(/\/+$/u, '');

/** A hold shorter than this is not an approval. It is an accident. */
export const APPROVAL_HOLD_SEC = 1;
export const APPROVAL_GESTURE = `pinch_hold_${APPROVAL_HOLD_SEC}s`;
/** The same hold, made with a pointer on a screen instead of a hand in a headset. */
export const POINTER_GESTURE = `pointer_hold_${APPROVAL_HOLD_SEC}s`;

export interface Account {
  token: string;
  user_id: string;
  name: string;
}

const TOKEN_KEY = 'twin.token';
const NAME_KEY = 'twin.account';
const DEVICE_KEY = 'twin.device';

/**
 * Which world this browser is looking at.
 *
 * A token names an account once somebody has signed one in. Before that the device
 * key does the same job: the twin opens a world for a device id it has never seen,
 * so the table is alive on the first fetch and no signup stands in front of it.
 * A request with neither is still refused — somebody has to say whose ledger moves.
 */
export const session = {
  get token(): string | null {
    return localStorage.getItem(TOKEN_KEY);
  },

  get name(): string {
    return localStorage.getItem(NAME_KEY) ?? '';
  },

  set(account: Account | null): void {
    if (account) {
      localStorage.setItem(TOKEN_KEY, account.token);
      localStorage.setItem(NAME_KEY, account.name);
      return;
    }
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(NAME_KEY);
  },

  /** Thirty-two random bytes, kept so a reload rejoins this world instead of opening another. */
  device(): string {
    const saved = localStorage.getItem(DEVICE_KEY);
    // Anything that is not a device id — including the credentials an older build
    // kept in this slot — is replaced, because a bad id is refused by the twin and
    // the table would then draw nothing at all.
    if (saved && /^[0-9a-f]{64}$/.test(saved)) return saved;
    const bytes = new Uint8Array(32);
    crypto.getRandomValues(bytes);
    const id = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
    localStorage.setItem(DEVICE_KEY, id);
    return id;
  },
};

function headers(extra: Record<string, string> = {}): Record<string, string> {
  const token = session.token;
  return { 'X-Twin-Device': session.device(), ...extra, ...(token ? { Authorization: `Bearer ${token}` } : {}) };
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, init);
  if (!response.ok) {
    if (response.status === 401 && session.token) session.set(null);
    throw new Error(`${path} -> ${response.status}`);
  }
  return (await response.json()) as T;
}

async function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(body ?? {}),
  });
}

async function get<T>(path: string): Promise<T> {
  return request<T>(path, { method: 'GET', headers: headers() });
}

/** What one ask returns: the words, what they were computed from, and the scene. */
export interface AskAnswer {
  said: string;
  focus: string;
  route: string;
  narration_route: string;
  scene: ScenePayload;
}

/** One `event:`/`data:` pair, or null when the chunk is punctuation rather than a frame. */
function parseFrame(chunk: string): { event: string; data: Record<string, unknown> } | null {
  let event = '';
  let data = '';
  for (const line of chunk.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    if (line.startsWith('data:')) data += line.slice(5).trim();
  }
  if (!event || !data) return null;
  try {
    const payload = JSON.parse(data) as Record<string, unknown>;
    return { event, data: payload };
  } catch {
    return null;
  }
}

/**
 * The same ask, read off a live stream.
 *
 * `onPiece` sees each sentence the moment the twin has checked it — never a raw
 * token, never a half-formed figure — and the promise resolves with the whole
 * answer, which is the version the table writes down and the one to display.
 */
async function askStream(intent: string, onPiece: (text: string) => void): Promise<AskAnswer> {
  const response = await fetch(`${BASE}/v1/ask/stream`, {
    method: 'POST',
    headers: headers({ 'Content-Type': 'application/json', Accept: 'text/event-stream' }),
    body: JSON.stringify({ intent }),
  });
  if (!response.ok) {
    if (response.status === 401 && session.token) session.set(null);
    throw new Error('/v1/ask/stream -> ' + response.status);
  }
  const reader = response.body?.getReader();
  if (!reader) throw new Error('/v1/ask/stream answered with no body to read');

  const decoder = new TextDecoder();
  let buffer = '';
  let answer: AskAnswer | null = null;
  let refused = '';

  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let cut = buffer.indexOf('\n\n');
    while (cut >= 0) {
      const frame = parseFrame(buffer.slice(0, cut));
      buffer = buffer.slice(cut + 2);
      cut = buffer.indexOf('\n\n');
      if (!frame) continue;
      if (frame.event === 'delta') onPiece(String(frame.data['text'] ?? ''));
      if (frame.event === 'failed') refused = String(frame.data['error'] ?? 'the twin could not answer');
      if (frame.event === 'done') answer = frame.data as unknown as AskAnswer;
    }
  }
  if (refused) throw new Error(refused);
  if (!answer) throw new Error('/v1/ask/stream ended before the answer arrived');
  return answer;
}

export const twinApi = {
  /** Gives this device's existing world an email and a password, or opens a fresh one. */
  signup: (email: string, password: string, name = '') => post<Account>('/v1/signup', { email, name, password }),
  login: (email: string, password: string) => post<Account>('/v1/login', { email, password }),
  /** Revokes the token only. The device behind it still opens the same table. */
  logout: () => post<{ signed_out: boolean }>('/v1/logout', {}),
  me: () => get<{
    user_id: string;
    name: string;
    signed_in: boolean;
    persona: string;
    day: number;
    horizon_days: number;
    events: number;
  }>('/v1/me'),
  world: () => get<ScenePayload>('/v1/world'),
  health: () => get<{
    ok: boolean;
    persona: string;
    planner: string;
    route: string;
    route_is_measured: boolean;
    model_providers: string[];
    model_routes: ModelRoute[];
    heartbeat_steps: string[];
    heartbeat_unwired: string[];
    paypal_configured: boolean;
    accounts: boolean;
    audit: FirmHealth;
  }>('/v1/health'),
  persona: () => get<{
    name: string;
    voice: string;
    prohibitions: string[];
    loop: string[];
    heartbeat: { slug: string; index: number; title: string; body: string }[];
  }>('/v1/persona'),
  scrub: (day: number) => post<{ day: number; scene: ScenePayload }>('/v1/scrub', { day }),
  pull: (event_id: string) => post<{ fork: Fork; scene: ScenePayload }>('/v1/pull', { event_id }),
  tick: (days: number, final_of_day: boolean) =>
    post<{ day: number; captions: Caption[]; scene: ScenePayload }>('/v1/tick', { days, final_of_day }),
  askStream,
  propose: (calls: unknown[]) => post<{ results: Record<string, unknown>[]; scene: ScenePayload }>('/v1/tools', { calls }),
  approve: (action_id: string, gesture: string) =>
    post<{ action_id: string; state: string; error?: string }>('/v1/approve', { action_id, gesture }),
  /** Closing the panel is not a decision. This is the one that says no in the ledger. */
  reject: (action_id: string) =>
    post<{ action_id: string; state: string }>('/v1/reject', {
      action_id,
      reviewer: 'the hand at the table',
      reason: 'refused from the panel',
    }),
  reconcile: (action_id: string) => post<{ action_id: string; state: string }>('/v1/reconcile', { action_id }),

  /**
   * The audit firm. `brief` needs no chain and writes nothing; `review` is the one
   * call that can put an agreement on a contract, so it is only ever made from a
   * button a hand chose to press.
   */
  firm: () => get<FirmBrief>('/v1/firm'),
  firmReview: (engagement: number) => post<FirmReview>('/v1/firm/review', { engagement }),
  firmAgreements: () => get<{ agreements: { id: string; state: string }[]; waiting_on_humans: unknown[]; chain: FirmChain }>(
    '/v1/firm/agreements'),
};
