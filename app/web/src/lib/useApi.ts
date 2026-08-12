import { useCallback, useEffect, useRef, useState } from "react";

/**
 * One fetch, three honest states.
 *
 * Every page used to do `.catch(() => {})` and then `if (!data) return <Spinner/>`,
 * which meant a 500 and a slow response looked identical -- and looked identical
 * forever, because nothing ever set the data. Six of seven pages could only spin.
 *
 * Two properties are load-bearing:
 *
 * **A failed refetch clears the data.** The alternative is worse than a blank
 * page: on the simulator, a failed re-run left the previous numbers on screen
 * while the sliders showed the new assumptions, so the user read results that did
 * not correspond to the visible inputs and nothing said so.
 *
 * **Responses are sequenced, not just cancelled.** A stale reply that arrives
 * after a newer one is dropped, so dragging a slider cannot end on an old answer.
 */
export interface ApiState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refetch: () => void;
}

export function useApi<T>(fetcher: () => Promise<T>, deps: unknown[]): ApiState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  const request = useRef(0);

  // The fetcher is a fresh closure every render; `deps` is what decides identity,
  // exactly as the caller intends.
  const run = useRef(fetcher);
  run.current = fetcher;

  useEffect(() => {
    const id = ++request.current;
    setLoading(true);
    run
      .current()
      .then((value) => {
        if (id !== request.current) return;
        setData(value);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (id !== request.current) return;
        setData(null);
        setError(cause instanceof Error ? cause.message : String(cause));
      })
      .finally(() => {
        if (id === request.current) setLoading(false);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const refetch = useCallback(() => setNonce((n) => n + 1), []);
  return { data, error, loading, refetch };
}

/**
 * Debounce a fast-changing value -- slider drags, search boxes.
 *
 * The simulator fired one POST per `onChange` of a range input, at up to 20,000
 * paths per request. Debouncing the knobs rather than throttling the request
 * keeps the last position the user actually chose.
 */
export function useDebounced<T>(value: T, delay = 250): T {
  const [settled, setSettled] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setSettled(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);
  return settled;
}
