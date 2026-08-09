# Data readiness validation report

- Source: `sample_data`
- Generated: 2026-08-09 17:50 UTC
- Checks run: 132 (90 passed, 30 failed)
- Blocking errors: **23** | Warnings: 7

**BLOCKED** - errors below must be resolved before survival modelling.

## Blocking issues

### `temporal.common_window` - (cross-table)

No common window: inventory_daily, sales_pos, replenishment_orders contributes no usable dates

Affected: 3 of 3 (100.0%)

Examples: `inventory_daily, sales_pos, replenishment_orders`

> Kaplan-Meier needs inventory, sales and replenishment observed over the same period. Without every one of them there is no window in which a spell can start, run and end.

### `survival.spells_constructible` - (derived)

No spells could be constructed

> With no spell table there is nothing for a survival estimator to consume.

### `structural.date_artifact` - external_signals_fact

post_datetime: 13 destroyed date cell(s)

Affected: 13 of 13 (100.0%)

Examples: `########`

> Column overflow was baked into the export. The underlying values are gone and must be re-extracted; widen the column or export dates as ISO text.

### `temporal.coverage` - external_signals_fact

No usable dates at all

Affected: 13 of 13 (100.0%)

> Every date value is missing, destroyed or unparseable, so this table has no time dimension.

### `referential.forecast_option_in_product_dim` - forecast

0.0% of forecast.option_uid found in product_dim (1 orphan value(s))

Affected: 11 of 11 (100.0%)

Examples: `14_1002_BLACK`

> Below the 99% threshold. Rows that fail to join are dropped from the panel and their risk days vanish.

### `structural.date_artifact` - forecast

Date: 11 destroyed date cell(s)

Affected: 11 of 11 (100.0%)

Examples: `########`

> Column overflow was baked into the export. The underlying values are gone and must be re-extracted; widen the column or export dates as ISO text.

### `referential.inventory_sku_in_product_dim` - inventory_daily

0.0% of inventory_daily.sku_uid found in product_dim (3 orphan value(s))

Affected: 3 of 3 (100.0%)

Examples: `14_1033_TAN_41, 14_1033_TAN_43, 14_1033_TAN_45`

> Below the 99% threshold. Rows that fail to join are dropped from the panel and their risk days vanish.

### `structural.date_artifact` - inventory_daily

Date: 3 destroyed date cell(s)

Affected: 3 of 3 (100.0%)

Examples: `########`

> Column overflow was baked into the export. The underlying values are gone and must be re-extracted; widen the column or export dates as ISO text.

### `survival.inventory_history` - inventory_daily

No multi-date inventory history

Affected: 0 of 3 (0.0%)

> A single snapshot shows a stock level, never a stock-out moment. Without repeated observations there is no duration to measure and no event to observe.

### `temporal.coverage` - inventory_daily

No usable dates at all

Affected: 3 of 3 (100.0%)

> Every date value is missing, destroyed or unparseable, so this table has no time dimension.

### `accounting.po_no_is_identifying` - pending_orders

Po_No is a single constant value

Affected: 1 of 1 (100.0%)

Examples: `Po_No=4500000000`

> Constant 4500000000 on all 16 real sample rows - not a usable key.

### `referential.size_scale` - pending_orders

Scales present: {'ALT': np.int64(9), 'EU': np.int64(7)}

Affected: 7 of 16 (43.8%)

Examples: `83, 84, 85, 86, 87`

> The 28-48 EU run and the 83-90 block are different systems. Without a scale map they must not share a column, and a SKU uid built from them is not comparable.

### `structural.date_artifact` - promotion_data

date: 12 destroyed date cell(s)

Affected: 12 of 12 (100.0%)

Examples: `########`

> Column overflow was baked into the export. The underlying values are gone and must be re-extracted; widen the column or export dates as ISO text.

### `temporal.coverage` - promotion_data

No usable dates at all

Affected: 12 of 12 (100.0%)

> Every date value is missing, destroyed or unparseable, so this table has no time dimension.

### `accounting.warehouse_id_is_identifying` - replenishment_orders

Warehouse_ID is a single constant value

Affected: 1 of 1 (100.0%)

Examples: `Warehouse_ID=Warehouse`

> Literal constant "Warehouse" on all 12 real sample rows. Without a real warehouse identity there are no DC->store lanes and no rebalancing.

### `grain.canonical_grain` - replenishment_orders

10 rows share a canonical key

Affected: 10 of 12 (83.3%)

