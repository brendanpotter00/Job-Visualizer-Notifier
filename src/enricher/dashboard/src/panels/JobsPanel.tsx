import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Box,
  Button,
  Chip,
  Drawer,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import RefreshIcon from "@mui/icons-material/Refresh";
import {
  DataGrid,
  type GridColDef,
  type GridPaginationModel,
  type GridRowParams,
} from "@mui/x-data-grid";
import type { JobDetail, JobRow, JobsResponse } from "../lib/api";
import { ApiError, fetchJobDetail } from "../lib/api";
import { fmtConfidence } from "../lib/format";
import { MONO } from "../theme";
import { ErrorNote, SectionTitle } from "../components/common";

const STATES = ["", "claimed", "cleaned", "enriched", "sent", "failed"] as const;

function rowId(r: JobRow): string {
  return `${r.source_id}::${r.job_listing_id}`;
}

function JudgeCell({ row }: { row: JobRow }) {
  if (!row.judged)
    return (
      <Typography variant="body2" color="text.secondary">
        —
      </Typography>
    );
  return row.judge_pass === 1 ? (
    <Chip size="small" color="success" label="pass" />
  ) : (
    <Chip size="small" color="error" label="corrected" />
  );
}

const columns: GridColDef<JobRow>[] = [
  { field: "title", headerName: "Title", flex: 1.4, minWidth: 180 },
  { field: "company", headerName: "Company", flex: 1, minWidth: 120 },
  {
    field: "raw_location",
    headerName: "Location",
    flex: 1,
    minWidth: 120,
    valueGetter: (v) => v ?? "—",
  },
  {
    field: "status",
    headerName: "State",
    width: 110,
    renderCell: (p) => <Chip size="small" variant="outlined" label={p.value} />,
  },
  { field: "category", headerName: "Category", flex: 1, minWidth: 140, valueGetter: (v) => v ?? "—" },
  { field: "level", headerName: "Level", width: 110, valueGetter: (v) => v ?? "—" },
  {
    field: "classify_confidence",
    headerName: "Conf",
    width: 80,
    align: "right",
    headerAlign: "right",
    valueFormatter: (v) => fmtConfidence(v as number | null),
  },
  {
    field: "judge_pass",
    headerName: "Judge",
    width: 110,
    sortable: false,
    renderCell: (p) => <JudgeCell row={p.row} />,
  },
  {
    field: "needs_human",
    headerName: "Human?",
    width: 100,
    renderCell: (p) => (p.value ? <Chip size="small" color="warning" label="review" /> : null),
  },
];

export function JobsPanel() {
  const [pagination, setPagination] = useState<GridPaginationModel>({ page: 0, pageSize: 25 });
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [needsHuman, setNeedsHuman] = useState(false);
  const [rows, setRows] = useState<JobRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<JobDetail | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    const qs = new URLSearchParams({
      limit: String(pagination.pageSize),
      offset: String(pagination.page * pagination.pageSize),
    });
    if (statusFilter) qs.set("status", statusFilter);
    if (needsHuman) qs.set("needs_human", "true");
    try {
      const res = await fetch(`/api/jobs?${qs}`);
      if (!res.ok) throw new Error(`${res.status}`);
      const body = (await res.json()) as JobsResponse;
      setRows(body.jobs);
      setTotal(body.total);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, [pagination.page, pagination.pageSize, statusFilter, needsHuman]);

  useEffect(() => {
    load();
  }, [load]);

  async function openDetail(params: GridRowParams<JobRow>) {
    try {
      setDetail(await fetchJobDetail(params.row.source_id, params.row.job_listing_id));
    } catch (e) {
      // A 404 means the row vanished between list and detail — safe to ignore.
      // Anything else (network drop, 500) is a real failure: surface it rather
      // than turning the click into a silent no-op.
      if (e instanceof ApiError && e.status === 404) return;
      setError(e instanceof Error ? e.message : String(e));
    }
  }

  const detailEntries = useMemo(
    () => (detail ? Object.entries(detail) : []),
    [detail],
  );

  return (
    <>
      <SectionTitle>Jobs</SectionTitle>
      <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
        <TextField
          select
          size="small"
          label="State"
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value);
            setPagination((p) => ({ ...p, page: 0 }));
          }}
          sx={{ minWidth: 150 }}
        >
          {STATES.map((s) => (
            <MenuItem key={s || "all"} value={s}>
              {s || "all states"}
            </MenuItem>
          ))}
        </TextField>
        <FormControlLabel
          control={
            <Switch
              checked={needsHuman}
              onChange={(e) => {
                setNeedsHuman(e.target.checked);
                setPagination((p) => ({ ...p, page: 0 }));
              }}
            />
          }
          label="needs human only"
        />
        <Box sx={{ flexGrow: 1 }} />
        <Button startIcon={<RefreshIcon />} onClick={load} size="small">
          Refresh
        </Button>
      </Stack>

      {error && <ErrorNote msg={error} />}

      <DataGrid<JobRow>
        rows={rows}
        columns={columns}
        getRowId={rowId}
        rowCount={total}
        loading={loading}
        paginationMode="server"
        paginationModel={pagination}
        onPaginationModelChange={setPagination}
        pageSizeOptions={[10, 25, 50]}
        disableColumnFilter
        disableRowSelectionOnClick
        onRowClick={openDetail}
        autoHeight
        sx={{ "& .MuiDataGrid-row": { cursor: "pointer" } }}
      />

      <Drawer anchor="right" open={detail != null} onClose={() => setDetail(null)}>
        <Box sx={{ width: 460, maxWidth: "90vw", p: 3 }}>
          <Typography variant="h6" gutterBottom>
            Job detail
          </Typography>
          <Stack spacing={1.25}>
            {detailEntries.map(([k, v]) => (
              <Box key={k}>
                <Typography variant="caption" color="text.secondary">
                  {k}
                </Typography>
                <Typography
                  variant="body2"
                  sx={{ fontFamily: MONO, whiteSpace: "pre-wrap", wordBreak: "break-word" }}
                >
                  {v == null ? "—" : String(v)}
                </Typography>
              </Box>
            ))}
          </Stack>
        </Box>
      </Drawer>
    </>
  );
}
