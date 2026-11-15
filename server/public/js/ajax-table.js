export function createAjaxTable({
  table,
  url,
  renderRow,
  filters = {},
  pageSize = 50,
  fetchImpl = fetch,
} = {}) {
  const element = typeof table === 'string' ? document.querySelector(table) : table;
  if (!element || !url || typeof renderRow !== 'function') {
    throw new Error('createAjaxTable requires table, url, and renderRow');
  }
  let page = Number(new URLSearchParams(location.search).get('page')) || 1;

  const load = async () => {
    const values = Object.fromEntries(Object.entries(filters).map(([key, selector]) => [
      key,
      document.querySelector(selector)?.value || '',
    ]));
    const params = new URLSearchParams({ ...values, page, pageSize });
    history.replaceState(null, '', `${location.pathname}?${params}`);
    const response = await fetchImpl(`${url}?${params}`);
    if (!response.ok) throw new Error(`Table request failed: ${response.status}`);
    const payload = await response.json();
    const rows = payload.rows || payload.items || [];
    element.tBodies[0].innerHTML = rows.map(renderRow).join('');
    element.closest('.card')?.querySelector('[data-ajax-table-summary]')
      ?.replaceChildren(document.createTextNode(`${payload.total ?? rows.length} results`));
    return payload;
  };

  for (const selector of Object.values(filters)) {
    document.querySelector(selector)?.addEventListener('change', () => {
      page = 1;
      load();
    });
  }
  return { load, setPage(value) { page = value; return load(); } };
}

if (typeof window !== 'undefined') window.createAjaxTable = createAjaxTable;
