export const tableLabels: Record<string, string> = {
  catalog: 'Каталог SKU', products: 'Атрибуты из источников', movements: 'Движения', 'monthly-sales': 'Продажи по месяцам',
  'monthly-stock': 'Остатки по месяцам', 'current-stock': 'Текущие остатки', moq: 'Условия заказа',
  shipments: 'Поставки', 'shipment-lines': 'Товар в пути', 'report-metrics': 'Показатели отчётов',
  seasonality: 'Сезонность', findings: 'Качество данных', workbooks: 'Исходные книги', sheets: 'Листы', suppliers: 'Поставщики', warehouses: 'Склады',
};
export const columnLabels: Record<string, string> = {
  sku: 'Код 1С', source_code: 'Код 1С', name: 'Наименование', product_name: 'Наименование', article: 'Артикул', supplier_name: 'Поставщик', supplier: 'Поставщик',
  unit: 'Ед.', category_code: 'Категория', category_year: 'Год категории', quantity: 'Количество', value: 'Значение',
  occurred_at: 'Дата движения', movement_at: 'Дата движения', document_number: '№ документа', document_type: 'Документ', warehouse_name: 'Склад', warehouse: 'Склад',
  period: 'Период', month: 'Месяц', year: 'Год', stock_type: 'Тип остатка', kind: 'Тип', metric: 'Показатель', metric_type: 'Показатель',
  rule_type: 'Тип правила', source_label: 'Подпись источника', label: 'Подпись', basis: 'Основание', expected_on: 'Ожидаемая дата', date_basis: 'Основание даты',
  normalizer_version: 'Версия импорта', semantic_status: 'Статус смысла', status: 'Статус', code: 'Код', severity: 'Уровень', description: 'Описание', resolution: 'Решение',
  path: 'Файл', relative_path: 'Файл', original_path: 'Файл', filename: 'Файл', sha256: 'SHA-256', sheet_name: 'Лист', row_number: 'Строка Excel', source_column: 'Колонка Excel',
  imported_at: 'Импортирован', row_count: 'Строк', column_count: 'Колонок', max_row: 'Строк', max_column: 'Колонок', supplier_code: 'Поставщик',
  supplier_article: 'Артикул', document_text: 'Документ', header: 'Заголовок', observed_on: 'Дата наблюдения', stock_basis: 'Основание остатка',
  semantic_basis: 'Основание', quantity_basis: 'Смысл количества', period_start: 'Начало периода', period_end: 'Конец периода',
  source_period: 'Период источника', source_header: 'Заголовок источника', finding_key: 'Ключ замечания', evidence: 'Доказательства', notes: 'Примечания',
  is_complete_period: 'Полный период', scope_label: 'Область остатка', as_of: 'Дата среза', interpretation_confirmed: 'Смысл подтверждён', ordered_on: 'Дата заказа',
  value_basis: 'Основание значения', metric_kind: 'Вид показателя', observed_year: 'Год наблюдения', report_period: 'Период отчёта', file_size: 'Размер файла', size_bytes: 'Размер, байт',
  byte_size: 'Размер, байт', archive_name: 'Архив', captured_at: 'Дата загрузки', capture_version: 'Версия загрузки', reported_rows: 'Строк в листе', reported_columns: 'Колонок в листе', position: 'Позиция листа',
};
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return 'Нет данных';
  if (value === '') return 'Пустая строка';
  if (typeof value === 'boolean') return value ? 'Да' : 'Нет';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}
export function makeQuery(values: Record<string, string | number>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== '') query.set(key, String(value));
  return query.toString();
}
