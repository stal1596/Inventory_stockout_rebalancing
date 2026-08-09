# Data readiness validation report

- Source: `data\synthetic`
- Generated: 2026-08-09 17:52 UTC
- Checks run: 169 (144 passed, 3 failed)
- Blocking errors: **0** | Warnings: 3

**READY WITH CAVEATS** - no blocking errors, but see the warnings.

## All checks

### A. Structural / schema

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| PASS | `structural.date_artifact` | external_signals_fact | post_datetime: no spreadsheet artifacts | 0 / 400 |
| PASS | `structural.date_parseable` | external_signals_fact | post_datetime: all non-artifact values parse | 0 / 400 |
| PASS | `structural.non_empty` | external_signals_fact | 400 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | external_signals_fact | All 6 numeric columns cast cleanly | 0 / 2,400 |
| PASS | `structural.required_columns` | external_signals_fact | All 4 required columns present | 0 / 4 |
| PASS | `structural.date_artifact` | forecast | Date: no spreadsheet artifacts | 0 / 2,367 |
| PASS | `structural.date_parseable` | forecast | Date: all non-artifact values parse | 0 / 2,367 |
| PASS | `structural.non_empty` | forecast | 2,367 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | forecast | All 5 numeric columns cast cleanly | 0 / 11,835 |
| PASS | `structural.required_columns` | forecast | All 7 required columns present | 0 / 7 |
| PASS | `structural.date_artifact` | inventory_daily | Date: no spreadsheet artifacts | 0 / 526,201 |
| PASS | `structural.date_parseable` | inventory_daily | Date: all non-artifact values parse | 0 / 526,201 |
| PASS | `structural.non_empty` | inventory_daily | 526,201 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | inventory_daily | All 4 numeric columns cast cleanly | 0 / 2,104,804 |
| PASS | `structural.required_columns` | inventory_daily | All 9 required columns present | 0 / 9 |
| PASS | `structural.date_artifact` | pending_orders | Purchase Date: no spreadsheet artifacts | 0 / 400 |
| PASS | `structural.date_artifact` | pending_orders | Delivery Date: no spreadsheet artifacts | 0 / 400 |
| PASS | `structural.date_artifact` | pending_orders | PO From Date: no spreadsheet artifacts | 0 / 400 |
| PASS | `structural.date_parseable` | pending_orders | Purchase Date: all non-artifact values parse | 0 / 400 |
| PASS | `structural.date_parseable` | pending_orders | Delivery Date: all non-artifact values parse | 0 / 400 |
| PASS | `structural.date_parseable` | pending_orders | PO From Date: all non-artifact values parse | 0 / 400 |
| PASS | `structural.non_empty` | pending_orders | 400 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | pending_orders | All 1 numeric columns cast cleanly | 0 / 400 |
| PASS | `structural.required_columns` | pending_orders | All 9 required columns present | 0 / 9 |
| PASS | `structural.non_empty` | product_dim | 400 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | product_dim | All 0 numeric columns cast cleanly | 0 / 400 |
| PASS | `structural.required_columns` | product_dim | All 6 required columns present | 0 / 6 |
| PASS | `structural.date_artifact` | promotion_data | date: no spreadsheet artifacts | 0 / 2,160 |
| PASS | `structural.date_parseable` | promotion_data | date: all non-artifact values parse | 0 / 2,160 |
| PASS | `structural.non_empty` | promotion_data | 2,160 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | promotion_data | All 2 numeric columns cast cleanly | 0 / 4,320 |
| PASS | `structural.required_columns` | promotion_data | All 4 required columns present | 0 / 4 |
| PASS | `structural.date_artifact` | replenishment_orders | Order_Date: no spreadsheet artifacts | 0 / 21,045 |
| PASS | `structural.date_parseable` | replenishment_orders | Order_Date: all non-artifact values parse | 0 / 21,045 |
| PASS | `structural.non_empty` | replenishment_orders | 21,045 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | replenishment_orders | All 2 numeric columns cast cleanly | 0 / 42,090 |
| PASS | `structural.required_columns` | replenishment_orders | All 7 required columns present | 0 / 7 |
| PASS | `structural.date_artifact` | sales_pos | Date: no spreadsheet artifacts | 0 / 526,201 |
| PASS | `structural.date_parseable` | sales_pos | Date: all non-artifact values parse | 0 / 526,201 |
| PASS | `structural.non_empty` | sales_pos | 526,201 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | sales_pos | All 2 numeric columns cast cleanly | 0 / 1,052,402 |
| PASS | `structural.required_columns` | sales_pos | All 6 required columns present | 0 / 6 |
| PASS | `structural.non_empty` | store_dim | 12 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | store_dim | All 2 numeric columns cast cleanly | 0 / 24 |
| PASS | `structural.required_columns` | store_dim | All 6 required columns present | 0 / 6 |
| PASS | `structural.non_empty` | vendor_data | 24 data row(s) | 0 / 1 |
| PASS | `structural.numeric_castable` | vendor_data | All 0 numeric columns cast cleanly | 0 / 24 |
| PASS | `structural.required_columns` | vendor_data | All 4 required columns present | 0 / 4 |
| PASS | `structural.header_hygiene` | external_signals_fact | Headers clean | 0 / 24 |
| PASS | `structural.header_hygiene` | forecast | Headers clean | 0 / 18 |
| PASS | `structural.header_hygiene` | inventory_daily | Headers clean | 0 / 15 |
| PASS | `structural.header_hygiene` | pending_orders | Headers clean | 0 / 22 |
| PASS | `structural.header_hygiene` | product_dim | Headers clean | 0 / 14 |
| PASS | `structural.header_hygiene` | promotion_data | Headers clean | 0 / 6 |
| PASS | `structural.header_hygiene` | replenishment_orders | Headers clean | 0 / 9 |
| PASS | `structural.header_hygiene` | sales_pos | Headers clean | 0 / 7 |
| PASS | `structural.header_hygiene` | store_dim | Headers clean | 0 / 9 |
| PASS | `structural.header_hygiene` | vendor_data | Headers clean | 0 / 6 |
| INFO | `structural.table_inventory` | (all) | 10 of 10 configured tables present | 0 / 10 |

