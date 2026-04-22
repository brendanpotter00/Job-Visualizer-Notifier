import { useMemo, useState } from 'react';
import { Box, Card, CardContent, Chip, Link, Stack, Typography } from '@mui/material';
import type { SxProps, Theme } from '@mui/material';
import { format, parseISO } from 'date-fns';
import { Link as RouterLink } from 'react-router-dom';
import {
  CHANGELOG,
  CHANGELOG_TAGS,
  type ChangelogEntry,
  type ChangelogTag,
} from '../../config/changelog';
import { MultiSelectAutocomplete } from '../../components/shared/filters/MultiSelectAutocomplete';

const BLACK_CHIP_SX: SxProps<Theme> = {
  bgcolor: 'common.black',
  color: 'common.white',
};

const TAG_SX: Record<ChangelogTag, SxProps<Theme>> = {
  feature: { bgcolor: 'success.main', color: 'success.contrastText' },
  improvement: BLACK_CHIP_SX,
  technical: BLACK_CHIP_SX,
  'new-companies': BLACK_CHIP_SX,
};

function isChangelogTag(value: string): value is ChangelogTag {
  return (CHANGELOG_TAGS as readonly string[]).includes(value);
}

export function ChangelogColumn() {
  const [selected, setSelected] = useState<ChangelogTag[]>([]);

  const visibleEntries: ChangelogEntry[] = useMemo(() => {
    const base =
      selected.length === 0
        ? [...CHANGELOG]
        : CHANGELOG.filter((entry) =>
            entry.tags.some((tag) => selected.includes(tag))
          );
    return base.sort((a, b) => Date.parse(b.date) - Date.parse(a.date));
  }, [selected]);

  const handleAdd = (value: string) => {
    if (isChangelogTag(value)) {
      setSelected((prev) => (prev.includes(value) ? prev : [...prev, value]));
    }
  };

  const handleRemove = (value: string) => {
    setSelected((prev) => prev.filter((tag) => tag !== value));
  };

  return (
    <Stack spacing={2}>
      <Typography variant="h5" component="h2">
        Changelog
      </Typography>
      <MultiSelectAutocomplete
        label="Tags"
        options={[...CHANGELOG_TAGS]}
        value={selected}
        onAdd={handleAdd}
        onRemove={handleRemove}
        placeholder="Filter by tag..."
      />
      {visibleEntries.length === 0 ? (
        <Typography variant="body2" color="text.secondary">
          No changelog entries match the selected tags.
        </Typography>
      ) : (
        <Stack spacing={2}>
          {visibleEntries.map((entry) => (
            <Card key={entry.id} variant="outlined">
              <CardContent>
                <Stack
                  direction="row"
                  justifyContent="space-between"
                  alignItems="flex-start"
                  spacing={2}
                  sx={{ mb: 1 }}
                >
                  <Typography variant="h6" component="h3">
                    {entry.title}
                  </Typography>
                  <Typography
                    variant="caption"
                    color="text.secondary"
                    sx={{ whiteSpace: 'nowrap', pt: 0.5 }}
                  >
                    {format(parseISO(entry.date), 'MMM d, yyyy')}
                  </Typography>
                </Stack>
                <Typography
                  variant="body2"
                  color="text.secondary"
                  sx={{ mb: entry.link ? 1 : 2 }}
                >
                  {entry.description}
                </Typography>
                {entry.link && (
                  <Typography variant="body2" sx={{ mb: 2 }}>
                    <Link component={RouterLink} to={entry.link.to}>
                      {entry.link.label}
                    </Link>
                  </Typography>
                )}
                <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
                  {entry.tags.map((tag) => (
                    <Chip
                      key={tag}
                      label={tag}
                      size="small"
                      sx={TAG_SX[tag]}
                    />
                  ))}
                </Box>
              </CardContent>
            </Card>
          ))}
        </Stack>
      )}
    </Stack>
  );
}
