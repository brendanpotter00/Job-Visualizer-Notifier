import {
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Checkbox,
  ListItemText,
  Box,
  Chip,
  Tooltip,
  IconButton,
  SelectChangeEvent,
} from '@mui/material';
import ClearIcon from '@mui/icons-material/Clear';
import { ROLE_TAG_GROUPS, type RoleTagGroup } from '../../../constants/tags.ts';

export interface RoleTagGroupFilterProps {
  /** Currently active role group IDs */
  activeGroups: string[];
  /** Called when a role group is toggled */
  onToggle: (groupId: string) => void;
  /** Called when all role groups are cleared */
  onClear: () => void;
  /** Minimum width for the select */
  minWidth?: number;
  /** Size variant */
  size?: 'small' | 'medium';
}

/**
 * Dropdown filter for toggling predefined role tag groups.
 * Each group contains a set of tags that are added/removed together.
 *
 * Groups include:
 * - Exclude Managers: Hide leadership roles
 * - Senior+ Only: Show senior, staff, principal roles
 * - Entry Level Only: Show junior/intern roles
 * - Exclude Entry Level: Hide junior/intern roles
 * - Exclude Contract: Hide contract/temporary roles
 */
export function RoleTagGroupFilter({
  activeGroups,
  onToggle,
  onClear,
  minWidth = 200,
  size = 'small',
}: RoleTagGroupFilterProps) {
  const handleChange = (event: SelectChangeEvent<string[]>) => {
    const value = event.target.value;
    // MUI Select with multiple returns string[] or string
    const newValues = typeof value === 'string' ? value.split(',') : value;

    // Find which groups were toggled
    const currentSet = new Set(activeGroups);
    const newSet = new Set(newValues);

    // Handle additions
    for (const groupId of newValues) {
      if (!currentSet.has(groupId)) {
        onToggle(groupId);
      }
    }

    // Handle removals
    for (const groupId of activeGroups) {
      if (!newSet.has(groupId)) {
        onToggle(groupId);
      }
    }
  };

  const getGroupById = (id: string): RoleTagGroup | undefined => {
    return ROLE_TAG_GROUPS.find((g) => g.id === id);
  };

  const getModeColor = (mode: 'include' | 'exclude'): 'success' | 'error' => {
    return mode === 'include' ? 'success' : 'error';
  };

  return (
    <FormControl size={size} sx={{ minWidth }}>
      <InputLabel id="role-filter-label">Role Filters</InputLabel>
      <Select
        labelId="role-filter-label"
        id="role-filter-select"
        multiple
        value={activeGroups}
        onChange={handleChange}
        label="Role Filters"
        renderValue={(selected) => (
          <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5 }}>
            {selected.map((groupId) => {
              const group = getGroupById(groupId);
              if (!group) return null;
              return (
                <Chip
                  key={groupId}
                  label={group.label}
                  size="small"
                  color={getModeColor(group.mode)}
                  variant="outlined"
                />
              );
            })}
          </Box>
        )}
        endAdornment={
          activeGroups.length > 0 ? (
            <IconButton
              size="small"
              onClick={(e) => {
                e.stopPropagation();
                onClear();
              }}
              sx={{ mr: 2 }}
            >
              <ClearIcon fontSize="small" />
            </IconButton>
          ) : null
        }
      >
        {ROLE_TAG_GROUPS.map((group) => (
          <MenuItem key={group.id} value={group.id}>
            <Checkbox checked={activeGroups.includes(group.id)} />
            <Tooltip title={group.description} placement="right" arrow>
              <ListItemText
                primary={group.label}
                secondary={
                  <Box component="span" sx={{ display: 'flex', alignItems: 'center', gap: 0.5 }}>
                    <Chip
                      label={group.mode === 'include' ? '+' : '-'}
                      size="small"
                      color={getModeColor(group.mode)}
                      sx={{ height: 16, fontSize: '0.65rem' }}
                    />
                    <span style={{ fontSize: '0.75rem', color: 'text.secondary' }}>
                      {group.tags.slice(0, 3).join(', ')}
                      {group.tags.length > 3 ? '...' : ''}
                    </span>
                  </Box>
                }
              />
            </Tooltip>
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
