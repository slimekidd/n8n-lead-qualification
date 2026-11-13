# AI Lead Qualification Pipeline — n8n + PostgreSQL + Gemini

A production-grade lead intake system: a lead arrives via webhook, an LLM classifies the request, the lead is scored by budget, saved to Google Sheets and pushed to the sales manager in Telegram. Every step is idempotent, every failure is retried or escalated, and nothing fails silently.

[![Watch the 1-minute demo](https://img.youtube.com/vi/VKCVVxkX0J8/maxresdefault.jpg)](https://youtu.be/VKCVVxkX0J8)

**▶ [1-minute demo](https://youtu.be/VKCVVxkX0J8):** a lead arrives, the AI provider goes down mid-run, and the lead is still delivered on the second attempt with no human involved.

**Why it's different from a typical "webhook → LLM → Telegram" flow:**
- 🔁 Temporary failures are retried automatically: up to 3 times, with a Telegram alert on each
- 🔒 No duplicate rows or messages, even on retries and parallel runs (atomic claim + idempotency flags)
- 🩺 Leads stuck after a crash are found and recovered by a monitor that checks the real execution status

> Built as a reference implementation. Four workflows, one PostgreSQL table, ~55 nodes. Every failure scenario below was reproduced and verified against the database, not just the n8n UI.

---

## What a business gets

| Pain | How this pipeline solves it |
|---|---|
| Leads from the website land in email and get lost | Every lead is stored in PostgreSQL with a status, and the manager gets a Telegram message within seconds |
| Manager wastes time on low-budget requests | Each lead is scored High / Medium / Low by budget and labelled by an LLM (e.g. "CRM integration", "Telegram bot") |
| An API hiccup (Gemini, Google, Telegram) means a lost lead | Temporary errors (503, 429, timeout) are retried automatically up to 3 times, 10 minutes apart |
| A crashed server leaves leads half-processed | A monitor finds anything stuck for 10+ minutes, inspects the real execution and either completes it or schedules a retry |
| Retries create duplicate rows / duplicate messages | Sheets and Telegram steps check the database before acting; re-running a lead never duplicates output |
| Nobody knows when something broke | Every failure path ends in a Telegram alert: workflow error, stuck lead, unreachable API, skipped retry |

---

## Architecture

```
                    ┌──────────────────────────────────────────────────────────────┐
  Webhook ─────────►│  AI Lead Qualification                                       │
  (new lead)        │  validate → insert (dedupe) → Gemini classify → score        │
                    │  → Sheets (if not saved) → Telegram (if not sent) → complete │
  Retry Processor ─►│  retry branch: atomic claim → same pipeline                  │
                    └───────────────┬───────────────────────────┬──────────────────┘
                                    │ error                     │ status in DB
                                    ▼                           ▼
                    ┌───────────────────────┐     ┌─────────────────────────────┐
                    │ Error Handler         │     │ PostgreSQL  leads           │
                    │ mark failed, classify │────►│ status / retry_count /      │
                    │ temporary vs permanent│     │ execution_id / flags        │
                    │ Telegram alert        │     └──────┬──────────────┬───────┘
                    └───────────────────────┘            │              │
                                                         ▼              ▼
                                      ┌──────────────────────┐  ┌─────────────────────────┐
                                      │ Lead Retry Processor │  │ Stuck Leads Monitor     │
                                      │ every minute:        │  │ every minute:           │
                                      │ failed + due → retry │  │ processing > 10 min →   │
                                      │ one lead at a time   │  │ inspect execution via   │
                                      └──────────────────────┘  │ n8n API → complete or   │
                                                                │ recover, alert once     │
                                                                └─────────────────────────┘
```

### Lead lifecycle

```
processing ──success──► completed
    │
    ├─ error (temporary) ──► failed + next_retry_at ──► Retry Processor ──► processing (retry_count+1)
    ├─ error (permanent) ──► failed, no retry, alert
    └─ stuck > 10 min ──► Monitor ──► completed (work was done) / failed + retry (work was not done)
```

---

## Engineering decisions worth noting

**Atomic claim for retries.** A retry is claimed with a single `UPDATE … WHERE status='failed' AND next_retry_at <= NOW() … RETURNING`. Check and take happen in one statement, so two processes can never retry the same lead. If the row was taken by someone else, the sub-workflow returns `not_claimed` and leaves it alone.

**Ownership by `execution_id`.** The DB row always carries the n8n execution that owns it. Every state-changing query filters on it, so a late or duplicate execution cannot overwrite a newer state. The monitor uses it to ask n8n "did this execution actually finish?" instead of guessing.

**Idempotent side effects.** `sheets_saved` and `telegram_sent` flags are checked before each external call and set right after. Re-running a lead three times produces one row and one message.

**No silent dead ends.** Every branch that could end with zero items has either `Always Output Data`, a Set node that returns a result, or a Telegram alert on the error output. The loop in Retry Processor can't be killed by one bad lead.

**Error classification by text.** The Error Handler decides temporary vs permanent by matching `503 / 429 / timeout / temporarily unavailable` in the error message. Simple, transparent, easy to extend.

---

## Verified scenarios

| Scenario | Result |
|---|---|
| New lead via webhook | `completed`, row in Sheets, Telegram message |
| Duplicate `lead_id` | ignored at insert, no side effects |
| Temporary error (503) | retried after 10 min → `completed`, `retry_count = 1` |
| Permanent error (invalid model) | `failed`, no retry, alert |
| Retry limit | `retry_count = 3` is never picked up |
| Race: lead taken by another process before retry | sub-workflow returns `not_claimed`, row untouched, queue continues |
| Crashed execution left lead in `processing` | Monitor → `recover` → Retry → `completed` |
| Manually cancelled execution | Error Handler marks `failed`; Monitor also handles `canceled` as fallback |
| Monitor can't reach n8n API (404) | one alert, no spam, lead flagged for manual check |
| Three leads in retry queue, first one fails | all three processed, loop not interrupted |

---

## Stack

n8n (self-hosted, Docker) · PostgreSQL 17 · Google Gemini (via n8n AI Agent + Structured Output Parser) · Google Sheets · Telegram Bot API · n8n REST API

---

## Setup (for reuse)

1. Create the `leads` table (schema in `schema.sql`).
2. Import the four workflows from `workflows/*.json`.
3. Create credentials: Postgres, Telegram Bot, Google Sheets OAuth2, Google Gemini API, Header Auth (webhook key), n8n API.
4. Replace placeholders: `YOUR_TELEGRAM_CHAT_ID`, `YOUR_GOOGLE_SHEET_ID`, `YOUR_N8N_HOST`.
5. In **Lead Retry Processor** → `Retry Lead Processing`, select your imported AI Lead Qualification workflow. In **Stuck Leads Monitor** → `Recovery Decision`, set `MAIN_WORKFLOW_ID` to its ID.
6. Set **Error Handler** as the Error Workflow in AI Lead Qualification and Lead Retry Processor settings.
7. Activate all four.

Webhook payload:
```json
POST /webhook/new-lead   (header X-API-Key: <your key>)
{ "lead_id": "site-1042", "name": "Jane Doe", "company": "Acme", "budget": "2500", "request": "Need a Telegram bot for support" }
```
