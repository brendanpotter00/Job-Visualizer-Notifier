import Accordion from '@mui/material/Accordion';
import AccordionDetails from '@mui/material/AccordionDetails';
import AccordionSummary from '@mui/material/AccordionSummary';
import Typography from '@mui/material/Typography';
import Button from '@mui/material/Button';
import Stack from '@mui/material/Stack';
import Box from '@mui/material/Box';
import Radio from '@mui/material/Radio';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import AddIcon from '@mui/icons-material/Add';
import { KeywordListCard } from './KeywordListCard.tsx';
import { SectionSaveButton } from './SectionSaveButton.tsx';
import type { DraftKeywordList } from './keywordListDraft.ts';
import type { KeywordList } from '../../types';

export interface KeywordListsEditorProps {
  /** All cards in display order: new (unsaved) first, then user lists, builtin last. */
  lists: DraftKeywordList[];
  onAddList: () => void;
  onCardCreated: (tempId: string) => void;
  onCardCancelNew: (tempId: string) => void;
  onCardDeleted: (id: string) => void;
  /** A persisted list's contents were saved (PATCH) — surfaces the server list for live propagation. */
  onCardContentSaved: (saved: KeywordList) => void;
  /** Staged active keyword list id (null = no keyword filter). */
  activeKeywordListId: string | null;
  /** Pick the active list (or null for "No keyword filter"). */
  onActiveChange: (id: string | null) => void;
  /** Section-save state/handlers for the active-list selection. */
  activeDirty: boolean;
  activeSaving: boolean;
  activeSuccess: boolean;
  activeError: string | null;
  onSaveActive: () => void;
}

/**
 * Card listing every keyword list. Each card saves its own *contents* (per-card
 * Save / Edit). The **active** keyword list is chosen via a single-select radio
 * on each card (plus a "No keyword filter" row) — that selection is staged and
 * persisted by this section's own Save button, which applies it to all pages.
 * "Add list" prepends a new draft card at the top in edit mode.
 */
export function KeywordListsEditor({
  lists,
  onAddList,
  onCardCreated,
  onCardCancelNew,
  onCardDeleted,
  onCardContentSaved,
  activeKeywordListId,
  onActiveChange,
  activeDirty,
  activeSaving,
  activeSuccess,
  activeError,
  onSaveActive,
}: KeywordListsEditorProps) {
  return (
    <Accordion
      defaultExpanded
      disableGutters
      sx={{
        borderRadius: 1,
        '&:before': { display: 'none' },
      }}
    >
      <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ px: 4, py: 1 }}>
        <Typography variant="h6">Keyword lists</Typography>
      </AccordionSummary>
      <AccordionDetails sx={{ px: 4, pb: 4, pt: 0 }}>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
          Named sets of include/exclude keywords. Each list saves its contents on its own. Select one
          below as the active list to apply it on all pages.
        </Typography>

        <Box sx={{ mb: 2 }}>
          <Button variant="outlined" size="small" startIcon={<AddIcon />} onClick={onAddList}>
            Add list
          </Button>
        </Box>

        <Stack spacing={2}>
          {/* "No keyword filter" clears the active selection. */}
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1,
              p: 1,
              border: 1,
              borderColor: activeKeywordListId === null ? 'primary.main' : 'divider',
              borderRadius: 1,
              bgcolor: activeKeywordListId === null ? 'action.selected' : undefined,
            }}
          >
            <Radio
              size="small"
              name="active-keyword-list"
              checked={activeKeywordListId === null}
              onChange={() => onActiveChange(null)}
              inputProps={{ 'aria-label': 'No keyword filter' }}
              sx={{ p: 0.5 }}
            />
            <Typography variant="body2">No keyword filter</Typography>
          </Box>

          {lists.map((list) => (
            <KeywordListCard
              key={list.id}
              list={list}
              startInEdit={list.isNew}
              onCreated={onCardCreated}
              onCancelNew={onCardCancelNew}
              onDeleted={onCardDeleted}
              onSaved={onCardContentSaved}
              isActive={list.id === activeKeywordListId}
              selectable={!list.isNew}
              onSelectActive={() => onActiveChange(list.id)}
            />
          ))}
        </Stack>

        <SectionSaveButton
          dirty={activeDirty}
          saving={activeSaving}
          success={activeSuccess}
          error={activeError}
          onSave={onSaveActive}
          label="Save active list"
        />
      </AccordionDetails>
    </Accordion>
  );
}