### B. Grain & uniqueness

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| PASS | `grain.canonical_grain` | external_signals_fact | Unique on canonical grain Brand+City+Footwear_Type+post_datetime | 0 / 400 |
| PASS | `grain.duplicate_key` | external_signals_fact | Unique on Brand+City+Footwear_Type+post_datetime | 0 / 400 |
| PASS | `grain.canonical_grain` | forecast | Unique on canonical grain option_uid+size+year+month | 0 / 2,367 |
| PASS | `grain.composite_key_parse` | forecast | All 2,367 options_ values parsed | 0 / 2,367 |
| PASS | `grain.duplicate_key` | forecast | Unique on options_+size+year+month | 0 / 2,367 |
| PASS | `grain.key_completeness` | forecast | sku_uid: every component populated | 0 / 2,367 |
| PASS | `grain.key_completeness` | forecast | option_uid: every component populated | 0 / 2,367 |
| PASS | `grain.canonical_grain` | inventory_daily | Unique on canonical grain store_id+sku_uid+date | 0 / 526,201 |
| PASS | `grain.duplicate_key` | inventory_daily | Unique on storeid+dns_item+color+size+Date | 0 / 526,201 |
| PASS | `grain.key_completeness` | inventory_daily | store_id: every component populated | 0 / 526,201 |
| PASS | `grain.key_completeness` | inventory_daily | sku_uid: every component populated | 0 / 526,201 |
| PASS | `grain.key_completeness` | inventory_daily | option_uid: every component populated | 0 / 526,201 |
| PASS | `grain.panel_density` | inventory_daily | Panel fill 100.0% (526,201 of 526,201 in-life store x SKU x day cells; 2,976 pairs over a 180-day window) | 0 / 526,201 |
| PASS | `grain.canonical_grain` | pending_orders | Unique on canonical grain Po_No+dns+Item+cname+size | 0 / 400 |
| PASS | `grain.duplicate_key` | pending_orders | Unique on Po_No+dns+Item+cname+size | 0 / 400 |
| PASS | `grain.key_completeness` | pending_orders | sku_uid: every component populated | 0 / 400 |
| PASS | `grain.key_completeness` | pending_orders | option_uid: every component populated | 0 / 400 |
| PASS | `grain.canonical_grain` | product_dim | Unique on canonical grain sku_uid | 0 / 400 |
| PASS | `grain.duplicate_key` | product_dim | Unique on dns+item+cname+size | 0 / 400 |
| PASS | `grain.key_completeness` | product_dim | sku_uid: every component populated | 0 / 400 |
| PASS | `grain.key_completeness` | product_dim | option_uid: every component populated | 0 / 400 |
| PASS | `grain.canonical_grain` | promotion_data | Unique on canonical grain city_norm+date | 0 / 2,160 |
| PASS | `grain.duplicate_key` | promotion_data | Unique on city+date | 0 / 2,160 |
| PASS | `grain.canonical_grain` | replenishment_orders | Unique on canonical grain store_id+sku_uid+date | 0 / 21,045 |
| PASS | `grain.composite_key_parse` | replenishment_orders | All 21,045 SKU values parsed | 0 / 21,045 |
| PASS | `grain.duplicate_key` | replenishment_orders | Unique on Store_ID+SKU+Size+Order_Date | 0 / 21,045 |
| PASS | `grain.key_completeness` | replenishment_orders | store_id: every component populated | 0 / 21,045 |
| PASS | `grain.key_completeness` | replenishment_orders | sku_uid: every component populated | 0 / 21,045 |
| PASS | `grain.key_completeness` | replenishment_orders | option_uid: every component populated | 0 / 21,045 |
| PASS | `grain.canonical_grain` | sales_pos | Unique on canonical grain store_id+sku_uid+date | 0 / 526,201 |
| PASS | `grain.duplicate_key` | sales_pos | Unique on storeid+dns_item+color+size+Date | 0 / 526,201 |
| PASS | `grain.key_completeness` | sales_pos | store_id: every component populated | 0 / 526,201 |
| PASS | `grain.key_completeness` | sales_pos | sku_uid: every component populated | 0 / 526,201 |
| PASS | `grain.key_completeness` | sales_pos | option_uid: every component populated | 0 / 526,201 |
| PASS | `grain.canonical_grain` | store_dim | Unique on canonical grain store_id | 0 / 12 |
| PASS | `grain.duplicate_key` | store_dim | Unique on storeid | 0 / 12 |
| PASS | `grain.key_completeness` | store_dim | store_id: every component populated | 0 / 12 |
| PASS | `grain.canonical_grain` | vendor_data | Unique on canonical grain Material+Vendor | 0 / 24 |
| PASS | `grain.duplicate_key` | vendor_data | Unique on Material+Vendor | 0 / 24 |
| INFO | `grain.cardinality` | external_signals_fact | 400 rows \| 158 dates | 0 / 400 |
| INFO | `grain.cardinality` | forecast | 2,367 rows \| 400 SKU-sizes \| 50 options \| 6 dates | 0 / 2,367 |
| INFO | `grain.cardinality` | inventory_daily | 526,201 rows \| 12 stores \| 400 SKU-sizes \| 50 options \| 180 dates | 0 / 526,201 |
| INFO | `grain.cardinality` | pending_orders | 400 rows \| 400 SKU-sizes \| 50 options \| 40 dates | 0 / 400 |
| INFO | `grain.cardinality` | product_dim | 400 rows \| 400 SKU-sizes \| 50 options | 0 / 400 |
| INFO | `grain.cardinality` | promotion_data | 2,160 rows \| 180 dates | 0 / 2,160 |
| INFO | `grain.cardinality` | replenishment_orders | 21,045 rows \| 12 stores \| 400 SKU-sizes \| 50 options \| 180 dates | 0 / 21,045 |
| INFO | `grain.cardinality` | sales_pos | 526,201 rows \| 12 stores \| 400 SKU-sizes \| 50 options \| 180 dates | 0 / 526,201 |
| INFO | `grain.panel_density` | sales_pos | Panel fill 100.0% (526,201 of 526,201 in-life store x SKU x day cells; 2,976 pairs over a 180-day window) | 0 / 526,201 |
| INFO | `grain.cardinality` | store_dim | 12 rows \| 12 stores | 0 / 12 |
| INFO | `grain.cardinality` | vendor_data | 24 rows | 0 / 24 |

