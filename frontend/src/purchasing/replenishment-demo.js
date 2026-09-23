// Synthetic fixtures with a real baseline formula, not a trained ML forecast.
export const warehouses = ['Алматы · Основной', 'Астана · Основной'];
export const products = [
  ['EK-1001','Кабель ВВГнг-LS 3×2,5','Кабель и провод','КазЭлектроКабель','м',120,20,600,8,60,1.2,1.15,420,7,50],
  ['EK-1002','Кабель ВВГнг-LS 3×1,5','Кабель и провод','КазЭлектроКабель','м',480,160,420,0,900,1.1,1.08,280,7,50],
  ['EK-1003','Провод ПВС 2×1,5','Кабель и провод','КазЭлектроКабель','м',900,0,180,0,0,1,1,210,7,50],
  ['EK-2001','Автоматический выключатель C16 1P','Модульное оборудование','IEK Казахстан','шт.',24,12,120,5,0,1.1,1.12,1450,5,12],
  ['EK-2002','УЗО 40А / 30мА 2P','Модульное оборудование','IEK Казахстан','шт.',18,10,48,0,80,1.05,1.1,8900,5,6],
  ['EK-2003','Щит распределительный 12 модулей','Модульное оборудование','IEK Казахстан','шт.',8,0,30,3,0,1.15,1.05,4200,5,4],
  ['EK-3001','Светильник LED ДВО 36 Вт','Освещение','Signify Казахстан','шт.',16,20,90,6,120,1.3,1.1,5600,10,6],
  ['EK-3002','Лампа LED E27 12 Вт','Освещение','Signify Казахстан','шт.',160,80,240,0,0,1.2,1.05,620,10,10],
].map(([sku,name,category,supplier,unit,stock,incoming,regularSales,stockoutDays,bulkSales,season,growth,price,lead,multiple])=>({sku,name,category,supplier,unit,stock,incoming,regularSales,stockoutDays,bulkSales,season,growth,price,lead,multiple,historyDays:30}));
const DAY=86400000;
export const historyBounds={start:'2025-09-23',end:'2026-09-22'};
export const addDays=(date,days)=>new Date(Date.parse(date+'T00:00:00Z')+days*DAY).toISOString().slice(0,10);
export const daysBetween=(start,end)=>Math.round((Date.parse(end+'T00:00:00Z')-Date.parse(start+'T00:00:00Z'))/DAY);
export const dateLabel=date=>new Intl.DateTimeFormat('ru-RU',{timeZone:'UTC'}).format(new Date(date+'T00:00:00Z'));
const validDate=date=>/^\d{4}-\d{2}-\d{2}$/.test(date||'')&&Number.isFinite(Date.parse(date+'T00:00:00Z'))&&new Date(date+'T00:00:00Z').toISOString().slice(0,10)===date;
export function validateOptions(options){
  if(![options.planningDate,options.forecastEnd,options.historyStart,options.historyEnd].every(validDate))return 'Заполните все даты корректными значениями.';
  if(options.forecastEnd<options.planningDate)return 'Конец прогноза должен быть не раньше даты расчёта.';
  if(!Number.isInteger(Number(options.horizon))||Number(options.horizon)<1||Number(options.horizon)>730)return 'Горизонт прогноза: от 1 до 730 целых дней.';
  if(daysBetween(options.planningDate,options.forecastEnd)+1!==Number(options.horizon))return 'Проверьте даты и длительность прогноза.';
  const selected=products.filter(p=>options.category==='Все категории'||p.category===options.category);
  if(selected.some(p=>Number(options.horizon)-p.lead<1||Number(options.horizon)-p.lead>365))return 'Период должен включать срок поставки и от 1 до 365 дней покрытия после неё (ограничение API).';
  if(options.historyStart>options.historyEnd)return 'Начало истории должно быть не позже её окончания.';
  if(options.historyStart<historyBounds.start||options.historyEnd>historyBounds.end)return 'Демо-история доступна с 23.09.2025 по 22.09.2026.';
  if(options.historyEnd>=options.planningDate)return 'История продаж должна заканчиваться раньше даты расчёта.';
  return '';
}
export function buildDemoRow(item,options) {
  const validation=validateOptions(options);
  if(validation)throw new Error(validation);
  const scale=options.warehouse===warehouses[1]?0.65:1;
  const stock=options.stock??Math.round(item.stock*scale);
  const incomingTotal=options.incoming??Math.round(item.incoming*scale);
  const firstReceipt=Math.ceil(incomingTotal*0.6);
  const deliveries=[
    {id:`${item.sku}-01`,date:addDays(options.planningDate,Math.max(1,item.lead-2)),quantity:firstReceipt},
    {id:`${item.sku}-02`,date:addDays(options.planningDate,item.lead+10),quantity:incomingTotal-firstReceipt},
  ].filter(receipt=>receipt.quantity>0).map(receipt=>({...receipt,included:receipt.date<=options.forecastEnd}));
  const incoming=deliveries.filter(receipt=>receipt.included).reduce((sum,receipt)=>sum+receipt.quantity,0);
  const historyDays=daysBetween(options.historyStart,options.historyEnd)+1;
  let regularSales=0,bulkSales=0,stockoutDays=0;
  const dailyHistory=[];
  // Deterministic synthetic daily observations; the selected range filters real dates.
  for(let offset=0;offset<historyDays;offset++){
    const date=addDays(options.historyStart,offset),day=new Date(date+'T00:00:00Z');
    if(day.getUTCDate()<=item.stockoutDays){stockoutDays++;dailyHistory.push({date,raw:0,regular:0,bulk:0,stockout:true});continue;}
    const weekday=day.getUTCDay()===0?0.55:day.getUTCDay()===6?0.8:1.13;
    const monthFactor=0.8+day.getUTCMonth()*0.025;
    const regular=Math.round(item.regularSales/(30-item.stockoutDays)*scale*weekday*monthFactor);
    const bulk=day.getUTCDate()===15?Math.round(item.bulkSales*scale):0;
    regularSales+=regular;bulkSales+=bulk;
    dailyHistory.push({date,raw:regular+bulk,regular,bulk,stockout:false});
  }
  const rawSales=regularSales+bulkSales;
  const excluded=options.excludeBulk?bulkSales:0;
  const availableDays=historyDays-stockoutDays;
  return {...item,stock,incoming,incomingTotal,deliveries,dailyHistory,rawSales,excluded,historyDays,stockoutDays,availableDays,
    planningDate:options.planningDate,forecastEnd:options.forecastEnd,historyStart:options.historyStart,historyEnd:options.historyEnd,horizon:Number(options.horizon)};
}

export const defaults={warehouse:warehouses[0],category:'Все категории',planningDate:'2026-09-23',forecastEnd:'2026-10-13',historyStart:'2026-07-29',historyEnd:'2026-09-22',horizon:21,excludeBulk:false,recoverStockouts:false,seasonality:false,growth:false};
export function csv(rows) {
  const escape=value=>'"'+String(value).replaceAll('"','""')+'"';
  return '\uFEFF'+[['SKU','Наименование','Склад','Поставщик','Количество','Ед.','Дата расчёта','Прогноз до','История с','История по','Рекомендуемое количество','Обоснование','Срочность','Комментарий','Метод прогноза','Дней истории в модели'],...rows.map(r=>[r.sku,r.name,r.warehouse,r.supplier,r.order,r.unit,r.planningDate,r.forecastEnd,r.historyStart,r.historyEnd,r.quantity,r.reason,r.urgency,r.note||'',r.method,r.forecastHistoryDays])].map(row=>row.map(escape).join(';')).join('\r\n');
}