Examples: `GGS01 \| 71_8440_BROWN_48 \| NaT, NCS01 \| 33_213_BLACK_38 \| NaT, LUS06 \| 57_38_ROSE-GOLD_34 \| NaT`

### `grain.duplicate_key` - replenishment_orders

4 key(s) repeat across 10 rows

Affected: 10 of 12 (83.3%)

Examples: `GGS01 \| METRO_71_8440_BROWN \| 48 \| ########, NCS01 \| METRO_33_213_BLACK \| 38 \| ########, LUS06 \| METRO_57_38_ROSE_GOLD \| 34 \| ########`

> Declared grain ['Store_ID', 'SKU', 'Size', 'Order_Date'] does not identify a row. Add a line number or a full timestamp, or the rows cannot be ordered or deduplicated.

### `referential.replenishment_sku_in_product_dim` - replenishment_orders

0.0% of replenishment_orders.sku_uid found in product_dim (6 orphan value(s))

Affected: 12 of 12 (100.0%)

Examples: `16_1020_GREY_40, 33_213_BLACK_38, 33_3181_WHITE_37, 44_571_GREY_41, 57_38_ROSE-GOLD_34`

> Below the 99% threshold. Rows that fail to join are dropped from the panel and their risk days vanish.

### `referential.replenishment_store_in_store_dim` - replenishment_orders

0.0% of replenishment_orders.store_id found in store_dim (6 orphan value(s))

Affected: 12 of 12 (100.0%)

Examples: `BHS01, GBS01, GGS01, KCS05, LUS06`

> Below the 99% threshold. Rows that fail to join are dropped from the panel and their risk days vanish.

### `structural.date_artifact` - replenishment_orders

Order_Date: 12 destroyed date cell(s)

Affected: 12 of 12 (100.0%)

Examples: `########`

> Column overflow was baked into the export. The underlying values are gone and must be re-extracted; widen the column or export dates as ISO text.

### `temporal.coverage` - replenishment_orders

No usable dates at all

Affected: 12 of 12 (100.0%)

> Every date value is missing, destroyed or unparseable, so this table has no time dimension.

### `structural.table_present` - sales_pos

Table absent from the extract (sales_pos.csv)

Affected: 1 of 1 (100.0%)

> Daily POS units per store x SKU. ABSENT from the real sample. Without it there is no demand signal and no time-to-event for Kaplan-Meier.

### `survival.demand_signal` - sales_pos

No POS/sales data

> Without demand the depletion process is unobserved. Stock reaching zero cannot be distinguished from a SKU that was never allocated, so the at-risk set cannot be defined.

## All checks

