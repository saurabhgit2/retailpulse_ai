/**
 * Insights.
 *
 * This page exists to answer a question the dashboard would otherwise leave
 * open: the architecture describes an insight layer as the project's
 * substantive novelty, and it is not in the dashboard. A reader who finds no
 * Insights page assumes the layer was never built. A reader who finds a
 * "coming soon" placeholder assumes it is late. Neither is true, so the page
 * says what is true instead.
 *
 * It deliberately contains no figures. Every number on it would be a copy of
 * a research result and would drift the moment a run was repeated; the run
 * directories are the authority for those, and this page points at them
 * rather than restating them.
 */

const SECTIONS = [
  {
    title: 'What the insight layer does',
    body: [
      'Forecasting, segmentation and association mining each produce output about a different kind of subject: a weekly revenue series, a group of customers, a pair of products. The insight layer reconciles those outputs over the shared data foundation and emits ranked recommendations with their supporting evidence attached, rather than presenting three sets of results side by side.',
      'It produces two conditions. The integrated condition ranks recommendations using evidence from all three engines together. The isolated-component condition presents the same underlying findings as three separate reports, which is how the literature currently delivers them. The comparison between those two conditions is what Research Question 4 measures.',
    ],
  },
  {
    title: 'Where it lives',
    body: [
      'As a reproducible research pipeline, not behind an API. Each run writes a timestamped directory holding the configuration that produced it, the SHA-256 digest of that configuration, the recorded Python and library versions, and the outputs in JSON and CSV form. The insight-layer run names the three engine runs it drew on and records their configuration hashes alongside its own.',
      'That is the same form the forecasting, segmentation and association runs take, so the whole chain from raw data to recommendation can be re-executed and checked by someone who was not here.',
    ],
  },
  {
    title: 'Why it is not a page in this dashboard',
    body: [
      'Assessment 2 scopes the dashboard to the analyses already exposed through the API, with segmentation and association reported as research output and the limitation recorded. There are no segmentation, association or recommendation endpoints, so there is nothing for a page here to call.',
      'The decision was made to protect the Research Question 4 evaluation rather than to save effort. The insight layer writes both experimental conditions as text session packs, which means participant sessions do not depend on this dashboard existing at all. Building a surface for them here would have consumed the week reserved for running them.',
    ],
  },
  {
    title: 'What was withdrawn, and what "AI" means here',
    body: [
      'A conversational assistant was specified in Assessment 1 and formally withdrawn in Assessment 2: it supported no research question and would have competed for the same week as the Research Question 4 sessions.',
      'This project contains no generative language model. "AI" denotes machine learning and statistical pattern discovery — gradient-boosted tree regression for demand forecasting, three unsupervised clustering families for segmentation, association-rule mining, and information-theoretic feature analysis. The explanation layer that Research Question 4 requires is defined as rendering each recommendation with its evidence and driving features, which is what the insight layer does.',
    ],
  },
];

export function InsightsPage() {
  return (
    <div>
      <header className="mb-4">
        <h1 className="text-xl font-semibold text-ink">Insights</h1>
        <p className="mt-1 text-sm text-muted">
          The insight layer is built. It is not a page in this dashboard, and this page explains
          why rather than leaving the absence to be guessed at.
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        {SECTIONS.map((section) => (
          <section key={section.title} className="rounded-lg border border-rule bg-surface p-4">
            <h2 className="text-sm font-semibold text-ink">{section.title}</h2>
            {section.body.map((paragraph) => (
              <p key={paragraph.slice(0, 40)} className="mt-2 text-xs leading-relaxed text-ink2">
                {paragraph}
              </p>
            ))}
          </section>
        ))}
      </div>

      <section className="mt-4 rounded-lg border border-rule bg-surface p-4">
        <h2 className="text-sm font-semibold text-ink">Where to look instead</h2>
        <p className="mt-2 text-xs leading-relaxed text-muted">
          The research outputs for all four questions are in the repository, two directories per
          question — one primary run and one robustness run — each carrying the configuration that
          produced it and its digest. The pages in this dashboard show the analyses the API serves:
          headline performance, seasonality and distributions, demand forecasts, customer value and
          recency, basket composition, and the statistical and feature analyses behind them.
        </p>
      </section>
    </div>
  );
}

export default InsightsPage;
