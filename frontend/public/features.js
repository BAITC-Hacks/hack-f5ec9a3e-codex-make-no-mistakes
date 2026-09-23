'use strict';

const weekdays=['Пн','Вт','Ср','Чт','Пт','Сб','Вс'];
const deliveryLabels={exported:'Файл подготовлен',queued:'В очереди',sending:'Отправляется',sent:'Принято почтовым сервером',failed:'Не отправлено',unknown:'Требуется проверка почты'};
const monthLabel=m=>new Date(m+'-01T12:00:00').toLocaleDateString('ru-RU',{month:'short',year:'2-digit'});
let selectedTrendGroup=null;
let trendRequest=0;

document.addEventListener('click', e=>{
 if(e.target.closest('[data-show-risk]')){
  state.status='urgent';state.risk='all';state.supplier='all';state.category='all';state.search='';state.page=1;
  renderRecommendations();
 }
});

function renderSupplierProfiles(){
 const profiles=state.data.supplier_profiles||{},mail=state.data.delivery||{};
 $('#content').innerHTML=viewHeader('Условия поставщиков','Условия заказа, календарь приёма и адреса для подтверждённой рассылки')+`
 <div class="notice">${icon(mail.configured?'check':'file')}<span>${mail.configured?`Почта настроена. Отправитель: ${esc(mail.sender)}. Рассылка включается отдельно при утверждении каждого заказа.`:'Автоматическая выгрузка доступна. Для рассылки укажите адреса поставщиков и настройте SMTP по инструкции в README.'}</span></div>
 <form id="supplier-form"><div class="supplier-forms">${Object.entries(profiles).map(([name,p])=>`
 <section class="panel info-card supplier-profile" data-profile="${esc(name)}">
  <div class="panel-title-line"><span class="supplier-logo ${name==='IEK'?'':'se'}">${name==='IEK'?'IEK':'SE'}</span><h2>${esc(name)}</h2></div>
  <div class="form-grid">
   <label class="field full">Email для заказов<input type="email" name="email" value="${esc(p.email)}" maxlength="254" placeholder="Адрес, подтверждённый поставщиком"><small>Один получатель. Адрес показывается перед подтверждением рассылки.</small></label>
   ${[['lead_days','Срок поставки, дней',365,state.data.settings.lead_days],['review_days','Период пересмотра, дней',180,state.data.settings.review_days],['default_moq','MOQ при отсутствии в файле',10000000,'Не задан'],['default_pack_size','Кратность при отсутствии в файле',10000000,'Не задан']].map(([key,label,max,fallback])=>`<label class="field">${label}<input name="${key}" type="number" min="1" max="${max}" step="1" value="${p[key]??''}" placeholder="${fallback}"></label>`).join('')}
   <label class="field full">Минимум разных артикулов в заказе<input name="min_order_lines" type="number" min="1" max="100000" step="1" required value="${p.min_order_lines}"><small>Проверяется отдельно для каждого поставщика. Штуки, метры и упаковки не складываются.</small></label>
   <fieldset class="field full weekday-field"><legend>Дни приёма новых заказов</legend><div class="weekdays">${weekdays.map((day,i)=>`<label><input type="checkbox" data-weekday="${i}" ${p.order_weekdays.includes(i)?'checked':''}>${day}</label>`).join('')}</div><small>Ничего не выбрано — любой день. Ожидание ближайшего дня учитывается в горизонте поставки.</small></fieldset>
   <label class="field full">Другие договорённости<textarea name="notes" maxlength="2000" rows="3" placeholder="Условия оплаты, доставки и примечания">${esc(p.notes)}</textarea><small>Примечание для менеджера; само по себе не меняет расчёт.</small></label>
  </div>
  <p class="tiny-note">Значения MOQ и кратности из исходного справочника имеют приоритет. Условия на этой странице заполняют только пропуски.</p>
 </section>`).join('')}</div>
 <div class="supplier-save"><span class="muted">Сохранение пересчитает рекомендации и сбросит текущий выбор.</span><button class="btn primary" type="submit">Сохранить условия и пересчитать</button></div><div id="supplier-error" role="alert"></div></form>`;
 $('#supplier-form').onsubmit=async e=>{
  e.preventDefault();const button=$('button[type=submit]',e.target);button.disabled=true;
  const updated={};
  for(const card of $$('.supplier-profile')){
   const p={email:$('[name=email]',card).value.trim(),notes:$('[name=notes]',card).value,min_order_lines:Number($('[name=min_order_lines]',card).value),order_weekdays:$$('[data-weekday]:checked',card).map(x=>Number(x.dataset.weekday))};
   for(const key of ['lead_days','review_days','default_moq','default_pack_size']){const value=$(`[name=${key}]`,card).value;p[key]=value===''?null:Number(value);}
   updated[card.dataset.profile]=p;
  }
  try{const run=await api('/api/suppliers',{profiles:updated});state.data={...state.data,...run};state.selected.clear();state.overrides.clear();state.page=1;render();toast('Условия сохранены. Рекомендации пересчитаны.');}
  catch(error){$('#supplier-error').className='error-message';$('#supplier-error').textContent=error.message;button.disabled=false;}
 };
}

