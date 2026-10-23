---
name: agy
description: Delegate work to Google Antigravity CLI (agy, Gemini models) using the user's several saved Google accounts — the account with the most quota left is picked automatically and the next one is tried when a limit runs out. Use when the user asks to use agy / Gemini / Antigravity, wants a second opinion or review from Gemini, wants to save Claude usage by handing off a self-contained task, or asks about agy account limits, quota, or switching agy (Gemini) accounts.
---

# agy (Gemini) with several Google accounts

The user's agy logins are managed by **usage-bar-windows** (`agy-acc`). Run every command below with the Bash tool exactly as written (the path is filled in at install time):

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

## 2. Delegate a task to agy

```bash
python "{{APP}}" acc run "PROMPT"
python "{{APP}}" acc run --file /path/to/prompt.txt     # long prompts, quotes, newlines, & | < > %
python "{{APP}}" acc run --group claude "PROMPT"        # choose by the Claude & GPT limit instead of Gemini
python "{{APP}}" acc run --account agy2 "PROMPT"        # a specific account
```

`run` picks the account with the lowest usage, switches agy to it, runs `agy -p PROMPT` in the **current directory**, streams agy's answer to stdout, and moves to the next account if agy reports an exhausted quota. A line on stderr says which account was used (`[agy-acc] agy2 (…@gmail.com) …`).

Exit codes: `0` done · `2` bad usage / agy not found · `3` every account is out of quota (show the user `acc quota`, including reset times) · `4` agy or the Antigravity app is open and the current account can't be used — ask the user to close them (`/quit`).

### How to delegate well
- **agy does not see this conversation.** Write a self-contained prompt: goal, relevant file paths, constraints, and the exact output format you want back.
- agy is an agent: it can read **and edit** files in the current directory. For questions, reviews and research, say explicitly in the prompt: *"Do not modify any files; only answer."* Let it edit only when the user asked agy to make the change, and then review the result yourself (`git diff`) before reporting.
- Prefer `--file` (write the prompt to a temp file first) whenever the prompt is long or contains quotes, newlines or shell metacharacters.
- agy can take minutes: give the Bash call a long timeout (up to 600000 ms) or run it in the background.
- Treat agy's answer as a second opinion: check important claims against the code before acting on them, and tell the user what came from agy and from which account.
- Never run plain interactive `agy`, `agy-acc add` or `agy-acc login` yourself — they need the user's browser and terminal. Never use `/logout` (it can revoke a saved account's token).

## 3. Account management — the user runs these in their own terminal

| Command | What it does |
|---|---|
| `agy-acc list` | saved accounts and their gmail (`*` = active) |
| `agy-acc add NAME` | add another gmail (agy opens → sign in → `/quit`) |
| `agy-acc login NAME` | sign an account in again (`needsLogin`) |
| `agy-acc use NAME` | make agy / Antigravity use NAME |
| `NAME` (e.g. `agy1`) or `agy-acc open NAME` | switch to NAME and open agy |
| `agy-acc rename OLD NEW`, `agy-acc email NAME GMAIL`, `agy-acc remove NAME` | housekeeping |
| `agy-acc doctor` | troubleshooting (no secrets printed) |

You may run `acc use NAME` yourself when the user asks to switch accounts; it refuses while agy is open.
