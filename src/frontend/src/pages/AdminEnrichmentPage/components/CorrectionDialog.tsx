import { useState } from 'react';
import Alert from '@mui/material/Alert';
import Autocomplete from '@mui/material/Autocomplete';
import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import Chip from '@mui/material/Chip';
import Dialog from '@mui/material/Dialog';
import DialogActions from '@mui/material/DialogActions';
import DialogContent from '@mui/material/DialogContent';
import DialogTitle from '@mui/material/DialogTitle';
import TextField from '@mui/material/TextField';
import Typography from '@mui/material/Typography';
import {
  useCorrectEnrichmentMutation,
  type EnrichmentCorrectionTarget,
} from '../../../features/admin/adminApi';
import { useGetFacetsQuery } from '../../../features/jobs/jobsApi';
import { FALLBACK_CATEGORIES, FALLBACK_LEVELS } from '../../../constants/enrichment';
import { FacetSelect } from '../../../components/shared/filters/FacetSelect';
import { SubcategoryOrderedSelect } from './SubcategoryOrderedSelect';
import { extractErrorMessage } from '../../../lib/errors';

/** The one category that carries subcategories. Mirrors the backend constant. */
const SUBCATEGORY_PARENT = 'software_engineering';

interface CorrectionDialogProps {
  open: boolean;
  row: EnrichmentCorrectionTarget | null;
  onClose: () => void;
}

/**
 * Human correction editor for one needs-human row (the AliasEditDialog analog).
 * Pre-fills the agent's proposal; saving publishes the corrected facets, clears
 * the flag, and locks the row against automated overwrite. The judge's notes
 * and the classifier's reasoning are shown IN the editor — the human corrects
 * with the agent's evidence in view, not from the title alone.
 *
 * The form lives in an inner component keyed by the row identity, so switching
 * rows remounts it and `useState` initializers re-seed from the new row — no
 * setState-in-effect re-seeding (lint rule).
 */
export function CorrectionDialog({ open, row, onClose }: CorrectionDialogProps) {
  if (!row) return null;
  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <CorrectionForm key={`${row.sourceId}:${row.jobListingId}`} row={row} onClose={onClose} />
    </Dialog>
  );
}

function CorrectionForm({ row, onClose }: { row: EnrichmentCorrectionTarget; onClose: () => void }) {
  const { data: facets } = useGetFacetsQuery();
  const [correct, { isLoading, error }] = useCorrectEnrichmentMutation();

  const [category, setCategory] = useState<string | undefined>(row.category ?? undefined);
  const [level, setLevel] = useState<string | undefined>(row.level ?? undefined);
  const [subcategories, setSubcategories] = useState<string[]>(row.subcategories ?? []);
  const [tags, setTags] = useState<string[]>(row.tags);
  const [note, setNote] = useState('');

  const isSwe = category === SUBCATEGORY_PARENT;
  // LIVE facets only — never FALLBACK_*. An admin writing a human label must not
  // be offered a slug the database will reject, nor denied one it has.
  const subcategoryOptions = facets?.subcategories ?? [];

  /**
   * Clearing on a category change happens HERE, in the handler — not in an
   * effect. A `useEffect` that reset the control's value would be the
   * setState-in-effect pattern the component's docstring forbids, and it would
   * also run a render late, briefly submitting a stale selection.
   */
  const handleCategoryChange = (next: string | undefined) => {
    setCategory(next);
    if (next !== SUBCATEGORY_PARENT) setSubcategories([]);
  };

  const handleSave = async () => {
    const result = await correct({
      sourceId: row.sourceId,
      jobListingId: row.jobListingId,
      body: {
        category: category ?? null,
        level: level ?? null,
        tags,
        note: note.trim() || null,
        // ⚠ A non-SWE row OMITS THE KEY ENTIRELY. Sending `[]` would be an
        // instruction ("evaluated, nothing applies"); omitting it means "leave
        // whatever is stored alone", which is what the backend's tri-state
        // needs to hear from a dialog that never showed the control.
        ...(isSwe ? { subcategories } : {}),
      },
    });
    if (!('error' in result)) {
      onClose();
    }
  };

  return (
    <>
      <DialogTitle>
        Correct labels
        <Typography variant="body2" color="text.secondary">
          {row.title ?? row.jobListingId} · {row.company}
        </Typography>
      </DialogTitle>
      <DialogContent>
        {(row.judgeNotes || row.classifyReasoning) && (
          <Box sx={{ mb: 2 }}>
            {row.judgeNotes && (
              <Typography variant="body2" sx={{ mb: 0.5 }}>
                <strong>Judge:</strong> {row.judgeNotes}
              </Typography>
            )}
            {row.classifyReasoning && (
              <Typography variant="body2" color="text.secondary">
                <strong>Classifier:</strong> {row.classifyReasoning}
                {row.classifyConfidence != null &&
                  ` (confidence ${row.classifyConfidence.toFixed(2)})`}
              </Typography>
            )}
          </Box>
        )}
        <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap', mb: 2, mt: 1 }}>
          <FacetSelect
            label="Category"
            options={facets?.categories ?? FALLBACK_CATEGORIES}
            value={category}
            onChange={handleCategoryChange}
          />
          <FacetSelect
            label="Level"
            options={facets?.levels ?? FALLBACK_LEVELS}
            value={level}
            onChange={setLevel}
          />
        </Box>
        {isSwe && (
          <SubcategoryOrderedSelect
            options={subcategoryOptions}
            value={subcategories}
            onChange={setSubcategories}
          />
        )}
        <Autocomplete
          multiple
          freeSolo
          options={[]}
          value={tags}
          onChange={(_e, value) =>
            setTags(value.map((t) => t.toLowerCase().trim()).filter(Boolean))
          }
          renderValue={(value, getItemProps) =>
            value.map((option, index) => (
              <Chip label={option} size="small" {...getItemProps({ index })} key={option} />
            ))
          }
          renderInput={(params) => (
            <TextField {...params} label="Tags" placeholder="Type a tag and press Enter" />
          )}
          sx={{ mb: 2 }}
        />
        <TextField
          label="Correction note (optional)"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          fullWidth
          multiline
          minRows={2}
          placeholder="Why the agent's label was wrong — feeds the golden set"
        />
        {error && (
          <Alert severity="error" sx={{ mt: 2 }}>
            {extractErrorMessage(error, 'Failed to save correction')}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={handleSave} disabled={isLoading}>
          Save correction
        </Button>
      </DialogActions>
    </>
  );
}