### C. Referential integrity

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| FAIL | `referential.external_signal_brand_overlap` | external_signals_fact | None of the 6 signal brands are ours | 6 / 6 |
| PASS | `referential.forecast_option_in_product_dim` | forecast | 100.0% of forecast.option_uid found in product_dim (0 orphan value(s)) | 0 / 2,367 |
| PASS | `referential.inventory_sku_in_product_dim` | inventory_daily | 100.0% of inventory_daily.sku_uid found in product_dim (0 orphan value(s)) | 0 / 526,201 |
| PASS | `referential.inventory_store_in_store_dim` | inventory_daily | 100.0% of inventory_daily.store_id found in store_dim (0 orphan value(s)) | 0 / 526,201 |
| PASS | `referential.colour_code_bridge` | pending_orders | 10 colour code(s) map to exactly one name | 0 / 10 |
| PASS | `referential.itemnumber_agrees_with_columns` | product_dim | itemnumber agrees with dns/item/size columns | 0 / 400 |
| PASS | `referential.replenishment_sku_in_product_dim` | replenishment_orders | 100.0% of replenishment_orders.sku_uid found in product_dim (0 orphan value(s)) | 0 / 21,045 |
| PASS | `referential.replenishment_store_in_store_dim` | replenishment_orders | 100.0% of replenishment_orders.store_id found in store_dim (0 orphan value(s)) | 0 / 21,045 |
| PASS | `referential.sales_sku_in_product_dim` | sales_pos | 100.0% of sales_pos.sku_uid found in product_dim (0 orphan value(s)) | 0 / 526,201 |
| PASS | `referential.sales_store_in_store_dim` | sales_pos | 100.0% of sales_pos.store_id found in store_dim (0 orphan value(s)) | 0 / 526,201 |
| PASS | `referential.brand_variant` | forecast | 3 distinct brand value(s), no near-duplicates | 0 / 3 |
| PASS | `referential.size_scale` | forecast | Single size scale (EU) | 0 / 2,367 |
| PASS | `referential.brand_variant` | inventory_daily | 3 distinct brand value(s), no near-duplicates | 0 / 3 |
| PASS | `referential.size_scale` | inventory_daily | Single size scale (EU) | 0 / 526,201 |
| PASS | `referential.store_id_repaired` | inventory_daily | No store ids needed repair | 0 / 526,201 |
| PASS | `referential.brand_variant` | pending_orders | 3 distinct brand value(s), no near-duplicates | 0 / 3 |
| PASS | `referential.size_scale` | pending_orders | Single size scale (EU) | 0 / 400 |
| PASS | `referential.brand_variant` | product_dim | 3 distinct brand value(s), no near-duplicates | 0 / 3 |
| PASS | `referential.itemnumber_parseable` | product_dim | Every itemnumber matches a known format | 0 / 400 |
| PASS | `referential.size_scale` | product_dim | Single size scale (EU) | 0 / 400 |
| PASS | `referential.promotion_city_in_store_dim` | promotion_data | 100.0% of promotion_data.city_norm found in store_dim (0 orphan value(s)) | 0 / 2,160 |
| PASS | `referential.size_scale` | replenishment_orders | Single size scale (EU) | 0 / 21,045 |
| PASS | `referential.store_id_repaired` | replenishment_orders | No store ids needed repair | 0 / 21,045 |
| PASS | `referential.store_id_repaired` | sales_pos | No store ids needed repair | 0 / 526,201 |

