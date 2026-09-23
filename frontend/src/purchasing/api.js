export function apiError(detail,status,statusText='') {
  if(Array.isArray(detail)) {
    const extra=detail.filter(item=>item.type==='extra_forbidden');
    if(extra.length) {
      const fields=[...new Set(extra.map(item=>(item.loc||[]).filter(part=>part!=='body').join('.')))];
      return `Сервер не поддерживает параметры расчёта: ${fields.join(', ')}. Версия сервера устарела — перезапустите backend и повторите расчёт.`;
    }
    return [...new Set(detail.map(item=>`${(item.loc||[]).filter(part=>part!=='body').join('.')}: ${item.msg}`))].join('; ');
  }
  return typeof detail==='string'?detail:`Не удалось выполнить запрос (${status}${statusText?` · ${statusText}`:''}).`;
}

export async function api(path, body, method) {
  const response = await fetch(`/api/v1${path}`, {
    method: method || (body === undefined ? 'GET' : 'POST'),
    ...(body === undefined ? {} : {headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)}),
  });
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* Retain the HTTP status. */ }
    throw new Error(`${response.status}: ${apiError(detail,response.status,response.statusText)}`);
  }
  return response.json();
}

export function overridesFor(rows, edits, notes) {
  return rows.filter(row => edits[row.row_id] !== undefined && edits[row.row_id] !== '').map(row => {
    const quantity = edits[row.row_id];
    if (row.status === 'needs_input') throw new Error('Сначала уточните исходные данные.');
    if (!/^\d+(?:\.\d{1,12})?$/.test(quantity)) throw new Error('Количество: неотрицательное число, до 12 знаков после точки.');
    if (!notes[row.row_id]?.trim()) throw new Error(`Укажите причину корректировки ${row.sku}.`);
    return {row_id:row.row_id,quantity,reason:notes[row.row_id].trim()};
  });
}
