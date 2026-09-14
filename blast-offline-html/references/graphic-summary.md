# Graphic Summary

The SVG is a simplified NCBI-style offline hit map, not a pixel-identical copy of the current website. Do not invent a second layout.

## Query master bar

- Draw a **black** rectangle the full query width, same height as hit bars (10 px).
- Label `Query` to the left of that bar.
- This bar is the query axis. Do not replace it with a grey track, a thin line, or an unfilled scale.

## Ticks

- Place ticks **above** the Query bar, aligned to the same left/right edges.
- Always include `1` and `qlen`.
- For length 20 use `1, 4, 8, 12, 16, 20`. For other lengths use four interior steps plus the two ends, dropping duplicates.

## Hit bars

- Color by **bit score**: `<40` black, `40–50` blue, `50–80` green, `80–200` purple, `≥200` red.
- Horizontal placement uses `Hsp_query-from` / `Hsp_query-to` against `BlastOutput_query-len`.
- Multiple HSPs: draw the best HSP for the bar; label the best-HSP display explicitly and list every HSP under the same `#alnHdr_{gi}`.
- Click the bar to jump to that alignment.

## What not to draw

- No NCBI header, logos, or remote CSS.
- Do not infer coordinates from gel photos or from a previously saved NCBI HTML.
- If a hit has no HSP, stop that file and report the gap; do not invent a bar.
