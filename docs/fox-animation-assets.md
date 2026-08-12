# Fox animation assets

The actor is assembled from independent body, expression, clothing, prop, and effect layers.
Expressions are intentionally postponed until the body motions and reusable props are stable.

## Canonical body

| State | Transparent asset | Frames | Frame size | Direction |
| --- | --- | ---: | --- | --- |
| `idle` | `panel/static/img/fox_body_idle.png` | 6 | 298 x 880 | front |
| `walk` | `panel/static/img/fox_body_walk.png` | 8 | 221 x 887 | right |
| `run` | `panel/static/img/fox_body_run.png` | 8 | 221 x 887 | right |

Chroma-key masters and intermediate drafts are kept in the external project history archive,
not in the runtime repository. Clothing and props must not be baked into these strips.
Left-facing movement can mirror the right-facing body at runtime.

## Existing action

- `panel/static/img/fox_read_scroll.png`: six-frame scroll-reading action.
- Hold the fully opened scroll frame longer than the transition frames.
- During the hold, bob the scroll vertically by 1-2 pixels.
- The scroll is an independent floating prop and does not need to touch the paws.

## Deferred runtime mapping

Task progress can later drive actor states, for example: reading before a step, walking while
navigating, running during sortie work, and a success effect after completion. Keep this mapping
out of the panel until the base body, prop, and effect library is complete.
