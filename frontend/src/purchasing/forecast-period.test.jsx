// @vitest-environment jsdom
import {useState} from 'react';
import {test,expect,afterEach} from 'vitest';
import {render,screen,fireEvent,cleanup} from '@testing-library/react';
import ForecastPeriod from './forecast-period.jsx';
afterEach(cleanup);

test('custom dates determine the inclusive horizon without presets',()=>{
  function Example(){const [input,setInput]=useState({planning_date:'2026-09-23',forecast_end:null});return <ForecastPeriod input={input} onChange={setInput}/>;}
  render(<Example/>);
  fireEvent.click(screen.getByText('Период прогноза'));
  fireEvent.change(screen.getByLabelText('Прогноз по дату включительно'),{target:{value:'2026-11-08'}});
  expect(screen.getByLabelText('Количество дней').value).toBe('47');
  fireEvent.change(screen.getByLabelText('Начало прогноза'),{target:{value:'2026-09-25'}});
  expect(screen.getByLabelText('Количество дней').value).toBe('45');
  expect(screen.getByLabelText('Прогноз по дату включительно').value).toBe('2026-11-08');
  fireEvent.change(screen.getByLabelText('Количество дней'),{target:{value:'19'}});
  expect(screen.getByLabelText('Прогноз по дату включительно').value).toBe('2026-10-13');
  fireEvent.change(screen.getByLabelText('Прогноз по дату включительно'),{target:{value:'2026-09-24'}});
  expect(screen.getByRole('button',{name:'Применить период'}).disabled).toBe(true);
});
