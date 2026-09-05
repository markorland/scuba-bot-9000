# scuba-bot-9000 — Implementation Plan

## Context

Steelhead exhibit cleaning currently gets handed out ad hoc, so the same people end up doing it
repeatedly while others rarely do. We want a bot that makes the rotation provably even over a
calendar year without anyone having to track it by hand.

The bot has its own Gmail mailbox — referred to throughout as `GMAIL_ADDRESS`, because the literal
address is a secret and is never committed. It reads from that mailbox and replies as it. Each week
a team member emails it with the subject **`Aquarium Sunday MM/DD/YYYY`**.

The body is **not** a bare name list. It opens with optional announcements, then carries one or
more date-headed blocks — a Sunday date on its own line, the people attending that Sunday one per
line, then the *following* Sunday and its people. **Only the first date block matters.** Everything
above it is chatter and everything below it is next week's problem.

That block mixes **team members** (eligible to clean steelhead) with **guests** (never eligible),
and nothing in the text distinguishes them — a name is a team member if and only if it resolves
against the roster. The bot picks the two team members furthest behind on steelhead duty
plus one backup, and replies to the thread with the assignment. Silence means the assignment stood
— no reply is needed for the normal case. Humans correct the record by replying with a slash
command (`/none`, `/worked ...`), and manage the roster the same way.

Members have email addresses on file, which is what lets the bot tell who is speaking.

Counts reset every January. On the first shift of the new year the bot assigns as usual, emails a
summary of the closing year, and then **deletes it** — nothing is kept beyond the current year, in
the database or in the backups. Medical leave must not push someone to the front of the queue when
they return — time on leave is invisible to the fairness math, not a debt to repay.

The repo holds only `README.md`, `LICENSE` and `.gitignore`, so this is greenfield — and **it is
public**, which constrains where the roster and the backups are allowed to live. See *Privacy and
repo layout*.

### Decisions already made

| Question | Decision |
|---|---|
| Command surface | Slash commands typed into **email replies** (real Slack/Discord deferred) |
| Gmail auth | **IMAP + SMTP with a Gmail app password**, behind a `MailClient` interface |
| Send modes | `dry-run` → `dark` (everything real, all mail to one address) → `live` |
| Bot behavior | Replies with the assignment; assigned people are assumed to have worked |
| Crew size | **2 primary + 1 backup** |
| Repeat rule | No back-to-back sessions; waived only when the pool is too small, and logged |
| Schedule email format | Subject `Aquarium Sunday MM/DD/YYYY`; body = preamble, then date-headed blocks of one name per line |
| Which week | The **first** date block in the body; later blocks (next Sunday) and any preamble are ignored |
| Subject vs body date | Body's first date header wins; the subject is the fallback when the body has none |
| Guest detection | Roster membership only — no marker in the email text |
| Attendee lines | Free-form — names carry qualifiers, codes and commentary; each line is *searched* for a roster name |
| Tentative markers | `Betsy - maybe` counts as attending; qualifiers are ignored |
| Schedule email sender | A team member (not the bot) — inbound to the bot's mailbox |
| Member identity | Name + aliases + **email address(es)**; email supplied at `/add-member` |
| Tie-break | Longest since last worked |
| Database | SQLite on a mounted volume |
| Runtime | Long-running container on the TrueNAS box |
| Host | TrueNAS, **not reachable from the internet** — a self-hosted runner dials out to GitHub |
| Secrets | GitHub Secrets on the **private** repo, rendered to `.env` on the host by the deploy job |
| Deployment | `deploy.yml` on the self-hosted runner: render `.env`, sync roster, `compose pull && up -d` |
| Backup | SQLite snapshot committed to the **private** data repo, but only when state actually changed |
| Year rollover | On the first assignment of a new year: assign → reply → summary email → purge → reset snapshots |
| Data retention | Current year only, in the live database *and* in the snapshots |
| Year summary | Its own email, `Steelhead <year> — year in review`; the only surviving record |
| First shift of January | Goes to whoever cleaned least in the closing year, via a carried-over ratio |
| Repo layout | Public `scuba-bot-9000` (code) + private `scuba-bot-9000-data` (roster, fixtures, snapshots, deploy) |
| Roster storage | `roster.yaml` in the private repo; seeds SQLite on first boot, DB authoritative after |
| PII in the public repo | None — no names, no addresses, no real email bodies, no `.db` files |

---

## Privacy and repo layout

**This repo is public.** Nothing identifying a team member can be in it, and "nothing" has to cover
the indirect routes, which is where this usually goes wrong: the roster file, the nightly DB dump
(names, addresses **and whole inbound email bodies**), fixtures built from real emails, and log
lines pasted into an issue.

Because it is already public, there is no future audit to defer to — a commit is exposed the
moment it is pushed. The history is clean as of the current `Initial commit`, and the cheap fix
stops being cheap the moment the first roster lands in a commit.

### Two repos

| | `scuba-bot-9000` (public) | `scuba-bot-9000-data` (private) |
|---|---|---|
| Holds | Code, tests, Dockerfile, compose, CI, `config.example.yaml` with invented people | `roster.yaml`, real email fixtures, `snapshots/` |
| Secrets in its Actions | **none** | **none** — the host holds them, see *Deployment* |
| Change rate | Often | Rarely — a few roster edits a year |

**The self-hosted runner is registered to the private repo, and only to it.** This is the
load-bearing rule of the whole split. GitHub's own guidance is that self-hosted runners do not
belong on public repositories: a pull request from a fork can run arbitrary code on the machine,
and here that machine is the NAS. A private repo cannot be forked by outsiders and only the owner
can push to it, which is what makes a runner safe on this side and unsafe on the other.

Concretely: `runs-on: self-hosted` must never appear in a workflow in the public repo. The public
repo's CI runs on GitHub-hosted runners with no secrets, over input that anyone can submit.

**Every secret lives in the private repo's Actions secrets**, delivered to the host by a deploy job
that executes on the runner. The public repo holds none — `publish.yml` needs only the token
GitHub injects.

### What lives where

- **Roster** → `roster.yaml`, private repo. Real names, aliases, addresses, `is_admin`. Deploy
  copies it to `/opt/scubabot/config/roster.yaml`, mounted read-only. It seeds an empty DB on first
  boot; after that **the DB is authoritative** and `/add-member` is the day-to-day surface. The file
  is the rebuild recipe, not the live state — so add a `db export-roster` CLI that regenerates it
  from the DB, to be committed back to the private repo whenever the roster changes. Without that
  the recipe silently rots and the disaster-recovery path stops working.
- **Public example config** → `config/config.example.yaml` with invented people. It doubles as
  schema documentation and as the fixture roster the public test suite ranks against.
- **DB snapshots** → `snapshots/` in the private repo. This is the most sensitive artifact in the
  project, because `schedules.raw_body` holds entire inbound emails.
- **Test fixtures** → the public repo gets **synthetic** emails only, hand-written to cover each
  parsing case. Real messages live in the private repo and run through the same test module when it
  is checked out beside the code: `pytest -m realdata`, deselected by default.
