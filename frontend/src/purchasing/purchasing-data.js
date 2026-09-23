import {api} from './api.js';
import {mapResult} from './planning-api.js';

export async function loadProducts(page=1,q=''){
  const catalog=await api(`/tables/catalog?${new URLSearchParams({page,page_size:20,q})}`);
  const items=await Promise.all(catalog.items.map(async product=>{
    const observations=await api(`/tables/products?${new URLSearchParams({product_id:product.id,page_size:200})}`);
    const names=[...new Set(observations.items.map(r=>r.name).filter(Boolean))];
    const categories=[...new Set(observations.items.map(r=>r.category_code).filter(Boolean))];
    return {...product,name:names.length===1?names[0]:product.sku,category:categories.length===1?categories[0]:'Не указана / неоднозначна'};
  }));
  return {...catalog,items};
}

export function sourcePayload(options,items){
  return {product_ids:items.map(p=>p.id),warehouse:options.warehouse,planning_date:options.planningDate,history_start:options.historyStart,history_end:options.historyEnd};
}

export function displayRows(input,result,options){
  return input.rows.map(row=>{
    const answer=result.rows.find(r=>r.row_id===row.row_id);
    if(!answer)throw new Error(`Нет результата для ${row.sku}`);
    return {...mapResult({sku:row.sku,name:row.name||row.sku,supplier:row.supplier,category:row.category||'Не указана / неоднозначна',unit:row.stock_unit,
      stock:row.free_stock==null?null:Number(row.free_stock),lead:row.lead_time_days??input.lead_time_days,multiple:row.order_multiple,price:null,season:1,growth:1,deliveries:row.incoming.map(d=>({id:d.id,date:d.expected_on,quantity:d.quantity})),
      forecastEnd:options.forecastEnd,horizon:options.horizon},answer,options),id:row.row_id,source:row,real:true};
  });
}

export async function calculateSource(options,items,changes={}){
  const prepared=await api('/planning/source-input',sourcePayload(options,items));
  const input={...prepared.input,forecast_end:options.forecastEnd,exclude_bulk:options.excludeBulk,compensate_stockouts:options.recoverStockouts,
    rows:prepared.input.rows.map(row=>({...row,...changes[row.row_id]}))};
  const result=await api('/planning/calculate',input);
  return {input,result,rows:displayRows(input,result,options),usage:prepared.usage};
}

export async function saveApproval(input,rows,actor,onSaved){
  let saved=await api('/scenarios',{name:`Закупка ${input.planning_date} · ${new Date().toLocaleString('ru-RU')}`,input});
  onSaved(saved);
  const overrides=rows.filter(r=>String(r.order)!==String(r.quantity)).map(r=>({row_id:r.id,quantity:String(r.order),reason:r.note.trim()}));
  if(overrides.length){saved=await api(`/scenarios/${saved.id}`,{expected_revision:saved.revision,name:saved.name,input,overrides},'PUT');onSaved(saved);}
  saved=await api(`/scenarios/${saved.id}/approve`,{expected_revision:saved.revision,approved_by:actor.trim(),acknowledge_scenario:true});
  onSaved(saved);return saved;
}
