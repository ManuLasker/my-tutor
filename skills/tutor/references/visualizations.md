# Interactive visualizations

Build one only when it genuinely helps: event loops, sorting/graph algorithms, state machines, layout algorithms, geometry, async timelines, anything dynamic. One concept per visualization.

## Build

1. Create `<slug>/interactive/index.html`, `style.css`, `app.js`.
2. No build step. Load Alpine from the viewer's bundled copy (it works offline, since `serve.py` serves `/vendor/` from the skill):
   ```html
   <script defer src="/vendor/alpinejs.min.js"></script>
   ```
   For data viz, add D3 with a pinned version: `<script src="https://cdn.jsdelivr.net/npm/d3@7.9.0/dist/d3.min.js"></script>`. If offline, use plain SVG/canvas instead. For drawing, plain JS is fine.
3. Playable controls: play / pause / step / reset / speed.
4. Link it from `session.md` under `## Visualization` as `/<slug>/interactive/`. The link must be root-relative: Lesson mode renders inside `/study.html`, so a relative `interactive/` link would 404.

## Serve

Use the same server as the viewer. Running it again is safe: if it's already up, it prints the existing URL and exits.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/serve.py
```

Open the URL it prints, replacing `study.html` with `<slug>/interactive/`. It binds `127.0.0.1` (or the config's `"bind"`) and picks the first free port from 8080. For other devices, use `--bind 0.0.0.0` (or the config) and the printed LAN URL. Unless `learner.md` shows the learner chose LAN access deliberately, warn once that everyone on the network can then read their notes and write progress.

## Which format fits which subject

| Subject type | Best format |
|---|---|
| Algorithms (sort, graph, search) | Alpine.js animation with step / play controls |
| State machines | Alpine.js with clickable transitions |
| Bash / CLI / shell | Code blocks + operator tables + ASCII pipes |
| Networking / protocols | ASCII sequence diagrams |
| Memory / data structures | ASCII boxes-and-arrows, then optional canvas |
| Math / geometry concepts | Alpine.js + Canvas or SVG |
| Frontend layout (flex / grid) | Live HTML with toggleable rules |
| Async patterns / event loop | ASCII timeline + small JS demo |
| Database concepts | ASCII tables + SQL snippets |
| Git workflows | ASCII commit graphs |