### D. Temporal coverage

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| FAIL | `temporal.forecast_granularity` | forecast | Forecast is monthly and carries no store dimension | 0 / 2,367 |
| PASS | `temporal.common_window` | (cross-table) | Common window 2025-06-01 to 2025-11-27 (180 days) | 0 / 180 |
| PASS | `temporal.contiguity` | inventory_daily | All 180 calendar days present | 0 / 180 |
| PASS | `temporal.forecast_alignment` | forecast | Forecast overlaps the inventory window by 6 month(s) | 0 / 6 |
| PASS | `temporal.window_length` | inventory_daily | Observation window is 180 days | 0 / 180 |
| INFO | `temporal.coverage` | external_signals_fact | 2025-06-01 to 2025-11-27 (180 days, 158 distinct, 0 undated rows) | 0 / 400 |
| INFO | `temporal.coverage` | forecast | 2025-06-01 to 2025-11-01 (154 days, 6 distinct, 0 undated rows) | 0 / 2,367 |
| INFO | `temporal.coverage` | inventory_daily | 2025-06-01 to 2025-11-27 (180 days, 180 distinct, 0 undated rows) | 0 / 526,201 |
| INFO | `temporal.coverage` | pending_orders | 2025-07-17 to 2025-11-27 (134 days, 40 distinct, 0 undated rows) | 0 / 400 |
| INFO | `temporal.coverage` | promotion_data | 2025-06-01 to 2025-11-27 (180 days, 180 distinct, 0 undated rows) | 0 / 2,160 |
| INFO | `temporal.coverage` | replenishment_orders | 2025-06-01 to 2025-11-27 (180 days, 180 distinct, 0 undated rows) | 0 / 21,045 |
| INFO | `temporal.contiguity` | sales_pos | All 180 calendar days present | 0 / 180 |
| INFO | `temporal.coverage` | sales_pos | 2025-06-01 to 2025-11-27 (180 days, 180 distinct, 0 undated rows) | 0 / 526,201 |

