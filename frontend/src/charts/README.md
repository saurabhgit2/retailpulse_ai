# charts/

The chart layer. **Hand-written SVG, not a charting library.**

That is a deliberate choice and the reason is consistency: every other analytical
component in this project is implemented from its definition so the dissertation can
explain it, and a chart is an analytical component. `scale.js` and `path.js` are about
200 lines between them, which is less than the configuration a library would have needed
anyway.

The cost is real and is stated in the limitations: **no zoom, no brush selection, no
animated transitions.**

## What is here

| file | responsibility |
|---|---|
| `scale.js` | `linearScale`, `bandScale`, `niceDomain`, `niceTicks`, `tickStep`, `nearestIndex` |
| `path.js` | `linePath`, `bandPath`, `barPath`, `segments` — SVG path strings |
| `axisFormat.js` | one unit for a whole axis, date ticks in UTC, label thinning, `labelAnchor` |
| `series.js` | the validated palette, emphasis colours, tail folding |
| `tokens.css` | eight series hues plus status colours, defined for light and dark |
| `useChartSize.js` | measures the container so charts are responsive without a library |
| `ChartFrame.jsx` | the card every chart sits in: states, legend, note, and the table view |
| `ChartTable.jsx` | the table twin of every chart |
| `Legend.jsx` | shown automatically for two or more series |
| `LineChart.jsx` | time series, with gaps where data is missing |
| `BarChart.jsx` | horizontal, for ranked categories with long names |
| `ColumnChart.jsx` | vertical, for distributions and ordered buckets |
| `SlopeChart.jsx` | two rankings side by side, for "did the ordering survive?" |

## The rules

**A chart receives data already shaped for display** and knows nothing about the API.
Adapting a response is the job of a `components/<page>/adapt*.js` module, which is pure
and tested against a fixture captured from the real endpoint.

**Every chart ships a table view.** This is not a fallback. Three of the eight series
hues sit below 3:1 contrast on white, and that is only legitimate because every value is
reachable in a table — without hovering, with a keyboard, and in a screen reader.
`ChartFrame` provides the toggle, so a chart that does not pass a `table` prop is
missing something.

**The palette order is the validation.** The eight hues were checked for colour-vision
deficiency as an ordered sequence: worst adjacent pair 9.1 ΔE in light mode, 8.4 in dark,
against a target of 8. Re-ordering them or substituting one invalidates that check.
`seriesPalette` throws rather than silently allocating a ninth colour.

**Bars start at zero.** A truncated baseline makes a 4% difference look like a 40% one.

**Missing data is a gap, not a line.** `linePath` breaks the path rather than
interpolating across an absent value.

**A value that cannot be computed renders as "—", never as 0.** Turning "we do not know"
into "it did not change" is the single most misleading thing a chart can do, and it is
precisely what the cleaning pipeline was built to avoid.

## Tests

`scale.test.js`, `path.test.js`, `axisFormat.test.js`, `series.test.js` and
`ChartFrame.test.jsx`. Several of them exist because of a specific defect:

- the tick step rounded up, so an axis asked for four ticks returned two;
- date labels compared their spacing against a stride rather than against pixels, so the
  last two overlapped on screen while the test passed;
- a label centred on the final bar was clipped by the viewport, rendering `£119,626` as
  `£119,62` — a number that does not look truncated.

Each of those was found by looking at a render, not by reading the code, and each has a
test now so that it stays found.
