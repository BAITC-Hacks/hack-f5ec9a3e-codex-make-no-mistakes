// @vitest-environment jsdom
import {afterEach,expect,test,vi} from 'vitest';
import {cleanup,fireEvent,render,screen,waitFor} from '@testing-library/react';
import ConnectedWorkspace from './connected-workspace.jsx';
import {overridesFor} from './api.js';

afterEach(()=>{cleanup();vi.unstubAllGlobals();});

test('server revisions, decimal overrides, approval conflict, export and reload use the backend',async()=>{
  HTMLDialogElement.prototype.showModal=function(){this.open=true;};
  HTMLDialogElement.prototype.close=function(){this.open=false;};
  const input={planning_date:'2026-09-23',lead_time_days:7,review_days:7,buffer_days:'0',growth_pct:'0',seasonality:{},exclude_bulk:false,compensate_stockouts:false,rows:[{row_id:'item',sku:'REAL-001',supplier:'Supplier',name:'Product',stock_unit:'шт',warehouse:'Алматы',basis:'synthetic',sales:[],sources:[],incoming:[],notes:[]}]};
  const result={rows:[{...input.rows[0],status:'scenario_only',purchase_unit:'шт',recommended_quantity:'100',free_stock:'50',eligible_incoming:'70',daily_demand:'20',maximum_prearrival_shortfall:'0',excluded_bulk_quantity:'0',missing_inputs:[],warnings:[],demand_adjustments:[],daily_balances:[],explanation:'Server arithmetic'}]};
  let saved=null,conflict=true;
  const requests=[];
  vi.stubGlobal('fetch',vi.fn(async(url,options)=>{
    const body=options.body?JSON.parse(options.body):null;requests.push({url,body,method:options.method});
    let response;
    if(url.includes('/tables/warehouses'))response={items:[{id:'w',name:'Алматы'}]};
    else if(url.includes('/tables/workbooks'))response={items:[]};
    else if(url.endsWith('/planning/demo-cases'))response=[{id:'baseline',name:'Synthetic baseline',input}];
    else if(url.endsWith('/planning/calculate'))response=result;
    else if(url.endsWith('/scenarios')&&body){saved={id:'saved',name:body.name,input:body.input,result,overrides:[],revision:1,approved_revision:null};response=saved;}
    else if(url.endsWith('/scenarios'))response={items:saved?[saved]:[]};
    else if(url.endsWith('/approve')){
      if(conflict)return {ok:false,status:409,json:async()=>({detail:'Stale revision'})};
      saved={...saved,approved_revision:body.expected_revision,approved_by:body.approved_by};response=saved;
    }else if(options.method==='PUT'){saved={...saved,revision:saved.revision+1,overrides:body.overrides,approved_revision:null};response=saved;}
    else response=saved;
    return {ok:true,json:async()=>structuredClone(response)};
  }));
  render(<ConnectedWorkspace/>);
  await waitFor(()=>expect(screen.getByLabelText('Синтетический пример').disabled).toBe(false));
  fireEvent.change(screen.getByLabelText('Синтетический пример'),{target:{value:'baseline'}});
  await screen.findByLabelText('Заказать REAL-001');
  fireEvent.change(screen.getByLabelText('Заказать REAL-001'),{target:{value:'24.125000000001'}});
  expect(screen.getByRole('button',{name:'Проверить и утвердить'}).disabled).toBe(true);
  fireEvent.change(screen.getByLabelText('Причина корректировки REAL-001'),{target:{value:'Reviewed exact quantity'}});
  fireEvent.click(screen.getByRole('button',{name:'Сохранить черновик / новую версию'}));
  await waitFor(()=>expect(saved?.revision).toBe(2));
  await waitFor(()=>expect(screen.getByRole('button',{name:'Проверить и утвердить'}).disabled).toBe(false));
  expect(saved.overrides[0].quantity).toBe('24.125000000001');
  fireEvent.click(screen.getByRole('button',{name:'Проверить и утвердить'}));
  fireEvent.change(screen.getByLabelText('Ответственный сотрудник'),{target:{value:'Test reviewer'}});
  fireEvent.click(screen.getByLabelText('Я проверил количества и принимаю сценарные допущения'));
  fireEvent.click(screen.getByRole('button',{name:'Утвердить сценарий'}));
  await waitFor(()=>expect(screen.getAllByRole('alert').some(el=>el.textContent.includes('409'))).toBe(true));
  expect(screen.queryByRole('link',{name:'Скачать утверждённый CSV'})).toBeNull();
  conflict=false;
  await waitFor(()=>expect(screen.getByRole('button',{name:'Утвердить сценарий'}).disabled).toBe(false));
  fireEvent.click(screen.getByRole('button',{name:'Утвердить сценарий'}));
  expect((await screen.findByRole('link',{name:'Скачать утверждённый CSV'})).getAttribute('href')).toBe('/api/v1/scenarios/saved/export?expected_revision=2');
  cleanup();render(<ConnectedWorkspace/>);
  await waitFor(()=>expect(screen.getAllByRole('button',{name:/Заказы поставщикам/})[0].disabled).toBe(false));
  fireEvent.click(screen.getAllByRole('button',{name:/Заказы поставщикам/})[0]);
  fireEvent.click(await screen.findByRole('button',{name:/Закупка 2026-09-23 · версия 2/}));
  await screen.findByRole('link',{name:'Скачать утверждённый CSV'});
  fireEvent.change(screen.getByLabelText('Заказать REAL-001'),{target:{value:'25'}});
  expect(screen.queryByRole('link',{name:'Скачать утверждённый CSV'})).toBeNull();
  expect(requests.filter(r=>r.url.endsWith('/approve')).every(r=>r.body.expected_revision===2)).toBe(true);
});

test('missing inputs cannot become an order through a manual override',()=>{
  expect(()=>overridesFor([{row_id:'blocked',sku:'B',status:'needs_input'}],{blocked:'6'},{blocked:'reason'})).toThrow('исходные данные');
});
