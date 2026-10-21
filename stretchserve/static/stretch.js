/* stretchserve browser layer.
 *
 * The server rendered each stretch as
 *   <span class="stx" data-key="...">
 *     <span class="stx-short">…</span>
 *     <span class="stx-long">…</span>
 *   </span>
 * This script:
 * - previews top-level stretches on hover with a tooltip floating above
 *   the pointer — nothing grows in place until the reader asks, so moving
 *   the pointer never reflows the page; a click grows the stretch in place
 *   and pins it open, « closes and unpins it (keyboard-operable too);
 * - marks the words the long form adds, by aligning the short form's
 *   words inside the long form (they are a subsequence by rule),
 * - renders ```mermaid and ```dot fenced blocks.
 */

(function () {
  "use strict";

  const WORD = /[\p{L}\p{N}]+/gu;

  function tokens(s) {
    return (s.toLowerCase().match(WORD) || []);
  }

  /* Mark words the long form adds: wrap runs of unmatched words in <mark class="stx-new">. */
  function markNew(stx) {
    const shortEl = stx.querySelector(":scope > .stx-short");
    const longEl = stx.querySelector(":scope > .stx-long");
    if (!shortEl || !longEl || longEl.dataset.marked) return;
    longEl.dataset.marked = "1";

    const shortTokens = tokens(shortEl.textContent);
    if (!shortTokens.length) return;

    // Collect word occurrences from the long form's text nodes, in order.
    const walker = document.createTreeWalker(longEl, NodeFilter.SHOW_TEXT, {
      acceptNode(node) {
        const parent = node.parentElement;
        // Skip code (verbatim) and content belonging to nested stretches:
        // those mark their own new words when they open.
        if (parent && parent.closest("code, pre, .stx-short, .stx-close")) {
          return NodeFilter.FILTER_REJECT;
        }
        return WORD.test(node.nodeValue) ? NodeFilter.FILTER_ACCEPT : NodeFilter.FILTER_REJECT;
      },
    });

    const occurrences = []; // {node, ranges: [{start, end, token}]}
    let node;
    while ((node = walker.nextNode())) {
      const text = node.nodeValue;
      const ranges = [];
      const re = new RegExp(WORD.source, "gu");
      let m;
      while ((m = re.exec(text))) {
        ranges.push({ start: m.index, end: m.index + m[0].length, token: m[0].toLowerCase() });
      }
      if (ranges.length) occurrences.push({ node, ranges });
    }

    // Longest common subsequence over the two token sequences.
    const longTokens = [];
    for (const occ of occurrences) for (const r of occ.ranges) longTokens.push(r);
    const n = shortTokens.length, mLen = longTokens.length;
    const dp = Array.from({ length: n + 1 }, () => new Uint32Array(mLen + 1));
    for (let i = n - 1; i >= 0; i--) {
      for (let j = mLen - 1; j >= 0; j--) {
        dp[i][j] = shortTokens[i] === longTokens[j].token
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    // Walk the alignment; tokens on the LCS are the words the reader already saw.
    let i = 0, j = 0;
    const matched = new Array(mLen).fill(false);
    while (i < n && j < mLen) {
      if (shortTokens[i] === longTokens[j].token) { matched[j] = true; i++; j++; }
      else if (dp[i + 1][j] >= dp[i][j + 1]) i++;
      else j++;
    }

    // Wrap unmatched runs per text node.
    let k = 0;
    for (const occ of occurrences) {
      const unmatched = occ.ranges.filter(() => !matched[k++]);
      if (!unmatched.length) continue;
      const node2 = occ.node;
      const text = node2.nodeValue;
      const frag = document.createDocumentFragment();
      let pos = 0;
      for (const r of unmatched) {
        if (r.start > pos) frag.appendChild(document.createTextNode(text.slice(pos, r.start)));
        const mark = document.createElement("mark");
        mark.className = "stx-new";
        mark.textContent = text.slice(r.start, r.end);
        frag.appendChild(mark);
        pos = r.end;
      }
      if (pos < text.length) frag.appendChild(document.createTextNode(text.slice(pos)));
      node2.parentNode.replaceChild(frag, node2);
    }
  }

  function annotate() {
    for (const stx of document.querySelectorAll(".stx")) {
      const shortEl = stx.querySelector(":scope > .stx-short");
      const longEl = stx.querySelector(":scope > .stx-long");
      if (!shortEl || !longEl) continue;
      shortEl.classList.add("is-link");
      shortEl.tabIndex = 0;
      if (!longEl.querySelector(":scope > .stx-close")) {
        const close = document.createElement("button");
        close.className = "stx-close";
        close.title = "close";
        close.setAttribute("aria-label", "close");
        close.textContent = "«";
        longEl.appendChild(close);
      }
      markNew(stx);
      // every stretch previews on hover — nested ones too; click still
      // pins in place, which is how a nested stretch grows in the page
      if (!stx.querySelector(":scope > .stx-long")) continue;
      stx.addEventListener("mouseenter", (e) => {
        mouseX = e.clientX; mouseY = e.clientY;
        clearTimeout(hoverTimers.get(stx));
        if (tipStx && tipStx !== stx) hideTip();
        hoverTimers.set(stx, setTimeout(() => showTip(stx), HOVER_OPEN_MS));
      });
      stx.addEventListener("mousemove", (e) => {
        mouseX = e.clientX; mouseY = e.clientY;
        if (tipStx === stx && !tip.hidden) moveTip(e.clientX, e.clientY);
      });
      stx.addEventListener("mouseleave", () => {
        clearTimeout(hoverTimers.get(stx));
        if (tipStx === stx) {
          hoverTimers.set(stx, setTimeout(() => hideTip(), HOVER_CLOSE_MS));
        }
      });
    }
  }

  function toggle(stx, open) {
    if (open === undefined) open = !stx.classList.contains("open");
    stx.classList.toggle("open", open);
    if (open) markNew(stx);
    return open;
  }

  document.addEventListener("click", (e) => {
    const close = e.target.closest(".stx-close");
    if (close) {
      const stx = close.closest(".stx");
      toggle(stx, false);
      stx.classList.remove("pinned");
      return;
    }
    const shortEl = e.target.closest(".stx-short");
    if (!shortEl) return;
    const stx = shortEl.parentElement;
    if (!stx.querySelector(":scope > .stx-long")) return;
    if (e.shiftKey) {
      // open this stretch and everything nested inside it (pinned)
      hideTip();
      const open = !stx.classList.contains("open");
      toggle(stx, open);
      stx.classList.toggle("pinned", open);
      for (const nested of stx.querySelectorAll(".stx")) {
        toggle(nested, open);
        nested.classList.toggle("pinned", open);
      }
    } else {
      // a click pins the stretch open; « closes and unpins
      hideTip();
      toggle(stx, true);
      stx.classList.add("pinned");
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" && e.key !== " ") return;
    const shortEl = e.target.closest(".stx-short");
    if (!shortEl) return;
    e.preventDefault();
    const open = toggle(shortEl.parentElement);
    shortEl.parentElement.classList.toggle("pinned", open);
  });

  /* --- hover to preview (tooltip above the pointer), click to pin --- */

  const HOVER_OPEN_MS = 150;   // brief dwell before a hover shows the preview
  const HOVER_CLOSE_MS = 300;  // grace period before hover-away hides it
  const hoverTimers = new WeakMap();

  // One floating preview per page: a clone of the hovered stretch's long
  // form, positioned above the pointer and inert to it (pointer-events:
  // none), so hover never moves the words the reader is looking at.
  const tip = document.createElement("div");
  tip.className = "stx-tip";
  tip.setAttribute("role", "tooltip");
  tip.hidden = true;
  document.body.appendChild(tip);
  let tipStx = null;
  let mouseX = 0, mouseY = 0;

  function showTip(stx) {
    if (stx.classList.contains("open")) return;
    const longEl = stx.querySelector(":scope > .stx-long");
    if (!longEl) return;
    markNew(stx);
    tip.replaceChildren();
    for (const child of [...longEl.childNodes]) tip.appendChild(child.cloneNode(true));
    // « belongs to the in-place copy; the preview is read-only
    tip.querySelectorAll(".stx-close").forEach((b) => b.remove());
    tipStx = stx;
    tip.hidden = false;
    moveTip(mouseX, mouseY);
  }

  function hideTip() {
    tipStx = null;
    tip.hidden = true;
  }

  function moveTip(x, y) {
    const PAD = 8, GAP = 14;
    const rect = tip.getBoundingClientRect();
    // horizontal: left-aligned with the text being stretched, so the words
    // the preview explains stay directly under its first line; vertical:
    // floats above the pointer
    let left = PAD;
    const shortEl = tipStx && tipStx.querySelector(":scope > .stx-short");
    if (shortEl) left = shortEl.getBoundingClientRect().left;
    left = Math.max(PAD, Math.min(left, window.innerWidth - rect.width - PAD));
    let top = y - GAP - rect.height;
    if (top < PAD) top = Math.min(y + GAP, Math.max(PAD, window.innerHeight - rect.height - PAD));
    tip.style.left = left + "px";
    tip.style.top = top + "px";
  }

  /* --- mermaid + graphviz --- */

  function renderGraphs() {
    for (const code of document.querySelectorAll("pre > code.language-mermaid")) {
      const pre = code.parentElement;
      const div = document.createElement("div");
      div.className = "mermaid";
      div.textContent = code.textContent;
      pre.replaceWith(div);
    }
    if (window.mermaid) window.mermaid.run({ querySelector: ".mermaid" }).catch(() => {});

    for (const code of document.querySelectorAll("pre > code.language-dot, pre > code.language-graphviz")) {
      if (!window.viz) break;
      const pre = code.parentElement;
      window.viz
        .renderSVGElement(code.textContent)
        .then((svg) => {
          const wrap = document.createElement("div");
          wrap.className = "graph-svg";
          wrap.appendChild(svg);
          pre.replaceWith(wrap);
        })
        .catch((err) => console.warn("dot render failed", err));
    }
  }

  // A fixed-position preview is stale the moment the page scrolls under it.
  document.addEventListener("scroll", hideTip, { capture: true, passive: true });

  if (window.mermaid || window.viz) renderGraphs();
  window.addEventListener("graphs-ready", renderGraphs);
  // annotate exactly once: defer scripts run while readyState is already
  // "interactive", so both paths below would otherwise run it
  if (document.readyState === "loading") {
    window.addEventListener("DOMContentLoaded", annotate);
  } else {
    annotate();
  }
})();

