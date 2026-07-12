import { createTheme, type PaletteMode, type Theme } from "@mui/material";

// Dark/light theme echoing boop's debug dashboard: near-black surfaces in dark,
// warm off-white in light, a sky-blue accent, and a mono font for numbers/ids.
export function makeTheme(mode: PaletteMode): Theme {
  const dark = mode === "dark";
  return createTheme({
    palette: {
      mode,
      primary: { main: dark ? "#4f9cf9" : "#1f6feb" },
      success: { main: dark ? "#3fb950" : "#1a7f37" },
      warning: { main: dark ? "#d29922" : "#9a6700" },
      error: { main: dark ? "#f85149" : "#cf222e" },
      background: dark
        ? { default: "#101012", paper: "#18181b" }
        : { default: "#f7f7f5", paper: "#ffffff" },
      divider: dark ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.10)",
    },
    shape: { borderRadius: 10 },
    typography: {
      fontFamily:
        'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
    },
    components: {
      MuiCard: { defaultProps: { variant: "outlined" } },
      MuiPaper: { defaultProps: { elevation: 0 } },
    },
  });
}

export const MONO =
  'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, monospace';
