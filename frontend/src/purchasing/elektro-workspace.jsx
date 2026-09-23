import {useEffect,useRef,useState} from 'react';
import {Boxes,Truck,FileText,Database,BookOpen,Calculator,ArrowDownToLine,Check,Search,X,ArrowUpRight} from 'lucide-react';
import {products,warehouses,defaults,csv,addDays,daysBetween,dateLabel,historyBounds,validateOptions} from './replenishment-demo.js';
import './purchasing-prototype.css';
import './elektro.css';
import './period.css';
import {calculatePlan} from './planning-api.js';
import DataSources from './data-sources.jsx';
import ProductEvidence,{ScenarioSources} from './product-evidence.jsx';

const fmt=value=>value==null?'Нет данных':new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(value);
const money=value=>`${fmt(value)} ₸`;
const navigation=[['planning','Пополнение склада','Расчёт и проверка потребности',Boxes],['orders','Заказы поставщикам','Утверждение и экспорт',Truck],['sources','Источники данных','Продажи, остатки и поставки',Database],['method','Логика расчёта','Факторы спроса и исключения',BookOpen]];
const flags=[['excludeBulk','Исключать разовые крупные продажи'],['recoverStockouts','Восстанавливать спрос при дефиците'],['seasonality','Учитывать сезонность'],['growth','Учитывать устойчивый рост']];

