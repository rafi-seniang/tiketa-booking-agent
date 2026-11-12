# 0002. The agent is an add-on to the booking service

Date: 12 November 2026. Status: accepted. Changes where 0001's rules are enforced, not the rules.

## Context

v0.1.0 was one service: the chat agent, the booking form's API and the cinema's tables together. That made the agent
look like the product. It is not: a cinema sells seats with or without a chat, and when the model provider is down or
the day's token budget is spent, booking must go on. A second AI entry point was also wanted (an MCP server for
assistants such as Claude), and two entry points must not mean two places that decide whether a seat is free.

## Decision

- **The booking service owns the cinema.** Films, showtimes, seats, bookings, prices, the weekly schedule and guest
  sessions moved to [tiketa-app](https://github.com/rafi-seniang/tiketa-app), with the web app and the MCP server.
  It must be up. This agent, and that MCP server, are add-ons that can be off.
- **The agent keeps only what is its own.** Conversation owners, LangGraph checkpoints, the turn lock, the token
  budget, traces. Its database has one table of its own.
- **The agent acts as the user, never as itself.** A request arrives with the user's guest cookie or API key. The
  agent passes exactly those credentials to the booking service, first to ask who the caller is, then on every tool
  call of the turn. It holds no key that can book. The credentials live in the turn's runtime context, which is not
  saved in checkpoints and is hidden from `repr`, so they stay out of state, logs and traces.
- **The booking service has the last word.** The tools still check a seat before showing a summary, for a good
  answer. The booking itself is the service's transaction, with its unique constraint and its price.
- **One idempotency key per tool call of a conversation,** a SHA-256 of both ids, so a resumed or retried
  `book_tickets` books once whatever a provider's tool call ids look like.
- **Infrastructure fails loudly.** The agent does not start without the booking service, a request gets 503 when it
  stops answering, and a turn ends with an `error` event. Refusals (404, 409, 422) keep the service's own words and
  go back to the model as before.

## Set aside

- **A service key that can book for anyone.** Simpler to wire, and one leaked key or one confused tool call away
  from booking as someone else.
- **Sharing the Postgres database.** No HTTP hop, and two codebases that must agree on every column and rule.
- **Loading the agent's tools from the MCP server.** One tool list for both. The agent's draft state and its
  `interrupt()` confirmation do not map onto MCP tools, and the MCP server books in two calls instead.
- **Verifying the guest cookie in the agent with a shared secret.** Saves one request per call, and puts the signing
  secret in a second service.

## Consequences

- One more HTTP request per agent request (who is calling), and one per tool call. Local calls take a few
  milliseconds beside model calls of seconds.
- The films in the system prompt are read at startup. A change of programme needs an agent restart.
- The seat layout is no longer known here. The seat map's text and legend are built from the service's answer.
- The evaluation scenarios need both services running, and have not been rerun since the split.
