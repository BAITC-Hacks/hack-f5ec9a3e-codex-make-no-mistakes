import {expect,test,vi,afterEach} from 'vitest';
import {calculatePlan,planningPayload} from './planning-api.js';
import {buildDemoRow,defaults,products,addDays} from './replenishment-demo.js';
afterEach(()=>vi.unstubAllGlobals());
test('existing contract gets raw dated evidence, no browser daily forecast, and exact custom coverage',async()=>{
  const options={...defaults,horizon:47,forecastEnd:addDays(defaults.planningDate,46)};
  const row=buildDemoRow(products[0],options),body=planningPayload([row],options);
  expect(body.forecast_end).toBeUndefined();
  expect(body.forecast_method).toBeUndefined();
  expect(body.review_days).toBe(40);
  expect(body.rows[0].daily_demand).toBeUndefined();
  expect(body.rows[0].sales[0]).toHaveProperty('customer_id');
  expect(body.rows[0].stockout_days.length).toBeGreaterThan(0);
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:true,json:async()=>({rows:[{row_id:row.sku,status:'scenario_only',recommended_quantity:'777',daily_demand:'9',forecast_demand:'423',raw_need:'283',eligible_incoming:'20',rounding_surplus:'0',excluded_bulk_quantity:'17',lost_demand_quantity:'4',arrival_date:'2026-09-30',explanation:'Server explanation',daily_balances:[{day:options.planningDate,demand:'9'}],incoming_decisions:[],warnings:[],demand_adjustments:[]}]})})));
  const [result]=await calculatePlan(options,{},undefined,[products[0]]);
  expect(result.quantity).toBe(777);
  expect(result.reason).toBe('Server explanation');
  expect(result.forecastSeries[0].forecast).toBe(9);
  expect(fetch.mock.calls[0][0]).toBe('/api/v1/planning/calculate');
});
test('API failure never falls back to a local forecast',async()=>{
  vi.stubGlobal('fetch',vi.fn(async()=>({ok:false,status:503,json:async()=>({detail:'Unavailable'})})));
  await expect(calculatePlan(defaults)).rejects.toThrow('Unavailable');
});