export default function ElektroWorkspace(){
  const [view,setView]=useState('planning');
  const [options,setOptions]=useState(defaults),[snapshot,setSnapshot]=useState(defaults);
  const [inputEdits,setInputEdits]=useState({}),[appliedInputs,setAppliedInputs]=useState({});
  const [edits,setEdits]=useState({}),[notes,setNotes]=useState({});
  const [approved,setApproved]=useState(false),[query,setQuery]=useState(''),[supplier,setSupplier]=useState('Все поставщики');
  const [detail,setDetail]=useState(null),[confirm,setConfirm]=useState(false),[notice,setNotice]=useState('');
  const dialog=useRef(null);
  useEffect(()=>{if(detail||confirm)dialog.current?.showModal();else dialog.current?.close();},[detail,confirm]);
  const dirty=JSON.stringify(options)!==JSON.stringify(snapshot)||JSON.stringify(inputEdits)!==JSON.stringify(appliedInputs);
  const [apiRows,setApiRows]=useState([]),[loading,setLoading]=useState(true),[apiError,setApiError]=useState(''),[retry,setRetry]=useState(0);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setApiError('');setApiRows([]);setApproved(false);
    calculatePlan(snapshot,appliedInputs,controller.signal).then(result=>{if(!controller.signal.aborted)setApiRows(result);})
      .catch(error=>{if(!controller.signal.aborted)setApiError(error.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[snapshot,appliedInputs,retry]);
  const rows=apiRows.map(result=>({...result,order:edits[result.sku]??result.quantity,note:notes[result.sku]||''}));
  const ordered=rows.filter(r=>r.order>0);
  const total=ordered.reduce((sum,r)=>sum+r.order*r.price,0);
  const validation=validateOptions(options);
  const invalid=rows.some(r=>r.needsInput||!Number.isInteger(r.order)||r.order<0||(r.order!==r.quantity&&!r.note.trim()));
  const canApprove=ordered.length>0&&!invalid&&!dirty&&!loading&&!apiError;
  const suppliers=[...new Set(rows.map(r=>r.supplier))];
  const visible=rows.filter(r=>(supplier==='Все поставщики'||r.supplier===supplier)&&`${r.sku} ${r.name}`.toLocaleLowerCase('ru').includes(query.toLocaleLowerCase('ru')));
  const selected=rows.find(r=>r.sku===detail);
  const changeOptions=(key,value)=>{
    setOptions(o=>{
      const next={...o,[key]:value};
      if(key==='horizon'&&value!==''&&Number.isInteger(Number(value))&&Number(value)>=1&&Number(value)<=730&&o.planningDate)next.forecastEnd=addDays(o.planningDate,Number(value)-1);
      if(key==='planningDate'&&value&&o.forecastEnd)next.horizon=daysBetween(value,o.forecastEnd)+1;
      if(key==='forecastEnd'&&value&&o.planningDate)next.horizon=daysBetween(o.planningDate,value)+1;
      return next;
    });
    if(key==='warehouse')setInputEdits({});setApproved(false);setNotice('');
  };
  const historyPreset=days=>{setOptions(o=>({...o,historyStart:addDays(o.historyEnd||historyBounds.end,1-days),historyEnd:o.historyEnd||historyBounds.end}));setApproved(false);setNotice('');};
  const recalculate=()=>{if(validation){setNotice(validation);return;}setSnapshot({...options});setAppliedInputs(structuredClone(inputEdits));setEdits({});setNotes({});setSupplier('Все поставщики');setApproved(false);setNotice('Рекомендации пересчитаны. Проверьте количества перед утверждением.');};
  const download=(subset)=>{
    if(!approved||dirty)return;
    const url=URL.createObjectURL(new Blob([csv(subset)],{type:'text/csv;charset=utf-8;'}));
    const link=document.createElement('a');link.href=url;link.download='elektrokomplekt-demo-orders.csv';link.click();URL.revokeObjectURL(url);
    setNotice('CSV скачан. Заказ поставщику не отправлен.');
  };
  const close=()=>{setDetail(null);setConfirm(false);};
  return <div className="pp2 ek">
    <aside className="pp2-sidebar">
      <div className="pp2-brand"><span>ЭК</span><div><strong>ЭЛЕКТРОКОМПЛЕКТ</strong><small>КОНТУР ЗАКУПОК</small></div></div>
      <div className="ek-workspace-label">РАБОЧЕЕ МЕСТО ЗАКУПЩИКА</div>
      <nav aria-label="Основное меню">{navigation.map(([id,label,desc,Icon])=><button key={id} className={id===view?'is-active':''} onClick={()=>setView(id)}><span className="pp2-nav-icon"><Icon/></span><span className="pp2-nav-copy"><b>{label}</b><small>{desc}</small></span></button>)}</nav>
      <div className="pp2-sidebar-footer"><div className="pp2-source"><span/><div><strong>Демонстрационные данные</strong><small>Локальный сценарий · без отправки</small></div></div></div>
    </aside>
    <main className="pp2-main">
      <div className="ek-topline"><span>Электрокомплект / Рабочее пространство</span><span className="ek-demo">ДЕМО · {dateLabel(snapshot.planningDate)}</span></div>
      <nav className="ek-mobile-nav" aria-label="Разделы">{navigation.map(([id,label])=><button key={id} onClick={()=>setView(id)} aria-current={view===id?'page':undefined}>{label}</button>)}</nav>
      <header className="pp2-heading ek-heading"><div><p>ПЛАНИРОВАНИЕ ЗАКУПОК</p><h1>{navigation.find(n=>n[0]===view)[1]}</h1><div className="ek-subtitle">{view==='planning'?'От истории продаж — к обоснованному заказу поставщику.':view==='orders'?'Проверьте состав, утвердите и выгрузите заказ.':'Прозрачные исходные данные и правила расчёта.'}</div></div><span className="ek-person">МЗ <small>Менеджер закупок</small></span></header>
      {view!=='sources'&&<div className="ek-notice">Демо-данные · прогноз рассчитан сервером · без автоматической отправки</div>}
      {loading&&<div role="status" className="ek-feedback">Получаем прогноз и рекомендации из API…</div>}
      {apiError&&<div role="alert" className="ek-warning">{apiError} <button className="ek-secondary" onClick={()=>setRetry(v=>v+1)}>Повторить расчёт</button></div>}
      {notice&&<div role="status" className="ek-feedback">{notice}</div>}
      {(view==='planning'||view==='orders')&&<>
        <section className="ek-card ek-controls" aria-label="Параметры расчёта">
          <label>Склад<select value={options.warehouse} onChange={e=>changeOptions('warehouse',e.target.value)}>{warehouses.map(w=><option key={w}>{w}</option>)}</select></label>
          <label>Категория<select value={options.category} onChange={e=>changeOptions('category',e.target.value)}>{['Все категории',...new Set(products.map(p=>p.category))].map(c=><option key={c}>{c}</option>)}</select></label>
          <details className="ek-period-picker"><summary><span>Период прогноза</span><strong><span>{options.planningDate?dateLabel(options.planningDate):'Начало'} — {options.forecastEnd?dateLabel(options.forecastEnd):'Конец'}</span><small>{options.horizon||'—'} дн. ▾</small></strong></summary><div className="ek-period-popover"><h3>Выберите свой период</h3><div className="ek-date-fields"><label>Начало прогноза<input type="date" value={options.planningDate} onChange={e=>changeOptions('planningDate',e.target.value)}/></label><label>Прогноз по дату включительно<input type="date" min={options.planningDate||undefined} value={options.forecastEnd} onChange={e=>changeOptions('forecastEnd',e.target.value)}/></label></div><label>Количество дней<input type="number" min="1" max="730" step="1" value={options.horizon} onChange={e=>changeOptions('horizon',e.target.value===''?'':Number(e.target.value))}/></label><p>Укажите свои даты. Обе даты включены. Период должен покрывать срок поставки плюс 1–365 дней; ограничения проверяются до расчёта.</p><button className="ek-primary" disabled={!!validation} onClick={e=>{e.currentTarget.closest('details').open=false;}}>Применить период</button></div></details>
          <button className="ek-primary" disabled={!!validation||loading} onClick={recalculate}><Calculator size={17}/>Рассчитать потребность</button>
          {validation&&<p role="alert" className="ek-date-error">{validation}</p>}
          <details className="ek-factors"><summary>Настройки расчёта · история и факторы спроса</summary><div>{flags.map(([key,label])=><label key={key}><input type="checkbox" checked={options[key]} onChange={e=>changeOptions(key,e.target.checked)}/>{label}</label>)}<section className="ek-history-settings"><h3>История продаж</h3><div className="ek-date-fields"><label>История с<input type="date" min={historyBounds.start} max={historyBounds.end} value={options.historyStart} onChange={e=>changeOptions('historyStart',e.target.value)}/></label><label>История по<input type="date" min={historyBounds.start} max={historyBounds.end} value={options.historyEnd} onChange={e=>changeOptions('historyEnd',e.target.value)}/></label></div><div className="ek-presets">{[30,90,180,365].map(days=><button key={days} aria-pressed={daysBetween(options.historyStart,options.historyEnd)+1===days} onClick={()=>historyPreset(days)}>{days} дней</button>)}</div><p>Демо-история: {dateLabel(historyBounds.start)} — {dateLabel(historyBounds.end)}</p></section></div></details>
        </section>
        {dirty&&<p className="ek-warning" role="status">Параметры изменены. Нажмите «Рассчитать потребность» — ниже показан предыдущий расчёт.</p>}
        <p className="ek-period-summary">Расчёт: {dateLabel(snapshot.planningDate)} — {dateLabel(snapshot.forecastEnd)} · {snapshot.horizon} дней. История: {dateLabel(snapshot.historyStart)} — {dateLabel(snapshot.historyEnd)}. Остатки — сценарий на дату расчёта.</p>
        <section className="ek-metrics" aria-label="Результат расчёта">
          <article><span>К пополнению</span><strong>{ordered.length}<small> / {rows.length} SKU</small></strong><p>{new Set(ordered.map(r=>r.supplier)).size} поставщика · {snapshot.warehouse}</p></article>
          <article className="ek-risk"><span>Риск до прихода поставки</span><strong>{rows.filter(r=>r.cover<r.lead).length}<small> SKU</small></strong><p>Текущего остатка не хватит до поставки</p></article>
          <article><span>Сумма закупки</span><strong>{money(total)}</strong><p>По демонстрационным закупочным ценам</p></article>
          <article><span>Разовые крупные продажи</span><strong>{rows.filter(r=>r.excluded>0).length}<small> SKU</small></strong><p>Исключены из регулярного спроса</p></article>
        </section>
        <div className="ek-toolbar"><div className="ek-tabs"><button className={view==='planning'?'active':''} onClick={()=>setView('planning')}>Рекомендации</button><button className={view==='orders'?'active':''} onClick={()=>setView('orders')}>Заказы по поставщикам</button></div><div className="ek-search"><Search size={16}/><input aria-label="Поиск SKU или товара" placeholder="SKU или название" value={query} onChange={e=>setQuery(e.target.value)}/></div><select aria-label="Фильтр поставщика" value={supplier} onChange={e=>setSupplier(e.target.value)}>{['Все поставщики',...suppliers].map(s=><option key={s}>{s}</option>)}</select></div>
        <div className="ek-results">
          <div className="ek-groups">{suppliers.filter(s=>visible.some(r=>r.supplier===s)).map(s=>{
            const group=visible.filter(r=>r.supplier===s&&(view!=='orders'||r.order>0));
            if(!group.length)return null;
            return <section className="ek-card ek-supplier" key={s}><header><div><Truck size={19}/><div><h2>{s}</h2><p>Приход {dateLabel(group[0].arrivalDate)} · {group[0].lead} дней · {group.length} позиций</p></div></div><strong>{money(group.reduce((sum,r)=>sum+r.order*r.price,0))}</strong></header>
              <div className="ek-table-scroll"><table><thead><tr><th>Товар / обоснование</th><th>Остаток / в пути</th><th>Прогноз / день</th><th>К заказу</th><th>Сумма</th><th>Срочность</th></tr></thead><tbody>{group.map(r=><tr key={r.sku}><td><small className="ek-sku">{r.sku} · {r.category}</small><b>{r.name}</b><button className="ek-reason" onClick={()=>setDetail(r.sku)}>{r.needsInput?'Уточнить исходные данные':'Почему такое количество?'}<ArrowUpRight size={14}/></button>{r.order!==r.quantity&&<input className="ek-comment" aria-label={`Причина корректировки ${r.sku}`} placeholder="Причина корректировки — обязательно" value={r.note} onChange={e=>{setNotes(n=>({...n,[r.sku]:e.target.value}));setApproved(false);}}/>}</td><td><b>{fmt(r.stock)} {r.unit}</b><small>+ {fmt(r.incoming)} в пути</small></td><td><b>{fmt(r.daily)} {r.unit}</b><small>сезон ×{r.season} · рост ×{r.growth}</small></td><td><input disabled={r.needsInput} className="ek-quantity" aria-label={`Заказать ${r.sku}`} type="number" min="0" step="1" value={r.order??''} onChange={e=>{setEdits(v=>({...v,[r.sku]:Number(e.target.value)}));setApproved(false);setNotice('');}}/><small>рекомендация: {r.quantity} {r.unit}</small></td><td><b>{money(r.order*r.price)}</b></td><td><span className={`ek-urgency ${r.urgency==='Срочно'?'urgent':r.urgency==='На этой неделе'?'soon':''}`}>{r.needsInput?'Нет истории наличия':r.quantity===0?'Запаса хватает':r.urgency}</span></td></tr>)}</tbody></table></div>
              {view==='orders'&&<footer><button className="ek-secondary" disabled={!approved||dirty} onClick={()=>download(ordered.filter(r=>r.supplier===s))}><ArrowDownToLine size={16}/>CSV поставщика</button></footer>}
            </section>;
          })}{(!visible.length||(view==='orders'&&!visible.some(r=>r.order>0)))&&<div className="ek-card ek-empty">Нет позиций. Измените фильтры или параметры расчёта.</div>}</div>
          <aside className="ek-summary"><span className="ek-summary-label">{approved?'УТВЕРЖДЕНО · ДЕМО':'НА ПРОВЕРКЕ'}</span><h2>План закупки</h2><strong>{money(total)}</strong><p>{ordered.length} позиций · {new Set(ordered.map(r=>r.supplier)).size} поставщика</p><hr/><ol><li><Check size={15}/>Потребность рассчитана</li><li><FileText size={15}/>Проверьте количество и обоснование</li><li><Truck size={15}/>Утвердите перед экспортом</li></ol>{invalid&&<p className="ek-summary-error">Проверьте наличие истории, целые неотрицательные количества и причину каждой корректировки.</p>}<button className="ek-primary" disabled={!canApprove||approved} onClick={()=>setConfirm(true)}>{approved?'Утверждено':'Проверить и утвердить'}</button><button className="ek-export" disabled={!approved||dirty} onClick={()=>download(ordered)}><ArrowDownToLine size={16}/>Скачать все заказы CSV</button><small>Утверждение действует на все {ordered.length} позиций расчёта, включая скрытые фильтрами. Ничего не отправляется автоматически.</small></aside>
        </div>
      </>}
      {view==='sources'&&<><ScenarioSources options={snapshot} rows={rows}/><DataSources/></>}
      {view==='method'&&<section className="ek-card ek-info"><h2>Почему предложено именно столько</h2><ol className="ek-method"><li><b>Очищаем продажи</b><p>Из сырых продаж убираем заранее размеченные разовые крупные заказы. В этом сценарии метки заданы вручную; алгоритм обнаружения аномалий не запускается.</p></li><li><b>Восстанавливаем доступный спрос</b><p>При включённой компенсации дни без наличия исключаются из наблюдений. Метод прогноза определяется реализацией сервера; frontend использует возвращённые значения и пояснения. Оценка потерянного спроса = дневной спрос × дни отсутствия.</p></li><li><b>Учитываем сезонность и рост</b><p>Дневной спрос × сезонный коэффициент × коэффициент устойчивого роста. В рабочей модели коэффициенты должны вычисляться из длительной истории.</p></li><li><b>Считаем заказ</b><p>Прогноз в день × выбранное число дней (от даты расчёта до конца прогноза включительно) − остаток − товары в пути. Срок поставки определяет дату прихода и риск дефицита до неё; он уже входит в горизонт и не прибавляется повторно. Неотрицательный результат округляем вверх до кратности поставщика.</p></li><li><b>Проверяем и утверждаем</b><p>Ручная корректировка требует причины. Изменение входов или количества отменяет утверждение. CSV содержит SKU, склад, поставщика, количество, единицу, срочность и обоснование; совместимость с конкретным импортом 1С требует проверки.</p></li></ol></section>}
      <footer className="ek-footer">Электрокомплект · HackAlem AI<span>Сценарий хранится до перезагрузки страницы</span></footer>
    </main>
    <dialog ref={dialog} className="ek-dialog" onCancel={close} onClose={close}><header><h2>{confirm?'Утвердить план закупки?':selected?.name}</h2><button aria-label="Закрыть" onClick={close}><X/></button></header>{confirm?<><p>Склад: <b>{snapshot.warehouse}</b></p><p>{ordered.length} позиций · {new Set(ordered.map(r=>r.supplier)).size} поставщика · <b>{money(total)}</b></p><p>Вы подтверждаете проверку всех количеств. Будет доступен CSV; поставщикам и в 1С ничего не отправляется.</p><div className="ek-dialog-actions"><button className="ek-secondary" onClick={close}>Вернуться к проверке</button><button className="ek-primary" disabled={!canApprove} onClick={()=>{setApproved(true);setView('orders');setNotice('Демо-план утверждён. Доступна выгрузка CSV.');close();}}>Утвердить {ordered.length} позиций</button></div></>:selected&&<>
      <p>{selected.sku} · {selected.supplier} · {snapshot.warehouse}</p>
      <ProductEvidence key={selected.sku} row={selected} options={snapshot}/>
      <dl className="ek-evidence">{[['Продажи за выбранные '+selected.historyDays+' дней',`${selected.rawSales} ${selected.unit}`],['Исключённые разовые продажи',`${selected.excluded} ${selected.unit} · анонимная группа C-0042`],['Дней наличия / отсутствия',selected.availableDays+' / '+selected.stockoutDays],['Оценка потерянного спроса',`${selected.lost} ${selected.unit}`],['Средний прогноз API / день',fmt(selected.daily)],['Сезонность / устойчивый рост',`×${snapshot.seasonality?selected.season:1} / ×${snapshot.growth?selected.growth:1}`],['Прогноз / день',`${fmt(selected.daily)} ${selected.unit}`],['Период прогноза',dateLabel(snapshot.planningDate)+' — '+dateLabel(snapshot.forecastEnd)],['Ожидаемый приход',dateLabel(selected.arrivalDate)],['Целевой запас',`${selected.target} ${selected.unit}`]].map(([key,value])=><div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
      <section className="ek-quantity-explanation" aria-label="Почему такое количество"><h3>Почему {selected.quantity} {selected.unit}?</h3><ol>
        <li><span>Потребность до {dateLabel(selected.forecastEnd)}</span><b>{fmt(selected.daily)} × {selected.horizon} дней ≈ {fmt(selected.target)} {selected.unit}</b><small>Дневной прогноз показан с округлением; расчёт использует полную точность.</small></li>
        <li><span>Вычитаем доступное обеспечение</span><b>{selected.target} − {selected.stock} на складе − {selected.incoming} в пути</b></li>
        <li><span>Чистая потребность</span><b>{selected.net} {selected.unit}</b></li>
        <li><span>Кратность поставщика: {selected.multiple} {selected.unit}</span><b>{selected.quantity/selected.multiple} партий = {selected.quantity} {selected.unit}</b><small>{selected.roundingExtra?`Округление вверх добавляет ${selected.roundingExtra} ${selected.unit}: меньшая партия не покроет потребность.`:'Дополнительное округление не требуется.'}</small></li>
      </ol></section>
      <div className="ek-formula">{selected.reason}<strong>Рекомендуем {selected.quantity} {selected.unit}</strong>{selected.api.missing_inputs?.length>0&&<p>Не хватает: {selected.api.missing_inputs.join(', ')}</p>}{selected.order!==selected.quantity&&<p>Ваш заказ: {selected.order} {selected.unit}. Причина: {selected.note||'ещё не указана'}</p>}</div>
      {selected.shortfallBeforeArrival>0&&<p className="ek-warning">Остатка хватит примерно на {fmt(selected.cover)} дней, поставка ожидается {dateLabel(selected.arrivalDate)}. До неё возможен дефицит до {selected.shortfallBeforeArrival} {selected.unit} без ранних поступлений. Уточните дату товаров в пути, ускорьте поставку или согласуйте перемещение: увеличение обычного заказа не устраняет этот разрыв.</p>}
      {selected.arrivalDate>selected.forecastEnd&&<p className="ek-warning">Поставка позже выбранного конца прогноза. Этот заказ не закроет дефицит внутри периода; требуется более ранняя поставка или перемещение.</p>}
      <h3>Проверить влияние исходных данных</h3><p>Изменения применятся после пересчёта. В пути — общий объём ожидаемых поставок. График разбивает его на два поступления; в расчёт попадут только даты внутри горизонта.</p><div className="ek-edit-inputs">{[['stock','Текущий остаток'],['incoming','Всего ожидается']].map(([key,label])=><label key={key}>{label}, {selected.unit}<input type="number" min="0" step="1" aria-label={label} value={inputEdits[selected.sku]?.[key]??(key==='incoming'?selected.incomingTotal:selected[key])} onChange={e=>{setInputEdits(v=>({...v,[selected.sku]:{...v[selected.sku],[key]:Math.max(0,Math.round(Number(e.target.value)))}}));setApproved(false);}}/></label>)}</div><button className="ek-primary" disabled={!!validation} onClick={()=>{recalculate();close();}}>Применить и пересчитать</button>
    </>}</dialog>
  </div>;
}
