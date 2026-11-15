# 0001. One agent loop on LangGraph, with every booking rule in code

Date: 8 November 2026. Status: accepted. Replaces Tiketa v1 (November 2025: a hand-written LangGraph loop on Gemini,
Gradio, history in a Python dict).

## Context

A cinema chatbot has to follow free conversation ("eh ganti film aja", "kursi paling belakang deket lorong",
"besok malem") and must never sell a seat twice, charge a price the model made up, or book what the user did not
confirm. Users jump between steps, so a fixed graph with one node per step (film, then time, then seats) breaks as
soon as they do. A free agent that calls `book(seats=...)` with arguments it wrote cannot be trusted with money.

Options looked at on 8 November 2026:

- **DeepSeek Harness (dsh):** a Node.js desktop and coding agent, a developer preview whose own SAFETY.md says it is
  not audited or production ready. It is a tool to work with, not a library for a backend service.
- **The kit's conversational-agent template:** a plain tool loop, router and sub-agents, in-memory sessions. Its own
  ADR says to move to LangGraph once checkpoints and human-in-the-loop interrupts are needed, which is this case.
- **LangChain v1 `create_agent` on LangGraph 1.x:** the agent loop with middleware hooks, durable checkpoints keyed
  by conversation, and `interrupt()` to wait for a person. OpenAI Agents SDK, Pydantic AI and Google ADK do much of the
  same. LangGraph has the checkpointers and interrupts built in.

## Decision

- **The model handles language, code handles every rule.** One `create_agent` loop, with tools to read (showtimes, a
  film, the seat map, this conversation's bookings) and one tool to change the booking draft, `update_booking`. The
  draft is typed graph state, not text: the tool checks every value against the database (the showtime exists and
  has not started, the seats exist, are free, and number at most `MAX_SEATS_PER_BOOKING`) before writing it.
- **A booking waits for the user, and the summary comes from the database.** `book_tickets` takes no arguments from
  the model. It reads the draft, prices it from the database, and pauses the graph with `interrupt()`. The client
  shows the summary with Confirm and Cancel. Only the resume, a button press (`POST .../confirmation`) or a typed reply,
  books. LangChain's `HumanInTheLoopMiddleware` was not used because it shows the person the model's tool arguments,
  and here the person must see what the database says.
- **A typed reply to the summary is read by a model, not matched.** "iya gas", "ok lanjut" or "ganti D5 aja" go to a
  small structured call (approve, decline, other) that runs with thinking off. Only a clear yes to the booking as
  shown approves it. The reply also joins the conversation, so the agent can act on a change.
- **The database holds the last line.** `UNIQUE (showtime_id, seat_id)` on booked seats, all seats in one transaction,
  and the tool call id as a unique idempotency key: a resumed or retried call returns the first booking. Seats taken
  while the user decides are caught when the summary is answered.
- **The model cannot reach other people's data.** The conversation id and the time come from the server through
  LangGraph's runtime context, never from the model. Conversations belong to the API key that created them, and
  another key gets 404.
- **Bounded loops and visible failures.** At most `MAX_MODEL_CALLS_PER_TURN` model calls per turn, then an `error`
  event. `ChatLiteLLM` retries calls that fail to start, and `ModelRetryMiddleware` retries a dropped stream once.
  A tool refusal returns to the model as text it can act on. An infrastructure error fails the turn with an `error`
  event, and the next turn answers the unfinished tool calls as not run, so the history stays valid.
- **One model setting, any provider.** LiteLLM through `langchain-litellm`. `LLM_MODEL=deepseek/deepseek-flash` by
  default, `gemini/gemini-3.8-flash` by changing one line. The LLM stack is pinned exactly, because litellm 1.82.7 and
  1.82.8 shipped malware in March 2026: a new version is taken on purpose, after it has been public for a while.
- **Thinking on by default.** `LLM_REASONING_EFFORT=low`. On the scenario set it was the only setting that chose seats
  from a description correctly every time (`evals/README.md`), for 0.6 s more per turn.
- **State lives in Postgres.** The cinema tables and LangGraph's checkpoints share one database, chosen by
  `DATABASE_URL` (SQLite works for a quick run). Any worker can take any turn, and a restart loses nothing. Redis holds
  the rate limit and a per-conversation lock, so one conversation runs one turn at a time across workers.
- **Traces in Phoenix.** OpenInference instrumentation sends every model call, tool call and middleware step to a
  self-hosted Phoenix, stored in the same Postgres. The traces hold what customers type, so they stay on our machine.
- **No regex or keyword lists for meaning.** Dates, times, film names, seat descriptions and yes or no replies are
  the model's job. Code checks the structured result: seat ids against the layout, ids against the database.

## Consequences

- One agent is enough while there is one domain. Refunds or membership would be the point to add sub-agents.
- Tests run the real graph with a scripted model and SQLite (`tests/`), so CI needs no key. Model behaviour is measured
  separately with the scenario runner and a judge (`evals/`).
- The schema is created at startup. Add Alembic before changing a live database.
- Not built: payment (the prompt says to pay at the counter with the booking code), user accounts beyond API keys,
  cancelling a booking, and a frontend. Gemini is configured but was not run live.
- The code is layered (changed on 8 November 2026, from the Lab's feature-first layout): routes declare HTTP,
  controllers stay thin, services hold the business process (the agent's graph and a chat turn), generative holds
  every prompt, tools and repositories touch the database. `app/core/lifespan.py` builds the agent and every client
  once at startup, so a request only runs a turn.

New decisions: copy this file as `NNNN-title.md`, state context, decision, consequences, and what it replaces.
