import { expect, test } from 'vitest';
import { formatValue, makeQuery } from './display';

test('blank and zero remain distinguishable, decimals and SKU remain exact', () => {
  expect(formatValue(null)).toBe('Нет данных');
  expect(formatValue(0)).toBe('0');
  expect(formatValue('0.000')).toBe('0.000');
  expect(formatValue('000123_')).toBe('000123_');
  expect(formatValue('#N/A')).toBe('#N/A');
});
test('server query preserves source and version, omits empty filters', () => {
  const query = new URLSearchParams(makeQuery({ page: 2, q: 'А & Б', workbook_id: 'book', normalizer_version: 'v1', supplier_id: '' }));
  expect(query.get('page')).toBe('2');
  expect(query.get('q')).toBe('А & Б');
  expect(query.get('workbook_id')).toBe('book');
  expect(query.get('normalizer_version')).toBe('v1');
  expect(query.has('supplier_id')).toBe(false);
});