### A. Structural / schema

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| FAIL | `structural.date_artifact` | external_signals_fact | post_datetime: 13 destroyed date cell(s) | 13 / 13 |
| FAIL | `structural.date_artifact` | forecast | Date: 11 destroyed date cell(s) | 11 / 11 |
| FAIL | `structural.date_artifact` | inventory_daily | Date: 3 destroyed date cell(s) | 3 / 3 |
| FAIL | `structural.date_artifact` | promotion_data | date: 12 destroyed date cell(s) | 12 / 12 |
| FAIL | `structural.date_artifact` | replenishment_orders | Order_Date: 12 destroyed date cell(s) | 12 / 12 |
| FAIL | `structural.table_present` | sales_pos | Table absent from the extract (sales_pos.csv) | 1 / 1 |
| FAIL | `structural.header_hygiene` | forecast | 1 header problem(s) | 1 / 18 |
| FAIL | `structural.header_hygiene` | pending_orders | 1 header problem(s) | 1 / 23 |
| PASS | `structural.non_empty` | external_signals_fact | 13 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | external_signals_fact | All 6 numeric columns cast cleanly | 0 / 78 |
| PASS | `structural.required_columns` | external_signals_fact | All 4 required columns present | 0 / 4 |
| PASS | `structural.non_empty` | forecast | 11 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | forecast | All 5 numeric columns cast cleanly | 0 / 55 |
| PASS | `structural.required_columns` | forecast | All 7 required columns present | 0 / 7 |
| PASS | `structural.non_empty` | inventory_daily | 3 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | inventory_daily | All 4 numeric columns cast cleanly | 0 / 12 |
| PASS | `structural.required_columns` | inventory_daily | All 9 required columns present | 0 / 9 |
| PASS | `structural.date_artifact` | pending_orders | Purchase Date: no spreadsheet artifacts | 0 / 16 |
| PASS | `structural.date_artifact` | pending_orders | Delivery Date: no spreadsheet artifacts | 0 / 16 |
| PASS | `structural.date_artifact` | pending_orders | PO From Date: no spreadsheet artifacts | 0 / 16 |
| PASS | `structural.date_parseable` | pending_orders | Purchase Date: all non-artifact values parse | 0 / 16 |
| PASS | `structural.date_parseable` | pending_orders | Delivery Date: all non-artifact values parse | 0 / 16 |
| PASS | `structural.date_parseable` | pending_orders | PO From Date: all non-artifact values parse | 0 / 16 |
| PASS | `structural.non_empty` | pending_orders | 16 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | pending_orders | All 1 numeric columns cast cleanly | 0 / 16 |
| PASS | `structural.required_columns` | pending_orders | All 9 required columns present | 0 / 9 |
| PASS | `structural.non_empty` | product_dim | 8 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | product_dim | All 0 numeric columns cast cleanly | 0 / 8 |
| PASS | `structural.required_columns` | product_dim | All 6 required columns present | 0 / 6 |
| PASS | `structural.non_empty` | promotion_data | 12 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | promotion_data | All 2 numeric columns cast cleanly | 0 / 24 |
| PASS | `structural.required_columns` | promotion_data | All 4 required columns present | 0 / 4 |
| PASS | `structural.non_empty` | replenishment_orders | 12 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | replenishment_orders | All 2 numeric columns cast cleanly | 0 / 24 |
| PASS | `structural.required_columns` | replenishment_orders | All 7 required columns present | 0 / 7 |
| PASS | `structural.non_empty` | store_dim | 3 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | store_dim | All 2 numeric columns cast cleanly | 0 / 6 |
| PASS | `structural.required_columns` | store_dim | All 6 required columns present | 0 / 6 |
| PASS | `structural.non_empty` | vendor_data | 6 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | vendor_data | All 0 numeric columns cast cleanly | 0 / 6 |
| PASS | `structural.required_columns` | vendor_data | All 4 required columns present | 0 / 4 |
| PASS | `structural.header_hygiene` | external_signals_fact | Headers clean | 0 / 24 |
| PASS | `structural.header_hygiene` | inventory_daily | Headers clean | 0 / 15 |
| PASS | `structural.header_hygiene` | product_dim | Headers clean | 0 / 14 |
| PASS | `structural.header_hygiene` | promotion_data | Headers clean | 0 / 6 |
| PASS | `structural.header_hygiene` | replenishment_orders | Headers clean | 0 / 9 |
| PASS | `structural.header_hygiene` | store_dim | Headers clean | 0 / 9 |
| PASS | `structural.header_hygiene` | vendor_data | Headers clean | 0 / 6 |
| INFO | `structural.table_inventory` | (all) | 9 of 10 configured tables present | 0 / 10 |

