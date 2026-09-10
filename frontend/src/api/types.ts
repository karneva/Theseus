export interface ApiResponse<T> {
  isSuccess: boolean;
  code: string;
  message: string;
  result: T;
}

export interface PageResponse<T> {
  content: T[];
  number?: number;
  page?: number;
  size: number;
  totalElements: number;
  totalPages: number;
}
