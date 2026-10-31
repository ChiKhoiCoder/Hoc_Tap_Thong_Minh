import axios from 'axios'

/** API client dùng chung cho các trang React sẽ được chuyển đổi dần. */
export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? '',
  headers: { Accept: 'application/json' },
  withCredentials: true,
  timeout: 15_000
})
