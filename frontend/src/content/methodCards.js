/**
 * "About this analysis" explanations (architecture §12.9). Every analysis gets
 * the same seven headings, so users and examiners always know where to look.
 */
export const METHOD_CARDS = {
  qualityReport: {
    title: 'About this data-quality report',
    what: 'Lists every change the cleaning pipeline made to your file, in the order it made them, with the number of rows affected and examples.',
    why: 'Nothing is changed silently. You can check each decision and trace every later result back to the rows it was based on.',
    input: 'Your uploaded CSV, the column mapping you confirmed, and the cleaning options.',
    output: 'Rows kept, rows excluded (with reasons), rows flagged but kept (returns, guest customers, outliers), and warnings.',
    assumptions: [
      'Rows identical in every column are duplicate entries, not repeat purchases.',
      'Invoices starting with "C" or negative quantities are returns.',
      'Fee and adjustment codes (postage, bank charges…) are not product sales.',
    ],
    limitations: [
      'Exact-duplicate removal can remove genuine repeated purchases.',
      'Outlier flags are statistical candidates, not confirmed errors.',
    ],
    interpretation:
      'Check that the rows kept plus the rows excluded add up to the rows in the file (the conservation check). If a large share is excluded for one reason, check the column mapping before trusting any analysis.',
  },
  columnMapping: {
    title: 'Why you confirm the column mapping',
    what: 'Links each column in your file to a standard field RetailPulse understands (date, quantity, price…).',
    why: 'Column names differ between systems. Asking you to confirm stops silent mistakes, like reading 03/04/2010 as the wrong month.',
    input: 'The detected columns, their types and sample values.',
    output: 'A confirmed mapping, and the list of analyses your data can support.',
    assumptions: ['Suggestions come from common column names and each column’s contents.'],
    limitations: ['A column with a familiar name but unusual contents may be suggested wrongly: check the sample values.'],
    interpretation: 'Required fields must be mapped. Unmapped optional fields only hide the analyses that need them.',
  },
};