function categoryChart(series){
 const w=900,h=300,p={l:65,r:22,t:22,b:40};
 const values=series.flatMap(r=>[r.raw,r.clean]).filter(v=>v!=null);
 const lo=Math.min(0,...values),hi=Math.max(1,...values),range=hi-lo;
 const x=i=>p.l+i*(w-p.l-p.r)/Math.max(1,series.length-1),y=v=>h-p.b-(v-lo)/range*(h-p.t-p.b);
 const line=key=>{let connected=false;return series.map((r,i)=>{if(r[key]==null){connected=false;return '';}const seg=`${connected?'L':'M'}${x(i).toFixed(1)},${y(r[key]).toFixed(1)}`;connected=true;return seg;}).join(' ');};
 return `<svg class="category-chart" viewBox="0 0 ${w} ${h}" role="img" aria-label="Фактические продажи и очищенный спрос категории за полные месяцы">
 ${[0,.25,.5,.75,1].map(t=>{const v=lo+range*t;return `<line x1="${p.l}" y1="${y(v)}" x2="${w-p.r}" y2="${y(v)}" stroke="#e5ece8"/><text x="${p.l-10}" y="${y(v)+4}" text-anchor="end" fill="#7b919a" font-size="12">${fmt(v)}</text>`;}).join('')}
 <path d="${line('raw')}" fill="none" stroke="#b1c2cc" stroke-width="2.4"/><path d="${line('clean')}" fill="none" stroke="#377765" stroke-width="3"/>
 ${series.map((r,i)=>`${r.clean!=null?`<circle cx="${x(i)}" cy="${y(r.clean)}" r="3" fill="#377765"><title>${esc(monthLabel(r.month))}: ${fmt(r.clean)}; факт ${fmt(r.raw)}; ${r.sku_count} SKU</title></circle>`:''}${i%3===0||i===series.length-1?`<text x="${x(i)}" y="${h-10}" text-anchor="middle" fill="#7b919a" font-size="12">${r.month.slice(5)}.${r.month.slice(2,4)}</text>`:''}`).join('')}</svg>`;
}

function renderTrends(){
 const options=state.data.category_options||[];
 if(!options.some(g=>g.id===selectedTrendGroup))selectedTrendGroup=(options.filter(g=>g.category!=='Без категории'&&g.unit==='шт').sort((a,b)=>b.sku_count-a.sku_count)[0]||options[0])?.id;
 $('#content').innerHTML=viewHeader('Тренды по категориям','Сравнение фактических продаж и регулярного спроса по полным месяцам')+`
 <section class="panel trend-panel"><div class="trend-picker"><label class="field">Поставщик · категория · единица измерения<select id="trend-group">${options.map(g=>`<option value="${esc(g.id)}" ${g.id===selectedTrendGroup?'selected':''}>${esc(g.supplier)} · ${g.category==='Без категории'?'Без категории':`категория ${esc(g.category)}`} · ${esc(g.unit)} · ${fmt(g.sku_count)} SKU</option>`).join('')}</select></label><span class="tiny-note">Каждый график включает одну единицу измерения.</span></div><div id="trend-result"><div class="loading-state compact"><span class="spinner"></span>Рассчитываем динамику категории…</div></div></section>`;
 $('#trend-group').onchange=e=>{selectedTrendGroup=e.target.value;loadTrend();};
 loadTrend();
}

