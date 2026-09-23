import {useEffect,useRef,useState} from 'react';
import './data-sources.css';

const tables=[['monthly-sales','Продажи по месяцам'],['movements','Движения продаж'],['monthly-stock','Остатки по месяцам'],['current-stock','Текущие остатки'],['shipment-lines','Товары в пути'],['shipments','Поставки'],['moq','Кратность и MOQ'],['products','Номенклатура'],['seasonality','Сезонность'],['findings','Замечания к данным']];
const labels={sku:'SKU',name:'Название',supplier_code:'Поставщик',month:'Месяц',quantity:'Количество',unit:'Единица',warehouse_name:'Склад',occurred_at:'Дата',document_number:'Документ',document_text:'Тип документа',metric:'Показатель',kind:'Тип',value:'Значение',expected_on:'Ожидается',header:'Заголовок',date_basis:'Основание даты',code:'Код',description:'Описание',status:'Статус',sheet_name:'Лист',row_number:'Строка',source_column:'Колонка',normalizer_version:'Версия',original_path:'Файл',supplier_article:'Артикул',evidence:'Подробности'};
const show=value=>value==null?'—':typeof value==='object'?JSON.stringify(value):String(value);
async function request(url,options){
  const response=await fetch(url,options);
  const data=await response.json().catch(()=>null);
  if(!response.ok)throw new Error(typeof data?.detail==='string'?data.detail:`Сервер вернул ошибку ${response.status}`);
  if(!data)throw new Error('Сервер вернул некорректный ответ');
  return data;
}

