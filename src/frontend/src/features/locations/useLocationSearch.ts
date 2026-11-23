import { useEffect, useState } from 'react';
import { useSearchLocationsQuery, type LocationSearchResult } from './locationsApi.ts';
import { extractErrorMessage } from '../../lib/errors.ts';

/** Debounce delay (ms) before a keystroke triggers a location search. */
export const LOCATION_SEARCH_DEBOUNCE_MS = 300;
/** Minimum query length before hitting the search endpoint. */
export const LOCATION_SEARCH_MIN_QUERY_LEN = 2;

export interface LocationSearchOptions {
  /** Only return locations that currently have at least one OPEN job. */
  openOnly?: boolean;
  /** Max suggestions to request from the server. */
  limit?: number;
}

export interface LocationSearchState {
  /** The latest results for the debounced query (undefined before the first). */
  results: LocationSearchResult[] | undefined;
  isFetching: boolean;
  /** A failed search's message, or null. Never silent (see `noOptionsText`). */
  errorMessage: string | null;
  /**
   * What an empty suggestion list means right now: keep typing, the request
   * failed, or nothing matched. Three different reasons, three texts.
   */
  noOptionsText: string;
}

/**
 * The debounced public location search (`GET /api/locations/search`) behind
 * every place picker: the filter bars' `AsyncMultiSelectAutocomplete`, the
 * Saved Filters page, and the onboarding location question. One place owns
 * the debounce, the minimum length and the three "no suggestions" reasons, so
 * the pickers cannot drift apart.
 */
export function useLocationSearch(
  inputValue: string,
  { openOnly, limit }: LocationSearchOptions = {}
): LocationSearchState {
  const [debouncedQuery, setDebouncedQuery] = useState('');

  // Debounce the raw input into the query that drives the request.
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedQuery(inputValue), LOCATION_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [inputValue]);

  const trimmedQuery = debouncedQuery.trim();
  const belowMinLength = trimmedQuery.length < LOCATION_SEARCH_MIN_QUERY_LEN;
  const { data, isFetching, isError, error } = useSearchLocationsQuery(
    { q: trimmedQuery, openOnly, limit },
    { skip: belowMinLength }
  );

  // Distinguish the three "no suggestions" reasons so the dropdown never reads
  // as a bare empty void (the original silent-failure bug): too-short query,
  // a failed request, or a genuinely empty result set.
  const errorMessage = isError ? extractErrorMessage(error, 'Location search failed') : null;
  const noOptionsText = belowMinLength
    ? `Type at least ${LOCATION_SEARCH_MIN_QUERY_LEN} characters to search`
    : (errorMessage ?? 'No matching locations');

  return { results: data, isFetching, errorMessage, noOptionsText };
}
