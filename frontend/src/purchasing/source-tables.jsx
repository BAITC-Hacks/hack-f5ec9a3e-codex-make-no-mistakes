import {useEffect,useRef,useState} from 'react';
import {ArrowDownToLine,ArrowUpDown,ChevronLeft,ChevronRight,Database,RefreshCw,Search,X} from 'lucide-react';
import {api} from './api.js';

export const sourceTables=[
  ['monthly-sales','Продажи по месяцам','Продажи','sku,month,quantity,unit,supplier_name'],
  ['movements','Документы продаж','Продажи','sku,occurred_at,quantity,unit,warehouse_name,document_number'],
  ['seasonality','Сезонность','Продажи','supplier_name,year,month,metric,value,basis'],
  ['report-metrics','Показатели отчётов','Продажи','sku,label,metric,value,unit'],
  ['monthly-stock','Остатки по месяцам','Остатки','sku,month,quantity,unit,warehouse_name,metric'],
  ['current-stock','Текущие остатки','Остатки','sku,as_of,metric,quantity,unit,warehouse_name'],
  ['shipment-lines','Товары в пути','Поставки','sku,quantity,unit,supplier_name'],
  ['shipments','Документы поставок','Поставки','supplier_name,document_number,expected_on,warehouse_name,date_basis'],
  ['moq','Кратность и MOQ','Поставки','sku,kind,value,unit,supplier_name'],
  ['catalog','Все товары','Справочники','sku,supplier_name'],
  ['products','Названия и атрибуты','Справочники','sku,name,supplier_article,unit,category_code'],
  ['suppliers','Поставщики','Справочники','code,name'],
  ['warehouses','Склады','Справочники','name'],
  ['workbooks','Исходные файлы','Источники и качество','original_path,byte_size,captured_at'],
  ['sheets','Листы файлов','Источники и качество','name,reported_rows,reported_columns,original_path'],
  ['findings','Замечания к данным','Источники и качество','code,description,status,original_path'],
];
const labels={id:'Идентификатор записи',product_id:'Идентификатор товара',supplier_id:'Идентификатор поставщика',workbook_id:'Идентификатор файла',source_row_id:'Исходная строка',source_sheet_id:'Исходный лист',sheet_id:'Идентификатор листа',warehouse_id:'Идентификатор склада',shipment_id:'Идентификатор поставки',sku:'Код товара',name:'Название',supplier_code:'Код поставщика',supplier_name:'Поставщик',month:'Месяц',year:'Год',quantity:'Количество',unit:'Ед.',warehouse_name:'Склад',occurred_at:'Дата продажи',document_number:'Документ',document_text:'Тип документа',metric:'Показатель',kind:'Условие',value:'Значение',expected_on:'Дата прихода',ordered_on:'Дата заказа',header:'Заголовок источника',date_basis:'Основание даты',code:'Код',description:'Описание',status:'Статус',sheet_name:'Лист',row_number:'Строка',source_column:'Колонка',normalizer_version:'Версия импорта',original_path:'Исходный файл',supplier_article:'Артикул',evidence:'Подробности проверки',label:'Показатель в отчёте',basis:'Основание',as_of:'Дата остатка',category_code:'Категория',category_year:'Год категории',is_complete_period:'Полный период',formula:'Исходная формула',sha256:'Контрольная сумма',byte_size:'Размер',captured_at:'Загружен',capture_version:'Формат сохранения',archive_name:'Архив',position:'Номер листа',reported_rows:'Строк',reported_columns:'Колонок',finding_key:'Ключ замечания',resolution:'Решение',period_start:'Начало периода',period_end:'Конец периода'};
const values={open:'Требует проверки',resolved:'Решено',accepted_limitation:'Учтено',unknown:'Неизвестно',explicit:'Указано в источнике',filename:'Из имени файла',assumed_year:'Год задан вручную',reported:'Из отчёта',derived:'Рассчитано',forecast:'Прогноз',on_hand:'В наличии',reserved:'В резерве',free:'Свободный остаток',stock_unspecified:'Остаток без уточнения',opening:'На начало месяца',minimum_order:'Минимальный заказ',order_multiple:'Кратность'};
const unscoped=new Set(['catalog','suppliers','warehouses','workbooks']);
const noSupplier=new Set(['suppliers','warehouses','workbooks','sheets','findings']);
const filename=value=>String(value||'').split(/[\\/]/).pop();
export function displaySourceValue(key,value){
  if(value===null||value===undefined||value==='')return '—';
  if(typeof value==='boolean')return value?'Да':'Нет';
  if(typeof value==='object')return JSON.stringify(value,null,2);
  if(key==='original_path')return filename(value);
  if(key==='byte_size')return `${(Number(value)/1048576).toLocaleString('ru-RU',{maximumFractionDigits:2})} МБ`;
  if(['quantity','value','reported_rows','reported_columns'].includes(key)&&/^-?\d+(\.\d+)?$/.test(String(value))){
    const [whole,fraction]=String(value).split('.');
    const tail=fraction?.replace(/0+$/,'');
    return whole.replace(/\B(?=(\d{3})+(?!\d))/g,'\u00a0')+(tail?','+tail:'');
  }
  if(['month','as_of','expected_on','ordered_on','occurred_at','captured_at'].includes(key)&&/^\d{4}-\d{2}-\d{2}/.test(String(value))){
    const date=String(value).slice(0,10).split('-').reverse().join('.');
    return date+(String(value).includes('T')?' · '+String(value).slice(11,16):'');
  }
  return ['status','metric','kind','basis','date_basis'].includes(key)?values[value]||String(value):String(value);
}

