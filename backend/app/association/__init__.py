"""Market basket analysis: which products are bought together, and does it last.

The pipeline, in the order the modules run:

    baskets     invoice lines -> sets of item ids, with every decision recorded
    itemsets    Apriori: which combinations occur often enough to consider
    measures    all_confidence, IS, normalised lift, cross-support
                (Ni et al. 2020) - the measures lift's defect requires
    rules       support, confidence, lift (Jirapatsil & Phumchusri 2022)
                plus the above, plus a Fisher exact test corrected for
                false discovery rate
    pruning     drop rules that restate a more general rule
    validation  mine on an earlier period, measure on a later one - RQ3
    hazards     what a rule-driven recommender does badly, measured
                (Kathriarachchi et al. 2026)
    colocation  turning the rules into a storage layout and scoring it
                (Jirapatsil & Phumchusri 2022)

Like `app.forecasting` and `app.segmentation`, this package is pure: pandas,
numpy and scipy only, no FastAPI, no SQLAlchemy, no session. It is given a
DataFrame of lines and returns dictionaries. The purity check in the test suite
enforces that, which is what lets every one of these functions be tested
without a database.

**This file deliberately imports nothing.** The segmentation package's
`__init__` imports all six of its modules, which meant the file could not be
committed until the last of them existed - a trap that cost a broken commit
once already. A package that re-exports its contents also makes `import
app.association` drag in scipy even when the caller wants one helper. Import
from the module you need:

    from app.association.baskets import build_baskets
    from app.association.rules import generate_rules
"""
