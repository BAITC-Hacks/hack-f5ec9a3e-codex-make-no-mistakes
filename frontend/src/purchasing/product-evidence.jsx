import {useEffect,useState} from 'react';
import {products,dateLabel,addDays,daysBetween,historyBounds} from './replenishment-demo.js';
import './product-evidence.css';
import {calculatePlan} from './planning-api.js';

const fmt=value=>value==null?'—':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(value);
export function stockoutPeriods(history){
  const periods=[];
  for(const day of history){
    if(!day.stockout)continue;
    const last=periods.at(-1);
    if(last&&addDays(last.end,1)===day.date){last.end=day.date;last.days++;}
    else periods.push({start:day.date,end:day.date,days:1});
  }
  return periods;
}

function DemandChart({row,options}){
  const [focus,setFocus]=useState(null);
  const points=[...row.dailyHistory.map(day=>({...day,clean:day.stockout?null:day.regular})),...row.forecastSeries];
  const width=720,height=230,left=42,right=16,top=18,bottom=36;
  const first=points[0].date,last=row.forecastEnd,span=Math.max(1,daysBetween(first,last));
  const max=Math.max(1,row.daily,...row.dailyHistory.map(p=>p.raw))*1.15;
  const x=date=>left+daysBetween(first,date)/span*(width-left-right);
  const y=value=>height-bottom-value/max*(height-top-bottom);
  const line=key=>{let started=false;return points.map(p=>{if(p[key]==null){started=false;return '';}const command=started?'L':'M';started=true;return `${command}${x(p.date).toFixed(2)},${y(p[key]).toFixed(2)}`;}).join(' ');};
  const shown=focus??points.at(-1);
  return <section className="ev-chart"><div className="ev-legend"><span className="raw">Продажи</span><span className="forecast">Прогноз</span><span className="stockout">Нет в наличии</span></div>
    <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Продажи и прогноз для ${row.sku}; прогноз ${fmt(row.daily)} ${row.unit} в день`}>
      <rect x={x(row.planningDate)} y={top} width={Math.max(0,width-right-x(row.planningDate))} height={height-top-bottom} fill="#edf4e8"/>
      {stockoutPeriods(row.dailyHistory).map(p=><rect key={p.start} x={x(p.start)} y={top} width={Math.max(2,x(addDays(p.end,1))-x(p.start))} height={height-top-bottom} fill="#fff0d9"/>)}
      {[0,0.5,1].map(f=><g key={f}><line x1={left} x2={width-right} y1={y(max*f)} y2={y(max*f)} stroke="#e3e9df"/><text x={left-7} y={y(max*f)+4} textAnchor="end">{fmt(max*f)}</text></g>)}
      <path d={line('raw')} className="ev-line raw"/><path d={line('forecast')} className="ev-line forecast"/>
      {row.dailyHistory.filter(p=>p.bulk>0).map(p=><circle key={p.date} cx={x(p.date)} cy={y(p.raw)} r="4" fill="#bc8034"><title>{dateLabel(p.date)}: разовая продажа {p.bulk} {row.unit}</title></circle>)}
      <line x1={x(row.planningDate)} x2={x(row.planningDate)} y1={top} y2={height-bottom} stroke="#729b70" strokeDasharray="4 4"/>
      <text x={left} y={height-10}>{dateLabel(first)}</text><text x={width-right} y={height-10} textAnchor="end">{dateLabel(last)}</text>
      {focus&&<circle cx={x(focus.date)} cy={y(focus.forecast??focus.raw)} r="5" fill="#234f38"/>}
      <rect x={left} y={top} width={width-left-right} height={height-top-bottom} fill="transparent" onPointerMove={e=>{const box=e.currentTarget.ownerSVGElement.getBoundingClientRect();const fraction=Math.max(0,Math.min(1,((e.clientX-box.left)/box.width*width-left)/(width-left-right)));const target=addDays(first,Math.round(fraction*span));setFocus(points.reduce((nearest,p)=>Math.abs(daysBetween(p.date,target))<Math.abs(daysBetween(nearest.date,target))?p:nearest));}}/>
    </svg>
    <div className="ev-chart-readout" aria-live="polite"><b>{dateLabel(shown.date)}</b><span>{shown.forecast!=null?`Прогноз: ${fmt(shown.forecast)} ${row.unit}`:`Продажи: ${shown.raw} ${row.unit}`}</span></div>
    <label className="ev-date-inspect">Проверить день<select value={shown.date} onChange={e=>setFocus(points.find(p=>p.date===e.target.value))}>{points.map(p=><option key={p.date} value={p.date}>{dateLabel(p.date)}</option>)}</select></label>
    <p>Прогноз и его дневная кривая получены из API. Серые значения — входные синтетические продажи. Дневной очищенный ряд API не возвращает: эффект очистки показан отдельно, без выдумывания точек графика.</p>

  </section>;
}

export default function ProductEvidence({row,options}){
  const [tab,setTab]=useState('demand');
  const item=products.find(p=>p.sku===row.sku);
  const inputs={...options,stock:row.stock,incoming:row.incomingTotal};
  const [comparison,setComparison]=useState(null),[comparisonError,setComparisonError]=useState('');
  const signature=JSON.stringify(inputs);
  useEffect(()=>{
    if(!['outliers','stockouts'].includes(tab))return;
    const controller=new AbortController();setComparison(null);setComparisonError('');
    const flag=tab==='outliers'?'excludeBulk':'recoverStockouts';
    Promise.all([false,true].map(value=>calculatePlan({...inputs,[flag]:value},{[row.sku]:{stock:row.stock,incoming:row.incomingTotal}},controller.signal,[item])))
      .then(([before,after])=>{if(!controller.signal.aborted)setComparison({before:before[0],after:after[0]});})
      .catch(error=>{if(!controller.signal.aborted)setComparisonError(error.message);});
    return ()=>controller.abort();
  },[tab,signature,row.sku]);
  const withBulk=comparison?.before,withoutBulk=comparison?.after,rawStockouts=comparison?.before,recovered=comparison?.after;
  const anomalies=row.dailyHistory.filter(p=>p.bulk>0),periods=stockoutPeriods(row.dailyHistory);
  return <section className="ev-panel" aria-label="Доказательства расчёта"><header><div><small>ОБОСНОВАНИЕ ПРОГНОЗА</small><h3>Что стоит за рекомендацией</h3></div><span className="ek-demo">СИНТЕТИЧЕСКИЕ ДАННЫЕ</span></header>
    <div className="ev-tabs" role="tablist" aria-label="Данные для обоснования">{[['demand','Спрос и прогноз'],['outliers',`Разовые продажи · ${anomalies.length}`],['stockouts',`Нет в наличии · ${row.stockoutDays} дн.`],['deliveries',`Поступления · ${row.deliveries.length}`]].map(([id,label])=><button key={id} type="button" role="tab" id={`ev-tab-${id}`} aria-selected={tab===id} aria-controls={`ev-content-${id}`} onClick={()=>setTab(id)}>{label}</button>)}</div>
    {comparisonError&&<p role="alert">{comparisonError}</p>}{['outliers','stockouts'].includes(tab)&&!comparison&&!comparisonError&&<p role="status">Сравниваем два сценария через API…</p>}
    <div role="tabpanel" id={`ev-content-${tab}`} aria-labelledby={`ev-tab-${tab}`}>
      {tab==='demand'&&<DemandChart row={row} options={options}/>}
      {tab==='outliers'&&<><div className="ev-comparison"><article><span>Заказ с разовыми продажами</span><b>{fmt(withBulk?.quantity)} {row.unit}</b></article><span>→</span><article><span>После исключения</span><b>{fmt(withoutBulk?.quantity)} {row.unit}</b></article></div><p>Исключение {options.excludeBulk?'включено':'выключено'} в текущем расчёте. Сравнение меняет только этот фактор. Окончательные исключения определяет сервер. Таблица показывает исходные синтетические крупные продажи, а не подтверждённые исключения.</p>{anomalies.length?<div className="ev-table"><table><thead><tr><th>Дата</th><th>Клиент</th><th>Количество</th><th>Причина / статус</th></tr></thead><tbody>{anomalies.map(day=><tr key={day.date}><td>{dateLabel(day.date)}</td><td>C-0042</td><td>{day.bulk} {row.unit}</td><td>Разовая проектная закупка · входная продажа{day.date<addDays(row.historyEnd,1-row.forecastHistoryDays)?' · вне окна модели':''}</td></tr>)}</tbody></table></div>:<p className="ev-empty">В выбранном диапазоне разовых продаж нет.</p>}</>}
      {tab==='stockouts'&&<><div className="ev-comparison"><article><span>Без восстановления спроса</span><b>{fmt(rawStockouts?.quantity)} {row.unit}</b></article><span>→</span><article><span>С восстановлением</span><b>{fmt(recovered?.quantity)} {row.unit}</b></article></div><p>Компенсация {options.recoverStockouts?'включена':'выключена'}. Оценка потерянного спроса API при включении: {fmt(recovered?.lost)} {row.unit}. Это оценка, не зафиксированные продажи.</p>{periods.length?<div className="ev-table"><table><thead><tr><th>Без остатка с</th><th>По</th><th>Дней</th><th>Источник</th></tr></thead><tbody>{periods.map(p=><tr key={p.start}><td>{dateLabel(p.start)}</td><td>{dateLabel(p.end)}</td><td>{p.days}</td><td>Синтетический журнал</td></tr>)}</tbody></table></div>:<p className="ev-empty">Периодов отсутствия в выбранной истории нет.</p>}<p>Детальный метод компенсации определяется сервером и показан в его пояснениях ниже.</p></>}
      {tab==='deliveries'&&<><div className="ev-comparison"><article><span>Всего ожидается</span><b>{row.incomingTotal} {row.unit}</b></article><span>→</span><article><span>Учтено до {dateLabel(row.forecastEnd)}</span><b>{row.incoming} {row.unit}</b></article></div><p>Синтетический график: 60% поставки за два дня до обычного срока, остаток через 10 дней после него. Поступления за пределами горизонта не уменьшают заказ.</p>{row.deliveries.length?<div className="ev-table"><table><thead><tr><th>Поставка</th><th>Приход</th><th>Количество</th><th>В расчёте</th></tr></thead><tbody>{row.deliveries.map(d=><tr key={d.id}><td>{d.id}</td><td>{dateLabel(d.date)}</td><td>{d.quantity} {row.unit}</td><td><span className={`ev-status ${d.included?'':'missing'}`}>{d.included?'Учтено':'Не учтено'}</span><small>{d.reason}</small></td></tr>)}</tbody></table></div>:<p className="ev-empty">Подтверждённых в демо поступлений нет.</p>}<p>Новый рекомендованный заказ придёт {dateLabel(row.arrivalDate)} и не включён повторно в «товары в пути».</p></>}
    </div>
    <details className="ev-api-notes"><summary>Пояснения и ограничения сервера</summary><ul>{[...row.adjustments,...row.warnings].map((note,i)=><li key={i}>{note}</li>)}</ul></details>
  </section>;
}

export function ScenarioSources({options,rows}){
  const entries=[
    ['Продажи',`${dateLabel(options.historyStart)} — ${dateLabel(options.historyEnd)}`,`${rows.length} SKU · ${rows.reduce((sum,r)=>sum+r.historyDays,0)} дневных наблюдений`,'Используются'],
    ['Остатки',`${options.warehouse} · ${dateLabel(options.planningDate)}`,`${rows.length} SKU; сценарные значения на дату расчёта`,'Используются'],
    ['Товары в пути',`До ${dateLabel(options.forecastEnd)}`,`${rows.reduce((sum,r)=>sum+r.deliveries.filter(d=>d.included).length,0)} поступлений внутри горизонта`,'Используются'],
    ['Периоды отсутствия','Ежедневные отметки наличия',`${rows.filter(r=>r.stockoutDays>0).length} SKU с периодами отсутствия`,options.recoverStockouts?'Используются':'Компенсация выключена'],
    ['Поставщики и условия','Сроки, цена, кратность',`${new Set(rows.map(r=>r.supplier)).size} поставщика`,'Используются'],
    ['Сезонность и рост','Заданные коэффициенты','Не вычислены из импортированных данных',`Сезонность ${options.seasonality?'вкл.':'выкл.'} · рост ${options.growth?'вкл.':'выкл.'}`],
    ['BOM / спецификации 1С','Источник отсутствует','Состав комплектов не учитывается','Нет данных'],
  ];
  return <section className="ek-card ek-info ev-source-status"><h2>Что использовано в текущем расчёте</h2><p>Источник: генератор демо, а не загруженный файл. Доступная история {dateLabel(historyBounds.start)} — {dateLabel(historyBounds.end)}. Импортированные книги ниже хранятся отдельно и пока не питают эти рекомендации.</p><div className="ev-table"><table><thead><tr><th>Вход</th><th>Период / актуальность</th><th>Покрытие / ограничения</th><th>Статус</th></tr></thead><tbody>{entries.map(([title,period,coverage,status])=><tr key={title}><td>{title}</td><td>{period}</td><td>{coverage}</td><td><span className={`ev-status ${status==='Нет данных'?'missing':''}`}>{status}</span></td></tr>)}</tbody></table></div>{rows.some(r=>r.needsInput)&&<p role="alert">Есть SKU без доступных наблюдений в окне модели. Утверждение заблокировано.</p>}</section>;
}
