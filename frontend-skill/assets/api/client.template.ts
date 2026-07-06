import { createApiClient } from '{{API_CLIENT_PACKAGE}}';
import type { AxiosInstance, AxiosRequestConfig, AxiosResponse } from 'axios';

import { envs } from '@shared/config';

import { authService } from './services/auth.service';
import { authTokensStorage } from './tokens';

const API_CONFIG = {
  timeout: 60_000,
  retryAttempts: 3,
};

export const apiClient: AxiosInstance = createApiClient({
  baseURL: envs.API_BASE_URL,
  authStorage: authTokensStorage,
  authService: authService,
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: API_CONFIG.timeout,
  retry: { retries: API_CONFIG.retryAttempts },
});

const createRequest =
  (baseURL?: string, timeout?: number) =>
  async <T = unknown>(
    config: AxiosRequestConfig,
    options?: AxiosRequestConfig
  ): Promise<T> => {
    const response: AxiosResponse<T> = await apiClient.request({
      baseURL,
      timeout,
      ...config,
      ...options,
    });

    return response.data;
  };

export const primaryApiRequest = createRequest();

export const secondaryApiRequest = createRequest(envs.API_SECONDARY_BASE_URL);

export const filesApiRequest = createRequest(envs.API_FILES_BASE_URL, 0);
