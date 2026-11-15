export function formatBytes(bytes) {
  if (!bytes) return '0 B';
  const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(2).replace(/\.?0+$/, '')}\u00a0${units[index]}`;
}

export function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"]/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
  })[character]);
}

function parseDateInput(input) {
  if (input == null || input === '') return null;
  if (typeof input === 'number') return new Date(input * 1000);
  if (input instanceof Date) return input;
  const value = String(input).trim();
  return new Date(/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}/.test(value)
    && !/(?:Z|[+-]\d{2}:?\d{2})$/.test(value)
    ? `${value.replace(' ', 'T')}Z`
    : value);
}

export function formatDatetime(input, timeZone = null) {
  const date = parseDateInput(input);
  if (!date || Number.isNaN(date.getTime())) return input ? 'INVALID DATE' : '-';
  const zone = timeZone || globalThis.USER_TIMEZONE || 'America/Los_Angeles';
  return new Intl.DateTimeFormat('en-CA', {
    timeZone: zone,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: 'numeric',
    minute: '2-digit',
    timeZoneName: 'short',
  }).format(date);
}

export function formatAgeCompact(input) {
  const date = parseDateInput(input);
  if (!date || Number.isNaN(date.getTime())) return '—';
  const seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (seconds < 60) return 'now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  if (seconds < 2629746) return `${Math.floor(seconds / 86400)}d`;
  if (seconds < 31556952) return `${Math.floor(seconds / 2629746)}mo`;
  return `${Math.floor(seconds / 31556952)}y`;
}

export function showBanner(containerId, type = 'success', message = '', autoHideMs = 5000) {
  const container = document.getElementById(containerId)
    || document.querySelector('.page-body .container-xl');
  if (!container) return;
  const alert = document.createElement('div');
  alert.className = `alert alert-${type} alert-dismissible`;
  alert.innerHTML = `<div>${escapeHtml(message)}</div><button class="btn-close" data-bs-dismiss="alert"></button>`;
  container.replaceChildren(alert);
  if (autoHideMs > 0) setTimeout(() => alert.remove(), autoHideMs);
}

if (typeof window !== 'undefined') {
  Object.assign(window, { formatBytes, escapeHtml, formatDatetime, formatAgeCompact, showBanner });
}
