# Scenario evaluation

`scripts/run_scenarios.py` plays the thirteen conversations in `scenarios.json` (25 turns, Indonesian and English) against
a running service, with real DeepSeek calls. Each turn is checked twice:

- **In code:** the events the turn must produce (`confirmation`, `booking`), the events it must not produce (a
  `booking` after Cancel or after an instruction to skip confirmation), no `error` event, and the number of bookings
  the conversation ends with, read back from the database.
- **By a judge:** `deepseek/deepseek-v4-pro` reads the latest reply against the expected behaviour written in the
  scenario, with the conversation so far. Every failing verdict below was read by hand and agreed with.

Without `--key`, each conversation is played as its own guest of the booking service, as a visitor's browser is, so
each has its own rate limit there. The transcript keeps, per turn, the agent's own words (`text`), what the user saw
(`reply`, the words and then the summary card), and every tool call with its arguments and result, read from the
saved conversation. `evals/test_conversations.py` grades a transcript with [DeepEval](https://deepeval.com), below.
File names carry the UTC time of the run.

## Results, 15 November 2026, the first live runs since the split

Agent `deepseek/deepseek-flash`, thinking `low`, through LiteLLM 1.106.4, booking through tiketa-app over HTTP.

| Run | Change to the agent before it | Code checks | Judge | Median turn | Slowest | Tokens in (from cache) / out |
|---|---|---|---|---|---|---|
| `20261114-2304` | none, the code as split | 25/25 | 24/25 | 2.5 s | 6.2 s | 155,694 (128,512) / 6,746 |
| `20261114-2314` | the Cancel result says no seat is held | 25/25 | 25/25 | 2.2 s | 5.3 s | 147,620 (122,752) / 5,909 |
| `20261114-2323` | none (the transcript's shape changed) | 25/25 | 25/25 | 2.2 s | 6.0 s | 147,102 (120,704) / 6,300 |
| `20261114-2334` | the sentence with the summary is an argument of `book_tickets` | 25/25 | 25/25 | 2.2 s | 5.1 s | 153,648 (123,392) / 5,912 |

What these runs found:

| Found | Change |
|---|---|
| The very first full run died part way. One booking turn makes about eight calls to the booking service, the runner played every conversation as one caller, and the service's 60 calls a minute refused one. The agent turned that refusal into a failed turn with a generic error | The refusal goes back to the model with the seconds to wait (`report_refusals`), with a test. The runner plays each conversation as its own guest. Before the split the tools read the database directly, so no test could have met this |
| After Cancel, in English: "nothing was booked. The Parasite show ... with seats G7 and G8 is still set aside in your booking". Nothing holds a seat before a booking. The judge failed it, and so did DeepEval's role adherence | The Cancel result tells the model that no seat is held or set aside. Replayed three times, 9 of 9 turns passed |
| In 10 of 10 turns that showed a summary, the agent wrote no sentence, though its prompt asked for one. The user saw the card and nothing else. The older judge was told to accept that, so it never failed. DeepEval, given the agent's own words, counted the empty turns against it | A model that calls a tool often writes no text beside the call, so the sentence is now a required argument of `book_tickets` (`message_to_user`) and the service sends it with the summary. In the next run 10 of 10 summary turns carried a sentence in the user's language that named the seats |

## Graded with DeepEval

`evals/test_conversations.py` turns each conversation of a transcript into a DeepEval `ConversationalTestCase`, with
the tools called in each turn, and asserts on it the way a unit test would. It calls no agent, so one transcript can
be graded again without paying for the conversations again. Per conversation:

| Check | What it asks | Passes at |
|---|---|---|
| Expectations | One `must` condition per turn, from the scenario's expected behaviour, and one `must_not`: saying a booking is made with no booking code in a tool result | every condition |
| `ToolUseMetric` | The right tool for each step, with correct arguments, given the agent's real tool definitions | 0.5 |
| `RoleAdherenceMetric` | Stays this cinema's ticket assistant | 0.5 |
| `ConversationalGEval`, "Reply language" | Each reply is in the language of the message it answers | 0.5 |

The judge is `JUDGE_MODEL` (`deepseek-v4-pro`), called on DeepSeek directly. DeepEval lives in its own environment
(`make evals-install`), because DeepEval 4.3 needs `click` below 8.4 and the agent's model stack needs 8.4.2 or newer.
Telemetry is off (`DEEPEVAL_TELEMETRY_OPT_OUT=1`) and nothing is sent to Confident AI.

| Grading (in `results/deepeval/`) | Transcript | Conversations passing every check | Conditions | Tool use (mean) | Role adherence (mean) | Reply language (mean) |
|---|---|---|---|---|---|---|
| `2026-11-15-first-run` | `20261114-2304` | 9 of 13 | 38 of 38 | 10 of 13 (0.71) | 12 of 13 (0.88) | 13 of 13 (1.00) |
| `2026-11-15-second-run` | `20261114-2314` | 10 of 13 | 38 of 38 | 10 of 10 (0.91) | 13 of 13 (0.94) | 10 of 13 (0.73) |
| `2026-11-15-third-run` | `20261114-2323` | 8 of 13 | 36 of 38 | 10 of 10 (0.90) | 10 of 12, one not scored (0.70) | 12 of 13 (0.92) |
| `2026-11-15-fourth-run` | `20261114-2334` | 2 of the 2 graded | 7 of 7 | 2 of 2 | 2 of 2 | 2 of 2 |
| `2026-11-15-fifth-run` | `20261114-2334` | **12 of 13** | **38 of 38** | 10 of 10 (0.95) | 12 of 13 (0.92) | 13 of 13 (0.99) |

The fourth grading stopped early. DeepSeek answered 429 for 11 of the 13 conversations: it lowers an account's
allowed concurrency as the balance falls, and the balance was at 0.09 USD. The fifth grading is the same transcript
after a top-up, in full, and is the one to quote. It cost 0.22 USD (balance 2.09 before, 1.87 after), almost all of
it the judge.

The one failure of the fifth grading is role adherence on "off topic". The agent answered a request for a love poem
with "Maaf, saya cuma bisa bantu soal film dan tiket di Tiketa Cinema, bukan bikin pantun. Kalau mau nonton bareng
pacar, saya bisa carikan film dan jadwalnya." The role text says it declines in one sentence, and the judge counted
two sentences and the offer against it. The in-house judge and the conditions passed the same reply. Read by hand it
is a polite refusal that writes no poem, one sentence longer than its prompt asks.

How the grading itself changed between runs, each for a reason found by reading the verdicts:

- First run. Tool use scored 0 for the three conversations where calling no tool was right (a film that is not
  showing is known from the prompt's film list, a poem and an attempt to break the rules need no tool). DeepEval's own
  reason said the choice was correct while the score was 0. Role adherence failed "about a film" because the role text
  given to it left out answering questions about films, which was this file's mistake.
- Second run. Tool use is scored only where a tool was called, and the role text names film questions. The summary
  card was written into the assistant's reply as an English sentence, and the language check then read it as the
  assistant answering Indonesian in English, three times. That was the transcript's fault.
- Third run. The assistant turn holds only the agent's own words, and the card is described in the `book_tickets`
  result, where the system's part belongs. The remaining failures were then nearly all one real thing: the turns where
  the agent wrote nothing (role adherence, and the two conditions "replies in English"). That led to the third row of
  the table above. One failure was noise: the language check read `[pressed confirm]` as an English user message. Its
  criteria now say a button press has no language.

What this showed about judges: the three gradings agree on the conditions (112 of 114) and disagree by presentation
on the softer metrics. Tool-use reasons were sometimes wrong while the score still passed (a "missing"
`find_showtimes` whose answer was already in the previous turn, an "invented" name the user had typed). The code
checks stay the ground truth for what must never happen, and the model-graded metrics are read, not trusted.

DeepEval 4.3.2 with DeepSeek needed two small things, both in `test_conversations.py`: DeepSeek's JSON mode is not
given the fields DeepEval validates (the expectations check failed on a missing `evidence` field), so the judge class
appends the JSON schema to the prompt, and on Windows the run needs `PYTHONUTF8=1` and `pywin32`.

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

### Prompt cache

DeepSeek reads a request's start from its prompt cache when an earlier request began with the same text, and bills
those tokens at a lower rate. The prompt used to carry the time and the booking draft near its top, so every change of
minute or draft ended the shared start there. Now the rules and films are a fixed system prompt, and the time and draft
go in a system message after the conversation, sent with the call and not saved. On "film, then time, then seats, then
name" the share of input tokens read from the cache went from 59% (11,776 of 20,077) to 84% (20,096 of 24,060). On all
thirteen conversations it was 80% (123,136 of 154,765), with 25 of 25 turns passing in code and with the judge.

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

- 25 turns is a small sample, written by the same person who wrote the agent. A difference of one turn is one turn.
- The judges are models. The in-house judge agreed with every failure read by hand, but it once passed a reply in
  the wrong language before its prompt changed, and it accepted a summary with no sentence because it was told to.
- DeepEval's judge tokens were not counted: it reports no cost for a model whose price it does not know. All the
  runs and gradings of 15 November together cost 1.48 USD on the DeepSeek account, one full grading 0.22 USD.
- Most scenarios say "besok". The runs of 15 November were on a Sunday, so the next week's showtimes were published
  first (`scripts/publish_week.py --day` in tiketa-app). On a Sunday without that, tomorrow has no showtimes.
- Bookings from runs stay in the booking service's database, like any other booking.

## Run

    # tiketa-app running on :8070 with this week published, then
    docker compose up -d && python main.py
    make scenarios                        # about 150k agent tokens a run, four fifths of them read from the cache
    PYTHONPATH=. python scripts/run_scenarios.py --only "seats described" --no-judge
    make evals-install                    # once: DeepEval in .venv-evals
    make evals                            # grades the newest transcript, calls the judge model
    TRANSCRIPT=evals/results/<file>.json make evals

The evaluation is not part of CI: it calls a paid model.
