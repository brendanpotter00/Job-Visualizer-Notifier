import { useState } from 'react';
import {
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormControlLabel,
  Switch,
  Stack,
  TextField,
  Autocomplete,
  Chip,
} from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import {
  setListTimeWindow,
  addListLocation,
  removeListLocation,
  addListDepartment,
  removeListDepartment,
  addListRoleCategory,
  removeListRoleCategory,
  addSearchTag,
  removeSearchTag,
  toggleListSoftwareOnly,
} from '../../features/filters/filtersSlice';
import {
  selectListFilters,
  selectAvailableLocations,
  selectAvailableDepartments,
} from '../../features/filters/filtersSelectors';
import type { TimeWindow, SoftwareRoleCategory } from '../../types';

const TIME_WINDOWS: { value: TimeWindow; label: string }[] = [
  { value: '30m', label: '30 minutes' },
  { value: '1h', label: '1 hour' },
  { value: '3h', label: '3 hours' },
  { value: '6h', label: '6 hours' },
  { value: '12h', label: '12 hours' },
  { value: '24h', label: '24 hours' },
  { value: '3d', label: '3 days' },
  { value: '7d', label: '7 days' },
  { value: '14d', label: '14 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: '180d', label: '6 months' },
  { value: '1y', label: '1 year' },
  { value: '2y', label: '2 years' },
];

const ROLE_CATEGORIES: { value: SoftwareRoleCategory; label: string }[] = [
  { value: 'frontend', label: 'Frontend' },
  { value: 'backend', label: 'Backend' },
  { value: 'fullstack', label: 'Full Stack' },
  { value: 'mobile', label: 'Mobile' },
  { value: 'data', label: 'Data' },
  { value: 'ml', label: 'ML/AI' },
  { value: 'devops', label: 'DevOps' },
  { value: 'platform', label: 'Platform' },
  { value: 'qa', label: 'QA' },
  { value: 'security', label: 'Security' },
];

/**
 * Filter controls for the job list
 */
export function ListFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector(selectListFilters);
  const availableLocations = useAppSelector(selectAvailableLocations);
  const availableDepartments = useAppSelector(selectAvailableDepartments);
  const [inputValue, setInputValue] = useState('');

  return (
    <Box sx={{ mb: 3 }}>
      <Stack spacing={2}>
        <Autocomplete
          multiple
          freeSolo
          size="small"
          options={[]}
          value={filters.searchQuery || []}
          inputValue={inputValue}
          onInputChange={(_, newValue) => setInputValue(newValue)}
          onChange={(_, newValue) => {
            // Handle chip removal via the X button
            if (Array.isArray(newValue)) {
              const removedTags = (filters.searchQuery || []).filter(
                tag => !newValue.includes(tag)
              );
              removedTags.forEach(tag => dispatch(removeSearchTag(tag)));
            }
          }}
          renderValue={(value, getItemProps) =>
            value.map((option, index) => {
              const { key, ...itemProps } = getItemProps({ index });
              return (
                <Chip
                  key={key}
                  label={option}
                  size="small"
                  {...itemProps}
                />
              );
            })
          }
          renderInput={(params) => (
            <TextField
              {...params}
              placeholder={
                filters.searchQuery && filters.searchQuery.length > 0
                  ? 'Add another tag...'
                  : 'Type to add search tags (e.g., software, data, backend)...'
              }
            />
          )}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && inputValue.trim()) {
              event.preventDefault();
              dispatch(addSearchTag(inputValue.trim()));
              setInputValue('');
            }
          }}
          fullWidth
        />

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Time Window</InputLabel>
            <Select
              value={filters.timeWindow}
              label="Time Window"
              onChange={(e) => dispatch(setListTimeWindow(e.target.value as TimeWindow))}
            >
              {TIME_WINDOWS.map((tw) => (
                <MenuItem key={tw.value} value={tw.value}>
                  {tw.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <Autocomplete
            multiple
            size="small"
            options={ROLE_CATEGORIES.map(cat => cat.value)}
            value={filters.roleCategory || []}
            onChange={(_, newValue) => {
              // Handle chip removal
              if (Array.isArray(newValue)) {
                const removedCats = (filters.roleCategory || []).filter(
                  cat => !newValue.includes(cat)
                );
                removedCats.forEach(cat => dispatch(removeListRoleCategory(cat)));

                // Handle chip addition
                const addedCats = newValue.filter(
                  cat => !(filters.roleCategory || []).includes(cat)
                );
                addedCats.forEach(cat => dispatch(addListRoleCategory(cat)));
              }
            }}
            renderValue={(value, getItemProps) =>
              value.map((option, index) => {
                const { key, ...itemProps } = getItemProps({ index });
                return (
                  <Chip
                    key={key}
                    label={ROLE_CATEGORIES.find(c => c.value === option)?.label || option}
                    size="small"
                    {...itemProps}
                  />
                );
              })
            }
            getOptionLabel={(option) =>
              ROLE_CATEGORIES.find(c => c.value === option)?.label || option
            }
            renderInput={(params) => (
              <TextField
                {...params}
                label="Role Category"
                placeholder="Select categories..."
              />
            )}
            sx={{ minWidth: 200 }}
          />

          {availableLocations.length > 0 && (
            <Autocomplete
              multiple
              size="small"
              options={availableLocations}
              value={filters.location || []}
              onChange={(_, newValue) => {
                // Handle chip removal
                if (Array.isArray(newValue)) {
                  const removedLocs = (filters.location || []).filter(
                    loc => !newValue.includes(loc)
                  );
                  removedLocs.forEach(loc => dispatch(removeListLocation(loc)));

                  // Handle chip addition
                  const addedLocs = newValue.filter(
                    loc => !(filters.location || []).includes(loc)
                  );
                  addedLocs.forEach(loc => dispatch(addListLocation(loc)));
                }
              }}
              renderValue={(value, getItemProps) =>
                value.map((option, index) => {
                  const { key, ...itemProps } = getItemProps({ index });
                  return (
                    <Chip
                      key={key}
                      label={option}
                      size="small"
                      {...itemProps}
                    />
                  );
                })
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Location"
                  placeholder="Select locations..."
                />
              )}
              sx={{ minWidth: 200 }}
            />
          )}

          {availableDepartments.length > 0 && (
            <Autocomplete
              multiple
              size="small"
              options={availableDepartments}
              value={filters.department || []}
              onChange={(_, newValue) => {
                // Handle chip removal
                if (Array.isArray(newValue)) {
                  const removedDepts = (filters.department || []).filter(
                    dept => !newValue.includes(dept)
                  );
                  removedDepts.forEach(dept => dispatch(removeListDepartment(dept)));

                  // Handle chip addition
                  const addedDepts = newValue.filter(
                    dept => !(filters.department || []).includes(dept)
                  );
                  addedDepts.forEach(dept => dispatch(addListDepartment(dept)));
                }
              }}
              renderValue={(value, getItemProps) =>
                value.map((option, index) => {
                  const { key, ...itemProps } = getItemProps({ index });
                  return (
                    <Chip
                      key={key}
                      label={option}
                      size="small"
                      {...itemProps}
                    />
                  );
                })
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Department"
                  placeholder="Select departments..."
                />
              )}
              sx={{ minWidth: 200 }}
            />
          )}
        </Stack>

        <Stack direction="row" spacing={2} alignItems="center">
          <FormControlLabel
            control={
              <Switch checked={filters.softwareOnly} onChange={() => dispatch(toggleListSoftwareOnly())} />
            }
            label="Software roles only"
          />
        </Stack>
      </Stack>
    </Box>
  );
}
