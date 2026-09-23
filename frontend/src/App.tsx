import { useEffect, useRef, useState } from 'react';
import { columnLabels, formatValue, makeQuery, tableLabels } from './display';
import type { TableDescriptor as Descriptor, TableRow as Row, TablePage as Page } from './api/types';

const hidden = new Set(['id', 'product_id', 'supplier_id', 'source_row_id', 'source_sheet_id', 'sheet_id', 'workbook_id', 'warehouse_id', 'shipment_id', 'sha256', 'original_path', 'supplier_code', 'normalizer_version', 'created_at', 'imported_at']);
const priority = ['sku', 'name', 'supplier_name', 'supplier_article', 'unit', 'occurred_at', 'month', 'year', 'quantity', 'value'];
async function get<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/v1/${path}`, { signal });
  if (!response.ok) throw new Error(`Сервер вернул ${response.status}. Проверьте API и подключение к базе данных.`);
  return response.json() as Promise<T>;
}
function Cell({ value }: { value: unknown }) {
  return <span className={value == null ? 'null' : typeof value === 'string' && value.startsWith('#') ? 'excel-error' : ''}>{formatValue(value)}</span>;
}

export default function App() {
  const [descriptors, setDescriptors] = useState<Descriptor[]>([]);
  const [suppliers, setSuppliers] = useState<Row[]>([]);
  const [books, setBooks] = useState<Row[]>([]);
  const [table, setTable] = useState('catalog');
  const [product, setProduct] = useState<{ id: string; sku: string } | null>(null);
  const [supplier, setSupplier] = useState('');
  const [book, setBook] = useState('');
  const [version, setVersion] = useState('');
  const [search, setSearch] = useState('');
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const [size, setSize] = useState(50);
  const [sort, setSort] = useState('');
  const [direction, setDirection] = useState<'asc' | 'desc'>('asc');
  const [result, setResult] = useState<Page | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<Row | null>(null);
  const [evidence, setEvidence] = useState<Row | null>(null);
  const [evidenceError, setEvidenceError] = useState('');
  const [evidenceRetry, setEvidenceRetry] = useState(0);
  const dialog = useRef<HTMLDialogElement>(null);
  const descriptor = descriptors.find(item => item.key === table);
  const columns = [...(descriptor?.columns ?? [])].filter(col => !hidden.has(col.key) || (table === 'workbooks' && col.key === 'original_path')).sort((a, b) => {
    const left = priority.indexOf(a.key), right = priority.indexOf(b.key);
    return (left < 0 ? 99 : left) - (right < 0 ? 99 : right);
  });
  useEffect(() => {
    const controller = new AbortController();
    Promise.all([get<Descriptor[]>('tables', controller.signal), get<Page>('tables/suppliers?page_size=200', controller.signal), get<Page>('tables/workbooks?page_size=200', controller.signal)])
      .then(([tables, supplierPage, bookPage]) => { setDescriptors(tables); setSuppliers(supplierPage.items); setBooks(bookPage.items); })
      .catch(err => { if (!controller.signal.aborted) { setError(String(err.message)); setLoading(false); } });
    return () => controller.abort();
  }, [retry]);
  useEffect(() => {
    if (!descriptor) return;
    const controller = new AbortController();
    setLoading(true); setError(''); setResult(null);
    const filters: Record<string, string | number> = { page, page_size: size, sort, direction, q };
    for (const [key, value] of Object.entries({ supplier_id: supplier, workbook_id: book, normalizer_version: version, product_id: product?.id ?? '' })) {
      if (descriptor.filters.includes(key)) filters[key] = value;
    }
    get<Page>(`tables/${table}?${makeQuery(filters)}`, controller.signal)
      .then(setResult).catch(err => { if (!controller.signal.aborted) setError(String(err.message)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [descriptor, table, supplier, book, version, product, q, page, size, sort, direction, retry]);
  useEffect(() => {
    if (!selected) return;
    dialog.current?.showModal(); setEvidence(null); setEvidenceError('');
    if (!selected.source_row_id) return;
    const controller = new AbortController();
    get<Row>(`source-rows/${selected.source_row_id}`, controller.signal).then(setEvidence)
      .catch(err => { if (!controller.signal.aborted) setEvidenceError(String(err.message)); });
    return () => controller.abort();
  }, [selected, evidenceRetry]);
  const changeTable = (key: string) => { setTable(key); setProduct(null); setPage(1); setSort(''); setDirection('asc'); setQ(''); setSearch(''); };
  const inspectProduct = (row: Row) => {
    changeTable('products'); setBook(''); setVersion('');
    setProduct({ id: String(row.product_id ?? row.id), sku: String(row.sku) });
  };
  const pages = Math.max(1, Math.ceil((result?.total ?? 0) / size));
  const filteredBooks = books.filter(item => !supplier || !item.supplier_id || item.supplier_id === supplier);
  const close = () => { dialog.current?.close(); setSelected(null); };

  return <div className="workspace">
    <aside className="sidebar"><a className="brand" href="#main"><span className="brand-icon">П</span>поставка<span className="brand-dot">.</span></a>
      <div className="workspace-label">HACKALEM / ЗАКУПКИ</div>
      <div className="nav-heading">РАБОЧЕЕ ПРОСТРАНСТВО</div>
      <nav aria-label="Таблицы данных">{(descriptors.length ? descriptors : Object.keys(tableLabels).map(key => ({ key }))).map(item => <button key={item.key} className={table === item.key ? 'nav-item active' : 'nav-item'} aria-current={table === item.key ? 'page' : undefined} onClick={() => changeTable(item.key)}><span className="nav-marker">{item.key === 'findings' ? '!' : '▦'}</span>{tableLabels[item.key] ?? item.key}</button>)}</nav>
      <div className="sidebar-footer"><span className="status-dot"/>Просмотр исходных данных<br/><small>Excel → PostgreSQL</small></div>
    </aside>
    <main id="main"><header className="topbar"><span>Рабочее пространство <span className="slash">/</span> Данные</span><span className="read-only">Только чтение</span></header>
      <section className="content"><div className="page-heading"><div><p className="eyebrow">БИБЛИОТЕКА ДАННЫХ</p><h1>{tableLabels[table] ?? table}</h1><p className="subtitle">Данные поставщиков с привязкой к каждой строке Excel.</p></div><button className="button" onClick={() => setRetry(value => value + 1)}>↻ Обновить</button></div>
        <div className="notice"><span className="notice-icon">i</span><div>{table === 'catalog' ? 'Одна строка — один SKU поставщика.' : table === 'products' ? 'Атрибуты одного SKU могут повторяться в разных строках Excel.' : 'Каждая строка — наблюдение из источника.'}<br/><small>{table === 'catalog' ? 'Названия и артикулы сохранены отдельно в источниках. Откройте атрибуты, чтобы проверить их происхождение.' : 'Версии и повторяющиеся отчёты не суммируются. Пустое значение не равно нулю.'}</small></div></div>
        {product && <div className="product-filter"><span>Атрибуты SKU <strong>{product.sku}</strong></span><button className="button" onClick={() => { setProduct(null); setPage(1); }}>Снять фильтр SKU</button></div>}
        <div className="filter-row">
          <label>Поставщик<select value={supplier} disabled={!descriptor?.filters.includes('supplier_id')} onChange={event => { setSupplier(event.target.value); setBook(''); setPage(1); }}><option value="">Все поставщики</option>{suppliers.map(item => <option key={String(item.id)} value={String(item.id)}>{String(item.name ?? item.code)}</option>)}</select></label>
          <label className="source-filter">Исходная книга<select value={book} disabled={!descriptor?.filters.includes('workbook_id')} onChange={event => { setBook(event.target.value); setPage(1); }}><option value="">Все источники (раздельные строки)</option>{filteredBooks.map(item => <option key={String(item.id)} value={String(item.id)}>{String(item.original_path ?? item.id).split(/[\\/]/).pop()} · {String(item.sha256).slice(0, 8)}</option>)}</select></label>
          <label>Версия нормализатора<input value={version} disabled={!descriptor?.filters.includes('normalizer_version')} placeholder="Все версии" onChange={event => { setVersion(event.target.value); setPage(1); }}/></label>
        </div>
        <section className="table-card" aria-label={tableLabels[table]}><div className="table-toolbar"><div><strong>Записи</strong><span className="count">{result ? result.total.toLocaleString('ru-RU') : '—'}</span></div><form className="search" onSubmit={event => { event.preventDefault(); setQ(search); setPage(1); }}><input aria-label="Поиск по таблице" placeholder={table === "products" ? "Код, название или артикул…" : "Код или текст источника…"} value={search} onChange={event => setSearch(event.target.value)}/><button type="submit">Найти</button></form></div>
          {loading ? <div className="state" role="status"><span className="spinner"/><strong>Загружаем записи</strong><p>Запрашиваем одну страницу из базы данных.</p></div> : error ? <div className="state" role="alert"><strong>Не удалось загрузить данные</strong><p>{error}</p><button className="button" onClick={() => setRetry(value => value + 1)}>Повторить</button></div> : !result?.items.length ? <div className="state"><strong>Записей не найдено</strong><p>Измените фильтры или загрузите Excel через скрипт импорта.</p><button className="button" onClick={() => { setProduct(null); setSupplier(''); setBook(''); setVersion(''); setSearch(''); setQ(''); setPage(1); }}>Сбросить фильтры</button></div> : <div className="table-scroll" tabIndex={0} role="region" aria-label="Таблица, прокрутка по горизонтали"><table><thead><tr>{columns.map(col => <th key={col.key} aria-sort={sort === col.key ? direction === 'asc' ? 'ascending' : 'descending' : undefined}><button disabled={!descriptor?.sortable.includes(col.key)} onClick={() => { setSort(col.key); setDirection(sort === col.key && direction === 'asc' ? 'desc' : 'asc'); setPage(1); }}>{columnLabels[col.key] ?? col.key}<span className="sort-indicator">{sort === col.key ? direction === 'asc' ? '↑' : '↓' : '↕'}</span></button></th>)}<th className="evidence-column">Источник</th></tr></thead><tbody>{result.items.map((row, index) => <tr key={String(row.id ?? index)}>{columns.map(col => <td key={col.key} className={col.key === 'sku' ? 'sku' : /NUMERIC|INTEGER/.test(col.type) ? 'numeric' : ''} title={formatValue(row[col.key])}><Cell value={row[col.key]}/></td>)}<td className="evidence-column"><button className="evidence-button" aria-label={`Открыть источник строки ${index + 1}`} onClick={() => table === 'catalog' ? inspectProduct(row) : setSelected(row)}>{table === 'catalog' ? 'Атрибуты →' : 'Подробнее ↗'}</button></td></tr>)}</tbody></table></div>}
          <footer className="table-footer"><span>{result?.total ? `${(page - 1) * size + 1}–${Math.min(page * size, result.total)} из ${result.total.toLocaleString('ru-RU')}` : '0 записей'}<span className="legend"> · Нет данных ≠ 0</span></span><div className="pagination"><label>Строк<select aria-label="Строк на странице" value={size} onChange={event => { setSize(Number(event.target.value)); setPage(1); }}>{[25, 50, 100, 200].map(value => <option key={value}>{value}</option>)}</select></label><button aria-label="Предыдущая страница" disabled={loading || page <= 1} onClick={() => setPage(value => value - 1)}>←</button><span>{page} / {pages}</span><button aria-label="Следующая страница" disabled={loading || page >= pages} onClick={() => setPage(value => value + 1)}>→</button></div></footer>
        </section><p className="bottom-note">Значения показаны как в источнике. Формулы, ошибки Excel и происхождение доступны в подробностях строки.</p>
      </section>
    </main>
    <dialog ref={dialog} className="drawer" onCancel={() => setSelected(null)} onClose={() => setSelected(null)}><header><div><p className="eyebrow">ПРОИСХОЖДЕНИЕ ДАННЫХ</p><h2>Исходная запись</h2></div><button className="button" aria-label="Закрыть подробности" onClick={close}>✕</button></header>{selected && <><section><h3>Нормализованная строка</h3><dl>{Object.entries(selected).map(([key, value]) => <div key={key}><dt>{columnLabels[key] ?? key}</dt><dd><Cell value={value}/></dd></div>)}</dl></section>{selected.source_row_id ? <section><h3>Ячейки Excel</h3><p className="subtitle">Формулы не пересчитываются. Показан сохранённый результат; отсутствующие ячейки остаются пустыми.</p>{evidenceError ? <div role="alert"><p>{evidenceError}</p><button className="button" onClick={() => setEvidenceRetry(value => value + 1)}>Повторить</button></div> : !evidence ? <p role="status">Загружаем исходную строку…</p> : <div className="raw-cells">{Object.entries((evidence.cells ?? {}) as Record<string, Row>).map(([coordinate, cell]) => <article key={coordinate}><strong>{coordinate}{String(evidence.row_number ?? '')}</strong><dl>{Object.entries(cell).map(([key, value]) => <div key={key}><dt>{({ type: 'Тип', value: 'Значение', formula: 'Формула', cached_value: 'Сохранённый результат', number_format: 'Формат' } as Record<string, string>)[key] ?? key}</dt><dd><Cell value={value}/></dd></div>)}</dl></article>)}</div>}</section> : <p className="subtitle">У этой записи нет отдельной ссылки на строку Excel. Доступные сведения об источнике показаны выше.</p>}</>}</dialog>
  </div>;
}
