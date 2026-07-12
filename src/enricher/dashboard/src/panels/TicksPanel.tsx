import { Fragment, useState } from "react";
import {
  Box,
  Card,
  Chip,
  Collapse,
  IconButton,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import KeyboardArrowDownIcon from "@mui/icons-material/KeyboardArrowDown";
import KeyboardArrowUpIcon from "@mui/icons-material/KeyboardArrowUp";
import type { TickView } from "../lib/api";
import { fmtDurationMs, fmtTs, tickDuration } from "../lib/format";
import { useApi } from "../lib/useApi";
import { MONO } from "../theme";
import { ErrorNote, Loading, SectionTitle, UpdatesPaused } from "../components/common";

function statusColor(status: string): "success" | "error" | "warning" | "default" {
  if (status === "ok") return "success";
  if (status === "error") return "error";
  if (status === "running") return "warning";
  return "default";
}

function TickRow({ tick }: { tick: TickView }) {
  const [open, setOpen] = useState(false);
  return (
    <Fragment>
      <TableRow hover sx={{ "& > *": { borderBottom: "unset" } }}>
        <TableCell padding="checkbox">
          <IconButton size="small" onClick={() => setOpen((o) => !o)}>
            {open ? <KeyboardArrowUpIcon /> : <KeyboardArrowDownIcon />}
          </IconButton>
        </TableCell>
        <TableCell sx={{ fontFamily: MONO }}>#{tick.id}</TableCell>
        <TableCell>
          <Stack direction="row" spacing={1} alignItems="center">
            <Chip size="small" color={statusColor(tick.status)} label={tick.status} />
            {tick.drift_suspected && <Chip size="small" color="error" label="drift" />}
          </Stack>
        </TableCell>
        <TableCell>{fmtTs(tick.started_at)}</TableCell>
        <TableCell align="right" sx={{ fontFamily: MONO }}>
          {tickDuration(tick.started_at, tick.ended_at)}
        </TableCell>
        <TableCell align="right">{tick.claimed}</TableCell>
        <TableCell align="right">{tick.classified}</TableCell>
        <TableCell align="right">{tick.judged}</TableCell>
        <TableCell align="right">{tick.sent}</TableCell>
        <TableCell align="right">{tick.nulled_facets}</TableCell>
        <TableCell align="right" sx={{ color: tick.errors > 0 ? "error.main" : undefined }}>
          {tick.errors}
        </TableCell>
      </TableRow>
      <TableRow>
        <TableCell sx={{ py: 0 }} colSpan={11}>
          <Collapse in={open} timeout="auto" unmountOnExit>
            <Box sx={{ py: 2 }}>
              <Typography variant="subtitle2" gutterBottom>
                Stage timings
              </Typography>
              {tick.stage_timings.length === 0 ? (
                <Typography color="text.secondary" variant="body2">
                  No stage timings for this tick.
                </Typography>
              ) : (
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>stage</TableCell>
                      <TableCell align="right">duration</TableCell>
                      <TableCell align="right">items</TableCell>
                      <TableCell align="right">retries</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {tick.stage_timings.map((s, i) => (
                      <TableRow key={`${s.stage}-${i}`}>
                        <TableCell>{s.stage}</TableCell>
                        <TableCell align="right">{fmtDurationMs(s.duration_ms)}</TableCell>
                        <TableCell align="right">{s.item_count}</TableCell>
                        <TableCell align="right">{s.retry_count}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
              {tick.notes && (
                <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
                  notes: {tick.notes}
                </Typography>
              )}
            </Box>
          </Collapse>
        </TableCell>
      </TableRow>
    </Fragment>
  );
}

export function TicksPanel() {
  const { data, loading, error } = useApi<{ ticks: TickView[] }>("/api/ticks?limit=50", 20000);
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorNote msg={error} />;
  if (!data) return null;

  return (
    <>
      {error && <UpdatesPaused msg={error} />}
      <SectionTitle>Recent ticks</SectionTitle>
      <Card>
        {data.ticks.length === 0 ? (
          <Box sx={{ p: 3 }}>
            <Typography color="text.secondary">No ticks recorded yet.</Typography>
          </Box>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell />
                <TableCell>tick</TableCell>
                <TableCell>status</TableCell>
                <TableCell>started</TableCell>
                <TableCell align="right">duration</TableCell>
                <TableCell align="right">claimed</TableCell>
                <TableCell align="right">classified</TableCell>
                <TableCell align="right">judged</TableCell>
                <TableCell align="right">sent</TableCell>
                <TableCell align="right">nulled</TableCell>
                <TableCell align="right">errors</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.ticks.map((t) => (
                <TickRow key={t.id} tick={t} />
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </>
  );
}
