/**
 * MOCK ONLY. Generates a small SYNTHETIC retail CSV so the upload flow can be
 * tried without downloading a real dataset.
 *
 * Everything here is invented: products, customers, prices and dates. Results
 * from this file must never be reported as findings (brief §33).
 *
 * The columns copy the layout of Online Retail II so column detection behaves
 * the same way, and the file deliberately contains the data-quality problems
 * the pipeline must handle: duplicates, cancellations, missing customer IDs,
 * zero prices, fee lines and invalid dates.
 */
import { toCsv } from '../../utils/csv';

/** Small seeded pseudo-random generator (mulberry32): same seed, same file. */
function createRandom(seed) {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = state;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const PRODUCTS = [
  ['SYN-001', 'SYNTHETIC CERAMIC MUG', 3.5],
  ['SYN-002', 'SYNTHETIC LINEN TEA TOWEL', 4.25],
  ['SYN-003', 'SYNTHETIC SCENTED CANDLE', 9.99],
  ['SYN-004', 'SYNTHETIC GLASS JAR, LARGE', 5.75],
  ['SYN-005', 'SYNTHETIC WOODEN COASTER SET', 6.5],
  ['SYN-006', 'SYNTHETIC GIFT WRAP ROLL', 1.95],
  ['SYN-007', 'SYNTHETIC PAPER LANTERN', 2.8],
  ['SYN-008', 'SYNTHETIC ENAMEL TIN', 7.25],
  ['SYN-009', 'SYNTHETIC COTTON TOTE BAG', 3.1],
  ['SYN-010', 'SYNTHETIC PHOTO FRAME', 8.4],
  ['SYN-011', 'SYNTHETIC STRING LIGHTS', 11.5],
  ['SYN-012', 'SYNTHETIC NOTEBOOK "A5"', 2.2],
];
const COUNTRIES = [
  ['United Kingdom', 0.82],
  ['France', 0.06],
  ['Germany', 0.05],
  ['Netherlands', 0.04],
  ['Ireland', 0.03],
];

const pad = (n) => String(n).padStart(2, '0');
const formatIso = (d) =>
  `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:00`;

function pickWeighted(random, items) {
  let r = random();
  for (const [value, weight] of items) {
    if ((r -= weight) <= 0) return value;
  }
  return items[items.length - 1][0];
}

/**
 * @returns {File} a CSV File named SYNTHETIC_retail_sample.csv
 */
export function generateSyntheticSample({ invoices = 900, seed = 2026 } = {}) {
  const random = createRandom(seed);
  const header = ['Invoice', 'StockCode', 'Description', 'Quantity', 'InvoiceDate', 'Price', 'Customer ID', 'Country'];
  const rows = [];
  const start = Date.UTC(2024, 0, 1, 8, 0); // Monday 1 Jan 2024 (invented period)
  const dayMs = 24 * 60 * 60 * 1000;

  for (let i = 0; i < invoices; i += 1) {
    const dayOffset = Math.floor(random() * 180);
    const date = new Date(start + dayOffset * dayMs + Math.floor(random() * 9 * 60) * 60 * 1000);
    const isCancellation = random() < 0.02;
    const invoice = `${isCancellation ? 'C' : ''}${700000 + i}`;
    const customer = random() < 0.2 ? '' : `${40000 + Math.floor(random() * 400)}.0`;
    const country = pickWeighted(random, COUNTRIES);
    const lines = 1 + Math.floor(random() * 5);

    for (let l = 0; l < lines; l += 1) {
      const [code, name, basePrice] = PRODUCTS[Math.floor(random() * PRODUCTS.length)];
      let quantity = 1 + Math.floor(random() ** 3 * 24);
      if (isCancellation) quantity = -quantity;
      const price = random() < 0.005 ? 0 : basePrice;
      const dateText = random() < 0.003 ? '2024-13-45 10:00:00' : formatIso(date); // deliberate bad date
      const row = [invoice, code, name, quantity, dateText, price.toFixed(2), customer, country];
      rows.push(row);
      if (random() < 0.02) rows.push([...row]); // deliberate exact duplicate
    }
    if (random() < 0.03) {
      rows.push([invoice, 'POST', 'POSTAGE', 1, formatIso(date), '18.00', customer, country]); // fee line
    }
  }

  return new File([toCsv(header, rows)], 'SYNTHETIC_retail_sample.csv', { type: 'text/csv' });
}
