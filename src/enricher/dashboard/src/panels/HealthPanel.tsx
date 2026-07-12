import {
  Card,
  CardContent,
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import type { Health } from "../lib/api";
import { fmtAge, fmtDurationMs, fmtTs } from "../lib/format";
import { useApi } from "../lib/useApi";
import { MONO } from "../theme";
import {
  ErrorNote,
  Loading,
  SectionTitle,
  StatTile,
  TileGrid,
  UpdatesPaused,
} from "../components/common";

const INBOX_STATES = ["claimed", "cleaned", "enriched", "sent", "failed"] as const;

function tickStatusColor(status: string): "success" | "error" | "warning" | "default" {
  if (status === "ok") return "success";
  if (status === "error") return "error";
  if (status === "running") return "warning";
  return "default";
}

export function HealthPanel() {
  const { data, loading, error } = useApi<Health>("/api/health", 5000);
  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorNote msg={error} />;
  if (!data) return null;

  const tick = data.latest_tick;

  return (
    <>
      {error && <UpdatesPaused msg={error} />}
      <SectionTitle>Pipeline · inbox by state</SectionTitle>
      <TileGrid>
        {INBOX_STATES.map((s) => (
          <StatTile
            key={s}
            label={s}
            value={data.inbox[s] ?? 0}
            color={s === "failed" && (data.inbox.failed ?? 0) > 0 ? "error.main" : undefined}
          />
        ))}
      </TileGrid>

      <SectionTitle>Backlog & review</SectionTitle>
      <TileGrid>
        <StatTile label="unsent" value={data.unsent} />
        <StatTile
          label="needs human"
          value={data.needs_human}
          color={data.needs_human > 0 ? "warning.main" : undefined}
        />
        <StatTile
          label="failed rows"
          value={data.failed_rows}
          color={data.failed_rows > 0 ? "error.main" : undefined}
        />
      </TileGrid>

      <SectionTitle>Liveness</SectionTitle>
      <Card>
        <CardContent>
          <Stack direction="row" spacing={4} flexWrap="wrap" useFlexGap alignItems="center">
            <div>
              <Typography variant="caption" color="text.secondary">
                last heartbeat
              </Typography>
              <Typography sx={{ fontFamily: MONO }}>
                {fmtTs(data.last_heartbeat_at)}
              </Typography>
            </div>
            <div>
              <Typography variant="caption" color="text.secondary">
                age
              </Typography>
              <Typography sx={{ fontFamily: MONO }}>
                {fmtAge(data.last_heartbeat_age_s)} ago
              </Typography>
            </div>
            {tick && (
              <div>
                <Typography variant="caption" color="text.secondary">
                  latest tick
                </Typography>
                <Stack direction="row" spacing={1} alignItems="center">
                  <Typography sx={{ fontFamily: MONO }}>#{tick.id}</Typography>
                  <Chip size="small" color={tickStatusColor(tick.status)} label={tick.status} />
                  <Typography variant="body2" color="text.secondary">
                    classified {tick.classified} · judged {tick.judged} · sent {tick.sent}
                    {tick.errors > 0 ? ` · errors ${tick.errors}` : ""}
                  </Typography>
                </Stack>
              </div>
            )}
          </Stack>
        </CardContent>
      </Card>

      <SectionTitle>Stage timings · cumulative</SectionTitle>
      <Card>
        {data.stage_timings.length === 0 ? (
          <CardContent>
            <Typography color="text.secondary">No stage timings recorded yet.</Typography>
          </CardContent>
        ) : (
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>stage</TableCell>
                <TableCell align="right">runs</TableCell>
                <TableCell align="right">avg</TableCell>
                <TableCell align="right">items</TableCell>
                <TableCell align="right">retries</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {data.stage_timings.map((t) => (
                <TableRow key={t.stage}>
                  <TableCell>{t.stage}</TableCell>
                  <TableCell align="right">{t.runs}</TableCell>
                  <TableCell align="right">{fmtDurationMs(t.avg_ms)}</TableCell>
                  <TableCell align="right">{t.items ?? 0}</TableCell>
                  <TableCell align="right">{t.retries ?? 0}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </>
  );
}
