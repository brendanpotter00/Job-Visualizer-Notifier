# Dune — The Contract

> **What Dune is:** the (cheeky) codename for the architecture Lauren Tan's team built for **Grokbot** at Cursor — a deliberately strict framework designed so AI coding agents produce good code by making the *conventional* path the *shortest* path. In the transcript in this folder it's named at **[40:51]**, and the "public nouns" this contract distills (Feature, Entrypoints, Transcript cards, shortest-path principle) are described at **[45:27]–[46:59]** — see [`lauren-tan-xai-grokbot-transcript.md`](./lauren-tan-xai-grokbot-transcript.md).

## Contract

A coding agent usually optimizes for what fits in its context:

- copy the nearest working pattern;
- edit the file already open;
- choose the shortest path that compiles;
- avoid deleting code whose callers are not visible;
- follow the requested implementation even when it conflicts with a system invariant.

These behaviors are predictable inputs to the framework design. Dune follows five rules:

1. The conventional path requires fewer decisions than a shortcut.
2. Forbidden dependencies fail mechanically.
3. Every durable value has one obvious writer.
4. New product work adds isolated files rather than branches in shared roots.
5. Exceptions are narrow, explicit, and reviewed as architecture changes.

The five public nouns carry those rules. A **Feature** creates an owned folder. Its **Entrypoints** and **Transcript cards** are discovere[...] reserved files rather than registered in shared inventories. The **Client** gives durable laptop state one writer behind named hooks[...] commands. **Host** behavior stays in the box behind one typed contract. The package boundary repeats the same lesson at the t[...] Dune lives at `sand/dune`, the application lives under `sand/src`, and Dune never imports application code.

---

> _Source note: three spots marked `[...]` in the final paragraph were truncated in the paste. Re-paste those full lines and I'll fill them in._
