export type ApiResponse<T> = {
  data: T;
  meta?: { total: number; limit: number; offset: number };
};

export type ApiError = { detail: string };
