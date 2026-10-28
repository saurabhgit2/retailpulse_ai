import { describe, expect, it } from 'vitest';

import RUN from './run.fixture.json';
import {
  adaptRun,
  holdoutForecast,
  models,
  rankCorrelation,
  significance,
  unwrap,
  warnings,
} from './adaptRun.js';

/**
 * `run.fixture.json` is a real run from the API, trimmed to the fields the
 * page reads. Fixturing from the server rather than from a hand-written shape
 * is the point: this file is the only place the frontend knows what a run
 * looks like.
 */

describe('unwrap', () => {
  it('accepts the run directly or wrapped', () => {
    expect(unwrap(RUN).id).toBe(RUN.id);
    expect(unwrap({ run: RUN }).id).toBe(RUN.id);
  });

  it('returns null for an empty response, which is what no runs looks like', () => {
    expect(unwrap(null)).toBeNull();
    expect(unwrap({})).toBeNull();
  });
});

describe('models', () => {
  it('pairs each model’s cross-validation mean with its hold-out score', () => {
    const byModel = Object.fromEntries(models(RUN).map((r) => [r.model, r]));
    expect(byModel.moving_average.cvWape).toBeCloseTo(20.86, 2);
    expect(byModel.moving_average.holdoutWape).toBeCloseTo(41.78, 2);
    expect(byModel.seasonal_naive.holdoutWape).toBeCloseTo(14.83, 2);
  });

  it('ranks the two stages independently', () => {
    const byModel = Object.fromEntries(models(RUN).map((r) => [r.model, r]));
    // Best on cross-validation, worst on the hold-out. That inversion is the
    // finding the page exists to show.
    expect(byModel.moving_average.cvRank).toBe(1);
    expect(byModel.moving_average.holdoutRank).toBe(8);
    expect(byModel.seasonal_naive.holdoutRank).toBe(1);
  });

  it('records how far each model moved between the stages', () => {
    const byModel = Object.fromEntries(models(RUN).map((r) => [r.model, r]));
    expect(byModel.moving_average.move).toBe(-7);
    expect(byModel.seasonal_naive_drift.move).toBeGreaterThan(0);
  });

  it('marks the model that saw other series during training', () => {
    const byModel = Object.fromEntries(models(RUN).map((r) => [r.model, r]));
    // The global tree model is fitted across the whole panel while the local
    // models see one series. Comparing them without saying so is unfair.
    expect(byModel.gbt_global.usesExogenous).toBe(true);
    expect(byModel.seasonal_naive.usesExogenous).toBe(false);
  });
});

describe('rankCorrelation', () => {
  it('reports that the two stages barely agree', () => {
    // -0.048 on this run, against -0.071 on the research run with three
    // folds. The conclusion survives a change of protocol.
    const rho = rankCorrelation(models(RUN));
    expect(rho).toBeLessThan(0.2);
    expect(rho).toBeGreaterThan(-0.3);
  });

  it('declines to report a correlation from too few models', () => {
    expect(rankCorrelation([{ cvRank: 1, holdoutRank: 2 }])).toBeNull();
  });
});

describe('holdoutForecast', () => {
  it('rebuilds the weeks from the protocol, since the response carries none', () => {
    const f = holdoutForecast(RUN);
    expect(f.periods[0]).toBe('2011-09-12');
    expect(f.periods).toHaveLength(f.point.length);
  });

  it('carries the measured coverage against the nominal level', () => {
    const f = holdoutForecast(RUN);
    expect(f.level).toBeCloseTo(0.8, 2);
    expect(f.coverage.observed).toBeCloseTo(0.25, 2);
    expect(f.coverage.verdict).toContain('too narrow');
  });

  it('flags a flat forecast so a horizontal line is not read as a bug', () => {
    // The selected model is a moving average, which projects its last mean
    // forward unchanged. The line is correct and looks broken.
    expect(holdoutForecast(RUN).isFlat).toBe(true);
  });
});

describe('significance', () => {
  it('reports the omnibus result and the server’s own reading of it', () => {
    const s = significance(RUN);
    expect(s.pValue).toBeCloseTo(0.258, 3);
    expect(s.rejects).toBe(false);
    expect(s.significantPairs).toBe(0);
    expect(s.comparisons).toBe(28);
  });

  it('keeps the caveat about the block count', () => {
    expect(significance(RUN).caveats.join(' ')).toContain('approximate');
  });
});

describe('warnings', () => {
  it('finds the folds where a model forecast zero', () => {
    // A symmetric error of exactly 200 is the arithmetic signature of a
    // forecast of zero. Four of them in this run, and a reader comparing
    // means would never see them.
    const { degenerate } = warnings(RUN);
    expect(degenerate.length).toBe(4);
    expect(degenerate.map((d) => d.model)).toContain('naive');
  });

  it('links the zero-filled closures to the fold boundary that landed on one', () => {
    // This is the mechanism: fold 2 trains up to 2010-12-27, a week with no
    // trade filled with zero, so any model anchored on the last observation
    // predicts zero for the whole horizon.
    const w = warnings(RUN);
    expect(w.gapPeriods).toContain('2010-12-27');
    expect(w.boundariesOnGaps.map((b) => b.trainEnd)).toContain('2010-12-27');
  });

  it('carries the pipeline’s own warning about what a zero means', () => {
    expect(warnings(RUN).gapNote).toContain('not the same as zero demand');
  });
});

describe('adaptRun', () => {
  it('names the selected model and the claim made about when it was chosen', () => {
    const run = adaptRun(RUN);
    expect(run.selection.model).toBe('moving_average');
    expect(run.selection.note).toContain('before the hold-out was scored');
  });

  it('returns null when there is no run, rather than an empty shell', () => {
    expect(adaptRun(null)).toBeNull();
  });
});
