# Axiomatic Teaching

A Textual TUI that sits between a human learner and [Grok Build](https://docs.x.ai/build/overview), driven exclusively over the Agent Client Protocol (ACP). The TUI is the only learner-facing UI. Knowledge is banked if and only if the MCP tool `record_lesson_success` accepts evidence that satisfies the lesson's success criterion stored in SQLite.

There is no “mark complete” button. Completions, concepts, style notes, and FSRS cards are written only when the success gate passes.

## Requirements

- Python 3.12+
- For live study sessions: `grok` on PATH and authenticated
- Works without Grok in `--demo` (echo agent)

## Install

Python 3.12 or 3.13. From the repository root (use the same interpreter you will run):

```bash
py -3.13 -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:    source .venv/bin/activate
pip install -e ".[dev]"
```

## Run

```bash
axiomatic-teach
python -m axiomatic_teaching
axiomatic-teach --demo
```

Optional flags:

```text
axiomatic-teach [--db PATH] [--demo] [--agent grok|echo] [--grok-bin PATH]
```

`--demo` sets demo mode and forces the echo agent so the TUI starts without spawning Grok. The echo agent is for layout and keyboard practice only: it does **not** call `record_lesson_success` and cannot bank a lesson. If `grok` is missing and you are not in demo/echo mode, the CLI prints a warning; the TUI can still start and show that ACP is disconnected.

Default SQLite path is `%LOCALAPPDATA%\AxiomaticTeaching\axiomatic.db` on Windows, or `$XDG_DATA_HOME/AxiomaticTeaching/axiomatic.db` (else `~/.local/share/AxiomaticTeaching/axiomatic.db`) on Unix. Override with `--db` or `AXIOMATIC_DB`.

## Create a lesson

From Home, press `n` to open the new-lesson form.

1. Title and topic are required.
2. An optional short success description (“what success looks like”, one or two sentences). Leave it blank to use a default: the learner can explain the core ideas in their own words and apply them to a simple example.

The app derives a single required criterion automatically: keywords from the success description (or from the title and topic if it was left blank), plus a default minimum evidence length of 50 characters of the learner’s own words. Confirm → the lesson is stored as `active`.

The TUI does not bank a lesson; only `record_lesson_success` does.

## Study

From Home, select an active lesson and press Enter or `s`.

- The TUI starts an ACP session with Grok Build: `grok agent --always-approve stdio` (or the echo agent in `--demo`).
- `session/new` attaches the axiomatic MCP server (stdio) and injects a small pedagogical context: the current success criterion, a few related **banked** lessons, 1-hop connections, style notes, and due reviews (hard-capped; the current criterion is never truncated; long descriptions are capped).
- A short kickoff prompt asks Grok for one diagnostic question and to wait. Subsequent input is `session/prompt`.
- The center pane streams agent text, dim thought lines, and tool-call cards (`record_lesson_success` is highlighted). The right pane shows the success description, the derived min-chars/keywords, and the last gate result. A failed gate marks the criterion ✗ (never a false all-green). Older lessons that still have more than one criterion are listed the same way.

Session working directory is a per-lesson folder under the app data dir (`lessons/<id>/`), not this repository.

## `record_lesson_success`

This MCP tool is the only writer of banked knowledge. Grok must pass `criterion_id` values from `get_lesson_criteria` (do not invent ids). The server also reads `AXIOMATIC_LESSON_ID`; if the payload `lesson_id` disagrees, the call is rejected.

**Pass only when all of the following hold:**

- The lesson exists and is `active` (drafts cannot be banked).
- Every **required** criterion has a corresponding evidence item (new lessons have one auto-derived required criterion; older lessons may still have more than one).
- Each evidence `text`, stripped, is at least `min_evidence_chars` (50 for auto-derived criteria; 40 is the model default).
- If a criterion has `keywords`, every keyword appears in the evidence text (case-insensitive, whitespace-normalized substring).
- `met` is `true` for required items (`met: false` is an automatic reject).
- Legacy optional criteria may be omitted; if provided, they still must meet length, keywords, and `met`.
- Unknown `criterion_id`s are ignored (not a failure) and do not satisfy anything.
- Empty evidence fails.

**On pass** (one SQLite transaction): insert the completion, mark the lesson `completed`, upsert proposed concepts/relations, insert a style note if non-empty, and create an FSRS card. **On fail:** return structured `unmet` reasons and write **no** completion, concepts, or style notes. Lessons cannot be marked completed through any other write path (`save_lesson` is rejected).

Review cards show the success description and a short evidence snippet so rating is retrieval, not a title click.

A second successful call returns `already_banked` and does not insert another completion. Concurrent double-calls serialize on SQLite and also return `already_banked` rather than erroring.

The gate checks the evidence payload against the stored criteria. It cannot prove that the text was spoken by the learner — that honesty rule is in the pedagogy injected into Grok. Short or keyword-missing payloads are still rejected, including over a live Grok ACP session.

Read-only companion tools: `get_lesson_criteria`, `list_banked_lessons`, `get_connections`. Learners never invoke these; Grok does, through the TUI session.

## Configuration

| Variable / flag | Meaning |
|-----------------|--------|
| `AXIOMATIC_DB` / `--db` | SQLite database path |
| `AXIOMATIC_HOME` | App data directory (database default, logs, per-lesson workspaces) |
| `AXIOMATIC_AGENT` / `--agent` | `grok` (default) or `echo` |
| `AXIOMATIC_GROK_BIN` / `--grok-bin` | Grok executable path (default: `grok` on PATH) |
| `AXIOMATIC_LESSON_ID` | Set by the ACP client on the MCP process; `record_lesson_success` must match this lesson |
| `--demo` | Demo mode: `Settings.demo=True` and agent `echo` |

## Tests

```bash
pytest
axiomatic-teach verify
python scripts/verify_critical_path.py
```

`axiomatic-teach verify [--db PATH]` is the product acceptance test. It uses a temporary SQLite file (unless `--db` is given), creates a lesson from title/topic plus a short success description, rejects insufficient evidence (too short / missing keywords), banks sufficient evidence, then asserts `already_banked` on a third call. No TUI and no Grok.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `n` | New lesson (from Home) |
| Enter / `s` | Study the selected active lesson |
| `k` | Knowledge (banked lessons, concepts, relations) |
| `r` | Review (due FSRS cards) |
| `?` | Help |
| `q` | Quit |
| Ctrl+S | Study: send input |
| Ctrl+Enter | New lesson: create |
| Ctrl+C | Study: cancel the in-flight ACP turn |
| Ctrl+Q / q | Quit (study unmount shuts the ACP child down, including the Windows process tree) |
| Esc | Study: back (shuts down the session) |

## License

[GNU Affero General Public License v3.0](LICENSE) (`AGPL-3.0-or-later`).
