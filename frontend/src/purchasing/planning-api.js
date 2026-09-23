import {buildDemoRow,products,validateOptions,daysBetween} from './replenishment-demo.js';
import {apiError} from './api.js';

export function planningPayload(rows,options){
  return {
    planning_date:options.planningDate,forecast_end:options.forecastEnd,forecast_method:'auto',review_days:7,
    exclude_bulk:options.excludeBulk,compensate_stockouts:options.recoverStockouts,
    rows:rows.map(row=>({
      row_id:row.sku,sku:row.sku,name:row.name,supplier:row.supplier,category:row.category,
      warehouse:options.warehouse,stock_unit:row.unit,purchase_unit:row.unit,
      free_stock:String(row.stock),stock_as_of:options.planningDate,
      stock_scope_confirmed:true,incoming_complete:true,constraints_confirmed:true,
      stock_per_purchase_unit:'1',minimum_order:'0',order_multiple:String(row.multiple),lead_time_days:row.lead,
      history_start:options.historyStart,history_end:options.historyEnd,
      seasonality:options.seasonality?Object.fromEntries(Array.from({length:12},(_,month)=>[String(month+1),String(Number((row.season*(0.9+month*0.0125)).toFixed(3)))])):{},
      growth_pct:options.growth?String(Number(((row.growth-1)*100).toFixed(4))):'0',
      stockout_days:row.dailyHistory.filter(day=>day.stockout).map(day=>day.date),
      sales:row.dailyHistory.flatMap(day=>[
        ...(day.regular?[{day:day.date,quantity:String(day.regular),document:`${row.sku}-${day.date}-regular`,customer_id:'C-0010'}]:[]),
        ...(day.bulk?[{day:day.date,quantity:String(day.bulk),document:`${row.sku}-${day.date}-bulk`,customer_id:'C-0042'}]:[]),
      ]),
      incoming:row.deliveries.map(d=>({id:d.id,quantity:String(d.quantity),expected_on:d.date,warehouse:options.warehouse,stock_unit:row.unit})),
      basis:'synthetic',sources:[{label:'Демонстрационные дневные продажи и поставки frontend'}],
    })),
  };
}
export function mapResult(row,result,options){
  const number=value=>value==null?null:Number(value);
  const balances=result.daily_balances??[];
  const daily=number(result.daily_demand),quantity=number(result.recommended_quantity);
  return {...row,api:result,warehouse:options.warehouse,quantity,quantityExact:result.recommended_quantity,
    daily,baseline:daily,rawDaily:number(result.raw_daily_demand),excluded:number(result.excluded_bulk_quantity),lost:number(result.lost_demand_quantity),
    target:number(result.forecast_demand),net:number(result.raw_need),incoming:number(result.eligible_incoming),
    roundingExtra:number(result.rounding_surplus),arrivalDate:result.arrival_date,shortfallBeforeArrival:number(result.maximum_prearrival_shortfall),
    needsInput:result.status==='needs_input',cover:daily>0?row.stock/daily:Infinity,
    season:options.seasonality?row.season:1,growth:options.growth?row.growth:1,
    method:result.forecast_method,methodLabel:({weekly_ewma:'Взвешенный спрос за 8 недель',history_mean:'Среднее по доступной истории',manual_daily_demand:'Явно заданный дневной спрос'}[result.forecast_method]||'Прогноз сервера'),forecastHistoryDays:result.forecast_method==='weekly_ewma'?56:row.historyDays,
    forecastSeries:balances.map(day=>({date:day.day,forecast:Number(day.demand)})),
    deliveries:row.deliveries.map(d=>{const decision=result.incoming_decisions?.find(v=>v.id===d.id);return {...d,included:decision?.credited??false,reason:decision?.reason??'Нет решения API'};}),
    reason:result.explanation,adjustments:result.demand_adjustments??[],warnings:result.warnings??[],
    urgency:result.maximum_prearrival_shortfall!=null&&Number(result.maximum_prearrival_shortfall)>0?'Срочно':result.first_shortage_date&&daysBetween(options.planningDate,result.first_shortage_date)<7?'На этой неделе':'Планово',
  };
}
export async function calculatePlan(options,edits={},signal,items=products){
  const error=validateOptions(options);if(error)throw new Error(error);
  const rows=items.filter(p=>options.category==='Все категории'||p.category===options.category).map(p=>buildDemoRow(p,{...options,...edits[p.sku]}));
  const results=await Promise.all([...new Set(rows.map(r=>r.lead))].map(async lead=>{
    const group=rows.filter(r=>r.lead===lead);
    const response=await fetch('/api/v1/planning/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(planningPayload(group,options)),signal});
    const payload=await response.json().catch(()=>null);
    if(!response.ok)throw new Error(apiError(payload?.detail,response.status));
    if(!Array.isArray(payload?.rows))throw new Error('API вернул некорректный результат расчёта.');
    return group.map(row=>{const result=payload.rows.find(r=>r.row_id===row.sku);if(!result)throw new Error(`В ответе API нет SKU ${row.sku}`);return mapResult(row,result,options);});
  }));
  return results.flat();
}
