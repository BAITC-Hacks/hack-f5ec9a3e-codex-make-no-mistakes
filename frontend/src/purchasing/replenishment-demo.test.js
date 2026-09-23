import {expect,test} from 'vitest';
import {buildDemoRow,defaults,products,validateOptions,addDays} from './replenishment-demo.js';
test('fixtures retain dated evidence and API horizon constraints',()=>{
 const row=buildDemoRow(products[0],defaults);
 expect(row.dailyHistory.length).toBe(row.historyDays);
 expect(row.dailyHistory.reduce((sum,d)=>sum+d.raw,0)).toBe(row.rawSales);
 expect(row.deliveries.reduce((sum,d)=>sum+d.quantity,0)).toBe(row.incomingTotal);
 expect(row.quantity).toBeUndefined();
 expect(validateOptions({...defaults,horizon:47,forecastEnd:addDays(defaults.planningDate,46)})).toBe('');
 expect(validateOptions({...defaults,horizon:2,forecastEnd:addDays(defaults.planningDate,1)})).toContain('API');
});
