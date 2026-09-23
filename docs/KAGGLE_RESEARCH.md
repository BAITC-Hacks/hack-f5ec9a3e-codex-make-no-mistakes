# Kaggle research for supplier replenishment / Исследование Kaggle

Research date: 2026-09-23. This is a research recommendation, not an implemented or benchmarked method. Project fit was assessed against PROJECT_CONTEXT.md, DATA_GUIDE.md, DATA_AUDIT.md and DELIVERY_PLAN.md. Existing application work was not evaluated.

## English

### Recommendation

Build an explainable replenishment calculation, benchmark simple demand forecasts, then test a compact pooled LightGBM model. Add an intermittent-demand candidate for genuinely sparse SKUs. Kaggle offers strong forecasting precedents, but the sources reviewed do not supply a complete solution to our supplier constraints, missing stockout records, or one-off customer purchases.

### Most useful sources, ranked for our project

| Source | Verified finding | What we should borrow / limitation |
| --- | --- | --- |
| [M5 Accuracy, fourth-place write-up](https://www.kaggle.com/competitions/m5-forecasting-accuracy/writeups/monsaraida-4th-place-solution) | LightGBM with Tweedie loss, five temporal holdouts, ordinary time/calendar/price features, no recursive features or blending. Separate models per store and forecast week. | Best practical modeling reference. Start smaller with pooled SKUs and chronological validation. “Single model” in the write-up means one model family without an ensemble, not one fitted estimator for the whole competition. |
| [Rohlik Sales, first-place write-up](https://www.kaggle.com/competitions/rohlik-sales-forecasting-challenge-v2/writeups/golden-1st-place-solution) | Direct daily forecasts; useful features included relative prices and competing-product availability. Outlier removal did not help this participant. The author reports expensive feature generation and training. | Borrow careful feature design. Our data lacks several of these inputs. Do not copy the full winning pipeline or assume automatic removal of large sales improves forecasting. |
| [Grupo Bimbo, first-place write-up](https://www.kaggle.com/competitions/grupo-bimbo-inventory-demand/discussion/23863) | Recent demand lags and grouped historical aggregates were central; customer/product identifiers and product-name parsing supplied features. Validation reproduced the multi-step prediction process. | Useful distribution-demand analogue. Borrow lagged product/category aggregates. Customer-specific features cannot be reproduced with our missing customer IDs. Its large ensemble is unnecessary as a starting point. |
| [M5 Uncertainty, third-place write-up](https://www.kaggle.com/competitions/m5-forecasting-uncertainty/writeups/ouranos-3rd-place-solution) | Combined point forecasts and statistical sales quantiles to estimate uncertainty. | Motivation to estimate a demand range and evaluate its calibration. Competition quantiles are not automatically a calibrated safety-stock policy for our suppliers. |
| [Store Sales — Time Series Forecasting](https://www.kaggle.com/c/store-sales-time-series-forecasting) | Favorita sales forecasting exercise with a linked time-series course. | Accessible onboarding and feature-engineering practice; less specific to our replenishment decisions than the write-ups above. |

Rohlik forecasts warehouse-item sales over 14 days and evaluates WMAE; our horizon must instead match the supplier's lead time and review cycle. [Competition overview](https://www.kaggle.com/competitions/rohlik-sales-forecasting-challenge-v2/).

For sparse demand, the official [StatsForecast tutorial](https://nixtlaverse.nixtla.io/statsforecast/docs/tutorials/intermittentdata.html) demonstrates Croston, TSB, ADIDA and IMAPA on M5 series. These are sensible candidates to compare, not proven winners for electrical products. Its intermittent models produce point forecasts; uncertainty needs a separate method.

The [Inventory Demand Forecasting and Stockout Risk dataset](https://www.kaggle.com/datasets/jayjoshi37/inventory-demand-forecasting-and-stockout-risk) explicitly describes its 2,800 records as synthetic. It could illustrate interfaces or scenarios, but cannot validate real replenishment performance. Our supplied partner data should remain the main evaluation source.

### Proposed experiment, grounded in our files

1. **Resolve the demand definition first.** Transactions cover Алматы and have meaningful positive sales from January 2025; monthly tables cover January 2024–September 2026 with unspecified warehouse scope. They disagree. Do not concatenate them as equivalent observations. Do not convert all signs with absolute value. Treat September as incomplete until cutoffs are confirmed; blank cells are not established zeros.
2. **Build baselines.** Compare recent mean demand, seasonal naive, and a robust recent-demand estimate with explicitly approved bulk events excluded. For monthly series, avoid elaborate SKU-specific seasonal fitting on only about two annual cycles. Test pooled category seasonality only where units and scope are compatible.
3. **Compare sparse-demand methods.** After establishing genuine zero-demand periods, compare Croston-SBA or TSB with those baselines. Do not use a median-only baseline for sparse series: it can predict zero almost everywhere. Unknown availability must remain unknown, rather than being interpreted as inactivity or obsolescence.
4. **Test one compact LightGBM candidate.** Pool product histories with SKU/supplier identifiers and available category codes. Candidate features: past demand, shifted rolling averages, calendar, time since last sale, and recent-vs-longer-term demand. For a weekly experiment, try 1/2/4/8-week lags and 4/8/13-week windows; these are proposed settings, not copied winning parameters. Generate every feature using information available at that forecast origin. Multi-step forecasts must not use actual future sales as lags. Weekly aggregation is a candidate to validate, not a reason to discard daily timing needed for arrivals.
5. **Validate over time.** Use several rolling origins with a horizon matching the proposed purchasing cycle, then reserve the latest complete interval as a final holdout. Fit outlier thresholds and seasonal factors separately inside each training fold. Compare forecast bias and MAE/WAPE within compatible units and supplier/segments; report undefined WAPE when actual demand totals zero. Do not add meters, packs and pieces into a single unweighted quantity error. Report sparse/regular segments separately and measure runtime. Keep the simple baseline unless the added model improves consistently.
6. **Evaluate purchasing behavior separately.** Compare shortages and average inventory under explicitly stated initial-stock, arrival and lead-time assumptions. Missing historical inventory and receipts prevent a factual claim of realized savings. Scenario simulation can demonstrate behavior, but its outcomes must be labeled simulated.

### Convert a forecast into an order

Use periodic review as an initial policy: cover demand during lead time plus the interval until the next purchasing review. An order-up-to policy replenishes the difference between a target and inventory position. This policy and protection-period reasoning are described in [MIT inventory lectures](https://ocw.mit.edu/courses/esd-260j-logistics-systems-fall-2006/8b53c45fd26ffff706d815131e8d177e_lect11.pdf) and [MIT supply-chain summary](https://ocw.mit.edu/courses/15-763j-manufacturing-system-and-supply-chain-design-spring-2005/e1800430fdccaf618b22bd551fc00fac_summary.pdf).

Proposed explanatory calculation:

`raw need = max(0, forecast over protection period + safety buffer - available stock - eligible incoming supply)`

Apply confirmed minimum shipment quantities and pack multiples only when raw need is positive. A minimum is not necessarily a multiple. Convert purchasing/stocking units before rounding. If available stock already excludes reservations, do not subtract them again. Define whether outstanding commitments are already represented by reservations or demand so they are counted once.

This is a quantity summary, not a complete arrival-timing simulation. Project stock through dated arrivals to flag a shortage before a shipment reaches the warehouse. A late shipment cannot resolve an earlier shortage; retain visibility of outstanding orders to avoid duplicate buying.

Initially expose the safety buffer as an explicit assumption. Later calibrate it against errors in cumulative demand over the full protection period. Do not add daily upper quantiles and label the result a calibrated horizon quantile. If the target is already a demand quantile, avoid adding another buffer for the same uncertainty. A nominal coverage probability is not the same as a demonstrated fill rate.

### Two hackathon requirements need special treatment

**One-off bulk orders:** preserve raw transactions, flag unusually large events relative to the SKU's past, and allow classification as regular or project demand. Exclude only the approved nonrecurring component from baseline training. Repeated increases should be allowed to represent growth. Show raw and adjusted forecasts and the affected document references. Document IDs can identify events, but cannot establish customer concentration. Validate the latter only on labeled synthetic data until customer IDs arrive.

**Lost demand:** confirmed unavailable periods should not teach the model that customer demand was zero. With actual availability intervals, compare an in-stock-trained estimate and explicit imputation scenarios. At present, monthly opening balances cannot identify exact stockout days. Any correction must be labeled an assumption and cannot be scored against invented ground truth.

### Suggested demo

Keep both suppliers in scope. Start the worked example with Systeme SKU `300200745_ / ATN540126`: the existing audit records free stock 23, incoming 120 and pack multiple 6. Confirm warehouse scope before combining these with Алматы demand. Show how changing incoming supply, lead time, and a classified bulk event changes the recommendation; show the arithmetic and assumptions beside it. Use synthetic labeled inputs for exact stockouts and customer concentration. IEK needs explicit handling of its missing current-stock snapshot and purchasing-unit conversions.

Research status: public competition pages, indexed participant write-ups and primary supporting references reviewed; no Kaggle dataset downloaded, notebook executed, or performance improvement measured. Some Kaggle pages returned an empty direct extraction, so their indexed write-up text was used. The proposal is evidence-informed and still requires local benchmarking.

## Русский: выводы для команды

Рекомендуемое направление — объяснимый расчёт пополнения, несколько простых прогнозных базовых методов и компактная модель LightGBM как проверяемый кандидат. Для товаров с подтверждённым редким спросом стоит сравнить методы Croston-SBA/TSB. Это предложение по исследованию, а не уже выбранный или реализованный алгоритм.

Полезные ориентиры: M5 Accuracy (4-е место), Rohlik Sales (1-е место), Grupo Bimbo (1-е место), M5 Uncertainty. Ссылки и проверенные выводы приведены в таблице выше. Их результаты обосновывают эксперименты на наших данных, но не гарантируют улучшение для электротоваров.

План:

1. Согласовать источник и склад спроса. Месячные отчёты и движения расходятся; пустоты, отрицательные количества и неполный сентябрь требуют отдельных правил.
2. Сравнить средний недавний спрос, сезонный наивный прогноз, вариант с подтверждёнными исключениями разовых заказов и методы редкого спроса.
3. Проверить LightGBM на исторических признаках без доступа к будущему. Использовать несколько последовательных временных проверок и финальный отложенный период. Оставить простой метод, если усложнение не даёт устойчивого выигрыша.
4. Рассчитывать потребность на срок поставки плюс интервал пересмотра заказа; учитывать свободный остаток, подходящий транзит, явно заданный страховой запас, минимальную отгрузку и кратность. Проверять даты приходов отдельно: поздний приход не закрывает ранний дефицит.
5. Показывать менеджеру происхождение цифр и эффект изменения параметров. Проверять прогнозную ошибку отдельно от результатов имитации запасов; не заявлять доказанную экономию по синтетическому сценарию.

Крупная продажа сама по себе не доказывает разовый заказ. Нужны сохранение исходных данных, маркировка события и сравнение исходного/скорректированного спроса. Без customer ID нельзя подтвердить концентрацию у одного клиента. Без точных интервалов наличия нельзя достоверно восстановить потерянный спрос: соответствующие сценарии пока должны быть явно синтетическими или основанными на обозначенных допущениях.

Для первого примера подходит Systeme `300200745_`: свободный остаток 23, транзит 120, кратность 6 по существующему аудиту. Складскую область нужно подтвердить. Оба поставщика остаются в объёме задачи. Исследование не включает обучение моделей, запуск Kaggle notebooks или изменение приложения.
