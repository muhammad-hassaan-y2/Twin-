# PayPal AI Hackathon — Oversight Twin

**Project combining two modular systems:**
1. **`tabletop-twin`**: PayPal Orders v2 execution engine with an explicit
   idempotency-keyed payment state machine (PENDING -> COMPLETED / FAILED / UNKNOWN).
2. **`swarm-oversight`**: Multi-agent AI safety monitor that intercepts spend
   requests across autonomous agents to prevent threshold-evasion attacks
   (split payments, multi-hop relays, payee alias spoofing).

The **`oversight_twin`** wrapper places the multi-agent guard inline in the
PayPal execution pipeline before `charge()` hits the PayPal Sandbox API.

---

## Architecture Diagram

```mermaid
graph TD
    A[Client] -->|POST /api/v1/agents/charge| B(FastAPI: app/main.py)
    B -->|Session.observe(Action)| C(Oversight Twin: app/oversight_twin.py)
    C -->|Monitor.review()| D[swarm-oversight Monitor]
    D -->|Flags: over_limit / relay / split| C
    C -- MoneyNotMoved -->|HTTP 402 + FAILED| B
    C -- Pass -->|Route to PayPal| E(PayPal Client: app/paypal_client.py)
    E -->|POST /v2/checkout/orders| F[PayPal Sandbox API]
    F -->|Order ID + status| E
    E -->|ORDER details + COMPLETED| B
    B -->|JSON response| A

    G[GET /api/v1/swarm/metrics] -->|Aggregate stats| B
    B -->|JSON metrics| G
```

---

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/v1/agents/charge` | Run the oversight guard; if clean, create a PayPal order. Returns `200 COMPLETED`, `402 FAILED`, or `500 UNKNOWN`. |
| `GET` | `/api/v1/swarm/metrics` | Return aggregate swarm metrics: total spend, active mandates, caught attack attempts. |

---

## Endpoint: POST /api/v1/agents/charge

**Request body:**

| Field | Type | Description |
|-------|------|-------------|
| `agent_id` | `str` | Identifier of the agent initiating the charge. |
| `payee_id` | `str` | Identifier of the payee receiving the funds. |
| `amount_cents` | `int` | Payment amount in **integer cents** (e.g., `1500` → `"15.00"` USD). |
| `mandate_cap_cents` | `int` | Per-agent spending cap in cents. |

**Success response (200):**

```json
{
  "state": "COMPLETED",
  "reason": null,
  "paypal_order_id": "ORDER-123456789",
  "paypal_order_json": { ... },
  "payee_id": "payee-01",
  "amount_cents": 1500,
  "amount_usd": "15.00"
}
```

**Cap‑breach response (402):**

```json
{
  "state": "FAILED",
  "reason": "Spending cap breached"
}
```

**PayPal/network error response (500/UNKNOWN):**

```json
{
  "state": "UNKNOWN",
  "reason": "PayPal request failed — see UNKNOWN state for reconciliation",
  "detail": "..."
}
```

---

## Endpoint: GET /api/v1/swarm/metrics

**Response:**

```json
{
  "total_spend_cents": 45000,
  "active_mandates": {
    "agent-01": 100000,
    "agent-02": 75000
  },
  "caught_attack_attempts": 3,
  "session_state": "PENDING"
}
```

---

## Installation & Running

### 1. Clone / ensure the project structure

```
L:swarmoversight/
├─ Twin/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ oversight_twin.py
│  │  ├─ paypal_client.py
│  │  └─ model.py (if needed)
│  ├─ tests/
│  │  └─ test_hackathon_submission.py
│  ├─ Dockerfile
│  ├─ docker-compose.yml
│  └─ README.md
└─ swarm-oversight/           # pre-existing submodule
   ├─ pyproject.toml
   ├─ swarm_oversight/
   │  ├─ __init__.py
   │  ├─ monitor.py
   │  ├─ model.py
   │  ├─ scenarios.py
   │  └─ harness.py
```

### 2. Install Python dependencies

From the `Twin/` directory:

```bash
python -m venv .venv
source .venv/bin/activate  # .venv\Scripts\activate on Windows
pip install fastapi uvicorn httpx pytest pytest-requests
```

The `swarm-oversight` submodule is already present and its dependencies are
minimal (standard library only).

### 3. Environment variables

Create a `.env` file in the `Twin/` directory:

```env
# PayPal Sandbox credentials (required for real API calls)
PAYPAL_CLIENT_ID=your-sandbox-client-id
PAYPAL_SECRET=your-sandbox-secret

# Optional: override monitor limits if desired
# (the defaults are per_agent=100_000, per_payee=200_000, window=10, etc.)
```

If `PAYPAL_CLIENT_ID` and `PAYPAL_SECRET` are not set the app will short‑circuit
the PayPal call and return `state: UNKNOWN` — this allows you to test the
oversight guard (`402 FAILED`) without needing real credentials.

### 4. Start the service

Using `docker-compose` (recommended):

```bash
docker-compose up --build api
```

Or directly with uvicorn:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000`.

### 5. Test the endpoints

```bash
# 1) Standard success (guard passes, mocked PayPal returns ORDER ID)
curl -X POST "http://localhost:8000/api/v1/agents/charge" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"agent-01","payee_id":"payee-01","amount_cents":5000,"mandate_cap_cents":100000}'

# 2) Single agent over cap → 402 FAILED (guard blocks, no PayPal call)
curl -X POST "http://localhost:8000/api/v1/agents/charge" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":"agent-01","payee_id":"payee-01","amount_cents":150000,"mandate_cap_cents":100000}'

# 3) Swarm metrics
curl -s "http://localhost:8000/api/v1/swarm/metrics"
```

---

## Test Suite

Run the automated test suite:

```bash
pytest tests/test_hackathon_submission.py -v
```

**Covered scenarios:**

| # | Scenario | Expected |
|---|----------|----------|
| 1 | **Standard Success** — single agent under mandate → HTTP 200, COMPLETED | ✅ |
| 2 | **Negative Control 1** — single agent over cap → HTTP 402, FAILED (zero PayPal call) | ✅ |
| 3 | **Negative Control 2** — collusive multi-agent split attack (A($40)+B($40)+C($30) vs cap $100) → Agent C throws `MoneyNotMoved`, state `FAILED`, zero HTTP calls to PayPal | ✅ |

Each test isolates the session state and mocks the PayPal client so the suite
runs deterministically without network credentials.

---

## Docker

The `Dockerfile` (below) installs the app and its dependencies into a minimal
container. The `docker-compose.yml` above orchestrates the service and provides
a dummy PayPal mock for local development without credentials.

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Install deps
COPY Twin/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the app code
COPY Twin/app/ /app/

# Copy the shared swarm-oversight package
COPY Twin/swarm-oversight/ /app/swarm-oversight/

# Default env (override at runtime)
ENV PAYPAL_CLIENT_ID="" \
    PAYPAL_SECRET=""

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Requirements (Twin/requirements.txt)

```
fastapi
uvicorn[standard]
httpx
pytest
```

---

## Project Structure (Twin/)

```
Twin/
├─ app/
│  ├─ __init__.py
│  ├─ main.py          # FastAPI endpoints
│  ├─ oversight_twin.py # Guard + Session + MoneyNotMoved
│  ├─ paypal_client.py # PayPal Orders v2 client
│  └─ model.py         # Shared dataclasses (Action, PaymentState)
├─ tests/
│  └─ test_hackathon_submission.py
├─ docker-compose.yml
├─ Dockerfile
├─ README.md
└─ .env.example          # see environment variables section above
```