### B. Grain & uniqueness

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| FAIL | `grain.canonical_grain` | replenishment_orders | 10 rows share a canonical key | 10 / 12 |
| FAIL | `grain.duplicate_key` | replenishment_orders | 4 key(s) repeat across 10 rows | 10 / 12 |
| PASS | `grain.canonical_grain` | external_signals_fact | Unique on canonical grain Brand+City+Footwear_Type+post_datetime | 0 / 13 |
| PASS | `grain.duplicate_key` | external_signals_fact | Unique on Brand+City+Footwear_Type+post_datetime | 0 / 13 |
| PASS | `grain.canonical_grain` | forecast | Unique on canonical grain option_uid+size+year+month | 0 / 11 |
| PASS | `grain.composite_key_parse` | forecast | All 11 options_ values parsed | 0 / 11 |
| PASS | `grain.duplicate_key` | forecast | Unique on options_+size+year+month | 0 / 11 |
| PASS | `grain.key_completeness` | forecast | sku_uid: every component populated | 0 / 11 |
| PASS | `grain.key_completeness` | forecast | option_uid: every component populated | 0 / 11 |
| PASS | `grain.canonical_grain` | inventory_daily | Unique on canonical grain store_id+sku_uid+date | 0 / 3 |
| PASS | `grain.duplicate_key` | inventory_daily | Unique on storeid+dns_item+color+size+Date | 0 / 3 |
| PASS | `grain.key_completeness` | inventory_daily | store_id: every component populated | 0 / 3 |
| PASS | `grain.key_completeness` | inventory_daily | sku_uid: every component populated | 0 / 3 |
| PASS | `grain.key_completeness` | inventory_daily | option_uid: every component populated | 0 / 3 |
| PASS | `grain.canonical_grain` | pending_orders | Unique on canonical grain Po_No+dns+Item+cname+size | 0 / 16 |
| PASS | `grain.duplicate_key` | pending_orders | Unique on Po_No+dns+Item+cname+size | 0 / 16 |
| PASS | `grain.key_completeness` | pending_orders | sku_uid: every component populated | 0 / 16 |
| PASS | `grain.key_completeness` | pending_orders | option_uid: every component populated | 0 / 16 |
| PASS | `grain.canonical_grain` | product_dim | Unique on canonical grain sku_uid | 0 / 8 |
| PASS | `grain.duplicate_key` | product_dim | Unique on dns+item+cname+size | 0 / 8 |
| PASS | `grain.key_completeness` | product_dim | sku_uid: every component populated | 0 / 8 |
| PASS | `grain.key_completeness` | product_dim | option_uid: every component populated | 0 / 8 |
| PASS | `grain.canonical_grain` | promotion_data | Unique on canonical grain city_norm+date | 0 / 12 |
| PASS | `grain.duplicate_key` | promotion_data | Unique on city+date | 0 / 12 |
| PASS | `grain.composite_key_parse` | replenishment_orders | All 12 SKU values parsed | 0 / 12 |
| PASS | `grain.key_completeness` | replenishment_orders | store_id: every component populated | 0 / 12 |
| PASS | `grain.key_completeness` | replenishment_orders | sku_uid: every component populated | 0 / 12 |
| PASS | `grain.key_completeness` | replenishment_orders | option_uid: every component populated | 0 / 12 |
| PASS | `grain.canonical_grain` | store_dim | Unique on canonical grain store_id | 0 / 3 |
| PASS | `grain.duplicate_key` | store_dim | Unique on storeid | 0 / 3 |
| PASS | `grain.key_completeness` | store_dim | store_id: every component populated | 0 / 3 |
| PASS | `grain.canonical_grain` | vendor_data | Unique on canonical grain Material+Vendor | 0 / 6 |
| PASS | `grain.duplicate_key` | vendor_data | Unique on Material+Vendor | 0 / 6 |
| INFO | `grain.cardinality` | external_signals_fact | 13 rows | 0 / 13 |
| INFO | `grain.cardinality` | forecast | 11 rows \| 7 SKU-sizes \| 1 options \| 2 dates | 0 / 11 |
| INFO | `grain.cardinality` | inventory_daily | 3 rows \| 1 stores \| 3 SKU-sizes \| 1 options | 0 / 3 |
| INFO | `grain.cardinality` | pending_orders | 16 rows \| 16 SKU-sizes \| 4 options \| 2 dates | 0 / 16 |
| INFO | `grain.cardinality` | product_dim | 8 rows \| 8 SKU-sizes \| 7 options | 0 / 8 |
| INFO | `grain.cardinality` | promotion_data | 12 rows | 0 / 12 |
| INFO | `grain.cardinality` | replenishment_orders | 12 rows \| 6 stores \| 6 SKU-sizes \| 6 options | 0 / 12 |
| INFO | `grain.cardinality` | store_dim | 3 rows \| 3 stores | 0 / 3 |
| INFO | `grain.cardinality` | vendor_data | 6 rows | 0 / 6 |

