/**
 * Static data served by the mock API.
 *
 * FIELD_GUIDE mirrors what GET /api/v1/datasets/field-guide will return from the
 * FastAPI backend (architecture §12.1). When the backend exists, it becomes the
 * single source of truth and this file is only used in mock mode.
 */

export const FIELD_GUIDE = {
  fields: [
    {
      key: 'occurred_at',
      label: 'Transaction date/time',
      status: 'required',
      expected_type: 'datetime',
      description: 'When the sale happened. Needed for every time-based analysis.',
      synonyms: ['date', 'orderdate', 'invoicedate', 'transactiondate', 'salesdate', 'timestamp', 'datetime'],
      example: '2010-12-01 08:26:00',
    },
    {
      key: 'quantity',
      label: 'Quantity',
      status: 'recommended',
      expected_type: 'numeric',
      description: 'Units sold on the line. Needed for demand forecasting. Negative values are treated as returns.',
      synonyms: ['quantity', 'qty', 'units', 'unitssold', 'volume'],
      example: '6',
    },
    {
      key: 'unit_price',
      label: 'Unit price',
      status: 'recommended',
      expected_type: 'numeric',
      description: 'Price per unit. With quantity, lets revenue be calculated when there is no revenue column.',
      synonyms: ['price', 'unitprice', 'sellingprice'],
      example: '2.55',
    },
    {
      key: 'revenue',
      label: 'Revenue (line total)',
      status: 'recommended',
      expected_type: 'numeric',
      description: 'Sales value of the line. If missing, it is derived as quantity × unit price.',
      synonyms: ['sales', 'revenue', 'amount', 'total', 'linetotal', 'salesamount'],
      example: '15.30',
    },
    {
      key: 'product_code',
      label: 'Product code / SKU',
      status: 'recommended',
      expected_type: 'any',
      description: 'Identifies the product. Needed for product analytics, SKU forecasts and basket analysis.',
      synonyms: ['stockcode', 'sku', 'productid', 'itemcode', 'productcode'],
      example: '85123A',
    },
    {
      key: 'product_name',
      label: 'Product name',
      status: 'optional',
      expected_type: 'any',
      description: 'Readable product label shown in charts and tables.',
      synonyms: ['description', 'productname', 'item', 'itemname'],
      example: 'WHITE HANGING HEART T-LIGHT HOLDER',
    },
    {
      key: 'invoice_id',
      label: 'Invoice / order ID',
      status: 'recommended',
      expected_type: 'any',
      description: 'Groups lines into orders. Needed for order counts, average order value and baskets.',
      synonyms: ['invoice', 'invoiceno', 'orderid', 'transactionid', 'receipt'],
      example: '536365',
    },
    {
      key: 'customer_id',
      label: 'Customer ID',
      status: 'recommended',
      expected_type: 'any',
      description: 'Pseudonymous customer identifier. Needed for RFM segmentation.',
      synonyms: ['customerid', 'customer', 'clientid', 'memberid'],
      example: '17850',
    },
    {
      key: 'category',
      label: 'Category',
      status: 'optional',
      expected_type: 'any',
      description: 'Product category, for category-level analysis and entropy.',
      synonyms: ['category', 'productcategory', 'department'],
      example: 'Home decor',
    },
    {
      key: 'region',
      label: 'Region / country / store',
      status: 'optional',
      expected_type: 'any',
      description: 'Where the sale happened. Enables region breakdowns and filters.',
      synonyms: ['country', 'region', 'store', 'storeid', 'location', 'state'],
      example: 'United Kingdom',
    },
    {
      key: 'discount',
      label: 'Discount / promotion',
      status: 'optional',
      expected_type: 'numeric',
      description: 'Discount amount or promotion flag, for promotion analysis.',
      synonyms: ['discount', 'promo', 'promotion', 'markdown'],
      example: '0.10',
    },
  ],
  capabilities: [
    {
      key: 'sales_analytics',
      label: 'Sales KPIs and trends',
      required: true, // processing is blocked unless this is possible
      requires_all: ['occurred_at'],
      requires_one_of: [['revenue'], ['quantity', 'unit_price']],
    },
    { key: 'demand_forecasting', label: 'Demand forecasting', requires_all: ['occurred_at', 'quantity'] },
    { key: 'product_analytics', label: 'Product analytics', requires_all: ['product_code'] },
    { key: 'order_metrics', label: 'Orders and average order value', requires_all: ['invoice_id'] },
    {
      key: 'segmentation',
      label: 'Customer segmentation (RFM)',
      requires_all: ['customer_id', 'invoice_id', 'occurred_at'],
      requires_one_of: [['revenue'], ['quantity', 'unit_price']],
    },
    { key: 'association_rules', label: 'Basket analysis (association rules)', requires_all: ['invoice_id', 'product_code'] },
    { key: 'category_analysis', label: 'Category analysis', requires_all: ['category'] },
    { key: 'region_analysis', label: 'Region analysis', requires_all: ['region'] },
    { key: 'promotion_analysis', label: 'Promotion analysis', requires_all: ['discount'] },
  ],
};

// Stock codes that are fees or adjustments rather than products (architecture
// §12.3 step 4). A starting list; the backend keeps it configurable.
export const NON_PRODUCT_CODES = [
  'POST', 'DOT', 'M', 'D', 'C2', 'BANK CHARGES', 'AMAZONFEE', 'CRUK', 'B', 'S', 'PADS', 'ADJUST',
];

export const DEFAULT_PROCESSING_OPTIONS = {
  date_format: null,
  drop_exact_duplicates: true,
  exclude_non_product_codes: true,
  non_product_codes: NON_PRODUCT_CODES,
  outlier_method: 'robust_z',
  outlier_threshold: 5,
  currency: 'GBP',
};

// Served by GET /datasets/template. The rows are marked as examples.
export const TEMPLATE_CSV = [
  'invoice_id,occurred_at,product_code,product_name,quantity,unit_price,revenue,customer_id,category,region,discount',
  'EXAMPLE-1001,2024-03-04 09:15:00,SKU-001,EXAMPLE CERAMIC MUG,4,3.50,14.00,C-0001,Kitchen,North,0',
  'EXAMPLE-1001,2024-03-04 09:15:00,SKU-014,EXAMPLE LINEN TEA TOWEL,2,4.25,8.50,C-0001,Kitchen,North,0',
  'EXAMPLE-1002,2024-03-04 11:02:00,SKU-007,EXAMPLE SCENTED CANDLE,1,9.99,9.99,,Home decor,South,0.10',
].join('\n') + '\n';