async function loadTrend(){
 const sequence=++trendRequest,group=(state.data.category_options||[]).find(g=>g.id===selectedTrendGroup);
 if(!group){$('#trend-result').innerHTML='<div class="empty">Категории пока недоступны.</div>';return;}
 if(group.unit.includes('не указана')){$('#trend-result').innerHTML=`<div class="empty">У ${fmt(group.sku_count)} товаров не указана единица измерения.<br>Суммарный график не строится: сначала уточните единицы в источнике.</div>`;return;}
 $('#trend-result').innerHTML='<div class="loading-state compact"><span class="spinner"></span>Рассчитываем динамику категории…</div>';
 try{
  const data=await api('/api/analytics/categories?'+new URLSearchParams({supplier:group.supplier,category:group.category,unit:group.unit}));
  if(sequence!==trendRequest||state.view!=='trends')return;
  const g=data.groups[0];if(!g){$('#trend-result').innerHTML='<div class="empty">Для выбранной категории нет истории.</div>';return;}
  $('#trend-result').innerHTML=`<div class="trend-summary"><div><span>Товаров в категории</span><strong>${fmt(g.sku_count)}</strong></div><div><span>Сопоставимых SKU за 6 месяцев</span><strong>${fmt(g.comparable_sku_count)}</strong></div><div><span>Изменение спроса: 3 мес. к 3 мес.</span><strong>${g.trend_percent==null?'Недостаточно данных':`${g.trend_percent>0?'+':''}${fmt(g.trend_percent)}%`}</strong></div></div>
  <div class="trend-chart-area"><div class="legend"><span><i></i>Фактические продажи, ${esc(g.unit)}</span><span><i class="clean"></i>Регулярный спрос, ${esc(g.unit)}</span></div>${categoryChart(g.series)}</div>
  <div class="trend-notes"><p>Изменение рассчитано по среднему дневному спросу одних и тех же товаров за последние три и предыдущие три полных месяца. Разрывы на графике означают отсутствие наблюдений.</p><p>${monthLabel(data.excluded_partial_month)} — неполный месяц: ${fmt(g.partial_month.raw)} ${esc(g.unit)}. Показан отдельно и не участвует в сравнении.</p></div>
  <details class="trend-details"><summary>Помесячные значения и полнота данных</summary><div class="table-scroll"><table><thead><tr><th>Месяц</th><th class="num">Продажи, ${esc(g.unit)}</th><th class="num">Регулярный спрос</th><th class="num">SKU с данными</th><th class="num">Полнота</th></tr></thead><tbody>${g.series.map(r=>`<tr><td>${monthLabel(r.month)}</td><td class="num">${fmt(r.raw)}</td><td class="num">${fmt(r.clean)}</td><td class="num">${fmt(r.sku_count)}</td><td class="num">${fmt(r.coverage_percent)}%</td></tr>`).join('')}</tbody></table></div></details>`;
 }catch(e){if(sequence===trendRequest&&state.view==='trends')$('#trend-result').innerHTML=`<div class="empty">${esc(e.message)}<p><button class="btn" id="retry-trends">Повторить</button></p></div>`;$('#retry-trends')?.addEventListener('click',loadTrend);}
}

function deliveryList(order){
 return (order.deliveries||[]).map(job=>`<div class="delivery-row"><div><strong>${esc(job.supplier)}</strong><small>${job.recipient?esc(job.recipient):'Рассылка не запрашивалась'}</small></div><span class="badge ${job.status==='sent'?'approved':job.status==='failed'||job.status==='unknown'?'urgent':'draft'}">${deliveryLabels[job.status]||esc(job.status)}</span>${job.status==='failed'?`<button class="btn small" data-retry-order="${esc(order.id)}" data-job="${esc(job.id)}">Повторить</button>`:''}${job.error?`<p class="delivery-error">${esc(job.error)}</p>`:''}</div>`).join('');
}