export default function DataSources({onImported}){
  const [files,setFiles]=useState([]),[supplier,setSupplier]=useState(''),[busy,setBusy]=useState(false);
  const [results,setResults]=useState([]),[progress,setProgress]=useState(''),[error,setError]=useState('');
  const [books,setBooks]=useState([]),[workbook,setWorkbook]=useState(''),[table,setTable]=useState('monthly-sales');
  const [page,setPage]=useState(1),[data,setData]=useState(null),[loading,setLoading]=useState(false),[revision,setRevision]=useState(0);
  const [product,setProduct]=useState(null),[planningDate,setPlanningDate]=useState(new Date().toISOString().slice(0,10)),[warehouse,setWarehouse]=useState('');
  const [prepared,setPrepared]=useState(null),[preparing,setPreparing]=useState(false),[prepareError,setPrepareError]=useState('');
  const fileInput=useRef(null);
  useEffect(()=>{setPrepared(null);setPrepareError('');},[workbook]);
  useEffect(()=>{
    const controller=new AbortController();
    request('/api/v1/tables/workbooks?page_size=200&sort=captured_at&direction=desc',{signal:controller.signal})
      .then(result=>setBooks(result.items)).catch(err=>{if(err.name!=='AbortError')setError(err.message);});
    return ()=>controller.abort();
  },[revision]);
  useEffect(()=>{
    const controller=new AbortController();setLoading(true);setData(null);setError('');
    const params=new URLSearchParams({page:String(page),page_size:'25'});
    if(workbook)params.set('workbook_id',workbook);
    request(`/api/v1/tables/${table}?${params}`,{signal:controller.signal}).then(setData)
      .catch(err=>{if(err.name!=='AbortError')setError(err.message);})
      .finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return ()=>controller.abort();
  },[table,workbook,page,revision]);
  async function upload(event){
    event.preventDefault();if(!files.length||busy)return;
    setBusy(true);setError('');setResults([]);
    const completed=[];
    try{
      for(let i=0;i<files.length;i++){
        const file=files[i];setProgress(`Файл ${i+1} из ${files.length}: ${file.name}. Разбор, проверка и сохранение…`);
        if(file.size>64*1024*1024){completed.push({path:file.name,status:'failed',error:'Файл превышает 64 МБ'});}
        else{
          const params=new URLSearchParams({filename:file.name});if(supplier)params.set('supplier',supplier);
          try{const result=await request(`/api/v1/sources/upload?${params}`,{method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file});completed.push(...result.results);}
          catch(err){completed.push({path:file.name,status:'failed',error:`${err.message}. При обрыве связи проверьте историю и повторите загрузку: дубликаты не создаются.`});}
        }
        setResults([...completed]);
      }
      const saved=completed.find(result=>result.workbook_id);
      if(saved){setWorkbook(saved.workbook_id);setPage(1);}
      setRevision(value=>value+1);setFiles([]);if(fileInput.current)fileInput.current.value='';
      if(saved)await onImported?.();
    }finally{setBusy(false);setProgress('');}
  }
  async function prepare(event){
    event.preventDefault();setPreparing(true);setPrepareError('');setPrepared(null);
    try{
      const result=await request('/api/v1/planning/source-input',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({product_ids:[product.product_id],planning_date:planningDate,warehouse,normalizer_version:product.normalizer_version||'v1',workbook_ids:workbook?[workbook]:[]})});
      setPrepared(result);
    }catch(err){setPrepareError(err.message);}finally{setPreparing(false);}
  }
  function downloadPrepared(){
    const url=URL.createObjectURL(new Blob([JSON.stringify(prepared,null,2)],{type:'application/json'}));
    const link=document.createElement('a');link.href=url;link.download=`source-input-${product.sku}.json`;link.click();URL.revokeObjectURL(url);
  }
  const columns=data?.items?.length?Object.keys(data.items[0]).filter(key=>labels[key]):[];
  return <div className="ek-sources">
    <section className="ek-card ek-info"><h2>Загрузить исходные данные</h2>
      <p>Загрузите Excel — данные будут проверены и сохранены. Продажи, остатки, поставки и справочники доступны для просмотра и выгрузки CSV с исходным файлом, листом и строкой.</p>
      <form className="ek-upload-form" onSubmit={upload}>
        <label>Поставщик<select value={supplier} disabled={busy} onChange={e=>setSupplier(e.target.value)}><option value="">Определить по имени файла</option><option value="iek">IEK</option><option value="systeme">Systeme Electric</option></select></label>
        <label>Файлы Excel, CSV или ZIP<input ref={fileInput} type="file" multiple accept=".xlsx,.csv,.zip" disabled={busy} onChange={e=>setFiles(Array.from(e.target.files||[]))}/></label>
        <button className="ek-primary" disabled={busy||!files.length}>{busy?'Импорт выполняется…':`Загрузить в базу${files.length?` (${files.length})`:''}`}</button>
      </form>
      <p className="ek-source-help">До 64 МБ на файл. ZIP: до 30 файлов. Поддерживаются формы IEK и Systeme из исходных архивов. Каждая книга сохраняется целиком или отклоняется; повторная загрузка пропускается. Большие книги могут обрабатываться несколько минут.</p>
      <details><summary>Формат CSV и правила импорта</summary><p><a href="/api/v1/sources/template.csv" download>Скачать шаблон CSV</a> — UTF-8, разделитель запятая или точка с запятой. Заголовок: <code>record_type,sku,name,date,quantity,unit,warehouse,document_number,document_text</code>.</p><p>Типы: <code>monthly_sales</code>, <code>monthly_stock</code>, <code>incoming</code>, <code>movements</code>. Дата YYYY-MM-DD; для месячных данных — первое число. SKU сохраняется текстом; число — с точкой. Для движений обязательны единица, склад и оба поля документа. Тип расхода передавайте как в источнике, например «Расходная накладная».</p><p>Пустые числа Excel не превращаются в нули. Ошибки формул и неопределённые даты отображаются в замечаниях. CSV-выгрузка таблиц содержит происхождение записей; для обратной загрузки используйте структуру шаблона.</p></details>
      {progress&&<p role="status">{progress}</p>}
      {results.length>0&&<ul className="ek-import-results" aria-label="Результаты импорта">{results.map((result,index)=><li key={index} className={result.status==='failed'?'failed':''}><strong>{result.path}</strong><span>{result.status==='imported'?'Сохранено в базе':result.status==='skipped'?'Уже загружено — пропущено':'Не импортировано'}</span>{result.error&&<p role="alert">{result.error}</p>}{result.counts&&<p>{Object.entries(result.counts).map(([key,count])=>`${key}: ${count.toLocaleString('ru-RU')}`).join(' · ')}</p>}{result.workbook_id&&<button className="ek-secondary" onClick={()=>{setWorkbook(result.workbook_id);setPage(1);}}>Показать записи файла</button>}{result.warnings?.length>0&&<details><summary>Замечания: {result.warnings.length}</summary><ul>{result.warnings.map((warning,i)=><li key={i}>{warning.description} · {warning.evidence.sheet} · {warning.evidence.count}</li>)}</ul></details>}</li>)}</ul>}
    </section>
    <section className="ek-card ek-info"><h2>Данные в базе</h2><p>Выберите файл и таблицу, чтобы проверить сохранённые записи. Для расчёта используйте выбранные источники и подтверждённые ограничения.</p>
      <div className="ek-source-filters"><label>Исходный файл<select value={workbook} onChange={e=>{setWorkbook(e.target.value);setPage(1);}}><option value="">Все файлы</option>{books.map(book=><option key={book.id} value={book.id}>{book.original_path}</option>)}</select></label><label>Таблица<select value={table} onChange={e=>{setTable(e.target.value);setPage(1);}}>{tables.map(([key,label])=><option key={key} value={key}>{label}</option>)}</select></label><button className="ek-secondary" onClick={()=>setRevision(v=>v+1)}>Обновить</button><a className="ek-secondary" href={`/api/v1/sources/export/${table}.csv${workbook?`?workbook_id=${workbook}`:''}`} download>Скачать таблицу CSV</a></div>
      {error&&<p role="alert" className="ek-source-error">{error}</p>}
      {loading?<p role="status">Загрузка записей…</p>:data&&<><p>Записей: {data.total.toLocaleString('ru-RU')}. Пустое значение — неизвестно, а не ноль.</p>{data.items.length?<div className="ek-table-scroll"><table><thead><tr>{columns.map(key=><th key={key}>{labels[key]}</th>)}{data.items.some(row=>row.product_id)&&<th>Подготовка расчёта</th>}</tr></thead><tbody>{data.items.map(row=><tr key={row.id}>{columns.map(key=><td key={key}>{show(row[key])}</td>)}{row.product_id&&<td><button className="ek-secondary" onClick={()=>{setProduct(row);setWarehouse(row.warehouse_name||'');setPrepared(null);setPrepareError('');}}>Выбрать SKU {row.sku}</button></td>}</tr>)}</tbody></table></div>:<p>В этой таблице пока нет записей выбранного файла. Выберите другую таблицу или загрузите данные.</p>}<div className="ek-source-pagination"><button className="ek-secondary" disabled={page===1} onClick={()=>setPage(v=>v-1)}>Назад</button><span>Страница {page} из {Math.max(1,Math.ceil(data.total/25))}</span><button className="ek-secondary" disabled={page*25>=data.total} onClick={()=>setPage(v=>v+1)}>Далее</button></div></>}
    </section>
    {product&&<section className="ek-card ek-info"><h2>Данные для расчёта: {product.sku}</h2><p>Используется {workbook?'выбранный файл':'набор загруженных файлов'}. Конфликтующие источники и неизвестные значения требуют проверки; они не заменяются предположениями.</p><form className="ek-upload-form" onSubmit={prepare}><label>Дата планирования<input type="date" required value={planningDate} onChange={e=>{setPlanningDate(e.target.value);setPrepared(null);}}/></label><label>Склад для расчёта<input required value={warehouse} onChange={e=>{setWarehouse(e.target.value);setPrepared(null);}}/></label><button className="ek-primary" disabled={preparing||!warehouse.trim()}>{preparing?'Подготовка…':'Подготовить данные для расчёта'}</button></form>{prepareError&&<p role="alert">{prepareError}</p>}{prepared&&<><p role="status">Подготовлено: {prepared.input.rows[0].sales.length} документов продаж, {prepared.input.rows[0].incoming.length} поставок. Свободный остаток: {show(prepared.input.rows[0].free_stock)}. Остатки, полноту поставок и ограничения необходимо подтвердить перед расчётом.</p><button className="ek-secondary" onClick={downloadPrepared}>Скачать данные расчёта JSON</button><details><summary>Происхождение и ограничения</summary><pre style={{whiteSpace:'pre-wrap',overflowWrap:'anywhere'}}>{JSON.stringify(prepared.usage,null,2)}</pre></details></>}</section>}
  </div>;
}