- **Docs and comments** → `GMAIL_ADDRESS`, never the literal address. A published inbox invites
  spam into the mailbox the bot parses every morning; commands are already refused from unknown
  senders, so the exposure is volume rather than control, but there is no upside to publishing it.

### Guardrails, not good intentions

Every rule above is one someone forgets at 11pm, so enforce them mechanically:

- `.gitignore` in the public repo: `config/config.yaml`, `roster.y*ml`, `data/`, `*.db`,
  `*.sqlite*`, `.env`, `fixtures/real/`.
- A **PII check** as a pre-commit hook *and* a CI job, failing on an email-shaped string outside
  `config.example.yaml`, a file named `roster.y*ml`, or any `.db`/`.sqlite` file. This is the only
  part of this section that still works on a bad day.
- `gitleaks` in CI for credentials.
- **Log redaction:** structured logs may carry member ids and canonical names, never full email
  addresses and never raw message bodies. Logs are the most common accidental disclosure, because
  people paste them into issues without rereading them.
- Bot **replies** name people freely — those are private emails to the team and stay as they are.

### When something leaks anyway

Commit author metadata is public along with the code; the decision is to leave it as the
maintainer's own address.

On GitHub a force-push does **not** erase what was already pushed. Pull-request head refs
(`refs/pull/N/head`) keep old commits fetchable by SHA even after the branch moves, unreachable
objects survive until GitHub garbage-collects them, and pushes to a public repo are mirrored into
the public events feed along with their SHAs. **Rewriting history in place does not remove
anything.**

So if personal data does land in a commit here, the remedy is to delete the repository and push a
clean history — recreating the repo takes the pull refs with it. That is cheap while the repo is a
few commits of planning and expensive once there are issues, forks and stars, which is the real
argument for getting the PII check running early rather than treating it as polish.

---

## Architecture

```
scuba-bot-9000/
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml
├── config/config.example.yaml       # invented sample roster + tuning — no real people
├── data/                            # volume mount → scubabot.db
├── src/scubabot/
│   ├── __main__.py                  # CLI: run-once / serve / dry-run / stats
│   ├── config.py                    # pydantic-settings; secrets from env only
│   ├── db.py                        # connection, schema, forward-only migrations
│   ├── mail/
│   │   ├── base.py                  # MailClient protocol (fetch/send/mark)
│   │   ├── imap_smtp.py             # app-password implementation — the one we ship
│   │   └── fake.py                  # in-memory, for tests
│   ├── parsing/
│   │   ├── names.py                 # normalization + alias resolution
│   │   ├── schedule.py              # body → date blocks → attendee names
│   │   └── commands.py              # reply body → [Command]
│   ├── fairness.py                  # ranking + selection (pure, no I/O)
│   ├── commands/                    # one handler per slash command
│   ├── compose.py                   # assignment / stats / help reply bodies
│   └── run.py                       # daily orchestration
└── tests/
    └── fixtures/                    # synthetic emails only
```

The private companion repo stays deliberately small:

```
scuba-bot-9000-data/
├── roster.yaml                      # real names, aliases, emails, admins
├── fixtures/                        # real schedule emails, for `pytest -m realdata`
├── snapshots/                       # nightly sqlite3 .dump
└── .github/workflows/
    ├── roster-check.yml          # validates roster.yaml — GitHub-hosted
    ├── deploy.yml                # renders .env, restarts the bot — self-hosted runner
    └── snapshot.yml              # commits the nightly dump — self-hosted runner
```

The self-hosted runner lives on the NAS and is registered to **this** repo only.

**Layering rule:** `fairness.py` and `parsing/` are pure functions over plain data — no DB, no
network. That is what makes the year-long simulation test cheap to write.

---

## Core logic

### Daily run (08:00 `America/Los_Angeles`)

Use a tz-aware schedule, not a fixed UTC offset, so the run stays at 8am local across the
PST/PDT switch.

1. **Fetch** unprocessed messages. Skip any whose `Message-ID` is already in `processed_messages`
   — this is the primary idempotency guard, not "unseen" flags. **Only messages the bot acts on are
   recorded there**; anything ignored is simply re-classified next run, which is cheap, deterministic
   and cannot produce a duplicate reply. Recording ignored mail would mean a stray newsletter counts
   as a database change and triggers a snapshot commit on an otherwise quiet day.
2. **Classify** each message by subject (see *Schedule email identification* below): new schedule,
   reply to a known thread, or ignore. A message can be both — a reply may carry commands.
3. **Schedule email** → trim signature/quotes → take the **first date block** → parse names →
   resolve against roster → guests logged and dropped → compute assignment → persist → reply.
4. **Command reply** → authorize sender → execute → reply with the result.
5. **Finalize** any assignment whose Sunday has passed by more than `finalize_grace_days`
   (default 1) and that was not corrected: write a `sessions` row per primary, status → `confirmed`.
6. **Roll over the year** if this run produced the first assignment of a new calendar year — see
   *Yearly rollover*.
7. **Record** the run.

Credit is awarded at *finalization*, not at assignment time, so `/none` and `/worked` have a
window to land first. Ranking counts confirmed **plus** still-pending assignments, so nobody gets
picked twice in a row while their first assignment is un-finalized.

**Most runs do nothing.** On a typical weekday there is no new schedule email and no reply, so the
run fetches, classifies nothing, finalizes nothing and exits. That is the expected case, and the
rest of the design leans on it: no snapshot commit, no email, one log line.

**Missed-run catch-up:** on startup, if the most recent `runs` row is older than today, run
immediately. A container restart must never silently skip a week.

### Schedule email identification

Both the subject and the body's first date header carry the date, which is far better than
inferring "the upcoming Sunday" — it means a schedule email sent two weeks early, or re-sent late,
still lands on the right date.

The subject is what *classifies* a message as a schedule email: match it case-insensitively against
roughly `aquarium\s+sunday\s+(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})`, tolerating extra words, `Fwd:`
prefixes, and stray punctuation. Because the format is only *usually* followed, also treat a body
containing a date header with 2+ roster names beneath it as a schedule email even when the subject
doesn't match — but log the mismatch so the subject pattern can be widened.

The **date** is then resolved in this order:

1. Body has a date header → **the first one wins.** It sits directly above the name list it
   describes, so it cannot be wrong about which crew we are reading.
2. No date header in the body, subject date parses → use the subject date.
3. Neither → fall back to the next upcoming Sunday, and **say in the reply which date was assumed**,
   so a wrong guess is caught the same day rather than at year end.

A subject/body disagreement should be vanishingly rare; when it happens the body wins silently for
assignment purposes, but both dates are stored (`schedules.subject_date`) and the discrepancy is
logged, so a systematic drift is visible rather than invisible. If the resolved date is not
actually a Sunday, accept it but flag it in the reply — the date the human wrote shouldn't be
silently overruled.

`schedules.schedule_date` is `UNIQUE`, so a duplicate or forwarded copy of the same week updates
the existing row rather than creating a second assignment.

