// Calling the Sida server's JSON API (one function), with its error type and the address helpers.

import { expertPath } from './model.js';

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

export async function api(path, { method = 'GET', body, form } = {}) {
  const options = { method, headers: {} };
  if (form !== undefined) {
    options.body = form; // FormData: the browser sets the multipart Content-Type
  } else if (body !== undefined) {
    options.headers['Content-Type'] = 'application/json';
    options.body = JSON.stringify(body);
  }
  let response;
  try { response = await fetch(path, options); }
  catch { throw new ApiError(0, 'Sida 서버에 연결할 수 없습니다. 서버가 켜져 있는지 확인해 주세요.'); }
  let data = null;
  try { data = await response.json(); } catch { /* empty body */ }
  if (!response.ok) {
    const detail = typeof data?.detail === 'string' ? data.detail : `요청이 실패했습니다 (${response.status})`;
    throw new ApiError(response.status, detail);
  }
  return data;
}

export const projectApi = (name) => `/api/projects/${encodeURIComponent(name)}`;
export const expertUrl = (name, agent, chat = '') => (chat ? expertPath(name, agent, 'chat', chat) : expertPath(name, agent));
export const sleep = (ms) => new Promise((resolve) => { setTimeout(resolve, ms); });
