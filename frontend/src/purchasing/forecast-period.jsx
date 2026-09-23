import './period.css';

const daysBetween=(start,end)=>Math.round((Date.parse(end+'T00:00:00Z')-Date.parse(start+'T00:00:00Z'))/86400000)+1;
const endAfter=(start,days)=>new Date(Date.parse(start+'T00:00:00Z')+(days-1)*86400000).toISOString().slice(0,10);
const label=date=>date?date.split('-').reverse().join('.'):'Выберите дату';

export default function ForecastPeriod({input,onChange,disabled=false}){
  const days=input.forecast_end&&input.planning_date?daysBetween(input.planning_date,input.forecast_end):'';
  const invalid=days!==''&&(!Number.isInteger(days)||days<1||days>730);
  return <details className="ek-period-picker">
    <summary><span>Период прогноза</span><strong><span>{input.forecast_end?`${label(input.planning_date)} — ${label(input.forecast_end)}`:'Выбрать свои даты'}</span><small>{days!==''?`${days} дн.`:'По срокам поставки'} ▾</small></strong></summary>
    <div className="ek-period-popover">
      <h3>Выберите свой период</h3>
      <div className="ek-date-fields">
        <label>Начало прогноза<input disabled={disabled} type="date" value={input.planning_date} onChange={e=>onChange({...input,planning_date:e.target.value})}/></label>
        <label>Прогноз по дату включительно<input disabled={disabled} type="date" min={input.planning_date} value={input.forecast_end||''} onChange={e=>onChange({...input,forecast_end:e.target.value||null,forecast_method:'auto'})}/></label>
      </div>
      <label>Количество дней<input disabled={disabled} type="number" min="1" max="730" step="1" value={Number.isFinite(days)?days:''} onChange={e=>{const value=Number(e.target.value);if(e.target.value==='' )onChange({...input,forecast_end:null});else if(input.planning_date&&Number.isInteger(value)&&value>=1&&value<=730)onChange({...input,forecast_end:endAfter(input.planning_date,value),forecast_method:'auto'});}}/></label>
      <p>Любые даты, от 1 до 730 дней. Обе границы включены. Метод выбирается автоматически по истории каждого товара.</p>
      {invalid&&<p role="alert">Конец должен быть не раньше начала; максимум 730 дней.</p>}
      {!input.forecast_end&&<p>Пока конец не выбран, горизонт каждой позиции определяется сроком поставки и интервалом пересмотра.</p>}
      <button className="ek-primary" disabled={disabled||invalid||!input.planning_date||!input.forecast_end} onClick={e=>{e.currentTarget.closest('details').open=false;}}>Применить период</button>
    </div>
  </details>;
}