### E. Business logic & stock accounting

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| PASS | `accounting.non_negative_forecast` | forecast | No negative values across 1 column(s) | 0 / 2,367 |
| PASS | `accounting.non_negative_stock` | inventory_daily | No negative values across 4 column(s) | 0 / 2,104,804 |
| PASS | `accounting.phantom_stockout` | inventory_daily | All 3,579 sale(s) from an empty opening position are covered by a recent order | 0 / 523,225 |
| PASS | `accounting.stock_components_sum_to_opening` | inventory_daily | warehouse_stock + store_stock + intransit_stock == opening_stk holds on all 526,201 rows | 0 / 526,201 |
| PASS | `accounting.stock_movement_sign` | inventory_daily | Every stock decrease across 523,225 consecutive-day transitions is explained by sales | 0 / 523,225 |
| PASS | `accounting.delivery_after_purchase` | pending_orders | Delivery Date is never before Purchase Date | 0 / 400 |
| PASS | `accounting.po_no_is_identifying` | pending_orders | Po_No varies across rows | 0 / 1 |
| PASS | `accounting.non_negative_replen` | replenishment_orders | No negative values across 2 column(s) | 0 / 42,090 |
| PASS | `accounting.warehouse_id_is_identifying` | replenishment_orders | Warehouse_ID varies across rows | 0 / 1 |
| PASS | `accounting.non_negative_units` | sales_pos | No negative values across 1 column(s) | 0 / 526,201 |
| PASS | `accounting.receipt_attribution` | inventory_daily | 100.0% of 20,265 inferred stock receipts trace to an order placed within 30 days | 0 / 20,265 |
| PASS | `accounting.warehouse_stock_not_store_scoped` | inventory_daily | warehouse_stock is constant within dns_item+color+size+Date across 70,700 group(s) | 0 / 526,201 |
| PASS | `accounting.store_capacity_present` | store_dim | All values positive across 1 column(s) | 0 / 12 |

### F. Survival readiness

| | Check | Table | Result | Affected |
|---|---|---|---|---|
| FAIL | `survival.informative_censoring` | (derived) | 47.6% of spells end in a replenishment rather than a stockout | 11,047 / 23,230 |
| PASS | `survival.event_count` | (derived) | 9,542 events observed (need at least 30 for a stable curve) | 0 / 23,230 |
| PASS | `survival.has_variation` | (derived) | Both events and censored spells are present | 0 / 23,230 |
| PASS | `survival.non_negative_duration` | (derived) | All durations are non-negative | 0 / 23,230 |
| PASS | `survival.inventory_history` | inventory_daily | 180 distinct dates observed | 0 / 526,201 |
| PASS | `survival.demand_signal` | sales_pos | 526,201 POS rows available | 0 / 526,201 |
| PASS | `survival.at_risk_set` | (derived) | Every SKU in the spell table sold at least one unit | 0 / 400 |
| PASS | `survival.stratum_support` | (derived) | All 3 store-tier strata have at least 30 events | 0 / 3 |
| INFO | `survival.left_truncation` | (derived) | 12.8% of spells were already running at the window start | 2,973 / 23,230 |
| INFO | `survival.spells_constructible` | (derived) | 23,230 spells, 9,542 stockout events (41.1%), median duration 19 days | 0 / 23,230 |
