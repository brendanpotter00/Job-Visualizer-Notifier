import { useMemo, useState } from "react";
import {
  AppBar,
  Box,
  Chip,
  CssBaseline,
  IconButton,
  Tab,
  Tabs,
  ThemeProvider,
  Toolbar,
  Tooltip,
  Typography,
  type PaletteMode,
} from "@mui/material";
import DarkModeIcon from "@mui/icons-material/DarkModeOutlined";
import LightModeIcon from "@mui/icons-material/LightModeOutlined";
import type { Health } from "./lib/api";
import { fmtAge } from "./lib/format";
import { useApi } from "./lib/useApi";
import { makeTheme } from "./theme";
import { HealthPanel } from "./panels/HealthPanel";
import { TicksPanel } from "./panels/TicksPanel";
import { JobsPanel } from "./panels/JobsPanel";
import { KnobsPanel } from "./panels/KnobsPanel";

const TABS = ["Health", "Ticks", "Jobs", "Knobs"] as const;
const STALE_AFTER_S = 900; // 15 min without a heartbeat -> "stale"

function initialMode(): PaletteMode {
  return localStorage.getItem("je-dash-theme") === "light" ? "light" : "dark";
}

export function App() {
  const [mode, setMode] = useState<PaletteMode>(initialMode);
  const [tab, setTab] = useState(0);
  const theme = useMemo(() => makeTheme(mode), [mode]);
  const { data: health, error: healthError } = useApi<Health>("/api/health", 5000);

  // A failed poll leaves `useApi`'s last-good `data` in place, so deriving the
  // chip from `data` alone would show green "alive" straight through a backend
  // outage. When the poll is erroring the API is unreachable — say so explicitly
  // instead of trusting the frozen heartbeat age.
  const disconnected = healthError != null;
  const age = health?.last_heartbeat_age_s ?? null;
  const live = !disconnected && age != null && age < STALE_AFTER_S;

  function toggleMode() {
    setMode((m) => {
      const next: PaletteMode = m === "dark" ? "light" : "dark";
      localStorage.setItem("je-dash-theme", next);
      return next;
    });
  }

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <AppBar position="sticky" color="default" enableColorOnDark>
        <Toolbar sx={{ gap: 1.5 }}>
          <Typography variant="h6" sx={{ fontWeight: 700 }}>
            job-enricher
          </Typography>
          <Typography variant="body2" color="text.secondary">
            dashboard
          </Typography>
          <Box sx={{ flexGrow: 1 }} />
          <Chip
            size="small"
            color={live ? "success" : "error"}
            variant={live ? "filled" : "outlined"}
            label={
              disconnected
                ? "disconnected"
                : age == null
                  ? "no heartbeat"
                  : live
                    ? `alive · ${fmtAge(age)} ago`
                    : `stale · ${fmtAge(age)} ago`
            }
          />
          <Tooltip title={`Switch to ${mode === "dark" ? "light" : "dark"} mode`}>
            <IconButton onClick={toggleMode} size="small">
              {mode === "dark" ? <LightModeIcon /> : <DarkModeIcon />}
            </IconButton>
          </Tooltip>
        </Toolbar>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ px: 2 }}>
          {TABS.map((t) => (
            <Tab key={t} label={t} />
          ))}
        </Tabs>
      </AppBar>
      <Box sx={{ p: 3, maxWidth: 1200, mx: "auto" }}>
        {tab === 0 && <HealthPanel />}
        {tab === 1 && <TicksPanel />}
        {tab === 2 && <JobsPanel />}
        {tab === 3 && <KnobsPanel />}
      </Box>
    </ThemeProvider>
  );
}
