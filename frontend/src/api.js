const configuredBase = import.meta.env.VITE_API_BASE_URL;

// 未配置时默认本地后端；显式配置为空字符串时走同源（Docker/Nginx 反向代理）
export const API_BASE = (
  configuredBase === undefined ? 'http://127.0.0.1:8000' : configuredBase
).replace(/\/$/, '');

export function getToken() {
  return localStorage.getItem('token');
}

export function getUsername() {
  return localStorage.getItem('username') || '';
}

export function setAuth(token, username) {
  localStorage.setItem('token', token);
  localStorage.setItem('username', username);
}

export function clearAuth() {
  localStorage.removeItem('token');
  localStorage.removeItem('username');
}

export function redirectToLogin() {
  clearAuth();
  if (window.location.pathname !== '/login') {
    window.location.href = '/login';
  }
}

export async function apiFetch(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (response.status === 401) {
    redirectToLogin();
    throw new Error('UNAUTHORIZED');
  }
  return response;
}

export async function apiJson(path, options = {}) {
  const response = await apiFetch(path, options);
  if (!response.ok) {
    let detail = `请求失败（${response.status}）`;
    try {
      const data = await response.json();
      if (data.detail) detail = data.detail;
    } catch {
      // 忽略响应体解析失败
    }
    throw new Error(detail);
  }
  return response.json();
}
