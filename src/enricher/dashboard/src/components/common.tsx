import type { ReactNode } from "react";
import { Alert, Box, Card, CardContent, CircularProgress, Typography } from "@mui/material";
import { MONO } from "../theme";

export function Loading() {
  return (
    <Box sx={{ display: "flex", justifyContent: "center", py: 8 }}>
      <CircularProgress />
    </Box>
  );
}

export function ErrorNote({ msg }: { msg: string }) {
  return (
    <Alert severity="error" sx={{ my: 2 }}>
      Failed to load: {msg}. Is the dashboard API running (`job-enricher dashboard`)?
    </Alert>
  );
}

/**
 * Non-blocking banner for a poll failure AFTER the first successful load: the
 * last-known data stays on screen, but we make it clear it's frozen so a
 * sustained outage isn't silently shown as live.
 */
export function UpdatesPaused({ msg }: { msg: string }) {
  return (
    <Alert severity="warning" variant="outlined" sx={{ my: 2 }}>
      Updates paused — can't reach the API ({msg}). Showing the last data received.
    </Alert>
  );
}

export function SectionTitle({ children }: { children: ReactNode }) {
  return (
    <Typography
      variant="overline"
      color="text.secondary"
      sx={{ display: "block", mt: 3, mb: 1, letterSpacing: 1 }}
    >
      {children}
    </Typography>
  );
}

export function StatTile({
  label,
  value,
  color,
}: {
  label: string;
  value: ReactNode;
  color?: string;
}) {
  return (
    <Card>
      <CardContent sx={{ py: 1.5, "&:last-child": { pb: 1.5 } }}>
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ textTransform: "uppercase", letterSpacing: 0.5 }}
        >
          {label}
        </Typography>
        <Typography variant="h4" sx={{ fontFamily: MONO, color, lineHeight: 1.3 }}>
          {value}
        </Typography>
      </CardContent>
    </Card>
  );
}

export function TileGrid({ children }: { children: ReactNode }) {
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fill, minmax(150px, 1fr))",
        gap: 1.5,
      }}
    >
      {children}
    </Box>
  );
}
