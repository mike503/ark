const API_BASE_URL = '/api';

async function apiRequest(method, path, data, params) {
  const cleanPath = String(path).replace(/^\/+/, '');
  const query = params && Object.keys(params).length
    ? `?${new URLSearchParams(params)}`
    : '';
  const response = await fetch(`${API_BASE_URL}/${cleanPath}${query}`, {
    method,
    headers: { 'content-type': 'application/json' },
    body: data == null ? undefined : JSON.stringify(data),
  });
  if (!response.ok) {
    let details = {};
    try {
      details = await response.json();
    } catch {
      // Response did not include JSON details.
    }
    const error = new Error(details.message || details.error || `API request failed: ${response.status}`);
    error.data = details;
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}

export const api_get = (path, params = {}) => apiRequest('GET', path, null, params);
export const api_post = (path, data = {}) => apiRequest('POST', path, data);
export const api_put = (path, data = {}) => apiRequest('PUT', path, data);
export const api_patch = (path, data = {}) => apiRequest('PATCH', path, data);
export const api_delete = (path, data = null) => apiRequest('DELETE', path, data);

if (typeof window !== 'undefined') {
  Object.assign(window, { api_get, api_post, api_put, api_patch, api_delete });
}