### Schedule email body parsing

The body looks roughly like this, and only the shaded part is used:

```
Reminder: the gate code changed to 4417.          ← preamble, discarded
Please arrive by 8:45 and sign in at the desk.

Sunday 03/08/2026                                 ← first date header: the week we assign
Alice Nguyen                                      ┐
Bob Carter                                        │ attendees — team members and guests
Cara Diaz                                         │ mixed together, one per line
Sam Whitfield                                     ┘

Sunday 03/15/2026                                 ← next week, discarded
Dev Patel
Erin Fox
```

**Algorithm** — scan top to bottom, split into date-headed blocks, keep the first block only:

1. **Trim the tail** before anything else: signature blocks (`-- `, `Sent from my …`), quoted
   history (leading `>`, `On <date> … wrote:`). If the message is HTML-only, convert to text first
   while preserving line breaks — `<br>`, `<p>`, `<li>` all become newlines, or a one-per-line list
   collapses into a single unparseable line.
2. **Find date headers.** A header is a line that is *mostly a date*: an optional weekday word, a
   date as `M/D`, `M/D/YY(YY)`, `M-D-YY`, or `Month D(th)`, plus optional trailing punctuation, and
   very little else. Cap the allowed extra words so a prose line like "we'll do a deep clean on
   3/15" is not mistaken for a header. A header missing its year takes the year that puts it
   closest to the message's own `Date:` header.
3. **Discard the preamble** — everything before the first header, however many lines it runs to.
4. **Take the first block only.** It runs from the first header to the next header, or to the end
   of the trimmed body if there is no second header.
5. Every remaining non-empty line in that block is an attendee candidate.

**Attendee lines: search for a name, do not clean the line.**

Lines are free-form, and there is no strip-the-decoration rule that survives contact with them:

```
Nadia                         bare first name
Betsy Swift                   first and last name
Owen (5B)                     trailing code
Betsy - maybe                 trailing qualifier
Nadia from Saturday           trailing phrase
The return of Betsy Swift     name buried mid-sentence
```

Any filter strict enough to reject prose also rejects the last line; any cleanup loose enough to
keep the last line also keeps prose. So invert the problem: **the roster is the pattern and the
line is the haystack.** The bot never decides what a line *means* — it only asks whether a known
roster name appears in it.

Per line:

1. **Normalize** — lowercase, strip accents and punctuation, split into tokens.
   `Owen (5B)` → `owen 5b`.
2. **Look up token n-grams** in a match index built once per run from the active roster. Each
   member contributes their canonical name, `first last`, last name alone, first name alone, and
   every alias — each entry carrying a specificity score (more tokens = more specific).
3. **Longest match wins.** Scan 3-grams, then 2-grams, then single tokens, taking the most specific
   hit. `the return of betsy doe` matches the 2-gram `betsy doe`, which outranks the bare
   `betsy`, so it resolves to one member rather than two competing readings.
4. **Take every non-overlapping match** on the line — `Betsy and Owen` is two people. Dedupe per
   member across the whole block, so a member named on two lines is credited once.
5. **No match → unmatched.** The line is stored verbatim in `unmatched_names` and named in the
   reply. It may be a guest, a misspelled member, or a stray note; the bot cannot tell them apart
   and should not pretend to.

Trailing junk needs no handling of its own. `(5B)`, `maybe` and `from Saturday` match nothing in
the index and are simply passed over — that is the whole point of the inversion. Decoration nobody
anticipated is inert instead of being something the parser has to have guessed in advance.

**Qualifiers are ignored.** `Betsy - maybe` is treated exactly as `Betsy`: on the list means
eligible. If maybes later turn out to no-show often, the hook is one predicate in the extractor
plus a `tentative` flag on `schedule_attendees` — deliberately not built now.

**False-positive guards:**

- Match **whole tokens only**, never substrings — `sam` must not fire inside `Samantha`.
- **First names are unique on the roster today, but the bot must not bake that in.** A single-token
  first-name match is accepted only when that name maps to exactly one active member. The day a
  second Nadia joins, every bare `Nadia` becomes ambiguous: no match, the line goes to
  `unmatched_names`, and the reply explains *why* — "`Nadia` matches two members, add an alias or a
  last name". Guessing between two people is the one failure here that nobody would ever notice.
- Roster names that collide with ordinary words (`May`, `Will`, `Art`, `Sunday`) go in an
  `ambiguous_tokens` config list; those members require a last name or alias to match at all.
- Only lines inside the first date block are scanned, so preamble prose never reaches the index.

**Guests are found by subtraction, not by marking.** Nothing in the email labels them; a name is a
team member if and only if it resolves to a roster entry seeded from `roster.yaml`. That makes
`unmatched_names` load-bearing rather than a nicety — a misspelled or newly-married team member
silently becomes an ineligible guest otherwise. The assignment reply therefore **lists the names it
could not match**, so a bad match is caught the same day it happens.

**Fallbacks:**

- No date header anywhere → treat the whole trimmed body as one block, date from the subject, and
  flag the assumption in the reply.
- First block resolves to zero roster names → write no assignment; reply asking a human to check,
  and include the raw lines that were parsed so the failure is diagnosable from the reply alone.

**Deliberately not used: the following Sunday's block.** Pre-assigning next week from it is
tempting and wrong — the crew list routinely changes between the two emails, so the bot would be
holding a stale assignment it then has to revoke. Each Sunday is assigned from its own email, and
the second block is parsed only far enough to know where the first one ends.

### Sender identity

Every inbound message's `From` address is resolved against `member_emails`. This gives the bot,
for free:

- **Authorization** — commands are accepted from known member addresses, not an address list
  maintained separately from the roster. One place to keep current.
- **Attribution** — `command_log.sender` records *who*, not just which address.
- **Better replies** — the bot can address the sender by name.

An unknown sender's schedule email is still processed (the roster in the body is what matters), but
their **commands are refused** with a short note on how to get added. Unknown senders are logged.

### Fairness ranking

Eligible for a given Sunday = on the parsed working list ∧ active member ∧ not on medical leave
covering that date.

#### Back-to-back cooldown

Nobody cleans steelhead two sessions running. This is a **filter applied before ranking**, not
another tiebreak term — as a tiebreak the load ratio would routinely outvote it, since the person
who just worked often still has the lowest ratio.

Split the eligible pool into two tiers:

- **Tier 1** — eligible members *not* credited (or holding a pending primary assignment) on the
  previous recorded steelhead session.
- **Tier 2** — everyone else eligible.

Fill both primary slots from Tier 1, ranked as below. Only when Tier 1 holds fewer than 2 people do
we dip into Tier 2; that assignment records `cooldown_waived = 1` and the reply says so out loud
("Dana is repeating — only three team members are on shift this week").

- Keyed on the **previous recorded session, not the previous calendar week.** A skipped Sunday or a
  `/none` week must not silently clear someone's cooldown.
- **Being listed as backup does not trigger a cooldown** — only actual credit does. A backup who
  never worked is fully available next week.
