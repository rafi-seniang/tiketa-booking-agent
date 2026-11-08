# Scenario evaluation

`scripts/run_scenarios.py` plays the thirteen conversations in `scenarios.json` (25 turns, Indonesian and English) against
a running service, with real DeepSeek calls. Each turn is checked twice:

- **In code:** the events the turn must produce (`confirmation`, `booking`), the events it must not produce (a
  `booking` after Cancel or after an instruction to skip confirmation), no `error` event, and the number of bookings
  the conversation ends with, read back from the database.
- **By a judge:** `deepseek/deepseek-v4-pro` reads the latest reply against the expected behaviour written in the
  scenario, with the conversation so far. Every failing verdict below was read by hand and agreed with.

## Results, 8 November 2026

Agent `deepseek/deepseek-flash` through LiteLLM 1.106.4, Postgres checkpoints, Redis, Phoenix tracing on.

| Thinking (`LLM_REASONING_EFFORT`) | Code checks | Judge | Median turn | Slowest turn | Tokens in / out |
|---|---|---|---|---|---|
| `none` | 17/17 | 16/17 | 2.0 s | 4.2 s | 84,737 / 2,173 |
| `low` (the default) | 17/17 | 17/17 | 2.6 s | 5.9 s | 82,219 / 3,985 |

The one difference is "3 kursi paling belakang deket lorong" (three seats in the back row by the aisle). Run alone
three times each, thinking off picked M16 to M18 (against the wall) twice and a correct block once. Thinking on picked
M7 to M9 (next to the aisle) all three times. Reading a text seat map for "next to each other" and "by the aisle" is
where the small model needs to think. Input tokens dominate the cost and barely change, so thinking is the default.

Later the same day, "moves to another day while the summary waits" was added and run four times with thinking `low`.
On Sunday the user asks for Dune "lusa" at 18:00 (Tuesday), then types "gajadi deh, besok aja untuk film yang sama di
jam paling malamnya, jumlah kursinya sama tapi di belakang" instead of confirming. All four runs booked nothing, moved
to Monday 20:45 (Dune's latest showtime that day), kept two seats and picked M8 and M9 three times and M10 and M11
once, in the back row by the aisle. Each run sent only the summary, with no sentence beside it.

Two step-by-step conversations were added and run twice each, all turns passing and read by hand. "Film, then time,
then seats, then name" asked for each missing piece in turn and showed the summary only once the name came. "Seats
named before the showtime" asks for Parasite with H9 and H10 and no time. The agent asked for the time and said it
would check those seats then. The code refuses seats before a showtime, because which seats are free depends on the
showtime. On "besok yang paling malem" it took Monday 21:15 and set H9 and H10 from the earlier message. It did not
mention that the aisle runs between H9 and H10.

Full rows, with every reply and verdict: `results/2026-11-08-deepseek-flash-thinking-low.json` and
`results/2026-11-08-deepseek-flash-thinking-off.json`.

## What earlier runs found, and what changed

| Found | Change |
|---|---|
| After a tool error written in English, the agent answered an Indonesian user in English | The prompt says to answer in the language of the user's latest message, also when tool results are in English |
| After Cancel, the agent replied as if the summary were still waiting ("The user did not confirm" read as "not yet") | The tool result now says what happened: Cancel was pressed, or a written reply came instead of a yes |
| Twice the agent sent only the summary, no sentence | The prompt asks for one sentence naming the seats with the `book_tickets` call. A summary alone still counts for the judge, because the user sees it with Confirm and Cancel |
| In thinking mode, the reply-reading model failed with "Thinking mode does not support this tool_choice", and the turn ended in an empty response | The reader always runs with thinking off. A failure before the agent runs now ends the stream with an `error` event and frees the turn |
| DeepSeek closed one stream after 19 s ("Connection closed"). `ChatLiteLLM` retries only calls that fail to start | `ModelRetryMiddleware` tries a dropped stream once more, then fails the turn |
| A scenario asked for seat F12, which the previous run had already booked | Scenarios that end in a booking let the agent pick a free seat, so runs do not depend on each other |
| The judge passed the English reply above | Its prompt checks the language first |
| The judge failed a correct "lusa" then "besok" reply, because it did not know today's date | Its prompt gets the current time in the cinema's timezone |
| "Kursi tengah" gave F4 and F5, a middle row but the left side | The seat map's legend states where the aisle, the walls and the centre are. The layout is data the model was missing. With it, the agent also pointed out that E9 and E10, which a scenario asked for, sit across the aisle (the scenario now asks for E7 and E8) |

## Limits

- 17 turns is a small sample, and one run of each setting. A difference of one turn is one turn.
- The judge is a model. It agreed with every failure read by hand, but it also once passed a reply in the wrong
  language before its prompt changed.
- Bookings from runs stay in the database. Run `scripts/seed.py` on a fresh database for a clean count.

## Run

    docker compose up -d && python scripts/seed.py && python main.py
    PYTHONPATH=. python scripts/run_scenarios.py              # about 85k agent tokens a run
    PYTHONPATH=. python scripts/run_scenarios.py --only "seats described" --no-judge
