// @vitest-environment jsdom
import {afterEach,expect,test,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import ElektroWorkspace from './connected-workspace.jsx';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});

test('Sources navigation opens uploader, posts original file, then reads persisted records',async()=>{
  HTMLDialogElement.prototype.close=function(){this.open=false;};
  const fetchMock=vi.fn(async(url,options)=>({ok:true,json:async()=>url==='/api/v1/planning/source-input'
    ?{input:{rows:[{sales:[{quantity:'3'}],incoming:[],free_stock:null}]},usage:[]}
    :url.includes('/planning/demo-cases')?[]
    :url.includes('/scenarios')?{items:[]}
    :url.includes('/tables/catalog?')?{items:[],total:0,page:1}
    :url.includes('/tables/warehouses?')?{items:[{id:'warehouse-1',name:'Алматы'}]}
    :options?.method==='POST'
    ?{results:[{path:'IEK.csv',status:'imported',workbook_id:'saved-book',counts:{monthly_sales:1}}]}
    :url.includes('/workbooks?')?{items:[{id:'saved-book',original_path:'IEK.csv'}],total:1}
    :{items:[{id:'row-1',product_id:'product-1',sku:'00123',quantity:'12.5',sheet_name:'CSV',row_number:2}],total:1}}));
  vi.stubGlobal('fetch',fetchMock);
  render(<ElektroWorkspace/>);
  const navigation=screen.getByRole('button',{name:/Источники данных.*Импортированные/});
  await waitFor(()=>expect(navigation.disabled).toBe(false));
  fireEvent.click(navigation);
  const file=new File(['record_type,sku'], 'IEK.csv',{type:'text/csv'});
  fireEvent.change(screen.getByLabelText('Файлы Excel, CSV или ZIP'),{target:{files:[file]}});
  fireEvent.click(screen.getByRole('button',{name:'Загрузить в базу (1)'}));
  await screen.findByText('Сохранено в базе');
  const upload=fetchMock.mock.calls.find(([,options])=>options?.method==='POST');
  expect(upload[0]).toContain('/api/v1/sources/upload?filename=IEK.csv');
  expect(upload[1].body).toBe(file);
  await waitFor(()=>expect(fetchMock.mock.calls.some(([url])=>url.includes('workbook_id=saved-book'))).toBe(true));
  expect(await screen.findByText('00123')).toBeTruthy();
  expect(screen.getByRole('link',{name:'Скачать таблицу CSV'}).href).toContain('workbook_id=saved-book');
  fireEvent.click(screen.getByRole('button',{name:'Выбрать SKU 00123'}));
  fireEvent.change(screen.getByLabelText('Склад для расчёта'),{target:{value:'Алматы'}});
  fireEvent.click(screen.getByRole('button',{name:'Подготовить данные для расчёта'}));
  await screen.findByText(/Подготовлено: 1 документов продаж/);
  const preparation=fetchMock.mock.calls.find(([url])=>url==='/api/v1/planning/source-input');
  expect(JSON.parse(preparation[1].body)).toMatchObject({product_ids:['product-1'],workbook_ids:['saved-book'],warehouse:'Алматы'});
});
