// @vitest-environment jsdom
import {expect,test,afterEach,beforeEach,vi} from 'vitest';
import {render,screen,fireEvent,cleanup,waitFor} from '@testing-library/react';
import ElektroWorkspace from './elektro-workspace.jsx';
afterEach(()=>{cleanup();vi.unstubAllGlobals();});
beforeEach(()=>{
 HTMLDialogElement.prototype.showModal=function(){this.open=true;};
 HTMLDialogElement.prototype.close=function(){this.open=false;};
 vi.stubGlobal('fetch',vi.fn(async(url,init)=>({ok:true,json:async()=>({rows:JSON.parse(init.body).rows.map(r=>({row_id:r.row_id,status:'scenario_only',recommended_quantity:'100',daily_demand:'5',forecast_demand:'105',eligible_incoming:'0',raw_need:'100',rounding_surplus:'0',arrival_date:'2026-09-30',explanation:'Расчёт API',daily_balances:[],incoming_decisions:[],warnings:[],demand_adjustments:[]}))})})));
});
test('API rows render; custom period reaches unchanged request schema; approval revokes on edit',async()=>{
 render(<ElektroWorkspace/>);
 await screen.findByLabelText('Заказать EK-1001');
 fireEvent.click(screen.getByText('Период прогноза'));
 fireEvent.change(screen.getByLabelText('Количество дней'),{target:{value:'47'}});
 expect(screen.getByLabelText('Прогноз по дату включительно').value).toBe('2026-11-08');
 fireEvent.click(screen.getByRole('button',{name:'Рассчитать потребность'}));
 await waitFor(()=>expect(fetch.mock.calls.some(([,init])=>JSON.parse(init.body).forecast_end==='2026-11-08')).toBe(true));
 await screen.findByLabelText('Заказать EK-1001');
 fireEvent.click(screen.getByRole('button',{name:'Проверить и утвердить'}));
 fireEvent.click(screen.getByRole('button',{name:'Утвердить 8 позиций'}));
 expect(screen.getByRole('button',{name:'Скачать все заказы CSV'}).disabled).toBe(false);
 fireEvent.change(screen.getByLabelText('Заказать EK-1001'),{target:{value:'750'}});
 expect(screen.getByRole('button',{name:'Скачать все заказы CSV'}).disabled).toBe(true);
});
