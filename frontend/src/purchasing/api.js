export async function api(path, body, method) {
  const response = await fetch(`/api/v1${path}`, {
    method: method || (body === undefined ? 'GET' : 'POST'),
    ...(body === undefined ? {} : {headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)}),
  });
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { /* Retain the HTTP status. */ }
    const message = Array.isArray(detail) ? detail.map(item => `${(item.loc||[]).join('.')}: ${item.msg}`).join('; ') : detail;
    throw new Error(`${response.status}: ${message||response.statusText}`);
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
