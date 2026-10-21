# stretchserve

**Serve a directory of stretchable markdown.** Agents (or you) write `.md`
files in which `{{short|long}}` marks a stretch: the page shows the short
form, hovering shows a preview floating above the pointer, a click grows it
into the long form in place and pins it open, and the words already read
never move. Ted Nelson's stretchtext (1967), served over HTTP.

Built on the semantics proven by [cc-stretch](https://github.com/pro-vi/cc-stretch)
(vendored in explorations at `vendor/cc-stretch`); its `parse.ts` is ported
here to Python. Python-first on purpose: `uv run` is all you need. The
scanner is the part worth porting to Rust later.

## Quickstart

```
uv run stretchserve serve docs      # binds to the LAN: ethernet if plugged in, else wifi
                                    # (--host 127.0.0.1 for local only)
uv run stretchserve check docs      # validate the stretch markup
uv run stretchserve mcp docs        # MCP server (stdio)
uv run pytest                       # test the scanner/renderer
```

For hosting without a server, `build` pre-renders the whole tree to a
static site — same renderer, done once — and the output deploys to any
static host (Cloudflare Pages, R2, S3, GitHub Pages):

```
uv run stretchserve build docs -o dist   # writes dist/ with .html pages + assets
npx wrangler pages deploy dist           # e.g. Cloudflare Pages
```

Links written as `[text](page.md)` are rewritten to `.html`, and
directories without an index get a generated listing page.

## Serving gzero

`stretchserve mcp [dir] --gzero` runs the same MCP surface over the
gzero stores, **read-only** (mutations stay with the gzero CLI and
gzero-mcp; the write tools aren't registered):

- `gzero/ws/<name>.md` — workflow sections of the project at `[dir]`
- `gzero/items/<id>.md` — work items: status, design, acceptance, notes
- `gzero/atoms/<scope>.md` — the atom store as a brief, grouped by node

Sections and items are read via the gzero CLI's JSON modes (`ws
list/show --json`, `item list/show --json`, run with `[dir]` as cwd);
atoms come straight from the SQLite store (`CX_DB`, default
`~/.pi/agent/context.db`). The skim/read views and validation work on
all of it — so as gzero sections adopt `{{short|long}}`, agents get
progressive disclosure there for free.

## MCP server

`stretchserve mcp [dir]` runs a stdio MCP server over the workspace —
the same directory the HTTP server can render. Seven tools:

- `list_documents` — title, stretch counts, issue counts per file
- `read_document(path, mode, open_keys)` — `source` (raw), `skim`
  (default: braces stripped, complete prose), or `read` (the stretches
  named in `open_keys` grown; opening a key opens its ancestors). Keys
  match exactly, by suffix, or uniquely by substring. Every response
  ends with an appendix of closed stretch keys, so a reader can decide
  what to open next — the feedback loop cc-stretch gives a model.
- `create_document` / `write_document` / `edit_document` / `delete_document`
  — content is validated on write; with `strict=true` (default) hard
  errors (unclosed, growth-rule violations, blank-line crossings) refuse
  the write.
- `check_document` — issues, the full stretch key map, and the diagram
  blocks (mermaid/dot) that will render in the browser.

Mermaid and graphviz are authored as fenced ` ```mermaid ` / ` ```dot `
blocks; nothing special is needed to create them over MCP.

## What the server does

- `.md` files render as pages; a directory with an `index.md`/`README.md`
  renders that as its index, otherwise you get a listing.
- Each stretch renders as `<span class="stx">` with short and long forms;
  the browser toggles them (see `static/stretch.js`), marks the words the
  long form adds by aligning the short form's words inside it, and adds a
  `«` to close.
- Fenced blocks tagged `mermaid` render via mermaid.js; `dot`/`graphviz`
  via viz.js (graphviz WASM). Both load from CDN.
- Markup problems are shown in a warnings box on the page and reported by
  `check`: unclosed stretches, a stretch crossing a blank line, a long
  form that drops or reorders the short form's words (the growth rule),
  stretches in headings, and `{{...}}` with no `|`.

## The rules (what "correctly" means)

1. **Skim is complete.** The short form answers on its own; anything the
   reader must decide or do stays outside every stretch.
2. **Growth is conservative.** The long form contains every word of the
   short form, in order, growing around them. Enforced as a hard error.
3. **Keys are stable.** A stretch is keyed `parent › short` (with `~2`,
   `~3` on repeated siblings), so adding an unrelated stretch never
   shifts another stretch's key.
4. **Markdown never lies.** Code spans and fences are opaque; no stretches
   in code, tables, or headings; list items stretch individually.

**Block growth** (Nelson's "a paragraph into several"): a long form may
hold paragraphs, lists and fenced code when the stretch stands on its
own line at the top level. Placement is validated: a block stretch
cannot start inside a list, quote, table, indent, or another stretch —
those stay inline-only.

## Architecture

- `stretchserve/scanner.py` — port of cc-stretch's `parse.ts`: stretch
  tree, keys, code-opaque scanning, plus `validate()` (the mechanical
  checks cc-stretch does socially, via a prompt guide and benchmark).
- `stretchserve/render.py` — stretch-aware markdown rendering: stretches
  become placeholder tokens, the document is converted once with
  python-markdown (so list/table structure around stretches survives),
  then short/long fragments are converted and substituted back.
- `stretchserve/server.py` — stdlib `http.server`; no framework.
- `stretchserve/static/stretch.js` — toggle, LCS-based new-word marking,
  mermaid/graphviz wiring.

## Roadmap

- MCP layer: done (see above). Next: aim it at the gzero atom/workflow
  stores so agents skim gzero and open depth on demand.
- Block-level growth: long forms that grow across paragraphs and lists.
- Vendored mermaid/viz (offline), syntax themes.
- Rust port of the scanner (the crate doesn't exist yet — checked
  crates.io; this would be the first stretchtext crate).
- IPython integration: render stretchable docs in notebooks.
