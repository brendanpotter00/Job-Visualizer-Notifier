import type { Job, GreenhouseConfig, LeverConfig } from '../types';

/**
 * Greenhouse job board API response
 * @see https://developers.greenhouse.io/job-board.html
 */
export interface GreenhouseJobResponse {
  id: number;
  title: string;
  absolute_url: string;
  location: {
    name: string;
  };
  departments: Array<{
    id: number;
    name: string;
  }>;
  offices: Array<{
    id: number;
    name: string;
    location: string;
  }>;
  updated_at: string; // ISO timestamp
  first_published?: string; // ISO timestamp - when job was first posted
  metadata?: Array<{
    id: number;
    name: string;
    value: string;
  }>;
}

export interface GreenhouseAPIResponse {
  jobs: GreenhouseJobResponse[];
}

/**
 * Lever job posting API response
 * @see https://github.com/lever/postings-api
 */
export interface LeverJobResponse {
  id: string;
  text: string; // Job title
  hostedUrl: string;
  categories: {
    commitment?: string; // Full-time, Part-time, etc.
    department?: string;
    location?: string;
    team?: string;
  };
  createdAt: number; // Unix timestamp (milliseconds)
  tags?: string[];
  workplaceType?: 'remote' | 'onsite' | 'unspecified';
}

/**
 * Standard API client interface.
 * All ATS clients implement this interface.
 */
export interface JobAPIClient {
  /**
   * Fetch jobs for a company.
   * @param config - Company-specific configuration
   * @param options - Fetch options
   * @returns Normalized jobs array
   */
  fetchJobs(
    config: GreenhouseConfig | LeverConfig,
    options?: FetchJobsOptions
  ): Promise<FetchJobsResult>;
}

export interface FetchJobsOptions {
  /** Filter to jobs created after this timestamp */
  since?: string;

  /** Maximum number of jobs to fetch */
  limit?: number;

  /** AbortSignal for request cancellation */
  signal?: AbortSignal;
}

export interface FetchJobsResult {
  jobs: Job[];
  metadata: {
    totalCount: number;
    softwareCount: number;
    fetchedAt: string;
  };
}

/**
 * API error types
 */
export class APIError extends Error {
  constructor(
    message: string,
    public statusCode?: number,
    public atsProvider?: 'greenhouse' | 'lever',
    public retryable: boolean = false
  ) {
    super(message);
    this.name = 'APIError';
  }
}
