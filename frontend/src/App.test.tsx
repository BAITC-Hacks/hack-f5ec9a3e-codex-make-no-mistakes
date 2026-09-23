// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';
import App from './App';

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const descriptors = ['catalog', 'products'].map(key => ({ key, columns: [{ key: 'sku', type: 'VARCHAR', nullable: false }, { key: 'quantity', type: 'NUMERIC', nullable: true }], sortable: ['sku'], filters: ['supplier_id', 'workbook_id', 'normalizer_version', 'product_id'] }));

test('table delegates paging, sort and literal search to API and opens exact source evidence', async () => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true; };
  HTMLDialogElement.prototype.close = function () { this.open = false; };
  const fetcher = vi.fn(async (input: string) => {
    const url = new URL(input, 'http://localhost');
    let body: unknown = { items: [] };
    if (url.pathname.endsWith('/tables')) body = descriptors;
    if (url.pathname.endsWith('/products') || url.pathname.endsWith('/catalog')) body = { total: 101, page: Number(url.searchParams.get('page')), page_size: 50, table: url.pathname.split('/').pop(), items: [{ id: 'product-1', product_id: 'product-1', sku: '0001_', quantity: null, source_row_id: 'raw-1', normalizer_version: 'v1' }] };
    if (url.pathname.endsWith('/raw-1')) body = { row_number: 2, cells: { E: { type: 'e', value: '#N/A' } } };
    return { ok: true, json: async () => body };
  });
  vi.stubGlobal('fetch', fetcher);
  render(<App/>);
  await screen.findByText('0001_');
  expect(screen.getByRole('heading', { name: 'Каталог SKU' })).toBeTruthy();
  expect(screen.getByText('Нет данных')).toBeTruthy();
  fireEvent.click(screen.getByLabelText('Следующая страница'));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('page=2'))).toBe(true));
  await screen.findByText('0001_');
  fireEvent.click(screen.getByRole('button', { name: /Код 1С/ }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('sort=sku'))).toBe(true));
  fireEvent.change(screen.getByLabelText('Поиск по таблице'), { target: { value: '0001_' } });
  fireEvent.click(screen.getByRole('button', { name: 'Найти' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('q=0001_') && url.includes('page=1'))).toBe(true));
  await screen.findByText('0001_');
  fireEvent.click(screen.getByRole('button', { name: 'Открыть источник строки 1' }));
  await waitFor(() => expect(fetcher.mock.calls.some(([url]) => url.includes('/products?') && url.includes('product_id=product-1') && url.includes('page=1'))).toBe(true));
  await screen.findByRole('button', { name: 'Снять фильтр SKU' });
  await screen.findByLabelText('Открыть источник строки 1');
  fireEvent.click(screen.getByLabelText('Открыть источник строки 1'));
  await screen.findByText('#N/A');
  expect(fetcher.mock.calls.some(([url]) => url.endsWith('/source-rows/raw-1'))).toBe(true);
  fireEvent.click(screen.getByLabelText('Закрыть подробности'));
  fireEvent.click(screen.getByRole('button', { name: /Каталог SKU/ }));
  await screen.findByRole('heading', { name: 'Каталог SKU' });
  expect(screen.queryByRole('button', { name: 'Снять фильтр SKU' })).toBeNull();
});

test('failed API can be retried and empty results are explicit', async () => {
  let failed = true;
  vi.stubGlobal('fetch', vi.fn(async (input: string) => {
    if (failed) throw new Error('Нет соединения');
    return { ok: true, json: async () => input.endsWith('/tables') ? descriptors : { items: [], total: 0, page: 1, page_size: 50 } };
  }));
  render(<App/>);
  await screen.findByRole('alert');
  failed = false;
  fireEvent.click(screen.getByRole('button', { name: 'Повторить' }));
  await screen.findByText('Записей не найдено');
  expect((screen.getByLabelText('Следующая страница') as HTMLButtonElement).disabled).toBe(true);
});
