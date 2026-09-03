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
  /**
   * ⚠ WHETHER THE ADMIN ACTUALLY TOUCHED THE PICKER — not whether it rendered.
   *
   * `useState(row.subcategories ?? [])` collapses "never evaluated" (`null`)
   * and "evaluated, nothing applies" (`[]`) into the same local `[]`. Sending
   * that unconditionally would turn EVERY correction on a never-evaluated SWE
   * row — a level-only fix, say — into the terminal assertion `'{}'` +
   * `source='human'`, which permanently ejects the row from the backfill queue
   * (`apply_subcategory_result` skips `source='human'`, and `apply_result`'s
   * per-field unlock only fires while the array IS NULL). It would also count
   * that row as "subcategorized" in the 90%-reveal numerator.
   *
   * Phase 1 makes it acute: `job_subcategories` ships EMPTY, so the picker
   * below has ZERO options and an admin literally cannot express "I looked".
   *
   * Only a real interaction with `SubcategoryOrderedSelect` sets this. The
   * category-change clear below deliberately does NOT — an admin flipping the
   * category to Growth and back has not decided anything about specialties.
   */
  const [subcategoriesTouched, setSubcategoriesTouched] = useState(false);
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

  /**
   * ⚠ THE KEY IS OMITTED UNLESS WE HAVE SOMETHING TO ASSERT.
   *
   * Omitting means "leave whatever is stored alone" (the backend's UNTOUCHED
   * row); sending `[]` is the INSTRUCTION "evaluated, nothing applies", which
   * is terminal and irreversible except through Re-enrich. So we send only
   * when one of two things is true:
   *   - the admin touched the picker — an explicit decision, including
   *     clearing an existing selection to `[]`; or
   *   - the row already carried an evaluated array, so re-asserting what is
   *     on screen loses nothing.
   * A non-SWE category never sends the key at all — the backend forces `'{}'`
   * from the category itself.
   */
  const sendSubcategories = isSwe && (row.subcategories !== null || subcategoriesTouched);

  const handleSave = async () => {
    const result = await correct({
      sourceId: row.sourceId,
      jobListingId: row.jobListingId,
      body: {
        category: category ?? null,
        level: level ?? null,
        tags,
        note: note.trim() || null,
        ...(sendSubcategories ? { subcategories } : {}),
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
            onChange={(next) => {
              setSubcategoriesTouched(true);
              setSubcategories(next);
            }}
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