- The backup slot prefers Tier 1 as well, but takes a Tier 2 member rather than go empty.
- `cooldown_sessions: 1` in config, so it can widen to 2 without a code change.
- `/stats` reports the year's waiver count — that is how "this should be rare" gets verified rather
  than assumed. A climbing number means the roster is too thin, and it should be visible.

#### Ranking

Sort ascending by:

1. **Load ratio** — `sessions_this_year / eligible_sundays_this_year`
2. Raw session count this year
3. **Closing year's load ratio** — `members.prior_year_ratio`, carried across the rollover
4. Days since last steelhead session (descending — longest wait first)
5. Canonical name (deterministic final tie-break)

Top 2 → primary, next 1 → backup.

Key 3 exists for January. Once the year rolls over, keys 1 and 2 are zero for everybody and would
decide nothing; the closing year's ratio is then the only real information available, so **the first
shift of the new year goes to the people who cleaned least last year**. It fades out on its own as
new sessions accumulate and the first two keys start separating people again. A member with no prior
year (someone who joined in December) ranks as though their prior ratio were zero — they have done
nothing, so they go first.

**Why a ratio rather than a raw count.** A raw count is what "the people who worked the least go
first" means intuitively, and when everyone attends similarly the ratio reduces to exactly that.
But it breaks on medical leave: someone out three months returns with the lowest raw count and
gets assigned every single week to "catch up" — precisely the penalty the requirement forbids.
Under the ratio, Sundays spent on leave never enter that member's denominator, so leave is
genuinely invisible. Same protection for anyone who simply isn't scheduled often.

Expose `fairness_mode: ratio | raw` in config so the behavior is inspectable and reversible.

**Degenerate cases:** fewer than 3 eligible team members working → assign what exists, drop the
backup first, and say so plainly in the reply. Zero eligible → reply asking a human to sort it out;
write no assignment. A roster small enough to force weekly cooldown waivers is a staffing problem
the bot should surface, not paper over.

### Yearly rollover

Every fairness query filters `WHERE year = ?`, so counters reset on their own at midnight Jan 1.
The rollover is what makes the reset real: it reports the closing year, then deletes it.

It is triggered by the **first assignment of a new year, not by the calendar**. If the bot is down
on Jan 1, or the first schedule email lands on the 8th, the rollover still happens exactly once and
still happens in the right order.

**The order is load-bearing:**

1. **Finalize** any assignment left pending from the closing year, so December's credit is complete
   before anything is counted or deleted.
2. **Write the carry-over values** — `prior_year_ratio` and `last_session_date` per member,
   computed from the closing year. This has to happen *before* the assignment in step 3, because
   that assignment ranks on `prior_year_ratio`; write it later and the first shift of the year would
   rank on values a year out of date.
3. **Assign** the new year's first Sunday. Ranking keys 1 and 2 are zero for everyone, so key 3
   decides: the people who cleaned least last year. The closing year's `sessions` are also still
   present, which is what lets the back-to-back cooldown see that someone worked on Dec 28. Purging
   first would let that person be assigned again a week later — the one rule a rollover could
   quietly break, and nobody would notice until it already had.
4. **Send the assignment reply.**
5. **Send the year-in-review summary** as its own email: `Steelhead <closing year> — year in review`.
6. **Confirm both sends succeeded.** If either failed, stop and retry next run. After step 7 the
   summary is the *only* surviving record of the year; purging before it is delivered destroys the
   data and produces nothing in exchange.
7. **Purge** the closing year and everything before it.
8. **Reset the snapshot branch** so the backups hold no more than the live database does.
9. **Record** the rollover in `year_rollovers`, which is what stops it running twice.

**The summary email** — per member: sessions worked, load ratio, longest gap between sessions. Plus
totals: Sundays covered, assignments voided by `/none`, corrections via `/worked`, cooldown waivers,
and members who joined or left. Anyone who wants a longer record keeps the email.

**Purged:** `sessions`, `schedules` and `schedule_attendees`, `assignments` and `assignment_slots`,
`unmatched_names`, `command_log`, `runs` — everything dated before Jan 1 of the current year.
Dropping `schedules` also removes every stored `raw_body`, so the most sensitive thing the bot holds
has a one-year life by default rather than accumulating forever.

**Survives the purge:**

- `members`, `member_aliases`, `member_emails` — the roster is not history.
- `leaves` that are open-ended or that end on or after Jan 1. **A member on medical leave across the
  boundary must stay on leave**; deleting their row would silently make them eligible on their first
  Sunday back, which is precisely the outcome the leave rule exists to prevent.
- `processed_messages`, on its own rolling window (`processed_message_retention_days`, default 400).
  It holds Message-IDs and nothing else, and it is the only thing stopping a re-fetched December
  email from being answered a second time. Tying it to the year purge would trade a real
  duplicate-reply risk for no privacy gain.
- `year_rollovers` — one row per year, dates only.
- `members.prior_year_ratio` and `members.last_session_date` — two scalars per member, written in
  step 2, before either the assignment or the delete needs them.

**Who goes first in January.** On Jan 1 every member has zero sessions in the new year, so the
first two ranking keys tie for everyone. The key that decides the first shift is the closing year's
load ratio, written to `members.prior_year_ratio` in step 2 and surviving the purge: **the
people who cleaned least last year go first.** That is the same rule that governs every other week
of the year, applied to the only data that still exists.

Two scalars per member survive the purge to make this work — `prior_year_ratio` and
`last_session_date`. Neither is history in any meaningful sense: no sessions, no schedules, no email
bodies, nothing beyond what the roster already implies.

**Carrying a ratio rather than a date is the whole point.** If January ordering fell back to
`last_session_date` alone, a member returning from three months of leave would have the oldest date
on the roster and be picked first every week until new-year sessions accumulated — precisely the
catch-up penalty the load ratio exists to prevent. Carrying the ratio carries leave-invisibility
across the year boundary with it. `last_session_date` is kept for a narrower job: honouring the
back-to-back cooldown when the previous session has been purged, such as a `/none` on the first
shift of the new year.

### Name matching

`roster.yaml` (private repo, mounted read-only on the host) seeds each member with a canonical
name, aliases, and one or more email addresses; the DB is the source of truth after first boot. Normalize names by lowercasing, stripping accents and
punctuation, collapsing whitespace. Match full name first, then unique first name.
A first name matches only when it is unique among active members; `ambiguous_tokens` in config
forces a last name for anyone whose name collides with an ordinary word. See *Schedule email body
parsing* for how a line is searched. An unmatched name is a guest — logged to `unmatched_names` so
an admin can add an alias if the bot guessed wrong. **The bot never assigns a name it could not resolve to a roster member.**

---

## Database (SQLite)

