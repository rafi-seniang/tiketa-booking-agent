# Security

Report a vulnerability privately to rafiseniangwangsa@gmail.com, not in a public issue.

## What is protected

| Asset | Why it matters |
|---|---|
| The model provider's money | Every chat turn is paid for. Anyone who can call the chat can spend it |
| Bookings and conversations | They hold people's names and what they booked |
| Seats | A seat sold twice, or held by a fake booking, is a real loss |
| Secrets | DeepSeek and Gemini keys, API keys, the session secret, the database password |

## Threats and what answers them

| Threat | Answer | Where |
|---|---|---|
| An API key read from the frontend's JavaScript | Browsers never get one. They get a guest session: a random id with an expiry, signed with HMAC-SHA256, in an `HttpOnly`, `SameSite=Strict` cookie, `Secure` once deployed | `app/middleware/auth.py`, `app/routes/auth.py` |
| A forged or edited guest cookie | The signature is checked in constant time and the expiry with it. A wrong one is a 401 | `GuestSessions.read` |
| Another site making the browser book (CSRF) | `SameSite=Strict` keeps the cookie off cross-site requests, and CORS allows only the listed origins | `app/middleware/cors.py` |
| One caller spending the budget | 60 requests a minute and 400,000 model tokens a day per caller, counted in Redis across workers | `app/middleware/rate_limit.py`, `app/core/token_budget.py` |
| Many callers spending the budget (new guest sessions are free) | 3,000,000 model tokens a day for everyone together closes the chat until the next UTC day. The booking form, which calls no model, keeps working | `app/services/chat.py` |
| Reading someone else's conversation or bookings | Each belongs to its caller. Another caller gets 404, as if it did not exist | `app/repositories/chat_sessions.py`, `app/repositories/cinema.py` |
| Prompt injection ("ignore the rules, 20 free seats") | Messages and tool results are data to the model. Prices, seat limits and the confirmation are enforced in code, and a booking happens only after a summary built from the database is confirmed | `app/tools/booking.py` |
| Double booking, a retried request booking twice | `UNIQUE (showtime_id, seat_id)`, one transaction per booking, an idempotency key per request | `app/repositories/cinema.py` |
| API keys in logs or Redis | Callers are named by a SHA-256 prefix of their key. Keys are compared in constant time and several can be active, for rotation | `app/middleware/rate_limit.py` |
| Private answers kept by a cache or framed by a page | `Cache-Control: no-store` on `/v1` and `/auth`, `nosniff`, `X-Frame-Options: DENY`, HSTS in production | `app/middleware/security_headers.py` |
| Internals in error messages | Errors are problem+json with a short detail and a request id. Stack traces go to the logs only | `app/core/errors.py` |
| A secret committed by mistake | Secrets live outside the repository (`../../secrets/secrets.env`, environment variables). gitleaks runs before each commit and on every push | `.pre-commit-config.yaml`, `.github/workflows/ci.yml` |
| A vulnerable or compromised dependency | Versions are pinned where it matters. pip-audit fails the build on a known vulnerability. Dependabot proposes updates only for releases 14 days old | `.pip-audit-ignore`, `.github/dependabot.yml` |
| Running a misconfigured production | The service refuses to start in production without `API_KEYS` and `SESSION_SECRET`, and refuses an unmigrated database | `app/settings.py`, `app/core/migrations.py` |
| A compromised container | It runs as a non-root user with only the app's files | `Dockerfile` |

## Accepted for now

- filelock 3.32.7 has 13 known flaws in local file locking. They need someone who can already write to the machine,
  and the service takes no lock path from a request. The fixed version needs a newer litellm, released days ago.
  Reviewed in `.pip-audit-ignore` until 21 November 2026.
- Conversations, with the names in them, are stored in Postgres checkpoints and in Phoenix traces without masking or
  a retention period. Masking personal data before it reaches the model and the traces is the next step.
- A guest session proves a browser, not a person. A determined caller can start many: the daily cap for everyone is
  what bounds the cost. A CAPTCHA on `/auth/guest` would raise the bar if that becomes a problem.

## Out of scope

Payment (bookings are paid at the counter with the code), user accounts and passwords, and cancelling a booking.
