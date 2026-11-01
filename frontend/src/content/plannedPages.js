/**
 * Pages that exist in the design but are built in a later phase.
 *
 * The sidebar listed these alongside the built pages so the whole product was
 * visible from day one, each linking to a "coming in Phase N" page describing
 * what it would contain. Every page in the design is now built, so the list is
 * empty.
 *
 * The export stays rather than being deleted. It costs nothing, it keeps the
 * coming-soon route and component wired for any page added later, and an empty
 * list is a clearer statement that nothing is outstanding than the absence of a
 * list would be.
 *
 * Promoting a page takes three edits and all three are required: remove it from
 * here, import it with a real route in routes.jsx, and add it to BUILT_PAGES in
 * Sidebar.jsx. Leaving an entry here while adding a route creates two routes on
 * the same path, and React Router v7 ranks by specificity rather than source
 * order, so which one wins is undefined.
 */
export const PLANNED_PAGES = [];