```
members(id, canonical_name, active, is_admin, added_at, removed_at,
        last_session_date, prior_year_ratio)
    -- both survive the yearly purge and are rewritten at each rollover.
    -- prior_year_ratio ranks the first shift of January (fewest cleanings last year go
    -- first); last_session_date honours the cooldown when the previous session is gone
member_aliases(member_id, alias_normalized UNIQUE)
member_emails(member_id, email_normalized UNIQUE, is_primary)
    -- multiple rows per member: people reply from a phone or work address
    -- and the bot must recognize all of them as the same person
leaves(id, member_id, start_date, end_date NULL, note)
schedules(id, schedule_date UNIQUE, subject_date, source_message_id, raw_body, parsed_at)
    -- schedule_date comes from the body's first date header; subject_date from the subject line.
    -- Both stored so a systematic disagreement is queryable rather than invisible.
    -- raw_body keeps the whole email, preamble and later blocks included, so a parser fix can be
    -- replayed against real messages without re-fetching the mailbox.
schedule_attendees(schedule_id, member_id NULL, raw_name, is_guest)
    -- first date block only; member_id NULL ⇒ guest (no roster match)
assignments(id, schedule_date UNIQUE, status, cooldown_waived, created_at, finalized_at)
    status ∈ pending | confirmed | overridden | voided
assignment_slots(assignment_id, member_id, role)   role ∈ primary | backup
sessions(id, member_id, session_date, year, source, UNIQUE(member_id, session_date))
processed_messages(message_id PK, processed_at, kind)
command_log(id, message_id, sender, command, args, result, created_at)
unmatched_names(id, raw_name, first_seen, times_seen)
runs(id, run_date UNIQUE, started_at, finished_at, status, summary)
year_rollovers(closing_year PK, summary_sent_at, purged_at, snapshots_reset_at)
    -- dates only, no names; makes the rollover idempotent. summary_sent_at is written
    -- before purged_at, so a crash between them is visible and recoverable
```

`sessions` is the single credit ledger — all stats read from it. `eligible_sundays` is derived
from `schedule_attendees` minus `leaves`, never stored as a counter that can drift.

Every table that accumulates rows is emptied of prior years at rollover, so the database stays
roughly constant in size year over year rather than growing forever.

Enable `PRAGMA journal_mode=WAL` and `foreign_keys=ON`.

---

## Slash commands (in email replies)

Parsed from lines beginning with `/`, **after stripping quoted text** — otherwise a quoted `/none`
from last week's thread re-executes every time someone replies. The sender's address must resolve
to an active member; unauthorized commands are logged and refused with a short explanation, never
silently ignored.

Two privilege levels, both derived from the roster rather than a separate list:

- **Any active member** — `/help`, `/roster`, `/stats`, `/none`, `/worked`. These are the
  week-to-week corrections, and gating them would just mean the record goes uncorrected.
- **Admins** (`is_admin` on the member) — `/add-member`, `/remove-member`, `/leave-start`,
  `/leave-end`, `/add-email`. These change who is in the rotation or alter the fairness math.

| Command | Effect |
|---|---|
| `/help` | List every command with a one-line description |
| `/add-member <name> <email> [alias, ...]` | Add to roster with a contact address |
| `/add-email <name> <email>` | Register an additional address for an existing member |
| `/remove-member <name>` | Soft-delete; history and past sessions preserved |
| `/stats` | Sessions, load ratio, last worked, current leave — per member, current year |
| `/leave-start <name> [YYYY-MM-DD]` | Begin medical leave (defaults to today) |
| `/leave-end <name> [YYYY-MM-DD]` | End medical leave |
| `/none [YYYY-MM-DD]` | Nobody cleaned steelhead — void the assignment, credit no one |
| `/worked <name>, <name> [YYYY-MM-DD]` | Different people worked than assigned — move the credit |
| `/roster` | Show active members, aliases, and addresses |

Date defaults to the Sunday of the thread the reply is on; falls back to the most recent Sunday.
Every command replies with a confirmation of what changed — a command that appears to do nothing
is worse than one that errors.

---

## Gmail: IMAP + SMTP with an app password

**Decided.** One credential (`GMAIL_APP_PASSWORD`), no OAuth flow, no refresh token to mount or
rotate, and nothing that silently expires while the container runs unattended for months. That last
point is what settles it: a headless bot nobody looks at until it fails badly should not depend on
a token that Google can invalidate on a password change or after a stretch of inactivity.

The cost is that an app password is **coarse** — full mailbox access, not the scoped
`gmail.readonly` + `gmail.send` an OAuth client would get. It is mitigated by the account being
single-purpose and dedicated: there is nothing else in that mailbox to lose.

### Setup

- **2-Step Verification must be on** — app passwords do not exist without it, and turning 2FA off
  later revokes every app password, which would take the bot down with an auth error that looks
  like a wrong password.
- Generate a 16-character app password and put it in the private repo's Actions secrets as
  `GMAIL_APP_PASSWORD`. `deploy.yml` renders it into `.env` on the host.
- `imap.gmail.com:993` over TLS, `smtp.gmail.com:465` over TLS. Read `INBOX`, not All Mail.

### Behaviour worth knowing

- **Threading is manual.** Set `In-Reply-To` and `References` from the message being answered;
  there are no native thread IDs the way the Gmail API has them. Getting this wrong doesn't error,
  it just scatters replies out of their threads, so it is worth asserting on in tests.
- **Gmail files SMTP-sent mail into Sent by itself.** Do not `APPEND` a copy over IMAP as well or
  every reply appears twice.
- **Connect per run, not per day.** The container is long-lived but only acts once each morning;
  holding an IMAP socket open for 24 hours invites half-dead connections that fail in ways a fresh
  login never would. Connect, do the run, disconnect.
- Free-account send limits are far above anything this bot does — a handful of replies a week.

### The escape hatch

Everything above sits behind the `MailClient` protocol, and `fake.py` means the tests never touch
Gmail. If the account is ever shared or audited and scoped credentials become necessary, adding a
`gmail_api.py` is one new file and a config switch — no changes to parsing, fairness, commands or
the scheduler.

Credentials come from environment variables. Never the config file, never the image, never a log
line.

---

## Send modes

Three modes, meant to be walked through in order. `mail.mode` in config, overridable with
`SCUBABOT_MAIL_MODE`:

| Mode | Parses & ranks | Writes to the DB | Sends | To whom |
|---|---|---|---|---|
| `dry-run` | yes | **no** | **no** | — renders the reply to stdout |
| `dark` | yes | **yes** | yes | **one address only** |
| `live` | yes | yes | yes | the thread's real recipients |

**`dark` is the useful one and the point of this section.** The bot does everything for real —
parses the incoming schedule, ranks, picks the crew, writes the assignment, finalizes credit the
next day — but every outbound message goes to a single address instead of the team. It is the only
way to find out whether the assignments are *right* on real emails, rather than whether the code
runs, and it does that without anyone on the team receiving a word from a bot that is still being
trusted.

Everything outbound redirects: assignment replies, command confirmations, the year-in-review
summary, and any "a human needs to look at this" message. A `/none` confirmation escaping to the
team would be exactly as confusing as an assignment escaping to them.

### What a dark message looks like

- Subject gets a `[DARK]` prefix, so a redirected message can never be mistaken for a real one.
- The body opens with a banner naming **who this would have gone to**, and the assignment follows
  unchanged. Without that, a dark soak tells you the bot sent *something* but not to whom — which
  is half the thing being tested.