export default function SourceTables({books,workbook,onWorkbookChange,revision,onRefresh,onSelectProduct}){
  const [table,setTable]=useState('monthly-sales'),[data,setData]=useState(null),[loading,setLoading]=useState(true),[error,setError]=useState('');
  const [query,setQuery]=useState(''),[search,setSearch]=useState(''),[supplier,setSupplier]=useState(''),[suppliers,setSuppliers]=useState([]);
  const [page,setPage]=useState(1),[size,setSize]=useState(25),[sort,setSort]=useState(''),[direction,setDirection]=useState('asc');
  const [detail,setDetail]=useState(null),[raw,setRaw]=useState(null),[rawError,setRawError]=useState(''),[rawLoading,setRawLoading]=useState(false);
  const [counts,setCounts]=useState({});
  const dialog=useRef(null);
  const config=sourceTables.find(item=>item[0]===table),groups=[...new Set(sourceTables.map(item=>item[2]))];
  const fileScoped=!unscoped.has(table),supplierScoped=!noSupplier.has(table);
  useEffect(()=>{setPage(1);setDetail(null);},[workbook]);
  useEffect(()=>{if(detail)dialog.current?.showModal();else dialog.current?.close();setRaw(null);setRawError('');},[detail]);
  useEffect(()=>{
    let active=true;
    api('/tables/suppliers?page_size=200').then(result=>{if(active)setSuppliers(result.items);}).catch(()=>{});
    for(const key of ['catalog','movements','monthly-stock','shipment-lines']){
      api(`/tables/${key}?page_size=1`).then(result=>{if(active)setCounts(previous=>({...previous,[key]:result.total}));}).catch(()=>{});
    }
    return ()=>{active=false;};
  },[revision]);
  const params=new URLSearchParams({page:String(page),page_size:String(size)});
  if(fileScoped&&workbook)params.set('workbook_id',workbook);
  if(supplierScoped&&supplier)params.set('supplier_id',supplier);
  if(search)params.set('q',search);
  if(sort){params.set('sort',sort);params.set('direction',direction);}
  const queryString=params.toString();
  useEffect(()=>{
    let active=true;setLoading(true);setError('');setData(null);
    api(`/tables/${table}?${queryString}`).then(result=>{if(active)setData(result);})
      .catch(err=>{if(active)setError(err.message);}).finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[table,queryString,revision]);
  function choose(key){setTable(key);setPage(1);setSort('');setDetail(null);}
  function sortBy(key){setSort(key);setDirection(sort===key&&direction==='asc'?'desc':'asc');setPage(1);}
  const columns=config[3].split(',');
  const exportParams=new URLSearchParams(params);exportParams.delete('page');exportParams.delete('page_size');exportParams.delete('sort');exportParams.delete('direction');
  return <section className="ek-data-browser" aria-label="Все доступные данные">
    <div className="ek-data-heading"><div><span className="ek-data-eyebrow">ЕДИНЫЙ КАТАЛОГ ДАННЫХ</span><h2>Все данные под рукой</h2><p>Продажи, запасы и поставки из загруженных файлов. Выберите таблицу, чтобы проверить записи.</p></div><span className="ek-data-table-count"><Database size={15}/>{sourceTables.length} таблиц</span></div>
    <div className="ek-data-overview">{[['catalog','Товаров','Номенклатура поставщиков'],['movements','Движений продаж','Документы и количества'],['monthly-stock','Записей остатков','История запасов по месяцам'],['shipment-lines','Строк поставок','Товары в пути']].map(([key,label,hint])=><button key={key} onClick={()=>choose(key)}><span>{label}</span><strong>{counts[key]===undefined?'—':counts[key].toLocaleString('ru-RU')}</strong><small>{hint}</small></button>)}</div>
    <div className="ek-card ek-data-panel">
      <nav className="ek-data-groups" aria-label="Группы данных">{groups.map(group=><button key={group} aria-pressed={config[2]===group} onClick={()=>choose(sourceTables.find(item=>item[2]===group)[0])}>{group}</button>)}</nav>
      <div className="ek-data-views" aria-label="Таблицы группы">{sourceTables.filter(item=>item[2]===config[2]).map(([key,label])=><button key={key} aria-pressed={table===key} onClick={()=>choose(key)}>{label}</button>)}</div>
      <div className="ek-data-title"><div><h3>{config[1]}</h3><span>{loading?'Загружаем записи…':data?`${data.total.toLocaleString('ru-RU')} записей по текущим фильтрам`:'Не удалось загрузить записи'}</span></div><div className="ek-data-actions"><button className="ek-secondary" aria-label="Обновить таблицы" onClick={onRefresh}><RefreshCw size={15}/></button>{fileScoped&&<a className="ek-secondary" href={`/api/v1/sources/export/${table}.csv?${exportParams}`} download><ArrowDownToLine size={15}/>Скачать таблицу CSV</a>}</div></div>
      <div className="ek-data-filters"><form onSubmit={event=>{event.preventDefault();setSearch(query.trim());setPage(1);}}><label htmlFor="source-search">Поиск в таблице</label><div className="ek-data-search"><Search size={16}/><input id="source-search" placeholder="Код, название или документ" value={query} onChange={event=>setQuery(event.target.value)}/><button type="submit">Найти</button></div></form><label>Поставщик таблицы<select disabled={!supplierScoped} value={supplierScoped?supplier:''} onChange={event=>{setSupplier(event.target.value);setPage(1);}}><option value="">Все поставщики</option>{suppliers.map(item=><option key={item.id} value={item.id}>{item.name||item.code}</option>)}</select></label><label>Исходный файл<select disabled={!fileScoped} value={fileScoped?workbook:''} onChange={event=>{onWorkbookChange(event.target.value);setPage(1);}}><option value="">Все файлы</option>{books.map(book=><option key={book.id} value={book.id}>{filename(book.original_path)}</option>)}</select></label></div>
      {error&&<div className="ek-data-empty" role="alert"><strong>Не удалось получить данные</strong><p>{error}</p><button className="ek-secondary" onClick={onRefresh}>Повторить загрузку</button></div>}
      {loading?<div className="ek-data-empty" role="status">Загружаем {config[1].toLowerCase()}…</div>:data&&<>
        {data.items.length?<div className="ek-data-scroll"><table className="ek-data-table"><caption className="ek-sr-only">{config[1]}</caption><thead><tr>{columns.map(key=><th key={key} scope="col" aria-sort={sort===key?(direction==='asc'?'ascending':'descending'):'none'}><button onClick={()=>sortBy(key)}>{labels[key]||key}<ArrowUpDown size={12}/></button></th>)}<th scope="col">Детали</th></tr></thead><tbody>{data.items.map(row=><tr key={row.id}>{columns.map(key=><td key={key} className={['quantity','value'].includes(key)?'ek-data-number':''} title={key==='original_path'?row[key]:undefined}>{key==='sku'?<strong className="ek-data-sku">{displaySourceValue(key,row[key])}</strong>:key==='status'?<span className={`ek-data-status ${row[key]==='open'?'is-warning':''}`}>{displaySourceValue(key,row[key])}</span>:displaySourceValue(key,row[key])}</td>)}<td><button className="ek-data-detail-button" aria-label={`Подробнее о записи ${row.sku||row.name||row.code||row.id}`} onClick={()=>setDetail(row)}>Подробнее ↗</button>{row.product_id&&<button className="ek-data-detail-button" onClick={()=>onSelectProduct(row)}>Выбрать SKU {row.sku}</button>}</td></tr>)}</tbody></table></div>:<div className="ek-data-empty"><Database size={28}/><strong>Записей не найдено</strong><p>Измените поиск или фильтры. Если данных ещё нет, загрузите исходный файл выше.</p>{(search||supplier||workbook)&&<button className="ek-secondary" onClick={()=>{setSearch('');setQuery('');setSupplier('');onWorkbookChange('');setPage(1);}}>Сбросить фильтры</button>}</div>}
        <footer className="ek-data-pagination"><span>{data.total?`${((page-1)*size+1).toLocaleString('ru-RU')}–${Math.min(page*size,data.total).toLocaleString('ru-RU')} из ${data.total.toLocaleString('ru-RU')}`:'0 записей'}</span><label>Строк на странице<select value={size} onChange={event=>{setSize(Number(event.target.value));setPage(1);}}>{[25,50,100].map(value=><option key={value}>{value}</option>)}</select></label><div><button aria-label="Предыдущая страница данных" disabled={page===1} onClick={()=>setPage(value=>value-1)}><ChevronLeft size={17}/></button><span>{page} / {Math.max(1,Math.ceil(data.total/size))}</span><button aria-label="Следующая страница данных" disabled={page*size>=data.total} onClick={()=>setPage(value=>value+1)}><ChevronRight size={17}/></button></div></footer>
      </>}
      <p className="ek-data-note">«—» означает, что значение не указано. Нули сохраняются отдельно. Происхождение и все поля записи — в деталях.</p>
    </div>
    <dialog ref={dialog} className="ek-dialog ek-data-dialog" onCancel={()=>setDetail(null)} onClose={()=>setDetail(null)}><header><div><small>{config[1]}</small><h2>{detail?.sku||detail?.name||'Детали записи'}</h2></div><button aria-label="Закрыть детали записи" onClick={()=>setDetail(null)}><X size={20}/></button></header>{detail&&<><dl className="ek-data-record">{Object.entries(detail).map(([key,value])=><div key={key}><dt>{labels[key]||key}</dt><dd>{key==='original_path'?String(value):displaySourceValue(key,value)}</dd></div>)}</dl>{detail.source_row_id&&<button className="ek-secondary" disabled={rawLoading} onClick={async()=>{setRawLoading(true);setRawError('');try{setRaw(await api(`/source-rows/${detail.source_row_id}`));}catch(err){setRawError(err.message);}finally{setRawLoading(false);}}}>{rawLoading?'Загрузка…':'Показать исходные ячейки'}</button>}{rawError&&<p role="alert">{rawError}</p>}{raw&&<pre className="ek-data-raw">{JSON.stringify(raw.cells,null,2)}</pre>}</>}</dialog>
  </section>;
}