function renderOrders(){
 $('#content').innerHTML=viewHeader('Заказы поставщикам','Утверждение → автоматическая выгрузка → подтверждённая рассылка',`<button class="btn" id="refresh-orders">${icon('refresh')}Обновить статусы</button><button class="btn" data-goto="recommendations">${icon('layers')}К рекомендациям</button>`)+(state.orders.length?state.orders.map(o=>`
 <section class="panel order-card"><div class="order-top"><div><h3>Заказ № ${esc(o.id)} <span class="badge ${o.status}">${o.status==='approved'?'Утверждён':'Черновик'}</span></h3><span class="order-meta">${dateText(o.created_at)} · ${fmt(o.items.length)} позиций · Срез ${dateText(o.as_of)}${o.reviewer?` · Проверил: ${esc(o.reviewer)}`:''}</span></div>
 <div class="actions"><a class="btn small" href="/api/orders/${encodeURIComponent(o.id)}/export" download>${icon('download')}Внутренний CSV</a>${o.status==='draft'?`<button class="btn primary small" data-approve="${esc(o.id)}">${icon('check')}Проверить и утвердить</button>`:(o.deliveries?.length?`<a class="btn primary small" href="/api/orders/${encodeURIComponent(o.id)}/exports" download>${icon('download')}Файлы поставщикам</a>`:`<button class="btn primary small" data-prepare="${esc(o.id)}">Создать файлы поставщикам</button>`)}</div></div>
 <div class="order-suppliers">${[...new Set(o.items.map(r=>r.supplier))].map(s=>`<span class="supplier-chip">${esc(s)} · ${o.items.filter(r=>r.supplier===s).length} позиций</span>`).join('')}</div>
 ${o.deliveries?.length?`<div class="deliveries">${deliveryList(o)}</div><p class="tiny-note">Каждому поставщику — только его позиции и количества. Статус принятия почтовым сервером не подтверждает прочтение письма.</p>`:''}
 <details><summary>Состав заказа и ручные корректировки</summary><div class="table-scroll"><table><thead><tr><th>Поставщик</th><th>Товар</th><th>Артикул</th><th class="num">Рекомендовано</th><th class="num">В заказе</th><th>Ед.</th></tr></thead><tbody>${o.items.map(r=>`<tr><td>${esc(r.supplier)}</td><td>${esc(r.name)}</td><td>${esc(r.sku)}</td><td class="num">${fmt(r.recommended)}</td><td class="num">${fmt(r.quantity)}${r.manual_override?' *':''}</td><td>${esc(r.unit)}</td></tr>`).join('')}</tbody></table></div><p class="tiny-note">* Количество скорректировано менеджером. Обоснования и остатки есть только во внутреннем CSV.</p></details></section>`).join(''):`<div class="panel empty">${icon('file')}Сохранённых заказов пока нет.<br>Выберите позиции в рекомендациях и сформируйте черновик.</div>`);
 bindGoto();
 $('#refresh-orders').onclick=async()=>{try{await loadOrders();renderOrders();toast('Статусы обновлены');}catch(e){toast(e.message);}};
 $$('[data-approve]').forEach(b=>b.onclick=()=>openApprove(b.dataset.approve));
 $$('[data-prepare]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await api(`/api/orders/${b.dataset.prepare}/prepare-exports`,{});await loadOrders();renderOrders();toast('Отдельные файлы поставщикам подготовлены');}catch(e){toast(e.message);b.disabled=false;}});
 $$('[data-retry-order]').forEach(b=>b.onclick=()=>openRetry(b.dataset.retryOrder,b.dataset.job));
}

async function openApprove(id){
 try{
  const info=await api('/api/suppliers');
  state.data.supplier_profiles=info.profiles;state.data.supplier_profiles_revision=info.revision;state.data.delivery=info.delivery;
  const o=state.orders.find(o=>o.id===id),names=[...new Set(o.items.map(r=>r.supplier))];
  const canSend=info.delivery.configured&&names.every(s=>info.profiles[s]?.email);
  openModal(`<form id="approve-form"><div class="modal-head"><h2>Утверждение заказа № ${esc(id)}</h2><button type="button" class="icon-btn" data-close-modal aria-label="Закрыть">${icon('close')}</button></div>
  <p class="modal-note">${o.items.length} позиций. После утверждения отдельный CSV для каждого поставщика будет создан автоматически.</p>
  ${o.items.some(r=>r.stock_stale)?'<div class="detail-warning">В заказе есть устаревшие остатки. Сверьте их в 1С.</div>':''}
  <div class="detail-warning">Проверьте сроки, MOQ и кратность, включая значения, принятые при пропусках в исходных данных.</div>
  <div class="approval-recipients">${names.map(s=>`<div><strong>${esc(s)}</strong><span>${esc(info.profiles[s]?.email||'Email не указан')}</span></div>`).join('')}</div>
  <label class="field full">Ответственный сотрудник<input name="reviewer" required maxlength="120" placeholder="Имя или рабочий идентификатор" autocomplete="off"></label>
  <label class="switch-row"><input type="checkbox" name="ack" required><span>Я проверил остатки, сроки, MOQ и количество. Утверждаю этот заказ.</span></label>
  <label class="switch-row"><input type="checkbox" name="send_email" ${canSend?'':'disabled'}><span>После утверждения автоматически отправить файлы указанным поставщикам<small>${canSend?'Подтверждаю получателей и отправку. Письма будут содержать только позиции соответствующего поставщика.':!info.delivery.configured?'SMTP пока не настроен. Файлы будут доступны для скачивания.':'Укажите email всех поставщиков в разделе «Условия поставщиков».'}</small></span></label>
  <div class="modal-actions"><button type="button" class="btn" data-close-modal>Отмена</button><button type="submit" class="btn primary">Утвердить и подготовить файлы</button></div></form>`);
  $('#approve-form').elements.send_email.onchange=e=>{$('#approve-form button[type=submit]').textContent=e.target.checked?'Утвердить и отправить':'Утвердить и подготовить файлы';};
  $('#approve-form').onsubmit=async e=>{
   e.preventDefault();const f=e.target,button=$('button[type=submit]',f);button.disabled=true;
   try{const send=f.elements.send_email.checked;await api(`/api/orders/${encodeURIComponent(id)}/approve`,{reviewer:f.elements.reviewer.value,acknowledge:f.elements.ack.checked,send_email:send,supplier_profiles_revision:info.revision});$('#modal').close();await loadOrders();renderOrders();toast(send?'Заказ утверждён. Подтверждённая рассылка поставлена в очередь.':'Заказ утверждён. Файлы поставщикам подготовлены.');}
   catch(err){modalError(err.message);button.disabled=false;}
  };
 }catch(e){toast(e.message);}
}

function openRetry(orderId,jobId){
 const order=state.orders.find(o=>o.id===orderId),job=order.deliveries.find(j=>j.id===jobId);
 openModal(`<div class="modal-head"><h2>Повторная отправка</h2><button class="icon-btn" data-close-modal aria-label="Закрыть">${icon('close')}</button></div><p>Повторить отправку заказа № ${esc(orderId)} поставщику ${esc(job.supplier)} на <strong>${esc(job.recipient)}</strong>?</p><p class="modal-note">Предыдущая попытка завершилась подтверждённой ошибкой. Состав утверждённого заказа остаётся прежним.</p><div class="modal-actions"><button class="btn" data-close-modal>Отмена</button><button class="btn primary" id="confirm-retry">Подтвердить отправку</button></div>`);
 $('#confirm-retry').onclick=async e=>{e.target.disabled=true;try{await api(`/api/orders/${orderId}/deliveries/${jobId}/retry`,{confirm:true});$('#modal').close();await loadOrders();renderOrders();}catch(err){modalError(err.message);e.target.disabled=false;}};
}

boot();