- `X-Scubabot-Original-To` carries the same list as a header, for filtering.
- `In-Reply-To`/`References` are still set as they would be live, so threading behaviour is under
  test too rather than being skipped.

### Fail closed

If the mode is `dark` and no recipient is configured, the bot **refuses to send at all** and logs
an error. It must never quietly fall back to live: the whole reason dark mode exists is that the
team should not hear from the bot yet, and a fallback would break that in exactly the situation
where nobody is watching.

The recipient comes from the environment (`DARK_RECIPIENT`), not from config, because it is a real
email address and committed config in this repo holds no real addresses.

### The mode must be obvious

The opposite mistake — sitting in `dark` while believing you are live — is quieter and worse: the
team simply never gets assignments and nobody thinks to ask why a bot they have never seen has
gone silent. So the mode is logged at startup, reported by `/stats`, and stated in the banner of
every dark message.

### Dark writes to the real database, deliberately

A dark soak on real schedule emails produces real, correct state, so going live is a config flip
with the year's counts already accumulated and continuous. The cost is that a soak which produced
*wrong* assignments has also recorded them — fix those with `/worked`, or start live from a clean
database. That is a better trade than soaking against a throwaway database and then going live with
no history at all.

---

## Docker & operations

- `python:3.12-slim`, non-root user, no build toolchain in the final layer.
- Volumes, all on a TrueNAS **pool dataset** so they survive an OS upgrade:
  `data:/data` (SQLite — **primary storage**), `config:/config:ro` (tuning + `roster.yaml` from the
  private-repo checkout), and the snapshot deploy key mounted read-only.
- Long-running container, `restart: unless-stopped`, APScheduler cron trigger at 08:00
  `America/Los_Angeles`. Running on your own host is what makes this correct: the scheduler reads
  a real timezone, so 8am stays 8am across the PST/PDT switch with no manual cron edits. Set `TZ`
  explicitly in compose rather than trusting the NAS default.
- **Outbound-only.** The container needs IMAP/SMTP to Gmail, HTTPS to GHCR and to GitHub for the
  snapshot push. Nothing listens; no ports are published.
- CLI escape hatches: `run --once`, `run --dry-run`, `stats`, `db upgrade`, `db backup`.
- Logs to stdout as structured JSON; Docker handles rotation. **Redacted:** member ids and
  canonical names may appear, full email addresses and raw message bodies never do.
- `run --once` and `run --dry-run` for manual invocation; `--dry-run` forces `dry-run` mode
  regardless of config, so it is always safe to run by hand against the live mailbox.

---

## Secrets, CI/CD, and backup

### The constraint

GitHub Secrets are only decryptable inside GitHub Actions. A container on your own hardware cannot
read them at runtime. So secrets have to be *pushed* to the host, and GitHub stays the source of
truth rather than the delivery mechanism.

### Workflows

| Workflow | Repo | Runner | Trigger | Does | Secrets |
|---|---|---|---|---|---|
| `ci.yml` | public | GitHub-hosted | PR + push | `pytest`, `ruff`, `mypy`, `gitleaks`, PII check | **none** |
| `publish.yml` | public | GitHub-hosted | push to `main` | Build image, push to GHCR | built-in `GITHUB_TOKEN` |
| `roster-check.yml` | private | GitHub-hosted | PR + push | `roster.yaml` parses, required fields, no duplicate emails or aliases | none |
| `deploy.yml` | private | **self-hosted** | `workflow_dispatch` + nightly | Render `.env`, sync `roster.yaml`, `docker compose pull && up -d` | all of them |
| `snapshot.yml` | private | **self-hosted** | nightly, after the bot's run | Commit the day's `sqlite3 .dump` | `GITHUB_TOKEN` |

**Private repo secrets:** `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`, `BOOTSTRAP_ADMIN_EMAILS`, and
`DARK_RECIPIENT` while soaking (see *Send modes*). `deploy.yml` renders them into `.env` on the
host.
**Public repo secrets: none.**

That list is shorter than it would otherwise be for two reasons. There is no `DEPLOY_SSH_KEY` or
`DEPLOY_HOST`, because the runner is already *on* the host — nothing connects in. And there is no
snapshot deploy key, because committing the dump is now a workflow step using the automatic
`GITHUB_TOKEN` rather than something the container does, so **no long-lived Git credential exists
on the NAS at all**.

### Deployment — a self-hosted runner on the NAS

The host has no inbound reachability, which is exactly the case a self-hosted runner is for: it
opens an *outbound* HTTPS connection to GitHub and waits for work. No port forwarding, no VPN, NAT
irrelevant. When `deploy.yml` runs, GitHub hands the secrets to the runner, which is already
executing on the NAS — so GitHub Secrets stays the single source of truth and **rotating the Gmail
app password is editing one secret and re-running the workflow**, never touching the NAS by hand.

`deploy.yml`, on `workflow_dispatch` plus a nightly schedule:

1. Render `/mnt/<pool>/apps/scubabot/.env` from secrets, `chmod 600`.
2. Sync `roster.yaml` from the repo checkout to the config directory.
3. `docker compose pull && docker compose up -d` — a no-op unless the image digest or the rendered
   files actually changed.

**No automatic trigger from the public repo.** Having `publish.yml` poke the private repo needs a
PAT stored on the public side, reintroducing the one credential the split removes. The nightly
schedule picks up new images within a day, which is ample for a bot that ships a few times a year.

### Running the runner on TrueNAS

- **Run it as a container app**, not a systemd service. TrueNAS treats the system dataset as
  disposable across upgrades, so a service installed into the OS can vanish on an update — and the
  failure mode is the bot silently freezing on an old image rather than anything erroring.
- **Work directory and everything else on a pool dataset**: the runner's workspace, the compose
  file, `.env`, the SQLite volume, the repo checkout.
- **The runner needs the host Docker socket** (`/var/run/docker.sock`) to run `docker compose`.
  Mounting it is effectively **root on the NAS**, so anyone who can push a workflow change to the
  private repo can run anything on that box. For a single-owner private repo that is a reasonable
  trade, but it is a real one and worth knowing before it is discovered later. If it ever stops
  being acceptable, split the job: the runner writes `.env` and the compose file, and a small
  TrueNAS cron job applies them, so the runner never touches Docker.
- **Pin third-party actions to a commit SHA.** On a GitHub-hosted runner a compromised action can
  steal that job's secrets; on this one it also has your NAS.
- **Assumes TrueNAS SCALE** (Linux, Docker). CORE is FreeBSD with no Docker; there the runner and
  the bot would both live in a Linux VM, which changes only this section.

### Making staleness visible

Two ways this stalls quietly: the runner goes offline, or the nightly deploy stops firing. Both are
visible without instrumentation — an offline runner is flagged in the repo's Actions settings, and
a failed or missing scheduled run shows in the Actions tab. Two things still worth adding:

