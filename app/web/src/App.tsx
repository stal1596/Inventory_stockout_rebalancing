import { useEffect, useState } from "react";
import { Link, Route, Routes } from "react-router-dom";
import { Shell } from "./components/Shell";
import { StoreProvider } from "./store";
import { ControlTower } from "./pages/ControlTower";
import { Risk } from "./pages/Risk";
import { Simulate } from "./pages/Simulate";
import { Prescribe } from "./pages/Prescribe";
import { Policy } from "./pages/Policy";
import { Inventory } from "./pages/Inventory";
import { Network } from "./pages/Network";
import { Data } from "./pages/Data";
import { Evidence } from "./pages/Evidence";
import { Quality } from "./pages/Quality";
import { Backtests } from "./pages/Backtests";
import { api } from "./lib/api";
import { Card, Empty, Spinner } from "./components/ui";

function NotFound() {
  return (
    <Card title="Page not found">
      <Empty>
        <div className="text-center">
          <p>There is no page at this address.</p>
          <Link to="/" className="inline-block mt-3 rounded-md px-3 py-1.5 text-[13px]"
                style={{ background: "var(--series-1)", color: "#fff" }}>
            Back to the Control Tower
          </Link>
        </div>
      </Empty>
    </Card>
  );
}

export function App() {
  const [health, setHealth] = useState<{ as_of?: string; c_index?: number } | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    // The API pays a ~50s warm-up on first boot; retry rather than showing an
    // error for what is really just a cold start.
    let cancelled = false;
    const attempt = (remaining: number) => {
      api
        .health()
        .then((h) => !cancelled && setHealth(h as any))
        .catch(() => {
          if (cancelled) return;
          if (remaining <= 0) setFailed(true);
          else setTimeout(() => attempt(remaining - 1), 3000);
        });
    };
    attempt(40);
    return () => {
      cancelled = true;
    };
  }, []);

  if (failed) {
    return (
      <div className="h-full grid place-items-center px-8 text-center">
        <div>
          <p className="text-[15px] font-medium mb-2">The API is not responding.</p>
          <p className="text-[13px]" style={{ color: "var(--text-secondary)" }}>
            Start it with <code>uv run uvicorn app.api.main:app</code> — it loads the
            extract and fits the model once, which takes about a minute.
          </p>
        </div>
      </div>
    );
  }

  if (!health) {
    return (
      <div className="h-full grid place-items-center">
        <div className="text-center">
          <Spinner label="Loading the extract and fitting the model…" />
          <p className="text-[12px] mt-2" style={{ color: "var(--text-muted)" }}>
            One-time warm-up, about a minute.
          </p>
        </div>
      </div>
    );
  }

  return (
    <StoreProvider>
      <Shell asOf={health.as_of} cIndex={health.c_index}>
        <Routes>
          <Route path="/" element={<ControlTower />} />
          <Route path="/inventory" element={<Inventory />} />
          <Route path="/risk" element={<Risk />} />
          <Route path="/simulate" element={<Simulate />} />
          <Route path="/prescribe" element={<Prescribe />} />
          <Route path="/policy" element={<Policy />} />
          <Route path="/network" element={<Network />} />
          <Route path="/data" element={<Data />} />
          <Route path="/evidence" element={<Evidence />} />
          <Route path="/quality" element={<Quality />} />
          <Route path="/backtests" element={<Backtests />} />
          {/* A mistyped URL used to render the dashboard, which made it
              indistinguishable from the homepage. */}
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Shell>
    </StoreProvider>
  );
}
