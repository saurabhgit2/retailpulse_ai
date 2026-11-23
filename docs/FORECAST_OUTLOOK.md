# Forecast outlook: how the Forecasting page picks its model

The Forecasting page used to show the RQ1 research experiment: eight models
ranked by cross-validation, with the winner replayed over a hold-out window
that had already happened. On Online Retail II the winner was usually a
moving average, so the page drew a flat line. The page now leads with a
**business outlook** instead. The experiment is still there, one click down,
and its code and stored results are unchanged.

## Why the old chart was flat

1. **Closure weeks counted as zero sales.** The shop does not trade over
   Christmas. The weekly series fills those weeks with zero to keep the
   calendar even. A model whose training window ended on a zero forecast
   zero, or a low flat level, and that distorted the cross-validation
   ranking.
2. **Selection was made on old folds.** The cross-validation folds ended
   months before the data did, and the ranking they produced did not carry
   over to later weeks (Spearman −0.07 against the hold-out).
3. **Nothing was forecast forward.** The chart only replayed the hold-out.

## What the outlook does instead

```
weekly series ─▶ fill closure weeks ─▶ back-test every method ─▶ keep the most accurate
                 from neighbours        from 8 recent weeks         ─▶ forecast the next 12 weeks
                                                                     ─▶ band from its past errors
```

- **Closure weeks** are filled with a straight line between the weeks either
  side, and they are never scored. A week that was closed a year ago is
  forecast as closed and flagged on the page.
- **Back-testing:** each method forecasts 12 weeks from each of 8 recent
  starting points (4 weeks apart), using only the data before that point.
  Its error is compared with what actually happened.
- **Selection:** the method with the lowest typical error (WAPE: total
  absolute miss ÷ total actual) is used. The page shows every method's score,
  so you can see why it won.
- **Band:** the ratio of actual to forecast is collected over every
  back-tested week. The 10th and 90th percentiles become the band, so it is
  as wide as the method's real past mistakes.

## The methods

| Method | What it does | Flat? |
|---|---|---|
| Last year, adjusted for growth | Same week last year × (last 13 weeks ÷ same 13 weeks a year earlier), with the ratio clipped to 0.5–2 | No |
| Same week last year | Copies the same week one year earlier | No |
| Trend and yearly pattern | Straight-line trend + 3 yearly harmonics, by least squares | No |
| Blend of the two seasonal methods | The average of the first and third | No |
| Recent level with a softened yearly pattern | Current level × last year's weekly index, shrunk halfway towards 1 | No |
| Recent level (exponential smoothing) | Smoothed recent level, carried forward | Yes |
| Average of the last 12 weeks | Mean of the last 12 weeks, carried forward | Yes |

The flat methods stay in the comparison on purpose, so the page shows how much
worse they do on a seasonal business.

**Units are net of returns.** Online Retail II has single order lines of tens
of thousands of units that were cancelled within minutes. One example is a
74,215-unit order of Medium Ceramic Top Storage Jars in January 2011. Counting
only sales kept these lines in full, and the seasonal methods then copied them
into the following January.

**Top products** use the four steadier methods (growth-adjusted last year,
softened pattern, recent level and recent average). A single product's history
is too noisy for a raw copy of last year or a fitted trend. Before fitting,
each product's history is cleaned in three ways:

- **Trimmed to its first sale.** A product launched in 2011 has no sales in
  the same weeks a year earlier. Copying last year would forecast zero.
  Rabbit Night Light did exactly this before the fix: 22,443 units in the
  last 12 weeks, and a forecast of 0.
- **One-off weeks capped.** A week more than 5 times every week within 4
  weeks of it, and more than 5 times the product's typical week, is capped at
  the larger of those two. A busy season is never capped, because its
  neighbouring weeks are busy too. The chart still shows what really sold.
- **Returns larger than sales count as zero sales, not negative demand.**

Each product keeps whichever method suited its own history best, with 6
back-tests 3 weeks apart. A method that forecasts nothing for a product that
is still selling is passed over. Confidence is **high** within 15% typical
error, **medium** within 30%, and **low** above that. Most single products
come out low, which is normal for weekly units of one item. The forecast is
still the best of the methods tried, but plan with the range, not the single
number.

## Where the code is

| Layer | File |
|---|---|
| Pure core (no web framework, no ORM) | `backend/app/forecasting/outlook.py` |
| Service and caching | `backend/app/services/outlook_service.py` |
| Queries | `backend/app/db/repositories/forecasts.py`: `net_units` in `weekly_series`, `top_product_units`, `product_names` |
| Endpoint | `GET /api/v1/datasets/{id}/forecast/outlook?horizon=12&products=20` |
| Page | `frontend/src/pages/ForecastingPage.jsx` |
| Response adapter | `frontend/src/components/forecasting/adaptOutlook.js` |
| Research view (moved, unchanged) | `frontend/src/components/forecasting/ResearchExperiment.jsx` |

The result is stored in the analysis cache under `forecast_outlook`. The first
request computes it, which can take a few seconds because of the product
query. After that it is instant until the dataset is re-processed or
`OUTLOOK_VERSION` changes.

## Tests

- `backend/tests/unit/test_forecast_outlook.py`: closures, back-test
  leakage, selection, intervals, closed-week flags, products, and module
  purity.
- `backend/tests/api/test_forecast_outlook.py`: the endpoint against
  PostgreSQL, caching, validation and authentication.
- `frontend/src/components/forecasting/adaptOutlook.test.js` and
  `frontend/src/pages/ForecastingPage.test.jsx`.