- The bot logs its **image digest and roster commit SHA at startup**, and `/stats` reports both, so
  staleness is answerable from the email interface without opening GitHub.
- GitHub disables scheduled workflows in repositories that go without activity for 60 days. Since
  snapshots now commit only when something changed, the thing keeping that clock alive is the
  **weekly** assignment, not a nightly commit — comfortably inside the window during the season,
  but a long closure with no Sundays could silently disable the nightly deploy schedule. If the bot
  goes quiet after a long break, check the Actions tab before debugging anything else.

### Backup to the private data repo

After each successful run, export and push a snapshot. **Commit a `sqlite3 .dump` text file, not
the binary `.db`** — it diffs readably, git compresses it well instead of storing an opaque blob
per night, and restoring never depends on SQLite file-format compatibility. The binary stays the
live database on the volume; the dump is the durable copy.

- Push to `snapshots/` in **`scuba-bot-9000-data`**, on its own branch so nightly commits never
  clutter that repo's history either.
- **Current year only.** At rollover, after the summary email is sent and the first assignment of
  the new year is made, the branch is replaced with a **fresh orphan branch** holding just the
  latest dump. Deleting the files is not enough — git keeps old commits, so a `git rm` would leave
  every purged year sitting in the repo forever and make the purge cosmetic. Recovery never wants
  a snapshot from last March anyway; restoring one would reintroduce stale counts.
- **Committed by `snapshot.yml` on the self-hosted runner, not by the container.** The bot writes
  the dump to the dataset and stops there; the workflow commits it using the automatic
  `GITHUB_TOKEN`. That keeps every Git credential inside a job GitHub scopes and expires, rather
  than a long-lived deploy key sitting on the NAS, and the container then needs no access to
  GitHub at all.
- **Only commit when something meaningful changed.** Most days are a no-op: the bot checks the
  mailbox, finds no new schedule email and no replies, and stops. Those days must produce no commit
  at all — not an empty one, not a timestamp-only one.

  The catch is that a naive dump changes *every* day regardless, because the run itself writes a
  `runs` row. So **the dump excludes `runs`**, and the workflow commits only if `git diff --quiet`
  says the file actually differs. `runs` is operational telemetry — it drives missed-run catch-up
  and nothing else — and the worst consequence of it being absent from a restore is one extra
  catch-up run. Everything that matters for fairness, identity or audit is still in the dump.

  With that in place, a quiet week is genuinely silent and every commit in `snapshots/` corresponds
  to something real: an assignment, a credit, a roster change, a correction.
- `db restore <file>` CLI command, and **test it** — an untested backup is not a backup.
- `db export-roster` regenerates `roster.yaml` from the live DB; commit it whenever the roster
  changes so the rebuild recipe stays current.

> **The dump is the most sensitive artifact in the project.** It carries names, email addresses and
> `schedules.raw_body` — entire inbound emails, including whatever the sender wrote above the name
> list. It goes to the private repo and nowhere else. There is no scrubbing step that makes it safe
> to publish, and no reason to try.

---

## Build order

1. **Repo split and guardrails.** Create the private data repo, write the `.gitignore`, and wire
   the PII check plus `gitleaks` into CI **before any roster exists**. Doing this first costs an
   hour; retrofitting it after one real name is committed costs a history rewrite and a rotation of
   anything else that leaked alongside it.
2. **Config, DB, fairness engine** — pure logic plus tests. No email at all.
3. **Mail client + schedule parsing + assignment reply** — end to end on the fake client first.
   Before writing the parser, collect **3–5 real schedule emails** into the *private* repo's
   `fixtures/`. The block/preamble/decoration rules above are inferred from a description; real
   messages are what turn them into a spec. The public suite gets synthetic equivalents.
4. **Command parsing and handlers** — including auth and quoted-text stripping.
5. **Docker, scheduler, catch-up, structured logging with redaction.**
   Includes the **year rollover** — summary email, purge, snapshot reset — which is easiest to get
   right while it can still be tested against a throwaway database.
6. **CI, image publishing, the self-hosted runner, `deploy.yml`, DB snapshot + restore.**
7. **Soak: `dry-run` for a week, then `dark` for two or three real Sundays, then `live`.** Dark is
   where the assignments get checked against what a human would have chosen, on real emails, with
   nobody on the team receiving anything.

---

## Verification

**Unit / logic**
- `pytest` over `fairness.py`: leave windows, ties, fewer-than-3 eligible, zero eligible.
- **Year-long simulation** — synthesize 52 Sundays with a realistic roster and assert the spread
  between the most- and least-assigned member stays within 1–2 sessions, **and that no member is
  assigned on consecutive sessions**. This is the test that actually proves the product requirement.
- **Cooldown tests** — (a) normal roster: assert zero back-to-back assignments and zero waivers;
  (b) three-person roster: assert the waiver fires, is recorded on the assignment, and is named in
  the reply body; (c) a `/none` week does not clear the previous session's cooldown; (d) serving as
  backup does not put anyone on cooldown.
- **Leave test** — member out 12 weeks; assert on return they are not assigned more often than
  peers over the following month.
- **Idempotency** — feed the same schedule email twice; assert exactly one assignment and one set
  of credits.
- **Quiet day is silent** — run with an empty mailbox, then with a mailbox holding only an
  unrelated message. Assert in both cases that the exported dump is byte-identical to the previous
  one, so no snapshot commit is produced, and that no email is sent.
- **Command auth** — unknown sender refused; non-admin member refused for `/add-member` but allowed
  for `/stats`; quoted `/none` in a reply body is ignored.
- **Subject parsing** — `Aquarium Sunday 03/08/2026`, `Re: Fwd: aquarium sunday 3-8-26`, a subject
  with no date, and a date that isn't a Sunday. Each resolves to the documented fallback and flags
  what it assumed.
- **Body parsing** — the highest-risk code in the project, so test it against real emails, not only
  synthesized ones. Real messages live in the private repo's `fixtures/` and run under
  `pytest -m realdata`; the public suite carries synthetic equivalents of each case below, written
  against the invented roster in `config.example.yaml`. Both assert the expected attendee list:
  - Two-block email → only the **first** block's names are returned; nobody from the second block
    appears anywhere in the assignment.
  - Multi-line preamble above the first header → discarded entirely, including a preamble that
    itself mentions a date in prose ("deep clean on 3/15").
  - Header variants — `Sunday 03/08/2026`, `SUNDAY 3/8`, `3-8-26`, `March 8th` — all recognized; a
    yearless header resolves against the message `Date:` header.
  - Real attendee lines — `Nadia`, `Betsy Swift`, `Owen (5B)`, `Betsy - maybe`,
    `Nadia from Saturday`, `The return of Betsy Swift` — each resolve to the right single member,
    and `Betsy - maybe` resolves identically to `Betsy`.
  - Longest match wins — `The return of Betsy Swift` yields Betsy Swift once, never Betsy twice.
  - Two names on one line → both members returned; the same member on two lines → counted once.
  - No substring matches — a member named Sam is not matched by a line reading `Samantha`.
  - **First-name collision** — add a second Nadia to the roster, then assert a bare `Nadia` stops
    matching, lands in `unmatched_names`, and the reply names the collision. This guards a rule
    that is currently vacuous and will silently start mattering the day the roster changes.
  - `ambiguous_tokens` — a member named `May` is not matched by `Sunday in May`.
  - A line with no roster name (`Bring the good brushes`) → unmatched, never assigned.
  - HTML-only body → converted with line breaks preserved, producing the same list as its plain-text
    twin.
  - Signature and quoted reply history below the last block → trimmed, contributing no names.
  - Zero date headers → falls back to whole-body parsing with the subject date, and flags it.
  - First block with no roster matches → no assignment written; reply contains the parsed raw lines.
