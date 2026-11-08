# Tiketa

A cinema booking assistant. People chat in Indonesian or English ("dune besok malem berdua, kursi tengah"), the agent
finds showtimes, reads the seat map and prepares the booking, and nothing is booked until the user confirms a summary
the server built from the database.

The second version of a 2025 portfolio project. v1 was a hand-written LangGraph loop on Gemini with a Gradio UI and
the conversation in a Python dict. v2 keeps the idea (one agent loop, separate read and write tools) and moves every
rule that must hold into code: typed booking state, a confirmation that pauses the graph, database constraints, durable
conversations and measured behaviour.

## How a booking flows

```mermaid
flowchart LR
    U[User message] --> A[Agent loop<br>create_agent + middleware]
    A -->|read| R[find_showtimes<br>get_movie_details<br>get_seat_map]
    A -->|change| D[update_booking<br>checks every value<br>against the database]
    D --> S[(Draft in graph state)]
    A -->|nothing missing| B[book_tickets]
    B --> I{{interrupt: summary<br>priced from the database}}
    I -->|Confirm, or a typed yes<br>read by a model| T[(One transaction<br>UNIQUE showtime + seat<br>idempotency key)]
    I -->|Cancel or a change| A
    T --> A
```

The model understands the language. Code decides what is true: which seats exist and are free, what they cost, whether
the showtime has started, whose conversation it is, and whether the user said yes to this exact booking.

| Concern | How |
|---|---|
| Free conversation, change of mind, relative dates | One LangChain `create_agent` loop. The prompt is rebuilt per call with the time in WIB, the films and the draft |
| No invented ids, prices or seats | Tools validate against Postgres. The draft only changes through `update_booking` |
| Booking only after a yes | `interrupt()` inside `book_tickets`, resumed by `POST .../confirmation` or a typed reply the reader model classifies |
| A seat sold once | `UNIQUE (showtime_id, seat_id)`, all seats in one transaction, the tool call id as idempotency key |
| Other people's data | Conversation id and time come from the server (runtime context). Conversations belong to an API key |
| Loops and outages | 10 model calls per turn at most, retries for failed and dropped calls, an `error` event otherwise |
| Long conversations | `SummarizationMiddleware` past 8,000 tokens. The draft is state, so it survives the summary |
| Restarts, several workers | Conversations are LangGraph checkpoints in Postgres. Redis holds the rate limit and a one-turn-at-a-time lock |
| Seeing what happened | Every model call, tool call and middleware step traced to a self-hosted Phoenix |

Decisions and the options set aside (DeepSeek Harness, the kit's plain-loop template, HumanInTheLoopMiddleware) are in
[docs/adr/0001-architecture.md](docs/adr/0001-architecture.md).

## Measured

Ten scripted conversations (17 turns) against the running service with real DeepSeek calls, checked in code (events,
bookings in the database) and by `deepseek-v4-pro` as judge. Details and what each run found: [evals/README.md](evals/README.md).

| Thinking | Code checks | Judge | Median turn |
|---|---|---|---|
| off | 17/17 | 16/17 | 2.0 s |
| `low` (default) | 17/17 | 17/17 | 2.6 s |

Thinking was the difference on seats described in words: "three seats in the back row by the aisle" came out right 3
of 3 times with it and 1 of 3 without.

## Run

Needs Python 3.12, Docker, and `DEEPSEEK_API_KEY` in `../../secrets/secrets.env`.

    python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"     # .venv/bin on Linux and macOS
    cp .env.example .env
    docker compose up -d                  # Postgres :5433, Redis :6383, Phoenix :6006, on 127.0.0.1 only
    PYTHONPATH=. python scripts/seed.py   # 21 films, a week of showtimes. Run again any day to extend it
    python main.py                        # http://127.0.0.1:8060/docs

Without Docker, set `DATABASE_URL=sqlite+aiosqlite:///./tiketa.db` and empty `REDIS_URL` and
`PHOENIX_COLLECTOR_ENDPOINT`. On Windows, use `127.0.0.1` rather than `localhost` in the URLs (`localhost` tries IPv6
first and stalls), and run uvicorn without reload as `uvicorn main:app --port 8060 --loop asyncio:SelectorEventLoop`,
because psycopg's async mode needs a selector event loop.

Switch to Gemini with `LLM_MODEL=gemini/gemini-3.8-flash` (reads `GEMINI_API_KEY`). It is configured, not yet run live.

    make check        # ruff, mypy strict, 33 tests with a scripted model: no key, no services
    make scenarios    # the evaluation above, about 85k agent tokens

## API

| Method and path | What |
|---|---|
| `POST /v1/sessions` | Start a conversation, returns `session_id` |
| `POST /v1/sessions/{id}/messages` | Send a message. The reply streams as server-sent events |
| `POST /v1/sessions/{id}/confirmation` | `{"approved": true}` books the waiting summary, `false` cancels it. Streams like a message |
| `GET /v1/sessions/{id}` | The conversation: turns, draft, waiting summary, bookings |
| `GET /v1/movies`, `GET /v1/showtimes?day=`, `GET /v1/showtimes/{id}/seats` | The catalog, for a UI next to the chat |
| `GET /health`, `GET /meta` | The Lab backend contract |

Events, one JSON object per `data:` line: `token` (a piece of the reply), `tool` (the agent calls a tool), `confirmation`
(the summary to show with Confirm and Cancel), `booking` (the booking just made), `message` (the whole reply, the one to
keep), `error`, `end` (model calls and tokens of the turn). `/v1` needs `X-API-Key` when `API_KEYS` is set.

## Layout

    main.py, config/            settings (every value from .env), JSON logging
    app/bootstrap.py            app factory: middleware, errors, /v1 with API key and rate limit
    app/platform/               resources built at startup, database, checkpointer, Redis, locks, tracing, errors
    app/engines/llm.py          the chat model through LiteLLM
    app/cinema/                 the domain both features use: tables, store, seat layout, seed data
    app/features/chat/          agent, tools, prompt, state, confirmation reader, service, SSE routes
    app/features/catalog/       read-only films, showtimes and seats
    scripts/                    seed.py, run_scenarios.py
    evals/                      scenarios, results, what they found
    tests/                      the real graph with a scripted model, the store, the API