### C. Referential integrity

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| FAIL | `referential.forecast_option_in_product_dim` | forecast | 0.0% of forecast.option_uid found in product_dim (1 orphan value(s)) | 11 / 11 |
| FAIL | `referential.inventory_sku_in_product_dim` | inventory_daily | 0.0% of inventory_daily.sku_uid found in product_dim (3 orphan value(s)) | 3 / 3 |
| FAIL | `referential.size_scale` | pending_orders | Scales present: {'ALT': np.int64(9), 'EU': np.int64(7)} | 7 / 16 |
| FAIL | `referential.replenishment_sku_in_product_dim` | replenishment_orders | 0.0% of replenishment_orders.sku_uid found in product_dim (6 orphan value(s)) | 12 / 12 |
| FAIL | `referential.replenishment_store_in_store_dim` | replenishment_orders | 0.0% of replenishment_orders.store_id found in store_dim (6 orphan value(s)) | 12 / 12 |
| FAIL | `referential.external_signal_brand_overlap` | external_signals_fact | None of the 7 signal brands are ours | 7 / 7 |
| FAIL | `referential.store_id_repaired` | inventory_daily | 1 distinct store id(s) across 3 row(s) only joined after letter-O/digit-0 repair | 3 / 3 |
| FAIL | `referential.promotion_city_in_store_dim` | promotion_data | 0.0% of promotion_data.city_norm found in store_dim (12 orphan value(s)) | 12 / 12 |
| PASS | `referential.inventory_store_in_store_dim` | inventory_daily | 100.0% of inventory_daily.store_id found in store_dim (0 orphan value(s)) | 0 / 3 |
| PASS | `referential.colour_code_bridge` | pending_orders | 2 colour code(s) map to exactly one name | 0 / 2 |
| PASS | `referential.itemnumber_agrees_with_columns` | product_dim | itemnumber agrees with dns/item/size columns | 0 / 8 |
| PASS | `referential.brand_variant` | forecast | 1 distinct brand value(s), no near-duplicates | 0 / 1 |
| PASS | `referential.size_scale` | forecast | Single size scale (EU) | 0 / 11 |
| PASS | `referential.brand_variant` | inventory_daily | 1 distinct brand value(s), no near-duplicates | 0 / 1 |
| PASS | `referential.size_scale` | inventory_daily | Single size scale (EU) | 0 / 3 |
| PASS | `referential.brand_variant` | pending_orders | 1 distinct brand value(s), no near-duplicates | 0 / 1 |
| PASS | `referential.brand_variant` | product_dim | 1 distinct brand value(s), no near-duplicates | 0 / 1 |
| PASS | `referential.itemnumber_parseable` | product_dim | Every itemnumber matches a known format | 0 / 8 |
| PASS | `referential.size_scale` | product_dim | Single size scale (EU) | 0 / 8 |
| PASS | `referential.size_scale` | replenishment_orders | Single size scale (EU) | 0 / 12 |
| PASS | `referential.store_id_repaired` | replenishment_orders | No store ids needed repair | 0 / 12 |

### D. Temporal coverage

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| FAIL | `temporal.common_window` | (cross-table) | No common window: inventory_daily, sales_pos, replenishment_orders contributes no usable dates | 3 / 3 |
| FAIL | `temporal.coverage` | external_signals_fact | No usable dates at all | 13 / 13 |
| FAIL | `temporal.coverage` | inventory_daily | No usable dates at all | 3 / 3 |
| FAIL | `temporal.coverage` | promotion_data | No usable dates at all | 12 / 12 |
| FAIL | `temporal.coverage` | replenishment_orders | No usable dates at all | 12 / 12 |
| FAIL | `temporal.forecast_granularity` | forecast | Forecast is monthly and carries no store dimension | 0 / 11 |
| INFO | `temporal.coverage` | forecast | 2026-06-01 to 2026-07-01 (31 days, 2 distinct, 0 undated rows) | 0 / 11 |
| INFO | `temporal.coverage` | pending_orders | 2026-01-10 to 2026-06-29 (171 days, 2 distinct, 0 undated rows) | 0 / 16 |

### E. Business logic & stock accounting

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| FAIL | `accounting.po_no_is_identifying` | pending_orders | Po_No is a single constant value | 1 / 1 |
| FAIL | `accounting.warehouse_id_is_identifying` | replenishment_orders | Warehouse_ID is a single constant value | 1 / 1 |
| FAIL | `accounting.store_capacity_present` | store_dim | 2 non-positive value(s) | 2 / 3 |
| PASS | `accounting.non_negative_forecast` | forecast | No negative values across 1 column(s) | 0 / 11 |
| PASS | `accounting.non_negative_stock` | inventory_daily | No negative values across 4 column(s) | 0 / 12 |
| PASS | `accounting.stock_components_sum_to_opening` | inventory_daily | warehouse_stock + store_stock + intransit_stock == opening_stk holds on all 3 rows | 0 / 3 |
| PASS | `accounting.delivery_after_purchase` | pending_orders | Delivery Date is never before Purchase Date | 0 / 16 |
| PASS | `accounting.non_negative_replen` | replenishment_orders | No negative values across 2 column(s) | 0 / 24 |
| PASS | `accounting.warehouse_stock_not_store_scoped` | inventory_daily | warehouse_stock is constant within dns_item+color+size+Date across 3 group(s) | 0 / 3 |

### F. Survival readiness

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| FAIL | `survival.spells_constructible` | (derived) | No spells could be constructed |  |
| FAIL | `survival.inventory_history` | inventory_daily | No multi-date inventory history | 0 / 3 |
| FAIL | `survival.demand_signal` | sales_pos | No POS/sales data |  |
