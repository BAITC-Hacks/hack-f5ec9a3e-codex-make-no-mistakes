// @vitest-environment jsdom
import {afterEach,expect,test,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import SourceTables,{displaySourceValue,sourceTables} from './source-tables.jsx';
import {apiError} from './api.js';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});

test('table filters, sorting, pagination and export share the selected data scope',async()=>{
  HTMLDialogElement.prototype.close=function(){this.open=false;};
  HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  const fetchMock=vi.fn(async(url)=>({ok:true,json:async()=>url.includes('/suppliers?')
    ?{items:[{id:'supplier-1',name:'IEK'}]}
    :{items:[{id:'r1',sku:'000123',quantity:'0.000000000000',month:'2026-08-01',supplier_name:'IEK',source_column:'E',sha256:'hash'}],total:70}}));
  vi.stubGlobal('fetch',fetchMock);
  render(<SourceTables books={[{id:'book-1',original_path:'C:/data/sales.xlsx'}]} workbook="book-1" onWorkbookChange={vi.fn()} revision={0} onRefresh={vi.fn()} onSelectProduct={vi.fn()}/>);
  await screen.findByText('000123');
  fireEvent.change(screen.getByLabelText('Поиск в таблице'),{target:{value:'000123'}});
  fireEvent.click(screen.getByRole('button',{name:'Найти'}));
  fireEvent.change(screen.getByLabelText('Поставщик таблицы'),{target:{value:'supplier-1'}});
  await waitFor(()=>expect(screen.getByRole('link',{name:'Скачать таблицу CSV'}).href).toContain('supplier_id=supplier-1'));
  expect(screen.getByRole('link',{name:'Скачать таблицу CSV'}).href).toContain('q=000123');
  expect(screen.getByRole('link',{name:'Скачать таблицу CSV'}).href).toContain('workbook_id=book-1');
  fireEvent.click(await screen.findByRole('button',{name:'Количество'}));
  await waitFor(()=>expect(fetchMock.mock.calls.at(-1)[0]).toContain('sort=quantity'));
  await screen.findByText('000123');
  fireEvent.click(screen.getByRole('button',{name:'Следующая страница данных'}));
  await waitFor(()=>expect(fetchMock.mock.calls.at(-1)[0]).toContain('page=2'));
  fireEvent.click(await screen.findByRole('button',{name:'Подробнее о записи 000123'}));
  expect(await screen.findByText('Контрольная сумма')).toBeTruthy();
  expect(screen.getByText('hash')).toBeTruthy();
  fireEvent.click(screen.getByRole('button',{name:'Закрыть детали записи'}));
  fireEvent.click(screen.getByRole('button',{name:'Справочники'}));
  await waitFor(()=>expect(fetchMock.mock.calls.at(-1)[0]).toContain('/tables/catalog?'));
  expect(fetchMock.mock.calls.at(-1)[0]).not.toContain('workbook_id');
  expect(screen.queryByRole('link',{name:'Скачать таблицу CSV'})).toBeNull();
});

test('all source tables are accessible and values preserve zero, missingness and exact decimals',()=>{
  expect(sourceTables).toHaveLength(16);
  expect(displaySourceValue('quantity',null)).toBe('—');
  expect(displaySourceValue('quantity','0.000000000000')).toBe('0');
  expect(displaySourceValue('quantity','123456789012345678.123456789012')).toBe('123\u00a0456\u00a0789\u00a0012\u00a0345\u00a0678,123456789012');
  expect(displaySourceValue('sku','000123')).toBe('000123');
  const message=apiError([{type:'extra_forbidden',loc:['body','forecast_end'],msg:'Extra inputs are not permitted'},{type:'extra_forbidden',loc:['body','forecast_method'],msg:'Extra inputs are not permitted'}],422);
  expect(message).toContain('forecast_end, forecast_method');
  expect(message).not.toContain('Extra inputs');
});