- **Guest exclusion** — a name absent from the roster is stored with `member_id NULL`, never
  assigned, and surfaced in `unmatched_names`; a *misspelled* roster name follows the same path and
  is named in the reply, which is the only thing that makes the mistake catchable.
- **Multi-address identity** — the same member sending from a second registered address is
  recognized and authorized.
- **Threading** — assert a generated reply carries `In-Reply-To` and a `References` chain built
  from the message it answers. IMAP has no native thread id, so a mistake here does not error, it
  just scatters replies out of their threads where nobody notices for weeks.

**Year rollover** — it runs once a year, so it will never be debugged in production; the tests are
the only place it is ever exercised before it matters.
- **Order** — simulate a December session followed by the first Sunday of January. Assert whoever
  worked in late December is **not** assigned on the first shift of the new year, proving the
  cooldown saw last year's data because the assignment ran before the purge.
- **Idempotency** — run the rollover twice. Assert exactly one summary email, one purge, one
  `year_rollovers` row.
- **Failed send blocks the purge** — make the summary send fail. Assert nothing is deleted, no
  `year_rollovers` row is written, and the next run retries and succeeds. This is the test that
  keeps a mail outage from turning into permanent data loss.
- **Purge scope** — assert prior-year sessions, schedules, assignments, unmatched names, command log
  and runs are gone, while members, aliases and emails are untouched.
- **Leave across the boundary** — a member with an open-ended leave, and one whose leave ends in
  March, both survive the purge and stay ineligible afterwards.
- **`processed_messages` retention** — assert rows inside the rolling window survive the purge, and
  that re-feeding a December email after rollover produces no second reply.
- **First shift of January** — give members different session counts across the closing year, then
  roll over. Assert the two assigned on the first Sunday are the two who cleaned *least* last year,
  and that the ordering came from `prior_year_ratio` rather than from names.
- **Leave does not distort January** — a member on leave for the last quarter of the closing year is
  **not** pushed to the front in January. This is the test that proves a ratio was carried rather
  than a date; carrying `last_session_date` alone would fail it.
- **Carry-over is written before the assignment**, not after: assert the first January assignment
  used the closing year's numbers, not the previous rollover's stale ones.
- **A member who joined in December** ranks as prior ratio zero and is assigned early rather than
  sorted last.
- **Summary content** — assert the emailed totals match the database as it stood immediately before
  the purge, per member and in aggregate.
- **Snapshot reset** — assert the snapshots branch afterwards has a single commit whose history
  contains no dump from a prior year.

**Integration (fake mail client)**
- Schedule email → correct 2+1 reply body, guests excluded, unmatched names logged and named in
  the reply, second date block ignored.
- Schedule email from an unknown address → still processed; a command from that address → refused.
- `/worked` after finalization moves credit and leaves totals consistent.
- Missed-run catch-up: set the clock forward two days, assert the pending Sunday finalizes.

**Manual, before going live**
1. `docker compose run --rm bot run --once --dry-run` against the real inbox; confirm the date it
   chose, the block it read, the parsed roster, and the rendered reply are all correct. The
   dry-run output should print the chosen block verbatim next to the names it extracted — that
   side-by-side is what makes a parsing bug obvious instead of subtle.
2. Send a test schedule email to the account, let it reply for real, then exercise `/stats`,
   `/none`, and `/worked` from an admin address. Confirm the reply lands **in the same thread**,
   and that Gmail's Sent folder holds exactly one copy of it, not two.
3. Restart the container mid-week and confirm catch-up fires exactly once.

**Send modes**
- **Dark redirects everything** — drive a full cycle (schedule email, a command reply, a rollover
  summary) in `dark` and assert every outbound message went to the dark recipient and **no member
  address appears in any `To` or `Cc`**.
- **The banner is accurate** — assert it names the recipients the message would have had live.
- **Dark still writes** — assert the assignment, slots and finalized session rows are identical to
  what `live` would have produced.
- **Fail closed** — set `dark` with no `DARK_RECIPIENT` and assert the bot sends nothing and logs
  an error, rather than falling back to live.
- **Dry-run writes nothing** — assert no rows change and no mail is sent, even for a schedule email
  that would otherwise create an assignment.
- **Mode is visible** — assert `/stats` reports the current mode.

**Privacy**
- **PII check, tested both ways** — assert the CI job fails on a commit containing an email-shaped
  string outside `config.example.yaml`, a `roster.yaml`, or a `.db` file, *and* passes on a clean
  tree. A guard nobody has watched fail is not known to work.
- **Log redaction** — run a full cycle against the fake client and assert no full email address and
  no raw message body appears anywhere in captured log output.
- **Public-suite isolation** — with the private repo absent, the whole public test suite passes and
  `pytest -m realdata` reports as deselected rather than failing.
- **Standing sweep** — the repo is already public, so this is periodic rather than a one-time gate:
  run the PII check over `git log --all -p`, and confirm no `snapshots/`, `roster.yaml` or real
  email body has reached this repo on any branch.
- **Snapshot key scope** — confirm the snapshot deploy key can push to the private repo and
  *cannot* reach the public one.

**Deploy & backup**
- Run `deploy.yml` from the Actions tab; confirm `.env` lands `600`, `roster.yaml` syncs, and the
  container comes up on the new image. Re-run it unchanged and confirm it is a no-op.
- Grep the container logs **and the Actions run log** for the Gmail password — it must appear in
  neither, and GitHub should have masked it in the job output.
- Reboot the NAS. Confirm the runner reconnects on its own and the bot restarts — an offline runner
  after a reboot or a TrueNAS upgrade is the most likely way this setup breaks.
- **Runner scope:** confirm the runner is registered to the private repo only, and grep both repos
  for `runs-on: self-hosted` — it must never appear in the public one.
- **Staleness check:** disable the nightly schedule, publish a new image, and confirm `/stats` still
  reports the old digest, so a stall is answerable from email as well as from the Actions tab.
- **Restore drill:** take a snapshot, delete the live `.db`, run `db restore`, and confirm
  `/stats` returns identical numbers. Do this before the bot has a year of history worth losing.
- **Rebuild-from-recipe drill:** with no snapshot at all, boot an empty DB against `roster.yaml`
  alone and confirm the roster comes back intact. This is what proves `db export-roster` is being
  kept current rather than quietly rotting.
