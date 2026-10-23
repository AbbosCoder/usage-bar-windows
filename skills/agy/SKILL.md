---
name: agy
description: Use Google Antigravity CLI (agy, Gemini models) as a coding subagent that edits the project itself — creating, changing and deleting files — so Claude saves its own usage by handing well-scoped parts of a task to agy and then reviewing the result. The user's several saved Google accounts are rotated automatically (most quota left first, next one when a limit runs out). Use when the user asks to use agy / Gemini / Antigravity, wants to save Claude limits, wants a second opinion or review from Gemini, or asks about agy account limits, quota, or switching agy (Gemini) accounts.
---

# agy (Gemini) as Claude's coding subagent

The user wants agy to work as **your subagent**: they give the task to you, you decide which parts agy does, agy does them directly in the project (create / edit / delete files, run commands), and you review and finish. The point is to spend fewer Claude tokens. The user's agy logins are managed by **usage-bar-windows** (`agy-acc`). Run every command below with the Bash tool exactly as written (the path is filled in at install time):

```bash
python "{{APP}}" acc <command>
```

Reply to the user in the language they write in (usually Uzbek).

## 1. Check limits

```bash
python "{{APP}}" acc quota            # table: account, gmail, Gemini 5h/week, Claude&GPT 5h/week, state (* = active)
python "{{APP}}" acc quota --json     # same as JSON: name, email, active, needsLogin, error,
                                      # gemini/claude {five, week: {used %, resets}}, geminiUsed, claudeUsed
python "{{APP}}" acc quota --refresh  # check every account again first (slower: runs agy once per account)
```

Numbers are **% used** (100 = exhausted). `needsLogin: true` means that account must be signed in again by the user.

## 2. Run agy

```bash
cd "<project root>" && python "{{APP}}" acc run --file /path/to/prompt.txt   # the usual form
python "{{APP}}" acc run "PROMPT"                        # short prompts without quotes/newlines
python "{{APP}}" acc run --group claude --file p.txt     # choose by the Claude & GPT limit instead of Gemini
python "{{APP}}" acc run --account agy2 --file p.txt     # a specific account
python "{{APP}}" acc run --read-only --include src/a.py:120-180 "PROMPT"   # answer only, no tools at all
```

- agy works in the **current directory** with **all tools pre-approved** (`--dangerously-skip-permissions`): it reads, creates, edits and deletes files and runs commands on its own. So always `cd` to the project root first and never run it from a folder it must not touch.
- `--read-only` gives agy no tools (it can't even read files): put the code in the prompt with `--include PATH[:START-END]` (repeatable; whole prompt under ~30 000 characters). Use it for pure questions where you want a guarantee nothing changes.
- `run` picks the account with the most quota left, switches agy to it, streams agy's answer to stdout and moves to the next account if a quota runs out. A line on stderr says which account was used (`[agy-acc] agy2 (…@gmail.com) …`).
- agy can take minutes: give the Bash call a long timeout (up to 600000 ms) or run it in the background.

Exit codes: `0` done · `2` bad usage / agy not found · `3` every account is out of quota (show the user `acc quota`, including reset times, and do the work yourself) · `4` agy or the Antigravity app is open and the current account can't be used — ask the user to close them (`/quit`).

## 3. How to use agy as a subagent

**What to hand off** — well-scoped work whose result you can check quickly: implementing a function or module to a spec, boilerplate and scaffolding, writing or extending tests, mechanical refactors and renames across files, docs and comments, translating code, fixing a bug you already located. Keep for yourself: understanding the request, design decisions, anything needing this conversation's context, and final review. Several independent pieces can be separate `run` calls, one after another (agy edits the same working tree — never run two at once in one folder).

**Before** — run `git status --short` so you can tell agy's changes from existing ones (if the tree is dirty, note which files already had changes). In a folder without git, list the relevant files first.

**The prompt** — agy does not see this conversation. Write it to a temp file and pass `--file`. Include:
1. The goal and the exact scope: which files to create / change / delete, and that it must not touch anything else.
2. The relevant context: file paths to read, function names, conventions to follow (agy can read files itself).
3. Constraints: "Do not run git commit, push, reset, checkout or any other git command that changes history or branches. Do not install packages or change config unless told. Work only inside this folder."
4. How to verify, if there is a cheap check (e.g. "run `python -m pytest tests/test_x.py` and fix failures").
5. What to report back: a short list of files changed and anything left undone.

**After** — you are responsible for the result:
1. `git status --short` and `git diff` (plus new untracked files): read what agy actually did; don't trust its summary alone.
2. Revert or fix anything outside the scope or wrong (for a file agy broke, `git checkout -- FILE` only if it had no earlier uncommitted changes of the user's).
3. Run the project's tests / checks yourself.
4. Tell the user which parts agy did, with which account, and what you changed after it.

**Second opinions / reviews** — same command; say in the prompt *"Do not modify any files; only answer."*, or use `--read-only` with `--include` when nothing may change.

**Never** run plain interactive `agy`, `agy-acc add` or `agy-acc login` yourself — they need the user's browser and terminal. Never use `/logout` (it can revoke a saved account's token).

## 4. Account management — the user runs these in their own terminal

| Command | What it does |
|---|---|
| `agy-acc list` | saved accounts and their gmail (`*` = active) |
| `agy-acc add NAME` | add another gmail (agy opens → sign in → `/quit`) |
| `agy-acc login NAME` | sign an account in again (`needsLogin`) |
| `agy-acc save NAME` | save the login agy has now (e.g. after agy refreshed its token: "hozirgi login hech qayerda saqlanmagan") |
| `agy-acc use NAME` | make agy / Antigravity use NAME |
| `NAME` (e.g. `agy1`) or `agy-acc open NAME` | switch to NAME and open agy |
| `agy-acc rename OLD NEW`, `agy-acc email NAME GMAIL`, `agy-acc remove NAME` | housekeeping |
| `agy-acc doctor` | troubleshooting (no secrets printed) |

You may run `acc use NAME` yourself when the user asks to switch accounts; it refuses while agy is open.
