import { useEffect, useState, type ReactNode } from "react";
import {
  Box,
  Card,
  CardContent,
  Chip,
  FormControlLabel,
  MenuItem,
  Slider,
  Snackbar,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import type { KnobValue, KnobsResponse } from "../lib/api";
import { postKnob } from "../lib/api";
import { useApi } from "../lib/useApi";
import { ErrorNote, Loading, SectionTitle, UpdatesPaused } from "../components/common";

type Snapshot = KnobsResponse["snapshot"];

function Labeled({ label, children }: { label: string; children: ReactNode }) {
  return (
    <Box sx={{ mb: 2.5 }}>
      <Typography variant="body2" sx={{ mb: 0.5 }}>
        {label}
      </Typography>
      {children}
    </Box>
  );
}

export function KnobsPanel() {
  const { data, loading, error, refresh } = useApi<KnobsResponse>("/api/knobs");
  const [snap, setSnap] = useState<Snapshot | null>(null);
  // The last COMMITTED server snapshot — the authoritative rollback source.
  // Updated wherever server truth is adopted (mount/refresh GET + save success),
  // NOT frozen at mount: knobs `useApi` doesn't poll, so `data` only advances on
  // an explicit refresh, and a rollback must target the last commit — not the
  // stale mount value — or a failed save would display a wrong committed value.
  const [committed, setCommitted] = useState<Snapshot | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  useEffect(() => {
    if (data) {
      setSnap(data.snapshot);
      setCommitted(data.snapshot);
    }
  }, [data]);

  if (loading && !data) return <Loading />;
  if (error && !data) return <ErrorNote msg={error} />;
  if (!data || !snap) return null;
  const meta = data.meta;

  async function save(key: keyof Snapshot, value: KnobValue) {
    try {
      const res = await postKnob(key, value);
      // The POST response is authoritative (may be clamped by the server). Adopt
      // it as both the live snapshot AND the last-committed rollback source.
      setSnap(res.snapshot);
      setCommitted(res.snapshot);
      // A successful POST proves the API is reachable. Refresh so useApi clears a
      // lingering `error` (the UpdatesPaused banner from a prior outage) and re-
      // syncs `data`; correctness of a future rollback doesn't depend on this GET
      // succeeding, since `committed` is already updated from the POST response.
      refresh();
    } catch (e) {
      setToast(e instanceof Error ? e.message : String(e));
      // Roll the affected control straight back to the last COMMITTED server
      // value. Don't rely on refresh() for this: during a sustained outage its
      // GET /api/knobs also fails, so useApi keeps the same `data` reference and
      // the `[data]` effect never re-runs to reset `snap` — the optimistic
      // slider value would otherwise stick on screen with no indicator.
      if (committed) setLocal(key, committed[key]);
      refresh(); // still adopt fresh server truth when the API is reachable
    }
  }

  // local (non-persisting) update so sliders drag smoothly before commit
  function setLocal(key: keyof Snapshot, value: KnobValue) {
    setSnap((s) => (s ? { ...s, [key]: value } : s));
  }

  const [batchLo, batchHi] = meta.classify_batch_bounds;
  const [fanLo, fanHi] = meta.classify_fanout_bounds;
  const [perTickLo, perTickHi] = meta.enrich_per_tick_limit_bounds;

  return (
    <>
      {error && <UpdatesPaused msg={error} />}
      <Stack direction="row" spacing={2} alignItems="baseline" sx={{ mt: 1 }}>
        <SectionTitle>Runtime knobs</SectionTitle>
        {meta.taxonomy_version && (
          <Chip size="small" variant="outlined" label={`taxonomy ${meta.taxonomy_version}`} />
        )}
      </Stack>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Edits persist immediately to the meta table — the next tick reads them.
      </Typography>

      <Box
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
          gap: 2,
        }}
      >
        <Card>
          <CardContent>
            <Typography variant="subtitle1" gutterBottom>
              Classify
            </Typography>
            <Labeled label="Engine">
              <TextField
                select
                size="small"
                fullWidth
                value={snap.classify_engine}
                onChange={(e) => save("classify_engine", e.target.value)}
              >
                {meta.engines.map((eng) => (
                  <MenuItem key={eng} value={eng}>
                    {eng}
                  </MenuItem>
                ))}
              </TextField>
            </Labeled>
            <Labeled label="Model (Claude tier — used when engine is claude-code)">
              <TextField
                select
                size="small"
                fullWidth
                disabled={snap.classify_engine !== "claude-code"}
                value={snap.classify_model}
                onChange={(e) => save("classify_model", e.target.value)}
              >
                {meta.models.map((m) => (
                  <MenuItem key={m} value={m}>
                    {m}
                  </MenuItem>
                ))}
              </TextField>
            </Labeled>
            <Labeled label="Open-model tag (Ollama — used by the ollama/opencode engines)">
              <TextField
                size="small"
                fullWidth
                value={snap.opencode_model}
                onChange={(e) => setLocal("opencode_model", e.target.value)}
                onBlur={() => {
                  if (committed && snap.opencode_model !== committed.opencode_model) {
                    save("opencode_model", snap.opencode_model);
                  }
                }}
                onKeyDown={(e) => {
                  // MUI forwards unclaimed handler props like onKeyDown to the
                  // TextField's root FormControl div, not the native input, so
                  // e.currentTarget is the wrong node to blur — e.target is
                  // always the actual input the keydown originated on.
                  if (e.key === "Enter") (e.target as HTMLInputElement).blur();
                }}
                helperText="e.g. qwen3:32b — must be pulled locally (ollama list)"
              />
            </Labeled>
            <Labeled label={`Batch size (jobs per sub-agent) — ${snap.classify_batch_size}`}>
              <Slider
                value={snap.classify_batch_size}
                min={batchLo}
                max={batchHi}
                step={1}
                marks
                valueLabelDisplay="auto"
                onChange={(_, v) => setLocal("classify_batch_size", v as number)}
                onChangeCommitted={(_, v) => save("classify_batch_size", v as number)}
              />
            </Labeled>
            <Labeled label={`Fan-out (parallel agents per wave) — ${snap.classify_fan_out}`}>
              <Slider
                value={snap.classify_fan_out}
                min={fanLo}
                max={fanHi}
                step={1}
                valueLabelDisplay="auto"
                onChange={(_, v) => setLocal("classify_fan_out", v as number)}
                onChangeCommitted={(_, v) => save("classify_fan_out", v as number)}
              />
            </Labeled>
            <Labeled
              label={`Per-tick row limit (shared by classify+judge on ollama/opencode) — ${snap.enrich_per_tick_limit}`}
            >
              <Slider
                value={snap.enrich_per_tick_limit}
                min={perTickLo}
                max={perTickHi}
                step={1}
                valueLabelDisplay="auto"
                onChange={(_, v) => setLocal("enrich_per_tick_limit", v as number)}
                onChangeCommitted={(_, v) => save("enrich_per_tick_limit", v as number)}
              />
            </Labeled>
          </CardContent>
        </Card>

        <Card>
          <CardContent>
            <Typography variant="subtitle1" gutterBottom>
              Judge
            </Typography>
            <Labeled label="Enabled">
              <FormControlLabel
                control={
                  <Switch
                    checked={snap.judge_enabled}
                    onChange={(e) => save("judge_enabled", e.target.checked)}
                  />
                }
                label={snap.judge_enabled ? "on" : "off"}
              />
            </Labeled>
            <Labeled label="Engine">
              <TextField
                select
                size="small"
                fullWidth
                value={snap.judge_engine}
                onChange={(e) => save("judge_engine", e.target.value)}
              >
                {meta.engines.map((eng) => (
                  <MenuItem key={eng} value={eng}>
                    {eng}
                  </MenuItem>
                ))}
              </TextField>
            </Labeled>
            <Labeled label="Model (Claude tier — used when engine is claude-code)">
              <TextField
                select
                size="small"
                fullWidth
                disabled={snap.judge_engine !== "claude-code"}
                value={snap.judge_model}
                onChange={(e) => save("judge_model", e.target.value)}
              >
                {meta.models.map((m) => (
                  <MenuItem key={m} value={m}>
                    {m}
                  </MenuItem>
                ))}
              </TextField>
            </Labeled>
            <Labeled label="Scope">
              <TextField
                select
                size="small"
                fullWidth
                value={snap.judge_scope}
                onChange={(e) => save("judge_scope", e.target.value)}
              >
                {meta.judge_scopes.map((s) => (
                  <MenuItem key={s} value={s}>
                    {s}
                  </MenuItem>
                ))}
              </TextField>
            </Labeled>
            <Labeled label={`Confidence ceiling — ${snap.judge_confidence_ceiling.toFixed(2)}`}>
              <Slider
                value={snap.judge_confidence_ceiling}
                min={0}
                max={1}
                step={0.05}
                valueLabelDisplay="auto"
                onChange={(_, v) => setLocal("judge_confidence_ceiling", v as number)}
                onChangeCommitted={(_, v) => save("judge_confidence_ceiling", v as number)}
              />
            </Labeled>
            <Labeled label={`Human floor — ${snap.judge_human_floor.toFixed(2)}`}>
              <Slider
                value={snap.judge_human_floor}
                min={0}
                max={1}
                step={0.05}
                valueLabelDisplay="auto"
                onChange={(_, v) => setLocal("judge_human_floor", v as number)}
                onChangeCommitted={(_, v) => save("judge_human_floor", v as number)}
              />
            </Labeled>
          </CardContent>
        </Card>
      </Box>

      <Snackbar
        open={toast != null}
        autoHideDuration={5000}
        onClose={() => setToast(null)}
        message={toast ? `Rejected: ${toast}` : ""}
      />
    </>
  );
}
