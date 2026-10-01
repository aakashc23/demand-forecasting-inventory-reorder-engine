# How a forecast becomes an order

Every morning the engine answers one question per SKU and store: *do we order today, and how much?*
Worked numbers are in [`reports/reorder_examples.md`](../reports/reorder_examples.md). The full list is `outputs/reorder_list.csv`.

## The logic, step by step

1. **Forecast.** The selected model predicts daily units for the next 28 days.
2. **Lead-time demand.** Add up the forecast for the days it takes a new order to arrive. This is what we expect to sell while we wait.
3. **Forecast error (sigma).** Past backtests show how far the forecast typically misses, as the RMSE of its daily errors. We buffer against the forecast being wrong, not against demand being "volatile".
4. **Safety stock** = Z x sigma x sqrt(lead time). Z comes from the service level. Longer waits and noisier forecasts need a bigger buffer. The sqrt assumes daily misses are independent, which is a simplification.
5. **Reorder point (ROP)** = lead-time demand + safety stock. Reaching this level means "order now".
6. **Order-up-to level** = ROP + one order cycle (7 days) of forecast demand. This is the stock level we aim to restore.
7. **Order quantity.** If inventory position (on-hand + open orders) is at or below the ROP, order enough to reach the order-up-to level, rounded **up** to whole cases. Otherwise order nothing.
8. **Risk flag.** HIGH: on-hand is below lead-time demand, so we stock out before any order can arrive. MEDIUM: at or below ROP, reorder now. OVERSTOCK: more than 30 days of cover. OK: everything else.

## What the assumptions mean

- **Service level 95% -> 98%.** Z rises, so safety stock and the ROP rise by roughly a quarter of the buffer. More SKUs trip the reorder point sooner and we carry more stock. The price of fewer stockouts is cash tied up in inventory.
- **Lead time doubles.** Lead-time demand doubles and safety stock grows by about 1.4x, so the ROP and order sizes grow substantially. More SKUs fall below lead-time demand and turn HIGH, because stock has to bridge a longer gap.
- **Case pack.** Orders round up, so we sometimes order slightly more than the target. Setting the pack to 1 removes this.

## Assumptions table

| Item | Source | Notes |
|---|---|---|
| Daily forecast | **Data / model** | Selected backtested model, refit to 2016-05-22 |
| Forecast error sigma | **Data / model** | RMSE of backtest errors per SKU-store |
| Unit price | **Data** | Latest observed `sell_price` |
| Service level | **ASSUMED** | 95%, a business choice |
| Lead times | **ASSUMED** | Per store, illustrative (5 / 7 / 10 days); M5 has no supplier data |
| Order cycle | **ASSUMED** | 7 days beyond lead time |
| Case pack | **ASSUMED** | 6 units, illustrative; M5 has no pack sizes |
| Current inventory | **ASSUMED (SYNTHETIC)** | Random 0 to 45 days of supply, fixed seed; M5 has no inventory data |
| Open orders | **ASSUMED** | None, so inventory position = on-hand |

Because on-hand stock is synthetic, the *list of SKUs to order* illustrates the method and is not a real replenishment plan. The forecast, sigma and prices are the real parts.
