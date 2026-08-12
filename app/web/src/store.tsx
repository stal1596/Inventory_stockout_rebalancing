import { createContext, useCallback, useContext, useMemo, type ReactNode } from "react";
import { useLocation, useNavigate, useSearchParams } from "react-router-dom";

/**
 * The selected position is application state, not page state.
 *
 * This is the whole "one workflow, not four dashboards" requirement, and it is a
 * single decision made here: a SKU chosen on the risk table is still selected on
 * the simulator and the recommendation, so a user never re-finds the thing they
 * were already looking at. Every page that acts on a position reads it from
 * here, and `focus()` is the one way to change it.
 *
 * It lives in the QUERY STRING rather than in React state. Held in memory it
 * survived navigation but not a refresh, and nothing was shareable -- a planner
 * could not send a colleague the view they were looking at, and the browser Back
 * button could not undo a filter change. The URL fixes all three at once, and
 * react-router already ships `useSearchParams`, so it costs no dependency.
 */

export interface Selection {
  storeId: string;
  skuUid: string;
}

export interface Filters {
  band?: string;
  storeId?: string;
  category?: string;
  minProbability?: number;
  coverage?: string;
  search?: string;
  /** Which p_stockout_{h}d column the probability filter and the table read. */
  horizon?: number;
}

interface StoreValue {
  selection: Selection | null;
  filters: Filters;
  /** Merges into the current filters. Pass `undefined` for a key to clear it. */
  setFilters: (next: Filters) => void;
  clearFilters: () => void;
  /** Select a position and go to a stage of the journey. */
  focus: (selection: Selection, stage?: Stage) => void;
  clearSelection: () => void;
}

export type Stage = "risk" | "simulate" | "prescribe" | "policy";

const STAGE_PATH: Record<Stage, string> = {
  risk: "/risk",
  simulate: "/simulate",
  prescribe: "/prescribe",
  policy: "/policy",
};

export const DEFAULT_HORIZON = 14;

/** Query-string keys. Short, because these end up in a shared link. */
const KEYS = {
  store: "store",
  sku: "sku",
  band: "band",
  storeId: "at",
  category: "cat",
  minProbability: "p",
  coverage: "cover",
  search: "q",
  horizon: "h",
} as const;

const FILTER_KEYS = [
  KEYS.band, KEYS.storeId, KEYS.category,
  KEYS.minProbability, KEYS.coverage, KEYS.search, KEYS.horizon,
];

const StoreContext = createContext<StoreValue | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();

  const selection = useMemo<Selection | null>(() => {
    const storeId = params.get(KEYS.store);
    const skuUid = params.get(KEYS.sku);
    return storeId && skuUid ? { storeId, skuUid } : null;
  }, [params]);

  const filters = useMemo<Filters>(() => {
    const probability = params.get(KEYS.minProbability);
    const horizon = params.get(KEYS.horizon);
    return {
      band: params.get(KEYS.band) ?? undefined,
      storeId: params.get(KEYS.storeId) ?? undefined,
      category: params.get(KEYS.category) ?? undefined,
      coverage: params.get(KEYS.coverage) ?? undefined,
      search: params.get(KEYS.search) ?? undefined,
      minProbability: probability === null ? undefined : Number(probability),
      horizon: horizon === null ? undefined : Number(horizon),
    };
  }, [params]);

  // Every writer goes through this, so the selection and the filters can never
  // clobber each other -- each only ever touches its own keys.
  const write = useCallback(
    (mutate: (next: URLSearchParams) => void) => {
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          mutate(next);
          return next;
        },
        { replace: true },
      );
    },
    [setParams],
  );

  const value = useMemo<StoreValue>(() => {
    const setOrDelete = (next: URLSearchParams, key: string, value: unknown) => {
      if (value === undefined || value === null || value === "") next.delete(key);
      else next.set(key, String(value));
    };

    return {
      selection,
      filters,
      // Merge, never replace. Replacing is what let an alert drill-through wipe
      // the store and category a user had already chosen.
      setFilters: (patch) =>
        write((next) => {
          if ("band" in patch) setOrDelete(next, KEYS.band, patch.band);
          if ("storeId" in patch) setOrDelete(next, KEYS.storeId, patch.storeId);
          if ("category" in patch) setOrDelete(next, KEYS.category, patch.category);
          if ("coverage" in patch) setOrDelete(next, KEYS.coverage, patch.coverage);
          if ("search" in patch) setOrDelete(next, KEYS.search, patch.search);
          if ("minProbability" in patch)
            setOrDelete(next, KEYS.minProbability, patch.minProbability);
          if ("horizon" in patch) setOrDelete(next, KEYS.horizon, patch.horizon);
        }),
      clearFilters: () => write((next) => FILTER_KEYS.forEach((key) => next.delete(key))),
      focus: (target, stage) => {
        const search = new URLSearchParams(params);
        search.set(KEYS.store, target.storeId);
        search.set(KEYS.sku, target.skuUid);
        // One navigation carries both the selection and the destination, so the
        // stage never lands before the selection it is meant to show.
        navigate({ pathname: stage ? STAGE_PATH[stage] : location.pathname, search: `?${search}` });
      },
      clearSelection: () =>
        write((next) => {
          next.delete(KEYS.store);
          next.delete(KEYS.sku);
        }),
    };
  }, [selection, filters, params, navigate, write, location.pathname]);

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore() {
  const context = useContext(StoreContext);
  if (!context) throw new Error("useStore must be used inside StoreProvider");
  return context;
}
