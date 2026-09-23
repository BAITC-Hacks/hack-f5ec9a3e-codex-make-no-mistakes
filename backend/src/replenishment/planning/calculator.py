"""Deterministic scenario arithmetic, composed with the existing bulk-candidate policy."""

from collections import defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_EVEN, Context, Decimal, localcontext
from fractions import Fraction
from math import ceil

from replenishment.demand.cleaning import Order, clean_orders
from replenishment.planning.models import (
    DailyBalance,
    IncomingDecision,
    InputRow,
    PlanningRequest,
    PlanningResult,
    ResultRow,
)

ZERO = Decimal(0)
ONE = Decimal(1)
POLICY_WARNING = (
    "Сценарий v0: календарные дни, поставки до расхода за день, неудовлетворённый спрос "
    "переносится. Политики срока поставки и запаса требуют подтверждения бизнеса."
)


def _decimal(value: Fraction) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator)


def _demand(request: PlanningRequest, row: InputRow, result: ResultRow) -> Fraction | None:
    """Return baseline daily demand; relative scenario adjustments are applied later."""
    if row.daily_demand is not None:
        result.forecast_method = "manual_daily_demand"
        result.raw_daily_demand = row.daily_demand
        result.excluded_bulk_quantity = ZERO
        result.lost_demand_quantity = ZERO
        result.demand_adjustments.append(
            "Использовано явное допущение среднего дневного спроса до сезонности и роста."
        )
        if row.sales or row.stockout_days:
            result.warnings.append(
                "Ручной дневной спрос заменяет расчёт по истории: "
                "очистка и компенсация повторно не применены."
            )
        return Fraction(row.daily_demand)
    if row.history_start is None or row.history_end is None:
        result.missing_inputs.append("daily_demand or history_start/history_end")
        return None

    days = (row.history_end - row.history_start).days + 1
    result.warnings.append(
        "Полнота истории и доступность в дни без известных дефицитов приняты как допущение; "
        "пропуск продажи внутри объявленного окна считается нулевым спросом."
    )
    if row.history_end < request.planning_date - timedelta(days=1):
        result.warnings.append(
            f"История заканчивается {row.history_end}; период до даты планирования не наблюдался."
        )
    daily_raw = defaultdict(lambda: ZERO)
    documents = defaultdict(lambda: ZERO)
    customer_ids = set()
    for sale in row.sales:
        daily_raw[sale.day] += sale.quantity
        if sale.quantity > 0:
            # Supplied customers combine split same-day documents; unknown customers stay unknown.
            identity = ("customer", sale.customer_id) if sale.customer_id else ("document", sale.document)
            documents[(sale.day, identity)] += sale.quantity
            if sale.customer_id:
                customer_ids.add(sale.customer_id)
    orders = [
        Order(
            row.supplier,
            row.sku,
            row.stock_unit,
            row.warehouse or "",
            day,
            f"{identity[0]}:{identity[1]}",
            quantity,
            (),
        )
        for (day, identity), quantity in documents.items()
    ]
    decisions = clean_orders(orders, as_of=request.planning_date)
    daily_regular = defaultdict(lambda: ZERO)
    excluded = ZERO
    for decision in decisions:
        quantity = decision.regular_quantity if request.exclude_bulk else decision.order.quantity
        daily_regular[decision.order.day] += quantity
        if decision.excluded_quantity > 0:
            applied = decision.excluded_quantity if request.exclude_bulk else ZERO
            excluded += applied
            result.demand_adjustments.append(
                f"{decision.order.day}: кандидат разовой закупки {decision.order.document}; "
                f"исходно {decision.order.quantity}, регулярная часть {decision.regular_quantity}, "
                f"исключено {applied}. Это статистический кандидат, не подтверждённая разовая закупка."
            )
    if any(decision.reason == "sustained_elevation_retained" for decision in decisions):
        result.demand_adjustments.append("Повторяющееся повышение на нескольких днях сохранено как спрос.")
    if customer_ids:
        result.demand_adjustments.append(
            "Закупки одного переданного анонимного клиента объединены за день до проверки всплесков."
        )
    else:
        result.warnings.append("Нет ID клиентов: концентрация спроса по клиентам не установлена.")

    raw_total = sum(daily_raw.values(), ZERO)
    regular_total = sum(daily_regular.values(), ZERO)
    result.raw_daily_demand = raw_total / days
    result.excluded_bulk_quantity = excluded
    lost = Fraction(0)
    stockouts = set(row.stockout_days)
    history_days = [row.history_start + timedelta(days=index) for index in range(days)]
    if request.compensate_stockouts:
        for day in sorted(stockouts):
            if daily_raw[day] > 0:
                result.missing_inputs.append(f"stockout evidence conflicts with sales on {day}")
                continue
            peers = [
                other for other in history_days if other not in stockouts and other.weekday() == day.weekday()
            ]
            if len(peers) < 2:
                result.missing_inputs.append(f"at least two available same-weekday observations for {day}")
                continue
            estimate = Fraction(sum((daily_regular[other] for other in peers), ZERO)) / len(peers)
            lost += estimate
            result.demand_adjustments.append(
                f"{day}: восстановлено {_decimal(estimate)} по {len(peers)} "
                "доступным аналогичным дням недели."
            )
        if not stockouts:
            result.warnings.append("Известные дни отсутствия не переданы; пропуски не считаются дефицитом.")
    elif stockouts:
        result.warnings.append("Компенсация известных дней отсутствия отключена политикой сценария.")
    result.lost_demand_quantity = _decimal(lost)
    if request.forecast_method == "auto" and days >= 56 and not request.compensate_stockouts:
        weighted_total = Fraction(0)
        weight_sum = Fraction(0)
        for age in range(56):
            weight = Fraction(72, 100) ** (age // 7)
            weighted_total += Fraction(daily_regular[row.history_end - timedelta(days=age)]) * weight
            weight_sum += weight
        result.forecast_method = "weekly_ewma"
        result.demand_adjustments.append(
            "Авто: взвешенный спрос за последние 56 дней выбранной истории; "
            "вес каждой более старой недели умножается на 0,72."
        )
        return weighted_total / weight_sum
    result.forecast_method = "history_mean"
    if request.forecast_method == "auto":
        result.demand_adjustments.append(
            "Авто: средняя по истории — короткое окно или включённая компенсация stockout."
        )
    result.demand_adjustments.append(
        f"Простая экспериментальная средняя за {days} календарных дней: исходные продажи {raw_total}, "
        f"регулярные {regular_total}, восстановленные {_decimal(lost)}. "
        "Дни без продаж внутри окна считаются нулевыми."
    )
    return (Fraction(regular_total) + lost) / days


def _incoming(request: PlanningRequest, row: InputRow, result: ResultRow) -> dict:
    arrivals = defaultdict(lambda: ZERO)
    for item in row.incoming:
        reason = ""
        blocked = False
        if item.expected_on is not None and result.coverage_end and item.expected_on >= result.coverage_end:
            reason = "outside_coverage: дата вне горизонта; не учтено"
        elif item.expected_on is None:
            reason, blocked = "missing_date: неизвестна дата прихода", True
        elif item.expected_on < request.planning_date:
            reason, blocked = "overdue_unconfirmed: просроченный приход требует проверки", True
        elif item.quantity is None:
            reason, blocked = "missing_quantity: неизвестно количество", True
        elif item.warehouse is None or item.warehouse != row.warehouse:
            reason, blocked = "warehouse_mismatch: склад не подтверждён или отличается", True
        elif item.stock_unit is None or item.stock_unit != row.stock_unit:
            reason, blocked = "stock_unit_mismatch: единица хранения не подтверждена или отличается", True
        elif result.coverage_end is None:
            reason, blocked = "unknown_coverage: неизвестен горизонт", True
        else:
            reason = "credited: подходящая поставка до конца горизонта"
            arrivals[item.expected_on] += item.quantity
        credited = reason.startswith("credited:")
        result.incoming_decisions.append(
            IncomingDecision(id=item.id, credited=credited, quantity=item.quantity, reason=reason)
        )
        if blocked:
            result.missing_inputs.append(f"incoming {item.id}: {reason}")
    result.eligible_incoming = sum(arrivals.values(), ZERO)
    return arrivals


def _calculate_row(request: PlanningRequest, row: InputRow) -> ResultRow:
    result = ResultRow(
        row_id=row.row_id,
        supplier=row.supplier,
        sku=row.sku,
        name=row.name,
        stock_unit=row.stock_unit,
        purchase_unit=row.purchase_unit,
        basis=row.basis,
        status="needs_input",
        explanation="",
        free_stock=row.free_stock,
        warnings=list(row.notes),
        sources=row.sources,
    )
    required = {
        "warehouse": row.warehouse,
        "free_stock": row.free_stock,
        "purchase_unit": row.purchase_unit,
        "stock_per_purchase_unit": row.stock_per_purchase_unit,
        "minimum_order": row.minimum_order,
        "order_multiple": row.order_multiple,
    }
    result.missing_inputs.extend(name for name, value in required.items() if value is None)
    for field in ("stock_scope_confirmed", "incoming_complete", "constraints_confirmed"):
        if not getattr(row, field):
            result.missing_inputs.append(field)
    if row.stock_as_of != request.planning_date:
        result.missing_inputs.append("stock_as_of must equal planning_date")
    lead = row.lead_time_days if row.lead_time_days is not None else request.lead_time_days
    if lead is None:
        result.missing_inputs.append("lead_time_days")
    else:
        result.arrival_date = request.planning_date + timedelta(days=lead)
        result.coverage_end = result.arrival_date + timedelta(days=request.review_days)
    if request.forecast_end is not None:
        result.coverage_end = request.forecast_end + timedelta(days=1)
        horizon = (result.coverage_end - request.planning_date).days
        if horizon not in (7, 21, 28):
            result.warnings.append(
                "Произвольный горизонт: экстраполяция, точность на этом периоде не проверена."
            )
        if result.arrival_date and result.arrival_date >= result.coverage_end:
            result.warnings.append(
                "Новая поставка придёт после выбранного периода и не закроет дефицит внутри него."
            )

    base = _demand(request, row, result)
    arrivals = _incoming(request, row, result)
    seasonal = row.seasonality if row.seasonality is not None else request.seasonality
    growth = row.growth_pct if row.growth_pct is not None else request.growth_pct
    if row.buffer_days is not None:
        buffer_days = row.buffer_days
        result.demand_adjustments.append("Запас задан отдельным допущением строки.")
    elif row.category in request.category_buffer_days:
        buffer_days = request.category_buffer_days[row.category]
        result.demand_adjustments.append(
            f"Явная политика категории «{row.category}»: запас {buffer_days} дней."
        )
    else:
        buffer_days = request.buffer_days
    forecasts = []
    if base is not None and result.coverage_end:
        horizon = (result.coverage_end - request.planning_date).days
        for index in range(horizon):
            day = request.planning_date + timedelta(days=index)
            demand = base * Fraction(seasonal.get(str(day.month), ONE)) * (1 + Fraction(growth) / 100)
            forecasts.append((day, demand))
        forecast = sum((quantity for _, quantity in forecasts), Fraction(0))
        buffer = forecast / horizon * Fraction(buffer_days)
        result.forecast_demand = _decimal(forecast)
        result.daily_demand = _decimal(forecast / horizon)
        result.buffer = _decimal(buffer)
        factors = ", ".join(f"{month}={factor}" for month, factor in sorted(seasonal.items())) or "1"
        result.demand_adjustments.append(
            f"Относительные сезонные поправки к выбранной базе по месяцам: {factors}; "
            f"рост {growth}% применён один раз; "
            f"запас {buffer_days} дней от среднего дневного прогноза за горизонт."
        )
        if seasonal:
            result.warnings.append(
                "Сезонные факторы — явные относительные допущения к базе; "
                "история не очищена от сезонности, абсолютные сезонные индексы требуют преобразования."
            )
    if row.category and row.category not in request.category_buffer_days:
        result.warnings.append(
            f"Категория «{row.category}» сохранена; числовая политика категории не задана."
        )
    result.warnings.extend(
        [POLICY_WARNING, "Спецификация компонентов (BOM) не задана; компоненты не рассчитаны."]
    )
    if result.missing_inputs:
        result.explanation = "Для расчёта нужны данные: " + "; ".join(result.missing_inputs)
        return result

    result.status = "scenario_only"
    need = max(Fraction(0), forecast + buffer - Fraction(row.free_stock) - Fraction(result.eligible_incoming))
    result.raw_need = _decimal(need)
    if need == 0:
        purchase = Fraction(0)
    else:
        converted = max(need / Fraction(row.stock_per_purchase_unit), Fraction(row.minimum_order))
        purchase = ceil(converted / Fraction(row.order_multiple)) * Fraction(row.order_multiple)
    equivalent = purchase * Fraction(row.stock_per_purchase_unit)
    result.recommended_quantity = _decimal(purchase)
    result.stock_equivalent = _decimal(equivalent)
    result.rounding_surplus = _decimal(equivalent - need)
    balance = Fraction(row.free_stock)
    result.maximum_prearrival_shortfall = ZERO
    for day, demand in forecasts:
        incoming = arrivals[day]
        balance += Fraction(incoming) - demand
        result.daily_balances.append(
            DailyBalance(day=day, demand=_decimal(demand), incoming=incoming, balance=_decimal(balance))
        )
        if balance < 0 and result.first_shortage_date is None:
            result.first_shortage_date = day
        if day < result.arrival_date:
            result.maximum_prearrival_shortfall = max(result.maximum_prearrival_shortfall, _decimal(-balance))
    if result.maximum_prearrival_shortfall > 0:
        result.warnings.append(
            f"Нужна проверка ускорения или перемещения: до новой поставки дефицит до "
            f"{result.maximum_prearrival_shortfall} {row.stock_unit}; "
            "обычный заказ не устранит ранний дефицит."
        )
    result.explanation = (
        f"{row.supplier} / {row.sku}, склад {row.warehouse}; горизонт [{request.planning_date}, "
        f"{result.coverage_end}), новая поставка {result.arrival_date}. "
        f"max(0, спрос {result.forecast_demand} + запас {result.buffer} − свободно {row.free_stock} "
        f"− подходящий транзит {result.eligible_incoming}) = {result.raw_need} {row.stock_unit}. "
        f"В одной {row.purchase_unit}: {row.stock_per_purchase_unit} {row.stock_unit}; "
        f"минимум {row.minimum_order}, кратность {row.order_multiple}. "
        f"Заказать {result.recommended_quantity} {row.purchase_unit} = {result.stock_equivalent} "
        f"{row.stock_unit}; избыток округления/минимума {result.rounding_surplus}. "
        f"Первый дефицит без нового заказа: {result.first_shortage_date or 'нет'}; "
        f"максимальный дефицит до прихода {result.maximum_prearrival_shortfall}."
    )
    if result.incoming_decisions:
        result.explanation += (
            " Поставки: "
            + "; ".join(f"{item.id} ({item.quantity}): {item.reason}" for item in result.incoming_decisions)
            + "."
        )
    return result


def calculate(request: PlanningRequest) -> PlanningResult:
    """Calculate without I/O or mutations; no row is an automatically approved order."""
    # Exact rational means/ceil avoid a repeating-decimal residue buying an extra unit.
    # A separate fixed context controls display only, independent of caller settings.
    with localcontext(Context(prec=100, rounding=ROUND_HALF_EVEN)):
        return PlanningResult(
            planning_date=request.planning_date,
            rows=[_calculate_row(request, row) for row in request.rows],
            warnings=[POLICY_WARNING],
        )
