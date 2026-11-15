# Security

Report a vulnerability privately to rafiseniangwangsa@gmail.com, not in a public issue.

## What is protected

| Asset | Why it matters |
|---|---|
| The model provider's money | Every chat turn is paid for. Anyone who can call the chat can spend it |
| Conversations | They hold people's names and what they booked |
| The user's credentials | The agent passes a guest cookie or API key on to the booking service. Leaked, they book as that person |
| Secrets | DeepSeek and Gemini keys, the booking service key, the database password |

Seats, bookings and guest sessions belong to the booking service
([tiketa-app](https://github.com/rafi-seniang/tiketa-app)) and are covered by its SECURITY.md.

## Threats and what answers them

| Threat | Answer | Where |
|---|---|---|
| An API key read from the frontend's JavaScript | Browsers never get one. They call with the guest session cookie the booking service set: `HttpOnly`, `SameSite=Strict`, `Secure` once deployed | tiketa-app |
| A forged or edited guest cookie | The agent does not judge it. The booking service checks the signature and expiry on every request and answers 401 | `app/middleware/auth.py` |
| The agent booking as someone else, or for more than the user may | It holds no key that can book. Every tool call carries the credentials of the person in the conversation, and only those | `app/tools/booking.py`, `app/repositories/booking_api.py` |
| Credentials in checkpoints, logs or traces | They live in the turn's runtime context, which is not saved, and are hidden from `repr`. Only an API key header and the one cookie are read from a request | `app/schemas/cinema.py`, `app/middleware/auth.py` |
| Another site making the browser chat (CSRF) | `SameSite=Strict` keeps the cookie off cross-site requests, and CORS allows only the listed origins | `app/middleware/cors.py` |
| One caller spending the budget | 60 requests a minute and 400,000 model tokens a day per caller, counted in Redis across workers | `app/middleware/rate_limit.py`, `app/core/token_budget.py` |
| Many callers spending the budget (new guest sessions are free) | 3,000,000 model tokens a day for everyone together closes the chat until the next UTC day. The seat map, which calls no model, keeps booking | `app/services/chat.py` |
| Reading someone else's conversation | Each belongs to its caller. Another caller gets 404, as if it did not exist | `app/repositories/chat_sessions.py` |
| Prompt injection ("ignore the rules, 20 free seats") | Messages and tool results are data to the model. Prices, seat limits and the confirmation are enforced in code and by the booking service, and a booking happens only after a summary priced by that service is confirmed | `app/tools/booking.py` |
| A retried or resumed tool call booking twice | One idempotency key per tool call of a conversation. The booking service returns the first booking | `app/repositories/booking_api.py` |
| A booking service that is down answered from memory | Never. Requests get 503 and the turn ends with an error | `app/repositories/booking_api.py` |
| Private answers kept by a cache or framed by a page | `Cache-Control: no-store` on `/v1`, `nosniff`, `X-Frame-Options: DENY`, HSTS in production | `app/middleware/security_headers.py` |
| Internals in error messages | Errors are problem+json with a short detail and a request id. Stack traces go to the logs only | `app/core/errors.py` |
| A secret committed by mistake | Secrets live outside the repository (`../../secrets/secrets.env`, environment variables). gitleaks runs before each commit and on every push | `.pre-commit-config.yaml`, `.github/workflows/ci.yml` |
| A vulnerable or compromised dependency | Versions are pinned where it matters. pip-audit fails the build on a known vulnerability. Dependabot proposes updates only for releases 14 days old | `.pip-audit-ignore`, `.github/dependabot.yml` |
| Running a misconfigured production | The service refuses to start in production without `BOOKING_API_KEY`, without the booking service, or on an unmigrated database | `app/settings.py`, `app/core/lifespan.py`, `app/core/migrations.py` |
| A compromised container | It runs as a non-root user with only the app's files | `Dockerfile` |

## Accepted for now

- filelock 3.32.7 has 13 known flaws in local file locking. They need someone who can already write to the machine,
  and the service takes no lock path from a request. The fixed version needs a newer litellm, released days ago.
  Reviewed in `.pip-audit-ignore` until 21 November 2026.
- Conversations, with the names in them, are stored in Postgres checkpoints and in Phoenix traces without masking or
  a retention period. Masking personal data before it reaches the model and the traces is the next step.
- A guest session proves a browser, not a person. A determined caller can start many: the daily cap for everyone is
  what bounds the cost. A CAPTCHA on the booking service's `/auth/guest` would raise the bar if that becomes a problem.
- With `LLM_GATEWAY_URL` set, conversations pass through that gateway. It has not been run live with this agent.

## Out of scope

Payment (bookings are paid at the counter with the code), user accounts and passwords, and cancelling a booking.
Seats and bookings themselves: see tiketa-app.
