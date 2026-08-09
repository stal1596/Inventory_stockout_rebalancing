# Data profile: `sample_data`

## Tables

| table | file | rows | columns | declared_grain | duplicate_grain_rows | broken_date_cells | date_range | stores | sku_sizes |
|---|---|---|---|---|---|---|---|---|---|
| store_dim | store_dim.csv | 3 | 9 | storeid | 0 | 0 |  | 3 |  |
| product_dim | product_dim.csv | 8 | 14 | dns+item+cname+size | 0 | 0 |  |  | 8 |
| inventory_daily | inventory_snapshot.csv | 3 | 15 | storeid+dns_item+color+size+Date | 0 | 3 |  | 1 | 3 |
| replenishment_orders | replenishment_orders.csv | 12 | 9 | Store_ID+SKU+Size+Order_Date | 6 | 12 |  | 6 | 6 |
| forecast | forecast.csv | 11 | 18 | options_+size+year+month | 0 | 11 | 2026-06-01 .. 2026-07-01 |  | 7 |
| pending_orders | pending_orders.csv | 16 | 23 | Po_No+dns+Item+cname+size | 0 | 0 | 2026-01-10 .. 2026-06-29 |  | 16 |
| promotion_data | promotion_data.csv | 12 | 6 | city+date | 0 | 12 |  |  |  |
| vendor_data | vendor_data.csv | 6 | 6 | Material+Vendor | 0 | 0 |  |  |  |
| external_signals_fact | external_signals_fact.csv | 13 | 24 | Brand+City+Footwear_Type+post_datetime | 0 | 13 |  |  |  |
| sales_pos | sales_pos.csv | ABSENT |  | storeid+dns_item+color+size+Date |  |  |  |  |  |

## Join reachability

| join | match_rate | matched | total | note |
|---|---|---|---|---|
| inventory_store_in_store_dim | 100.0% | 3 | 3 |  |
| replenishment_store_in_store_dim | 0.0% | 0 | 12 |  |
| sales_store_in_store_dim | n/a |  |  | table absent |
| inventory_sku_in_product_dim | 0.0% | 0 | 3 |  |
| replenishment_sku_in_product_dim | 0.0% | 0 | 12 |  |
| sales_sku_in_product_dim | n/a |  |  | table absent |
| forecast_option_in_product_dim | 0.0% | 0 | 11 |  |
| promotion_city_in_store_dim | 0.0% | 0 | 12 |  |

## Constant columns (no identifying power)

| table | column | value | rows |
|---|---|---|---|
| store_dim | site_type | Store | 3 |
| product_dim | dns | 35 | 8 |
| product_dim | comp | LOOM & LACE | 8 |
| product_dim | gender | LT | 8 |
| product_dim | product | FOOTWEAR | 8 |
| product_dim | cname | ANTIC GOLD | 8 |
| product_dim | assortment | LT CHAPPALS 0-1 | 8 |
| product_dim | item_status | Loom & Lace | 8 |
| product_dim | CATEGORY | OCCASION | 8 |
| product_dim | SUBCAT | OPEN | 8 |
| product_dim | cno | 28 | 8 |
| inventory_daily | dns_item | 14_1033 | 3 |
| inventory_daily | color | TAN | 3 |
| inventory_daily | brands | LOOM & PACE | 3 |
| inventory_daily | assortment | MENS SLIP-ONS | 3 |
| inventory_daily | gender | GT | 3 |
| inventory_daily | item_status | LOOM & PACE | 3 |
| inventory_daily | category | PREMIUM CLOSE | 3 |
| inventory_daily | subcat | FORMAL | 3 |
| inventory_daily | Date | ######## | 3 |
| inventory_daily | storeid | GUSO3 | 3 |
| replenishment_orders | Order_Date | ######## | 12 |
| replenishment_orders | Warehouse_ID | Warehouse | 12 |
| forecast | options_ | VELTRIX_14_1002_BLACK | 11 |
| forecast | year | 2026 | 11 |
| forecast | dns_item | 14_1002 | 11 |
| forecast | color | BLACK | 11 |
| forecast | brands | VELTRIX | 11 |
| forecast | gender | GT | 11 |
| forecast | dns | 14 | 11 |
| forecast | category | PREMIUM CLOSE | 11 |
| forecast | flag | CONTINUE | 11 |
| forecast | assortment | MENS BOOTS | 11 |
| forecast | subcat | FORMAL | 11 |
| forecast | avg_price | 6990 | 11 |
| forecast | product | footwear | 11 |
| forecast | lead_time | 90 | 11 |
| forecast | Date | ######## | 11 |
| pending_orders | Po_No | 4500000000 | 16 |
| pending_orders | dns | 900 | 16 |
| pending_orders | pcode | 1 | 16 |
| pending_orders | Purchase Type | Standard PO | 16 |
| pending_orders | Purchase Group | 203 | 16 |
| pending_orders | PRODUCT | AC | 16 |
| pending_orders | AsOnDate | 20260531 | 16 |
| pending_orders | Inhouse_OTR | LOOM & LACE | 16 |
| pending_orders | Company | Packing | 16 |
| pending_orders | Purchase Group description | Packing | 16 |
| promotion_data | date | ######## | 12 |
| promotion_data | states | Tamil Nadu | 12 |
| promotion_data | zone | SOUTH ZONE | 12 |
| promotion_data | promotion_flag | 1 | 12 |
| promotion_data | holiday_flag | 0 | 12 |
| vendor_data | Search_2 | BRAND | 6 |
| external_signals_fact | Country | India | 13 |
| external_signals_fact | post_datetime | ######## | 13 |

## Size scales

| table | EU | ALT |
|---|---|---|
| inventory_daily | 3 | 0.0 |
| product_dim | 8 | 0.0 |
| pending_orders | 7 | 9.0 |
| forecast | 11 | 0.0 |
| replenishment_orders | 12 | 0.0 |
