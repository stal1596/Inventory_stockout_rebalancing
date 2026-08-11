import { createContext, useContext, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router-dom";

/**
 * The selected position is application state, not page state.
 *
 * This is the whole "one workflow, not four dashboards" requirement, and it is a
 * single decision made here: a SKU chosen on the risk table is still selected on
 * the simulator and the recommendation, so a user never re-finds the thing they
 * were already looking at. Every page that acts on a position reads it from
 * here, and `focus()` is the one way to change it.
 */

export interface Selection {
  storeId: string;
  skuUid: string;
}

interface Filters {
  band?: string;
  storeId?: string;
  category?: string;
  minProbability?: number;
  coverage?: string;
  search?: string;
}

interface StoreValue {
  selection: Selection | null;
  filters: Filters;
  setFilters: (next: Filters) => void;
  /** Select a position and go to a stage of the journey. */
  focus: (selection: Selection, stage?: Stage) => void;
  clearSelection: () => void;
}

export type Stage = "risk" | "simulate" | "prescribe";

const STAGE_PATH: Record<Stage, string> = {
  risk: "/risk",
  simulate: "/simulate",
  prescribe: "/prescribe",
};

const StoreContext = createContext<StoreValue | null>(null);

export function StoreProvider({ children }: { children: ReactNode }) {
  const [selection, setSelection] = useState<Selection | null>(null);
  const [filters, setFilters] = useState<Filters>({});
  const navigate = useNavigate();

  const value = useMemo<StoreValue>(
    () => ({
      selection,
      filters,
      setFilters,
      focus: (next, stage) => {
        setSelection(next);
        if (stage) navigate(STAGE_PATH[stage]);
      },
      clearSelection: () => setSelection(null),
    }),
    [selection, filters, navigate],
  );

  return <StoreContext.Provider value={value}>{children}</StoreContext.Provider>;
}

export function useStore() {
  const context = useContext(StoreContext);
  if (!context) throw new Error("useStore must be used inside StoreProvider");
  return context;
}
